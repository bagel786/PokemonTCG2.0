#!/usr/bin/env python3
"""Outcome-driven schema-5 PPO with a training-only centralized critic.

Unlike the retired PPO path, the actor consumes only public schema-5 features,
the critic consumes a physically separate private simulator vector, and action
advantages may come from branching Q comparisons rather than a saturated
single-state value estimate.  Only actor weights are exportable.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import random
import sys
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from training.azure_guard import enforce_azure_workload
from training.schema5_relational import RelationalDirectPolicyNet, export_relational, load_relational
from training.train_bc import collate, move


PRIVATE_CRITIC_SIZE = 256


class CentralizedCritic(nn.Module):
    """Training-only critic; no instance of this class enters runtime packages."""

    def __init__(self) -> None:
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(PRIVATE_CRITIC_SIZE, 256), nn.ReLU(),
            nn.Linear(256, 128), nn.ReLU(), nn.Linear(128, 1),
        )

    def forward(self, private: torch.Tensor) -> torch.Tensor:
        return self.network(private).squeeze(-1)


def validate_rollout(row: dict[str, Any]) -> None:
    if int((row.get("features") or {}).get("feature_version", -1)) != 5:
        raise ValueError("outcome RL requires public schema-5 actor features")
    if "critic_features" in row.get("features", {}):
        raise ValueError("critic-only fields leaked into actor features")
    private = row.get("critic_features")
    if not isinstance(private, list) or len(private) != PRIVATE_CRITIC_SIZE:
        raise ValueError(f"critic_features must be a separate {PRIVATE_CRITIC_SIZE}-vector")
    if not all(math.isfinite(float(value)) for value in private):
        raise ValueError("non-finite critic feature")
    if float(row.get("terminal_reward", 99)) not in {-1.0, 0.0, 1.0}:
        raise ValueError("terminal reward must be win/draw/loss only")
    action = row.get("action")
    options = row["features"].get("options", [])
    if not isinstance(action, list) or not all(isinstance(index, int) and 0 <= index < len(options) for index in action):
        raise ValueError("rollout action is not a legal option-index list")
    if not math.isfinite(float(row.get("old_logprob", math.nan))):
        raise ValueError("old_logprob is missing or non-finite")
    if "action_q" in row or "expected_sarsa_q" in row:
        if not all(math.isfinite(float(row[key])) for key in ("action_q", "expected_sarsa_q")):
            raise ValueError("Q comparison is incomplete")


def iter_rows(paths: Iterable[Path]) -> Iterable[dict[str, Any]]:
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                validate_rollout(row)
                yield row


def complete_logprob(logits: torch.Tensor, counts: torch.Tensor, batch: dict, record: int, action: list[int]) -> torch.Tensor:
    start, end = batch["record_options"][record]
    local = logits[start:end]
    minimum = int(round(float(batch["global"][record, 28].item()) * 9))
    maximum = int(round(float(batch["global"][record, 29].item()) * 9))
    logprob = local.sum() * 0
    if minimum != maximum:
        logprob = logprob + F.log_softmax(counts[record, minimum:maximum + 1], dim=0)[len(action) - minimum]
    available = torch.ones(len(local), dtype=torch.bool, device=local.device)
    for index in action:
        step = local.masked_fill(~available, -torch.inf)
        logprob = logprob + F.log_softmax(step, dim=0)[index]
        available[index] = False
    return logprob


def _batch(rows: list[dict[str, Any]]) -> dict[str, Any]:
    actor_rows = [{"features": row["features"], "action": row["action"], "reward": row["terminal_reward"], "sample_weight": 1.0} for row in rows]
    result = collate(actor_rows)
    result["old_logprob"] = torch.tensor([float(row["old_logprob"]) for row in rows], dtype=torch.float32)
    result["terminal_reward"] = torch.tensor([float(row["terminal_reward"]) for row in rows], dtype=torch.float32)
    result["private"] = torch.tensor([row["critic_features"] for row in rows], dtype=torch.float32)
    result["q_advantage"] = torch.tensor([
        float(row["action_q"]) - float(row["expected_sarsa_q"])
        if "action_q" in row and "expected_sarsa_q" in row else float("nan")
        for row in rows
    ], dtype=torch.float32)
    result["director_actions"] = [row.get("director_action") for row in rows]
    result["baseline_actions"] = [row.get("baseline_action") if not bool(row.get("supported_context", True)) else None for row in rows]
    return result


def iter_batches(paths: list[Path], batch_size: int, seed: int) -> Iterable[dict[str, Any]]:
    rows = list(iter_rows(paths))
    if not rows:
        raise RuntimeError("outcome rollout stream is empty")
    random.Random(seed).shuffle(rows)
    for start in range(0, len(rows), batch_size):
        yield _batch(rows[start:start + batch_size])


def actor_loss(actor, critic, batch, clip_ratio: float, entropy_weight: float, auxiliary_weight: float) -> tuple[torch.Tensor, dict[str, float]]:
    logits, counts = actor(batch)
    logprobs = torch.stack([complete_logprob(logits, counts, batch, index, action) for index, action in enumerate(batch["record_actions"])])
    with torch.no_grad():
        values = critic(batch["private"])
        outcome_advantage = batch["terminal_reward"] - torch.tanh(values)
        q_mask = torch.isfinite(batch["q_advantage"])
        advantages = torch.where(q_mask, batch["q_advantage"], outcome_advantage)
        # Normalize by actual-order/opponent groups in the collector before
        # batching; batch normalization is a final numeric stabilizer only.
        advantages = (advantages - advantages.mean()) / (advantages.std(unbiased=False) + 1e-6)
    ratio = torch.exp(logprobs - batch["old_logprob"])
    surrogate = torch.minimum(ratio * advantages, ratio.clamp(1 - clip_ratio, 1 + clip_ratio) * advantages)
    policy = -surrogate.mean()
    entropy = -(torch.exp(logprobs).clamp_max(1) * logprobs).mean()
    auxiliary_terms = []
    for index, action in enumerate(batch["director_actions"]):
        if isinstance(action, list):
            auxiliary_terms.append(-complete_logprob(logits, counts, batch, index, action))
    for index, action in enumerate(batch["baseline_actions"]):
        if isinstance(action, list):
            auxiliary_terms.append(-complete_logprob(logits, counts, batch, index, action))
    auxiliary = torch.stack(auxiliary_terms).mean() if auxiliary_terms else policy * 0
    loss = policy - entropy_weight * entropy + auxiliary_weight * auxiliary
    approximate_kl = (((ratio - 1) - (logprobs - batch["old_logprob"]))).mean()
    return loss, {
        "policy_loss": float(policy.detach()),
        "entropy": float(entropy.detach()),
        "auxiliary_loss": float(auxiliary.detach()),
        "approximate_kl": float(approximate_kl.detach()),
        "q_fraction": float(q_mask.float().mean()),
    }


def train(args) -> dict[str, Any]:
    enforce_azure_workload(allow_local_smoke=args.allow_local_smoke, workload_size=len(args.rollouts))
    random.seed(args.seed); np.random.seed(args.seed); torch.manual_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    actor = RelationalDirectPolicyNet().to(device)
    load_relational(actor, Path(args.initial_actor))
    critic = CentralizedCritic().to(device)
    actor_optimizer = torch.optim.AdamW(actor.parameters(), lr=args.actor_lr, weight_decay=1e-5)
    critic_optimizer = torch.optim.AdamW(critic.parameters(), lr=args.critic_lr, weight_decay=1e-5)
    history = []
    hard_stopped = False
    for epoch in range(args.epochs):
        totals: dict[str, float] = {"batches": 0}
        for raw in iter_batches(list(map(Path, args.rollouts)), args.batch_size, args.seed + epoch):
            batch = move(raw, device)
            critic_logits = critic(batch["private"])
            critic_loss = F.mse_loss(torch.tanh(critic_logits), batch["terminal_reward"])
            critic_optimizer.zero_grad(set_to_none=True)
            critic_loss.backward()
            torch.nn.utils.clip_grad_norm_(critic.parameters(), 1.0)
            critic_optimizer.step()

            loss, metrics = actor_loss(actor, critic, batch, args.clip_ratio, args.entropy_weight, args.auxiliary_weight)
            if not torch.isfinite(loss):
                raise FloatingPointError("non-finite outcome-RL actor loss")
            if metrics["approximate_kl"] > args.hard_kl:
                hard_stopped = True
                break
            actor_optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(actor.parameters(), 1.0)
            actor_optimizer.step()
            totals["batches"] += 1
            totals["critic_loss"] = totals.get("critic_loss", 0.0) + float(critic_loss.detach())
            for key, value in metrics.items():
                totals[key] = totals.get(key, 0.0) + value
        count = max(1.0, totals.pop("batches"))
        record = {"epoch": epoch + 1, **{key: value / count for key, value in totals.items()}}
        history.append(record)
        if hard_stopped:
            break
    actor_path = export_relational(actor.cpu(), Path(args.output_actor))
    critic_path = Path(args.output_critic)
    critic_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": critic.cpu().state_dict(), "training_only": True, "private_size": PRIVATE_CRITIC_SIZE}, critic_path)
    manifest = {
        "status": "complete" if not hard_stopped else "hard_kl_stopped",
        "schema_version": 5,
        "terminal_reward_only": True,
        "public_actor_private_critic_separation": True,
        "public_agent_imitation": False,
        "actor": str(actor_path.resolve()),
        "critic_training_only": str(critic_path.resolve()),
        "critic_export_prohibited": True,
        "seed": args.seed,
        "history": history,
    }
    Path(args.manifest).parent.mkdir(parents=True, exist_ok=True)
    Path(args.manifest).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initial-actor", required=True)
    parser.add_argument("--rollouts", action="append", required=True)
    parser.add_argument("--output-actor", required=True)
    parser.add_argument("--output-critic", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=96)
    parser.add_argument("--actor-lr", type=float, default=5e-5)
    parser.add_argument("--critic-lr", type=float, default=2e-4)
    parser.add_argument("--clip-ratio", type=float, default=0.15)
    parser.add_argument("--entropy-weight", type=float, default=0.005)
    parser.add_argument("--auxiliary-weight", type=float, default=0.20)
    parser.add_argument("--hard-kl", type=float, default=0.03)
    parser.add_argument("--seed", type=int, default=2026080901)
    parser.add_argument("--allow-local-smoke", action="store_true")
    args = parser.parse_args()
    result = train(args)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())

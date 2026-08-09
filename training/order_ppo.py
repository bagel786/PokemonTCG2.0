#!/usr/bin/env python3
"""Strict schema-2 terminal-outcome PPO for one verified actual play order.

This intentionally does not share the schema-5 critic/Q/GAE path.  Collection
and training both call :func:`complete_action_logprob`, so behavior-likelihood
parity is a hard precondition rather than an assumption.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np
import torch
from torch.nn import functional as F

from ptcg_ai.features import MAX_SELECT_COUNT
from training.azure_guard import enforce_azure_workload
from training.train_bc import PolicyNet, collate, export_npz, load_npz_weights, move


FORBIDDEN_FIELDS = {
    "old_value", "value", "gae", "action_q", "expected_sarsa_q",
    "bench_reward", "director_action", "imitation_action", "critic_features",
}


def sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def validate_row(row: dict[str, Any], expected_order: str | None = None) -> None:
    present = FORBIDDEN_FIELDS.intersection(row)
    if present:
        raise ValueError(f"forbidden outcome-PPO fields: {sorted(present)}")
    features = row.get("features") or {}
    if int(features.get("feature_version", -1)) != 2:
        raise ValueError("order PPO requires exact schema-2 features")
    if expected_order and row.get("actual_order") != expected_order:
        raise ValueError("rollout actual order does not match requested policy")
    if row.get("actual_order") not in {"first", "second"}:
        raise ValueError("actual_order must be latched from firstPlayer")
    if int(row.get("physical_seat", -1)) not in {0, 1}:
        raise ValueError("physical_seat is missing")
    if float(row.get("terminal_reward", 99)) not in {-1.0, 0.0, 1.0}:
        raise ValueError("terminal reward must be -1, 0, or +1")
    if not math.isfinite(float(row.get("old_logprob", math.nan))):
        raise ValueError("complete-action behavior log probability is invalid")
    if abs(float(row.get("behavior_temperature", 0.0)) - 0.70) > 1e-12:
        raise ValueError("behavior temperature must be exactly 0.70")
    if not row.get("policy_hash") or not row.get("chooser") or "choice" not in row:
        raise ValueError("policy provenance/chooser/choice is incomplete")
    if list(row.get("action", [])) != list(row.get("choice", [])):
        raise ValueError("action and recorded choice disagree")
    if row.get("forced_order_decision") or row.get("shield_modified") or row.get("postprocessed"):
        if row.get("trainable", True):
            raise ValueError("postprocessed decisions must be excluded from PPO")


def _limits(batch: dict[str, Any], index: int) -> tuple[int, int]:
    minimum = int(round(float(batch["global"][index, 28].item()) * MAX_SELECT_COUNT))
    maximum = int(round(float(batch["global"][index, 29].item()) * MAX_SELECT_COUNT))
    return minimum, maximum


def complete_action_logprob(
    logits: torch.Tensor,
    count_logits: torch.Tensor,
    batch: dict[str, Any],
    index: int,
    action: list[int],
    temperature: torch.Tensor | float,
) -> torch.Tensor:
    """Probability of count plus ordered without-replacement option choices."""
    start, end = batch["record_options"][index]
    divisor = torch.as_tensor(temperature, dtype=logits.dtype, device=logits.device).clamp_min(1e-6)
    local = logits[start:end] / divisor
    minimum, maximum = _limits(batch, index)
    if not (minimum <= len(action) <= maximum):
        raise ValueError("recorded action count is outside the encoded legal range")
    result = local.sum() * 0.0
    if minimum != maximum:
        valid_counts = count_logits[index, minimum:maximum + 1] / divisor
        result = result + F.log_softmax(valid_counts, dim=0)[len(action) - minimum]
    available = torch.ones(len(local), dtype=torch.bool, device=local.device)
    for selected in action:
        if selected < 0 or selected >= len(local) or not bool(available[selected]):
            raise ValueError("recorded complete action is illegal or contains a duplicate")
        result = result + F.log_softmax(local.masked_fill(~available, -torch.inf), dim=0)[selected]
        available = available.clone()
        available[selected] = False
    return result


def _actor_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "features": row["features"],
        "action": list(map(int, row["action"])),
        "reward": float(row["terminal_reward"]),
        "sample_weight": 1.0,
    }


def build_batch(rows: list[dict[str, Any]]) -> dict[str, Any]:
    batch = collate([_actor_row(row) for row in rows])
    batch["old_logprob"] = torch.tensor([float(row["old_logprob"]) for row in rows], dtype=torch.float32)
    batch["advantage"] = torch.tensor([float(row["advantage"]) for row in rows], dtype=torch.float32)
    batch["temperature"] = torch.tensor([float(row["behavior_temperature"]) for row in rows], dtype=torch.float32)
    return batch


def load_rows(paths: Iterable[Path], expected_order: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    policy_hashes: set[str] = set()
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                validate_row(row, expected_order)
                policy_hashes.add(str(row["policy_hash"]).upper())
                if bool(row.get("trainable", True)):
                    rows.append(row)
    if not rows:
        raise RuntimeError("no trainable outcome-PPO decisions")
    if len(policy_hashes) != 1:
        raise ValueError(f"rollouts contain multiple behavior policies: {sorted(policy_hashes)}")
    return rows


def assign_cross_fitted_advantages(rows: list[dict[str, Any]], folds: int = 5) -> dict[str, Any]:
    """Attach episode-separated, opponent-specific terminal-return baselines."""
    episode_returns: dict[tuple[str, str], float] = {}
    for row in rows:
        key = (str(row["opponent_id"]), str(row["episode_id"]))
        reward = float(row["terminal_reward"])
        if key in episode_returns and episode_returns[key] != reward:
            raise ValueError("an episode contains inconsistent terminal returns")
        episode_returns[key] = reward
    by_opponent_fold: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    episode_fold: dict[tuple[str, str], int] = {}
    for key, reward in episode_returns.items():
        opponent, episode = key
        fold = int(hashlib.sha256(episode.encode()).hexdigest()[:8], 16) % folds
        episode_fold[key] = fold
        by_opponent_fold[opponent][fold].append(reward)
    baselines: dict[tuple[str, int], float] = {}
    for opponent, grouped in by_opponent_fold.items():
        if set(grouped) != set(range(folds)):
            raise ValueError(f"opponent {opponent} does not cover all {folds} episode folds")
        for heldout in range(folds):
            training = [value for fold, values in grouped.items() if fold != heldout for value in values]
            if not training:
                raise ValueError("cross-fitted baseline has no training episodes")
            baselines[(opponent, heldout)] = float(np.mean(training))
    for row in rows:
        key = (str(row["opponent_id"]), str(row["episode_id"]))
        baseline = baselines[(key[0], episode_fold[key])]
        row["baseline"] = baseline
        row["advantage"] = float(row["terminal_reward"]) - baseline
    return {
        "folds": folds,
        "episodes": len(episode_returns),
        "opponents": sorted(by_opponent_fold),
        "baseline_range": [min(baselines.values()), max(baselines.values())],
    }


@torch.no_grad()
def likelihood_parity(model: PolicyNet, rows: list[dict[str, Any]], batch_size: int, device: torch.device) -> dict[str, float]:
    ratios: list[torch.Tensor] = []
    disagreements: list[torch.Tensor] = []
    model.eval()
    for start in range(0, len(rows), batch_size):
        batch = move(build_batch(rows[start:start + batch_size]), device)
        logits, counts, _ = model(batch)
        current = torch.stack([
            complete_action_logprob(logits, counts, batch, index, action, batch["temperature"][index])
            for index, action in enumerate(batch["record_actions"])
        ])
        difference = current - batch["old_logprob"]
        ratios.append(torch.exp(difference).cpu())
        disagreements.append(difference.abs().cpu())
    ratio = torch.cat(ratios)
    disagreement = torch.cat(disagreements)
    return {
        "initial_ratio": float(ratio.mean()),
        "max_logprob_disagreement": float(disagreement.max()),
        "records": int(len(ratio)),
    }


def train(args: argparse.Namespace) -> dict[str, Any]:
    enforce_azure_workload(allow_local_smoke=args.allow_local_smoke, workload_size=args.games)
    random.seed(args.seed); np.random.seed(args.seed); torch.manual_seed(args.seed)
    initial_hash = sha256(args.initial_model)
    rows = load_rows([Path(path) for path in args.rollouts], args.actual_order)
    observed_hashes = {str(row["policy_hash"]).upper() for row in rows}
    if observed_hashes != {initial_hash}:
        raise ValueError(f"rollout policy hash {observed_hashes} does not match initial model {initial_hash}")
    baseline = assign_cross_fitted_advantages(rows, folds=5)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = PolicyNet(feature_version=2).to(device)
    load_npz_weights(model, args.initial_model)
    parity = likelihood_parity(model, rows, args.batch_size, device)
    if abs(parity["initial_ratio"] - 1.0) > 0.0001 or parity["max_logprob_disagreement"] > 1e-5:
        raise RuntimeError(f"likelihood parity failed: {parity}")

    initial_state = copy.deepcopy(model.state_dict())
    actor_parameters = [parameter for name, parameter in model.named_parameters() if not name.startswith("value.")]
    optimizer = torch.optim.AdamW(actor_parameters, lr=args.learning_rate, weight_decay=0.0)
    random.Random(args.seed).shuffle(rows)
    totals = {"batches": 0, "policy_loss": 0.0, "approx_kl": 0.0, "ratio": 0.0, "clip_fraction": 0.0}
    status = "complete"
    for start in range(0, len(rows), args.batch_size):
        batch = move(build_batch(rows[start:start + args.batch_size]), device)
        model.train()
        logits, counts, _ = model(batch)
        new_logprob = torch.stack([
            complete_action_logprob(logits, counts, batch, index, action, batch["temperature"][index])
            for index, action in enumerate(batch["record_actions"])
        ])
        log_ratio = new_logprob - batch["old_logprob"]
        ratio = torch.exp(log_ratio)
        advantage = batch["advantage"]
        unclipped = ratio * advantage
        clipped = ratio.clamp(1.0 - args.clip_ratio, 1.0 + args.clip_ratio) * advantage
        loss = -torch.minimum(unclipped, clipped).mean()
        if not torch.isfinite(loss):
            model.load_state_dict(initial_state)
            status = "rolled_back_nonfinite"
            break
        approximate_kl = ((ratio - 1.0) - log_ratio).mean()
        prospective_batches = totals["batches"] + 1
        rolling_kl = (totals["approx_kl"] + float(approximate_kl.detach())) / prospective_batches
        if not math.isfinite(rolling_kl) or rolling_kl >= args.hard_kl:
            model.load_state_dict(initial_state)
            status = "rolled_back_hard_kl"
            break
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(actor_parameters, 1.0)
        optimizer.step()
        totals["batches"] = prospective_batches
        totals["policy_loss"] += float(loss.detach())
        totals["approx_kl"] += float(approximate_kl.detach())
        totals["ratio"] += float(ratio.mean().detach())
        totals["clip_fraction"] += float(((ratio - 1.0).abs() > args.clip_ratio).float().mean().detach())
        if rolling_kl >= args.target_kl:
            status = "target_kl_stop"
            break

    output = Path(args.output)
    export_npz(model.cpu(), output)
    count = max(1, int(totals["batches"]))
    metrics = {key: value / count for key, value in totals.items() if key != "batches"}
    manifest = {
        "status": status,
        "actual_order": args.actual_order,
        "schema_version": 2,
        "games": args.games,
        "decisions": len(rows),
        "terminal_reward_only": True,
        "critic": False,
        "gae": False,
        "q_boost": False,
        "imitation": False,
        "ppo_epochs": 1,
        "clip_ratio": args.clip_ratio,
        "learning_rate": args.learning_rate,
        "target_kl": args.target_kl,
        "hard_kl": args.hard_kl,
        "initial_model_sha256": initial_hash,
        "output_model_sha256": sha256(output),
        "parity": parity,
        "cross_fitted_baseline": baseline,
        "metrics": metrics,
        "seed": args.seed,
    }
    manifest_path = Path(args.manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initial-model", required=True)
    parser.add_argument("--rollouts", action="append", required=True)
    parser.add_argument("--actual-order", choices=("first", "second"), required=True)
    parser.add_argument("--games", type=int, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=3e-5)
    parser.add_argument("--clip-ratio", type=float, default=0.10)
    parser.add_argument("--target-kl", type=float, default=0.005)
    parser.add_argument("--hard-kl", type=float, default=0.01)
    parser.add_argument("--seed", type=int, default=2026080801)
    parser.add_argument("--allow-local-smoke", action="store_true")
    args = parser.parse_args()
    result = train(args)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] in {"complete", "target_kl_stop"} else 2


if __name__ == "__main__":
    raise SystemExit(main())

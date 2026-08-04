#!/usr/bin/env python3
"""Outcome-driven PPO fine-tuning with an elite behavior-cloning anchor."""

from __future__ import annotations

import argparse
import copy
import gzip
import itertools
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np
import torch
from torch.nn import functional as F

from training.train_bc import PolicyNet, collate, export_npz, iter_batches, move, policy_loss
from training.azure_guard import enforce_azure_workload


def load_npz(model: PolicyNet, path: str | Path):
    w = np.load(path, allow_pickle=False)
    state = model.state_dict()
    mapping = {
        "state_embedding.weight": w["state_embedding"],
        "card_embedding.weight": w["card_embedding"],
        "attack_embedding.weight": w["attack_embedding"],
        "type_embedding.weight": w["type_embedding"],
        "context_embedding.weight": w["context_embedding"],
        "area_embedding.weight": w["area_embedding"],
        "global_linear.weight": w["global_w"].T,
        "global_linear.bias": w["global_b"],
        "numeric_linear.weight": w["numeric_w"].T,
        "numeric_linear.bias": w["numeric_b"],
        "option_linear.weight": w["option_w"].T,
        "option_linear.bias": w["option_b"],
        "score.weight": w["score_w"].T,
        "score.bias": w["score_b"],
        "count.weight": w["count_w"].T,
        "count.bias": w["count_b"],
        "value.weight": w["value_w"].T,
        "value.bias": w["value_b"],
    }
    for name, value in mapping.items():
        state[name].copy_(torch.as_tensor(value, dtype=state[name].dtype))
    model.load_state_dict(state)


def iter_rollout_batches(path, batch_size, shuffle_buffer=20_000):
    rows = []

    def batches(buffer):
        # Interleave matchup/seat groups so early minibatches cannot be dominated
        # by the largest archetype before a smaller hard group is seen.
        grouped = {}
        for row in buffer:
            key = row.get("matchup_group") or f"{row.get('opponent_archetype', row.get('opponent', 'unknown'))}|seat{row.get('seat', 0)}"
            grouped.setdefault(key, []).append(row)
        for values in grouped.values():
            random.shuffle(values)
        keys = list(grouped)
        random.shuffle(keys)
        interleaved = []
        while keys:
            remaining = []
            for key in keys:
                if grouped[key]:
                    interleaved.append(grouped[key].pop())
                if grouped[key]:
                    remaining.append(key)
            keys = remaining
        buffer = interleaved
        for start in range(0, len(buffer), batch_size):
            selected = buffer[start : start + batch_size]
            if not selected:
                continue
            batch = collate(selected)
            batch["old_logprob"] = torch.tensor([row["old_logprob"] for row in selected], dtype=torch.float32)
            batch["old_value"] = torch.tensor([row["old_value"] for row in selected], dtype=torch.float32)
            batch["advantages"] = torch.tensor([row["advantage"] for row in selected], dtype=torch.float32)
            batch["is_blunder"] = torch.tensor([bool(row.get("is_blunder", False)) for row in selected], dtype=torch.bool)
            batch["behavior_temperature"] = torch.tensor(
                [row.get("behavior_temperature", 1.0) for row in selected], dtype=torch.float32
            )
            group_names = [
                row.get("matchup_group")
                or f"{row.get('opponent_archetype', row.get('opponent', 'unknown'))}|seat{row.get('seat', 0)}"
                for row in selected
            ]
            group_map = {name: index for index, name in enumerate(sorted(set(group_names)))}
            batch["group_ids"] = torch.tensor([group_map[name] for name in group_names], dtype=torch.long)
            corrections = []
            for row in selected:
                behavior = float(row.get("behavior_sampling_probability", 1.0))
                target = float(row.get("target_sampling_probability", behavior))
                corrections.append(max(0.5, min(2.0, target / max(1e-12, behavior))))
            batch["importance_weight"] = torch.tensor(corrections, dtype=torch.float32)
            yield batch

    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("trainable"):
                rows.append(row)
                if len(rows) >= shuffle_buffer:
                    yield from batches(rows)
                    rows = []
    if rows:
        yield from batches(rows)


def normalize_advantages_by_group(advantages, group_ids=None):
    """Normalize within matchup/seat groups, falling back globally for singletons."""
    global_normalized = (advantages - advantages.mean()) / (advantages.std(unbiased=False) + 1e-6)
    if group_ids is None:
        return global_normalized
    normalized = global_normalized.clone()
    for group_id in torch.unique(group_ids):
        mask = group_ids == group_id
        values = advantages[mask]
        if values.numel() >= 2:
            normalized[mask] = (values - values.mean()) / (values.std(unbiased=False) + 1e-6)
    return normalized


def weighted_mean(values, weights):
    return (values * weights).sum() / weights.sum().clamp_min(1e-6)


def rollout_record_weights(batch):
    weights = batch.get("weights")
    if weights is None:
        weights = torch.ones_like(batch["advantages"])
    correction = batch.get("importance_weight")
    if correction is not None:
        weights = weights * correction
    return weights


def ppo_policy_loss(logits, count_logits, batch, clip_ratio):
    new_logprobs = []
    entropies = []
    for record_index, (start, end) in enumerate(batch["record_options"]):
        # The behavior policy sampled logits / temperature. PPO's importance
        # ratio must evaluate the new policy under that exact distribution.
        local = logits[start:end] / batch["behavior_temperature"][record_index].clamp_min(1e-3)
        actions = batch["record_actions"][record_index]
        minimum = int(round(float(batch["global"][record_index, 28].item()) * 9))
        maximum = int(round(float(batch["global"][record_index, 29].item()) * 9))
        logprob = local.sum() * 0.0
        entropy_terms = []
        if minimum != maximum:
            valid = count_logits[record_index, minimum : maximum + 1] / batch["behavior_temperature"][record_index].clamp_min(1e-3)
            count_log_probs = F.log_softmax(valid, dim=0)
            count_probabilities = torch.softmax(valid, dim=0)
            logprob = logprob + count_log_probs[len(actions) - minimum]
            entropy_terms.append(-(count_probabilities * count_log_probs).sum())
        available = torch.ones(len(local), dtype=torch.bool, device=local.device)
        for action in actions:
            step_available = available.clone()
            step_logits = local.masked_fill(~step_available, -torch.inf)
            log_probs = F.log_softmax(step_logits, dim=0)
            probabilities = torch.softmax(step_logits, dim=0)
            logprob = logprob + log_probs[action]
            entropy_terms.append(-(probabilities[step_available] * log_probs[step_available]).sum())
            available = step_available.clone()
            available[action] = False
        new_logprobs.append(logprob)
        entropies.append(torch.stack(entropy_terms).mean() if entropy_terms else local.sum() * 0.0)
    new_logprobs = torch.stack(new_logprobs)
    entropy_values = torch.stack(entropies)
    advantages = batch["advantages"]
    advantages = normalize_advantages_by_group(advantages, batch.get("group_ids"))
    record_weights = rollout_record_weights(batch)
    log_ratio = new_logprobs - batch["old_logprob"]
    ratio = torch.exp(log_ratio)
    unclipped = ratio * advantages
    clipped = torch.clamp(ratio, 1 - clip_ratio, 1 + clip_ratio) * advantages
    approximate_kl_values = (ratio - 1.0) - log_ratio
    clipped_values = ((ratio - 1.0).abs() > clip_ratio).float()
    approximate_kl = weighted_mean(approximate_kl_values, record_weights)
    clip_fraction = weighted_mean(clipped_values, record_weights)
    entropy = weighted_mean(entropy_values, record_weights)

    # Invariant 1.6: Isolated policy penalty loss L_penalty for flagged blunder actions
    is_blunder = batch.get("is_blunder")
    if is_blunder is not None and is_blunder.any():
        penalty_loss = weighted_mean(new_logprobs[is_blunder], record_weights[is_blunder])
    else:
        penalty_loss = new_logprobs.sum() * 0.0

    return (
        -weighted_mean(torch.minimum(unclipped, clipped), record_weights),
        entropy,
        penalty_loss,
        float(ratio.mean().item()),
        float(approximate_kl.item()),
        float(clip_fraction.item()),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--initial-model", required=True)
    parser.add_argument("--rollouts", required=True)
    parser.add_argument("--bc-shard", action="append", default=[])
    parser.add_argument("--require-card", type=int, default=0)
    parser.add_argument("--output", required=True)
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--clip-ratio", type=float, default=0.2)
    parser.add_argument("--bc-weight", type=float, default=0.50)
    parser.add_argument("--entropy-weight", type=float, default=0.01)
    parser.add_argument("--penalty-weight", type=float, default=0.10, help="policy penalty loss weight for suboptimal/blunder actions")
    parser.add_argument("--target-kl", type=float, default=0.02)
    parser.add_argument("--hard-kl", type=float, default=0.04)
    parser.add_argument("--turn1-bench-reward", type=float, default=0.0, help="auxiliary reward bonus for establishing >=2 bench Pokemon on Turn 1")
    parser.add_argument("--allow-unanchored-training", action="store_true", help="allow training with bc_weight < 0.05 or missing bc_shard (diagnostic ablation only)")
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument("--allow-local-smoke", action="store_true")
    args = parser.parse_args()
    enforce_azure_workload(allow_local_smoke=args.allow_local_smoke, workload_size=1)

    if not args.allow_unanchored_training:
        if args.bc_weight < 0.05:
            raise ValueError(
                f"Rule 1 violation (Dual-Anchor Principle): bc_weight={args.bc_weight:.4f} is below the 0.05 minimum anchor threshold. "
                "Unanchored RL erodes elite human priors. Pass --allow-unanchored-training to explicitly override for diagnostic ablations."
            )
        if not args.bc_shard:
            raise ValueError(
                "Rule 1 violation (Dual-Anchor Principle): At least one --bc-shard must be provided to anchor PPO updates against human play. "
                "Pass --allow-unanchored-training to explicitly override for diagnostic ablations."
            )

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    arrays = np.load(args.initial_model, allow_pickle=False)
    feature_version = int(np.asarray(arrays["model_schema_version"]).item()) if "model_schema_version" in arrays else 1
    model = PolicyNet(feature_version)
    load_npz(model, args.initial_model)
    model.to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=1e-5)
    bc_paths = [Path(path) for path in args.bc_shard]

    # Materialize once: a thin anchor shard (e.g. a low-volume archetype) cycles
    # out many times per rollout epoch, and re-reading the gzip shard from disk
    # on every exhaustion (rather than looping in memory) turns one PPO epoch
    # into tens of full-file rescans.
    bc_batches = list(iter_batches(
        bc_paths, args.batch_size, required_card=args.require_card, feature_version=feature_version,
    )) if bc_paths else []
    if bc_paths and not bc_batches:
        raise RuntimeError(
            f"bc-shard yields no batches for require-card={args.require_card} "
            f"at feature_version={feature_version}"
        )

    hard_stopped = False
    for epoch in range(args.epochs):
        epoch_start = copy.deepcopy(model.state_dict())
        model.train()
        bc_iterator = itertools.cycle(bc_batches) if bc_batches else None
        totals = {"loss": 0.0, "policy": 0.0, "value": 0.0, "penalty": 0.0, "ratio": 0.0, "approx_kl": 0.0, "clip_fraction": 0.0, "batches": 0}
        for rollout in iter_rollout_batches(args.rollouts, args.batch_size):
            rollout = move(rollout, device)
            logits, count_logits, values = model(rollout)
            ppo_loss, entropy, penalty_loss, ratio, approximate_kl, clip_fraction = ppo_policy_loss(logits, count_logits, rollout, args.clip_ratio)
            value_losses = F.binary_cross_entropy_with_logits(values, rollout["values"], reduction="none")
            value_loss = weighted_mean(value_losses, rollout_record_weights(rollout))
            loss = ppo_loss + 0.5 * value_loss - args.entropy_weight * entropy + args.penalty_weight * penalty_loss
            if bc_iterator is not None:
                bc_batch = move(next(bc_iterator), device)
                bc_logits, _, _ = model(bc_batch)
                bc_loss, _, _ = policy_loss(bc_logits, bc_batch)
                loss = loss + args.bc_weight * bc_loss
            rolling_kl = (totals["approx_kl"] + approximate_kl) / (totals["batches"] + 1)
            if rolling_kl >= args.hard_kl:
                model.load_state_dict(epoch_start)
                hard_stopped = True
                print({"epoch": epoch + 1, "hard_kl_stop": rolling_kl, "rolled_back": True})
                break
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            totals["loss"] += float(loss.item())
            totals["policy"] += float(ppo_loss.item())
            totals["value"] += float(value_loss.item())
            totals["penalty"] += float(penalty_loss.item())
            totals["ratio"] += ratio
            totals["approx_kl"] += approximate_kl
            totals["clip_fraction"] += clip_fraction
            totals["batches"] += 1
            if totals["approx_kl"] / totals["batches"] >= args.target_kl:
                break
        count = max(1, totals.pop("batches"))
        print({"epoch": epoch + 1, **{key: value / count for key, value in totals.items()}, "device": str(device)})
        if hard_stopped:
            break
    export_npz(model.cpu(), Path(args.output))
    print({"output": args.output})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

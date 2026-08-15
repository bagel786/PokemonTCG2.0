#!/usr/bin/env python3
"""Behavior-clone schema-5 DirectPolicyNet from Dragapult teacher shards.

Plain BC (sequential complete-action softmax + masked count loss) with an
optional semantic-equivalence target: any option that is semantically
identical to the teacher's choice (duplicate engine options) is accepted.

Semantic groups are precomputed at extraction time (``action_groups``).
Episode-level sample weights are optional and come from the shard rows.

Usage:
    python3 scripts/dragapult_emergency_train.py \
        data/dragapult_emergency/shards/55456110/train.jsonl.gz \
        --validation data/dragapult_emergency/shards/55456110/validation.jsonl.gz \
        --output artifacts/dragapult_emergency/bc_flg_a.npz
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from training.schema5 import DirectPolicyNet, export_direct
from training.train_bc import iter_batches, masked_count_loss, move

_CONTEXT_NAMES = {
    41: "IS_FIRST", 0: "ROOT",
    7: "CHOOSE_ACTIVE", 8: "CHOOSE_BENCH", 9: "ATTACH", 10: "EVOLVE",
    11: "PLAY", 12: "ABILITY", 18: "SEARCH", 19: "DISCARD", 20: "RECOVER",
    21: "DRAW", 22: "PRIZE", 23: "ENERGY_SEARCH", 24: "REVEAL", 25: "DAMAGE",
    26: "SHUFFLE", 28: "BENCH_PLACE", 30: "COIN", 31: "ATTACK", 32: "RETREAT",
    33: "EVOLVE2", 34: "TARGET", 35: "RETREAT_ENERGY", 36: "HAND_DISCARD",
    37: "DECK_PLACE", 38: "PLACE", 39: "SWITCH", 40: "MOVE_ENERGY",
}


def semantic_group_loss(logits: torch.Tensor, batch: dict) -> tuple[torch.Tensor, int, int]:
    losses: list[torch.Tensor] = []
    exact = total = 0
    groups_by_record = batch.get("record_action_groups")
    for record_index, (start, end) in enumerate(batch["record_options"]):
        local = logits[start:end]
        actions = batch["record_actions"][record_index]
        groups = groups_by_record[record_index] if groups_by_record is not None else None
        if not actions:
            continue
        available = torch.ones(len(local), dtype=torch.bool, device=local.device)
        terms: list[torch.Tensor] = []
        for position, action in enumerate(actions):
            step_available = available.clone()
            masked = local.masked_fill(~step_available, -torch.inf)
            log_softmax = F.log_softmax(masked, dim=0)
            group = None
            if groups is not None and position < len(groups):
                group = [int(index) for index in groups[position]
                         if int(index) < len(local)]
            if group is not None and len(group) > 1 and all(step_available[i] for i in group):
                terms.append(-torch.logsumexp(log_softmax[group], dim=0))
            else:
                terms.append(-log_softmax[action])
            available = step_available.clone()
            available[action] = False
        losses.append(torch.stack(terms).mean() * batch["weights"][record_index])
        if len(actions) == 1:
            total += 1
            exact += int(torch.argmax(local).item() == actions[0])
    if not losses:
        return logits.sum() * 0.0, exact, total
    return torch.stack(losses).sum() / batch["weights"].sum().clamp_min(1e-6), exact, total


@torch.no_grad()
def agreement_metrics(logits, counts, batch) -> dict:
    metrics = {
        "records": 0, "single_top1": 0, "single_top3": 0, "single_total": 0,
        "semantic_top1": 0, "semantic_total": 0, "count_correct": 0, "count_total": 0,
        "order_first": [0, 0], "order_second": [0, 0],
        "early": [0, 0], "mid": [0, 0], "late": [0, 0],
        "context": {},
    }
    groups_by_record = batch.get("record_action_groups")
    starts = [start for start, _ in batch["record_options"]]
    for record_index, (start, end) in enumerate(batch["record_options"]):
        local = logits[start:end]
        actions = batch["record_actions"][record_index]
        global_row = batch["global"][record_index]
        if len(actions) != 1:
            continue
        metrics["records"] += 1
        metrics["single_total"] += 1
        ranked = torch.argsort(local, descending=True, stable=True).tolist()
        chosen = actions[0]
        top1 = int(ranked[0] == chosen)
        top3 = int(chosen in ranked[:3])
        metrics["single_top1"] += top1
        metrics["single_top3"] += top3
        groups = groups_by_record[record_index] if groups_by_record is not None else None
        if groups and groups[0]:
            metrics["semantic_total"] += 1
            metrics["semantic_top1"] += int(ranked[0] in groups[0])
        order_key = "order_first" if float(global_row[3]) >= 0.5 else "order_second"
        metrics[order_key][0] += top1
        metrics[order_key][1] += 1
        prize = float(global_row[10])
        stage = "early" if prize > 0.75 else "mid" if prize > 0.35 else "late"
        metrics[stage][0] += top1
        metrics[stage][1] += 1
        context = int(batch["context"][start])
        name = _CONTEXT_NAMES.get(context, str(context))
        bucket = metrics["context"].setdefault(name, [0, 0])
        bucket[0] += top1
        bucket[1] += 1
        minimum = int(round(float(global_row[28]) * 9))
        maximum = int(round(float(global_row[29]) * 9))
        if minimum == maximum:
            metrics["count_total"] += 1
            desired = int(batch["counts"][record_index])
            metrics["count_correct"] += int(desired == minimum)
    return metrics


def summarize(metrics: dict) -> str:
    def rate(correct_key: str) -> str:
        value = metrics.get(correct_key, 0)
        if isinstance(value, list):
            correct, total = value
        else:
            correct = value
            total = metrics.get(correct_key + "_total", 0)
        return f"{correct}/{total} ({100 * correct / max(1, total):.1f}%)"
    parts = [f"records={metrics['records']}",
             f"top1 {rate('single_top1')}", f"top3 {rate('single_top3')}",
             f"semantic_top1 {rate('semantic_top1')}",
             f"first {rate('order_first')}", f"second {rate('order_second')}",
             f"early {rate('early')}", f"mid {rate('mid')}", f"late {rate('late')}",
             f"count {rate('count_correct')}"]
    return "  ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("shards", nargs="+")
    parser.add_argument("--validation", nargs="+", default=[])
    parser.add_argument("--output", required=True)
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--max-records", type=int, default=0)
    parser.add_argument("--max-validation-records", type=int, default=20000)
    parser.add_argument("--semantic", action="store_true")
    parser.add_argument("--team-ranks", default="",
                        help="ordered newline-delimited team names for modest quality weighting")
    parser.add_argument("--grim-weight", type=float, default=0.0,
                        help="multiply sample_weight by this for rows tagged opponent_grimmsnarl")
    parser.add_argument("--seed", type=int, default=20260814)
    args = parser.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"device: {device}", flush=True)

    model = DirectPolicyNet().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=1e-5)
    paths = [Path(p) for p in args.shards]
    validation_paths = [Path(p) for p in args.validation]
    loss_fn = semantic_group_loss if args.semantic else None
    team_weights: dict[str, float] = {}
    if args.team_ranks:
        names = [line.strip() for line in Path(args.team_ranks).read_text().splitlines()
                 if line.strip()]
        for rank, name in enumerate(names, 1):
            team_weights[name] = 1.5 if rank <= 1 else 1.2 if rank <= 3 else 1.0
        print(f"team weights: {team_weights}", flush=True)
    grim_weight = float(args.grim_weight)
    if grim_weight:
        print(f"grimmsnarl row weight multiplier: {grim_weight}", flush=True)

    def adjust_weights(batch: dict) -> None:
        if not grim_weight:
            return
        tagged = batch.get("record_grimmsnarl")
        if not tagged:
            return
        for index, flagged in enumerate(tagged):
            if flagged:
                batch["weights"][index] *= grim_weight

    def run_epoch(epoch: int, training: bool) -> dict:
        if training:
            model.train()
            source = paths
            max_records = args.max_records
        else:
            model.eval()
            source = validation_paths
            max_records = args.max_validation_records
        running = batches = 0
        agreement = None
        for batch in iter_batches(source, args.batch_size, max_records,
                                  feature_version=5, validation=not training,
                                  team_weights=team_weights if training else None):
            batch = move(batch, device)
            adjust_weights(batch)
            if training:
                logits, counts = model(batch)
                if loss_fn is not None:
                    option_loss, _, _ = loss_fn(logits, batch)
                else:
                    from training.train_bc import policy_loss
                    option_loss, _, _ = policy_loss(logits, batch)
                loss = option_loss + 0.25 * masked_count_loss(counts, batch)
                if not torch.isfinite(loss):
                    raise FloatingPointError(f"non-finite loss at epoch {epoch}")
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                running += float(loss.item())
                batches += 1
            else:
                with torch.no_grad():
                    logits, counts = model(batch)
                    metric = agreement_metrics(logits, counts, batch)
                    if agreement is None:
                        agreement = metric
                    else:
                        for key, value in metric.items():
                            if isinstance(value, list):
                                agreement[key][0] += value[0]
                                agreement[key][1] += value[1]
                            elif isinstance(value, dict):
                                for name, pair in value.items():
                                    bucket = agreement[key].setdefault(name, [0, 0])
                                    bucket[0] += pair[0]
                                    bucket[1] += pair[1]
                            else:
                                agreement[key] += value
        if training:
            return {"mode": "train", "epoch": epoch, "loss": running / max(1, batches),
                    "batches": batches}
        print(f"  validation: {summarize(agreement)}", flush=True)
        return {"mode": "validation", **{k: v for k, v in agreement.items()
                                         if not isinstance(v, (dict,))}}

    history = []
    for epoch in range(1, args.epochs + 1):
        train_metrics = run_epoch(epoch, True)
        print(json.dumps(train_metrics), flush=True)
        history.append(train_metrics)
        if validation_paths:
            history.append(run_epoch(epoch, False))
    if validation_paths:
        history.append(run_epoch(0, False))
    export_direct(model.cpu(), Path(args.output))
    print(json.dumps({"output": args.output, "history": history}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

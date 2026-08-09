#!/usr/bin/env python3
"""Evaluate A2 and a schema-4 ensemble on an untouched replay stream."""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.relational import _complete_score
from training.schema4 import RelationalResidualNet, legacy_a2_batch, load_residual
from training.train_bc import PolicyNet, collate, load_npz_weights, move


def rows(path: Path, requested_split: str = "all"):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if requested_split == "all" or row.get("split") == requested_split:
                yield row


def chunks(iterable, size):
    batch = []
    for value in iterable:
        batch.append(value)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def bounds(batch, record_index):
    minimum = int(round(float(batch["global"][record_index, 28]) * 9))
    maximum = int(round(float(batch["global"][record_index, 29]) * 9))
    return minimum, maximum


def action(logits, counts, minimum, maximum):
    maximum = min(maximum, len(counts) - 1, len(logits))
    minimum = min(minimum, maximum)
    desired = minimum if minimum == maximum else minimum + int(np.argmax(counts[minimum:maximum + 1]))
    return tuple(np.argsort(-logits, kind="stable")[:desired].astype(int).tolist())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stream")
    parser.add_argument("--base", default="artifacts/recovery_probes/extracted/a2_base/policy_weights.npz")
    parser.add_argument("--heads", nargs=3, required=True)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--output", required=True)
    parser.add_argument("--split", default="all", choices=("all", "train", "validation", "holdout"))
    args = parser.parse_args()
    device = torch.device("cpu")
    base = PolicyNet(2).to(device).eval()
    load_npz_weights(base, args.base)
    heads = []
    for path in args.heads:
        arrays = np.load(path, allow_pickle=False)
        mode = "r0" if int(arrays["residual_mode"]) == 0 else "r1"
        model = RelationalResidualNet(mode).to(device).eval()
        load_residual(model, path)
        heads.append(model)
    support_margin = max(float(np.load(path, allow_pickle=False)["support_margin"]) for path in args.heads)
    metrics = Counter()
    strata = defaultdict(Counter)
    context_strata = defaultdict(Counter)
    override_examples = []
    episode_deltas = defaultdict(lambda: [0, 0])
    with torch.no_grad():
        for source_rows in chunks(rows(Path(args.stream), args.split), args.batch_size):
            batch = move(collate(source_rows), device)
            base_logits, base_count, _ = base(legacy_a2_batch(batch))
            predictions = [head(batch) for head in heads]
            base_logits = base_logits.cpu().numpy()
            base_count = base_count.cpu().numpy()
            residual_logits = [value[0].cpu().numpy() for value in predictions]
            residual_count = [value[1].cpu().numpy() for value in predictions]
            for record_index, (start, end) in enumerate(batch["record_options"]):
                minimum, maximum = bounds(batch, record_index)
                truth = tuple(batch["record_actions"][record_index])
                base_action = action(base_logits[start:end], base_count[record_index], minimum, maximum)
                head_actions = []
                final_logits = []
                final_counts = []
                for head_index in range(3):
                    logits = base_logits[start:end] + residual_logits[head_index][start:end]
                    counts = base_count[record_index] + residual_count[head_index][record_index]
                    final_logits.append(logits)
                    final_counts.append(counts)
                    head_actions.append(action(logits, counts, minimum, maximum))
                candidate, support = Counter(head_actions).most_common(1)[0]
                mean_logits = np.mean(final_logits, axis=0)
                mean_counts = np.mean(final_counts, axis=0)
                mean_action = action(mean_logits, mean_counts, minimum, maximum)
                select = SimpleNamespace(minCount=minimum, maxCount=maximum)
                margin = _complete_score(mean_logits, mean_counts, candidate, select)
                margin -= _complete_score(mean_logits, mean_counts, base_action, select)
                chosen = candidate if support >= 2 and (candidate == base_action or margin >= support_margin) else base_action
                order = source_rows[record_index].get("hero_order") or "unknown"
                context_value = int(source_rows[record_index]["features"]["options"][0]["context"])
                context_name = "MAIN" if context_value == 0 else f"context_{context_value}"
                metrics["records"] += 1
                metrics["base_exact"] += base_action == truth
                metrics["candidate_exact"] += chosen == truth
                metrics["base_top1"] += bool(truth) and bool(base_action) and base_action[0] == truth[0]
                metrics["candidate_top1"] += bool(truth) and bool(chosen) and chosen[0] == truth[0]
                metrics["mean_exact"] += mean_action == truth
                metrics["vote_exact"] += candidate == truth
                for head_index, head_action in enumerate(head_actions):
                    metrics[f"head_{head_index}_exact"] += head_action == truth
                metrics["overrides"] += chosen != base_action
                metrics["changed_to_expert"] += chosen == truth and base_action != truth
                metrics["changed_away"] += chosen != truth and base_action == truth
                episode_key = str(source_rows[record_index].get("episode_id"))
                episode_deltas[episode_key][0] += int(chosen == truth) - int(base_action == truth)
                episode_deltas[episode_key][1] += 1
                strata[order]["records"] += 1
                strata[order]["base_exact"] += base_action == truth
                strata[order]["candidate_exact"] += chosen == truth
                context_strata[context_name]["records"] += 1
                context_strata[context_name]["base_exact"] += base_action == truth
                context_strata[context_name]["candidate_exact"] += chosen == truth
                if chosen != base_action and len(override_examples) < 100:
                    override_examples.append({
                        "episode_id": source_rows[record_index].get("episode_id"),
                        "step": source_rows[record_index].get("step"),
                        "order": order,
                        "truth": truth,
                        "base": base_action,
                        "candidate": chosen,
                        "support": support,
                        "margin": margin,
                    })
    total = metrics["records"]
    clusters = np.asarray(list(episode_deltas.values()), dtype=np.float64)
    rng = np.random.default_rng(20260808)
    bootstrap = np.empty(10_000, dtype=np.float64)
    for index in range(len(bootstrap)):
        sampled = clusters[rng.integers(0, len(clusters), size=len(clusters))]
        bootstrap[index] = sampled[:, 0].sum() / max(1.0, sampled[:, 1].sum())
    report = {
        "status": "complete",
        "stream": str(Path(args.stream).resolve()),
        "records": total,
        "base_complete_agreement": metrics["base_exact"] / max(1, total),
        "candidate_complete_agreement": metrics["candidate_exact"] / max(1, total),
        "complete_agreement_uplift_points": 100 * (metrics["candidate_exact"] - metrics["base_exact"]) / max(1, total),
        "episode_clusters": len(clusters),
        "episode_cluster_bootstrap_95_points": [
            100 * float(np.quantile(bootstrap, 0.025)),
            100 * float(np.quantile(bootstrap, 0.975)),
        ],
        "base_top1": metrics["base_top1"] / max(1, total),
        "candidate_top1": metrics["candidate_top1"] / max(1, total),
        "ungated_mean_complete_agreement": metrics["mean_exact"] / max(1, total),
        "ungated_vote_complete_agreement": metrics["vote_exact"] / max(1, total),
        "head_complete_agreement": [
            metrics[f"head_{index}_exact"] / max(1, total) for index in range(3)
        ],
        "overrides": metrics["overrides"],
        "changed_to_expert": metrics["changed_to_expert"],
        "changed_away": metrics["changed_away"],
        "by_actual_order": {
            name: {
                "records": values["records"],
                "base_complete_agreement": values["base_exact"] / max(1, values["records"]),
                "candidate_complete_agreement": values["candidate_exact"] / max(1, values["records"]),
            }
            for name, values in sorted(strata.items())
        },
        "by_context": {
            name: {
                "records": values["records"],
                "base_complete_agreement": values["base_exact"] / max(1, values["records"]),
                "candidate_complete_agreement": values["candidate_exact"] / max(1, values["records"]),
                "uplift_points": 100 * (values["candidate_exact"] - values["base_exact"]) / max(1, values["records"]),
            }
            for name, values in sorted(context_strata.items())
        },
        "override_examples": override_examples,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "override_examples"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

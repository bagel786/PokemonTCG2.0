#!/usr/bin/env python3
"""Measure how A2-ERR checkpoints fit the certified training corrections."""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / "vendor").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np
import torch

from training.evaluate_a2_err_offline import option_key, semantic_ranking
from training.train_bc import PolicyNet, collate, load_npz_weights, move


def rows_in_batches(path: Path, batch_size: int):
    rows = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            rows.append(json.loads(line))
            if len(rows) == batch_size:
                yield rows
                rows = []
    if rows:
        yield rows


def empty_metric() -> dict[str, float]:
    return {"rows": 0, "top1": 0, "top3": 0, "promoted": 0, "margin_sum": 0.0}


def update(metric: dict[str, float], *, top1: bool, top3: bool, promoted: bool, margin: float) -> None:
    metric["rows"] += 1
    metric["top1"] += int(top1)
    metric["top3"] += int(top3)
    metric["promoted"] += int(promoted)
    metric["margin_sum"] += float(margin)


def finalize(metric: dict[str, float]) -> dict:
    rows = int(metric["rows"])
    return {
        "rows": rows,
        "semantic_top1": metric["top1"] / rows if rows else None,
        "semantic_top3": metric["top3"] / rows if rows else None,
        "promoted_to_semantic_rank1": metric["promoted"] / rows if rows else None,
        "mean_elite_minus_rejected_semantic_max_logit": metric["margin_sum"] / rows if rows else None,
    }


def audit(base_path: Path, candidates: list[tuple[str, Path]], corrections: Path, batch_size: int) -> dict:
    torch.set_num_threads(1)
    device = torch.device("cpu")
    model_paths = [("exact_a2", base_path), *candidates]
    models = {}
    for name, path in model_paths:
        model = PolicyNet(2).to(device).eval()
        load_npz_weights(model, path)
        models[name] = model
    metrics = {
        name: {
            "overall": empty_metric(),
            "by_outcome_order": defaultdict(empty_metric),
            "by_rank_band": defaultdict(empty_metric),
            "by_action_family": defaultdict(empty_metric),
        }
        for name in models
    }
    base_rank_invariant_failures = 0
    for rows in rows_in_batches(corrections, batch_size):
        batch = move(collate(rows), device)
        with torch.no_grad():
            outputs = {name: model(batch)[0].cpu().numpy() for name, model in models.items()}
        for record_index, row in enumerate(rows):
            start, end = batch["record_options"][record_index]
            options = row["features"]["options"]
            label_index = int(row["action"][0])
            elite_key = option_key(options[label_index])
            base_local = outputs["exact_a2"][start:end]
            base_ranked = np.argsort(-base_local, kind="stable").astype(int).tolist()
            base_semantic = semantic_ranking(options, base_ranked)
            rejected_key = base_semantic[0]
            if elite_key not in base_semantic[1:3]:
                base_rank_invariant_failures += 1
            elite_indices = [index for index, option in enumerate(options) if option_key(option) == elite_key]
            rejected_indices = [index for index, option in enumerate(options) if option_key(option) == rejected_key]
            slices = (
                ("overall", "overall"),
                ("by_outcome_order", f"{row['outcome']}-{row['actual_order']}"),
                ("by_rank_band", row["rank_band"]),
                ("by_action_family", row["action_category"]),
            )
            for name, logits in outputs.items():
                local = logits[start:end]
                ranked = np.argsort(-local, kind="stable").astype(int).tolist()
                semantic = semantic_ranking(options, ranked)
                top1 = semantic[0] == elite_key
                top3 = elite_key in semantic[:3]
                margin = float(np.max(local[elite_indices]) - np.max(local[rejected_indices]))
                for section, key in slices:
                    target = metrics[name][section] if section == "overall" else metrics[name][section][key]
                    update(target, top1=top1, top3=top3, promoted=top1, margin=margin)
    result = {
        "experiment": "A2-ERR-1",
        "stage": "original train-correction learning audit",
        "corrections": str(corrections),
        "base_rank_2_or_3_invariant_failures": base_rank_invariant_failures,
        "models": {},
    }
    for name, sections in metrics.items():
        result["models"][name] = {
            "overall": finalize(sections["overall"]),
            "by_outcome_order": {key: finalize(value) for key, value in sorted(sections["by_outcome_order"].items())},
            "by_rank_band": {key: finalize(value) for key, value in sorted(sections["by_rank_band"].items())},
            "by_action_family": {key: finalize(value) for key, value in sorted(sections["by_action_family"].items())},
        }
    return result


def parse_candidate(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("candidate must be NAME=PATH")
    name, raw_path = value.split("=", 1)
    path = Path(raw_path).resolve()
    if not name or not path.is_file():
        raise argparse.ArgumentTypeError(f"invalid candidate: {value}")
    return name, path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--candidate", action="append", type=parse_candidate, required=True)
    parser.add_argument("--corrections", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--batch-size", type=int, default=256)
    args = parser.parse_args()
    report = audit(
        Path(args.base).resolve(), args.candidate, Path(args.corrections).resolve(), args.batch_size
    )
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "rows": report["models"]["exact_a2"]["overall"]["rows"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

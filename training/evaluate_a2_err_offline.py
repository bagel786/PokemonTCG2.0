#!/usr/bin/env python3
"""Evaluate the frozen A2-ERR-1 Gate A and Gate B thresholds."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / "vendor").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np
import torch
import torch.nn.functional as F

from training.train_bc import PolicyNet, collate, load_npz_weights, move
from training.train_elite_margin import A2_ERR_BASE_SHA256, frozen_array_audit


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def option_key(option: dict) -> tuple:
    return (
        int(option["option_type"]), int(option["context"]),
        int(option["source_card"]), int(option["target_card"]),
        int(option["attack_id"]), int(option["area"]), int(option["in_play_area"]),
        tuple(round(float(value), 6) for index, value in enumerate(option["numeric"]) if index not in (9, 10, 11)),
    )


def semantic_ranking(options: list[dict], ranked: list[int]) -> list[tuple]:
    seen = set()
    result = []
    for index in ranked:
        key = option_key(options[index])
        if key not in seen:
            seen.add(key)
            result.append(key)
    return result


def batches(paths: list[Path], batch_size: int):
    rows = []
    for path in paths:
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


def empty_metric() -> Counter:
    return Counter()


def update_metric(metric: Counter, row: dict, base_logits: np.ndarray, candidate_logits: np.ndarray) -> None:
    metric["states"] += 1
    base_shifted = base_logits.astype(np.float64) - float(np.max(base_logits))
    candidate_shifted = candidate_logits.astype(np.float64) - float(np.max(candidate_logits))
    base_probability = np.exp(base_shifted) / np.exp(base_shifted).sum()
    candidate_probability = np.exp(candidate_shifted) / np.exp(candidate_shifted).sum()
    metric["kl_sum"] += float(np.sum(base_probability * (np.log(base_probability) - np.log(candidate_probability))))
    base_ranked = np.argsort(-base_logits, kind="stable").astype(int).tolist()
    candidate_ranked = np.argsort(-candidate_logits, kind="stable").astype(int).tolist()
    options = row["features"]["options"]
    base_semantic = semantic_ranking(options, base_ranked)
    candidate_semantic = semantic_ranking(options, candidate_ranked)
    metric["semantic_change"] += int(base_semantic[0] != candidate_semantic[0])
    action = row.get("action", [])
    if len(action) != 1 or not 0 <= int(action[0]) < len(options):
        return
    label = option_key(options[int(action[0])])
    metric["single"] += 1
    metric["base_top1"] += int(base_semantic[0] == label)
    metric["candidate_top1"] += int(candidate_semantic[0] == label)
    metric["base_top3"] += int(label in base_semantic[:3])
    metric["candidate_top3"] += int(label in candidate_semantic[:3])


def finalize(metric: Counter) -> dict:
    single = metric["single"]
    states = metric["states"]
    base_top1 = metric["base_top1"] / single if single else None
    candidate_top1 = metric["candidate_top1"] / single if single else None
    base_top3 = metric["base_top3"] / single if single else None
    candidate_top3 = metric["candidate_top3"] / single if single else None
    return {
        "states": states,
        "single_semantic_decisions": single,
        "base_top1": base_top1,
        "candidate_top1": candidate_top1,
        "top1_delta_pp": (candidate_top1 - base_top1) * 100.0 if single else None,
        "base_top3": base_top3,
        "candidate_top3": candidate_top3,
        "top3_delta_pp": (candidate_top3 - base_top3) * 100.0 if single else None,
        "semantic_greedy_change_rate": metric["semantic_change"] / states if states else None,
        "mean_per_state_kl": metric["kl_sum"] / states if states else None,
    }


def gate_a_subsets(row: dict) -> list[str]:
    result = []
    teacher_qualified_top70 = row.get(
        "teacher_qualified_top70", int(row["teacher_source_date_rank"]) <= 70
    )
    if teacher_qualified_top70:
        result.append("all_top70")
        if int(row["teacher_source_date_rank"]) <= 20:
            result.append("rank_1_20")
        if row["outcome"] == "loss" and row["actual_order"] == "first":
            result.append("loss_first")
        if row["outcome"] == "loss" and row["actual_order"] == "second":
            result.append("loss_second")
    if row.get("strict_both_ge_1050"):
        result.extend([
            "strict_all",
            f"strict_{row['outcome']}",
            f"strict_{row['actual_order']}",
        ])
    return result


def decide_gate_a(subsets: dict[str, dict]) -> dict:
    required = ("strict_loss", "strict_win", "strict_first", "strict_second", "strict_all")
    missing = [name for name in required if not subsets.get(name, {}).get("single_semantic_decisions")]
    checks = {
        "loss_semantic_top1_delta_at_least_3pp": not missing and subsets["strict_loss"]["top1_delta_pp"] >= 3.0,
        "win_semantic_top1_delta_at_least_1pp": not missing and subsets["strict_win"]["top1_delta_pp"] >= 1.0,
        "first_top1_regression_at_most_0_5pp": not missing and subsets["strict_first"]["top1_delta_pp"] >= -0.5,
        "second_top1_regression_at_most_0_5pp": not missing and subsets["strict_second"]["top1_delta_pp"] >= -0.5,
        "semantic_top3_regression_at_most_0_25pp": not missing and subsets["strict_all"]["top3_delta_pp"] >= -0.25,
    }
    return {"status": "PASS" if all(checks.values()) else "FAIL", "missing_subsets": missing, "checks": checks}


def decide_gate_b(overall: dict, integrity: dict) -> dict:
    checks = {
        "semantic_top1_regression_at_most_0_5pp": overall["top1_delta_pp"] >= -0.5,
        "semantic_top3_regression_at_most_0_1pp": overall["top3_delta_pp"] >= -0.1,
        "semantic_greedy_change_rate_at_most_3pct": overall["semantic_greedy_change_rate"] <= 0.03,
        "mean_per_state_kl_at_most_0_02": overall["mean_per_state_kl"] <= 0.02,
        "count_outputs_identical": integrity["count_output_mismatches"] == 0,
        "value_outputs_identical": integrity["value_output_mismatches"] == 0,
        "all_frozen_parameter_arrays_byte_identical": integrity["frozen_array_audit"]["all_frozen_arrays_byte_identical"],
        "zero_non_finite_values": integrity["non_finite_values"] == 0,
        "zero_policy_runtime_errors": integrity["policy_runtime_errors"] == 0,
    }
    return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks}


def evaluate(
    base_path: Path,
    candidates: list[tuple[str, Path]],
    aug13: Path,
    legacy: list[Path],
    output: Path,
    batch_size: int = 256,
) -> dict:
    if sha256_file(base_path) != A2_ERR_BASE_SHA256:
        raise ValueError("exact A2 base SHA-256 mismatch")
    torch.set_num_threads(1)
    device = torch.device("cpu")
    base = PolicyNet(2).to(device).eval()
    load_npz_weights(base, base_path)
    models = {}
    for name, path in candidates:
        model = PolicyNet(2).to(device).eval()
        load_npz_weights(model, path)
        models[name] = model

    gate_a_metrics = {name: defaultdict(empty_metric) for name in models}
    gate_b_metrics = {name: defaultdict(empty_metric) for name in models}
    integrity = {
        name: {
            "count_output_mismatches": 0,
            "value_output_mismatches": 0,
            "non_finite_values": 0,
            "policy_runtime_errors": 0,
            "frozen_array_audit": frozen_array_audit(base_path, path),
        }
        for name, path in candidates
    }

    def run(paths: list[Path], destination, subset_function, *, preservation: bool) -> None:
        for rows in batches(paths, batch_size):
            try:
                batch = move(collate(rows), device)
                with torch.no_grad():
                    base_logits, base_counts, base_values = base(batch)
                    predictions = {name: model(batch) for name, model in models.items()}
            except Exception:
                for name in models:
                    integrity[name]["policy_runtime_errors"] += len(rows)
                continue
            for name, (candidate_logits, candidate_counts, candidate_values) in predictions.items():
                if preservation:
                    integrity[name]["count_output_mismatches"] += int(not torch.equal(base_counts, candidate_counts))
                    integrity[name]["value_output_mismatches"] += int(not torch.equal(base_values, candidate_values))
                integrity[name]["non_finite_values"] += int(
                    not torch.isfinite(candidate_logits).all()
                    or not torch.isfinite(candidate_counts).all()
                    or not torch.isfinite(candidate_values).all()
                )
            for record_index, row in enumerate(rows):
                start, end = batch["record_options"][record_index]
                base_local = base_logits[start:end].cpu().numpy()
                subsets = subset_function(row)
                for name, (candidate_logits, _, _) in predictions.items():
                    candidate_local = candidate_logits[start:end].detach().cpu().numpy()
                    for subset in subsets:
                        update_metric(destination[name][subset], row, base_local, candidate_local)

    run([aug13], gate_a_metrics, gate_a_subsets, preservation=False)
    for path in legacy:
        run([path], gate_b_metrics, lambda row, name=path.name: ["overall", name], preservation=True)

    checkpoints = {}
    selected = None
    for name, path in candidates:
        gate_a_subsets_final = {key: finalize(value) for key, value in sorted(gate_a_metrics[name].items())}
        gate_b_splits = {key: finalize(value) for key, value in sorted(gate_b_metrics[name].items())}
        gate_a = decide_gate_a(gate_a_subsets_final)
        gate_b = decide_gate_b(gate_b_splits["overall"], integrity[name])
        passed = gate_a["status"] == gate_b["status"] == "PASS"
        checkpoints[name] = {
            "path": str(path), "sha256": sha256_file(path),
            "gate_a": {**gate_a, "subsets": gate_a_subsets_final},
            "gate_b": {**gate_b, "metrics": gate_b_splits, "integrity": integrity[name]},
            "offline_status": "PASS" if passed else "FAIL",
        }
        if selected is None and passed:
            selected = name
    report = {
        "experiment": "A2-ERR-1",
        "stage": "offline promotion gates",
        "base": {"path": str(base_path), "sha256": sha256_file(base_path)},
        "aug13_holdout": {"path": str(aug13), "sha256": sha256_file(aug13)},
        "legacy_aug6_a2_holdout": [
            {"path": str(path), "sha256": sha256_file(path)} for path in legacy
        ],
        "legacy_holdout_interpretation": "unchanged Aug-6-created A2 validation, whole-team holdout, and temporal holdout union; each split also reported separately",
        "checkpoints": checkpoints,
        "selected_earliest_checkpoint": selected,
        "status": "PASS" if selected is not None else "FAIL",
        "gameplay_authorized": selected is not None,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def parse_candidate(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("candidate must be NAME=PATH")
    name, raw = value.split("=", 1)
    path = Path(raw).resolve()
    if not name or not path.is_file():
        raise argparse.ArgumentTypeError(f"invalid candidate: {value}")
    return name, path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--candidate", action="append", type=parse_candidate, required=True)
    parser.add_argument("--aug13", required=True)
    parser.add_argument("--legacy", action="append", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--batch-size", type=int, default=256)
    args = parser.parse_args()
    report = evaluate(
        Path(args.base).resolve(), args.candidate, Path(args.aug13).resolve(),
        [Path(value).resolve() for value in args.legacy], Path(args.output).resolve(), args.batch_size,
    )
    print(json.dumps({
        "status": report["status"],
        "selected_earliest_checkpoint": report["selected_earliest_checkpoint"],
        "gameplay_authorized": report["gameplay_authorized"],
        "output": str(Path(args.output).resolve()),
    }, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())

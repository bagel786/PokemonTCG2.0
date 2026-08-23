#!/usr/bin/env python3
"""Analyze the frozen four-cell representation-by-training ablation."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
from collections import defaultdict
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
FRESH = ROOT / "paper/data/fresh_confirmation/raw"
ABLATION = ROOT / "paper/data/ablation/raw"
TRAINING_REPORT = ROOT / "paper/data/ablation/training_report.json"
OPPONENT_FILES = {
    "B0": ("grim_b0", "grim_b0.json"),
    "d842_runtime": ("grim_d842_runtime", "grim_d842_runtime.json"),
    "master_v1": ("grim_master_v1", "grim_master_v1.json"),
    "replay_refresh": ("grim_replay_refresh", "grim_replay_refresh.json"),
    "starmie": ("starmie", "starmie_v2_boss_atk.json"),
    "dipplin": ("dipplin", "dipplin_d1.json"),
    "alakazam_no_search": ("alakazam_no_search", "alakazam_2_4a_no_search.json"),
}
EXPECTED = {
    "C1": "13426288358d597ead809e45c364c7f7b9274a6eebf55ddd942142e3326535c3",
    "C2": "36e804ae6c593db57b595bfca9fd48592da10957f0e5f840a7e390edbeb39b63",
    "C4": "83489e0c80c631763c65375d2a7a34d28d6aa9fbb1d11e89d130c83b1e27f1c0",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def candidate_and_control(path: Path) -> tuple[dict, dict, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    grouped = defaultdict(dict)
    for row in payload["rows"]:
        key = (str(row["actual_order"]), int(row["seed"]), int(row["physical_seat"]))
        grouped[key][str(row["arm"])] = row
    candidate, control = {}, {}
    for key, pair in grouped.items():
        if set(pair) != {"candidate", "control"}:
            raise ValueError(f"{path}: incomplete pair {key}")
        candidate[key] = pair["candidate"]
        control[key] = pair["control"]
    if len(grouped) != 400:
        raise ValueError(f"{path}: expected 400 pairs, got {len(grouped)}")
    return payload, candidate, control


def exact_mcnemar(left: np.ndarray, right: np.ndarray) -> float:
    differences = left.astype(int) - right.astype(int)
    positive = int(sum(differences == 1))
    negative = int(sum(differences == -1))
    total = positive + negative
    if not total:
        return 1.0
    lower = min(positive, negative)
    return min(1.0, 2 * sum(math.comb(total, k) for k in range(lower + 1)) / 2 ** total)


def holm(values: list[float]) -> list[float]:
    adjusted = [0.0] * len(values)
    running = 0.0
    for rank, index in enumerate(sorted(range(len(values)), key=values.__getitem__)):
        running = max(running, (len(values) - rank) * values[index])
        adjusted[index] = min(1.0, running)
    return adjusted


def main() -> int:
    training = json.loads(TRAINING_REPORT.read_text(encoding="utf-8"))
    expected = {**EXPECTED, "C3": training["package_tree_sha256"]}
    rows = []
    sources = [{"path": str(TRAINING_REPORT.relative_to(ROOT)), "sha256": sha256_file(TRAINING_REPORT)}]
    for opponent, (ablation_label, fresh_filename) in OPPONENT_FILES.items():
        paths = {
            "C2": ABLATION / f"c2_identity_a2_{ablation_label}.json",
            "C3": ABLATION / f"c3_blind_trained_{ablation_label}.json",
            "C4": FRESH / fresh_filename,
        }
        loaded = {cell: candidate_and_control(path) for cell, path in paths.items()}
        for cell, (payload, _, _) in loaded.items():
            if payload["candidate_sha256"] != expected[cell]:
                raise ValueError(f"{paths[cell]}: unexpected {cell} package hash")
            if payload["control_sha256"] != expected["C1"]:
                raise ValueError(f"{paths[cell]}: unexpected C1 package hash")
            if not payload.get("production_engine_preserved"):
                raise ValueError(f"{paths[cell]}: production engine sentinel failed")
            sources.append({
                "cell": cell, "opponent": opponent,
                "path": str(paths[cell].relative_to(ROOT)), "sha256": sha256_file(paths[cell]),
            })
        keys = set(loaded["C4"][1])
        if any(set(loaded[cell][1]) != keys for cell in ("C2", "C3")):
            raise ValueError(f"{opponent}: candidate seed/order/seat schedules do not match")
        for key in sorted(keys):
            controls = [loaded[cell][2][key] for cell in ("C2", "C3", "C4")]
            control_tuple = [
                (int(row["win"]), int(row.get("draw", 0)), int(row.get("hero_policy_errors", 0)))
                for row in controls
            ]
            if len(set(control_tuple)) != 1:
                raise ValueError(f"{opponent} {key}: deterministic C1 arm differs across runs")
            candidates = {cell: loaded[cell][1][key] for cell in ("C2", "C3", "C4")}
            if any(int(row.get("hero_policy_errors", 0)) for row in candidates.values()):
                raise ValueError(f"{opponent} {key}: candidate policy error")
            if any(int(row.get("opponent_policy_errors", 0)) for row in candidates.values()):
                raise ValueError(f"{opponent} {key}: opponent policy error")
            order, seed, seat = key
            rows.append({
                "opponent": opponent,
                "actual_order": order,
                "seed": seed,
                "physical_seat": seat,
                "c1_blind_a2_win": int(controls[0]["win"]),
                "c2_identity_a2_win": int(candidates["C2"]["win"]),
                "c3_blind_trained_win": int(candidates["C3"]["win"]),
                "c4_identity_trained_win": int(candidates["C4"]["win"]),
            })
    if len(rows) != 2_800:
        raise ValueError(f"expected 2800 matched worlds, got {len(rows)}")

    fields = list(rows[0])
    canonical = ROOT / "paper/data/ablation/canonical_ablation.csv"
    with canonical.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    cell_keys = [
        "c1_blind_a2_win", "c2_identity_a2_win",
        "c3_blind_trained_win", "c4_identity_trained_win",
    ]
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["opponent"], row["actual_order"])].append(row)
    strata = sorted(grouped)
    if len(strata) != 14 or any(len(grouped[key]) != 200 for key in strata):
        raise ValueError("ablation is not balanced over 14 200-pair strata")
    iterations = 100_000
    rng = np.random.default_rng(20260824)
    bootstrap = np.empty((len(strata), len(cell_keys), iterations), dtype=np.float32)
    batch = 1_000
    for stratum_index, key in enumerate(strata):
        values = np.asarray([[row[field] for field in cell_keys] for row in grouped[key]], dtype=np.float32)
        for start in range(0, iterations, batch):
            stop = min(iterations, start + batch)
            indices = rng.integers(0, len(values), size=(stop - start, len(values)))
            bootstrap[stratum_index, :, start:stop] = values[indices].mean(axis=1).T
    cell_bootstrap = bootstrap.mean(axis=0)
    observed = np.asarray([[row[field] for field in cell_keys] for row in rows], dtype=np.int8)
    cell_rates = {f"C{index + 1}": float(observed[:, index].mean()) for index in range(4)}
    contrasts = [
        ("C2-C1", 1, 0),
        ("C3-C1", 2, 0),
        ("C4-C1", 3, 0),
        ("C4-C2", 3, 1),
        ("C4-C3", 3, 2),
    ]
    results = []
    raw_p = []
    for label, left, right in contrasts:
        samples = cell_bootstrap[left] - cell_bootstrap[right]
        differences = observed[:, left].astype(int) - observed[:, right].astype(int)
        result = {
            "contrast": label,
            "effect": float(differences.mean()),
            "ci_low": float(np.percentile(samples, 2.5)),
            "ci_high": float(np.percentile(samples, 97.5)),
            "left_only_wins": int(sum(differences == 1)),
            "right_only_wins": int(sum(differences == -1)),
            "mcnemar_exact_two_sided_p": exact_mcnemar(observed[:, left], observed[:, right]),
            "pairs": len(rows),
        }
        raw_p.append(result["mcnemar_exact_two_sided_p"])
        results.append(result)
    for result, adjusted in zip(results, holm(raw_p), strict=True):
        result["holm_adjusted_p_5_contrasts"] = adjusted
    interaction_samples = cell_bootstrap[3] - cell_bootstrap[2] - cell_bootstrap[1] + cell_bootstrap[0]
    interaction_values = observed[:, 3] - observed[:, 2] - observed[:, 1] + observed[:, 0]
    interaction = {
        "contrast": "C4-C3-C2+C1",
        "effect": float(interaction_values.mean()),
        "ci_low": float(np.percentile(interaction_samples, 2.5)),
        "ci_high": float(np.percentile(interaction_samples, 97.5)),
        "pairs": len(rows),
        "method": "paired within-cell bootstrap; no McNemar test for interaction",
    }
    report = {
        "schema_version": 1,
        "generated_at_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "script": str(Path(__file__).resolve().relative_to(ROOT)),
        "script_sha256": sha256_file(Path(__file__).resolve()),
        "canonical_sha256": sha256_file(canonical),
        "package_hashes": expected,
        "cell_win_rates": cell_rates,
        "contrasts": results,
        "interaction": interaction,
        "bootstrap": {"iterations": iterations, "seed": 20260824, "strata": 14},
        "sources": sources,
    }
    output = ROOT / "paper/data/ablation/summary.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (ROOT / "paper/data/ablation/contrasts.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        fields = list(results[0])
        for key in interaction:
            if key not in fields:
                fields.append(key)
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(results + [interaction])
    (ROOT / "paper/ablation_macros.tex").write_text(
        "% Auto-generated by paper/scripts/analyze_ablation.py; do not edit.\n"
        + "".join(
            f"\\newcommand{{\\Ablation{result['contrast'].replace('-', 'to').replace('+', 'plus')}}}"
            f"{{{100 * result['effect']:.2f}}}\n"
            for result in results
        ),
        encoding="utf-8",
    )
    print(json.dumps({
        "cell_win_rates": cell_rates,
        "contrasts": results,
        "interaction": interaction,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

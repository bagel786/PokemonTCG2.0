#!/usr/bin/env python3
"""Independently reaggregate surviving raw null/negative-result artifacts."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import subprocess
from collections import defaultdict
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
TEMPORAL = [
    ROOT / "artifacts/grim_b_final_confirmation_vs_d842_second_400pairs.json",
    ROOT / "artifacts/grim_b_final_confirmation_vs_master_v1_second_400pairs.json",
    ROOT / "artifacts/grim_b_final_confirmation_vs_replay_refresh_second_400pairs.json",
]
ORACLE_DIR = ROOT / "artifacts/grim_sequence_oracle_v0"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def exact_mcnemar(positive: int, negative: int) -> float:
    total = positive + negative
    if not total:
        return 1.0
    lower = min(positive, negative)
    return min(1.0, 2 * sum(math.comb(total, k) for k in range(lower + 1)) / 2 ** total)


def percentile(values: np.ndarray) -> list[float]:
    return [float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))]


def temporal_summary(iterations: int = 100_000) -> tuple[dict, list[dict]]:
    strata = []
    sources = []
    candidate_wins = control_wins = candidate_only = control_only = errors = 0
    for path in TEMPORAL:
        payload = json.loads(path.read_text(encoding="utf-8"))
        arms = defaultdict(dict)
        for row in payload["rows"]:
            arms[(row["actual_order"], row["pair_index"])][row["arm"]] = row
        differences = []
        for key, pair in sorted(arms.items()):
            if set(pair) != {"candidate", "control"}:
                raise ValueError(f"{path}: incomplete pair {key}")
            candidate, control = pair["candidate"], pair["control"]
            for field in ("seed", "actual_order", "physical_seat"):
                if candidate[field] != control[field]:
                    raise ValueError(f"{path}: {field} mismatch")
            value = int(candidate["win"]) - int(control["win"])
            differences.append(value)
            candidate_wins += int(candidate["win"])
            control_wins += int(control["win"])
            candidate_only += int(value == 1)
            control_only += int(value == -1)
            errors += sum(int(pair[arm].get("hero_policy_errors", 0)) for arm in pair)
            errors += sum(int(pair[arm].get("opponent_policy_errors", 0)) for arm in pair)
        strata.append(np.asarray(differences, dtype=np.float32))
        sources.append({
            "path": str(path.relative_to(ROOT)), "sha256": sha256_file(path),
            "pairs": len(differences), "effect": float(np.mean(differences)),
        })
    rng = np.random.default_rng(20260825)
    bootstrap = np.empty(iterations, dtype=np.float32)
    batch = 1_000
    for start in range(0, iterations, batch):
        stop = min(iterations, start + batch)
        cell_means = []
        for values in strata:
            indices = rng.integers(0, len(values), size=(stop - start, len(values)))
            cell_means.append(values[indices].mean(axis=1))
        bootstrap[start:stop] = np.asarray(cell_means).mean(axis=0)
    return ({
        "label": "Two-turn temporal takeover",
        "experiment": "temporal_two_turn_takeover",
        "unit": "paired games",
        "n": sum(len(values) for values in strata),
        "candidate_wins": candidate_wins,
        "control_wins": control_wins,
        "candidate_only": candidate_only,
        "control_only": control_only,
        "effect": float(np.mean(np.concatenate(strata))),
        "ci_low": percentile(bootstrap)[0],
        "ci_high": percentile(bootstrap)[1],
        "mcnemar_exact_two_sided_p": exact_mcnemar(candidate_only, control_only),
        "method": "paired bootstrap stratified over three opponents; 100000 draws",
        "errors": errors,
        "scope": "actual-second; three fixed internal opponents",
    }, sources)


def oracle_summary(iterations: int = 100_000) -> tuple[dict, list[dict]]:
    manifest_path = ORACLE_DIR / "manifest.json"
    roots_path = ORACLE_DIR / "stage1_roots.jsonl.gz"
    raw_path = ORACLE_DIR / "stage1_raw_results.jsonl.gz"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_raw = manifest["outputs"]["raw_results"]["sha256"].lower()
    expected_roots = manifest["outputs"]["roots"]["sha256"].lower()
    if sha256_file(raw_path) != expected_raw or sha256_file(roots_path) != expected_roots:
        raise ValueError("sequence-oracle manifest digest mismatch")
    root_values = []
    candidate_wins = baseline_wins = candidate_only = baseline_only = 0
    with gzip.open(raw_path, "rt", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            values = []
            for world in record["confirmation"]["worlds"]:
                candidate = int(world["candidate"]["win"])
                baseline = int(world["baseline"]["win"])
                value = candidate - baseline
                values.append(value)
                candidate_wins += candidate
                baseline_wins += baseline
                candidate_only += int(value == 1)
                baseline_only += int(value == -1)
            root_values.append(np.asarray(values, dtype=np.float32))
    if len(root_values) != 60 or any(len(values) != 16 for values in root_values):
        raise ValueError("unexpected oracle root/world count")
    rng = np.random.default_rng(20260826)
    root_means = np.asarray([values.mean() for values in root_values], dtype=np.float32)
    bootstrap = np.empty(iterations, dtype=np.float32)
    batch = 2_000
    for start in range(0, iterations, batch):
        stop = min(iterations, start + batch)
        indices = rng.integers(0, len(root_means), size=(stop - start, len(root_means)))
        bootstrap[start:stop] = root_means[indices].mean(axis=1)
    return ({
        "label": "Bounded sequence oracle",
        "experiment": "bounded_sequence_oracle",
        "unit": "confirmation worlds (60 root clusters)",
        "n": sum(len(values) for values in root_values),
        "clusters": len(root_values),
        "candidate_wins": candidate_wins,
        "control_wins": baseline_wins,
        "candidate_only": candidate_only,
        "control_only": baseline_only,
        "effect": float(np.concatenate(root_values).mean()),
        "ci_low": percentile(bootstrap)[0],
        "ci_high": percentile(bootstrap)[1],
        "mcnemar_exact_two_sided_p": exact_mcnemar(candidate_only, baseline_only),
        "method": "root-cluster bootstrap; 100000 draws",
        "errors": sum(int(manifest["coverage"][key]) for key in (
            "cleanup_errors", "engine_errors", "incomplete_rollouts",
            "plan_world_errors", "policy_errors", "root_errors",
        )),
        "scope": "second-own-turn roots; three fixed opponents; at most two deviations",
        "prespecified_gate": 0.03,
    }, [
        {"path": str(manifest_path.relative_to(ROOT)), "sha256": sha256_file(manifest_path)},
        {"path": str(roots_path.relative_to(ROOT)), "sha256": sha256_file(roots_path)},
        {"path": str(raw_path.relative_to(ROOT)), "sha256": sha256_file(raw_path)},
    ])


def main() -> int:
    temporal, temporal_sources = temporal_summary()
    oracle, oracle_sources = oracle_summary()
    rows = [temporal, oracle]
    output_json = ROOT / "paper/data/negative_results.json"
    output_csv = ROOT / "paper/data/negative_results.csv"
    output_json.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": 1,
        "generated_at_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "script": str(Path(__file__).resolve().relative_to(ROOT)),
        "script_sha256": sha256_file(Path(__file__).resolve()),
        "results": rows,
        "sources": temporal_sources + oracle_sources,
        "exclusions": [
            "PPO, expected-Q, and Turn Director exact estimates are excluded because surviving raw rows are absent."
        ],
    }
    output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    fields = list(rows[0])
    for row in rows[1:]:
        for key in row:
            if key not in fields:
                fields.append(key)
    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({row["experiment"]: {
        "effect": row["effect"], "ci": [row["ci_low"], row["ci_high"]], "n": row["n"]
    } for row in rows}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

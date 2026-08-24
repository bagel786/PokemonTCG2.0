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
TEMPORAL_EXPECTED = {
    "grim_b_final_confirmation_vs_d842_second_400pairs.json": (
        "0c15b56adf3b09c654505a152309fdc9f8401579a495da714347d98ae735003c", 3_100_000_000,
    ),
    "grim_b_final_confirmation_vs_master_v1_second_400pairs.json": (
        "8a06ebab47cc60ed981dfada85972eb8a62e732e349f01c2a3085262079f06e8", 3_110_000_000,
    ),
    "grim_b_final_confirmation_vs_replay_refresh_second_400pairs.json": (
        "30e45955b67893514c8ee077cac15d46fc207efe781cbce1b94242defda4cbdc", 3_120_000_000,
    ),
}
TEMPORAL_CANDIDATE = "8f7515b7db7013214d4de9487914273fd16255275545c1bb2c3e34493d2feba0"
TEMPORAL_CONTROL = "13426288358d597ead809e45c364c7f7b9274a6eebf55ddd942142e3326535c3"
SEEDED_ENGINE = "867e3f9bb87e0b48889a44b5d4b04f5d2d434b2a0788d1b2bcfe0caebcb5ab78"
PRODUCTION_ENGINE = "eae88634e26dc31d94150a4d8202fc9d32596b8c688ef67e14cb4088cd4d5771"
ORACLE_DIR = ROOT / "artifacts/grim_sequence_oracle_v0"
ORACLE_EXPECTED = {
    "manifest": "d5e66f88878591d7f2a6d0270c9949aa9f4e591bb44b2855f8e072c57bed6846",
    "roots": "fd98f2792f349e75a77917fb94c380b26409c604cdfb04de2622d3a418765032",
    "raw": "4fed0067e8a2c04533428459379d0b25abc07f4e9fadd08ff03ca3a5f389d953",
    "search_engine": "c257a121c07943c13b81cd276cfd6a88e035820e1678c64701a38692183b172e",
    "source_tree": "9c56d2cd64d55be9b6734dcdb55e32c6a8a8debaa92bff32f4429ee7a74fa547",
}
ORACLE_GATE_REPORT = {
    "commit": "def0c62a6cb804d8991df5c91a541037afc50cde",
    "path": "docs/GRIM_SEQUENCE_ORACLE_V0.md",
    "git_blob": "6a9e8e145e9e99dabde5bfa1bcd1a1794b926b40",
    "sha256": "780c754f351e966037cfb7fa2384b6568c1bf91e27ee37ddf8d598d0ca6303c2",
}


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
        expected_opponent, expected_base_seed = TEMPORAL_EXPECTED[path.name]
        exact_checks = {
            "candidate_sha256": TEMPORAL_CANDIDATE,
            "control_sha256": TEMPORAL_CONTROL,
            "opponent_sha256": expected_opponent,
            "engine_sha256": SEEDED_ENGINE,
            "base_seed": expected_base_seed,
            "games": 800,
            "pairs_per_order": 400,
            "workers": 8,
            "actual_orders": ["second"],
            "production_engine_preserved": True,
            "production_engine_sha256_before": PRODUCTION_ENGINE,
            "production_engine_sha256_after": PRODUCTION_ENGINE,
        }
        for field, expected in exact_checks.items():
            actual = payload.get(field)
            if isinstance(actual, str):
                actual = actual.lower()
            if actual != expected:
                raise ValueError(f"{path}: {field}={actual!r}, expected {expected!r}")
        if payload.get("rng_provenance") != {
            "deviceRand": False,
            "engine": "local_seeded_mt19937",
            "entrypoint": "BattleStartSeeded",
            "native_gameplay_random_device": False,
            "same_actual_order_and_physical_seat_within_pair": True,
            "same_seed_within_candidate_control_pair": True,
        }:
            raise ValueError(f"{path}: unexpected RNG provenance")
        if len(payload.get("rows", [])) != 800:
            raise ValueError(f"{path}: expected exactly 800 rows")
        arms = defaultdict(dict)
        for row in payload["rows"]:
            arm = row.get("arm")
            key = (row.get("actual_order"), row.get("pair_index"))
            if arm not in {"candidate", "control"}:
                raise ValueError(f"{path}: unknown arm {arm!r}")
            if arm in arms[key]:
                raise ValueError(f"{path}: duplicate arm {arm!r} for pair {key}")
            arms[key][arm] = row
        expected_keys = {("second", pair_index) for pair_index in range(400)}
        if set(arms) != expected_keys:
            raise ValueError(f"{path}: pair schedule differs from the 400 prescribed units")
        differences = []
        for key, pair in sorted(arms.items()):
            if set(pair) != {"candidate", "control"}:
                raise ValueError(f"{path}: incomplete pair {key}")
            candidate, control = pair["candidate"], pair["control"]
            for field in ("seed", "actual_order", "physical_seat"):
                if candidate[field] != control[field]:
                    raise ValueError(f"{path}: {field} mismatch")
            pair_index = key[1]
            expected_seed = expected_base_seed + 1_000_000 + pair_index
            if candidate["seed"] != expected_seed or candidate["physical_seat"] != pair_index % 2:
                raise ValueError(f"{path}: seed/seat schedule mismatch for pair {pair_index}")
            for arm, row in pair.items():
                if row.get("task_id") != f"second-{pair_index:05d}-{arm}":
                    raise ValueError(f"{path}: task ID mismatch for pair {pair_index}/{arm}")
                win, draw = row.get("win"), row.get("draw")
                if win not in {0, 1} or draw not in {0, 1} or win + draw > 1:
                    raise ValueError(f"{path}: invalid outcome for pair {pair_index}/{arm}")
                if int(row.get("hero_policy_errors", 0)) or int(row.get("opponent_policy_errors", 0)):
                    raise ValueError(f"{path}: policy error invalidates pair {pair_index}/{arm}")
            value = int(candidate["win"]) - int(control["win"])
            differences.append(value)
            candidate_wins += int(candidate["win"])
            control_wins += int(control["win"])
            candidate_only += int(value == 1)
            control_only += int(value == -1)
            errors += sum(int(pair[arm].get("hero_policy_errors", 0)) for arm in pair)
            errors += sum(int(pair[arm].get("opponent_policy_errors", 0)) for arm in pair)
        if len(differences) != 400:
            raise ValueError(f"{path}: expected 400 complete pairs")
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
    gate_object = f"{ORACLE_GATE_REPORT['commit']}:{ORACLE_GATE_REPORT['path']}"
    gate_bytes = subprocess.check_output(["git", "show", gate_object], cwd=ROOT)
    gate_blob = subprocess.check_output(
        ["git", "rev-parse", gate_object], cwd=ROOT, text=True
    ).strip()
    if (
        hashlib.sha256(gate_bytes).hexdigest() != ORACLE_GATE_REPORT["sha256"]
        or gate_blob != ORACLE_GATE_REPORT["git_blob"]
    ):
        raise ValueError("sequence-oracle historical gate report provenance mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if sha256_file(manifest_path) != ORACLE_EXPECTED["manifest"]:
        raise ValueError("sequence-oracle manifest digest mismatch")
    expected_raw = manifest["outputs"]["raw_results"]["sha256"].lower()
    expected_roots = manifest["outputs"]["roots"]["sha256"].lower()
    if expected_raw != ORACLE_EXPECTED["raw"] or expected_roots != ORACLE_EXPECTED["roots"]:
        raise ValueError("sequence-oracle manifest records unexpected output digests")
    if sha256_file(raw_path) != ORACLE_EXPECTED["raw"] or sha256_file(roots_path) != ORACLE_EXPECTED["roots"]:
        raise ValueError("sequence-oracle manifest digest mismatch")
    if manifest.get("coverage") != {
        "cleanup_errors": 0, "engine_errors": 0, "incomplete_rollouts": 0,
        "plan_world_errors": 0, "policy_errors": 0, "root_errors": 0, "roots": 60,
    }:
        raise ValueError("sequence-oracle coverage or error counts differ from frozen expectations")
    engine = manifest.get("engine", {})
    if (
        engine.get("seeded_search_sha256", "").lower() != ORACLE_EXPECTED["search_engine"]
        or engine.get("seeded_source_tree_sha256", "").lower() != ORACLE_EXPECTED["source_tree"]
        or engine.get("production_sha256_before", "").lower() != PRODUCTION_ENGINE
        or engine.get("production_sha256_after", "").lower() != PRODUCTION_ENGINE
        or engine.get("production_unchanged") is not True
    ):
        raise ValueError("sequence-oracle engine provenance mismatch")
    expected_packages = {
        "a2": TEMPORAL_CONTROL,
        "d842": TEMPORAL_EXPECTED["grim_b_final_confirmation_vs_d842_second_400pairs.json"][0],
        "master_v1": TEMPORAL_EXPECTED["grim_b_final_confirmation_vs_master_v1_second_400pairs.json"][0],
        "replay_refresh": TEMPORAL_EXPECTED["grim_b_final_confirmation_vs_replay_refresh_second_400pairs.json"][0],
    }
    for label, expected_hash in expected_packages.items():
        package = manifest.get("packages", {}).get(label, {})
        if (
            package.get("tree_sha256_before", "").lower() != expected_hash
            or package.get("tree_sha256_after", "").lower() != expected_hash
            or package.get("unchanged") is not True
        ):
            raise ValueError(f"sequence-oracle package provenance mismatch: {label}")

    root_ids = []
    with gzip.open(roots_path, "rt", encoding="utf-8") as handle:
        for line in handle:
            root = json.loads(line)
            root_ids.append(root.get("root_id"))
    if len(root_ids) != 60 or len(set(root_ids)) != 60 or any(not item for item in root_ids):
        raise ValueError("unexpected or duplicate sequence-oracle roots")
    root_values = []
    candidate_wins = baseline_wins = candidate_only = baseline_only = invalidated_worlds = 0
    result_root_ids = []
    with gzip.open(raw_path, "rt", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            root_id = record.get("root_id")
            if not root_id or root_id in result_root_ids:
                raise ValueError("missing or duplicate root ID in oracle results")
            result_root_ids.append(root_id)
            values = []
            worlds = record.get("confirmation", {}).get("worlds", [])
            if {world.get("world") for world in worlds} != set(range(16)):
                raise ValueError(f"oracle root {root_id}: unexpected world IDs")
            physical_seat = record.get("root", {}).get("physical_seat")
            if physical_seat not in {0, 1}:
                raise ValueError(f"oracle root {root_id}: invalid physical seat")
            for world in worlds:
                for arm in ("candidate", "baseline"):
                    outcome = world.get(arm, {})
                    win, draw = outcome.get("win"), outcome.get("draw")
                    if win not in {0, 1} or draw not in {0, 1} or win + draw > 1:
                        raise ValueError(f"oracle root {root_id}: invalid {arm} outcome")
                    if not isinstance(outcome.get("invalidated"), bool):
                        raise ValueError(f"oracle root {root_id}: malformed invalidation flag")
                    if arm == "baseline" and outcome.get("invalidated") is not False:
                        raise ValueError(f"oracle root {root_id}: baseline cannot be invalidated")
                    expected_result = physical_seat if win else (2 if draw else 1 - physical_seat)
                    if outcome.get("result") != expected_result:
                        raise ValueError(f"oracle root {root_id}: inconsistent {arm} result code")
                candidate = int(world["candidate"]["win"])
                baseline = int(world["baseline"]["win"])
                invalidated_worlds += int(world["candidate"]["invalidated"])
                value = candidate - baseline
                values.append(value)
                candidate_wins += candidate
                baseline_wins += baseline
                candidate_only += int(value == 1)
                baseline_only += int(value == -1)
            root_values.append(np.asarray(values, dtype=np.float32))
            if record.get("confirmation", {}).get("summary", {}).get("invalidated_worlds") != sum(
                int(world["candidate"]["invalidated"]) for world in worlds
            ):
                raise ValueError(f"oracle root {root_id}: invalidation summary mismatch")
    if set(result_root_ids) != set(root_ids):
        raise ValueError("oracle result/root files contain different root IDs")
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
        "candidate_plan_invalidated_worlds": invalidated_worlds,
        "effect": float(np.concatenate(root_values).mean()),
        "ci_low": percentile(bootstrap)[0],
        "ci_high": percentile(bootstrap)[1],
        "mcnemar_exact_two_sided_p": None,
        "mcnemar_omission_reason": (
            "Worlds are clustered within 60 roots; a world-level exact McNemar test would "
            "incorrectly treat the 960 worlds as independent."
        ),
        "method": "root-cluster bootstrap; 100000 draws",
        "errors": sum(int(manifest["coverage"][key]) for key in (
            "cleanup_errors", "engine_errors", "incomplete_rollouts",
            "plan_world_errors", "policy_errors", "root_errors",
        )),
        "scope": "second-own-turn roots; three fixed opponents; at most two deviations",
        "historically_reported_gate": 0.03,
        "gate_provenance_commit": ORACLE_GATE_REPORT["commit"],
        "gate_provenance_path": ORACLE_GATE_REPORT["path"],
        "gate_provenance_git_blob": ORACLE_GATE_REPORT["git_blob"],
        "gate_provenance_sha256": ORACLE_GATE_REPORT["sha256"],
        "gate_provenance_status": (
            "The report and gate-bearing implementation first entered reachable Git history "
            "with the result artifacts; advance specification is not independently verified."
        ),
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

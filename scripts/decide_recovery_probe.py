#!/usr/bin/env python3
"""Aggregate A1/A2 shards and emit the sole fail-closed upload decision."""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from training.promotion import aggregate_shards, evaluate_probe_gate


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def expand(pattern: str) -> list[str]:
    paths = sorted(glob.glob(pattern))
    if not paths:
        raise ValueError(f"pattern matched no shards: {pattern}")
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a1", default="artifacts/recovery_azure/shards/a1_shard_*.json")
    parser.add_argument("--a2", default="artifacts/recovery_azure/shards/a2_shard_*.json")
    parser.add_argument("--structural", default="artifacts/recovery_azure/shards/structural_shard_*.json")
    parser.add_argument("--authentic-manifest", required=True)
    parser.add_argument("--preflight-manifest", required=True)
    parser.add_argument("--output", default="artifacts/recovery_probes/promotion_manifest.json")
    args = parser.parse_args()

    candidates = {"a1": aggregate_shards(expand(args.a1)), "a2": aggregate_shards(expand(args.a2))}
    structural = aggregate_shards(expand(args.structural))
    builds = json.loads((ROOT / "artifacts" / "recovery_probes" / "build_manifest.json").read_text())
    build_by_name = {row["name"]: row for row in builds["artifacts"]}
    expected_trees = {
        "a1": build_by_name["a1_d842_shield"]["extracted_tree_sha256"].lower(),
        "a2": build_by_name["a2_v2_shield"]["extracted_tree_sha256"].lower(),
    }
    for name, aggregate_result in candidates.items():
        if aggregate_result["artifact_hashes"]["artifact_a_sha256"] != expected_trees[name]:
            raise ValueError(f"{name} result was not produced by the exact upload archive contents")
    if structural["artifact_hashes"]["artifact_a_sha256"] != build_by_name["d842_control_exact"]["extracted_tree_sha256"].lower():
        raise ValueError("structural control result does not match exact d842 archive contents")
    authentic_spec = json.loads(Path(args.authentic_manifest).read_text())
    authentic = {}
    for candidate_name in ("a1", "a2"):
        authentic[candidate_name] = {
            opponent: (
                aggregate_shards(expand(paths["candidate"])),
                aggregate_shards(expand(paths["control"])),
            )
            for opponent, paths in authentic_spec.get(candidate_name, {}).items()
        }
    decisions = {
        name: evaluate_probe_gate(result, structural, authentic[name])
        for name, result in candidates.items()
    }

    preflight = json.loads(Path(args.preflight_manifest).read_text())
    required_preflight = (
        "stored_replays_zero_exceptions",
        "synthetic_prevention_passed",
        "all_changes_classified",
        "sterile_ubuntu_passed",
        "kaggle_handshake_selfplay_passed",
    )
    preflight_passed = all(preflight.get(key) is True for key in required_preflight)
    for decision in decisions.values():
        decision["checks"]["all_preflight_checks"] = preflight_passed
        decision["passed"] = decision["passed"] and preflight_passed

    qualified = [name for name, decision in decisions.items() if decision["passed"]]
    selected = "d842_control_exact"
    if "a1" in qualified:
        selected = "a1"
        if "a2" in qualified:
            a2_lead = candidates["a2"]["win_rate"] - candidates["a1"]["win_rate"]
            no_seat_regression = all(
                candidates["a2"]["seat_results"][seat]["win_rate"]
                >= candidates["a1"]["seat_results"][seat]["win_rate"]
                for seat in ("0", "1")
            )
            no_matchup_regression = all(
                decisions["a2"]["authentic_opponents"][name]["difference"]
                >= decisions["a1"]["authentic_opponents"][name]["difference"]
                for name in decisions["a1"]["authentic_opponents"]
            )
            if a2_lead >= 0.02 and no_seat_regression and no_matchup_regression:
                selected = "a2"
    elif "a2" in qualified:
        selected = "a2"

    archives = {
        "a1": ROOT / "artifacts" / "recovery_probes" / "a1_d842_shield.tar.gz",
        "a2": ROOT / "artifacts" / "recovery_probes" / "a2_v2_shield.tar.gz",
        "d842_control_exact": ROOT / "artifacts" / "recovery_probes" / "d842_control_exact.tar.gz",
    }
    manifest = {
        "created_unix": time.time(),
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "promotion_result": "passed" if selected != "d842_control_exact" else "control_only",
        "selected": selected,
        "upload_order": [selected, "d842_control_exact"] if selected != "d842_control_exact" else ["d842_control_exact"],
        "exact_upload_archive": str(archives[selected]),
        "archives": {name: {"path": str(path), "sha256": sha256(path)} for name, path in archives.items()},
        "preflight": preflight,
        "decisions": decisions,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"promotion_result": manifest["promotion_result"], "selected": selected, "upload_order": manifest["upload_order"]}))
    return 0 if selected != "d842_control_exact" else 2


if __name__ == "__main__":
    raise SystemExit(main())

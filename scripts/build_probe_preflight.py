#!/usr/bin/env python3
"""Certify replay, synthetic, package, and clean-Ubuntu probe preflights."""

from __future__ import annotations

import argparse
import glob
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from training.evaluation_schema import load_evaluation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="artifacts/recovery_probes/preflight_manifest.json")
    args = parser.parse_args()
    replay = json.loads((ROOT / "artifacts" / "recovery_probes" / "replay_audit.json").read_text())
    builds = json.loads((ROOT / "artifacts" / "recovery_probes" / "build_manifest.json").read_text())
    build_by_name = {row["name"]: row for row in builds["artifacts"]}
    test = subprocess.run([
        sys.executable, "-m", "pytest", "-q",
        "tests/test_tactical_shield.py", "tests/test_prevention.py", "tests/test_safety.py",
    ], cwd=ROOT, capture_output=True, text=True)
    shard_paths = sorted(glob.glob(str(ROOT / "artifacts" / "recovery_azure" / "shards" / "*.json")))
    shards = []
    shard_errors = []
    for path in shard_paths:
        if Path(path).name.startswith("auth_"):
            continue
        try:
            shards.append(load_evaluation(path))
        except Exception as exc:
            shard_errors.append(f"{Path(path).name}: {type(exc).__name__}: {exc}")
    expected_names = {
        *(f"a1_shard_{index}.json" for index in range(1, 4)),
        *(f"a2_shard_{index}.json" for index in range(1, 4)),
        *(f"structural_shard_{index}.json" for index in range(1, 4)),
    }
    actual_names = {Path(path).name for path in shard_paths}
    complete_shards = expected_names <= actual_names and len(shards) >= 9 and not shard_errors
    zero_errors = complete_shards and all(
        row["hero_policy_errors"] == 0 and row["opponent_policy_errors"] == 0 for row in shards
    )
    worker_count = len({row["artifact_provenance"]["worker"] for row in shards}) if shards else 0
    manifest = {
        "stored_replays_zero_exceptions": replay.get("passed") is True
        and all(row["counts"].get("exceptions", 0) == 0 for row in (replay["a1"], replay["a2"])),
        "synthetic_prevention_passed": test.returncode == 0,
        "all_changes_classified": replay.get("passed") is True
        and all(row["counts"].get("unclassified_changes", 0) == 0 for row in (replay["a1"], replay["a2"])),
        "sterile_ubuntu_passed": complete_shards and zero_errors and worker_count >= 4,
        "kaggle_handshake_selfplay_passed": complete_shards and zero_errors
        and all(build_by_name[name]["sterile_validation"]["passed"] for name in ("a1_d842_shield", "a2_v2_shield")),
        "details": {
            "pytest_returncode": test.returncode,
            "pytest_stdout": test.stdout[-2000:],
            "replay_audit": replay,
            "evaluation_shards": len(shards),
            "evaluation_workers": worker_count,
            "evaluation_schema_errors": shard_errors,
            "zero_policy_errors": zero_errors,
        },
    }
    manifest["passed"] = all(manifest.get(key) is True for key in (
        "stored_replays_zero_exceptions", "synthetic_prevention_passed", "all_changes_classified",
        "sterile_ubuntu_passed", "kaggle_handshake_selfplay_passed",
    ))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in manifest.items() if isinstance(value, bool)}))
    return 0 if manifest["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

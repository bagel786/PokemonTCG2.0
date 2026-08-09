#!/usr/bin/env python3
"""Create the immutable fail-closed M0 replay/clone gate decision."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main() -> int:
    farm_path = ROOT / "artifacts" / "schema5_azure" / "training_farm_manifest.json"
    screen_path = ROOT / "artifacts" / "schema5_matrix_screen" / "matrix_screen.json"
    farm = json.loads(farm_path.read_text(encoding="utf-8"))
    screen = json.loads(screen_path.read_text(encoding="utf-8"))
    if farm.get("status") != "complete" or int(farm.get("job_count", 0)) != 72 or len(farm.get("results", [])) != 72:
        raise RuntimeError("incomplete M0 Azure matrix")
    if int(screen.get("models", 0)) != 60:
        raise RuntimeError("incomplete M0 identity screen")
    clone_results = [row for row in farm["results"] if row.get("kind") == "clone"]
    if len(clone_results) != 12:
        raise RuntimeError("incomplete clone matrix")
    best_clone = max(clone_results, key=lambda row: float(row["selected_complete_agreement"]))
    checks = {
        "all_60_candidate_seeds_screened": int(screen["models"]) == 60,
        "candidate_branching_uplift_at_least_8": int(screen["passing_models"]) > 0,
        "at_least_four_clones_at_82_agreement": sum(
            float(row["selected_complete_agreement"]) >= .82 for row in clone_results
        ) >= 4,
    }
    result = {
        "status": "passed" if all(checks.values()) else "failed",
        "decision": "eligible_for_gameplay_gate" if all(checks.values()) else "cancel_m0_no_upload",
        "checks": checks,
        "measurements": {
            "candidate_models": screen["models"],
            "candidate_passing_models": screen["passing_models"],
            "best_candidate_identity_screen": screen["best"],
            "clone_models": len(clone_results),
            "best_clone_complete_agreement": best_clone["selected_complete_agreement"],
            "best_clone": {key: best_clone[key] for key in ("name", "seed", "model", "model_sha256")},
        },
        "artifacts": {
            "farm_manifest": str(farm_path.resolve()), "farm_manifest_sha256": sha256(farm_path),
            "screen_manifest": str(screen_path.resolve()), "screen_manifest_sha256": sha256(screen_path),
            "training_bundle_sha256": farm["bundle_sha256"],
        },
        "upload_archive": None,
    }
    output = ROOT / "artifacts" / "schema5_m0" / "promotion_manifest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

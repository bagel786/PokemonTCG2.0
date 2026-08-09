#!/usr/bin/env python3
"""Fail-closed R0 agreement screen; gameplay is forbidden after a screen miss."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agreement", default="artifacts/recovery_r0/heldout_agreement.json")
    parser.add_argument("--heads", nargs=3, required=True)
    parser.add_argument("--output", default="artifacts/recovery_r0/promotion_manifest.json")
    args = parser.parse_args()
    agreement_path = Path(args.agreement)
    agreement = json.loads(agreement_path.read_text(encoding="utf-8"))
    required = {
        "status": agreement.get("status"),
        "records": agreement.get("records"),
        "complete_agreement_uplift_points": agreement.get("complete_agreement_uplift_points"),
        "episode_cluster_bootstrap_95_points": agreement.get("episode_cluster_bootstrap_95_points"),
    }
    if any(value is None for value in required.values()):
        raise RuntimeError(f"agreement report is incomplete: {required}")
    checks = {
        "report_complete": agreement["status"] == "complete",
        "minimum_records_1500": int(agreement["records"]) >= 1500,
        "agreement_uplift_at_least_8_points": float(agreement["complete_agreement_uplift_points"]) >= 8.0,
        "changed_to_expert_exceeds_changed_away": int(agreement["changed_to_expert"]) > int(agreement["changed_away"]),
    }
    passed = all(checks.values())
    manifest = {
        "candidate": "r0_play_binding_residual",
        "stage": "heldout_policy_screen",
        "passed": passed,
        "decision": "proceed_to_gameplay_gate" if passed else "retire_without_gameplay_or_upload",
        "thresholds": {"complete_agreement_uplift_points": 8.0, "minimum_records": 1500},
        "measurements": agreement,
        "checks": checks,
        "artifacts": {
            "agreement_report": str(agreement_path.resolve()),
            "agreement_report_sha256": sha256(agreement_path),
            "residual_heads": [
                {"path": str(Path(path).resolve()), "sha256": sha256(Path(path))}
                for path in args.heads
            ],
        },
        "upload_archive": None,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"passed": passed, "decision": manifest["decision"], "checks": checks}, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

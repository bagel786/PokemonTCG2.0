#!/usr/bin/env python3
"""Write the immutable fail-closed qualification decision for the 5k director."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "grim_5k_floor_director"
WORKERS = (
    ("ptcg-train-south-rg", "ptcg-train"),
    ("ptcg-recovery-centralus-rg", "grim-centralus"),
    ("ptcg-recovery-eastus2-rg", "grim-eastus2"),
    ("ptcg-recovery-northcentralus-rg", "grim-northcentralus"),
    ("ptcg-recovery-westus2-rg", "grim-westus2"),
)


def azure_snapshot():
    az = shutil.which("az.cmd") or shutil.which("az.bat") or shutil.which("az") or "az"
    rows = []
    for group, name in WORKERS:
        result = subprocess.run(
            [az, "vm", "get-instance-view", "-g", group, "-n", name,
             "--query", "instanceView.statuses[?starts_with(code, 'PowerState/')].displayStatus | [0]",
             "-o", "tsv"],
            cwd=ROOT, capture_output=True, text=True, timeout=60, check=False,
        )
        rows.append({
            "resource_group": group, "name": name,
            "power_state": result.stdout.strip() if result.returncode == 0 else None,
            "error": result.stderr.strip() if result.returncode else None,
        })
    return rows


def main():
    build = json.loads((OUT / "build_manifest.json").read_text(encoding="utf-8"))
    audit = json.loads((OUT / "replay_audit.json").read_text(encoding="utf-8"))
    workers = azure_snapshot()
    gates = {
        "frozen_inputs_and_build": bool(
            build.get("deterministic_double_build") and build.get("sterile_validation", {}).get("passed")
        ),
        "replay_determinism": bool(audit.get("determinism_gate")),
        "replay_safety": bool(audit.get("safety_gate")),
        "intervention_coverage": bool(audit.get("coverage_gate")),
        "sub850_proxy_strength": bool(audit.get("strength_proxy_gate")),
        "eight_world_rule_certification": False,
        "d842_10000_game_strength": False,
        "retention_5x2000_games": False,
        "active_pair_preupload": False,
    }
    failed = [name for name, passed in gates.items() if not passed]
    all_deallocated = bool(workers) and all(row.get("power_state") == "VM deallocated" for row in workers)
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_archive": build["archive"],
        "candidate_archive_sha256": build["archive_sha256"],
        "input_hashes": {
            "archive": build["base_archive_sha256"], "model": build["model_sha256"],
            "deck": build["deck_sha256"], "engine": build["engine_hashes"],
            "floor_policy": build["floor_policy_sha256"],
        },
        "historical_baseline": {
            "games": 123, "wins": 77, "win_rate": 0.6260162601626016,
            "label": "mixed-Grim evidence; not pure-d842 performance",
        },
        "gates": gates,
        "failed_gates": failed,
        "replay_evidence": {
            "source_episodes": audit["source_episodes"],
            "coverage": audit["coverage"], "holdout": audit["holdout"],
            "holdout_clustered_lower_bound": audit["holdout_clustered_lower_bound"],
            "holdout_first": audit["holdout_first"], "holdout_second": audit["holdout_second"],
            "decision_digest": audit["decision_digest"],
            "invalid_actions": audit["invalid_actions"], "exceptions": audit["exceptions"],
        },
        "evaluation": {
            "package_vs_package": "not_run_after_earlier_mandatory_gate_failure",
            "diagnostic_opponents": "not_run_after_earlier_mandatory_gate_failure",
        },
        "azure": {
            "incremental_spend_usd": 0.0, "authorized_cap_usd": 100.0,
            "workers": workers, "all_workers_deallocated": all_deallocated,
        },
        "deployment": {
            "qualified": False, "uploaded": False,
            "reason": "mandatory strength proxy gate failed; later gates were not run",
            "active_pair_check": "skipped because upload is prohibited",
            "automatic_second_upload": False,
        },
    }
    target = OUT / "promotion_manifest.json"
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if all_deallocated and not manifest["deployment"]["uploaded"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

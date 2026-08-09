#!/usr/bin/env python3
"""Delete only the explicitly named ephemeral recovery resource groups."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AZURE = shutil.which("az.cmd") or shutil.which("az") or "az"
EPHEMERAL_GROUPS = (
    "ptcg-recovery-centralus-rg",
    "ptcg-recovery-eastus-rg",
    "ptcg-recovery-eastus2-rg",
    "ptcg-recovery-northcentralus-rg",
    "ptcg-recovery-westus2-rg",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="required acknowledgement for deletion")
    parser.add_argument("--output", default="artifacts/recovery_azure/cleanup_manifest.json")
    args = parser.parse_args()
    existing = json.loads(subprocess.check_output(
        [AZURE, "group", "list", "--query", "[].name", "-o", "json"], cwd=ROOT, text=True
    ))
    targets = [name for name in EPHEMERAL_GROUPS if name.lower() in {item.lower() for item in existing}]
    manifest = {"targets": targets, "existing_groups": existing, "executed": args.execute, "timestamp": time.time()}
    if args.execute:
        for name in targets:
            subprocess.run([AZURE, "group", "delete", "-n", name, "--yes", "--no-wait"], cwd=ROOT, check=True)
        manifest["status"] = "deletion_requested"
    else:
        manifest["status"] = "dry_run"
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

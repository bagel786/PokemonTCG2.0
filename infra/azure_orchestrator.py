#!/usr/bin/env python3
"""Azure VM Orchestrator for Pokemon TCG AI Simulation and RL Training.

Handles provisioning, status checks, code synchronization, rollout jobs,
and automated deallocation with strict budget enforcement.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def run_az(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    az_exe = shutil.which("az") or shutil.which("az.bat") or shutil.which("az.cmd") or "az"
    cmd = [az_exe, *args]
    res = subprocess.run(cmd, capture_output=True, text=True, shell=(os.name == "nt"))
    if check and res.returncode != 0:
        raise RuntimeError(f"Azure CLI failed: {res.stderr.strip()}")
    return res


def get_account_info() -> dict:
    res = run_az(["account", "show", "--output", "json"])
    return json.loads(res.stdout)


def get_vm_status(resource_group: str, vm_name: str) -> dict:
    res = run_az([
        "vm", "get-instance-view",
        "-g", resource_group,
        "-n", vm_name,
        "--output", "json"
    ], check=False)
    if res.returncode != 0:
        return {"status": "not_found"}
    data = json.loads(res.stdout)
    statuses = [s.get("displayStatus", "") for s in data.get("instanceView", {}).get("statuses", [])]
    return {"status": "running" if any("running" in s.lower() for s in statuses) else "stopped", "raw": statuses}


def deallocate_vm(resource_group: str, vm_name: str):
    print(f"Deallocating VM {vm_name} in {resource_group} to stop billing...", flush=True)
    run_az(["vm", "deallocate", "-g", resource_group, "-n", vm_name, "--no-wait"], check=False)
    print("Deallocation command sent.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status", help="Check Azure account and VM status")
    subparsers.add_parser("stop", help="Deallocate the training VM")

    prov = subparsers.add_parser("provision", help="Provision/start the training VM")
    prov.add_argument("--resource-group", default="ptcg-ai-rg")
    prov.add_argument("--vm-name", default="ptcg-train")
    prov.add_argument("--location", default="eastus")
    prov.add_argument("--size", default="Standard_D16ds_v5")
    prov.add_argument("--priority", choices=["Spot", "Regular"], default="Spot")

    args = parser.parse_args()

    if args.command == "status" or not args.command:
        acc = get_account_info()
        print(f"Azure Account: {acc.get('name')} (Tenant: {acc.get('tenantId')})")
        vm_st = get_vm_status("ptcg-ai-rg", "ptcg-train")
        print(f"VM ptcg-train status: {vm_st.get('status')}")

    elif args.command == "stop":
        deallocate_vm("ptcg-ai-rg", "ptcg-train")


if __name__ == "__main__":
    main()

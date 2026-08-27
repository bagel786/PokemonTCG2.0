"""Genuine cross-process context replicas (repair T11/R17).

Runs one single-arm execution inside a fresh interpreter via sys.executable and
reports pid + start time + projection digest. Used whenever a construction
claims cross-process replay scope.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

WORKER_TEMPLATE = r'''
import json, os, sys, time
_venv_site = os.environ.get("PINNED_VENV_SITE")
if _venv_site and _venv_site not in sys.path:
    sys.path.append(_venv_site)
sys.path.insert(0, os.environ["PROSPECTIVE_REPAIR_ROOT"])
payload = json.loads(sys.stdin.read())
system = payload["system"]
seed = int(payload["seed"])
construction = payload["construction"]
from systems.mechanics import spec_from_construction, ExecutionSpec
from systems.holdem_wrapper import HoldemWrapper
from systems.ising_wrapper import IsingWrapper

# Reconstruct minimal spec: enough for the specific cross-proc construction
grammar = json.load(open(os.path.join(
    os.environ["PROSPECTIVE_REPAIR_ROOT"],
    "protocol", "FAULT_GRAMMAR.json")))
g = next(x for x in grammar["constructions"] if x["id"] == construction)
spec = spec_from_construction(g)
from systems.mechanics import PersistentStateFile
spec._persistent_state = PersistentStateFile(lambda: payload["state_dir"])
spec.declared_seed = seed
spec.context_scope = "cross_process"
spec.replay_scope_claimed = "cross_process"

if system == "holdem":
    w = HoldemWrapper()
    art = w.run_arm(seed=seed, arm="A", spec=spec, repeat_id="ctx",
                    context_id=f"xproc-{os.getpid()}", process_rank=1)
else:
    w = IsingWrapper(state_dir=payload["state_dir"])
    art = w.run_arm(seed=seed, temperature_arm="A", spec=spec,
                    repeat_id="ctx", context_id=f"xproc-{os.getpid()}",
                    process_rank=1)
print(json.dumps({"pid": os.getpid(), "digest": art["projection_digest"],
                  "wall_s": art["wall_s"]}))
'''


def run_cross_process_replica(root: str, system: str, construction: str,
                              seed: int, state_dir: str,
                              timeout: int = 180) -> dict:
    env = dict(os.environ)
    env["PROSPECTIVE_REPAIR_ROOT"] = root
    venv_site = root + "/../redesign/.venv/lib/python3.11/site-packages"
    env["PINNED_VENV_SITE"] = str(Path(venv_site).resolve())
    proc = subprocess.run(
        [sys.executable, "-c", WORKER_TEMPLATE],
        input=json.dumps({"system": system, "seed": seed,
                          "construction": construction,
                          "state_dir": state_dir}),
        capture_output=True, text=True, env=env, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"subprocess replica failed: {proc.stderr[-800:]}")
    line = [l for l in proc.stdout.strip().splitlines() if l.startswith("{")][-1]
    out = json.loads(line)
    out["process_separated"] = True
    out["proc_start_time"] = time.time()
    return out

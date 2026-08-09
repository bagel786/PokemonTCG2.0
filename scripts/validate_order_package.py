#!/usr/bin/env python3
"""Sterile load, deterministic replay, self-play, and latency audit for 5k+."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

VALIDATION = r'''
import importlib.util, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from cg.api import to_observation_class
from cg.game import battle_finish, battle_select, battle_start

spec=importlib.util.spec_from_file_location("submission_main", "main.py")
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
handshake={"select":None,"current":None,"logs":[]}
deck=module.agent(handshake); assert len(deck)==60
latencies=[]; decisions=0; deterministic=True
for _ in range(int(__import__('os').environ['PTCG_VALIDATION_GAMES'])):
 raw,started=battle_start(deck,deck); assert started.errorType==0
 try:
  while True:
   obs=to_observation_class(raw)
   if obs.current is not None and int(obs.current.result)>=0: break
   begin=time.perf_counter(); first=module.agent(raw); latencies.append(time.perf_counter()-begin)
   second=module.agent(raw); deterministic = deterministic and first == second
   raw=battle_select(first); decisions += 1
 finally: battle_finish()
errors=int(getattr(module._AGENT,'errors',0) or 0)
latencies.sort()
result={"games":int(__import__('os').environ['PTCG_VALIDATION_GAMES']),"decisions":decisions,
 "policy_errors":errors,"deterministic_replay":deterministic,
 "latency_p99_ms":1000*latencies[min(len(latencies)-1,int(len(latencies)*.99))],
 "latency_max_ms":1000*max(latencies)}
print(json.dumps(result))
assert deterministic and errors==0 and result["latency_p99_ms"] < 50.0
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--games", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="order-package-audit-") as temporary:
        stage = Path(temporary)
        with tarfile.open(args.archive, "r:gz") as archive:
            archive.extractall(stage, filter="data")
        environment = dict(os.environ)
        environment["PTCG_VALIDATION_GAMES"] = str(args.games)
        result = subprocess.run(
            [sys.executable, "-I", "-c", VALIDATION], cwd=stage, env=environment,
            text=True, capture_output=True, timeout=1200,
        )
        if result.returncode:
            raise RuntimeError(f"package validation failed:\n{result.stdout}\n{result.stderr}")
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Extract a submission archive and exercise its Kaggle entry point locally."""

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
import importlib.util, json, os, sys, time
from pathlib import Path
from cg.game import battle_start, battle_select, battle_finish
from cg.api import to_observation_class

# Kaggle's agent loader may execute main.py without defining __file__.  Exercise
# that path before the conventional import so a locally valid module cannot die
# during the remote validation handshake.
source=Path("main.py").read_text(encoding="utf-8")
exec_namespace={"__name__":"submission_entry"}
exec(compile(source,"main.py","exec"),exec_namespace)
exec_deck=exec_namespace["agent"]({"select":None,"logs":[],"current":None,"search_begin_input":None})
assert len(exec_deck)==60

spec=importlib.util.spec_from_file_location("submission_main", "main.py")
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
deck=module.agent({"select":None,"logs":[],"current":None,"search_begin_input":None})
assert len(deck)==60
games=int(os.environ.get("PTCG_VALIDATION_GAMES","1")); decisions=0; latencies=[]; errors=0
for game in range(games):
 raw,start=battle_start(deck,deck); assert start.errorType==0
 try:
  while True:
   obs=to_observation_class(raw)
   if obs.current is not None and obs.current.result != -1: break
   begin=time.perf_counter(); action=module.agent(raw); latencies.append(time.perf_counter()-begin)
   raw=battle_select(action); decisions+=1
 finally:
  battle_finish()
errors=getattr(getattr(module,"_AGENT",None),"errors",0)
latencies.sort()
print(json.dumps({"games":games,"decisions":decisions,"policy_errors":errors,"latency_p99_ms":1000*latencies[min(len(latencies)-1,int(len(latencies)*.99))],"latency_max_ms":1000*max(latencies)}))
assert errors==0
'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive")
    parser.add_argument("--games", type=int, default=1)
    args = parser.parse_args()
    archive = Path(args.archive).resolve()
    with tempfile.TemporaryDirectory(prefix="ptcg-validate-") as temporary:
        stage = Path(temporary)
        with tarfile.open(archive, "r:gz") as bundle:
            bundle.extractall(stage, filter="data")
        result = subprocess.run(
            [sys.executable, "-c", VALIDATION],
            cwd=stage,
            text=True,
            capture_output=True,
            timeout=600,
            env={**os.environ, "PTCG_VALIDATION_GAMES": str(args.games)},
        )
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr, file=sys.stderr)
            return result.returncode
        print(result.stdout.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

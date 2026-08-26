"""Stage B. This module intentionally has no truth/scenario dependency."""
from __future__ import annotations
import argparse,json,time
from pathlib import Path
from redesign_v2.framework.canonical_framework import decide
from redesign_v2.benchmark.design import METHODS,SUBCLAIMS

VOCAB={"ADMIT","DOWNGRADE","SUPPRESS","FAIL_CLOSED","ABSTAIN_NOT_EVALUATED"}
def validate(infile:Path,outfile:Path):
 rows=[]
 for line in infile.read_text().splitlines():
  case=json.loads(line); ev=case["observed_evidence"]
  for method,caps in METHODS.items():
   for claim in SUBCLAIMS:
    t=time.perf_counter_ns()
    decision=decide(claim,ev) if claim in caps else "ABSTAIN_NOT_EVALUATED"
    runtime=time.perf_counter_ns()-t
    rec={"case_id":case["case_id"],"method":method,"subclaim":claim,"decision":decision,"runtime_ns":runtime}
    rec["evidence_bytes"]=len(json.dumps({"claim":claim,"evidence":ev},sort_keys=True,separators=(",",":"))) if claim in caps else 0
    assert decision in VOCAB;rows.append(rec)
 outfile.parent.mkdir(parents=True,exist_ok=True)
 with outfile.open("w") as f:
  for r in rows:f.write(json.dumps(r,sort_keys=True,separators=(",",":"))+"\n")
 return len(rows)
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--input",type=Path,required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args();print(validate(a.input,a.output))

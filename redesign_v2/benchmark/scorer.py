"""Stage C: join frozen decisions to hidden, construction-derived truth."""
from __future__ import annotations
import argparse,json,hashlib
from pathlib import Path
from redesign_v2.framework.canonical_framework import decide
from redesign_v2.benchmark.design import METHODS,SUBCLAIMS
def load(p):return [json.loads(x) for x in p.read_text().splitlines()]
def score(decisions:Path,truth_path:Path,out:Path):
 truth={r["case_id"]:r for r in load(truth_path)}; rows=[]
 for d in load(decisions):
  t=truth[d["case_id"]]; applicable=d["subclaim"] in METHODS[d["method"]]
  expected=decide(d["subclaim"],t["construction_facts"]) if applicable else "ABSTAIN_NOT_EVALUATED"
  rows.append({**d,"system":t["system"],"scenario":t["scenario"],"seed":t["seed"],"expected":expected,"applicable":applicable,"correct":d["decision"]==expected})
 out.parent.mkdir(parents=True,exist_ok=True)
 with out.open("w") as f:
  for r in rows:f.write(json.dumps(r,sort_keys=True,separators=(",",":"))+"\n")
 return len(rows)
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--decisions",type=Path,required=True);p.add_argument("--truth",type=Path,required=True);p.add_argument("--out",type=Path,required=True);a=p.parse_args();print(score(a.decisions,a.truth,a.out))

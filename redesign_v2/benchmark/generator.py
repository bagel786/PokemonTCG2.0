"""Stage A: generate opaque validator bundles and a separately stored truth vault."""
from __future__ import annotations
import argparse,gzip,json,os
from pathlib import Path
from .design import SCENARIOS,construction_facts
from .rng_manager import sha256_id
from .systems import RUNNERS

def contexts(s): return ["tight_budget","ample_budget"] if s=="S4" else (["fresh","reused"] if s=="S5" else (["fifo","reverse"] if s=="S6" else ["declared"]))
def write_jsonl(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w") as f:
        for r in rows:f.write(json.dumps(r,sort_keys=True,separators=(",",":"))+"\n")
def write_jsonl_gz(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with gzip.open(path,"wt") as f:
        for r in rows:f.write(json.dumps(r,sort_keys=True,separators=(",",":"))+"\n")

def generate(out:Path,seeds:list[int],mode:str):
    evidence=[];truth=[];artifacts=[]
    for system in ("holdem","ising"):
      for scenario in SCENARIOS:
       for seed_index,seed in enumerate(seeds):
        case_id=sha256_id({"campaign":"v2","mode":mode,"system":system,"scenario":scenario,"seed_index":seed_index})[:32]
        facts=construction_facts(scenario); ctxs=contexts(scenario)
        runs=[]
        for ctx in ctxs:
          for repeat in (0,1):
            for arm in ("A","B"):
              runs.append(RUNNERS[system](seed,arm,repeat,scenario,ctx))
        # Mechanism-derived observable facts; scenario names are not serialized to validator input.
        by={(r["context"],r["repeat"],r["arm"]):r for r in runs}
        c0=ctxs[0]
        same=all(by[(c0,0,a)]["trace_sha256"]==by[(c0,1,a)]["trace_sha256"] for a in ("A","B"))
        cross=all(by[(ctxs[0],0,a)]["trace_sha256"]==by[(ctxs[-1],0,a)]["trace_sha256"] for a in ("A","B"))
        observed=dict(facts); observed["same_context_repeat_stable"]=same;observed["cross_context_repeat_stable"]=cross
        if scenario=="S7" and seed_index%3==2: observed["rows_complete"]=False
        evidence_artifacts=[]
        for r in runs:
          safe={k:v for k,v in r.items() if k not in {"declared_seed"}}
          aid=sha256_id({"case":case_id,"arm":r["arm"],"context":r["context"],"repeat":r["repeat"]})[:24]
          safe["artifact_id"]=aid
          event_values=safe.get("chance_events",safe.get("event_log",[]))
          public={k:v for k,v in safe.items() if k not in {"chance_events","event_log","actions","trajectory"}}
          public.update({"event_count":len(event_values),"event_log_sha256":sha256_id(event_values)})
          if "actions" in safe: public["policy_identities"]=sorted({x["policy_identity"] for x in safe["actions"]})
          evidence_artifacts.append(public)
          artifacts.append({"case_id":case_id,**safe})
        evidence.append({"case_id":case_id,"system_family":system,"declared_schedule":{"unit_id":sha256_id({"case":case_id,"seed":seed})[:20],"condition_labels":["A","B"],"contexts":ctxs,"repeat_count":2,"evaluation_order_randomized":True},"statistical_design":{"branch_b_model":observed["branch_b_model"]},"observed_evidence":observed,"artifacts":evidence_artifacts})
        truth.append({"case_id":case_id,"system":system,"scenario":scenario,"seed":seed,"seed_index":seed_index,"construction_facts":facts})
    write_jsonl(out/"validator_input"/"cases.jsonl",evidence)
    write_jsonl(out/"truth_vault"/"ground_truth.jsonl",truth)
    write_jsonl_gz(out/"raw"/"artifacts.jsonl.gz",artifacts)
    manifest={"mode":mode,"cases":len(evidence),"seeds":len(seeds),"validator_input_sha256":sha256_id(evidence),"truth_sha256":sha256_id(truth)}
    (out/"generation_manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
    return manifest

if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--out",type=Path,required=True);p.add_argument("--seeds",required=True);p.add_argument("--mode",required=True)
 a=p.parse_args();print(json.dumps(generate(a.out,[int(x) for x in a.seeds.split(",")],a.mode),indent=2))

"""Known-truth hierarchical Gaussian oracle and final raw bank writer."""
from __future__ import annotations
import argparse,gzip,json,math
from pathlib import Path
import numpy as np
from scipy import stats

CONFIGS={
 "O0":dict(delta=0.0,rho=0.0,cluster_sd=0.0,repeats=1,paired=True),
 "O1":dict(delta=0.0,rho=0.6,cluster_sd=0.0,repeats=1,paired=True),
 "O2":dict(delta=0.5,rho=0.0,cluster_sd=0.0,repeats=1,paired=True),
 "O3":dict(delta=0.5,rho=0.6,cluster_sd=0.0,repeats=1,paired=True),
 "O4":dict(delta=0.5,rho=0.3,cluster_sd=0.8,repeats=3,paired=True),
 "O5":dict(delta=0.0,rho=0.3,cluster_sd=1.0,repeats=4,paired=True),
 "O6":dict(delta=0.5,rho=0.0,cluster_sd=0.5,repeats=1,paired=False),
 "O7":dict(delta=0.5,rho=0.4,cluster_sd=0.6,repeats=2,paired=True),
}
def _test(d,truth):
 n=len(d); est=float(np.mean(d)); se=float(np.std(d,ddof=1)/math.sqrt(n)); crit=float(stats.t.ppf(.975,n-1)); lo,hi=est-crit*se,est+crit*se
 p=float(2*stats.t.sf(abs(est/se),n-1)) if se else (0.0 if est else 1.0)
 return est,se,lo,hi,p,lo<=truth<=hi
def generate(out:Path,root_seed:int,reps:int=1000,n:int=80):
 out.mkdir(parents=True,exist_ok=True); obs_path=out/"oracle_observations.jsonl.gz"; result_path=out/"oracle_dataset_results.jsonl"
 with gzip.open(obs_path,"wt") as obs, result_path.open("w") as results:
  for ci,(name,c) in enumerate(CONFIGS.items()):
   cov=np.array([[1,c["rho"]],[c["rho"],1.]])
   for rep in range(reps):
    rng=np.random.Generator(np.random.Philox(np.random.SeedSequence([root_seed,ci,rep])))
    ua=rng.normal(0,c["cluster_sd"],n); ub=ua if c["paired"] else rng.normal(0,c["cluster_sd"],n)
    unit_a=[];unit_b=[];naive=[]
    for i in range(n):
     av=[];bv=[]
     for j in range(c["repeats"]):
      e=rng.multivariate_normal([0,0],cov) if c["paired"] else rng.normal(size=2)
      ya=c["delta"]/2+ua[i]+e[0];yb=-c["delta"]/2+ub[i]+e[1]
      pair=f"{name}:{rep}:{i}" if c["paired"] else None
      for arm,y,cluster in (("A",ya,f"A:{i}" if not c["paired"] else str(i)),("B",yb,f"B:{i}" if not c["paired"] else str(i))):
       obs.write(json.dumps({"configuration":name,"replicate":rep,"unit_id":i,"cluster_id":cluster,"repeat_id":j,"condition":arm,"outcome":float(y),"crn_pair_id":pair,"root_seed":root_seed},separators=(",",":"))+"\n")
      av.append(ya);bv.append(yb);naive.append(ya-yb)
     unit_a.append(np.mean(av));unit_b.append(np.mean(bv))
    a=np.asarray(unit_a);b=np.asarray(unit_b)
    if c["paired"]:
     methods={"paired_unit":_test(a-b,c["delta"]),"naive_repeat":_test(np.asarray(naive),c["delta"])}
    else:
     est=float(a.mean()-b.mean());se=float(math.sqrt(a.var(ddof=1)/n+b.var(ddof=1)/n));crit=float(stats.t.ppf(.975,2*n-2));lo,hi=est-crit*se,est+crit*se;p=float(2*stats.t.sf(abs(est/se),2*n-2));methods={"unpaired_welch":(est,se,lo,hi,p,lo<=c["delta"]<=hi)}
    for method,(est,se,lo,hi,p,covered) in methods.items():
     results.write(json.dumps({"configuration":name,"replicate":rep,"method":method,"n_units":n,"n_repeats":c["repeats"],"truth_delta":c["delta"],"estimate":est,"se":se,"ci_lo":lo,"ci_hi":hi,"p_value":p,"reject_null":p<.05,"covered":covered,"theoretical_difference_variance":2+2*c["cluster_sd"]**2-2*(c["cluster_sd"]**2+c["rho"]) if c["paired"] else 2+2*c["cluster_sd"]**2},separators=(",",":"))+"\n")
 manifest={"root_seed":root_seed,"replicates_per_configuration":reps,"units_per_replicate":n,"sample_size_points":[20,40,80],"configurations":CONFIGS,"known_zero":["O0","O1","O5"],"known_nonzero":["O2","O3","O4","O6","O7"]}
 (out/"oracle_generation_manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n");return manifest
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--out",type=Path,required=True);p.add_argument("--seed",type=int,required=True);p.add_argument("--reps",type=int,default=1000);p.add_argument("--n",type=int,default=80);a=p.parse_args();print(json.dumps(generate(a.out,a.seed,a.reps,a.n),indent=2))

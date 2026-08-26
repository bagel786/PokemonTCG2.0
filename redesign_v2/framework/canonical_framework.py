"""Canonical V2 claim definitions. Generated files must not be hand edited."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BRANCHES = {
 "A":{"name":"matched descriptive","question":"Did runs share declared schedule fields and denominator?","subclaims":["A"]},
 "B":{"name":"statistically paired inference","question":"What sampling/design mechanism makes observations paired units?","subclaims":["B"]},
 "C":{"name":"replay/repeatability","question":"Are declared projections repeatable over every context named by the claim?","subclaims":["C1","C2"]},
 "D":{"name":"common-random-number coupling","question":"Is coupling valid, and separately is it beneficial?","subclaims":["D1","D2"]},
 "E":{"name":"event-aligned stochastic coupling","question":"Do corresponding exogenous events receive corresponding random quantities?","subclaims":["E"]},
}
REQUIREMENTS = {
 "A":["artifact_a_identified","artifact_b_identified","declared_seed","seed_interpretation_matches_declaration","context_declared","rows_complete","grouping_correct"],
 "B":{"any_of":["probability_sampled_unit","repeated_measures_design","treatment_randomized","hierarchical_model","defended_joint_stochastic_model"],"separate_facts":["seed_sampled_from_declared_distribution","treatment_randomized","evaluation_order_randomized","repeated_measures_design","probability_sampled_unit","hierarchical_model","defended_joint_stochastic_model"]},
 "C1":["canonical_trace_sha256","same_context_repeat_tested","same_context_repeat_stable"],
 "C2":["canonical_trace_sha256","all_named_contexts_tested","cross_context_repeat_stable"],
 "D1":["coupling_specified","shared_and_independent_streams_specified","marginals_preserved","no_stream_collision"],
 "D2":["D1_valid","covariance_estimated","paired_variance_estimated","independent_variance_estimated","variance_ratio_with_uncertainty"],
 "E":["stable_event_ontology","exogenous_event_ids","event_values_logged","event_keyed_rng","dependence_assumptions"],
}
WORDING = {
 "A":"schedule-matched descriptive comparison",
 "B":"paired inference under the declared sampling/design model",
 "C1":"repeatable in the declared context",
 "C2":"repeatable across the named contexts",
 "D1":"valid common-random-number coupling under the declared construction",
 "D2":"measured variance benefit" ,
 "E":"event-aligned stochastic coupling under the declared ontology",
 "forbidden_without_extra_model":["causal effect","counterfactual proof","all possible failure modes"],
}
GRAPH = {"start":"intended_claim","routes":{k:v["subclaims"] for k,v in BRANCHES.items()},"cumulative":False,
 "rules":["B does not depend on C/D/E unless the declared B model explicitly incorporates that evidence","C scope selects C1 or C2","D1 does not imply D2","unknown evidence never strengthens a claim"]}

def decide(subclaim:str, evidence:dict)->str:
    """Fail closed; UNKNOWN is never truthy. B consumes design facts only."""
    if subclaim == "B":
        declared=evidence.get("branch_b_model")
        bases=set(REQUIREMENTS["B"]["any_of"])
        if declared not in bases: return "FAIL_CLOSED"
        return "ADMIT" if evidence.get(declared) is True else "SUPPRESS"
    req=REQUIREMENTS[subclaim]
    vals=[evidence.get(x) for x in req]
    if any(v is None or v == "UNKNOWN" for v in vals): return "FAIL_CLOSED"
    if subclaim == "D2" and all(vals):
        return "ADMIT" if evidence.get("variance_ratio",float("inf")) < 1 else "DOWNGRADE"
    return "ADMIT" if all(vals) else "SUPPRESS"

def generate()->None:
    payloads={
      "claim_classes_v2.json":BRANCHES,
      "evidence_requirements_v2.json":REQUIREMENTS,
      "decision_graph_v2.json":GRAPH,
      "permitted_wording_v2.json":WORDING,
    }
    for name,obj in payloads.items(): (ROOT/name).write_text(json.dumps(obj,indent=2,sort_keys=True)+"\n")
    lines=["# Claim-Specific Framework V2","","Generated from `canonical_framework.py`; do not edit manually.",""]
    for key,v in BRANCHES.items():
      lines += [f"## {key} — {v['name'].title()}","",v["question"],"",f"Subclaims: {', '.join(v['subclaims'])}.",""]
    lines += ["## Non-cumulative invariant","","Evidence for one branch does not establish another branch. D1 validity and D2 benefit are separate; Branch E supports no causal wording.",""]
    (ROOT/"CLAIM_SPECIFIC_FRAMEWORK_V2.md").write_text("\n".join(lines))

if __name__ == "__main__": generate()

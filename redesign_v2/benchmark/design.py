"""Frozen-by-commit design semantics shared by generation and truth derivation."""
SCENARIOS=[f"S{i}" for i in range(11)]
SUBCLAIMS=["A","B","C1","C2","D1","D2","E"]
METHODS={
 "schedule_check":["A"],
 "paired_design_check":["B"],
 "trace_repeat_check":["C1","C2"],
 "crn_validator":["D1","D2"],
 "event_alignment_validator":["E"],
 "full_claim_router":["A","B","C1","C2","D1","D2","E"],
}

def construction_facts(scenario):
    f={"artifact_a_identified":True,"artifact_b_identified":True,"declared_seed":True,"seed_interpretation_matches_declaration":True,"context_declared":True,"rows_complete":True,"grouping_correct":True,
       "seed_sampled_from_declared_distribution":True,"treatment_randomized":False,"evaluation_order_randomized":True,"repeated_measures_design":True,"probability_sampled_unit":True,"hierarchical_model":True,"defended_joint_stochastic_model":True,"branch_b_model":"repeated_measures_design",
       "canonical_trace_sha256":True,"same_context_repeat_tested":True,"same_context_repeat_stable":True,"all_named_contexts_tested":True,"cross_context_repeat_stable":True,
       "coupling_specified":False,"shared_and_independent_streams_specified":True,"marginals_preserved":True,"no_stream_collision":True,
       "D1_valid":False,"covariance_estimated":True,"paired_variance_estimated":True,"independent_variance_estimated":True,"variance_ratio_with_uncertainty":True,"variance_ratio":1.0,
       "stable_event_ontology":False,"exogenous_event_ids":False,"event_values_logged":True,"event_keyed_rng":False,"dependence_assumptions":True}
    if scenario=="S1": f["seed_interpretation_matches_declaration"]=False
    if scenario=="S3": f.update({"coupling_specified":True,"D1_valid":True,"stable_event_ontology":True,"exogenous_event_ids":True,"event_keyed_rng":True,"variance_ratio":0.8})
    if scenario=="S4": f["cross_context_repeat_stable"]=False
    if scenario=="S5": f["cross_context_repeat_stable"]=False
    if scenario=="S6": f["cross_context_repeat_stable"]=False
    if scenario=="S7": f["rows_complete"]=False
    if scenario=="S8": f["same_context_repeat_stable"]=False;f["cross_context_repeat_stable"]=False
    if scenario=="S9": f.update({"repeated_measures_design":False,"probability_sampled_unit":False,"hierarchical_model":False,"defended_joint_stochastic_model":False})
    if scenario=="S10": f.update({"repeated_measures_design":False,"probability_sampled_unit":False,"hierarchical_model":False,"defended_joint_stochastic_model":False,"branch_b_model":"repeated_measures_design"})
    return f

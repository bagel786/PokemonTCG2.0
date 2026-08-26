#!/usr/bin/env python3
"""Canonical source for the Claim-Specific Validation Framework (CSVF).

Single source of truth. Running this script regenerates:
  - CLAIM_SPECIFIC_FRAMEWORK.md   (human readable)
  - claim_classes.json
  - evidence_requirements.json
  - permitted_wording.json
  - decision_graph.json

Edit THIS FILE ONLY; never hand-edit generated outputs.
"""

import json
import os
from collections import OrderedDict

FRAMEWORK_META = OrderedDict([
    ("name", "Claim-Specific Validation Framework"),
    ("short_name", "CSVF"),
    ("version", "1.0.0-prospective"),
    ("frozen_date", "2026-08-26"),
    ("central_question", "What exact scientific claim does the evaluator want to make?"),
    ("core_principle",
     "Evidence requirements attach to the inferential objective of the claim, "
     "not to a universal cumulative ladder. A researcher may legitimately satisfy "
     "Branch B without satisfying Branches C or E whenever the statistical design "
     "alone supports the paired inference."),
    ("anti_pattern",
     "The superseded cumulative 'validity ladder' treated deterministic replay and "
     "event alignment as prerequisites for every paired claim. This over-requires "
     "evidence and suppresses valid analyses."),
])

# ---------------------------------------------------------------------------
# Evidence predicate registry (id -> definition). Referenced by claim classes.
# ---------------------------------------------------------------------------
EVIDENCE_REGISTRY = OrderedDict([
    # Branch A
    ("artifact_identity", "Each recorded run carries a verifiable artifact identifier (code version, model/binary hash, configuration hash)."),
    ("schedule_identity", "Declared schedule fields (seed, opponent/context condition, row identifiers) match across compared runs."),
    ("complete_rows", "All scheduled rows are present in the analysis denominator; missing rows are detected, not silently dropped."),
    ("correct_grouping", "Runs are grouped into analysis units by the declared grouping key (e.g., seed-condition cluster)."),
    # Branch B
    ("randomized_assignment", "Conditions were assigned to units by a documented randomization procedure."),
    ("probability_sampling", "Units were drawn by a documented probability sampling scheme from a declared frame."),
    ("repeated_measures_design", "The design declares within-unit repeated measurement whose correlation structure the analysis models."),
    ("hierarchical_model", "The analysis uses a model with explicit cluster/hierarchy structure matching the data-generating process."),
    ("defended_joint_stochastic_model", "A joint stochastic model for paired outcomes is stated and its assumptions defended against the observed design."),
    # Branch C
    ("within_artifact_repeated_executions", "The same artifact was executed multiple times under declared identical conditions."),
    ("declared_trace_projection", "A declared, finite projection of the execution trace (fields, ordering, comparison rule) is specified before comparison."),
    ("context_testing", "Execution was repeated across process instances, worker reuse states, and execution contexts to expose nondeterminism."),
    ("exact_repeatability_criteria", "An exact equality criterion on the declared trace projection is declared before testing."),
    # Branch D
    ("specified_coupling_construction", "The common-random-number coupling construction is fully specified (which streams, substreams, draws are shared)."),
    ("preserved_marginals", "The coupling preserves each arm's marginal distributions (verified empirically or argued structurally)."),
    ("measured_covariance", "Cross-arm covariance induced by the coupling is estimated from replicated pairs."),
    ("measured_variance_reduction", "Variance of the paired difference is compared against independent-sampling variance on the same budget."),
    ("synchronization_assumptions", "Assumptions about stream synchronization across arms are declared (and tested where possible)."),
    # Branch E
    ("stable_event_identifiers", "Semantic events carry identifiers that are stable across policies/algorithms (declared event ontology)."),
    ("event_value_records", "Random quantities delivered at each semantic event are recorded with their event keys."),
    ("event_keyed_streams_or_validated_equivalent", "Event-keyed random streams exist, or an equivalent validated construction is documented."),
    ("declared_event_ontology", "The event ontology (what counts as an event, its granularity) is declared before acquisition."),
    ("dependence_assumptions", "Assumptions under which event-level equality implies distribution-level coupling validity are stated."),
])

# ---------------------------------------------------------------------------
# Claim classes (Branches A-E).
# ---------------------------------------------------------------------------
CLAIM_CLASSES = [
    OrderedDict([
        ("id", "BRANCH_A"),
        ("order", 1),
        ("name", "Matched Descriptive Comparison"),
        ("question", "Do these recorded runs share the declared schedule?"),
        ("example_claim", "These recorded runs shared declared schedule fields."),
        ("description",
         "A descriptive claim that two or more recorded runs used the same declared "
         "schedule (seed value, context/opponent, row identity). No statistical or "
         "causal inference is made; no replay is implied."),
        ("required_evidence", ["artifact_identity", "schedule_identity", "complete_rows", "correct_grouping"]),
        ("explicitly_not_required", ["exact_replay_of_execution", "identical_trace_projection", "event_alignment"]),
        ("permitted_wording", [
            "the runs shared the declared seed value and schedule fields",
            "runs were matched on recorded schedule fields",
            "the schedule was complete for {n}/{n} scheduled rows",
        ]),
        ("forbidden_wording", [
            "the runs are replicates of one another",
            "the executions were identical",
            "paired estimates are valid because seeds match",
        ]),
    ]),
    OrderedDict([
        ("id", "BRANCH_B"),
        ("order", 2),
        ("name", "Statistically Paired Inference"),
        ("question", "Does the paired estimator's reference distribution have a justified basis?"),
        ("example_claim", "The paired estimator and uncertainty procedure have a justified reference distribution."),
        ("description",
         "A claim that a paired difference estimator and its uncertainty have a valid "
         "statistical justification via randomized assignment, probability sampling, "
         "repeated-measures design, hierarchical modeling, or a defended joint stochastic model."),
        ("required_evidence", [
            "at_least_one_of:[randomized_assignment,probability_sampling,repeated_measures_design,hierarchical_model,defended_joint_stochastic_model]",
            "correct_grouping",
            "complete_rows",
        ]),
        ("explicitly_not_required", ["exact_replay_of_execution", "event_alignment"]),
        ("permitted_wording", [
            "under the randomized/repeated-measures design, the paired difference estimator has a justified reference distribution",
            "pairing is justified by the declared assignment mechanism",
            "uncertainty was obtained by the prespecified procedure under assumption X",
        ]),
        ("forbidden_wording", [
            "seeds were shared, therefore pairing is exact",
            "paired inference requires no assumptions because seeds match",
            "the interval is an exact confidence interval (without justified sampling interpretation)",
        ]),
    ]),
    OrderedDict([
        ("id", "BRANCH_C"),
        ("order", 3),
        ("name", "Deterministic Replay"),
        ("question", "Does repeating the same artifact reproduce the declared trace projection?"),
        ("example_claim", "Repeating the same artifact under declared conditions reproduces the declared trace projection exactly."),
        ("description",
         "A claim about execution repeatability of one artifact: repeated executions under "
         "declared conditions produce byte-identical declared trace projections across "
         "processes, workers, and contexts."),
        ("required_evidence", [
            "within_artifact_repeated_executions",
            "declared_trace_projection",
            "context_testing",
            "exact_repeatability_criteria",
        ]),
        ("explicitly_not_required", ["event_alignment", "cross_arm_coupling"]),
        ("permitted_wording", [
            "K/K repeated executions reproduced the declared projection of the trace exactly",
            "execution is repeatable under the declared conditions and projection scope",
            "no mismatch was found in the declared projection across tested contexts",
        ]),
        ("forbidden_wording", [
            "the system is deterministic (unscoped)",
            "replay holds, therefore cross-arm comparisons are aligned",
            "any trace field matches (beyond the declared projection)",
        ]),
    ]),
    OrderedDict([
        ("id", "BRANCH_D"),
        ("order", 4),
    ("name", "Common-Random-Number Variance Reduction"),
    ("question", "Does shared randomness create a valid coupling that improves comparison precision?"),
    ("example_claim", "Shared randomness creates a valid coupling that improves comparison precision."),
    ("description",
     "A claim that a CRN-style coupling between two configurations preserves marginals, "
     "induces measurable positive covariance, and reduces variance of the paired "
     "difference relative to independent sampling on the same replication budget."),
    ("required_evidence", [
        "specified_coupling_construction",
        "preserved_marginals",
        "measured_covariance",
        "measured_variance_reduction",
        "synchronization_assumptions",
    ]),
    ("explicitly_not_required", ["within_artifact_exact_replay", "semantic_event_equality"]),
    ("permitted_wording", [
        "the declared coupling reduced variance of the paired difference by factor r versus independent sampling",
        "marginal distributions were preserved under the coupling (verified by test T)",
        "cross-arm covariance was positive and synchronized as assumed",
    ]),
        ("forbidden_wording", [
            "CRN applies because seeds match (without marginal preservation and variance evidence)",
            "variance reduction generalizes beyond the measured scenario",
            "repeatability alone demonstrates coupling validity",
        ]),
    ]),
]

CLAIM_CLASSES.append(OrderedDict([
    ("id", "BRANCH_E"),
    ("order", 5),
    ("name", "Event-Aligned Counterfactual or Mechanistic Claim"),
    ("question", "Did corresponding semantic events receive the same random quantities across divergent arms?"),
    ("example_claim", "Corresponding exogenous events received the same random quantities across divergent policies or algorithms."),
    ("description",
     "A mechanistic/counterfactual claim at event granularity: semantic events identified "
     "by a stable ontology received identical random quantities across arms whose behavior "
     "diverged, enabling event-level attribution."),
    ("required_evidence", [
        "stable_event_identifiers",
        "event_value_records",
        "event_keyed_streams_or_validated_equivalent",
        "declared_event_ontology",
        "dependence_assumptions",
    ]),
    ("explicitly_not_required", ["within_artifact_exact_replay", "trace_projection_equality_everywhere"]),
    ("permitted_wording", [
        "for e/e matched event keys, recorded random quantities were identical across arms",
        "event-level equality held under the declared ontology and keying construction",
        "counterfactual attribution is supported at event granularity under the declared dependence assumptions",
    ]),
    ("forbidden_wording", [
        "events were aligned because schedules matched",
        "event alignment holds without a declared ontology",
        "post-hoc event matching justifies counterfactual claims",
    ]),
]))

# ---------------------------------------------------------------------------
# Decision graph.
# ---------------------------------------------------------------------------
DECISION_GRAPH = OrderedDict([
    ("entry", "N_ENTRY"),
    ("nodes", [
        OrderedDict([("id", "N_ENTRY"), ("type", "route"), ("rule",
            "Classify the evaluator's intended claim by inferential objective into exactly one branch A-E. If classification fails or is ambiguous after documented adjudication -> D_FAIL_CLOSED.")]),
        OrderedDict([("id", "N_A"), ("type", "branch"), ("claim_class", "BRANCH_A"),
                     ("checks", ["artifact_identity", "schedule_identity", "complete_rows", "correct_grouping"]),
                     ("pass_to", "D_ADMIT_DESCRIPTIVE"), ("fail_to", "D_SUPPRESS_OR_DOWNGRADE")]),
        OrderedDict([("id", "N_B"), ("type", "branch"), ("claim_class", "BRANCH_B"),
                     ("checks", ["B_design_justification", "correct_grouping", "complete_rows"]),
                     ("pass_to", "D_ADMIT_STATISTICAL"), ("fail_to", "D_SUPPRESS_OR_DOWNGRADE")]),
        OrderedDict([("id", "N_C"), ("type", "branch"), ("claim_class", "BRANCH_C"),
                     ("checks", ["within_artifact_repeated_executions", "declared_trace_projection", "context_testing", "exact_repeatability_criteria"]),
                     ("pass_to", "D_ADMIT_REPLAY"), ("fail_to", "D_SUPPRESS_OR_DOWNGRADE")]),
        OrderedDict([("id", "N_D"), ("type", "branch"), ("claim_class", "BRANCH_D"),
                     ("checks", ["specified_coupling_construction", "preserved_marginals", "measured_covariance", "measured_variance_reduction", "synchronization_assumptions"]),
                     ("pass_to", "D_ADMIT_CRN"), ("fail_to", "D_SUPPRESS_OR_DOWNGRADE")]),
        OrderedDict([("id", "N_E"), ("type", "branch"), ("claim_class", "BRANCH_E"),
                     ("checks", ["stable_event_identifiers", "event_value_records", "event_keyed_streams_or_validated_equivalent", "declared_event_ontology", "dependence_assumptions"]),
                     ("pass_to", "D_ADMIT_EVENT"), ("fail_to", "D_SUPPRESS_OR_DOWNGRADE")]),
        OrderedDict([("id", "D_ADMIT_DESCRIPTIVE"), ("type", "decision"), ("outcome", "ADMIT_AS_DESCRIPTIVE")]),
        OrderedDict([("id", "D_ADMIT_STATISTICAL"), ("type", "decision"), ("outcome", "ADMIT_AS_STATISTICAL_PAIRED")]),
        OrderedDict([("id", "D_ADMIT_REPLAY"), ("type", "decision"), ("outcome", "ADMIT_AS_REPLAY_SCOPED")]),
        OrderedDict([("id", "D_ADMIT_CRN"), ("type", "decision"), ("outcome", "ADMIT_AS_CRN_EVIDENCED")]),
        OrderedDict([("id", "D_ADMIT_EVENT"), ("type", "decision"), ("outcome", "ADMIT_AS_EVENT_ALIGNED")]),
        OrderedDict([("id", "D_SUPPRESS_OR_DOWNGRADE"), ("type", "decision"), ("outcome",
            "SUPPRESS_CLAIM_OR_DOWNGRADE_TO_SUPPORTED_BRANCH")]),
        OrderedDict([("id", "D_FAIL_CLOSED"), ("type", "decision"), ("outcome", "FAIL_CLOSED_UNCLASSIFIABLE")]),
    ]),
    ("invariants", [
        "result exclusion: classifier inputs exclude final outcome values of the study being validated",
        "monotonicity: removing any required evidence can never upgrade an admission decision",
        "fail closed: unknown or ambiguous state yields FAIL_CLOSED_UNCLASSIFIABLE, never admission",
        "projection scoping: replay admission is scoped to the declared trace projection only",
        "deterministic classifier: identical evidence inputs yield identical decisions",
        "branch independence: satisfaction of any branch imposes no requirement from another branch",
    ]),
])

PERMITTED_WORDING_DOC = OrderedDict([
    ("global_rules", [
        "Wording must name the branch satisfied.",
        "Statistical wording must name the design feature that justifies it.",
        "Replay wording must name the projection scope.",
        "Equivalence requires a prespecified margin; nonsignificance must never be reported as absence of effect.",
    ]),
    ("by_branch", {c["id"]: {"permitted": c["permitted_wording"], "forbidden": c["forbidden_wording"]}
                   for c in CLAIM_CLASSES}),
])


def build_markdown():
    lines = []
    a = lines.append
    a(f"# {FRAMEWORK_META['name']} ({FRAMEWORK_META['short_name']}) v{FRAMEWORK_META['version']}")
    a("")
    a(f"**Frozen:** {FRAMEWORK_META['frozen_date']}  ")
    a(f"**Central question:** *{FRAMEWORK_META['central_question']}*")
    a("")
    a(f"> **Core principle.** {FRAMEWORK_META['core_principle']}")
    a("")
    a(f"> **Superseded anti-pattern.** {FRAMEWORK_META['anti_pattern']}")
    a("")
    a("---")
    a("")
    a("## The five branches")
    a("")
    for c in CLAIM_CLASSES:
        a(f"### {c['id']} — {c['name']}")
        a("")
        a(f"- **Question:** {c['question']}")
        a(f"- **Example claim:** “{c['example_claim']}”")
        a(f"- **Description:** {c['description']}")
        a("- **Required evidence:**")
        for ev in c["required_evidence"]:
            if ev.startswith("at_least_one_of:"):
                alts = ev.split(":", 1)[1]
                a(f"  - at least one of: {', '.join('`' + x + '`' for x in alts.split(','))}")
            else:
                a(f"  - `{ev}` — {EVIDENCE_REGISTRY[ev]}")
        a("- **Explicitly NOT required:** " + "; ".join(c["explicitly_not_required"]))
        a("- **Permitted wording:**")
        for w in c["permitted_wording"]:
            a(f"  - “{w}”")
        a("- **Forbidden wording:**")
        for w in c["forbidden_wording"]:
            a(f"  - ✗ “{w}”")
        a("")
    a("## Independence of branches")
    a("")
    a("| Satisfied | Imposes requirement on other branches? |")
    a("|---|---|")
    a("| B (statistical pairing) | None from C or E; design features justify the reference distribution |")
    a("| C (replay) | None; replay says nothing about cross-arm coupling |")
    a("| D (CRN) | None from C; marginal preservation + covariance evidence suffices |")
    a("| E (event alignment) | None from C; scoped to declared ontology |")
    a("| A (descriptive) | None; never upgrades to statistical language |")
    a("")
    a("## Decision flow (summary)")
    a("")
    for n in DECISION_GRAPH["nodes"]:
        if n["type"] == "route":
            a(f"- **Route.** {n['rule']}")
        elif n["type"] == "branch":
            a(f"- **{n['id']}** (`{n['claim_class']}`): check {', '.join('`' + ch + '`' for ch in n['checks'])}; pass → {n['pass_to']}; fail → {n['fail_to']}")
        else:
            a(f"- **{n['id']}** → {n['outcome']}")
    a("")
    a("## Implementation invariants (tested, not theorized)")
    a("")
    for inv in DECISION_GRAPH["invariants"]:
        a(f"- {inv}")
    a("")
    a("---")
    a("")
    a("*This document and the four JSON files (`claim_classes.json`, `evidence_requirements.json`, `permitted_wording.json`, `decision_graph.json`) are generated from the single canonical source `canonical_framework.py`. Regenerate with `python3 canonical_framework.py`.*")
    return "\n".join(lines)


def main():
    out_dir = os.path.dirname(os.path.abspath(__file__))

    def dump(name, obj):
        path = os.path.join(out_dir, name)
        with open(path, "w") as f:
            json.dump(obj, f, indent=2)
            f.write("\n")

    dump("claim_classes.json", OrderedDict([
        ("meta", FRAMEWORK_META),
        ("claim_classes", CLAIM_CLASSES),
    ]))
    dump("evidence_requirements.json", OrderedDict([
        ("meta", FRAMEWORK_META),
        ("evidence_registry", EVIDENCE_REGISTRY),
        ("requirements_by_class", {c["id"]: c["required_evidence"] for c in CLAIM_CLASSES}),
    ]))
    dump("permitted_wording.json", PERMITTED_WORDING_DOC)
    dump("decision_graph.json", DECISION_GRAPH)
    with open(os.path.join(out_dir, "CLAIM_SPECIFIC_FRAMEWORK.md"), "w") as f:
        f.write(build_markdown() + "\n")

    print("Generated 5 files from canonical source.")


if __name__ == "__main__":
    main()

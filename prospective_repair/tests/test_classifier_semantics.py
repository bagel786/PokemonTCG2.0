"""Classifier semantics vs frozen grammar + safety invariants I1–I5."""
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from framework.classifier import classify_all          # noqa: E402
from runner.gen_expected_table import GRAMMAR           # noqa: E402


EXPECTED = json.loads((Path(__file__).resolve().parents[1] /
                       "protocol" / "EXPECTED_DECISION_TABLE.json").read_text())


def test_expected_table_consistent_with_grammar_truth():
    exp_map = {"VALID": "ADMIT", "DOWNGRADE": "DOWNGRADE",
               "INVALID": "SUPPRESS"}
    mis = []
    for r in EXPECTED["rows"]:
        b7 = r["B7_csvf_full"]
        pairs = (("BRANCH_A", "descriptive"), ("BRANCH_B", "paired_inference"),
                 ("BRANCH_C", "replay"), ("BRANCH_D", "crn"),
                 ("BRANCH_E", "event_alignment"))
        for br, dim in pairs:
            want = exp_map.get(r["gt"][dim])
            if want and b7[br] != want:
                mis.append((r["construction"], br))
    assert not mis, f"{len(mis)} mismatches: {mis[:8]}"


def _all_bundles(limit=12):
    """Build subset-degradation bundles from a valid-baseline bundle."""
    import runner.gen_expected_table as gt
    cdef = next(c for c in GRAMMAR["constructions"] if c["id"] == "G01")
    spec = gt.spec_from_construction(cdef)
    spec.declared_seed = 99
    a, b = gt.synthetic_artifacts(spec)
    from runner.bundle_builder import build_bundle
    base = build_bundle("holdem", spec, a, b, [], [],
                        gt.context_records(spec, a),
                        {"rows_scheduled": 4, "rows_present_recorded": 4,
                         "ids_unique": True}, cdef)
    groups = {
        "identity": lambda x: setattr(x, "allowed_differences_declared", False),
        "fields": lambda x: setattr(x, "schedule_fields_match", False),
        "effective": lambda x: setattr(x, "effective_seed_a", 12345),
        "rows": lambda x: setattr(x, "rows_present", 1),
        "ids": lambda x: setattr(x, "row_ids_unique", False),
        "unit": lambda x: setattr(x, "analysis_unit", "decision"),
        "design": lambda x: setattr(x, "design_justifications", []),
        "repeats": lambda x: setattr(x, "repeats_digests_equal_primary", None),
        "contexts": lambda x: setattr(x, "contexts", []),
        "coupling": lambda x: setattr(x, "coupling_type", "none"),
        "ontology": lambda x: setattr(x, "ontology_match", None),
        "marginals": lambda x: setattr(x, "marginals_preserved", None),
    }
    names = list(groups)
    rank = {"ADMIT": 3, "DOWNGRADE": 2, "SUPPRESS": 1, "FAIL_CLOSED": 1}
    for size in range(0, len(names) + 1):
        count = 0
        for combo in itertools.combinations(names, size):
            bb = base.__class__(**{f: getattr(base, f) for f in
                                   base.__dataclass_fields__})
            bb.predicate_trace = {}
            bb.identity_arm_a = base.identity_arm_a
            bb.identity_arm_b = base.identity_arm_b
            for c in combo:
                groups[c](bb)
            full = rank[max(classify_all(base).values(), key=lambda d: rank[d])]
            dec = rank[max(classify_all(bb).values(), key=lambda d: rank[d])]
            if dec > full:
                yield f"upgraded by removing {combo}"
            count += 1
            if count >= limit:
                break
        if size >= 3:
            break


def test_monotone_under_evidence_removal():
    problems = list(_all_bundles())
    assert not problems, problems[:5]


def test_fail_closed_on_missing_critical_evidence():
    import runner.gen_expected_table as gt
    from runner.bundle_builder import build_bundle
    cdef = next(c for c in GRAMMAR["constructions"] if c["id"] == "G02")
    spec = gt.spec_from_construction(cdef)
    spec.declared_seed = 5
    a, b = gt.synthetic_artifacts(spec)
    for art in (a, b):
        art["marginals_ok"] = None
        art["event_keys"] = []
    bundle = build_bundle("ising", spec, a, b, [], [], [],
                          {"rows_scheduled": 1, "rows_present_recorded": 1,
                           "ids_unique": True}, cdef)
    dec = classify_all(bundle)
    assert dec["BRANCH_D"] in ("FAIL_CLOSED", "SUPPRESS")
    assert dec["BRANCH_E"] in ("FAIL_CLOSED", "SUPPRESS")


def test_projection_scope_outside_claim_logged_not_used():
    """Out-of-scope records don't affect within-artifact C decisions; the
    production row always carries same-process replicas as repeat evidence."""
    import runner.gen_expected_table as gt
    from runner.bundle_builder import build_bundle
    cdef = next(c for c in GRAMMAR["constructions"] if c["id"] == "G01")
    spec = gt.spec_from_construction(cdef)
    spec.declared_seed = 7
    a, b = gt.synthetic_artifacts(spec)
    row_common = {"rows_scheduled": 4, "rows_present_recorded": 4,
                  "ids_unique": True}
    bu1 = build_bundle("holdem", spec, a, b, [], [],
                       gt.context_records(spec, a), row_common, cdef)
    d1 = classify_all(bu1)["BRANCH_C"]
    # an out-of-scope cross-process record whose digest differs is LOGGED but
    # must not perturb the within-artifact decision:
    ctx_extra = gt.context_records(spec, a) + [
        {"context_label": "other-machine", "pid": 999,
         "digest": "unrelated-artifact-digest",
         "primary_digest": a["projection_digest"],
         "process_separated": True, "dealer_fp": None}]
    bu2 = build_bundle("holdem", spec, a, b, [], [], ctx_extra, row_common,
                       cdef)
    bu2.replay_scope_claimed = "within_artifact"
    d2 = classify_all(bu2)["BRANCH_C"]
    assert d1 == d2 == "ADMIT"


def test_deterministic_classification_same_process():
    import runner.gen_expected_table as gt
    from runner.bundle_builder import build_bundle
    outs = set()
    for _ in range(5):
        cdef = next(c for c in GRAMMAR["constructions"] if c["id"] == "G16")
        spec = gt.spec_from_construction(cdef)
        spec.declared_seed = 11
        a, b = gt.synthetic_artifacts(spec)
        bu = build_bundle("holdem", spec, a, b, [], [], [],
                          {"rows_scheduled": 1, "rows_present_recorded": 1,
                           "ids_unique": True}, cdef)
        outs.add(json.dumps(classify_all(bu), sort_keys=True))
    assert len(outs) == 1

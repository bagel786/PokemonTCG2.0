"""Analysis-pipeline executability + safety fixtures (synthetic rows only;
never touches any acquired bank)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.schema_validators import validate_stream, validate_aggregate  # noqa: E402


def _synth_rows(n_seeds=6):
    rows = []
    gtmap = {"G01": {"descriptive": "VALID", "paired_inference": "VALID",
                     "replay": "VALID", "crn": "VALID",
                     "event_alignment": "NOT_APPLICABLE"}}
    gid = list(gtmap)[0]
    for system in ("holdem",):
        for seed in range(1000, 1000 + n_seeds):
            for arm in ("A", "B"):
                rows.append({
                    "level": "outcome", "system": system,
                    "construction": gid, "seed": seed, "arm": arm,
                    "wall_s": 0.01, "cpu_s": 0.01, "outcome_value": 1.5,
                    "projection_digest": f"d-{arm}-{seed}",
                    "effective_seed": seed, "repeat_id": "r0",
                    "context_id": "primary", "artifact_bytes": 128})
            for method in ("B7_csvf_full", "B5_cluster_hierarchical"):
                for br in ("BRANCH_A", "BRANCH_B", "BRANCH_C", "BRANCH_D",
                           "BRANCH_E"):
                    gt = gtmap[gid][{"BRANCH_A": "descriptive",
                                     "BRANCH_B": "paired_inference",
                                     "BRANCH_C": "replay",
                                     "BRANCH_D": "crn",
                                     "BRANCH_E": "event_alignment"}[br]]
                    dec = {"NOT_APPLICABLE": "ABSTAIN_NOT_EVALUATED"}
                    decision = dec.get(gt, "ADMIT")
                    score = "CORRECT" if decision == "ADMIT" else \
                        ("ABSTAINED" if decision.startswith("ABSTAIN")
                         else "CORRECT")
                    rows.append({
                        "level": "decision", "system": system,
                        "construction": gid, "seed": seed, "method": method,
                        "branch": br, "decision": decision, "gt": gt,
                        "score_class": score,
                        "coverage_flag": True, "reason_codes": [],
                        "bundle_payload_sha256": "h" * 8,
                        "view_payload": {},
                        "audit_payload": {"bundle": {"row_id": "x"},
                                          "bundle_sha256": "h" * 8}})
    return rows


def test_schema_validators_accept_clean_synthetic_and_detect_problems():
    rows = _synth_rows()
    counts = validate_stream(rows)
    assert counts["decision"] > 0 and counts["outcome"] > 0


def test_forbidden_aggregates_rejected():
    for bad in ({"two_proportion_z_test": {"p": 0.03}},
                {"typeI_error_result": 0.05},
                {"power_curve_result": [0.8]},
                {"coverage_rate_result": 0.94}):
        try:
            validate_aggregate(bad)
            raise AssertionError(f"forbidden aggregate accepted: {bad}")
        except ValueError:
            pass
    assert validate_aggregate({"wilson_interval": [0.5, 0.4, 0.6]})


def test_wilson_fixture_against_frozen_equation_docs():
    from analysis.stats import wilson_interval
    p, lo, hi = wilson_interval(38, 40)
    doc = (Path(__file__).resolve().parents[1] / "protocol" /
           "ANALYSIS_PLAN.md").read_text()
    assert "[0.835,0.986]" in doc.replace(" ", "")
    assert round(lo, 3) == 0.835 and round(hi, 3) == 0.986


def test_stats_determinism_seeded():
    from analysis.stats import variance_ratio_benefit
    import numpy as np
    rng = np.random.default_rng(0)
    a = rng.normal(size=60)
    b = a * 0.9 + rng.normal(scale=0.2, size=60)
    r1 = variance_ratio_benefit(list(a), list(b))
    r2 = variance_ratio_benefit(list(a), list(b))
    assert r1 == r2
    assert r1["status"] == "EXPLORATORY_NOT_CONFIRMATORY"

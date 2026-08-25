"""Independent tests for the raw-row statistical reaggregation."""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "paper/final_protocol/scripts/independent_statistics_audit.py"
OUTPUT = ROOT / "paper/final_protocol/source_data/independent_statistics_verification.json"
CANONICAL_VERIFICATION_SCRIPT = ROOT / "paper/final_protocol/scripts/verify_statistics.py"
CANONICAL_VERIFICATION_OUTPUT = ROOT / "paper/final_protocol/source_data/statistics_verification.json"


@pytest.fixture(scope="module")
def audit_module():
    spec = importlib.util.spec_from_file_location("independent_statistics_audit", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def canonical_verification_module():
    spec = importlib.util.spec_from_file_location(
        "verify_statistics", CANONICAL_VERIFICATION_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def report(audit_module):
    return audit_module.build_report()


def test_report_is_exactly_reproducible(report):
    recorded = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert report == recorded
    assert report["status"] == "PASS"
    assert report["conflicts"] == []


def test_legacy_reweighting_keys_are_normalized_without_ci_semantics(
    canonical_verification_module,
):
    observed = canonical_verification_module.normalized_reweighting_record(
        {
            "clusters": 200,
            "estimate": 0.495,
            "bootstrap_95_ci": [0.425, 0.565],
            "bootstrap_draws": 100_000,
            "bootstrap_seed": 2026083118,
        }
    )
    assert observed == {
        "clusters": 200,
        "estimate": 0.495,
        "quantiles_2_5_97_5": [0.425, 0.565],
        "reweighting_draws": 100_000,
        "reweighting_seed": 2026083118,
    }
    with pytest.raises(
        canonical_verification_module.VerificationError, match="reversed"
    ):
        canonical_verification_module.normalized_reweighting_record(
            {
                "estimate": 0.5,
                "bootstrap_95_ci": [0.6, 0.4],
                "bootstrap_draws": 100,
                "bootstrap_seed": 1,
            }
        )


def test_canonical_verification_emits_only_bounded_statistical_semantics():
    payload = json.loads(CANONICAL_VERIFICATION_OUTPUT.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "pevl-statistics-verification-v2"
    assert "descriptive only" in payload["interpretation_boundary"]
    assert "no confidence interval" in payload["interpretation_boundary"]
    stress = payload["stress"]
    reweighting = stress["empirical_reweighting"]
    assert reweighting["estimate"] == 0.495
    assert reweighting["quantiles_2_5_97_5"] == [0.425, 0.565]
    assert reweighting["reweighting_draws"] == 100_000
    assert reweighting["reweighting_seed"] == 2026083118
    assert "fixed-battery descriptive" in reweighting["inferential_status"]
    assert "not a confidence interval" in reweighting["inferential_status"]
    fixed_composition = stress["fixed_composition_reweighting_sensitivity"]
    assert fixed_composition["estimate"] == 0.495
    assert fixed_composition["quantiles_2_5_97_5"] == pytest.approx(
        [0.46, 0.53], abs=1e-15
    )
    assert fixed_composition["stratum_disagreement_counts"] == {
        "dipplin/first": 4,
        "dipplin/second": 3,
        "starmie/first": 44,
        "starmie/second": 48,
    }
    assert fixed_composition["design_status"] == (
        "post-acquisition source-driven sensitivity"
    )
    assert "fixed-composition" in fixed_composition["role"]
    assert "not a confidence interval" in fixed_composition["inferential_status"]
    assert stress["earliest_divergence_localization_included"] is False
    assert "first_divergence_actor_counts" not in stress

    factorial = payload["factorial"]
    assert set(factorial["contrasts"]) == {
        "primary_c4_minus_c1",
        "representation_main",
        "training_main",
        "interaction",
    }
    for contrast in factorial["contrasts"].values():
        assert "quantiles_2_5_97_5" in contrast
        assert "fixed-battery descriptive" in contrast["inferential_status"]
        assert "not a confidence interval" in contrast["inferential_status"]
    numerical_audit = factorial["mcnemar_numerical_audit_not_admitted"]
    assert numerical_audit["status"] == "NUMERICAL_AUDIT_ONLY_NOT_ADMITTED"
    assert numerical_audit["displayed_in_manuscript"] is False
    assert numerical_audit["admitted_for_inference"] is False
    assert numerical_audit["discordant_units"] == 705

    prohibited_keys = {
        "bootstrap",
        "bootstrap_95_ci",
        "bootstrap_draws",
        "bootstrap_seed",
        "first_divergence_actor_counts",
        "primary_mcnemar",
        "target_population",
    }

    def keys(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from keys(item)
        elif isinstance(value, list):
            for item in value:
                yield from keys(item)

    assert prohibited_keys.isdisjoint(keys(payload))


def test_source_hashes_inventory_schemas_and_nonfinite_checks(audit_module, report):
    integrity = report["source_integrity"]
    assert integrity["source_count"] == 58
    assert integrity["role_counts"] == {
        "factorial_raw_acquisition": 15,
        "historical_raw_acquisition": 21,
        "preflight_raw_acquisition": 20,
        "stress_raw_acquisition": 2,
    }
    assert integrity["nonfinite_values"] == 0
    assert integrity["numeric_values_checked"] > 400_000
    assert integrity["validation_checks"] == {
        "status": "PASS",
        "source_hashes_verified": 58,
        "exact_source_inventory": True,
        "exact_top_level_schemas_verified": 58,
        "exact_execution_row_schemas_verified": 32_600,
        "analysis_units_explicit": True,
        "orders_and_seed_offsets_verified": True,
        "stratum_sizes_verified": True,
        "all_generated_quantile_pairs_finite_and_ordered": True,
    }
    for row in integrity["sources"]:
        assert audit_module.sha256_file(ROOT / row["path"]) == row["sha256"]
        assert row["sha256"] == audit_module.EXPECTED_SOURCE_HASHES[row["path"]]


def test_schema_nonfinite_and_quantile_guards_fail_closed(audit_module):
    with pytest.raises(audit_module.AuditError, match="schema drift"):
        audit_module.validate_exact_keys({"a": 1}, frozenset({"a", "b"}), "tampered")
    with pytest.raises(audit_module.AuditError, match="nonfinite"):
        audit_module.count_finite_numbers({"x": math.nan}, "tampered")
    with pytest.raises(audit_module.AuditError, match="reversed"):
        audit_module.validate_quantile_pair([2.0, 1.0], "tampered")
    with pytest.raises(audit_module.AuditError, match="nonfinite"):
        audit_module.validate_quantile_pair([0.0, math.inf], "tampered")


def test_eq1_projection_detects_byte_count_only_disagreement(audit_module):
    baseline = {
        "trace_sha256": "a" * 64,
        "trace_bytes": 100,
        "win": True,
        "draw": False,
        "hero_policy_errors": 0,
        "opponent_policy_errors": 0,
        "decisions": 12,
    }
    changed = dict(baseline)
    changed["trace_bytes"] = 101
    flags = audit_module.disagreement_flags([baseline, changed])
    assert flags["trace_digest_disagreement"] is False
    assert flags["trace_byte_count_disagreement"] is True
    assert flags["trace_projection_disagreement"] is True
    assert flags["any_required_disagreement"] is True


def test_historical_raw_control_reaggregation(report):
    result = report["historical"]
    assert result["units"] == 2_800
    assert result["strata"] == 14
    assert result["raw_acquisition_rows"] == 16_800
    assert result["control_executions_compared"] == 8_400
    assert result["outcome_disagreement_units"] == 210
    assert result["error_disagreement_units"] == 0
    assert result["decision_count_disagreement_units"] == 457
    assert result["outcome_or_error_disagreement_units"] == 210
    assert result["available_record_disagreement_units"] == 458
    assert result["outcome_disagreement_percent"] == 7.5
    assert math.isclose(result["available_record_disagreement_percent"], 16.357142857142858)
    assert result["by_context"]["starmie"]["outcome_disagreement_units"] == 191
    assert result["by_context"]["starmie"]["available_record_disagreement_units"] == 377
    assert result["by_context"]["dipplin"]["outcome_disagreement_units"] == 19
    assert result["by_context"]["dipplin"]["available_record_disagreement_units"] == 81
    assert sum(row["outcome_disagreement_units"] for row in result["by_context"].values()) == 210
    assert sum(row["available_record_disagreement_units"] for row in result["by_context"].values()) == 458
    assert result["order_checks"] == {
        "orders": ["first", "second"],
        "units_per_context_order": 200,
        "second_order_seed_offset": 1_000_000,
    }


def test_preflight_units_executions_and_each_mismatch_type(report):
    result = report["preflight"]
    assert result["jobs"] == 20
    assert result["trajectory_units"] == 1_000
    assert result["executions"] == 3_000
    assert result["profiles_per_unit"] == 3
    for field in (
        "trace_digest_disagreement_units",
        "trace_byte_count_disagreement_units",
        "trace_projection_disagreement_units",
        "outcome_disagreement_units",
        "error_disagreement_units",
        "decision_count_disagreement_units",
        "any_required_disagreement_units",
    ):
        assert result[field] == 0
    assert len(result["job_rows"]) == 20
    assert all(row["trajectory_units"] == 50 and row["executions"] == 150 for row in result["job_rows"])
    assert result["order_checks"]["units_per_job_order"] == 25


def test_timed_search_cluster_counts_strata_and_seeded_quantiles(report):
    result = report["timed_search_stress"]
    assert result["clusters"] == 200
    assert result["executions"] == 800
    assert result["profiles_per_cluster"] == 4
    assert result["trace_digest_disagreement_clusters"] == 99
    assert result["trace_byte_count_disagreement_clusters"] == 96
    assert result["trace_projection_disagreement_clusters"] == 99
    assert result["outcome_disagreement_clusters"] == 47
    assert result["decision_count_disagreement_clusters"] == 93
    assert result["error_disagreement_clusters"] == 0
    assert set(result["strata"]) == {
        "dipplin/first", "dipplin/second", "starmie/first", "starmie/second"
    }
    assert all(row["clusters"] == 50 for row in result["strata"].values())
    assert [
        result["strata"][key]["trace_disagreement"]["estimate"]
        for key in ("dipplin/first", "dipplin/second", "starmie/first", "starmie/second")
    ] == [0.08, 0.06, 0.88, 0.96]

    pooled = result["specified_pooled_whole_cluster_reweighting"]
    assert pooled["estimate"] == 0.495
    assert pooled["reweighting_quantiles_2_5_97_5"] == [0.425, 0.565]
    assert pooled["reweighting_seed"] == 2026083118
    assert pooled["reweighting_draws"] == 100_000
    stratified = result["alternative_stratified_whole_cluster_sensitivity"]
    assert stratified["estimate"] == 0.495
    assert stratified["reweighting_quantiles_2_5_97_5"] == pytest.approx([0.46, 0.53], abs=1e-15)
    assert stratified["reweighting_seed"] == 2026083118
    assert stratified["strata"] == sorted(result["strata"])
    assert result["protocol_interpretation"]["finding_status"] == "PROSE_AMBIGUITY_RESOLVED_BY_FROZEN_EXECUTABLE"


def test_factorial_rates_contrasts_reweighting_and_mcnemar_recalculation(report):
    result = report["factorial"]
    assert result["units_per_cell"] == 2_000
    assert result["strata"] == 10
    assert result["units_per_stratum"] == 200
    assert result["raw_execution_rows"] == 12_000
    assert result["repeated_control_executions"] == 6_000
    assert result["repeated_control_units"] == 2_000
    assert set(result["repeated_control_mismatches"].values()) == {0}
    assert result["cell_win_counts"] == {"C1": 1236, "C2": 1242, "C3": 1215, "C4": 1247}
    assert result["cell_win_rates"] == {"C1": 0.618, "C2": 0.621, "C3": 0.6075, "C4": 0.6235}
    expected = {
        "primary_c4_minus_c1": (0.0055, [-0.0205, 0.0315]),
        "representation_main": (0.0095, [-0.01075, 0.03]),
        "training_main": (-0.004, [-0.02025, 0.0125]),
        "interaction": (0.013, [-0.0185, 0.0445]),
    }
    for name, (estimate, quantiles) in expected.items():
        row = result["contrasts"][name]
        assert row["estimate"] == estimate
        assert row["reweighting_quantiles_2_5_97_5"] == pytest.approx(quantiles, abs=1e-15)
        assert row["reweighting_seed"] == 2026083117
        assert row["reweighting_draws"] == 100_000
        assert row["reweighting_quantiles_2_5_97_5"][0] <= row["reweighting_quantiles_2_5_97_5"][1]
    assert result["mcnemar"] == {
        "c4_only_wins": 358,
        "c1_only_wins": 347,
        "discordant_units": 705,
        "exact_two_sided_p": 0.7064831563628252,
    }
    assert result["order_checks"]["orders"] == ["first", "second"]
    assert result["order_checks"]["second_order_seed_offset"] == 1_000_000


def test_all_central_displayed_percentages_and_percentage_points(report):
    display = report["displayed_value_audit"]
    assert all(row["status"] == "MATCH" for row in display["macro_count_checks"].values())
    assert all(row["status"] == "MATCH" for row in display["factorial_macro_checks"].values())
    assert display["mcnemar_recalculation"]["displayed_in_manuscript"] is False
    assert all(row["status"] == "MATCH" for row in display["figure_4_checks"].values())
    assert all(row["status"] == "MATCH" for row in display["figure_5_checks"].values())
    assert display["stress_overall"]["matches_specified_pooled"] is True
    assert display["stress_overall"]["matches_alternative_fixed_composition_sensitivity"] is False
    percentages = display["percentage_inventory"]
    assert percentages["historical"]["outcome_disagreement_percent"] == 7.5
    assert percentages["stress"]["trace_digest_disagreement_percent"] == 49.5
    assert percentages["stress"]["specified_pooled_quantiles_percent"] == pytest.approx([42.5, 56.5])
    assert percentages["stress"]["alternative_fixed_composition_quantiles_percent"] == pytest.approx([46.0, 53.0])
    assert percentages["factorial"]["cell_win_percentages"] == pytest.approx(
        {"C1": 61.8, "C2": 62.1, "C3": 60.75, "C4": 62.35}
    )

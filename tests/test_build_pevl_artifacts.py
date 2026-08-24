import copy
import hashlib
import json
import runpy
import shutil
from pathlib import Path

import pytest

from paper.scripts import build_pevl_artifacts as artifacts


ROOT = Path(__file__).resolve().parents[1]


def preflight_fixture(status="PASS"):
    mismatches = 0 if status == "PASS" else 1
    rows = []
    for arm in ("C1", "C2", "C3", "C4"):
        for opponent in sorted(artifacts.EXPECTED_PREFLIGHT_OPPONENTS):
            failed = status == "FAIL" and not rows
            rows.append(
                {
                    "arm": arm,
                    "opponent": opponent,
                    "passed": not failed,
                    "mismatch_units": 1 if failed else 0,
                    "trace_mismatch_units": 1 if failed else 0,
                    "outcome_mismatch_units": 0,
                    "error_mismatch_units": 0,
                    "decision_count_mismatch_units": 0,
                    "trajectory_units": 50,
                    "executions": 150,
                    "source": f"paper/data/pevl/preflight/raw/{arm}_{opponent}.json",
                    "source_sha256": "0" * 64,
                }
            )
    return {
        "schema_version": 1,
        "analysis_id": "trace_preflight",
        "status": status,
        "admission_decision": (
            "admit_factorial_acquisition"
            if status == "PASS"
            else "suppress_factorial"
        ),
        "protocol_commit": "protocol-commit",
        "arms": 4,
        "opponents": 5,
        "trajectory_units": 1_000,
        "executions": 3_000,
        "mismatch_units": mismatches,
        "trace_mismatch_units": mismatches,
        "outcome_mismatch_units": 0,
        "error_mismatch_units": 0,
        "decision_count_mismatch_units": 0,
        "rows": rows,
        "claim_boundary": "Within-arm trace reproducibility only.",
    }


def stress_fixture():
    disagreement_counts = {
        "dipplin/first": 5,
        "dipplin/second": 10,
        "starmie/first": 15,
        "starmie/second": 20,
    }
    strata = {}
    for index, (name, count) in enumerate(
        disagreement_counts.items(), start=1
    ):
        estimate = count / 50
        strata[name] = {
            "trace_disagreement": {
                "clusters": 50,
                "estimate": estimate,
                "bootstrap_95_ci": [
                    max(0.0, estimate - 0.1),
                    min(1.0, estimate + 0.1),
                ],
                "bootstrap_draws": 100_000,
                "bootstrap_seed": 2026083118,
            },
            "outcome_disagreement_count": index,
            "decision_count_disagreement_count": index + 1,
            "error_disagreement_count": 0,
            "policy_error_present_count": 0,
        }
    return {
        "schema_version": 1,
        "analysis_id": "timed_search_stress",
        "status": "TRACE_DIVERGENCE",
        "protocol_commit": "protocol-commit",
        "clusters": 200,
        "executions": 800,
        "trace_disagreement_clusters": 50,
        "trace_disagreement": {
            "clusters": 200,
            "estimate": 0.25,
            "bootstrap_95_ci": [0.19, 0.31],
            "bootstrap_draws": 100_000,
            "bootstrap_seed": 2026083118,
        },
        "outcome_disagreement_clusters": 10,
        "decision_count_disagreement_clusters": 14,
        "error_disagreement_clusters": 0,
        "policy_error_present_clusters": 0,
        "first_divergence_actor_counts": {},
        "strata": strata,
        "timing": {},
        "cluster_rows": [],
        "sources": [],
        "bootstrap_note": "Cluster bootstrap.",
        "pevl_level_6_boundary": "Localization is not unique causation.",
    }


def factorial_fixture():
    estimates = {
        "primary_c4_minus_c1": 0.04,
        "representation_main": 0.025,
        "training_main": 0.015,
        "interaction": 0.01,
    }
    return {
        "schema_version": 1,
        "analysis_id": "factorial",
        "status": "ADMITTED_SEED_MATCHED",
        "admission_decision": "admit_with_bounded_wording",
        "protocol_commit": "protocol-commit",
        "target_population": (
            "five prospectively frozen determinism-eligible opponent "
            "packages by two actual orders"
        ),
        "units": 2_000,
        "games": 12_000,
        "control_mismatch_units": 0,
        "cell_win_rates": {
            "C1": 0.50,
            "C2": 0.52,
            "C3": 0.51,
            "C4": 0.54,
        },
        "contrasts": {
            name: {
                "estimate": estimate,
                "bootstrap_95_ci": [estimate - 0.02, estimate + 0.02],
                "bootstrap_draws": 100_000,
                "bootstrap_seed": 2026083117,
                "resampling": "paired units within each of ten opponent-by-order strata",
            }
            for name, estimate in estimates.items()
        },
        "simple_effects_descriptive": {},
        "primary_mcnemar": {},
        "pevl_levels": {},
        "sources": [],
    }


def historical_fixture():
    return json.loads(
        (ROOT / "paper/data/ablation/summary.json").read_text(
            encoding="utf-8"
        )
    )


def combined_fixture(historical, preflight, stress, factorial):
    audit = historical["control_parity_audit"]
    return {
        "schema_version": 1,
        "framework": "Paired Evaluation Validity Ladder",
        "protocol": "paper/protocol/PEVL_PROSPECTIVE_PROTOCOL.md",
        "historical_control_parity": {
            "status": historical["status"],
            "units": audit["pairs"],
            "outcome_record_mismatch_units": audit[
                "outcome_record_mismatch_units"
            ],
            "serialized_record_mismatch_units": audit[
                "serialized_record_mismatch_units"
            ],
            "by_opponent": audit["by_opponent"],
            "cause_audit": historical["cause_audit"],
        },
        "prospective_trace_preflight": preflight,
        "timed_search_stress": stress,
        "gated_factorial": factorial,
        "claim_boundary": "No Level-7 claim is admitted.",
    }


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_defaults_target_processed_analyzer_summaries():
    assert artifacts.DEFAULT_PREFLIGHT.name == "trace_preflight_summary.json"
    assert artifacts.DEFAULT_STRESS.name == "timed_search_stress_summary.json"
    assert artifacts.DEFAULT_FACTORIAL.name == "factorial_summary.json"
    assert artifacts.DEFAULT_COMBINED.name == "summary.json"


def test_cli_parser_exposes_each_artifact_input_once():
    parsed = artifacts.parse_args([])
    assert parsed.synthetic == artifacts.DEFAULT_SYNTHETIC
    assert parsed.historical == artifacts.DEFAULT_HISTORICAL
    assert parsed.preflight == artifacts.DEFAULT_PREFLIGHT
    assert parsed.stress == artifacts.DEFAULT_STRESS
    assert parsed.factorial == artifacts.DEFAULT_FACTORIAL
    assert parsed.combined == artifacts.DEFAULT_COMBINED
    assert parsed.figures_dir == artifacts.DEFAULT_FIGURES
    assert parsed.tables_dir == artifacts.DEFAULT_TABLES


def test_copied_builder_defaults_to_release_layout(tmp_path):
    release = tmp_path / "renamed-companion-package"
    (release / "data/processed").mkdir(parents=True)
    script = release / "scripts/build_pevl_artifacts.py"
    script.parent.mkdir(parents=True)
    shutil.copy2(ROOT / "paper/scripts/build_pevl_artifacts.py", script)

    namespace = runpy.run_path(str(script), run_name="release_layout_test")
    assert namespace["RELEASE_LAYOUT"] is True
    assert namespace["DEFAULT_SYNTHETIC"] == (
        release / "synthetic/results/pevl_results.json"
    )
    assert namespace["DEFAULT_HISTORICAL"] == (
        release / "data/processed/ablation_summary.json"
    )
    assert namespace["DEFAULT_PREFLIGHT"] == (
        release / "data/processed/pevl_trace_preflight_summary.json"
    )
    assert namespace["DEFAULT_STRESS"] == (
        release / "data/processed/pevl_timed_search_stress_summary.json"
    )
    assert namespace["DEFAULT_FACTORIAL"] == (
        release / "data/processed/pevl_factorial_summary.json"
    )
    assert namespace["DEFAULT_COMBINED"] == (
        release / "data/processed/pevl_summary.json"
    )
    assert namespace["DEFAULT_FIGURES"] == release / "figures"
    assert namespace["DEFAULT_TABLES"] == release / "generated/tables"


def test_required_static_inputs_validate_against_published_machine_records():
    synthetic = json.loads(
        artifacts.DEFAULT_SYNTHETIC.read_text(encoding="utf-8")
    )
    historical = historical_fixture()
    assert set(artifacts.validate_synthetic(synthetic)) == (
        artifacts.EXPECTED_SYNTHETIC_MODES
    )
    audit = artifacts.validate_historical(historical)
    assert audit["pairs"] == 2_800
    assert audit["outcome_record_mismatch_units"] == 210
    assert audit["serialized_record_mismatch_units"] == 458


def test_complete_processed_summaries_validate_and_cross_check():
    historical = historical_fixture()
    preflight = preflight_fixture()
    stress = stress_fixture()
    factorial = factorial_fixture()
    assert artifacts.validate_preflight(preflight)["status"] == "PASS"
    assert artifacts.validate_stress(stress)["clusters"] == 200
    assert artifacts.validate_factorial(factorial)["units"] == 2_000
    artifacts.validate_combined(
        combined_fixture(historical, preflight, stress, factorial),
        historical=historical,
        preflight=preflight,
        stress=stress,
        factorial=factorial,
    )


def test_pending_and_suppressed_branches_do_not_become_renderable():
    assert artifacts.validate_preflight(
        {
            "schema_version": 1,
            "analysis_id": "trace_preflight",
            "status": "NOT_RUN",
            "admission_decision": "suppress",
        }
    ) is None
    assert artifacts.validate_stress(
        {
            "schema_version": 1,
            "analysis_id": "timed_search_stress",
            "status": "INCOMPLETE",
        }
    ) is None
    assert artifacts.validate_factorial(
        {
            "schema_version": 1,
            "analysis_id": "factorial",
            "status": "SUPPRESSED_BY_PREFLIGHT",
            "admission_decision": "suppress",
        }
    ) is None


def test_validators_fail_closed_on_inconsistent_totals_and_branches():
    preflight = preflight_fixture()
    preflight["trajectory_units"] -= 1
    with pytest.raises(artifacts.ArtifactInputError, match="reproduce summary"):
        artifacts.validate_preflight(preflight)

    stress = stress_fixture()
    stress["strata"]["starmie/second"][
        "outcome_disagreement_count"
    ] += 1
    with pytest.raises(artifacts.ArtifactInputError, match="secondary counts"):
        artifacts.validate_stress(stress)

    factorial = factorial_fixture()
    factorial["control_mismatch_units"] = 1
    with pytest.raises(artifacts.ArtifactInputError, match="control mismatches"):
        artifacts.validate_factorial(factorial)

    inconsistent = factorial_fixture()
    inconsistent["contrasts"]["interaction"]["estimate"] = -0.01
    with pytest.raises(artifacts.ArtifactInputError, match="cell win rates"):
        artifacts.validate_factorial(inconsistent)

    nonfinite = factorial_fixture()
    nonfinite["contrasts"]["primary_c4_minus_c1"]["bootstrap_95_ci"] = [
        float("-inf"),
        float("inf"),
    ]
    with pytest.raises(artifacts.ArtifactInputError, match="finite"):
        artifacts.validate_factorial(nonfinite)


def test_json_loader_rejects_nonfinite_constants(tmp_path):
    path = tmp_path / "nonfinite.json"
    path.write_text('{"estimate": Infinity}\n', encoding="utf-8")
    with pytest.raises(artifacts.ArtifactInputError, match="non-finite"):
        artifacts.load_json(path, "nonfinite fixture")

    unresolved = factorial_fixture()
    unresolved["status"] = "READY"
    with pytest.raises(artifacts.ArtifactInputError, match="unresolved"):
        artifacts.validate_factorial(unresolved)


def test_combined_summary_rejects_component_drift():
    historical = historical_fixture()
    preflight = preflight_fixture()
    stress = stress_fixture()
    factorial = factorial_fixture()
    combined = combined_fixture(historical, preflight, stress, factorial)
    combined["gated_factorial"] = copy.deepcopy(factorial)
    combined["gated_factorial"]["units"] = 1_999
    with pytest.raises(artifacts.ArtifactInputError, match="gated_factorial"):
        artifacts.validate_combined(
            combined,
            historical=historical,
            preflight=preflight,
            stress=stress,
            factorial=factorial,
        )


def test_latex_fragments_report_exact_historical_and_prospective_counts(
    tmp_path,
):
    retrospective = artifacts.table_retrospective(
        artifacts.validate_historical(historical_fixture()), tmp_path
    ).read_text(encoding="utf-8")
    assert "Overall & 2,800 & 210 (7.5\\%)" in retrospective
    assert "458 (16.4\\%)" in retrospective

    preflight = preflight_fixture()
    prospective = artifacts.table_prospective(
        preflight,
        artifacts.validate_preflight(preflight),
        artifacts.validate_stress(stress_fixture()),
        tmp_path,
    ).read_text(encoding="utf-8")
    assert "1,000 & 3,000 & 0 units" in prospective
    assert "200 & 800 & 50 clusters" in prospective
    assert "factorial acquisition admitted \\\\" in prospective


def test_admitted_build_emits_all_conditional_artifact_names(
    tmp_path, monkeypatch
):
    historical = historical_fixture()
    preflight = preflight_fixture()
    stress = stress_fixture()
    factorial = factorial_fixture()
    synthetic_path = artifacts.DEFAULT_SYNTHETIC
    historical_path = tmp_path / "historical.json"
    preflight_path = tmp_path / "trace_preflight_summary.json"
    stress_path = tmp_path / "timed_search_stress_summary.json"
    factorial_path = tmp_path / "factorial_summary.json"
    combined_path = tmp_path / "summary.json"
    for path, payload in (
        (historical_path, historical),
        (preflight_path, preflight),
        (stress_path, stress),
        (factorial_path, factorial),
        (
            combined_path,
            combined_fixture(historical, preflight, stress, factorial),
        ),
    ):
        write_json(path, payload)

    def fake_figure(key):
        def render(*args):
            output_dir = args[-1]
            output_dir.mkdir(parents=True, exist_ok=True)
            paths = [
                output_dir / f"{artifacts.FIGURE_STEMS[key]}.{suffix}"
                for suffix in ("pdf", "png")
            ]
            for path in paths:
                path.write_bytes(b"fixture")
            return paths

        return render

    for key in artifacts.FIGURE_STEMS:
        monkeypatch.setattr(
            artifacts, f"figure_{key}", fake_figure(key)
        )
    monkeypatch.setattr(artifacts, "setup_style", lambda: None)

    result = artifacts.build_artifacts(
        synthetic_path=synthetic_path,
        historical_path=historical_path,
        preflight_path=preflight_path,
        stress_path=stress_path,
        factorial_path=factorial_path,
        combined_path=combined_path,
        figures_dir=tmp_path / "figures",
        tables_dir=tmp_path / "tables",
    )
    generated_names = {Path(path).name for path in result["generated"]}
    assert not result["skipped"]
    assert {
        f"{stem}.{suffix}"
        for stem in artifacts.FIGURE_STEMS.values()
        for suffix in ("pdf", "png")
    } <= generated_names
    assert set(artifacts.TABLE_NAMES.values()) <= generated_names


def test_ladder_pdf_and_png_are_deterministic(tmp_path):
    synthetic = json.loads(
        artifacts.DEFAULT_SYNTHETIC.read_text(encoding="utf-8")
    )
    first = artifacts.figure_ladder(synthetic["levels"], tmp_path / "a")
    second = artifacts.figure_ladder(synthetic["levels"], tmp_path / "b")
    by_suffix = {
        path.suffix: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in first
    }
    assert by_suffix == {
        path.suffix: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in second
    }
    assert next(path for path in first if path.suffix == ".pdf").read_bytes().startswith(
        b"%PDF"
    )
    assert next(path for path in first if path.suffix == ".png").read_bytes().startswith(
        b"\x89PNG\r\n\x1a\n"
    )

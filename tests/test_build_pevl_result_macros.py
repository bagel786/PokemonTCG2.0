import copy
import hashlib
import json

import pytest

from paper.scripts import build_pevl_result_macros as macros


PROTOCOL_COMMIT = "c" * 40


def preflight_payload():
    rows = [
        {
            "arm": arm,
            "opponent": opponent,
            "passed": True,
            "mismatch_units": 0,
            "trace_mismatch_units": 0,
            "outcome_mismatch_units": 0,
            "error_mismatch_units": 0,
            "decision_count_mismatch_units": 0,
            "trajectory_units": 50,
            "executions": 150,
            "source": f"paper/data/pevl/preflight/raw/{arm.lower()}_{opponent}.json",
            "source_sha256": "a" * 64,
        }
        for arm in macros.PREFLIGHT_ARMS
        for opponent in macros.DETERMINISTIC_OPPONENTS
    ]
    return {
        "schema_version": 1,
        "analysis_id": "trace_preflight",
        "status": "PASS",
        "admission_decision": "admit_factorial_acquisition",
        "protocol_commit": PROTOCOL_COMMIT,
        "arms": 4,
        "opponents": 5,
        "trajectory_units": 1_000,
        "executions": 3_000,
        "mismatch_units": 0,
        "trace_mismatch_units": 0,
        "outcome_mismatch_units": 0,
        "error_mismatch_units": 0,
        "decision_count_mismatch_units": 0,
        "rows": rows,
        "claim_boundary": "bounded",
    }


def bootstrap_rate(clusters, disagreements, interval):
    return {
        "clusters": clusters,
        "estimate": disagreements / clusters,
        "bootstrap_95_ci": interval,
        "bootstrap_draws": 100_000,
        "bootstrap_seed": 2026083118,
    }


def stress_payload():
    cluster_rows = []
    strata = {}
    total = {"trace": 0, "outcome": 0, "decision": 0, "error": 0, "policy": 0}
    actors = 0
    for opponent in macros.TIMED_OPPONENTS:
        for order in macros.ORDERS:
            counts = {"trace": 0, "outcome": 0, "decision": 0, "error": 0, "policy": 0}
            for seed in range(50):
                trace = seed == 0
                outcome = trace and opponent == "starmie"
                decision = trace and opponent == "dipplin" and order == "first"
                error = trace and opponent == "dipplin" and order == "second"
                policy = False
                flags = {
                    "trace": trace,
                    "outcome": outcome,
                    "decision": decision,
                    "error": error,
                    "policy": policy,
                }
                for name, flag in flags.items():
                    counts[name] += int(flag)
                    total[name] += int(flag)
                if trace:
                    actors += 1
                cluster_rows.append(
                    {
                        "opponent": opponent,
                        "task_id": f"{order}-{seed:03d}",
                        "actual_order": order,
                        "all_four_trace_agree": not trace,
                        "trace_disagreement": trace,
                        "outcome_disagreement": outcome,
                        "decision_count_disagreement": decision,
                        "error_disagreement": error,
                        "policy_error_present": policy,
                        "first_divergence": (
                            {"trace_line": 3, "actors": ["hero"]} if trace else None
                        ),
                    }
                )
            strata[f"{opponent}/{order}"] = {
                "trace_disagreement": bootstrap_rate(50, counts["trace"], [0.0, 0.08]),
                "outcome_disagreement_count": counts["outcome"],
                "decision_count_disagreement_count": counts["decision"],
                "error_disagreement_count": counts["error"],
                "policy_error_present_count": counts["policy"],
            }
    timing = {
        opponent: {
            run: {
                "games": 100,
                "mean_seconds": 0.02,
                "median_seconds": 0.02,
                "interquartile_range_seconds": [0.01, 0.03],
            }
            for run in macros.STRESS_RUNS
        }
        for opponent in macros.TIMED_OPPONENTS
    }
    return {
        "schema_version": 1,
        "analysis_id": "timed_search_stress",
        "status": "TRACE_DIVERGENCE",
        "protocol_commit": PROTOCOL_COMMIT,
        "clusters": 200,
        "executions": 800,
        "trace_disagreement_clusters": total["trace"],
        "trace_disagreement": bootstrap_rate(200, total["trace"], [0.005, 0.04]),
        "outcome_disagreement_clusters": total["outcome"],
        "decision_count_disagreement_clusters": total["decision"],
        "error_disagreement_clusters": total["error"],
        "policy_error_present_clusters": total["policy"],
        "first_divergence_actor_counts": {"hero": actors},
        "strata": strata,
        "timing": timing,
        "cluster_rows": cluster_rows,
        "sources": [
            {
                "opponent": opponent,
                "path": f"artifacts/pevl_20260824/stress/{opponent}/proof.json",
                "sha256": "b" * 64,
            }
            for opponent in macros.TIMED_OPPONENTS
        ],
        "bootstrap_note": "clustered",
        "pevl_level_6_boundary": "does not prove a unique causal source",
    }


def factorial_sources():
    return [
        {
            "cell": cell,
            "opponent": opponent,
            "path": f"paper/data/pevl/factorial/raw/{cell.lower()}_{opponent}.json",
            "sha256": "d" * 64,
        }
        for cell in ("C2", "C3", "C4")
        for opponent in macros.DETERMINISTIC_OPPONENTS
    ]


def factorial_payload():
    rates = {"C1": 0.50, "C2": 0.52, "C3": 0.53, "C4": 0.56}
    estimates = {
        "primary_c4_minus_c1": rates["C4"] - rates["C1"],
        "representation_main": 0.5
        * ((rates["C2"] - rates["C1"]) + (rates["C4"] - rates["C3"])),
        "training_main": 0.5
        * ((rates["C3"] - rates["C1"]) + (rates["C4"] - rates["C2"])),
        "interaction": rates["C4"] - rates["C3"] - rates["C2"] + rates["C1"],
    }
    contrasts = {
        name: {
            "estimate": estimate,
            "bootstrap_95_ci": [estimate - 0.02, estimate + 0.02],
            "bootstrap_draws": 100_000,
            "bootstrap_seed": 2026083117,
            "resampling": "paired units within each of ten opponent-by-order strata",
        }
        for name, estimate in estimates.items()
    }
    return {
        "schema_version": 1,
        "analysis_id": "factorial",
        "status": "ADMITTED_SEED_MATCHED",
        "admission_decision": "admit_with_bounded_wording",
        "protocol_commit": PROTOCOL_COMMIT,
        "target_population": "frozen population",
        "units": 2_000,
        "games": 12_000,
        "control_mismatch_units": 0,
        "cell_win_rates": rates,
        "contrasts": contrasts,
        "simple_effects_descriptive": {
            "c2_minus_c1": rates["C2"] - rates["C1"],
            "c3_minus_c1": rates["C3"] - rates["C1"],
            "c4_minus_c1": rates["C4"] - rates["C1"],
            "c4_minus_c2": rates["C4"] - rates["C2"],
            "c4_minus_c3": rates["C4"] - rates["C3"],
        },
        "primary_mcnemar": {
            "c4_only_wins": 180,
            "c1_only_wins": 60,
            "exact_two_sided_p": 0.00001,
            "role": "secondary",
        },
        "pevl_levels": {
            "levels_1_to_5": "bounded",
            "level_6": "the audit does not prove a unique causal source",
            "level_7": "not established",
            "level_8": "seed-matched only",
        },
        "sources": factorial_sources(),
    }


def suppressed_factorial_payload():
    return {
        "schema_version": 1,
        "analysis_id": "factorial",
        "status": "SUPPRESSED_CONTROL_PARITY_FAILURE",
        "admission_decision": "suppress_all_factorial_contrasts",
        "protocol_commit": PROTOCOL_COMMIT,
        "control_mismatch_units": 2,
        "first_control_mismatches": [
            {"opponent": "b0", "actual_order": "first", "pair_index": 1},
            {"opponent": "d842", "actual_order": "second", "pair_index": 2},
        ],
        "sources": factorial_sources(),
    }


def combined_payload(preflight, stress, factorial):
    return {
        "schema_version": 1,
        "framework": "Paired Evaluation Validity Ladder",
        "protocol": "paper/protocol/PEVL_PROSPECTIVE_PROTOCOL.md",
        "historical_control_parity": {},
        "prospective_trace_preflight": preflight,
        "timed_search_stress": stress,
        "gated_factorial": factorial,
        "claim_boundary": "bounded",
    }


def write_inputs(tmp_path, *, factorial=None):
    preflight = preflight_payload()
    stress = stress_payload()
    factorial = factorial_payload() if factorial is None else factorial
    payloads = {
        "preflight": preflight,
        "stress": stress,
        "factorial": factorial,
        "combined": combined_payload(preflight, stress, factorial),
    }
    paths = {}
    for label, payload in payloads.items():
        path = tmp_path / f"{label}.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        paths[label] = path
    return paths


def run_builder(paths, output):
    return macros.build_result_macros(
        preflight_path=paths["preflight"],
        stress_path=paths["stress"],
        factorial_path=paths["factorial"],
        combined_path=paths["combined"],
        output_path=output,
    )


def test_builds_complete_admitted_macro_families_deterministically(tmp_path):
    paths = write_inputs(tmp_path)
    output = tmp_path / "pevl_results_macros.tex"

    result = run_builder(paths, output)
    first = output.read_text(encoding="utf-8")
    second_result = run_builder(paths, output)
    second = output.read_text(encoding="utf-8")

    assert result["stress_status"] == "TRACE_DIVERGENCE"
    assert result["factorial_status"] == "ADMITTED_SEED_MATCHED"
    assert result["output_sha256"] == hashlib.sha256(first.encode()).hexdigest()
    assert second_result["output_sha256"] == result["output_sha256"]
    assert first == second
    assert r"\newcommand{\PEVLPreflightReady}{}" in first
    assert r"\newcommand{\PEVLPreflightTraceMismatches}{0}" in first
    assert r"\newcommand{\PEVLPreflightOutcomeMismatches}{0}" in first
    assert r"\newcommand{\PEVLPreflightErrorMismatches}{0}" in first
    assert r"\newcommand{\PEVLPreflightDecisionMismatches}{0}" in first
    assert r"\newcommand{\PEVLTimedStressReady}{}" in first
    assert r"\newcommand{\PEVLTimedStressTraceMismatches}{4}" in first
    assert r"\newcommand{\PEVLTimedStressTraceMismatchPct}{2.00}" in first
    assert r"\newcommand{\PEVLTimedStressAbstractSentence}" in first
    assert r"\newcommand{\PEVLTimedStressResultsParagraph}" in first
    assert r"\newcommand{\PEVLTimedStressTableRows}" in first
    assert r"\newcommand{\PEVLFactorialReady}{}" in first
    assert r"\newcommand{\PEVLFactorialAdmitted}{}" in first
    assert r"\newcommand{\PEVLFactorialPrimaryEstimatePP}{+6.00}" in first
    assert r"\newcommand{\PEVLFactorialAbstractSentence}" in first
    assert r"\newcommand{\PEVLFactorialResultsParagraph}" in first
    assert r"\newcommand{\PEVLFactorialResultsTable}" in first
    assert "PEVLFactorialSuppressedReady" not in first


def test_suppressed_factorial_emits_distinct_no_effect_family(tmp_path):
    paths = write_inputs(tmp_path, factorial=suppressed_factorial_payload())
    output = tmp_path / "pevl_results_macros.tex"

    result = run_builder(paths, output)
    text = output.read_text(encoding="utf-8")

    assert result["factorial_status"] == "SUPPRESSED_CONTROL_PARITY_FAILURE"
    assert r"\newcommand{\PEVLFactorialReady}{}" in text
    assert r"\newcommand{\PEVLFactorialSuppressedReady}{}" in text
    assert "PEVLFactorialAdmitted" not in text
    assert r"\newcommand{\PEVLFactorialSuppressedMismatchUnits}{2}" in text
    assert r"\newcommand{\PEVLFactorialAbstractSentence}" in text
    assert r"\newcommand{\PEVLFactorialResultsParagraph}" in text
    assert r"\newcommand{\PEVLFactorialResultsTable}{}" in text
    assert "EstimatePP" not in text


def test_rejects_nonterminal_or_incomplete_interval_without_replacing_output(tmp_path):
    paths = write_inputs(tmp_path)
    output = tmp_path / "pevl_results_macros.tex"
    run_builder(paths, output)
    original = output.read_bytes()

    factor = json.loads(paths["factorial"].read_text(encoding="utf-8"))
    del factor["contrasts"]["interaction"]["bootstrap_95_ci"]
    paths["factorial"].write_text(json.dumps(factor), encoding="utf-8")
    combined = json.loads(paths["combined"].read_text(encoding="utf-8"))
    combined["gated_factorial"] = factor
    paths["combined"].write_text(json.dumps(combined), encoding="utf-8")
    with pytest.raises(macros.MacroInputError, match="interval"):
        run_builder(paths, output)
    assert output.read_bytes() == original

    factor = {"schema_version": 1, "analysis_id": "factorial", "status": "INCOMPLETE"}
    paths["factorial"].write_text(json.dumps(factor), encoding="utf-8")
    combined["gated_factorial"] = factor
    paths["combined"].write_text(json.dumps(combined), encoding="utf-8")
    with pytest.raises(macros.MacroInputError, match="not terminal"):
        run_builder(paths, output)
    assert output.read_bytes() == original


def test_rejects_standalone_combined_drift(tmp_path):
    paths = write_inputs(tmp_path)
    combined = json.loads(paths["combined"].read_text(encoding="utf-8"))
    combined["timed_search_stress"]["trace_disagreement_clusters"] = 99
    paths["combined"].write_text(json.dumps(combined), encoding="utf-8")

    with pytest.raises(macros.MacroInputError, match="does not exactly match"):
        run_builder(paths, tmp_path / "out.tex")


def test_tex_escape_covers_latex_metacharacters_and_control_whitespace():
    escaped = macros.tex_escape("\\{}$&#_%~^\nnext")
    assert escaped == (
        r"\textbackslash{}\{\}\$\&\#\_\%"
        r"\textasciitilde{}\textasciicircum{} next"
    )


def test_manuscript_wiring_uses_one_complete_terminal_factorial_family():
    base_macros = (macros.ROOT / "paper/pevl_macros.tex").read_text(encoding="utf-8")
    manuscript = (macros.ROOT / "paper/main.tex").read_text(encoding="utf-8")
    assert r"\InputIfFileExists{pevl_results_macros.tex}{}{%" in base_macros
    assert "Terminal PEVL result macros are missing" in base_macros
    assert "Trace-preflight results are not terminal" in base_macros
    assert "Timed-search stress results are not terminal" in base_macros
    assert "Factorial admission result is not terminal" in base_macros
    assert r"\PEVLTimedStressAbstractSentence\space\fi" in manuscript
    assert r"\PEVLFactorialAbstractSentence\space\fi" in manuscript
    assert r"\ifdefined\PEVLFactorialReady\PEVLFactorialAbstractSentence\space\fi" in manuscript
    assert r"\ifdefined\PEVLFactorialSuppressedReady" not in manuscript
    admitted_or_suppressed = manuscript.split(r"\ifdefined\PEVLFactorialReady")[-1]
    assert r"\PEVLFactorialResultsParagraph" in admitted_or_suppressed
    assert r"\PEVLFactorialResultsTable" in admitted_or_suppressed
    assert r"\ifdefined\PEVLFactorialAdmitted" in manuscript

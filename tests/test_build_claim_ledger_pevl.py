import copy
import csv
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from paper.scripts import build_claim_ledger as ledger
from paper.scripts import build_pevl_result_macros as macros


SOURCE_ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy_file(root, relative):
    source = SOURCE_ROOT / relative
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def write_json(root, relative, payload):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_source(root, relative, content):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return digest(path)


def prepare_static_tree(root):
    seed = json.loads((SOURCE_ROOT / ledger.PEVL_SEED_AUDIT).read_text(encoding="utf-8"))
    historical = json.loads(
        (SOURCE_ROOT / ledger.PEVL_HISTORICAL).read_text(encoding="utf-8")
    )
    fixed = {
        ledger.PEVL_SYNTHETIC,
        ledger.PEVL_SYNTHETIC_MATRIX,
        "paper/synthetic/results/pevl_results.schema.json",
        "paper/synthetic/pevl_synthetic.py",
        "paper/supplement/PEVL_FRAMEWORK.md",
        ledger.PEVL_SEED_AUDIT,
        "paper/scripts/audit_seed_namespace.py",
        ledger.PEVL_HISTORICAL,
        "paper/scripts/analyze_ablation.py",
        ledger.PEVL_PROTOCOL,
        ledger.PEVL_ANALYZER,
    }
    inventories = [seed["sources"], historical["sources"]]
    for relative in sorted(
        fixed | {item["path"] for inventory in inventories for item in inventory}
    ):
        copy_file(root, relative)

    # The historical summary freezes old evaluator bytes. Rebase only this temp
    # fixture's inventory to the copied current files so byte validation can be
    # exercised without changing the real frozen summary.
    for item in historical["sources"]:
        item["sha256"] = digest(root / item["path"])
    historical["script_sha256"] = digest(root / "paper/scripts/analyze_ablation.py")
    write_json(root, ledger.PEVL_HISTORICAL, historical)


def preflight_payload(root, *, status="PASS"):
    rows = []
    for arm in macros.PREFLIGHT_ARMS:
        for opponent in macros.DETERMINISTIC_OPPONENTS:
            relative = f"paper/data/pevl/preflight/raw/{arm.lower()}_{opponent}.json"
            source_hash = write_source(root, relative, f"{arm}/{opponent}\n".encode())
            failed = status == "FAIL" and not rows
            rows.append(
                {
                    "arm": arm,
                    "opponent": opponent,
                    "passed": not failed,
                    "mismatch_units": int(failed),
                    "trace_mismatch_units": int(failed),
                    "outcome_mismatch_units": 0,
                    "error_mismatch_units": 0,
                    "decision_count_mismatch_units": 0,
                    "trajectory_units": 50,
                    "executions": 150,
                    "source": relative,
                    "source_sha256": source_hash,
                }
            )
    return {
        "schema_version": 1,
        "analysis_id": "trace_preflight",
        "status": status,
        "admission_decision": (
            "admit_factorial_acquisition" if status == "PASS" else "suppress_factorial"
        ),
        "protocol_commit": ledger.PEVL_PROTOCOL_COMMIT,
        "arms": 4,
        "opponents": 5,
        "trajectory_units": 1_000,
        "executions": 3_000,
        "mismatch_units": int(status == "FAIL"),
        "trace_mismatch_units": int(status == "FAIL"),
        "outcome_mismatch_units": 0,
        "error_mismatch_units": 0,
        "decision_count_mismatch_units": 0,
        "rows": rows,
        "claim_boundary": (
            "Passing is bounded within-arm reproducibility and does not establish "
            "cross-arm event alignment."
        ),
    }


def bootstrap_rate(clusters, disagreements, interval):
    return {
        "clusters": clusters,
        "estimate": disagreements / clusters,
        "bootstrap_95_ci": interval,
        "bootstrap_draws": 100_000,
        "bootstrap_seed": 2026083118,
    }


def stress_payload(root, *, parity=False):
    cluster_rows = []
    strata = {}
    total = {"trace": 0, "outcome": 0, "decision": 0, "error": 0, "policy": 0}
    actor_count = 0
    for opponent in macros.TIMED_OPPONENTS:
        for order in macros.ORDERS:
            counts = {"trace": 0, "outcome": 0, "decision": 0, "error": 0, "policy": 0}
            for seed in range(50):
                trace = not parity and seed == 0
                flags = {
                    "trace": trace,
                    "outcome": trace and opponent == "starmie",
                    "decision": trace and opponent == "dipplin" and order == "first",
                    "error": trace and opponent == "dipplin" and order == "second",
                    "policy": False,
                }
                for name, value in flags.items():
                    counts[name] += int(value)
                    total[name] += int(value)
                actor_count += int(trace)
                cluster_rows.append(
                    {
                        "opponent": opponent,
                        "task_id": f"{order}-{seed:03d}",
                        "actual_order": order,
                        "all_four_trace_agree": not trace,
                        "trace_disagreement": trace,
                        "outcome_disagreement": flags["outcome"],
                        "decision_count_disagreement": flags["decision"],
                        "error_disagreement": flags["error"],
                        "policy_error_present": False,
                        "first_divergence": (
                            {"trace_line": 3, "actors": ["hero"]} if trace else None
                        ),
                    }
                )
            strata[f"{opponent}/{order}"] = {
                "trace_disagreement": bootstrap_rate(
                    50, counts["trace"], [0.0, 0.06]
                ),
                "outcome_disagreement_count": counts["outcome"],
                "decision_count_disagreement_count": counts["decision"],
                "error_disagreement_count": counts["error"],
                "policy_error_present_count": 0,
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
    sources = []
    for opponent in macros.TIMED_OPPONENTS:
        relative = f"paper/data/pevl/stress/raw/{opponent}_proof.json"
        sources.append(
            {
                "opponent": opponent,
                "path": relative,
                "sha256": write_source(root, relative, f"{opponent}\n".encode()),
            }
        )
    return {
        "schema_version": 1,
        "analysis_id": "timed_search_stress",
        "status": "TRACE_PARITY" if parity else "TRACE_DIVERGENCE",
        "protocol_commit": ledger.PEVL_PROTOCOL_COMMIT,
        "clusters": 200,
        "executions": 800,
        "trace_disagreement_clusters": total["trace"],
        "trace_disagreement": bootstrap_rate(
            200, total["trace"], [0.0, 0.04] if parity else [0.005, 0.04]
        ),
        "outcome_disagreement_clusters": total["outcome"],
        "decision_count_disagreement_clusters": total["decision"],
        "error_disagreement_clusters": total["error"],
        "policy_error_present_clusters": 0,
        "first_divergence_actor_counts": {} if parity else {"hero": actor_count},
        "strata": strata,
        "timing": timing,
        "cluster_rows": cluster_rows,
        "sources": sources,
        "bootstrap_note": "seed-condition cluster bootstrap",
        "pevl_level_6_boundary": "does not prove a unique causal source",
    }


def factorial_sources(root):
    sources = []
    for cell in ("C2", "C3", "C4"):
        for opponent in macros.DETERMINISTIC_OPPONENTS:
            relative = f"paper/data/pevl/factorial/raw/{cell.lower()}_{opponent}.json"
            sources.append(
                {
                    "cell": cell,
                    "opponent": opponent,
                    "path": relative,
                    "sha256": write_source(
                        root, relative, f"{cell}/{opponent}\n".encode()
                    ),
                }
            )
    return sources


def admitted_factorial(root):
    rates = {"C1": 0.50, "C2": 0.52, "C3": 0.53, "C4": 0.56}
    estimates = {
        "primary_c4_minus_c1": 0.06,
        "representation_main": 0.025,
        "training_main": 0.035,
        "interaction": 0.01,
    }
    return {
        "schema_version": 1,
        "analysis_id": "factorial",
        "status": "ADMITTED_SEED_MATCHED",
        "admission_decision": "admit_with_bounded_wording",
        "protocol_commit": ledger.PEVL_PROTOCOL_COMMIT,
        "target_population": "five frozen opponents by two orders",
        "units": 2_000,
        "games": 12_000,
        "control_mismatch_units": 0,
        "cell_win_rates": rates,
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
        "simple_effects_descriptive": {
            "c2_minus_c1": 0.02,
            "c3_minus_c1": 0.03,
            "c4_minus_c1": 0.06,
            "c4_minus_c2": 0.04,
            "c4_minus_c3": 0.03,
        },
        "primary_mcnemar": {
            "c4_only_wins": 180,
            "c1_only_wins": 60,
            "exact_two_sided_p": 4.0990161694649685e-15,
            "role": "secondary",
        },
        "pevl_levels": {
            "levels_1_to_5": "bounded",
            "level_6": "does not prove a unique causal source",
            "level_7": "not established for the restricted engine",
            "level_8": "bounded seed-matched estimates admitted",
        },
        "sources": factorial_sources(root),
    }


def write_factorial_units(root):
    path = root / ledger.PEVL_FACTORIAL_UNITS
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "opponent", "actual_order", "pair_index", "scheduled_seed",
        "engine_seed_uint32", "physical_seat", "c1_win", "c2_win",
        "c3_win", "c4_win", "c1_draw", "c2_draw", "c3_draw", "c4_draw",
        "c1_decisions", "c2_decisions", "c3_decisions", "c4_decisions",
    ]
    bases = {
        "b0": 2026082700,
        "d842": 2026083700,
        "master": 2026084700,
        "replay": 2026085700,
        "alakazam_no_search": 2026086700,
    }
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        unit = 0
        for opponent in macros.DETERMINISTIC_OPPONENTS:
            for order in macros.ORDERS:
                for pair_index in range(200):
                    scheduled = bases[opponent] + (
                        1_000_000 if order == "second" else 0
                    ) + pair_index
                    wins = {
                        "c1": int(unit < 1_000),
                        "c2": int(unit < 1_040),
                        "c3": int(unit < 1_060),
                        "c4": int(unit < 940 or 1_000 <= unit < 1_180),
                    }
                    writer.writerow(
                        {
                            "opponent": opponent,
                            "actual_order": order,
                            "pair_index": pair_index,
                            "scheduled_seed": scheduled,
                            "engine_seed_uint32": scheduled,
                            "physical_seat": pair_index % 2,
                            **{f"{cell}_win": value for cell, value in wins.items()},
                            **{f"{cell}_draw": 0 for cell in wins},
                            **{f"{cell}_decisions": 10 for cell in wins},
                        }
                    )
                    unit += 1
    return path


def combined_historical(root):
    historical = json.loads((root / ledger.PEVL_HISTORICAL).read_text(encoding="utf-8"))
    audit = historical["control_parity_audit"]
    return {
        "status": historical["status"],
        "units": audit["pairs"],
        "outcome_record_mismatch_units": audit["outcome_record_mismatch_units"],
        "outcome_record_mismatch_rate": (
            audit["outcome_record_mismatch_units"] / audit["pairs"]
        ),
        "serialized_record_mismatch_units": audit[
            "serialized_record_mismatch_units"
        ],
        "serialized_record_mismatch_rate": (
            audit["serialized_record_mismatch_units"] / audit["pairs"]
        ),
        "by_opponent": audit["by_opponent"],
        "cause_audit": historical["cause_audit"],
        "source": ledger.PEVL_HISTORICAL,
        "source_sha256": digest(root / ledger.PEVL_HISTORICAL),
    }


def write_terminal_inputs(root, *, preflight=None, stress=None, factorial=None):
    preflight = preflight_payload(root) if preflight is None else preflight
    stress = stress_payload(root) if stress is None else stress
    factorial = admitted_factorial(root) if factorial is None else factorial
    combined = {
        "schema_version": 1,
        "framework": "Paired Evaluation Validity Ladder",
        "protocol": ledger.PEVL_PROTOCOL,
        "historical_control_parity": combined_historical(root),
        "prospective_trace_preflight": preflight,
        "timed_search_stress": stress,
        "gated_factorial": factorial,
        "claim_boundary": "Game-engine results cannot establish Level 7.",
    }
    for relative, payload in (
        (ledger.PEVL_PREFLIGHT, preflight),
        (ledger.PEVL_STRESS, stress),
        (ledger.PEVL_FACTORIAL, factorial),
        (ledger.PEVL_COMBINED, combined),
    ):
        write_json(root, relative, payload)
    return preflight, stress, factorial, combined


@pytest.fixture
def pevl_root(tmp_path, monkeypatch):
    prepare_static_tree(tmp_path)
    write_factorial_units(tmp_path)
    write_terminal_inputs(tmp_path)
    monkeypatch.setattr(ledger, "ROOT", tmp_path)
    return tmp_path


def test_admitted_pevl_rows_are_append_ready_and_hash_actual_sources(pevl_root):
    rows = ledger.build_pevl_claim_rows()
    assert [row["claim_id"] for row in rows] == [
        "PEVL-SYNTH", "PEVL-SEED", "PEVL-HIST", "PEVL-PREFLIGHT",
        "PEVL-STRESS", "PEVL-FACTORIAL",
    ]
    assert all(list(row) == ledger.FIELDS for row in rows)
    assert all(row["include_or_omit"] == "INCLUDE" for row in rows)
    ledger.validate_ledger(rows)
    by_id = {row["claim_id"]: row for row in rows}
    assert "2,800/2,800 requested seeds changed" in by_id["PEVL-SEED"]["verified_value"]
    assert "2,800 unique consumed seeds, 0 collisions" in by_id["PEVL-SEED"]["verified_value"]
    assert "0/1,000" in by_id["PEVL-PREFLIGHT"]["verified_value"]
    assert "4/200" in by_id["PEVL-STRESS"]["verified_value"]
    assert "does not establish Level 7" in by_id["PEVL-STRESS"]["limitations"]
    assert "+6.00 pp" in by_id["PEVL-FACTORIAL"]["verified_value"]
    assert "+2.50 pp" in by_id["PEVL-FACTORIAL"]["verified_value"]
    assert ledger.PEVL_FACTORIAL_UNITS in by_id["PEVL-FACTORIAL"]["raw_source"]
    assert "Level 7 is not established" in by_id["PEVL-FACTORIAL"]["limitations"]


def test_suppressed_factorial_is_transparent_and_rejects_stale_units(pevl_root):
    factor = {
        "schema_version": 1,
        "analysis_id": "factorial",
        "status": "SUPPRESSED_CONTROL_PARITY_FAILURE",
        "admission_decision": "suppress_all_factorial_contrasts",
        "protocol_commit": ledger.PEVL_PROTOCOL_COMMIT,
        "control_mismatch_units": 2,
        "first_control_mismatches": [
            {"opponent": "b0", "actual_order": "first", "pair_index": 1},
            {"opponent": "d842", "actual_order": "second", "pair_index": 2},
        ],
        "sources": factorial_sources(pevl_root),
    }
    preflight = preflight_payload(pevl_root)
    stress = stress_payload(pevl_root)
    write_terminal_inputs(
        pevl_root, preflight=preflight, stress=stress, factorial=factor
    )
    with pytest.raises(ValueError, match="stale unit table"):
        ledger.build_pevl_claim_rows()
    (pevl_root / ledger.PEVL_FACTORIAL_UNITS).unlink()
    row = ledger.build_pevl_claim_rows()[-1]
    assert row["status"] == "VERIFIED"
    assert "2 repeated-control mismatch units" in row["verified_value"]
    assert "no effects admitted" in row["verified_value"]
    assert "Estimate" not in row["verified_value"]
    assert ledger.PEVL_FACTORIAL_UNITS not in row["raw_source"]


def test_trace_parity_and_preflight_suppression_are_reported_without_effect_leakage(
    pevl_root,
):
    parity_stress = stress_payload(pevl_root, parity=True)
    factor = admitted_factorial(pevl_root)
    write_factorial_units(pevl_root)
    write_terminal_inputs(pevl_root, stress=parity_stress, factorial=factor)
    stress_row = ledger.build_pevl_claim_rows()[4]
    assert "TRACE_PARITY; 0/200" in stress_row["verified_value"]
    assert "divergence" not in stress_row["verified_value"].lower()

    preflight = preflight_payload(pevl_root, status="FAIL")
    stress = stress_payload(pevl_root)
    suppressed = {
        "schema_version": 1,
        "analysis_id": "factorial",
        "status": "SUPPRESSED_BY_PREFLIGHT",
        "admission_decision": "suppress",
        "protocol_commit": ledger.PEVL_PROTOCOL_COMMIT,
        "reason": "the frozen four-arm trace preflight did not pass in full",
    }
    write_terminal_inputs(
        pevl_root, preflight=preflight, stress=stress, factorial=suppressed
    )
    (pevl_root / ledger.PEVL_FACTORIAL_UNITS).unlink()
    rows = ledger.build_pevl_claim_rows()
    assert "FAIL; 1/1,000" in rows[3]["verified_value"]
    assert "SUPPRESSED_BY_PREFLIGHT" in rows[5]["verified_value"]
    assert "no factorial effects admitted" in rows[5]["verified_value"]
    assert ledger.PEVL_FACTORIAL_UNITS not in rows[5]["raw_source"]


def test_terminal_inputs_fail_closed_on_nonterminal_and_combined_drift(pevl_root):
    preflight = preflight_payload(pevl_root)
    stress = stress_payload(pevl_root)
    factor = admitted_factorial(pevl_root)
    factor["status"] = "INCOMPLETE"
    factor.pop("admission_decision")
    write_terminal_inputs(
        pevl_root, preflight=preflight, stress=stress, factorial=factor
    )
    with pytest.raises(ValueError, match="not terminal"):
        ledger.build_pevl_claim_rows()

    factor = admitted_factorial(pevl_root)
    write_factorial_units(pevl_root)
    _preflight, _stress, _factor, combined = write_terminal_inputs(
        pevl_root, preflight=preflight, stress=stress, factorial=factor
    )
    combined["historical_control_parity"]["units"] = 2_799
    write_json(pevl_root, ledger.PEVL_COMBINED, combined)
    with pytest.raises(ValueError, match="historical control-parity"):
        ledger.build_pevl_claim_rows()

    write_factorial_units(pevl_root)
    factor = admitted_factorial(pevl_root)
    factor["protocol_commit"] = "d" * 40
    write_terminal_inputs(
        pevl_root, preflight=preflight, stress=stress, factorial=factor
    )
    with pytest.raises(ValueError, match="protocol commits"):
        ledger.build_pevl_claim_rows()


def test_source_tamper_and_factorial_unit_drift_are_rejected(pevl_root):
    stress = json.loads((pevl_root / ledger.PEVL_STRESS).read_text(encoding="utf-8"))
    proof = pevl_root / stress["sources"][0]["path"]
    proof.write_bytes(b"tampered\n")
    with pytest.raises(ValueError, match="source hash mismatch"):
        ledger.build_pevl_claim_rows()

    # Restore terminal inputs and then alter one unit without changing the summary.
    write_factorial_units(pevl_root)
    write_terminal_inputs(pevl_root)
    units = pevl_root / ledger.PEVL_FACTORIAL_UNITS
    with units.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    rows[1_500]["c4_win"] = "1"
    with units.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError, match="C4 win rate"):
        ledger.build_pevl_claim_rows()


def test_historical_git_source_preserves_frozen_evaluator_bytes():
    relative = "training/evaluate_deterministic_crn.py"
    commit = ledger.HISTORICAL_SOURCE_COMMITS[relative]
    expected = "fa60021b0906401aeb2c7c33e0f65f586eff256d83d689d688a86a40480e1341"
    source = f"git:{commit}:{relative}"

    assert ledger.sha256_file(relative) != expected
    assert ledger.source_sha256(source) == expected
    paths, hashes = ledger.artifact_bundle_from_inventory(
        [{"path": relative, "sha256": expected}],
        git_fallback_by_path=ledger.HISTORICAL_SOURCE_COMMITS,
    )
    assert paths == source
    assert hashes == expected


def test_git_source_rejects_unsafe_or_missing_objects():
    commit = next(iter(ledger.HISTORICAL_SOURCE_COMMITS.values()))
    with pytest.raises(ValueError, match="repository-relative"):
        ledger.source_sha256(f"git:{commit}:../outside")
    with pytest.raises(ValueError, match="cannot read immutable Git source"):
        ledger.source_sha256(f"git:{'0' * 40}:paper/main.tex")

from __future__ import annotations

import json
from pathlib import Path

from scripts import package_a2_order_finalist as package


def _report(path: Path, first_hash: str, second_hash: str, *, top1_delta: float) -> Path:
    baseline = {
        "count_accuracy": 0.98,
        "single_index_top1": 0.70,
        "single_index_top3": 0.92,
        "single_semantic_nonforced_top1": 0.76,
        "single_semantic_top3_eligible": 0.96,
    }
    specialist = dict(baseline)
    specialist["single_index_top1"] += top1_delta
    rates = lambda values: {name: {"value": value} for name, value in values.items()}
    path.write_text(json.dumps({
        "evaluation_scope": "stateless_npz_ranker_only; runtime overrides and search are excluded",
        "rows_considered": 100,
        "models": {
            "temporal_full": {"sha256": first_hash.lower()},
            "second_specialist": {"sha256": second_hash.lower()},
        },
        "results": {
            "temporal_full": {"overall": {"rates": rates(baseline)}},
            "second_specialist": {"overall": {"rates": rates(specialist)}},
        },
    }), encoding="utf-8")
    return path


def test_gate_rejects_byte_identical_non_specialist(tmp_path: Path):
    model_hash = "A" * 64
    broad = _report(tmp_path / "broad.json", model_hash, model_hash, top1_delta=0.0)
    hard = _report(tmp_path / "hard.json", model_hash, model_hash, top1_delta=0.0)
    result = package.heldout_gate(broad, hard, model_hash, model_hash)

    assert result["passed"] is False
    assert result["gameplay_eligible"] is False
    assert result["checks"]["distinct_second_model"] is False
    assert result["checks"]["broad_single_index_top1_material"] is False
    assert result["scopes"]["broad_second"]["delta"]["single_index_top1"] == 0.0


def test_gate_accepts_distinct_material_top1_without_retention_regression(tmp_path: Path):
    first_hash = "A" * 64
    second_hash = "B" * 64
    broad = _report(tmp_path / "broad.json", first_hash, second_hash, top1_delta=0.006)
    hard = _report(tmp_path / "hard.json", first_hash, second_hash, top1_delta=0.006)
    result = package.heldout_gate(broad, hard, first_hash, second_hash)

    assert result["passed"] is True
    assert result["diagnostic_only"] is True
    assert result["gameplay_eligible"] is False
    assert all(result["checks"].values())


def _paired_summary(*, pairs: int, delta: float, lower: float, candidate_discordant: int = 1, control_discordant: int = 0, errors: int = 0) -> dict:
    return {
        "pairs": pairs,
        "paired_difference": delta,
        "paired_95_ci": [lower, delta + 0.02],
        "discordant_candidate_wins": candidate_discordant,
        "discordant_control_wins": control_discordant,
        "candidate_policy_errors": errors,
        "control_policy_errors": 0,
        "opponent_policy_errors": 0,
    }


def _gameplay_report(path: Path, candidate_tree: str) -> dict:
    engine_hash = package.PINNED_PRODUCTION_ENGINE_SHA256
    report = {
        "candidate_sha256": candidate_tree.lower(),
        "control_sha256": package.a2.FROZEN_SOURCE_TREE_SHA256.lower(),
        "opponent_sha256": package.a2.FROZEN_SOURCE_TREE_SHA256.lower(),
        "engine_sha256": package.CERTIFIED_DETERMINISTIC_ENGINE_SHA256.lower(),
        "rng_provenance": {
            "engine": "local_seeded_mt19937",
            "deviceRand": False,
            "native_gameplay_random_device": False,
            "same_seed_within_candidate_control_pair": True,
            "same_actual_order_and_physical_seat_within_pair": True,
        },
        "production_engine_preserved": True,
        "production_engine_sha256_before": engine_hash,
        "production_engine_sha256_after": engine_hash,
        "pairs_per_order": 1000,
        "games": 4000,
        "orders": {
            "first": _paired_summary(
                pairs=1000,
                delta=0.0,
                lower=0.0,
                candidate_discordant=0,
                control_discordant=0,
            ),
            "second": _paired_summary(pairs=1000, delta=0.04, lower=0.01),
        },
        "overall": _paired_summary(pairs=2000, delta=0.02, lower=0.005),
    }
    path.write_text(json.dumps(report), encoding="utf-8")
    return report


def test_gameplay_gate_promotes_only_exact_first_parity_and_positive_two_sided_bounds(tmp_path: Path):
    candidate_tree = "C" * 64
    evidence = tmp_path / "gameplay.json"
    _gameplay_report(evidence, candidate_tree)

    result = package.gameplay_gate(evidence, candidate_tree)

    assert result["passed"] is True
    assert result["gameplay_eligible"] is True
    assert result["checks"]["first_order_exact_parity"] is True
    assert result["checks"]["second_order_two_sided_95_lower_positive"] is True
    assert result["checks"]["overall_two_sided_95_lower_positive"] is True
    assert all(result["checks"].values())


def test_gameplay_gate_rejects_wrong_identity_errors_short_run_and_nonpositive_lower_bound(tmp_path: Path):
    candidate_tree = "C" * 64
    evidence = tmp_path / "gameplay.json"
    report = _gameplay_report(evidence, "D" * 64)
    report["pairs_per_order"] = 999
    report["games"] = 3995
    report["orders"]["first"]["candidate_policy_errors"] = 1
    report["orders"]["first"]["paired_difference"] = 0.001
    report["orders"]["first"]["discordant_candidate_wins"] = 1
    report["orders"]["second"]["paired_95_ci"][0] = 0.0
    report["overall"]["paired_95_ci"][0] = -0.001
    report["production_engine_sha256_after"] = "F" * 64
    report["engine_sha256"] = "A" * 64
    report["rng_provenance"]["same_seed_within_candidate_control_pair"] = False
    evidence.write_text(json.dumps(report), encoding="utf-8")

    result = package.gameplay_gate(evidence, candidate_tree)

    assert result["passed"] is False
    assert result["gameplay_eligible"] is False
    assert result["checks"] == {
        "candidate_matches_fresh_stage": False,
        "control_is_pinned_authentic_a2": True,
        "opponent_is_pinned_authentic_a2": True,
        "certified_deterministic_engine": False,
        "deterministic_paired_rng": False,
        "production_engine_preserved": False,
        "both_actual_orders_present": True,
        "minimum_pairs_per_order": False,
        "complete_game_count": False,
        "zero_all_policy_errors": False,
        "first_order_exact_parity": False,
        "second_order_two_sided_95_lower_positive": False,
        "overall_two_sided_95_lower_positive": False,
    }

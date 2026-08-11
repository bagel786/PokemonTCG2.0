from __future__ import annotations

import copy
import hashlib

import pytest

from scripts.compare_dipplin_d0_d1 import (
    ComparisonError,
    QualificationThresholds,
    VERDICT_D0,
    VERDICT_D1,
    compare_reports,
    independent_difference,
    wilson,
)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _cell(rows):
    completed = [row for row in rows if row["completed"]]
    wins = sum(row["win"] for row in completed)
    games = len(completed)
    return {
        "scheduled_games": len(rows),
        "games": games,
        "failed_games": len(rows) - games,
        "wins": wins,
        "draws": 0,
        "losses": games - wins,
        "win_rate": wins / games,
        "wilson_95": wilson(wins, games),
        "hero_policy_errors": sum(row["hero_policy_errors"] for row in rows),
        "opponent_policy_errors": 0,
        "hero_illegal_actions": sum(row["hero_illegal_actions"] for row in rows),
        "opponent_illegal_actions": 0,
        "decisions": 10 * len(rows),
    }


def _report(
    *,
    arm: str,
    opponent: str,
    seed: int,
    wins: int,
    games: int = 20,
    bad_context: bool = False,
):
    rows = []
    for index in range(games):
        telemetry = {}
        intervened = False
        if arm == "d1":
            # First half are intervention games; the other half are genuine
            # attempted-search abstentions, not merely no-opportunity games.
            intervened = index < games // 2
            telemetry = {
                "d1_attempts": 1,
                "d1_abstentions": int(not intervened),
                "d1_overrides": int(intervened),
                "d0_d1_disagreements": int(intervened),
            }
            if intervened:
                telemetry["d1_override_context_boss"] = 1

        if arm == "d1" and bad_context:
            # Put all wins in abstention games, making the frequent Boss
            # intervention context observably negative.
            won = int(index >= games // 2 and index - games // 2 < wins)
        elif arm == "d1":
            # Intervention games win first.  Any remaining wins occur among
            # abstentions, so intervention outcomes beat abstention outcomes.
            won = int(index < wins)
        else:
            # Spread control wins across seats/orders.
            winning = {0, 5, 10, 15}
            if wins != 4:
                winning = set(range(wins))
            won = int(index in winning)
        rows.append(
            {
                "game_index": index,
                "hero_seat": index % 2,
                "actual_order": "first" if (index // 2) % 2 == 0 else "second",
                "completed": True,
                "win": won,
                "draw": 0,
                "hero_policy_errors": 0,
                "opponent_policy_errors": 0,
                "hero_illegal_actions": 0,
                "opponent_illegal_actions": 0,
                "hero_telemetry": telemetry,
                "d1_intervened": intervened,
                "opponent_name": opponent,
            }
        )

    overall = _cell(rows)
    artifact = _digest(f"artifact-{arm}")
    opponent_artifact = _digest(f"opponent-{opponent}")
    provenance = {
        "source_commit": "1" * 40,
        "source_bundle_sha256": "",
        "worker": "test",
        "seed": seed,
        "deck_a_sha256": _digest("frozen-dipplin-deck"),
        "deck_b_sha256": _digest(f"deck-{opponent}"),
        "submission_a_sha256": artifact,
        "submission_b_sha256": opponent_artifact,
        "artifact_a_sha256": artifact,
        "artifact_b_sha256": opponent_artifact,
        "engine_binary": "libcg.dylib",
        "engine_sha256": _digest("engine"),
        "evaluator_sha256": _digest("evaluator"),
        "external_adapter_sha256": _digest("adapter"),
        "evaluation_schema_sha256": _digest("schema"),
        "runtime_environment": {
            "process_ptcg": {},
            "submission_a_overrides": {},
            "submission_b_overrides": {"NO_SEARCH": "0"},
        },
        "archive_a_sha256": _digest(f"archive-{arm}"),
        "archive_b_sha256": _digest(f"opponent-archive-{opponent}"),
        "rng_contract": {
            "engine": "independent_std_random_device",
            "python_numpy_schedule_seed": seed,
            "paired_deals": False,
            "common_random_numbers": False,
        },
        "runtime_blinding_contract": {
            "hero_receives_opponent_label": False,
            "hero_receives_opponent_package_identity": False,
            "agent_call_payload": "engine_observation_only",
            "labels_added_in_parent_after_game": True,
        },
        "post_evaluation_submission_a_sha256": artifact,
        "post_evaluation_submission_b_sha256": opponent_artifact,
        "submission_artifacts_unchanged_during_evaluation": True,
    }
    counts = {
        "attempts": sum(row["hero_telemetry"].get("d1_attempts", 0) for row in rows),
        "abstentions": sum(row["hero_telemetry"].get("d1_abstentions", 0) for row in rows),
        "overrides": sum(row["hero_telemetry"].get("d1_overrides", 0) for row in rows),
        "d0_d1_disagreements": sum(
            row["hero_telemetry"].get("d0_d1_disagreements", 0) for row in rows
        ),
    }
    return {
        "schema": "dipplin-authentic-evaluation-v1",
        "hero_name": arm,
        "opponent_name": opponent,
        "scheduled_games": games,
        "games": games,
        "wins_a": overall["wins"],
        "win_rate_a": overall["win_rate"],
        "wilson_95": overall["wilson_95"],
        "hero_policy_errors": 0,
        "opponent_policy_errors": 0,
        "hero_illegal_actions": 0,
        "opponent_illegal_actions": 0,
        "failed_games": 0,
        "decisions": games * 10,
        "elapsed_seconds": 1.0,
        "overall": overall,
        "rng_provenance": {
            "engine": "unpaired_std_random_device",
            "python_numpy_seed_schedule": seed,
            "paired_deals": False,
            "common_random_numbers": False,
        },
        "latency_ms": {
            "hero": {
                "count": games * 5,
                "mean": 10.0 if arm == "d1" else 1.0,
                "p50": 8.0 if arm == "d1" else 1.0,
                "p95": 20.0 if arm == "d1" else 2.0,
                "p99": 30.0 if arm == "d1" else 3.0,
                "max": 40.0 if arm == "d1" else 4.0,
            }
        },
        "d1_intervention_analysis": {"canonical_counts": counts},
        "artifact_provenance": provenance,
        "game_rows": rows,
    }


def _population(
    *,
    d1_wins: int = 16,
    bad_context: bool = False,
    d1_seeds=(101, 202),
):
    opponents = ("a2", "d842", "alakazam_2_7", "alakazam_2_4a")
    seeds = (101, 202)
    d0 = [
        _report(arm="d0", opponent=opponent, seed=seed, wins=4)
        for opponent in opponents
        for seed in seeds
    ]
    d1 = [
        _report(
            arm="d1",
            opponent=opponent,
            seed=seed,
            wins=d1_wins,
            bad_context=bad_context,
        )
        for opponent in opponents
        for seed in d1_seeds
    ]
    return d0, d1


def test_qualified_report_is_explicitly_unpaired_and_covers_required_splits():
    d0, d1 = _population()
    result = compare_reports(d0, d1)

    assert result["verdict"] == VERDICT_D1
    assert result["comparison_design"]["paired"] is False
    assert result["sample"]["native_games_are_unpaired"] is True
    assert result["performance"]["d0"]["overall"]["games"] == 160
    assert set(result["performance"]["d1"]["opponent"]) == {
        "a2",
        "d842",
        "alakazam_2_7",
        "alakazam_2_4a",
    }
    assert set(result["performance"]["d1"]["actual_order"]) == {"first", "second"}
    assert set(result["performance"]["d1"]["seat"]) == {"0", "1"}
    assert result["d1_search"]["canonical_counts"] == {
        "attempts": 160,
        "abstentions": 80,
        "overrides": 80,
        "disagreements": 80,
    }
    assert result["d1_search"]["games"]["intervention"]["games"] == 80
    assert result["d1_search"]["games"]["abstention_only"]["games"] == 80
    assert result["d1_search"]["context_outcomes"]["boss"]["outcome"]["win_rate"] == 1.0
    assert result["qualification"]["failed_checks"] == []


def test_rejects_any_paired_or_common_random_number_label():
    d0, d1 = _population()
    d1[0]["rng_provenance"]["paired_deals"] = True
    with pytest.raises(ComparisonError, match="independent/unpaired"):
        compare_reports(d0, d1)


def test_schedule_seeds_remain_independent_arm_labels_not_pair_keys():
    d0, d1 = _population(d1_seeds=(303, 404))
    result = compare_reports(d0, d1)

    assert result["verdict"] == VERDICT_D1
    assert result["comparison_design"]["report_matching"] == "opponent_name only"
    assert result["provenance"]["schedule_seeds_by_arm_and_opponent"]["d0"]["a2"] == [
        101,
        202,
    ]
    assert result["provenance"]["schedule_seeds_by_arm_and_opponent"]["d1"]["a2"] == [
        303,
        404,
    ]


def test_rejects_mismatched_authentic_opponent_provenance():
    d0, d1 = _population()
    changed = _digest("wrong-opponent-build")
    d1[0]["artifact_provenance"].update(
        {
            "artifact_b_sha256": changed,
            "submission_b_sha256": changed,
            "post_evaluation_submission_b_sha256": changed,
        }
    )
    with pytest.raises(ComparisonError, match="opponent provenance differs"):
        compare_reports(d0, d1)


def test_material_matchup_collapse_forces_d0_preferred():
    d0, d1 = _population()
    # Rebuild both confirmation blocks for one opponent below its 20% D0 rate.
    replacements = [
        _report(arm="d1", opponent="a2", seed=seed, wins=2)
        for seed in (101, 202)
    ]
    d1 = [report for report in d1 if report["opponent_name"] != "a2"] + replacements
    result = compare_reports(d0, d1)

    assert result["verdict"] == VERDICT_D0
    assert "a2" in result["flags"]["material_matchup_collapses"]
    assert not result["qualification"]["checks"]["no_material_matchup_collapse"]


def test_negative_high_frequency_intervention_context_is_flagged():
    d0, d1 = _population(d1_wins=8, bad_context=True)
    result = compare_reports(d0, d1)

    assert result["verdict"] == VERDICT_D0
    assert result["flags"]["negative_high_frequency_intervention_contexts"]["boss"][
        "difference"
    ] < 0
    assert not result["qualification"]["checks"][
        "no_negative_high_frequency_intervention_context"
    ]


def test_one_schedule_block_cannot_claim_independent_confirmation():
    d0, d1 = _population()
    d0 = [report for report in d0 if report["artifact_provenance"]["seed"] == 101]
    d1 = [report for report in d1 if report["artifact_provenance"]["seed"] == 101]
    result = compare_reports(d0, d1)

    assert result["verdict"] == VERDICT_D0
    assert not result["qualification"]["checks"]["independent_fresh_schedule_blocks"]


def test_independent_difference_never_claims_pairing():
    result = independent_difference(
        {"games": 100, "wins": 70}, {"games": 100, "wins": 50}
    )
    assert result["paired"] is False
    assert result["estimate"] == pytest.approx(0.2)
    assert result["confidence_95"][0] > 0


def test_threshold_validation_fails_closed():
    d0, d1 = _population()
    with pytest.raises(ComparisonError, match="minimum sample"):
        compare_reports(
            d0,
            d1,
            thresholds=QualificationThresholds(min_opponents=0),
        )

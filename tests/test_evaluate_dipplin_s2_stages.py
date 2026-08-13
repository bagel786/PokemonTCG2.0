from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

import pytest

from scripts.evaluate_dipplin_s2_stages import (
    LATER_STAGE_DECISION_CONTRACT,
    StageEvaluationError,
    evaluate_spec,
    independent_difference,
    main,
    wilson,
)


BASELINE_TREE = "1" * 64
BASELINE_ARCHIVE = "2" * 64
CANDIDATE_TREE = "3" * 64
CANDIDATE_ARCHIVE = "4" * 64
HERO_DECK = "5" * 64
ENGINE = "6" * 64
EVALUATOR = "7" * 64
ADAPTER = "8" * 64
EVALUATION_SCHEMA = "9" * 64
OPPONENT_TREE = "a" * 64
OPPONENT_DECK = "b" * 64


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_result(
    path: Path,
    *,
    opponent_name: str,
    requested_games: int,
    wins: int,
    tree_sha256: str,
    archive_sha256: str,
    hero_name: str,
    s2_enabled: bool,
    actual_order: str = "second",
    failed_games: int = 0,
    quality: dict[str, int] | None = None,
    overrides: dict[int, int] | None = None,
    d1_intervened_games: set[int] | None = None,
    operational_telemetry: dict[str, int] | None = None,
) -> None:
    quality = quality or {}
    overrides = overrides or {}
    d1_intervened_games = d1_intervened_games or set()
    operational_telemetry = operational_telemetry or {}
    completed_games = requested_games - failed_games
    assert 0 <= wins <= completed_games
    rows: list[dict[str, Any]] = []
    for game_index in range(requested_games):
        completed = game_index >= failed_games
        won = int(completed and game_index - failed_games < wins)
        override_count = overrides.get(game_index, 0)
        telemetry: dict[str, int] = {"s2_enabled": int(s2_enabled)}
        if game_index == 0:
            telemetry.update(operational_telemetry)
        if override_count:
            telemetry.update({
                "s2_pre_attack_sequence_proof_checked": override_count + 1,
                "s2_pre_attack_sequence_proof_admitted": override_count,
                "s2_pre_attack_sequence_proof_overrides": override_count,
            })
        hero_seat = game_index % 2
        opponent_seat = 1 - hero_seat
        first_player = opponent_seat if actual_order == "second" else hero_seat
        rows.append(
            {
                "game_index": game_index,
                "hero_name": hero_name,
                "opponent_name": opponent_name,
                "hero_seat": hero_seat,
                "opponent_seat": opponent_seat,
                "first_player": first_player,
                "actual_order": actual_order,
                "completed": completed,
                "win": won,
                "draw": 0,
                "outcome": "failed" if not completed else "win" if won else "loss",
                "result_seat": (
                    None if not completed else hero_seat if won else opponent_seat
                ),
                "failure": {"type": "SyntheticFailure"} if not completed else None,
                "cleanup_errors": [],
                "hero_policy_errors": quality.get("hero_policy_errors", 0)
                if game_index == 0
                else 0,
                "opponent_policy_errors": quality.get("opponent_policy_errors", 0)
                if game_index == 0
                else 0,
                "hero_illegal_actions": quality.get("hero_illegal_actions", 0)
                if game_index == 0
                else 0,
                "opponent_illegal_actions": quality.get("opponent_illegal_actions", 0)
                if game_index == 0
                else 0,
                "hero_telemetry": telemetry,
                "hero_latency_ms": {
                    "count": 1,
                    "mean": 1.0,
                    "p50": 1.0,
                    "p95": 1.0,
                    "p99": 1.0,
                    "max": 1.0,
                },
                # This intentionally can disagree with the exact S2 event set.
                "d1_intervened": game_index in d1_intervened_games,
                "d1_intervention_count": int(game_index in d1_intervened_games),
            }
        )

    proof_totals = {
        key: sum(int(row["hero_telemetry"].get(key, 0)) for row in rows)
        for key in {key for row in rows for key in row["hero_telemetry"]}
    }
    counters = {
        key: quality.get(key, 0)
        for key in (
            "hero_policy_errors",
            "opponent_policy_errors",
            "hero_illegal_actions",
            "opponent_illegal_actions",
        )
    }
    overall = {
        "scheduled_games": requested_games,
        "games": completed_games,
        "wins": wins,
        "draws": 0,
        "losses": completed_games - wins,
        "failed_games": failed_games,
        "win_rate": wins / completed_games if completed_games else 0.0,
        "wilson_95": wilson(wins, completed_games),
        **counters,
    }
    result = {
        "schema": "dipplin-authentic-evaluation-v1",
        "hero_name": hero_name,
        "opponent_name": opponent_name,
        "scheduled_games": requested_games,
        "games": completed_games,
        "wins_a": wins,
        "win_rate_a": wins / completed_games if completed_games else 0.0,
        "wilson_95": wilson(wins, completed_games),
        "failed_games": failed_games,
        "forced_actual_order": actual_order,
        "forced_order_accounting_complete": True,
        **counters,
        "overall": overall,
        "rng_provenance": {
            "engine": "unpaired_std_random_device",
            "paired_deals": False,
            "common_random_numbers": False,
        },
        "latency_ms": {
            "hero": {
                "count": requested_games,
                "mean": 1.0,
                "p50": 1.0,
                "p95": 1.0,
                "p99": 1.0,
                "max": 1.0,
            }
        },
        "hero_telemetry": proof_totals,
        "artifact_provenance": {
            "submission_a_sha256": tree_sha256,
            "post_evaluation_submission_a_sha256": tree_sha256,
            "archive_a_sha256": archive_sha256,
            "deck_a_sha256": HERO_DECK,
            "submission_b_sha256": OPPONENT_TREE,
            "post_evaluation_submission_b_sha256": OPPONENT_TREE,
            "artifact_b_sha256": OPPONENT_TREE,
            "deck_b_sha256": OPPONENT_DECK,
            "engine_sha256": ENGINE,
            "evaluator_sha256": EVALUATOR,
            "external_adapter_sha256": ADAPTER,
            "evaluation_schema_sha256": EVALUATION_SCHEMA,
            "runtime_environment": {
                "process_ptcg": {},
                "submission_a_overrides": {},
                "submission_b_overrides": {},
            },
            "process_behavior_environment": {"PYTHONDONTWRITEBYTECODE": "1"},
            "max_decisions": 2000,
            "forced_actual_order": actual_order,
            "submission_artifacts_unchanged_during_evaluation": True,
            "runtime_blinding_contract": {
                "hero_receives_opponent_label": False,
                "hero_receives_opponent_package_identity": False,
                "agent_call_payload": "engine_observation_only",
                "labels_added_in_parent_after_game": True,
            },
            "rng_contract": {
                "engine": "independent_std_random_device",
                "paired_deals": False,
                "common_random_numbers": False,
            },
        },
        "game_rows": rows,
    }
    _write_json(path, result)


def _build_spec(
    tmp_path: Path,
    *,
    baseline_wins: list[int],
    candidate_wins: list[int],
    games_per_matchup: int,
    candidate_failures: dict[int, int] | None = None,
    candidate_quality: dict[int, dict[str, int]] | None = None,
    candidate_overrides: dict[int, dict[int, int]] | None = None,
    candidate_d1: dict[int, set[int]] | None = None,
    candidate_operational: dict[int, dict[str, int]] | None = None,
    material_drop: float = -0.05,
    catastrophic_drop: float = -0.20,
    include_stage2: bool = False,
) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    assert len(baseline_wins) == len(candidate_wins)
    candidate_failures = candidate_failures or {}
    candidate_quality = candidate_quality or {}
    candidate_overrides = candidate_overrides or {}
    candidate_d1 = candidate_d1 or {}
    candidate_operational = candidate_operational or {}
    matchup_names = [f"matchup-{index}" for index in range(len(baseline_wins))]
    baseline_cells: list[dict[str, Any]] = []
    candidate_cells: list[dict[str, Any]] = []
    for index, matchup in enumerate(matchup_names):
        baseline_path = tmp_path / f"baseline-{index}.json"
        candidate_path = tmp_path / f"candidate-{index}.json"
        _write_result(
            baseline_path,
            opponent_name=matchup,
            requested_games=games_per_matchup,
            wins=baseline_wins[index],
            tree_sha256=BASELINE_TREE,
            archive_sha256=BASELINE_ARCHIVE,
            hero_name="S1",
            s2_enabled=False,
        )
        _write_result(
            candidate_path,
            opponent_name=matchup,
            requested_games=games_per_matchup,
            wins=candidate_wins[index],
            tree_sha256=CANDIDATE_TREE,
            archive_sha256=CANDIDATE_ARCHIVE,
            hero_name="S2",
            s2_enabled=True,
            failed_games=candidate_failures.get(index, 0),
            quality=candidate_quality.get(index),
            overrides=candidate_overrides.get(index),
            d1_intervened_games=candidate_d1.get(index),
            operational_telemetry=candidate_operational.get(index),
        )
        common = {
            "matchup": matchup,
            "opponent_name": matchup,
            "actual_order": "second",
            "requested_games": games_per_matchup,
        }
        baseline_cells.append(
            {
                "id": f"baseline-{index}",
                **common,
                "path": baseline_path.name,
                "artifact_sha256": _sha256(baseline_path),
                "expected_wins": baseline_wins[index],
            }
        )
        candidate_cells.append(
            {
                "id": f"candidate-{index}",
                **common,
                "path": candidate_path.name,
                "artifact_sha256": _sha256(candidate_path),
            }
        )

    stages: dict[str, Any] = {"stage1": {"candidate_cells": candidate_cells}}
    if include_stage2:
        stages["stage2"] = {
            "baseline_cells": baseline_cells,
            "candidate_cells": candidate_cells,
        }
    else:
        stages["stage2"] = None
    baseline_manifest = tmp_path / "baseline-manifest.json"
    candidate_manifest = tmp_path / "candidate-manifest.json"
    _write_json(
        baseline_manifest,
        {
            "variant": "s1",
            "output": {
                "extracted_tree_sha256": BASELINE_TREE,
                "archive_sha256": BASELINE_ARCHIVE,
            },
            "runtime": {
                "evaluated_configuration": {
                    "search": True,
                    "s2": False,
                }
            },
        },
    )
    _write_json(
        candidate_manifest,
        {
            "variant": "s2",
            "output": {
                "extracted_tree_sha256": CANDIDATE_TREE,
                "archive_sha256": CANDIDATE_ARCHIVE,
            },
            "runtime": {
                "evaluated_configuration": {
                    "search": True,
                    "s2": True,
                }
            },
        },
    )
    hypothesis = tmp_path / "hypothesis.json"
    _write_json(hypothesis, {"schema": "synthetic-hypothesis-v1"})
    spec = {
        "schema": "dipplin-s2-stage-evaluation-spec-v1",
        "evidence_files": [
            {
                "id": "hypothesis",
                "path": hypothesis.name,
                "sha256": _sha256(hypothesis),
            }
        ],
        "evaluation_contract": {
            "deck_a_sha256": HERO_DECK,
            "engine_sha256": ENGINE,
            "evaluator_sha256": EVALUATOR,
            "external_adapter_sha256": ADAPTER,
            "evaluation_schema_sha256": EVALUATION_SCHEMA,
            "nonfatal_search_fallback_keys": [
                "d1_errors",
                "d1_timeouts",
                "d1_abstention_reason_engine_error",
                "d1_abstention_reason_timeout",
            ],
            "nonfatal_search_fallback_prefixes": ["d1_error_detail_"],
        },
        "opponents": {
            matchup: {
                "opponent_name": matchup,
                "tree_sha256": OPPONENT_TREE,
                "deck_sha256": OPPONENT_DECK,
            }
            for matchup in matchup_names
        },
        "baseline": {
            "name": "synthetic S1",
            "variant": "s1",
            "result_hero_name": "S1",
            "expected_s2_enabled": False,
            "tree_sha256": BASELINE_TREE,
            "archive_sha256": BASELINE_ARCHIVE,
            "package_manifest": {
                "path": baseline_manifest.name,
                "sha256": _sha256(baseline_manifest),
            },
            "expected_runtime_configuration": {"search": True, "s2": False},
            "expected_manifest_values": {
                "runtime.evaluated_configuration.search": True,
                "runtime.evaluated_configuration.s2": False,
            },
            "cells": baseline_cells,
        },
        "candidate": {
            "name": "synthetic S2",
            "variant": "s2",
            "result_hero_name": "S2",
            "expected_s2_enabled": True,
            "tree_sha256": CANDIDATE_TREE,
            "archive_sha256": CANDIDATE_ARCHIVE,
            "package_manifest": {
                "path": candidate_manifest.name,
                "sha256": _sha256(candidate_manifest),
            },
            "expected_runtime_configuration": {"search": True, "s2": True},
            "expected_manifest_values": {
                "runtime.evaluated_configuration.search": True,
                "runtime.evaluated_configuration.s2": True,
            },
        },
        "later_stage_decision_contracts": {
            "frozen_before_result_admission": True,
            **LATER_STAGE_DECISION_CONTRACT,
        },
        "stage1_decision": {
            "expected_actual_order": "second",
            "expected_matchups": matchup_names,
            "requested_games_per_matchup": games_per_matchup,
            "expected_baseline_games": games_per_matchup * len(matchup_names),
            "expected_baseline_wins": sum(baseline_wins),
            "minimum_promising_pooled_delta": 0.03,
            "strong_signal_pooled_delta": 0.05,
            "material_pooled_drop_delta": material_drop,
            "catastrophic_matchup_drop_delta": catastrophic_drop,
        },
        "stages": stages,
    }
    spec_path = tmp_path / "spec.json"
    _write_json(spec_path, spec)
    return spec_path


def _rewrite_spec(spec_path: Path, mutate: Callable[[dict[str, Any]], None]) -> None:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    mutate(spec)
    _write_json(spec_path, spec)


def test_wilson_and_independent_newcombe_match_audited_formula() -> None:
    assert wilson(51, 100) == pytest.approx(
        [0.4134801193402717, 0.6057800106955886]
    )
    result = independent_difference(
        {"wins": 183, "games": 400}, {"wins": 171, "games": 400}
    )
    assert result["estimate"] == pytest.approx(0.03)
    assert result["confidence_95"] == pytest.approx(
        [-0.03868416315337188, 0.09828598007277554]
    )
    assert result["method"] == "independent_newcombe_wilson_difference"
    assert result["paired"] is False


def test_later_stage_contracts_are_frozen_before_results(tmp_path: Path) -> None:
    spec_path = _build_spec(
        tmp_path,
        baseline_wins=[4],
        candidate_wins=[8],
        games_per_matchup=10,
    )
    report = evaluate_spec(spec_path)
    assert report["later_stage_decision_contracts"]["stage2"][
        "requested_games_per_arm_per_matchup"
    ] == 300
    assert report["later_stage_decision_contracts"]["stage3"][
        "minimum_candidate_minus_s1_pooled_delta"
    ] == -0.04
    assert report["later_stage_decision_contracts"]["stage4"][
        "minimum_pooled_s2_win_rate"
    ] == 0.47
    assert report["later_stage_decision_contracts"]["stage5"][
        "exploratory_improvements_can_help"
    ] is False

    _rewrite_spec(
        spec_path,
        lambda spec: spec["later_stage_decision_contracts"]["stage2"].__setitem__(
            "minimum_candidate_pooled_win_rate", 0.49
        ),
    )
    with pytest.raises(StageEvaluationError, match="later-stage decision contract"):
        evaluate_spec(spec_path)


def test_strong_stage1_uses_only_exact_s2_override_rows_and_accepts_later_stage(
    tmp_path: Path,
) -> None:
    spec_path = _build_spec(
        tmp_path,
        baseline_wins=[4, 4, 4, 4],
        candidate_wins=[5, 5, 5, 5],
        games_per_matchup=10,
        candidate_overrides={0: {1: 2}},
        candidate_d1={0: {0, 1}},
        include_stage2=True,
    )
    report = evaluate_spec(spec_path)
    stage1 = report["stages"]["stage1"]
    assert stage1["decision"]["verdict"] == "STRONG"
    assert stage1["pooled"]["baseline"]["wins"] == 16
    assert stage1["pooled"]["candidate"]["wins"] == 20
    assert stage1["macro"]["baseline_win_rate"] == pytest.approx(0.4)
    assert stage1["macro"]["candidate_win_rate"] == pytest.approx(0.5)
    proof = stage1["candidate_s2_proof"]
    assert proof["overrides"] == 2
    assert proof["games_with_override_count"] == 1
    assert proof["games_with_override"] == [
        {
            "cell_id": "candidate-0",
            "game_index": 1,
            "completed": True,
            "outcome": "win",
            "override_count": 2,
        }
    ]
    assert proof["d1_intervention_fields_used"] is False
    assert stage1["candidate_latency_ms"]["count"] == 40
    assert report["stages"]["stage2"]["status"] == "EVALUATED"
    assert (
        report["stages"]["stage2"]["decision"]["verdict"]
        == "NOT_IMPLEMENTED_FOR_LATER_STAGE"
    )


def test_exact_three_point_lift_is_promising_not_paired(tmp_path: Path) -> None:
    spec_path = _build_spec(
        tmp_path,
        baseline_wins=[51, 48, 33, 39],
        candidate_wins=[54, 51, 37, 41],
        games_per_matchup=100,
    )
    stage = evaluate_spec(spec_path)["stages"]["stage1"]
    assert stage["pooled"]["baseline"]["wins"] == 171
    assert stage["pooled"]["candidate"]["wins"] == 183
    assert stage["decision"]["verdict"] == "PROMISING"
    assert stage["decision"]["observed"]["pooled_delta"] == pytest.approx(0.03)
    assert stage["statistical_contract"]["same_schedule_is_paired"] is False


def test_below_three_point_lift_is_killed(tmp_path: Path) -> None:
    spec_path = _build_spec(
        tmp_path,
        baseline_wins=[51, 48, 33, 39],
        candidate_wins=[54, 51, 36, 41],
        games_per_matchup=100,
    )
    decision = evaluate_spec(spec_path)["stages"]["stage1"]["decision"]
    assert decision["verdict"] == "KILL"
    assert "POOLED_LIFT_BELOW_3PP_SCREEN" in decision["reasons"]


@pytest.mark.parametrize(
    ("failures", "quality", "reason"),
    [
        ({0: 1}, {}, "ERRORS_OR_FAILURES_GT_ZERO"),
        ({}, {0: {"hero_policy_errors": 1}}, "ERRORS_OR_FAILURES_GT_ZERO"),
        ({}, {0: {"opponent_illegal_actions": 1}}, "ILLEGAL_ACTIONS_GT_ZERO"),
    ],
)
def test_runtime_quality_defects_force_kill(
    tmp_path: Path,
    failures: dict[int, int],
    quality: dict[int, dict[str, int]],
    reason: str,
) -> None:
    spec_path = _build_spec(
        tmp_path,
        baseline_wins=[4],
        candidate_wins=[8],
        games_per_matchup=10,
        candidate_failures=failures,
        candidate_quality=quality,
    )
    decision = evaluate_spec(spec_path)["stages"]["stage1"]["decision"]
    assert decision["verdict"] == "KILL"
    assert reason in decision["reasons"]


def test_known_search_abstentions_are_accounted_but_unknown_errors_kill(
    tmp_path: Path,
) -> None:
    known_spec = _build_spec(
        tmp_path / "known",
        baseline_wins=[4],
        candidate_wins=[8],
        games_per_matchup=10,
        candidate_operational={0: {"d1_errors": 1, "d1_timeouts": 2}},
    )
    stage = evaluate_spec(known_spec)["stages"]["stage1"]
    assert stage["decision"]["verdict"] == "STRONG"
    assert stage["pooled"]["candidate"]["operational_telemetry"][
        "nonfatal_search_fallback_counts"
    ] == {"d1_errors": 1, "d1_timeouts": 2}

    unknown_spec = _build_spec(
        tmp_path / "unknown",
        baseline_wins=[4],
        candidate_wins=[8],
        games_per_matchup=10,
        candidate_operational={0: {"s2_cleanup_errors": 1}},
    )
    decision = evaluate_spec(unknown_spec)["stages"]["stage1"]["decision"]
    assert decision["verdict"] == "KILL"
    assert "FATAL_OPERATIONAL_TELEMETRY_GT_ZERO" in decision["reasons"]


def test_s2_mode_and_cross_arm_opponent_identity_fail_closed(tmp_path: Path) -> None:
    spec_path = _build_spec(
        tmp_path,
        baseline_wins=[4],
        candidate_wins=[8],
        games_per_matchup=10,
    )
    candidate_path = tmp_path / "candidate-0.json"
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate["game_rows"][0]["hero_telemetry"]["s2_enabled"] = 0
    candidate["hero_telemetry"]["s2_enabled"] -= 1
    _write_json(candidate_path, candidate)
    _rewrite_spec(
        spec_path,
        lambda spec: spec["stages"]["stage1"]["candidate_cells"][0].__setitem__(
            "artifact_sha256", _sha256(candidate_path)
        ),
    )
    with pytest.raises(StageEvaluationError, match="s2_enabled mode mismatch"):
        evaluate_spec(spec_path)

    opponent_spec = _build_spec(
        tmp_path / "opponent",
        baseline_wins=[4],
        candidate_wins=[8],
        games_per_matchup=10,
    )
    _rewrite_spec(
        opponent_spec,
        lambda spec: spec["stages"]["stage1"]["candidate_cells"][0].__setitem__(
            "opponent_name", "different-opponent"
        ),
    )
    with pytest.raises(StageEvaluationError, match="opponent contract mismatch"):
        evaluate_spec(opponent_spec)


def test_catastrophic_matchup_collapse_kills_even_with_strong_pool(
    tmp_path: Path,
) -> None:
    spec_path = _build_spec(
        tmp_path,
        baseline_wins=[5, 5],
        candidate_wins=[1, 10],
        games_per_matchup=10,
        catastrophic_drop=-0.20,
    )
    decision = evaluate_spec(spec_path)["stages"]["stage1"]["decision"]
    assert decision["observed"]["pooled_delta"] == pytest.approx(0.05)
    assert decision["verdict"] == "KILL"
    assert "CATASTROPHIC_MATCHUP_COLLAPSE" in decision["reasons"]
    assert decision["observed"]["catastrophic_matchup_cells"] == [
        "matchup-0|second"
    ]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda spec: spec["stages"]["stage1"]["candidate_cells"][0].__setitem__(
                "artifact_sha256", "f" * 64
            ),
            "artifact hash mismatch",
        ),
        (
            lambda spec: spec["stages"]["stage1"]["candidate_cells"][0].__setitem__(
                "requested_games", 11
            ),
            "row count",
        ),
        (
            lambda spec: spec["stages"]["stage1"]["candidate_cells"][0].__setitem__(
                "actual_order", "first"
            ),
            "order accounting mismatch",
        ),
        (
            lambda spec: spec["candidate"].__setitem__("tree_sha256", "a" * 64),
            "tree mismatch",
        ),
        (
            lambda spec: spec["candidate"].__setitem__("archive_sha256", "b" * 64),
            "archive mismatch",
        ),
    ],
)
def test_hash_games_order_tree_and_archive_mismatches_fail_closed(
    tmp_path: Path,
    mutation: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    spec_path = _build_spec(
        tmp_path,
        baseline_wins=[4],
        candidate_wins=[8],
        games_per_matchup=10,
    )
    _rewrite_spec(spec_path, mutation)
    with pytest.raises(StageEvaluationError, match=message):
        evaluate_spec(spec_path)


def test_undefined_material_and_catastrophic_thresholds_fail_closed(
    tmp_path: Path,
) -> None:
    spec_path = _build_spec(
        tmp_path,
        baseline_wins=[4],
        candidate_wins=[8],
        games_per_matchup=10,
    )
    _rewrite_spec(
        spec_path,
        lambda spec: spec["stage1_decision"].pop("catastrophic_matchup_drop_delta"),
    )
    with pytest.raises(StageEvaluationError, match="catastrophic_matchup_drop_delta"):
        evaluate_spec(spec_path)


def test_null_vague_thresholds_are_safe_only_when_no_arm_declines(
    tmp_path: Path,
) -> None:
    improving_spec = _build_spec(
        tmp_path / "improving",
        baseline_wins=[4, 4],
        candidate_wins=[4, 5],
        games_per_matchup=10,
    )
    _rewrite_spec(
        improving_spec,
        lambda spec: spec["stage1_decision"].update(
            {
                "material_pooled_drop_delta": None,
                "catastrophic_matchup_drop_delta": None,
            }
        ),
    )
    assert evaluate_spec(improving_spec)["stages"]["stage1"]["decision"][
        "verdict"
    ] == "STRONG"

    declining_spec = _build_spec(
        tmp_path / "declining",
        baseline_wins=[4, 4],
        candidate_wins=[3, 6],
        games_per_matchup=10,
    )
    _rewrite_spec(
        declining_spec,
        lambda spec: spec["stage1_decision"].update(
            {
                "material_pooled_drop_delta": None,
                "catastrophic_matchup_drop_delta": None,
            }
        ),
    )
    with pytest.raises(StageEvaluationError, match="catastrophic"):
        evaluate_spec(declining_spec)


def test_cli_writes_kill_report_and_returns_nonzero(tmp_path: Path) -> None:
    spec_path = _build_spec(
        tmp_path,
        baseline_wins=[4],
        candidate_wins=[4],
        games_per_matchup=10,
    )
    output = tmp_path / "report.json"
    assert main(["--spec", str(spec_path), "--output", str(output)]) == 2
    assert json.loads(output.read_text(encoding="utf-8"))["stages"]["stage1"][
        "decision"
    ]["verdict"] == "KILL"

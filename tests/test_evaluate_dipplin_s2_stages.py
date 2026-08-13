from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

import pytest
import scripts.evaluate_dipplin_s2_stages as stage_module

from scripts.evaluate_dipplin_s2_stages import (
    LATER_STAGE_DECISION_CONTRACT,
    STAGE4_CONTROL_CONTRACT,
    STAGE4_CONTROL_EVALUATION_CONTRACT,
    STAGE5_BASELINE_CONTRACT,
    STAGE5_RUN_CONTRACT,
    StageEvaluationError,
    _stage2_decision,
    _stage3_decision,
    _stage4_decision,
    _stage5_evaluation,
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
        "stage4_control_evaluation_contract": STAGE4_CONTROL_EVALUATION_CONTRACT,
        "stage4_controls": STAGE4_CONTROL_CONTRACT,
        "stage5_baseline": STAGE5_BASELINE_CONTRACT,
        "stage5_run_contract": STAGE5_RUN_CONTRACT,
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


def _arm(games: int, wins: int) -> dict[str, Any]:
    return {
        "scheduled_games": games,
        "games": games,
        "wins": wins,
        "draws": 0,
        "losses": games - wins,
        "failed_games": 0,
        "hero_policy_errors": 0,
        "opponent_policy_errors": 0,
        "hero_illegal_actions": 0,
        "opponent_illegal_actions": 0,
        "win_rate": wins / games,
        "wilson_95": wilson(wins, games),
        "operational_telemetry": {
            "nonfatal_search_fallback_counts": {},
            "fatal_counts": {},
            "fatal_count": 0,
        },
    }


def _comparison(
    *, actual_order: str, games: int, baseline_wins: list[int], candidate_wins: list[int]
) -> dict[str, Any]:
    matchups = ["A2", "d842", "AZ2.4a", "AZ2.7"]
    per_matchup: dict[str, Any] = {}
    for matchup, baseline, candidate in zip(matchups, baseline_wins, candidate_wins):
        baseline_arm = _arm(games, baseline)
        candidate_arm = _arm(games, candidate)
        per_matchup[f"{matchup}|{actual_order}"] = {
            "matchup": matchup,
            "actual_order": actual_order,
            "baseline": baseline_arm,
            "candidate": candidate_arm,
            "candidate_minus_baseline": independent_difference(
                candidate_arm, baseline_arm
            ),
        }
    baseline_pool = _arm(games * 4, sum(baseline_wins))
    candidate_pool = _arm(games * 4, sum(candidate_wins))
    return {
        "per_matchup": per_matchup,
        "pooled": {
            "baseline": baseline_pool,
            "candidate": candidate_pool,
            "candidate_minus_baseline": independent_difference(
                candidate_pool, baseline_pool
            ),
        },
        "macro": {
            "baseline_win_rate": sum(value / games for value in baseline_wins) / 4,
            "candidate_win_rate": sum(value / games for value in candidate_wins) / 4,
            "candidate_minus_baseline": (
                sum(candidate_wins) - sum(baseline_wins)
            ) / (games * 4),
        },
    }


def _stage4_summary(first_wins: int, second_wins: int) -> dict[str, Any]:
    controls = {"first": _arm(500, 302), "second": _arm(500, 197)}
    candidates = {
        "first": _arm(300, first_wins),
        "second": _arm(300, second_wins),
    }
    control_pool = _arm(1000, 499)
    candidate_pool = _arm(600, first_wins + second_wins)
    return {
        "per_order": {
            order: {
                "control": controls[order],
                "candidate": candidates[order],
                "candidate_minus_control": independent_difference(
                    candidates[order], controls[order]
                ),
            }
            for order in ("first", "second")
        },
        "pooled": {
            "baseline": control_pool,
            "candidate": candidate_pool,
            "candidate_minus_baseline": independent_difference(
                candidate_pool, control_pool
            ),
        },
    }


def _replay_aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    labels = (
        "EQUIVALENT",
        "AGENT_DOMINATES",
        "EXPERT_DOMINATES",
        "INCOMPARABLE",
        "UNCERTIFIABLE",
    )
    counts = {label: sum(row["classification"] == label for row in rows) for label in labels}
    episodes: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        episodes.setdefault(str(row["episode_id"]), []).append(row)
    episode_rates = {
        label: (
            sum(
                sum(row["classification"] == label for row in episode_rows)
                / len(episode_rows)
                for episode_rows in episodes.values()
            )
            / len(episodes)
            if episodes
            else 0.0
        )
        for label in labels
    }
    return {
        "episode_count": len(episodes),
        "decision_count": len(rows),
        "classification_counts": counts,
        "decision_rates": {
            label: counts[label] / len(rows) if rows else 0.0 for label in labels
        },
        "episode_rates": episode_rates,
        "episode_bootstrap_95": {
            label: [episode_rates[label], episode_rates[label]] for label in labels
        },
        "expert_dominates_rate": episode_rates["EXPERT_DOMINATES"],
        "agent_dominates_rate": episode_rates["AGENT_DOMINATES"],
    }


def _stage5_fixture(
    tmp_path: Path,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    baseline_rows = [
        {
            "record_id": "r0",
            "episode_id": 1,
            "replay_sha256": "a" * 64,
            "seat": 0,
            "step": 10,
            "turn": 2,
            "own_turn_ordinal": 1,
            "actual_order": "second",
            "opponent_archetype": "other",
            "hero_deck_family": "THWACKEY_DIPPLIN",
            "decision_family": "attack_threshold",
            "game_phase": "EARLY",
            "expert_action": [1],
            "expert_semantic": "expert-0",
            "classification": "EXPERT_DOMINATES",
            "proposal_error": None,
            "uncertifiable_reason": None,
        },
        {
            "record_id": "r1",
            "episode_id": 2,
            "replay_sha256": "b" * 64,
            "seat": 1,
            "step": 20,
            "turn": 3,
            "own_turn_ordinal": 2,
            "actual_order": "first",
            "opponent_archetype": "other",
            "hero_deck_family": "THWACKEY_DIPPLIN",
            "decision_family": "setup",
            "game_phase": "EARLY",
            "expert_action": [2],
            "expert_semantic": "expert-1",
            "classification": "EQUIVALENT",
            "proposal_error": None,
            "uncertifiable_reason": None,
        },
        {
            "record_id": "r2",
            "episode_id": 3,
            "replay_sha256": "c" * 64,
            "seat": 0,
            "step": 30,
            "turn": 4,
            "own_turn_ordinal": 2,
            "actual_order": "second",
            "opponent_archetype": "other",
            "hero_deck_family": "THWACKEY_DIPPLIN",
            "decision_family": "recovery",
            "game_phase": "MID",
            "expert_action": [3],
            "expert_semantic": "expert-2",
            "classification": "UNCERTIFIABLE",
            "proposal_error": None,
            "uncertifiable_reason": "s1_action_unstable",
        },
    ]
    baseline_path = tmp_path / "s1.json"
    _write_json(
        baseline_path,
        {
            "schema": "dipplin-replay-regret-v1",
            "split": "VALIDATION",
            "sealed": False,
            "aggregate": _replay_aggregate(baseline_rows),
            "decision_rows": baseline_rows,
        },
    )
    primary_rows = json.loads(json.dumps(baseline_rows))
    primary_rows[0]["classification"] = "EQUIVALENT"
    primary_rows[2]["uncertifiable_reason"] = "candidate_action_unstable"
    for row in primary_rows:
        row.update(
            {
                "candidate_variant": "s2",
                "candidate_s2_enabled": True,
                "s2_override_telemetry_trustworthy": True,
                "s2_pre_attack_sequence_proof_overrides_delta": 0,
            }
        )
    exploratory_rows = [
        {
            "record_id": "x0",
            "episode_id": 4,
            "classification": "AGENT_DOMINATES",
            "decision_family": "setup",
            "candidate_variant": "s2",
            "candidate_s2_enabled": True,
            "s2_override_telemetry_trustworthy": True,
            "s2_pre_attack_sequence_proof_overrides_delta": 1,
            "semantic_equivalent": False,
            "proposal_error": None,
            "uncertifiable_reason": None,
        }
    ]
    candidate_path = tmp_path / "s2.json"
    primary_aggregate = _replay_aggregate(primary_rows)
    exploratory_aggregate = _replay_aggregate(exploratory_rows)
    baseline_hash = _sha256(baseline_path)
    ids = [row["record_id"] for row in baseline_rows]
    spec = {
        "stage5_baseline": {
            "path": baseline_path.name,
            "artifact_sha256": baseline_hash,
            "schema": "dipplin-replay-regret-v1",
            "split": "VALIDATION",
            "sealed": False,
            "decision_count": 3,
            "episode_count": 3,
            "record_id_sequence_sha256": stage_module._object_sha256(ids),
            "classification_counts": _replay_aggregate(baseline_rows)[
                "classification_counts"
            ],
            "expert_dominates_episode_rate": 1 / 3,
        },
        "stage5_run_contract": {
            "baseline_package": {
                "archive_sha256": "1" * 64,
                "manifest_sha256": "2" * 64,
                "extracted_tree_sha256": "3" * 64,
                "runtime_source_tree_sha256": "4" * 64,
            },
            "candidate_package": {
                "archive_sha256": "5" * 64,
                "manifest_sha256": "6" * 64,
                "extracted_tree_sha256": "7" * 64,
                "runtime_source_tree_sha256": "8" * 64,
            },
            "replay_run": {
                "validation_manifest_file_sha256": "9" * 64,
                "validation_manifest_payload_sha256": "a" * 64,
                "baseline_s1_validation_result_sha256": baseline_hash,
                "parameters": {"synthetic": 1},
                "evaluator": {
                    "path": "synthetic.py",
                    "sha256": "b" * 64,
                    "git_blob_sha1": "c" * 40,
                },
            },
            "exploratory_hard_ceiling": 4,
        },
    }
    candidate_payload = {
        "schema": "dipplin-replay-regret-v2",
        "split": "VALIDATION",
        "sealed": False,
        "candidate_variant": "s2",
        "headline_set": "paired_primary",
        "aggregate_alias": "evaluation_sets.paired_primary.aggregate",
        "aggregate": primary_aggregate,
        "combined_rate_permitted": False,
        "manifest_payload_sha256": "a" * 64,
        "baseline_incumbent_s1": {
            **spec["stage5_run_contract"]["baseline_package"],
            "validation_result_sha256": baseline_hash,
        },
        "evaluated_candidate": spec["stage5_run_contract"]["candidate_package"],
        "run_contract": {
            "candidate": "s2",
            "validation_manifest_file_sha256": "9" * 64,
            "validation_manifest_payload_sha256": "a" * 64,
            "baseline_s1_validation_result_sha256": baseline_hash,
            "parameters": {"synthetic": 1},
            "full_manifest_episode_count": 3,
            "evaluator": spec["stage5_run_contract"]["replay_run"]["evaluator"],
        },
        "universe_counts": {
            "manifest_episode_count": 3,
            "useful_prompt_count": 5,
            "paired_primary_record_count": 3,
            "out_of_primary_useful_prompt_count": 2,
            "s2_override_prompt_count": 1,
            "paired_primary_s2_override_prompt_count": 0,
            "out_of_primary_s2_override_prompt_count": 1,
            "out_of_primary_s2_override_expert_equivalent_count": 0,
            "out_of_primary_s2_override_disagreement_count": 1,
            "s2_exploratory_record_count": 1,
            "s2_exploratory_hard_ceiling": 4,
        },
        "evaluation_sets": {
            "paired_primary": {
                "role": "qualification_primary",
                "selection": {
                    "mode": "exact_frozen_s1_record_ids",
                    "source_result_sha256": baseline_hash,
                    "record_count": 3,
                    "record_id_sequence_sha256": stage_module._object_sha256(ids),
                    "order_preserved": True,
                },
                "aggregate": primary_aggregate,
                "decision_rows": primary_rows,
            },
            "s2_exploratory": {
                "role": "exploratory_safety_veto_only",
                "safety_veto_only": True,
                "eligible_for_efficacy_rate": False,
                "selection": {
                    "mode": "exhaustive_disjoint_out_of_primary_s2_override_disagreements",
                    "requires_trustworthy_s2_override_delta": True,
                    "requires_candidate_expert_disagreement": True,
                    "hard_ceiling": 4,
                    "disjoint_from": "paired_primary",
                },
                "aggregate": exploratory_aggregate,
                "decision_rows": exploratory_rows,
            },
        },
    }
    _write_json(candidate_path, candidate_payload)
    stage = {
        "candidate_result": {
            "path": candidate_path.name,
            "artifact_sha256": _sha256(candidate_path),
        }
    }
    return tmp_path / "spec.json", spec, stage


def _rewrite_stage5_candidate(
    spec_path: Path,
    stage: dict[str, Any],
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    path = spec_path.parent / stage["candidate_result"]["path"]
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    primary = payload["evaluation_sets"]["paired_primary"]
    exploratory = payload["evaluation_sets"]["s2_exploratory"]
    primary["aggregate"] = _replay_aggregate(primary["decision_rows"])
    exploratory["aggregate"] = _replay_aggregate(exploratory["decision_rows"])
    payload["aggregate"] = primary["aggregate"]
    _write_json(path, payload)
    stage["candidate_result"]["artifact_sha256"] = _sha256(path)


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


def test_stage2_pass_strong_and_collapse_boundaries() -> None:
    boundary = _stage2_decision(
        _comparison(
            actual_order="second",
            games=300,
            baseline_wins=[150] * 4,
            candidate_wins=[150] * 4,
        )
    )
    assert boundary["verdict"] == "PASS"
    assert all(boundary["gates"].values())
    assert boundary["targets"]["strong_55pct_target_met"] is False

    strong = _stage2_decision(
        _comparison(
            actual_order="second",
            games=300,
            baseline_wins=[150] * 4,
            candidate_wins=[165] * 4,
        )
    )
    assert strong["verdict"] == "STRONG"
    assert strong["targets"]["strong_55pct_target_met"] is True

    collapse = _stage2_decision(
        _comparison(
            actual_order="second",
            games=300,
            baseline_wins=[150] * 4,
            candidate_wins=[120, 180, 180, 180],
        )
    )
    assert collapse["verdict"] == "KILL"
    assert collapse["gates"]["no_catastrophic_matchup_drop"] is False


def test_stage3_regression_and_collapse_boundaries() -> None:
    boundary = _stage3_decision(
        _comparison(
            actual_order="first",
            games=100,
            baseline_wins=[50] * 4,
            candidate_wins=[46] * 4,
        )
    )
    assert boundary["verdict"] == "PASS"
    assert all(boundary["gates"].values())

    below = _stage3_decision(
        _comparison(
            actual_order="first",
            games=100,
            baseline_wins=[50] * 4,
            candidate_wins=[45, 46, 46, 46],
        )
    )
    assert below["verdict"] == "KILL"
    assert below["gates"]["pooled_delta_above_regression_floor"] is False

    collapse = _stage3_decision(
        _comparison(
            actual_order="first",
            games=100,
            baseline_wins=[50] * 4,
            candidate_wins=[40, 55, 55, 55],
        )
    )
    assert collapse["verdict"] == "KILL"
    assert collapse["gates"]["no_catastrophic_matchup_drop"] is False


def test_stage4_exact_control_boundaries_and_statistical_loss() -> None:
    boundary = _stage4_decision(_stage4_summary(174, 108))
    assert boundary["verdict"] == "PASS"
    assert all(boundary["gates"].values())
    assert boundary["observed"]["candidate_pooled_win_rate"] == pytest.approx(0.47)
    assert boundary["observed"]["candidate_minus_control_pooled_delta"] == pytest.approx(
        -0.029
    )

    pooled_kill = _stage4_decision(_stage4_summary(174, 107))
    assert pooled_kill["verdict"] == "KILL"
    assert pooled_kill["gates"]["candidate_pooled_rate_at_least_47pct"] is False

    order_kill = _stage4_decision(_stage4_summary(168, 120))
    assert order_kill["verdict"] == "KILL"
    assert order_kill["gates"]["each_order_delta_above_floor"] is False

    statistical_kill = _stage4_decision(_stage4_summary(130, 90))
    assert statistical_kill["verdict"] == "KILL"
    assert statistical_kill["gates"]["no_statistically_clear_loss"] is False


def test_stage5_paired_pass_and_canonical_unstable_family(tmp_path: Path) -> None:
    spec_path, spec, stage = _stage5_fixture(tmp_path)
    evaluation = _stage5_evaluation(stage, spec=spec, spec_path=spec_path)
    assert evaluation["decision"]["verdict"] == "PASS"
    assert all(evaluation["decision"]["gates"].values())
    assert evaluation["paired_transitions"]["ed_to_non_ed"] == 1
    assert evaluation["paired_transitions"]["non_ed_to_ed"] == 0
    assert evaluation["paired_transitions"]["matrix"]["EXPERT_DOMINATES"][
        "EQUIVALENT"
    ] == 1
    assert evaluation["failure_families"]["new"] == []


@pytest.mark.parametrize(
    ("failure", "failed_gate"),
    [
        ("ed_to_uncertifiable", "primary_incomparable_uncertifiable_burden_not_increased"),
        ("reverse_ed", "favorable_ed_exits_exceed_reverse_ed_entries"),
        ("exploratory_ed", "zero_certified_exploratory_expert_dominates"),
        ("exploratory_incomparable", "zero_certified_exploratory_incomparable"),
        ("new_family", "no_new_failure_family"),
    ],
)
def test_stage5_safety_kills(
    tmp_path: Path, failure: str, failed_gate: str
) -> None:
    spec_path, spec, stage = _stage5_fixture(tmp_path)

    def mutate(payload: dict[str, Any]) -> None:
        primary = payload["evaluation_sets"]["paired_primary"]["decision_rows"]
        exploratory = payload["evaluation_sets"]["s2_exploratory"]["decision_rows"]
        if failure == "ed_to_uncertifiable":
            primary[0]["classification"] = "UNCERTIFIABLE"
            primary[0]["uncertifiable_reason"] = "candidate_action_unstable"
        elif failure == "reverse_ed":
            primary[0]["classification"] = "AGENT_DOMINATES"
            primary[1]["classification"] = "EXPERT_DOMINATES"
        elif failure == "exploratory_ed":
            exploratory[0]["classification"] = "EXPERT_DOMINATES"
        elif failure == "exploratory_incomparable":
            exploratory[0]["classification"] = "INCOMPARABLE"
        else:
            primary[2]["uncertifiable_reason"] = "brand_new_failure"

    _rewrite_stage5_candidate(spec_path, stage, mutate)
    evaluation = _stage5_evaluation(stage, spec=spec, spec_path=spec_path)
    assert evaluation["decision"]["verdict"] == "KILL"
    assert evaluation["decision"]["gates"][failed_gate] is False


def test_stage5_exact_pair_identity_aggregate_and_universe_fail_closed(
    tmp_path: Path,
) -> None:
    for name in ("identity", "aggregate", "universe", "primary_override_count"):
        case = tmp_path / name
        spec_path, spec, stage = _stage5_fixture(case)
        candidate_path = case / "s2.json"
        payload = json.loads(candidate_path.read_text(encoding="utf-8"))
        if name == "identity":
            payload["evaluation_sets"]["paired_primary"]["decision_rows"][0][
                "expert_semantic"
            ] = "tampered"
        elif name == "aggregate":
            payload["evaluation_sets"]["paired_primary"]["aggregate"][
                "classification_counts"
            ]["EQUIVALENT"] += 1
            payload["aggregate"] = payload["evaluation_sets"]["paired_primary"][
                "aggregate"
            ]
        else:
            if name == "universe":
                payload["universe_counts"]["useful_prompt_count"] += 1
            else:
                payload["universe_counts"][
                    "paired_primary_s2_override_prompt_count"
                ] = 1
                payload["universe_counts"]["s2_override_prompt_count"] = 2
        _write_json(candidate_path, payload)
        stage["candidate_result"]["artifact_sha256"] = _sha256(candidate_path)
        with pytest.raises(StageEvaluationError):
            _stage5_evaluation(stage, spec=spec, spec_path=spec_path)


def test_sequential_gating_never_opens_a_later_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec_path = _build_spec(
        tmp_path,
        baseline_wins=[4, 4, 4, 4],
        candidate_wins=[5, 5, 5, 5],
        games_per_matchup=10,
    )
    _rewrite_spec(
        spec_path,
        lambda spec: spec["stages"].update(
            {
                "stage3": {"candidate_cells": "must-not-open"},
                "stage4": {"candidate_cells": "must-not-open"},
                "stage5": {"candidate_result": "must-not-open"},
            }
        ),
    )
    report = evaluate_spec(spec_path)
    assert report["stages"]["stage2"]["status"] == "PENDING"
    for name in ("stage3", "stage4", "stage5", "stage6"):
        assert report["stages"][name]["status"] == "INADMISSIBLE_PRECEDING_STAGE_PENDING"
        assert report["stages"][name]["blocked_by"] == "stage2"

    kill_spec = _build_spec(
        tmp_path / "kill",
        baseline_wins=[4],
        candidate_wins=[4],
        games_per_matchup=10,
    )
    _rewrite_spec(
        kill_spec,
        lambda spec: spec["stages"].update(
            {"stage2": {"candidate_cells": "must-not-open"}}
        ),
    )
    killed = evaluate_spec(kill_spec)
    assert killed["stages"]["stage1"]["decision"]["verdict"] == "KILL"
    assert killed["stages"]["stage2"]["status"] == "INADMISSIBLE_PRECEDING_STAGE_KILL"
    assert killed["stages"]["stage2"]["blocked_by"] == "stage1"


def test_stage2_kill_blocks_stage3_without_inspection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec_path = _build_spec(
        tmp_path,
        baseline_wins=[4, 4, 4, 4],
        candidate_wins=[5, 5, 5, 5],
        games_per_matchup=10,
    )
    _rewrite_spec(
        spec_path,
        lambda spec: spec["stages"].update(
                {
                    "stage2": {
                        "baseline_cells": "synthetic",
                        "candidate_cells": "synthetic",
                    },
                "stage3": {"candidate_cells": "must-not-open"},
            }
        ),
    )
    original = stage_module._stage_comparison

    def fake_comparison(name: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        if name == "stage2":
            return _comparison(
                actual_order="second",
                games=300,
                baseline_wins=[150] * 4,
                candidate_wins=[120, 180, 180, 180],
            )
        return original(name, *args, **kwargs)

    monkeypatch.setattr(stage_module, "_stage_comparison", fake_comparison)
    report = evaluate_spec(spec_path)
    assert report["stages"]["stage2"]["decision"]["verdict"] == "KILL"
    assert report["stages"]["stage3"]["status"] == "INADMISSIBLE_PRECEDING_STAGE_KILL"
    assert report["stages"]["stage3"]["blocked_by"] == "stage2"


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


def test_strong_stage1_uses_only_exact_s2_override_rows_and_blocks_pending_chain(
    tmp_path: Path,
) -> None:
    spec_path = _build_spec(
        tmp_path,
        baseline_wins=[4, 4, 4, 4],
        candidate_wins=[5, 5, 5, 5],
        games_per_matchup=10,
        candidate_overrides={0: {1: 2}},
        candidate_d1={0: {0, 1}},
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
    assert report["stages"]["stage2"]["status"] == "PENDING"
    assert report["stages"]["stage3"]["status"] == "INADMISSIBLE_PRECEDING_STAGE_PENDING"
    assert report["stages"]["stage3"]["blocked_by"] == "stage2"


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

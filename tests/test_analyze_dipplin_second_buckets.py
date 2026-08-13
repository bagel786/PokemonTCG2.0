from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.analyze_dipplin_second_buckets import (
    AnalysisError,
    TRACE_SCHEMA,
    analyze_documents,
    render_markdown,
)


def _board(
    *,
    bench=3,
    applin=2,
    engine=1,
    festival=True,
    thwackey=1,
    replacement="ready",
):
    return {
        "active_id": 93,
        "active_energy": 1,
        "active_ready": True,
        "bench_count": bench,
        "bench_ids": [42, 89, 93][:bench],
        "applin_lines": applin,
        "engine_lines": engine,
        "thwackey_count": thwackey,
        "festival_active": festival,
        "replacement_state": replacement,
        "energy_placement": {
            "total": 2,
            "active": 1,
            "applin_line": 2,
            "engine_line": 0,
            "other_support": 0,
        },
    }


def _trace(
    bucket,
    *,
    win,
    first_attack=2,
    first_double=3,
    productive=3,
    doubles=1,
    kos=1,
    prizes=2,
    dead=0,
    trapped=0,
    turn_one=None,
    first_board=None,
    prerequisites=None,
):
    return {
        "schema": TRACE_SCHEMA,
        "actual_order": "second",
        "opening_bucket": bucket,
        "opening_active_id": 88,
        "quick_sign_legal": bucket == "volbeat_active_quick_sign_legal",
        "completed": True,
        "collection_complete": True,
        "trace_errors": [],
        "win": win,
        "first_productive_attack_own_turn": first_attack,
        "first_festival_double_attack_own_turn": first_double,
        "productive_attacks": productive,
        "festival_double_attacks": doubles,
        "first_hit_kos": kos,
        "prizes_taken": prizes,
        "turn_one_board": turn_one if turn_one is not None else _board(),
        "first_attack_board": (
            first_board
            if first_board is not None
            else (_board(bench=4) if first_attack is not None else None)
        ),
        "dead_turns": dead,
        "trapped_active_turns": trapped,
        "missed_attack_prerequisites": prerequisites or {},
        "turn_records": [],
    }


def _row(index, trace, *, outcome=None):
    outcome = outcome or ("win" if trace["win"] else "loss")
    return {
        "game_index": index,
        "python_seed": 1000 + index,
        "hero_seat": index % 2,
        "actual_order": "second",
        "completed": True,
        "outcome": outcome,
        "win": int(outcome == "win"),
        "draw": int(outcome == "draw"),
        "hero_policy_errors": 0,
        "opponent_policy_errors": 0,
        "hero_illegal_actions": 0,
        "opponent_illegal_actions": 0,
        "second_bucket_trace": trace,
    }


def _evaluation(rows, hero_hash="hero-a"):
    return {
        "schema": "dipplin-authentic-evaluation-v1",
        "scheduled_games": len(rows),
        "forced_actual_order": "second",
        "artifact_provenance": {"submission_a_sha256": hero_hash},
        "game_rows": rows,
    }


def test_bucket_reports_wilson_timing_means_coverage_and_outcome_splits():
    winning = _trace(
        "applin_42_active",
        win=True,
        first_attack=2,
        first_double=3,
        productive=4,
        prizes=6,
        prerequisites={"festival": 1},
    )
    losing = _trace(
        "applin_42_active",
        win=False,
        first_attack=None,
        first_double=None,
        productive=2,
        dead=2,
        prerequisites={"dipplin": 2, "replacement": 1},
    )
    # A missing field is an explicit coverage gap, never an observed zero.
    losing.pop("prizes_taken")
    result = analyze_documents(
        [("eval.json", _evaluation([_row(0, winning), _row(1, losing)]))]
    )
    bucket = result["buckets"]["applin_42_active"]

    assert bucket["results"]["games"] == 2
    assert bucket["results"]["wins"] == 1
    assert bucket["results"]["win_rate"] == 0.5
    lower, upper = bucket["results"]["wilson_95"]
    assert lower < 0.5 < upper
    timing = bucket["mechanisms"]["timing"][
        "first_productive_attack_own_turn"
    ]
    assert timing["observed_games"] == 1
    assert timing["never_games"] == 1
    assert timing["unknown_games"] == 0
    assert timing["mean_observed"] == 2
    productive = bucket["mechanisms"]["mechanism_means"][
        "productive_attacks"
    ]
    assert productive["mean"] == 3
    prizes = bucket["mechanisms"]["mechanism_means"]["prizes_taken"]
    assert prizes["observed_games"] == 1
    assert prizes["missing_games"] == 1
    assert prizes["mean"] == 6
    assert bucket["coverage"]["outcomes"] == {
        "win": 1,
        "loss": 1,
        "draw": 0,
    }
    assert bucket["by_outcome"]["win"]["mechanisms"][
        "mechanism_means"
    ]["productive_attacks"]["mean"] == 4
    assert bucket["by_outcome"]["loss"]["mechanisms"][
        "missed_attack_prerequisites"
    ]["dipplin"]["mean"] == 2


def test_duplicate_rows_are_removed_before_bucket_analysis():
    trace = _trace("grookey_active", win=False)
    row = _row(0, trace)
    result = analyze_documents(
        [("duplicate.json", _evaluation([row, deepcopy(row)]))]
    )

    assert result["input_coverage"]["rows_seen"] == 2
    assert result["input_coverage"]["eligible_traced_games"] == 1
    assert result["input_coverage"]["excluded_rows"]["duplicate"] == 1
    assert result["buckets"]["grookey_active"]["results"]["games"] == 1


def test_mixed_traced_hero_hashes_fail_closed_by_default():
    first = _evaluation(
        [_row(0, _trace("applin_42_active", win=True))], "hash-a"
    )
    second = _evaluation(
        [_row(1, _trace("grookey_active", win=False))], "hash-b"
    )

    with pytest.raises(AnalysisError, match="mixed hero submission hashes"):
        analyze_documents([("a.json", first), ("b.json", second)])

    allowed = analyze_documents(
        [("a.json", first), ("b.json", second)],
        allow_mixed_hero_hashes=True,
    )
    assert allowed["hero_hashes"] == ["hash-a", "hash-b"]


def test_aggregate_only_context_never_enters_traced_bucket_totals_or_hash_check():
    traced = _evaluation(
        [_row(0, _trace("volbeat_active_quick_sign_legal", win=True))],
        "sterile-s1",
    )
    historical = {
        "actual_order": "second",
        "games": 100,
        "wins": 44,
        "draws": 0,
        "hero_sha256": "historical-nonsterile-s1",
        "hero_telemetry": {
            "setup_active_88": 33,
            "productive_attacks_taken": 500,
        },
    }
    result = analyze_documents(
        [("traced.json", traced), ("historical.json", historical)]
    )

    assert result["overall"]["results"]["games"] == 1
    assert result["hero_hashes"] == ["sterile-s1"]
    context = result["aggregate_context"]
    assert len(context["sources"]) == 1
    assert context["sources"][0]["bucket_analysis_available"] is False
    assert context["groups"][0]["games"] == 100
    assert context["groups"][0]["wins"] == 44
    assert context["groups"][0]["hero_telemetry"]["setup_active_88"] == 33


def test_opportunity_rank_is_transparent_and_outcome_independent():
    rows = [
        _row(
            0,
            _trace(
                "volbeat_active_quick_sign_legal",
                win=True,
                first_attack=2,
                first_double=3,
                dead=0,
                trapped=0,
            ),
        ),
        _row(
            1,
            _trace(
                "volbeat_active_quick_sign_legal",
                win=False,
                first_attack=2,
                first_double=3,
                dead=0,
                trapped=0,
            ),
        ),
        _row(
            2,
            _trace(
                "grookey_active",
                win=False,
                first_attack=None,
                first_double=None,
                dead=2,
                trapped=1,
            ),
        ),
        _row(
            3,
            _trace(
                "grookey_active",
                win=False,
                first_attack=4,
                first_double=None,
                dead=1,
                trapped=1,
            ),
        ),
    ]
    first = analyze_documents([("eval.json", _evaluation(rows))])

    flipped_rows = deepcopy(rows)
    for row in flipped_rows:
        row["win"] = 1 - row["win"]
        row["outcome"] = "win" if row["win"] else "loss"
        row["second_bucket_trace"]["win"] = bool(row["win"])
    second = analyze_documents(
        [("eval.json", _evaluation(flipped_rows))]
    )

    assert first["opportunity_ranking"] == second["opportunity_ranking"]
    ranking = first["opportunity_ranking"]
    assert ranking["method"]["uses_outcomes_or_win_rate"] is False
    assert ranking["buckets"][0]["bucket"] == "grookey_active"
    assert ranking["buckets"][0]["opportunity"] > 0
    assert ranking["buckets"][1]["bucket"] == (
        "volbeat_active_quick_sign_legal"
    )
    assert ranking["buckets"][1]["opportunity"] == 0


def test_invalid_or_untraced_rows_are_counted_as_coverage_not_imputed():
    valid = _row(0, _trace("shaymin_active", win=False))
    missing_trace = deepcopy(valid)
    missing_trace["game_index"] = 1
    missing_trace.pop("second_bucket_trace")
    first_order = deepcopy(valid)
    first_order["game_index"] = 2
    first_order["actual_order"] = "first"
    failed = deepcopy(valid)
    failed["game_index"] = 3
    failed["completed"] = False
    partial_trace = deepcopy(valid)
    partial_trace["game_index"] = 4
    partial_trace["second_bucket_trace"]["collection_complete"] = False
    partial_trace["second_bucket_trace"]["trace_errors"] = ["observe:synthetic"]

    result = analyze_documents(
        [
            (
                "coverage.json",
                _evaluation(
                    [valid, missing_trace, first_order, failed, partial_trace]
                ),
            )
        ]
    )
    exclusions = result["input_coverage"]["excluded_rows"]
    assert exclusions["missing_trace"] == 1
    assert exclusions["not_actual_second"] == 1
    assert exclusions["not_completed"] == 1
    assert exclusions["trace_incomplete"] == 1
    assert result["overall"]["results"]["games"] == 1


def test_markdown_preserves_missing_coverage_and_method_caveat():
    result = analyze_documents(
        [("eval.json", _evaluation([_row(0, _trace("shaymin_active", win=False, first_attack=None))]))]
    )
    report = render_markdown(result)
    assert "shaymin_active | 1" in report
    assert "Never attacked" in report
    assert "not a causal strength estimate" in report

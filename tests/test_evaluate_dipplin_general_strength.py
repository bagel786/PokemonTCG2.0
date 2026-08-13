from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.evaluate_dipplin_general_strength import (
    DashboardError,
    build_dashboard,
    render_markdown,
)


def _write(path: Path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evaluation(order: str, wins: int, *, games: int = 10, tree="tree-a"):
    return {
        "games": games,
        "wins": wins,
        "draws": 0,
        "actual_order": order,
        "hero_policy_errors": 0,
        "opponent_policy_errors": 0,
        "hero_sha256": tree,
        "physical_seats": {"0": {"games": games // 2}, "1": {"games": games // 2}},
    }


def test_dashboard_keeps_orders_opponents_and_evidence_tiers_separate(tmp_path):
    package = tmp_path / "s1.tar.gz"
    package.write_bytes(b"frozen-s1")
    anchors = []
    for opponent, first_wins, second_wins in (("A2", 6, 4), ("AZ", 8, 2)):
        for order, wins in (("first", first_wins), ("second", second_wins)):
            path = tmp_path / f"{opponent}-{order}.json"
            _write(path, _evaluation(order, wins))
            anchors.append({"opponent": opponent, "actual_order": order, "path": path.name})
    mirror_first = tmp_path / "mirror-first.json"
    mirror_second = tmp_path / "mirror-second.json"
    _write(mirror_first, _evaluation("first", 6))
    _write(mirror_second, _evaluation("second", 4))
    replay = tmp_path / "validation.json"
    _write(
        replay,
        {
            "episodes": 5,
            "summary": {
                "episodes": 5,
                "overall": {
                    "classifications": {
                        "EQUIVALENT": 2,
                        "AGENT_DOMINATES": 1,
                        "EXPERT_DOMINATES": 1,
                        "INCOMPARABLE": 1,
                        "UNCERTIFIABLE": 0,
                    }
                },
            },
        },
    )
    spec = tmp_path / "spec.json"
    _write(
        spec,
        {
            "candidate": {
                "name": "S1",
                "source_sha": "abc",
                "package": package.name,
            },
            "strong_anchors": anchors,
            "same_deck": {
                "s1_vs_s1_first": mirror_first.name,
                "s1_vs_s1_second": mirror_second.name,
            },
            "replay_validation": replay.name,
            "mechanics": {"passed": 10, "failed": 0},
            "weak_clones": [{"name": "Lucario", "errors": 0, "coverage": 3}],
        },
    )

    dashboard = build_dashboard(spec)
    assert dashboard["strong_anchors"]["anchor_actual_first"] == 0.7
    assert dashboard["strong_anchors"]["anchor_actual_second"] == pytest.approx(0.3)
    assert dashboard["strong_anchors"]["robust_anchor"] == pytest.approx(0.3)
    assert dashboard["strong_anchors"]["anchor_macro"] == 0.5
    assert dashboard["same_deck"]["s1_vs_s1_first"]["win_rate"] == 0.6
    assert dashboard["replay_validation"]["episodes"] == 5
    assert dashboard["replay_validation"]["rates"]["EXPERT_DOMINATES"] == 0.2
    assert dashboard["sealed_replay_holdout"]["status"] == "NOT_RUN"
    assert dashboard["weak_clones"][0]["win_rate_is_strength_metric"] is False
    assert dashboard["score_contract"]["single_magic_score"] is False
    report = render_markdown(dashboard)
    assert "robust min: 30.00%" in report
    assert "ceilinged" in report


def test_dashboard_rejects_declared_order_conflict(tmp_path):
    package = tmp_path / "s1.tar.gz"
    package.write_bytes(b"x")
    result = tmp_path / "result.json"
    _write(result, _evaluation("second", 5))
    spec = tmp_path / "spec.json"
    _write(
        spec,
        {
            "candidate": {"name": "S1", "package": package.name},
            "strong_anchors": [
                {"opponent": "A2", "actual_order": "first", "path": result.name}
            ],
        },
    )
    with pytest.raises(DashboardError, match="declared order conflicts"):
        build_dashboard(spec)


def test_anchor_macro_is_order_balanced_when_shard_replication_differs(tmp_path):
    package = tmp_path / "s1.tar.gz"
    package.write_bytes(b"x")
    first = tmp_path / "first.json"
    second_a = tmp_path / "second-a.json"
    second_b = tmp_path / "second-b.json"
    _write(first, _evaluation("first", 8, games=10))
    _write(second_a, _evaluation("second", 2, games=10))
    _write(second_b, _evaluation("second", 4, games=20))
    spec = tmp_path / "spec.json"
    _write(
        spec,
        {
            "candidate": {"name": "S1", "package": package.name},
            "strong_anchors": [
                {"opponent": "A2", "actual_order": "first", "path": first.name},
                {"opponent": "A2", "actual_order": "second", "path": second_a.name},
                {"opponent": "A2", "actual_order": "second", "path": second_b.name},
            ],
        },
    )
    anchors = build_dashboard(spec)["strong_anchors"]
    # First=.8, combined second=.2, so the order-balanced macro is .5 even
    # though the pooled 40-game sample is .35.
    assert anchors["anchor_actual_first"] == 0.8
    assert anchors["anchor_actual_second"] == 0.2
    assert anchors["anchor_macro"] == 0.5
    assert anchors["anchor_sample_weighted"] == 0.35
    assert anchors["opponents"]["A2"]["overall"]["order_balanced_win_rate"] == 0.5


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("artifact_sha256", "0" * 64, "artifact_sha256 mismatch"),
        ("expected_games", 11, "expected_games mismatch"),
        ("expected_wins", 6, "expected_wins mismatch"),
        (
            "expected_evaluated_tree_sha256",
            "b" * 64,
            "evaluated-tree mismatch",
        ),
    ],
)
def test_dashboard_rejects_declared_anchor_evidence_mismatch(
    tmp_path, field, value, message
):
    package = tmp_path / "s1.tar.gz"
    package.write_bytes(b"x")
    result = tmp_path / "result.json"
    _write(result, _evaluation("first", 5, tree="a" * 64))
    record = {
        "opponent": "A2",
        "actual_order": "first",
        "path": result.name,
        "artifact_sha256": _sha256(result),
        "expected_games": 10,
        "expected_wins": 5,
        "expected_evaluated_tree_sha256": "a" * 64,
    }
    record[field] = value
    spec = tmp_path / "spec.json"
    _write(
        spec,
        {
            "candidate": {"name": "S1", "package": package.name},
            "strong_anchors": [record],
        },
    )
    with pytest.raises(DashboardError, match=message):
        build_dashboard(spec)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        ("package", "candidate.package_sha256 mismatch"),
        ("tree", "candidate.tree_sha256 mismatch"),
        ("manifest", "candidate.manifest_sha256 mismatch"),
    ],
)
def test_candidate_package_manifest_and_tree_are_enforced(tmp_path, mutate, message):
    package = tmp_path / "s1.tar.gz"
    package.write_bytes(b"frozen")
    tree = "a" * 64
    manifest = tmp_path / "manifest.json"
    _write(
        manifest,
        {
            "output": {
                "archive_sha256": _sha256(package),
                "extracted_tree_sha256": tree,
            }
        },
    )
    result = tmp_path / "result.json"
    _write(result, _evaluation("first", 5, tree=tree))
    candidate = {
        "name": "S1",
        "package": package.name,
        "package_sha256": _sha256(package),
        "manifest": manifest.name,
        "manifest_sha256": _sha256(manifest),
        "tree_sha256": tree,
    }
    if mutate == "package":
        candidate["package_sha256"] = "0" * 64
    elif mutate == "tree":
        candidate["tree_sha256"] = "b" * 64
    else:
        candidate["manifest_sha256"] = "0" * 64
    spec = tmp_path / "spec.json"
    _write(
        spec,
        {
            "candidate": candidate,
            "strong_anchors": [
                {"opponent": "A2", "actual_order": "first", "path": result.name}
            ],
        },
    )
    with pytest.raises(DashboardError, match=message):
        build_dashboard(spec)


def test_bucket_analysis_keeps_aggregate_only_context_out_of_per_game_results(tmp_path):
    package = tmp_path / "s1.tar.gz"
    package.write_bytes(b"x")
    anchor = tmp_path / "anchor.json"
    tree = "a" * 64
    _write(anchor, _evaluation("first", 5, tree=tree))
    bucket = tmp_path / "bucket.json"
    _write(
        bucket,
        {
            "schema": "dipplin-second-bucket-analysis-v1",
            "trace_schema": "dipplin-second-bucket-trace-v1",
            "hero_hashes": [tree],
            "mixed_hero_hashes_allowed": False,
            "input_coverage": {
                "eligible_traced_games": 2,
                "rows_seen": 2,
                "row_sources": [{"source": "trace.json", "rows": 2, "hero_hash": tree}],
                "aggregate_only_sources": 1,
                "excluded_rows": {"missing_trace": 0},
                "quality_counters": {"hero_policy_errors": 0},
            },
            "overall": {
                "results": {"games": 2, "wins": 1, "losses": 1, "draws": 0, "win_rate": 0.5},
                "coverage": {"eligible_games": 2},
            },
            "buckets": {
                "grookey_active": {
                    "results": {"games": 2, "wins": 1, "losses": 1, "draws": 0, "win_rate": 0.5}
                }
            },
            "opportunity_ranking": {
                "method": {"uses_outcomes_or_win_rate": False},
                "reference_mechanism_rates": {},
                "buckets": [
                    {
                        "rank": 1,
                        "bucket": "grookey_active",
                        "games": 2,
                        "bucket_frequency": 1.0,
                        "opportunity": 0.25,
                    }
                ],
            },
            "aggregate_context": {
                "note": "context only",
                "sources": [{"games": 1200, "wins": 999}],
            },
        },
    )
    spec = tmp_path / "spec.json"
    _write(
        spec,
        {
            "candidate": {"name": "S1", "package": package.name},
            "strong_anchors": [
                {"opponent": "A2", "actual_order": "first", "path": anchor.name}
            ],
            "second_bucket_analysis": {
                "path": bucket.name,
                "artifact_sha256": _sha256(bucket),
                "expected_eligible_games": 2,
                "expected_evaluated_tree_sha256": tree,
            },
        },
    )
    dashboard = build_dashboard(spec)
    result = dashboard["second_bucket_analysis"]
    assert result["eligible_traced_games"] == 2
    assert result["results"]["games"] == 2
    assert result["aggregate_only_sources"] == 1
    assert result["aggregate_context"]["merged_as_per_game"] is False
    assert result["opportunity_ranking"]["buckets"][0]["bucket"] == "grookey_active"


def test_replay_regret_aggregate_uses_episode_rates_not_decision_counts(tmp_path):
    package = tmp_path / "s1.tar.gz"
    package.write_bytes(b"x")
    anchor = tmp_path / "anchor.json"
    _write(anchor, _evaluation("first", 5))
    replay = tmp_path / "replay.json"
    _write(
        replay,
        {
            "split": "VALIDATION",
            "sealed": False,
            "aggregate": {
                "episode_count": 2,
                "decision_count": 101,
                "classification_counts": {
                    "EXPERT_DOMINATES": 100,
                    "AGENT_DOMINATES": 1,
                },
                "episode_rates": {
                    "EXPERT_DOMINATES": 0.5,
                    "AGENT_DOMINATES": 0.5,
                },
                "episode_bootstrap_95": {
                    "EXPERT_DOMINATES": [0.0, 1.0],
                    "AGENT_DOMINATES": [0.0, 1.0],
                },
            },
        },
    )
    spec = tmp_path / "spec.json"
    _write(
        spec,
        {
            "candidate": {"name": "S1", "package": package.name},
            "strong_anchors": [
                {"opponent": "A2", "actual_order": "first", "path": anchor.name}
            ],
            "replay_validation": replay.name,
        },
    )
    result = build_dashboard(spec)["replay_validation"]
    assert result["episodes"] == 2
    assert result["decisions"] == 101
    assert result["rates"]["EXPERT_DOMINATES"] == 0.5
    assert result["rate_basis"] == "episode_mean"
    assert result["bootstrap_95"]["EXPERT_DOMINATES"] == [0.0, 1.0]


def test_custom_provenance_and_linux_certification_are_surfaced(tmp_path):
    package = tmp_path / "s1.tar.gz"
    package.write_bytes(b"x")
    anchor = tmp_path / "anchor.json"
    _write(anchor, _evaluation("first", 5))
    certification = tmp_path / "linux.json"
    tree = "a" * 64
    archive = "b" * 64
    _write(
        certification,
        {
            "schema": "cert-v1",
            "games": 2,
            "wins": 1,
            "draws": 0,
            "failed_games": 0,
            "hero_policy_errors": 0,
            "opponent_policy_errors": 0,
            "hero_illegal_actions": 0,
            "opponent_illegal_actions": 0,
            "artifact_provenance": {
                "archive_a_sha256": archive,
                "submission_a_sha256": tree,
                "submission_artifacts_unchanged_during_evaluation": True,
                "platform": "Linux",
                "machine": "x86_64",
            },
            "cells": {
                "actual_order": {"first": {"games": 1}, "second": {"games": 1}}
            },
        },
    )
    spec = tmp_path / "spec.json"
    _write(
        spec,
        {
            "candidate": {"name": "S1", "package": package.name},
            "provenance": {"starting_sha": "abc", "note": "frozen"},
            "strong_anchors": [
                {"opponent": "A2", "actual_order": "first", "path": anchor.name}
            ],
            "operational_provenance": {
                "linux": {
                    "path": certification.name,
                    "artifact_sha256": _sha256(certification),
                    "archive_sha256": archive,
                    "evaluated_tree_sha256": tree,
                    "games": 2,
                    "actual_first_games": 1,
                    "actual_second_games": 1,
                    "completed_games": 2,
                    "policy_errors": 0,
                    "illegal_actions": 0,
                    "artifact_mutations": 0,
                    "status": "PASS",
                }
            },
        },
    )
    dashboard = build_dashboard(spec)
    assert dashboard["provenance"]["starting_sha"] == "abc"
    linux = dashboard["operational_provenance"]["linux"]
    assert linux["status"] == "PASS"
    assert linux["actual_order_games"] == {"first": 1, "second": 1}
    assert linux["evaluated_tree_sha256"] == tree

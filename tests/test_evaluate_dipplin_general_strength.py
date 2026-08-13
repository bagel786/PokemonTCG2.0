from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from scripts.evaluate_dipplin_general_strength import (
    CANONICAL_MECHANICS_COMMAND,
    CANONICAL_MECHANICS_JUNIT,
    CANONICAL_MECHANICS_SCOPE,
    CANONICAL_MECHANICS_TEST_FILE,
    CANONICAL_MECHANICS_TEST_NAMES,
    PINNED_MECHANICS_JUNIT_SHA256,
    PINNED_MECHANICS_TEST_FILE_SHA256,
    PINNED_S1_SETUP_AUDIT_SHA256,
    WEAK_CLONE_UNAVAILABLE_AVAILABILITY,
    WEAK_CLONE_UNAVAILABLE_COVERAGE,
    WEAK_CLONE_UNAVAILABLE_STATUS,
    DashboardError,
    _mechanics_dashboard,
    _portable_v2_output,
    _receipt_dashboard,
    _replay_aggregate_v2,
    _replay_quality_counts,
    _replay_v2_summary,
    _stage6_promotion_gate,
    _stage_reports_equal,
    _strength_source_dashboard,
    _verify_sealed_nested_contract,
    _v2_operational_provenance,
    _v2_replay_manifest_provenance,
    _verify_s2_linux_provenance,
    _weak_clones_dashboard,
    build_dashboard,
    render_markdown,
    _setup_choice_audit,
)


def _write(path: Path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _unavailable_clone(name: str) -> dict[str, object]:
    return {
        "name": name,
        "availability": WEAK_CLONE_UNAVAILABLE_AVAILABILITY,
        "coverage": WEAK_CLONE_UNAVAILABLE_COVERAGE,
        "runnable_status": WEAK_CLONE_UNAVAILABLE_STATUS,
        "evaluated_contexts": "NOT_MEASURABLE",
        "failed_games": "NOT_MEASURABLE",
        "policy_errors": "NOT_MEASURABLE",
        "illegal_actions": "NOT_MEASURABLE",
        "unknown_contexts": "NOT_MEASURABLE",
        "note": "No exact-current candidate execution artifact is available.",
    }


def _canonical_mechanics() -> dict[str, object]:
    return {
        "status": "PASS",
        "junit_xml": str(CANONICAL_MECHANICS_JUNIT),
        "junit_xml_sha256": PINNED_MECHANICS_JUNIT_SHA256,
        "expected_tests": len(CANONICAL_MECHANICS_TEST_NAMES),
        "command": CANONICAL_MECHANICS_COMMAND,
        "run_date": "2026-08-13",
        "test_files": [
            {
                "path": str(CANONICAL_MECHANICS_TEST_FILE),
                "sha256": PINNED_MECHANICS_TEST_FILE_SHA256,
            }
        ],
        "scope": list(CANONICAL_MECHANICS_SCOPE),
        "caveat": "Policy-level mechanics evidence; not an archive execution.",
    }


def _canonical_setup_audit() -> dict[str, object]:
    root = Path(__file__).resolve().parents[1]
    return {
        "path": str(
            root
            / "artifacts/general_strength/s1_buckets/setup_choice_audit_5000.json"
        ),
        "artifact_sha256": PINNED_S1_SETUP_AUDIT_SHA256,
        "expected_schema": "dipplin-setup-choice-audit-v1",
        "expected_games": 5000,
        "expected_actual_order": "second",
        "expected_archive_sha256": (
            "ec74efe096473c58a2057cabfee93bf337bc18848c202a6e3d36bcba802db171"
        ),
        "expected_tree_sha256": (
            "940654489ea1f286982226f1f0cba4dd7340378b997a3f88ab6915c5d67f6c98"
        ),
        "note": "Aggregate setup-only causal audit; never strength evidence.",
    }


def _tar_gz(path: Path, files: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name, payload in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))


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


def test_dashboard_rejects_unknown_schema(tmp_path):
    spec = tmp_path / "spec.json"
    _write(spec, {"dashboard_schema": "future-dashboard-v99"})

    with pytest.raises(DashboardError, match="unsupported dashboard_schema"):
        build_dashboard(spec)


def test_strict_candidate_binds_runtime_tree_and_source_sha(tmp_path):
    from scripts.package_dipplin import (
        package_file_manifest,
        package_tree_sha256,
        runtime_source_tree_sha256,
    )

    package = tmp_path / "s2.tar.gz"
    files = {"main.py": b"pass\n"}
    _tar_gz(package, files)
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    (extracted / "main.py").write_bytes(files["main.py"])
    manifest = tmp_path / "manifest.json"
    tree = package_tree_sha256(extracted).lower()
    runtime_tree = runtime_source_tree_sha256(extracted)[0].lower()
    _write(
        manifest,
        {
            "variant": "s2",
            "output": {
                "archive_sha256": _sha256(package),
                "extracted_tree_sha256": tree,
                "file_manifest": package_file_manifest(extracted),
            },
            "runtime": {"runtime_source_tree_sha256": runtime_tree},
        },
    )
    candidate = {
        "name": "S2",
        "variant": "s2",
        "source_sha": "c" * 40,
        "tree_sha256": tree,
        "runtime_tree_sha256": runtime_tree,
        "package": package.name,
        "package_sha256": _sha256(package),
        "manifest": manifest.name,
        "manifest_sha256": _sha256(manifest),
    }
    from scripts.evaluate_dipplin_general_strength import _candidate_dashboard

    result = _candidate_dashboard(tmp_path, candidate, strict=True)
    assert result["verified_runtime_tree_sha256"] == runtime_tree

    candidate["runtime_tree_sha256"] = "d" * 64
    with pytest.raises(DashboardError, match="runtime_tree_sha256 mismatch"):
        _candidate_dashboard(tmp_path, candidate, strict=True)
    candidate["runtime_tree_sha256"] = runtime_tree
    candidate["source_sha"] = "short"
    with pytest.raises(DashboardError, match="40-character"):
        _candidate_dashboard(tmp_path, candidate, strict=True)

    candidate["source_sha"] = "c" * 40
    candidate["tree_sha256"] = None
    with pytest.raises(DashboardError, match="tree_sha256 is required"):
        _candidate_dashboard(tmp_path, candidate, strict=True)


def test_v1_weak_clone_rows_remain_compatible():
    row = {
        "name": "Lucario",
        "status": "NOT_RUN_FOR_CURRENT_S1",
        "evidence_tier": "coverage_only",
        "result_path": None,
    }
    result = _weak_clones_dashboard([row], strict=False)[0]
    assert result["status"] == row["status"]
    assert result["evidence_tier"] == "coverage_only"
    assert result["result_path"] is None


def test_v2_operational_provenance_rejects_unhashed_claim():
    with pytest.raises(DashboardError, match="hashed artifact declaration"):
        _v2_operational_provenance(Path.cwd(), {"linux": {"status": "PASS"}})


def test_replay_quality_counts_are_exact_and_partitioned(tmp_path):
    aggregate = {
        "classification_counts": {
            "EQUIVALENT": 2,
            "AGENT_DOMINATES": 1,
            "EXPERT_DOMINATES": 1,
            "INCOMPARABLE": 1,
            "UNCERTIFIABLE": 3,
        },
        "quality_counts": {
            "proposal_error_rows": 2,
            "candidate_policy_error_rows": 1,
            "candidate_action_unstable_rows": 1,
            "uncertifiable_rows": 3,
            "incomparable_rows": 1,
        },
    }
    result = _replay_quality_counts(aggregate, tmp_path / "replay.json")
    assert result["candidate_policy_error_rows"] == 1

    aggregate["quality_counts"]["proposal_error_rows"] = 3
    with pytest.raises(DashboardError, match="partition"):
        _replay_quality_counts(aggregate, tmp_path / "replay.json")
    aggregate["quality_counts"]["proposal_error_rows"] = 2
    aggregate["quality_counts"]["incomparable_rows"] = 0
    with pytest.raises(DashboardError, match="aliases"):
        _replay_quality_counts(aggregate, tmp_path / "replay.json")


def test_strict_weak_clones_reject_strength_outcomes_and_unmeasured_zeros():
    with pytest.raises(DashboardError, match="prohibited strength outcome"):
        _weak_clones_dashboard(
            [{"name": "Lucario", "win_rate": 0.99}], strict=True
        )
    malformed = _unavailable_clone("Lucario")
    malformed["policy_errors"] = 0
    with pytest.raises(DashboardError, match="NOT_MEASURABLE"):
        _weak_clones_dashboard(
            [malformed],
            strict=True,
        )
    row = _weak_clones_dashboard([_unavailable_clone("Lucario")], strict=True)[0]
    assert row["win_rate_is_strength_metric"] is False

    runnable_without_evidence = _unavailable_clone("Lucario")
    runnable_without_evidence["runnable_status"] = "RUN"
    runnable_without_evidence["availability"] = "RUNNABLE_CURRENT_CANDIDATE"
    runnable_without_evidence["coverage"] = "execution_artifact"
    with pytest.raises(DashboardError, match="RUN is not admitted"):
        _weak_clones_dashboard([runnable_without_evidence], strict=True)


def test_strict_mechanics_requires_exact_pinned_suite_and_rejects_one_test(tmp_path):
    declaration = _canonical_mechanics()
    result = _mechanics_dashboard(Path.cwd(), declaration, strict=True)
    assert result["passed"] == 15

    junit = tmp_path / "forged.xml"
    junit.write_text(
        '<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0">'
        '<testcase name="test_one"/></testsuite></testsuites>',
        encoding="utf-8",
    )
    forged = dict(declaration)
    forged.update(
        {
            "junit_xml": str(junit),
            "junit_xml_sha256": _sha256(junit),
            "expected_tests": 1,
        }
    )
    with pytest.raises(DashboardError, match="not canonical"):
        _mechanics_dashboard(tmp_path, forged, strict=True)


def test_linux_certification_enforces_platform_machine_and_s2_mode(tmp_path):
    tree = "a" * 64
    archive = "b" * 64
    certification = tmp_path / "linux.json"
    payload = {
        "schema": "cert-v1",
        "games": 2,
        "wins": 1,
        "draws": 0,
        "failed_games": 0,
        "hero_policy_errors": 0,
        "opponent_policy_errors": 0,
        "hero_illegal_actions": 0,
        "opponent_illegal_actions": 0,
        "hero_telemetry": {"s2_enabled": 2},
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
    }
    _write(certification, payload)
    declaration = {
        "path": certification.name,
        "artifact_sha256": _sha256(certification),
        "archive_sha256": archive,
        "evaluated_tree_sha256": tree,
        "expected_platform": "Linux",
        "expected_machine": "x86_64",
        "expected_s2_enabled": True,
        "games": 2,
        "actual_first_games": 1,
        "actual_second_games": 1,
        "completed_games": 2,
        "policy_errors": 0,
        "illegal_actions": 0,
        "artifact_mutations": 0,
        "s2_enabled_games": 2,
        "status": "PASS",
    }
    from scripts.evaluate_dipplin_general_strength import _operational_provenance

    result = _operational_provenance(tmp_path, {"linux": declaration})
    assert result["linux"]["s2_enabled_games"] == 2

    payload["artifact_provenance"]["machine"] = "arm64"
    _write(certification, payload)
    declaration["artifact_sha256"] = _sha256(certification)
    with pytest.raises(DashboardError, match="machine mismatch"):
        _operational_provenance(tmp_path, {"linux": declaration})


def test_v2_manifest_contract_requires_both_pristine_frozen_splits(tmp_path):
    with pytest.raises(DashboardError, match="keys mismatch"):
        _v2_replay_manifest_provenance(
            tmp_path,
            {
                "validation": {
                    "path": "validation.json",
                    "artifact_sha256": "a" * 64,
                },
                "final_holdout": {
                    "path": "holdout.json",
                    "artifact_sha256": "b" * 64,
                },
            },
        )


def test_v2_replay_aggregate_rejects_nonpartition_rates(tmp_path):
    aggregate = _v2_aggregate()
    aggregate["episode_rates"]["EQUIVALENT"] = 0.25
    with pytest.raises(DashboardError, match="do not form a partition"):
        _replay_aggregate_v2(
            aggregate,
            path=tmp_path / "replay.json",
            expected_episodes=2,
            sealed=True,
        )


def _v2_aggregate(*, episodes=2):
    counts = {
        "EQUIVALENT": 1,
        "AGENT_DOMINATES": 1,
        "EXPERT_DOMINATES": 0,
        "INCOMPARABLE": 0,
        "UNCERTIFIABLE": 0,
    }
    return {
        "episode_count": episodes,
        "decision_count": 2,
        "manifest_episode_count": episodes,
        "evaluated_episode_count": episodes,
        "episode_coverage": 1.0,
        "classification_counts": counts,
        "decision_rates": {
            label: count / 2 for label, count in counts.items()
        },
        "episode_rates": {
            "EQUIVALENT": 0.5,
            "AGENT_DOMINATES": 0.5,
            "EXPERT_DOMINATES": 0.0,
            "INCOMPARABLE": 0.0,
            "UNCERTIFIABLE": 0.0,
        },
        "episode_bootstrap_95": {
            label: [0.0, 1.0] for label in counts
        },
        "expert_dominates_rate": 0.0,
        "agent_dominates_rate": 0.5,
        "quality_counts": {
            "proposal_error_rows": 0,
            "candidate_policy_error_rows": 0,
            "candidate_action_unstable_rows": 0,
            "uncertifiable_rows": 0,
            "incomparable_rows": 0,
        },
    }


def test_replay_v2_aggregate_requires_full_coverage_and_safe_quality_counts(tmp_path):
    aggregate = _v2_aggregate()
    result = _replay_aggregate_v2(
        aggregate,
        path=tmp_path / "holdout.json",
        expected_episodes=2,
        sealed=True,
    )
    assert result["quality_counts"]["candidate_policy_error_rows"] == 0

    aggregate["episode_coverage"] = 0.5
    with pytest.raises(DashboardError, match="coverage"):
        _replay_aggregate_v2(
            aggregate,
            path=tmp_path / "holdout.json",
            expected_episodes=2,
            sealed=True,
        )


def test_receipt_rejects_caller_selected_alternate_path(tmp_path):
    from scripts import evaluate_dipplin_replay_regret as regret

    holdout = tmp_path / "holdout.json"
    holdout.write_text("{}\n", encoding="utf-8")
    qualification_sha = "a" * 64
    payload_sha = "b" * 64
    validation_sha = "c" * 64
    manifest_file_sha = "d" * 64
    manifest_payload_sha = "e" * 64
    package_sha = "f" * 64
    candidate_manifest_sha = "1" * 64
    tree = "2" * 64
    runtime_tree = "3" * 64
    evaluator_path = Path(regret.__file__).resolve()
    evaluator_sha = _sha256(evaluator_path)
    evaluator_bytes = evaluator_path.read_bytes()
    evaluator_blob = hashlib.sha1(
        b"blob " + str(len(evaluator_bytes)).encode("ascii") + b"\0" + evaluator_bytes
    ).hexdigest()
    parameters = dict(regret.FROZEN_SEALED_PARAMETERS)
    receipt = tmp_path / "receipt.json"
    value = {
        "schema": "dipplin-final-holdout-receipt-v2",
        "status": "COMPLETE",
        "baseline_s1_archive_sha256": regret.PINNED_S1_ARCHIVE_SHA256,
        "baseline_s1_validation_sha256": regret.PINNED_S1_VALIDATION_OUTPUT_SHA256,
        "manifest_file_sha256": manifest_file_sha,
        "manifest_payload_sha256": manifest_payload_sha,
        "candidate": "s2",
        "candidate_archive_sha256": package_sha,
        "candidate_manifest_sha256": candidate_manifest_sha,
        "candidate_extracted_tree_sha256": tree,
        "candidate_runtime_tree_sha256": runtime_tree,
        "qualification_file_sha256": qualification_sha,
        "qualification_payload_sha256": payload_sha,
        "candidate_validation_sha256": validation_sha,
        "evaluator_path": str(evaluator_path.relative_to(evaluator_path.parents[1])),
        "evaluator_sha256": evaluator_sha,
        "evaluator_git_blob_sha1": evaluator_blob,
        "parameters": parameters,
        "aggregate_output": str(holdout.resolve()),
        "aggregate_output_sha256": _sha256(holdout),
    }
    _write(receipt, value)
    declaration = {
        "path": receipt.name,
        "artifact_sha256": _sha256(receipt),
        "expected_parameters": parameters,
        "evaluator": {
            "path": str(evaluator_path.relative_to(evaluator_path.parents[1])),
            "sha256": evaluator_sha,
            "git_blob_sha1": evaluator_blob,
        },
    }
    with pytest.raises(DashboardError, match="path is not canonical"):
        _receipt_dashboard(
            tmp_path,
            declaration,
            holdout={"source": str(holdout), "source_sha256": _sha256(holdout)},
            holdout_manifest={
                "source_sha256": manifest_file_sha,
                "manifest_payload_sha256": manifest_payload_sha,
            },
            qualification={
                "file_sha256": qualification_sha,
                "payload_sha256": payload_sha,
                "candidate_validation_sha256": validation_sha,
            },
            candidate={
                "package_sha256": package_sha,
                "manifest_sha256": candidate_manifest_sha,
                "verified_tree_sha256": tree,
                "verified_runtime_tree_sha256": runtime_tree,
            },
        )


def _replay_candidate():
    return {
        "package_sha256": "a" * 64,
        "manifest_sha256": "b" * 64,
        "verified_tree_sha256": "c" * 64,
        "verified_runtime_tree_sha256": "d" * 64,
    }


def _evaluated_candidate():
    return {
        "archive_sha256": "a" * 64,
        "manifest_sha256": "b" * 64,
        "extracted_tree_sha256": "c" * 64,
        "runtime_source_tree_sha256": "d" * 64,
    }


def _replay_baseline():
    from scripts import evaluate_dipplin_replay_regret as regret

    frozen = regret.verify_frozen_s1_provenance()

    return {
        "variant": "s1",
        "archive_sha256": regret.PINNED_S1_ARCHIVE_SHA256,
        "manifest_sha256": regret.PINNED_S1_MANIFEST_SHA256,
        "extracted_tree_sha256": regret.PINNED_S1_EXTRACTED_TREE_SHA256,
        "runtime_source_tree_sha256": regret.PINNED_S1_RUNTIME_TREE_SHA256,
        "validation_result_sha256": regret.PINNED_S1_VALIDATION_OUTPUT_SHA256,
        "paired_record_count": regret.PINNED_S1_PRIMARY_RECORD_COUNT,
        "paired_record_id_sequence_sha256": frozen[
            "paired_record_id_sequence_sha256"
        ],
    }


def _replay_declaration(path: Path, *, split: str, sealed: bool, manifest):
    return {
        "path": path.name,
        "artifact_sha256": _sha256(path),
        "expected_schema": "dipplin-replay-regret-v2",
        "expected_split": split,
        "expected_sealed": sealed,
        "expected_episode_count": 2,
        "expected_manifest_file_sha256": manifest["source_sha256"],
        "expected_manifest_payload_sha256": manifest[
            "manifest_payload_sha256"
        ],
    }


def test_sealed_replay_rejects_alternate_path_and_nested_detail(tmp_path):
    from scripts.evaluate_dipplin_general_strength import CANONICAL_REPLAY_METHOD
    from scripts import evaluate_dipplin_replay_regret as regret

    alternate = tmp_path / "holdout.json"
    alternate.write_text("{}\n", encoding="utf-8")
    manifest = {
        "source_sha256": "e" * 64,
        "manifest_payload_sha256": "f" * 64,
        "episode_count": 2,
        "opponent_archetype_episode_counts": {"deck_a": 1, "deck_b": 1},
    }
    with pytest.raises(DashboardError, match="path is not canonical"):
        _replay_v2_summary(
            tmp_path,
            _replay_declaration(
                alternate, split="FINAL_HOLDOUT", sealed=True, manifest=manifest
            ),
            split="FINAL_HOLDOUT",
            candidate=_replay_candidate(),
            manifest=manifest,
        )

    document = {
        "method": {**CANONICAL_REPLAY_METHOD, "private_sentinel": [1, 2, 3]},
        "baseline_incumbent_s1": _replay_baseline(),
        "evaluated_candidate": regret.verify_s2_candidate(),
    }
    with pytest.raises(DashboardError, match="method contract mismatch"):
        _verify_sealed_nested_contract(document, alternate)

    document["method"] = CANONICAL_REPLAY_METHOD
    document["evaluated_candidate"] = {
        **regret.verify_s2_candidate(),
        "private_sentinel": [1, 2, 3],
    }
    with pytest.raises(DashboardError, match="schema/identity mismatch"):
        _verify_sealed_nested_contract(document, alternate)


def test_validation_replay_v2_rejects_noncanonical_path(tmp_path):
    manifest = {
        "source_sha256": "e" * 64,
        "manifest_payload_sha256": "f" * 64,
        "episode_count": 2,
        "opponent_archetype_episode_counts": {"deck_a": 1, "deck_b": 1},
    }
    primary_aggregate = _v2_aggregate()
    primary_aggregate.update(
        {
            "opponent_archetype_episode_counts": {"deck_a": 1, "deck_b": 1},
            "opponent_archetype_decision_counts": {"deck_a": 1, "deck_b": 1},
            "opponent_archetypes": {"deck_a": 1, "deck_b": 1},
            "opponent_archetypes_basis": "unique_episode_id",
        }
    )
    exploratory_aggregate = _v2_aggregate()
    for key in (
        "manifest_episode_count",
        "evaluated_episode_count",
        "episode_coverage",
    ):
        exploratory_aggregate.pop(key)
    exploratory_aggregate.update(
        {
            "episodes_with_selected_prompts": 2,
            "opponent_archetype_episode_counts": {"deck_a": 1, "deck_b": 1},
            "opponent_archetype_decision_counts": {"deck_a": 1, "deck_b": 1},
            "opponent_archetypes": {"deck_a": 1, "deck_b": 1},
            "opponent_archetypes_basis": "unique_episode_id",
        }
    )
    primary = {
        "role": "qualification_primary",
        "selection": {
            "mode": "exact_frozen_s1_record_ids",
            "record_count": 2,
            "order_preserved": True,
        },
        "aggregate": primary_aggregate,
        "decision_rows": [{"record_id": "a"}, {"record_id": "b"}],
    }
    exploratory = {
        "role": "exploratory_safety_veto_only",
        "safety_veto_only": True,
        "eligible_for_efficacy_rate": False,
        "aggregate": exploratory_aggregate,
        "decision_rows": [{"record_id": "c"}, {"record_id": "d"}],
    }
    path = tmp_path / "validation.json"
    document = {
        "schema": "dipplin-replay-regret-v2",
        "split": "VALIDATION",
        "sealed": False,
        "candidate_variant": "s2",
        "baseline_incumbent_s1": _replay_baseline(),
        "manifest_payload_sha256": manifest["manifest_payload_sha256"],
        "evaluated_candidate": _evaluated_candidate(),
        "headline_set": "paired_primary",
        "aggregate_alias": "evaluation_sets.paired_primary.aggregate",
        "aggregate": primary_aggregate,
        "evaluation_sets": {
            "paired_primary": primary,
            "s2_exploratory": exploratory,
        },
        "combined_rate_permitted": False,
    }
    _write(path, document)
    declaration = _replay_declaration(
        path, split="VALIDATION", sealed=False, manifest=manifest
    )
    with pytest.raises(DashboardError, match="VALIDATION replay path is not canonical"):
        _replay_v2_summary(
            tmp_path,
            declaration,
            split="VALIDATION",
            candidate=_replay_candidate(),
            manifest=manifest,
        )


def test_strength_source_uses_stage3_first_stage2_second_and_recomputes(
    tmp_path, monkeypatch
):
    from scripts import evaluate_dipplin_s2_stages as stage_evaluator

    s1_tree = "1" * 64
    s2_tree = "2" * 64
    package_sha = "3" * 64
    manifest_sha = "4" * 64

    def cell(label, order, tree, wins, games=10):
        path = tmp_path / f"{label}.json"
        payload = _evaluation(order, wins, games=games, tree=tree)
        payload.update(
            {
                "failed_games": 0,
                "hero_illegal_actions": 0,
                "opponent_illegal_actions": 0,
            }
        )
        _write(path, payload)
        return {
            "id": label,
            "matchup": "A2",
            "opponent_name": "A2",
            "actual_order": order,
            "source": {
                "path": str(path),
                "artifact_sha256": _sha256(path),
                "tree_sha256": tree,
            },
            "games": games,
            "scheduled_games": games,
            "wins": wins,
            "losses": games - wins,
            "draws": 0,
            "failed_games": 0,
            "hero_policy_errors": 0,
            "opponent_policy_errors": 0,
            "hero_illegal_actions": 0,
            "opponent_illegal_actions": 0,
            "operational_telemetry": {
                "fatal_counts": {},
                "nonfatal_search_fallback_counts": {},
            },
        }

    stages = {
        "stage1": {
            "status": "EVALUATED",
            "decision": {"verdict": "STRONG", "gates": {"pass": True}},
        },
        "stage2": {
            "status": "EVALUATED",
            "baseline_cells": [cell("s1-second", "second", s1_tree, 5)],
            "candidate_cells": [cell("s2-second", "second", s2_tree, 6)],
            "decision": {"verdict": "PASS", "gates": {"pass": True}},
        },
        "stage3": {
            "status": "EVALUATED",
            "baseline_cells": [cell("s1-first", "first", s1_tree, 7)],
            "candidate_cells": [cell("s2-first", "first", s2_tree, 8)],
            "decision": {"verdict": "PASS", "gates": {"pass": True}},
        },
        "stage4": {
            "status": "EVALUATED",
            "baseline_cells": [
                cell("mirror-control-first", "first", s1_tree, 6),
                cell("mirror-control-second", "second", s1_tree, 4),
            ],
            "candidate_cells": [
                cell("mirror-s2-first", "first", s2_tree, 6),
                cell("mirror-s2-second", "second", s2_tree, 5),
            ],
            "decision": {"verdict": "PASS", "gates": {"pass": True}},
        },
        "stage5": {
            "status": "EVALUATED",
            "decision": {"verdict": "PASS", "gates": {"pass": True}},
        },
    }
    spec_path = tmp_path / "stages-spec.json"
    _write(
        spec_path,
        {"schema": "synthetic", "provenance": {"source_head": "6" * 40}},
    )
    report = {
        "schema": "dipplin-s2-stage-evaluation-v1",
        "spec": {"path": str(spec_path.resolve()), "sha256": _sha256(spec_path)},
        "baseline": {"tree_sha256": s1_tree, "archive_sha256": "5" * 64},
        "candidate": {
            "tree_sha256": s2_tree,
            "archive_sha256": package_sha,
            "package_manifest": {"sha256": manifest_sha},
        },
        "stages": stages,
    }
    report_path = tmp_path / "stages-report.json"
    _write(report_path, report)
    monkeypatch.setattr(stage_evaluator, "evaluate_spec", lambda _path: report)
    declaration = {
        "stage_spec": spec_path.name,
        "stage_spec_sha256": _sha256(spec_path),
        "stage_report": report_path.name,
        "stage_report_sha256": _sha256(report_path),
        "anchor_stage_by_order": {"first": "stage3", "second": "stage2"},
        "same_deck_stage": "stage4",
        "required_verdicts": {
            "stage1": ["PROMISING", "STRONG"],
            "stage2": ["PASS", "STRONG"],
            "stage3": ["PASS"],
            "stage4": ["PASS"],
            "stage5": ["PASS"],
        },
    }
    with pytest.raises(DashboardError, match="canonical Stage1-5 spec/report"):
        _strength_source_dashboard(
            tmp_path,
            declaration,
            {
                "verified_tree_sha256": s2_tree,
                "package_sha256": package_sha,
                "manifest_sha256": manifest_sha,
                "source_sha": "6" * 40,
            },
        )


def test_v2_stage2_kill_keeps_exact_s1_and_marks_later_proof_not_applicable(
    tmp_path,
):
    from scripts import evaluate_dipplin_replay_regret as regret

    root = Path(__file__).resolve().parents[1]
    incumbent_spec_path = root / "data/dipplin_general_strength/s1_dashboard_spec.json"
    incumbent_spec = json.loads(incumbent_spec_path.read_text(encoding="utf-8"))
    incumbent_candidate = dict(incumbent_spec["candidate"])
    incumbent_candidate.update(
        {
            "variant": "s1",
            "runtime_tree_sha256": regret.PINNED_S1_RUNTIME_TREE_SHA256.lower(),
            "package": str(root / "artifacts/dipplin_s1/submission.tar.gz"),
            "manifest": str(root / "artifacts/dipplin_s1/submission.manifest.json"),
        }
    )
    stage_spec = root / "data/dipplin_general_strength/s2_stage_evaluation_spec.json"
    stage_spec_document = json.loads(stage_spec.read_text(encoding="utf-8"))
    source_head = stage_spec_document["provenance"]["source_head"]
    stage_report = root / "artifacts/general_strength/s2_stage2/stage2_evaluation.json"

    replay_manifests = json.loads(json.dumps(incumbent_spec["replay_manifests"]))
    replay_manifests["validation"]["path"] = str(
        regret.PINNED_MANIFESTS["VALIDATION"]["path"]
    )
    replay_manifests["final_holdout"]["path"] = str(
        regret.PINNED_MANIFESTS["FINAL_HOLDOUT"]["path"]
    )
    validation = root / "artifacts/general_strength/replay/validation_regret_s1.json"
    weak_clones = [
        _unavailable_clone(name)
        for name in (
            "Mega Lucario",
            "Crustle / Kangaskhan",
            "Teal Mask Ogerpon",
            "Bellibolt",
            "Starmie / Froslass",
            "Dragapult",
            "Mega Lopunny",
            "Garchomp",
        )
    ]
    second_bucket = dict(incumbent_spec["second_bucket_analysis"])
    second_bucket["path"] = str(
        root / "artifacts/general_strength/s1_buckets/second_bucket_analysis_400.json"
    )
    linux = dict(
        incumbent_spec["operational_provenance"]["linux_x86_64_complete_game"]
    )
    linux["path"] = str(
        root / "artifacts/dipplin_s1/certification/linux_x86_64_complete_game.json"
    )
    spec = tmp_path / "dashboard-v2.json"
    _write(
        spec,
        {
            "dashboard_schema": "dipplin-general-strength-dashboard-v2",
            "candidate": incumbent_candidate,
            "rejected_s2_candidate": {
                "source_sha": source_head,
                "package": str(root / "artifacts/dipplin_s2/submission.tar.gz"),
                "package_sha256": regret.PINNED_S2_ARCHIVE_SHA256,
                "manifest": str(root / "artifacts/dipplin_s2/submission.manifest.json"),
                "manifest_sha256": regret.PINNED_S2_MANIFEST_SHA256,
                "tree_sha256": regret.PINNED_S2_EXTRACTED_TREE_SHA256,
                "runtime_tree_sha256": regret.PINNED_S2_RUNTIME_TREE_SHA256,
            },
            "strength_source": {
                "stage_spec": str(stage_spec),
                "stage_spec_sha256": _sha256(stage_spec),
                "stage_report": str(stage_report),
                "stage_report_sha256": _sha256(stage_report),
                "incumbent_dashboard_spec": str(incumbent_spec_path),
                "incumbent_dashboard_spec_sha256": _sha256(incumbent_spec_path),
                "required_stage1_verdicts": ["STRONG"],
                "required_stage2_verdict": "KILL",
            },
            "replay_manifests": replay_manifests,
            "replay_validation": {
                "path": str(validation),
                "artifact_sha256": _sha256(validation),
                "expected_schema": "dipplin-replay-regret-v1",
                "expected_split": "VALIDATION",
                "expected_sealed": False,
                "expected_episode_count": 50,
                "expected_manifest_file_sha256": regret.PINNED_MANIFESTS[
                    "VALIDATION"
                ]["file_sha256"],
                "expected_manifest_payload_sha256": regret.PINNED_MANIFESTS[
                    "VALIDATION"
                ]["payload_sha256"],
            },
            "second_bucket_analysis": second_bucket,
            "setup_choice_audit": _canonical_setup_audit(),
            "mechanics": _canonical_mechanics(),
            "weak_clones": weak_clones,
            "operational_provenance": {"linux_x86_64_complete_game": linux},
            "final_verdict": "KEEP_S1",
        },
    )
    dashboard = build_dashboard(spec)
    assert dashboard["candidate"]["variant"] == "s1"
    assert dashboard["stage_verdicts"]["stage2"] == "KILL"
    assert dashboard["qualification"]["status"].startswith("NOT_APPLICABLE")
    assert dashboard["sealed_replay_holdout"]["status"].startswith("NOT_RUN")
    assert dashboard["operational_provenance"]["s2_linux_x86_64"][
        "status"
    ].startswith("NOT_APPLICABLE")
    assert dashboard["strong_anchors"]["anchor_actual_first"] == 0.5425


def test_v2_kill_rejects_forged_s1_replay_path_and_non_keep_verdict(tmp_path):
    from scripts import evaluate_dipplin_replay_regret as regret
    from scripts.evaluate_dipplin_general_strength import (
        _s1_replay_validation_summary,
    )

    forged = tmp_path / "forged-s1.json"
    _write(
        forged,
        {
            "schema": "dipplin-replay-regret-v1",
            "split": "VALIDATION",
            "sealed": False,
            "aggregate": {"classification_counts": {"EQUIVALENT": 1}},
        },
    )
    declaration = {
        "path": forged.name,
        "artifact_sha256": _sha256(forged),
        "expected_schema": "dipplin-replay-regret-v1",
        "expected_split": "VALIDATION",
        "expected_sealed": False,
        "expected_episode_count": 50,
        "expected_manifest_file_sha256": regret.PINNED_MANIFESTS["VALIDATION"][
            "file_sha256"
        ],
        "expected_manifest_payload_sha256": regret.PINNED_MANIFESTS[
            "VALIDATION"
        ]["payload_sha256"],
    }
    with pytest.raises(DashboardError, match="path is not canonical"):
        _s1_replay_validation_summary(
            tmp_path,
            declaration,
            candidate={
                "package_sha256": regret.PINNED_S1_ARCHIVE_SHA256.lower(),
                "manifest_sha256": regret.PINNED_S1_MANIFEST_SHA256.lower(),
            },
            manifest={
                "episode_count": 50,
                "source_sha256": regret.PINNED_MANIFESTS["VALIDATION"][
                    "file_sha256"
                ].lower(),
                "manifest_payload_sha256": regret.PINNED_MANIFESTS[
                    "VALIDATION"
                ]["payload_sha256"].lower(),
            },
        )

    root = Path(__file__).resolve().parents[1]
    incumbent_spec_path = root / "data/dipplin_general_strength/s1_dashboard_spec.json"
    incumbent = json.loads(incumbent_spec_path.read_text(encoding="utf-8"))
    candidate = dict(incumbent["candidate"])
    candidate.update(
        {
            "variant": "s1",
            "runtime_tree_sha256": regret.PINNED_S1_RUNTIME_TREE_SHA256.lower(),
            "package": str(root / "artifacts/dipplin_s1/submission.tar.gz"),
            "manifest": str(root / "artifacts/dipplin_s1/submission.manifest.json"),
        }
    )
    spec = tmp_path / "wrong-verdict.json"
    _write(
        spec,
        {
            "dashboard_schema": "dipplin-general-strength-dashboard-v2",
            "candidate": candidate,
            "final_verdict": "S1_NEAR_ARCHITECTURE_CEILING",
        },
    )
    with pytest.raises(DashboardError, match="combination is inconsistent"):
        build_dashboard(spec)


def test_v2_operational_provenance_requires_artifact_sha256(tmp_path):
    artifact = tmp_path / "linux.json"
    _write(artifact, {"schema": "test"})
    with pytest.raises(DashboardError, match="hashed artifact declaration"):
        _v2_operational_provenance(tmp_path, {"linux": {"path": artifact.name}})


def test_setup_choice_audit_requires_canonical_5k_artifact(tmp_path):
    result = _setup_choice_audit(Path.cwd(), _canonical_setup_audit())
    assert result["games"] == 5000
    assert result["strength_evidence"] is False

    forged = tmp_path / "setup.json"
    forged.write_text("{}\n", encoding="utf-8")
    declaration = _canonical_setup_audit()
    declaration.update(
        {"path": str(forged), "artifact_sha256": _sha256(forged)}
    )
    with pytest.raises(DashboardError, match="path is not canonical"):
        _setup_choice_audit(tmp_path, declaration)


def test_setup_choice_audit_rejects_self_hashed_tamper(tmp_path, monkeypatch):
    from scripts import evaluate_dipplin_general_strength as dashboard_module

    forged = tmp_path / "setup_choice_audit_5000.json"
    forged.write_bytes(
        dashboard_module.CANONICAL_S1_SETUP_AUDIT.read_bytes().replace(
            b'"games": 5000', b'"games": 4999', 1
        )
    )
    monkeypatch.setattr(dashboard_module, "CANONICAL_S1_SETUP_AUDIT", forged)
    declaration = _canonical_setup_audit()
    declaration.update(
        {"path": str(forged), "artifact_sha256": _sha256(forged)}
    )
    with pytest.raises(DashboardError, match="hash differs from the frozen pin"):
        _setup_choice_audit(tmp_path, declaration)


def test_stage6_promotion_gate_rejects_expert_dominating_holdout():
    holdout = {
        "decision_count": 100,
        "quality_counts": {
            "proposal_error_rows": 0,
            "candidate_policy_error_rows": 0,
            "candidate_action_unstable_rows": 0,
            "uncertifiable_rows": 0,
            "incomparable_rows": 0,
        },
        "rates": {"EXPERT_DOMINATES": 1.0, "AGENT_DOMINATES": 0.0},
    }
    with pytest.raises(DashboardError, match="Stage6 promotion gate"):
        _stage6_promotion_gate(holdout)


def test_stage_report_recomputation_allows_only_tiny_float_drift():
    pinned = {
        "candidate_latency_ms": {"weighted_mean": 127.22539320693278},
        "decision": {"verdict": "KILL"},
    }
    alternate_python = {
        "candidate_latency_ms": {"weighted_mean": 127.22539320693276},
        "decision": {"verdict": "KILL"},
    }
    assert _stage_reports_equal(pinned, alternate_python)

    tampered = json.loads(json.dumps(alternate_python))
    tampered["candidate_latency_ms"]["weighted_mean"] += 1e-6
    assert not _stage_reports_equal(pinned, tampered)


def test_s2_linux_certification_stays_inadmissible_until_pin_is_frozen():
    with pytest.raises(DashboardError, match="no pre-frozen artifact SHA"):
        _verify_s2_linux_provenance(
            Path.cwd(),
            {"s2_linux_x86_64": {}},
            {},
            candidate={"package_sha256": "a" * 64, "verified_tree_sha256": "b" * 64},
        )


def test_s2_linux_certification_rejects_extra_operational_labels(monkeypatch):
    from scripts import evaluate_dipplin_general_strength as dashboard_module

    monkeypatch.setattr(
        dashboard_module, "PINNED_S2_LINUX_CERTIFICATION_SHA256", "c" * 64
    )
    with pytest.raises(DashboardError, match="exactly the canonical"):
        _verify_s2_linux_provenance(
            Path.cwd(),
            {"s2_linux_x86_64": {}, "synthetic_linux": {}},
            {},
            candidate={"package_sha256": "a" * 64, "verified_tree_sha256": "b" * 64},
        )


def test_real_keep_s1_v2_spec_builds_canonical_rejection_dashboard():
    root = Path(__file__).resolve().parents[1]
    dashboard = build_dashboard(
        root / "data/dipplin_general_strength/s2_dashboard_spec.json"
    )
    assert dashboard["schema"] == "dipplin-general-strength-dashboard-v2"
    assert dashboard["candidate"]["variant"] == "s1"
    assert dashboard["final_verdict"] == "KEEP_S1"
    assert dashboard["stage_verdicts"] == {"stage1": "STRONG", "stage2": "KILL"}
    assert dashboard["mechanics"]["passed"] == 15
    assert dashboard["operational_provenance"]["linux_x86_64_complete_game"][
        "status"
    ] == "PASS"
    assert dashboard["sealed_replay_holdout"]["status"].startswith("NOT_RUN")
    assert {row["name"] for row in dashboard["weak_clones"]} == {
        "Mega Lucario",
        "Crustle / Kangaskhan",
        "Teal Mask Ogerpon",
        "Bellibolt",
        "Starmie / Froslass",
        "Dragapult",
        "Mega Lopunny",
        "Garchomp",
    }
    assert not any(
        Path(value).is_absolute()
        for value in _all_string_values(dashboard)
    )


def _all_string_values(value):
    if isinstance(value, dict):
        for nested in value.values():
            yield from _all_string_values(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _all_string_values(nested)
    elif isinstance(value, str):
        yield value


def test_v2_output_paths_are_cross_checkout_stable_and_reject_escapes(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    left_value = {"source": str(left / "artifacts/evidence.json")}
    right_value = {"source": str(right / "artifacts/evidence.json")}
    assert _portable_v2_output(left_value, repo_root=left) == _portable_v2_output(
        right_value, repo_root=right
    ) == {"source": "artifacts/evidence.json"}

    outside = tmp_path / "outside.json"
    with pytest.raises(DashboardError, match="escapes approved roots"):
        _portable_v2_output(
            {"source": str(outside)},
            repo_root=left,
            fixture_root=right,
        )

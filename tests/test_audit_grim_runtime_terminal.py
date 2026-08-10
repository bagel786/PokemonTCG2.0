from __future__ import annotations

import copy

from scripts.audit_grim_runtime_terminal import (
    _pass_digests,
    compare_passes,
    selected_by_stride,
    summarize_branches,
)


def test_stride_sample_is_bounded_and_offset_is_exact():
    selected = [
        ordinal
        for ordinal in range(100)
        if selected_by_stride(ordinal, limit=4, stride=7, offset=3)
    ]
    assert selected == [3, 10, 17, 24]
    assert not selected_by_stride(3, limit=0, stride=7, offset=3)


def test_pass_digest_callers_can_exclude_latency_without_weakening_decisions():
    classification = [{"status": "abstained", "reason": "timeout"}]
    decisions = [{"baseline": {"type": 5}, "selected": {"type": 5}}]
    first = _pass_digests(classification, decisions)
    # Latency is intentionally maintained outside these deterministic rows.
    second = _pass_digests(copy.deepcopy(classification), copy.deepcopy(decisions))
    assert first == second
    changed = copy.deepcopy(decisions)
    changed[0]["selected"] = {"type": 6}
    assert _pass_digests(classification, changed)[1] != first[1]


def test_branch_summary_exposes_accumulated_taint_and_same_turn_failures():
    events = [
        {
            "tainted": True,
            "all_taint_causes_preexisting": True,
            "child_logs_start_with_root_logs": True,
            "root_log_count": 4,
            "terminal_win": True,
            "same_turn": False,
            "taint_reasons": ["random_log:2"],
        },
        {
            "tainted": True,
            "all_taint_causes_preexisting": False,
            "child_logs_start_with_root_logs": True,
            "root_log_count": 4,
            "terminal_win": False,
            "same_turn": False,
            "taint_reasons": ["hidden_deck_or_looking_move"],
        },
    ]
    summary = summarize_branches(events)
    assert summary["all_native_branches_tainted"] is True
    assert summary["totals"]["tainted_only_by_preexisting_root_logs"] == 1
    assert summary["totals"]["terminal_win_rejected_as_not_same_turn"] == 1


def test_repeatability_requires_both_classification_and_decision_digests():
    first = {
        "classification_digest_sha256": "A",
        "decision_digest_sha256": "B",
        "native_rng_order_trace_digest_sha256": "N",
        "_classification_rows": [{"status": "proved"}],
    }
    exact = copy.deepcopy(first)
    assert compare_passes(first, exact)["required_repeatability_passed"] is True
    changed = copy.deepcopy(first)
    changed["classification_digest_sha256"] = "C"
    changed["_classification_rows"] = [{"status": "abstained"}]
    comparison = compare_passes(first, changed)
    assert comparison["required_repeatability_passed"] is False
    assert comparison["classification_mismatch_examples"]

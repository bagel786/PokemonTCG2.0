"""Tests for the machine-readable stage 6 source-audit decision rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from pevl_bench import stage6_rules


RELEASE = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def rules():
    return stage6_rules.load_rules(RELEASE / "protocol/stage6_source_audit_rules.json")


def test_rules_schema_and_outcome_set(rules) -> None:
    assert rules["schema_version"] == stage6_rules.RULES_SCHEMA_VERSION
    assert [outcome["id"] for outcome in rules["outcomes"]] == list(stage6_rules.OUTCOME_ORDER)
    priorities = [rule["priority"] for rule in rules["rules"]]
    assert sorted(priorities) == list(range(1, len(priorities) + 1))


def test_retained_table_matches_rendered_table(rules) -> None:
    retained = (RELEASE / "docs/STAGE6_DECISION_RULES.md").read_text(encoding="utf-8")
    assert retained == stage6_rules.render_decision_table(rules)


def test_black_box_boundary_is_unavailable(rules) -> None:
    result = stage6_rules.classify(
        rules=rules, source_access="unavailable_black_box", inventory_declared=False, hits=[]
    )
    assert result["outcome"] == "UNAVAILABLE"


def test_undeclared_inventory_fails_closed_to_unresolved(rules) -> None:
    result = stage6_rules.classify(
        rules=rules, source_access="available", inventory_declared=False, hits=[]
    )
    assert result["outcome"] == "UNRESOLVED"


def test_estimand_changing_hit_suppresses_mechanistic_claim(rules) -> None:
    result = stage6_rules.classify(
        rules=rules,
        source_access="available",
        inventory_declared=True,
        hits=[{"executes_dynamically": True, "changes_execution_relation": True}],
    )
    assert result["outcome"] == "ESTIMAND_CHANGING"


def test_bounded_hit_with_recorded_evidence_is_controlled(rules) -> None:
    result = stage6_rules.classify(
        rules=rules,
        source_access="available",
        inventory_declared=True,
        hits=[
            {
                "executes_dynamically": True,
                "changes_execution_relation": False,
                "bounded_or_disabled": True,
                "evidence_recorded": True,
            }
        ],
    )
    assert result["outcome"] == "CONTROLLED"


def test_executing_unbounded_hit_is_residual(rules) -> None:
    result = stage6_rules.classify(
        rules=rules,
        source_access="available",
        inventory_declared=True,
        hits=[
            {
                "executes_dynamically": True,
                "changes_execution_relation": False,
                "bounded_or_disabled": False,
            }
        ],
    )
    assert result["outcome"] == "RESIDUAL"


def test_dormant_hit_has_no_automatic_pass(rules) -> None:
    result = stage6_rules.classify(
        rules=rules,
        source_access="available",
        inventory_declared=True,
        hits=[{"executes_dynamically": False}],
    )
    assert result["outcome"] == "UNRESOLVED"


def test_clean_scan_never_yields_controlled(rules) -> None:
    result = stage6_rules.classify(
        rules=rules, source_access="available", inventory_declared=True, hits=[]
    )
    assert result["outcome"] == "RESIDUAL"
    note = next(rule.get("note", "") for rule in rules["rules"] if rule["id"] == "clean_scan_no_proof")
    assert "never yields CONTROLLED" in note


def test_classification_is_statelessly_deterministic(rules) -> None:
    kwargs = {
        "source_access": "available",
        "inventory_declared": True,
        "hits": [{"executes_dynamically": True, "changes_execution_relation": False, "bounded_or_disabled": False}],
    }
    assert stage6_rules.classify(rules=rules, **kwargs) == stage6_rules.classify(rules=rules, **kwargs)


def test_malformed_input_defaults_to_unresolved_fail_closed(rules) -> None:
    result = stage6_rules.classify(
        rules=rules, source_access="nonsense", inventory_declared=True, hits=None
    )
    assert result["outcome"] == rules["default_outcome"] == "UNRESOLVED"

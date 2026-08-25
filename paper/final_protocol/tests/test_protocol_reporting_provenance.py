"""Mutation tests for frozen-plan versus completed-reporting provenance."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


FINAL = Path(__file__).resolve().parents[1]
SCRIPT = FINAL / "scripts/audit_contradictions.py"

PROTOCOL = """
## Estimands and uncertainty

The 95% intervals use 100,000 paired resamples within each stratum.
Exact two-sided McNemar inference for the primary binary contrast is secondary.

### Timed-search repeat/worker stress test

Full restricted traces are retained locally for divergence localization; the
public package contains digests, first-divergence positions, and timing summaries.
"""

MANUSCRIPT = """
The completed-case descriptive-only Level taxonomy and reporting restrictions
are post-acquisition additions and were not part of the frozen plan.

The frozen historical audit was retrospective: outcome records already existed
before it ran, so it is not evidence of prospective blinding.

The digest-byte-count comparison is a later integrity extension. The frozen
primary endpoint was the trace digest, and adding byte counts changed no
reported mismatch counts.

For the stress test, the frozen protocol promised localization and timing
summaries. Those outputs are omitted and unverifiable; this is a
protocol/reporting deviation.
"""


@pytest.fixture(scope="module")
def audit_module():
    spec = importlib.util.spec_from_file_location("audit_contradictions", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_complete_explicit_provenance_disclosure_passes(audit_module) -> None:
    state = audit_module.provenance_semantics_state(PROTOCOL, MANUSCRIPT)
    required = {key: value for key, value in state.items() if key != "prohibited_phrase_hits"}
    assert required
    assert all(required.values())
    assert state["prohibited_phrase_hits"] == []


@pytest.mark.parametrize(
    ("document", "old", "replacement", "failed_boundary"),
    (
        (
            "protocol",
            "The 95% intervals use",
            "Intervals use",
            "frozen_95_percent_intervals",
        ),
        (
            "protocol",
            "Exact two-sided McNemar inference",
            "A paired numerical sensitivity",
            "frozen_exact_two_sided_mcnemar",
        ),
        (
            "protocol",
            "divergence localization",
            "diagnostics",
            "frozen_stress_localization_timing_promise",
        ),
        (
            "manuscript",
            "post-acquisition additions",
            "conservative additions",
            "completed_case_taxonomy_is_post_acquisition",
        ),
        (
            "manuscript",
            "audit was retrospective",
            "audit was run",
            "historical_audit_is_retrospective_not_blinding",
        ),
        (
            "manuscript",
            "a later integrity extension",
            "an integrity comparison",
            "digest_byte_is_later_extension_without_count_change",
        ),
        (
            "manuscript",
            "omitted and unverifiable",
            "not included",
            "stress_omission_is_reporting_deviation",
        ),
    ),
)
def test_each_required_provenance_boundary_fails_closed_when_mutated(
    audit_module,
    document: str,
    old: str,
    replacement: str,
    failed_boundary: str,
) -> None:
    protocol = PROTOCOL
    manuscript = MANUSCRIPT
    if document == "protocol":
        assert old in protocol
        protocol = protocol.replace(old, replacement, 1)
    else:
        assert old in manuscript
        manuscript = manuscript.replace(old, replacement, 1)

    state = audit_module.provenance_semantics_state(protocol, manuscript)
    assert state[failed_boundary] is False


@pytest.mark.parametrize(
    ("phrase", "expected_hit"),
    (
        (
            "This is a prospectively frozen claim map.",
            "prospectively_frozen_claim_map",
        ),
        (
            "Under the frozen rule this admitted a fixed-battery descriptive contrast.",
            "frozen_rule_admitted_descriptive",
        ),
        (
            "Stage~8 executes the frozen admission map shown below.",
            "stage_8_executes_frozen_map",
        ),
    ),
)
def test_each_known_false_frozen_phrase_fails_closed(
    audit_module,
    phrase: str,
    expected_hit: str,
) -> None:
    state = audit_module.provenance_semantics_state(PROTOCOL, f"{MANUSCRIPT}\n{phrase}\n")
    assert state["prohibited_phrase_hits"] == [expected_hit]


def test_latex_comment_cannot_satisfy_missing_disclosure(audit_module) -> None:
    manuscript = MANUSCRIPT.replace(
        "The frozen historical audit was retrospective: outcome records already existed\n"
        "before it ran, so it is not evidence of prospective blinding.",
        "% The frozen historical audit was retrospective: outcome records already existed "
        "and is not evidence of prospective blinding.",
        1,
    )
    state = audit_module.provenance_semantics_state(PROTOCOL, manuscript)
    assert state["historical_audit_is_retrospective_not_blinding"] is False


def test_file_bound_audit_routes_missing_boundary_to_contradiction(
    audit_module,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper = tmp_path / "paper"
    final = paper / "final_protocol"
    protocol_path = paper / "protocol/PEVL_PROSPECTIVE_PROTOCOL.md"
    manuscript_path = final / "main.tex"
    protocol_path.parent.mkdir(parents=True)
    manuscript_path.parent.mkdir(parents=True)
    protocol_path.write_text(PROTOCOL, encoding="utf-8")
    manuscript_path.write_text(MANUSCRIPT, encoding="utf-8")
    monkeypatch.setattr(audit_module, "PAPER", paper)
    monkeypatch.setattr(audit_module, "FINAL", final)

    passing = audit_module.Audit()
    audit_module.check_protocol_reporting_provenance(passing)
    assert passing.contradictions == []
    assert len(passing.checks) == 8

    manuscript_path.write_text(
        MANUSCRIPT.replace("omitted and unverifiable", "not included", 1),
        encoding="utf-8",
    )
    failing = audit_module.Audit()
    audit_module.check_protocol_reporting_provenance(failing)
    assert [item["check_id"] for item in failing.contradictions] == [
        "PROVENANCE-STRESS-REPORTING-DEVIATION"
    ]

"""Fail-closed tests for the research-audit verifier."""

from __future__ import annotations

import csv
import importlib.util
import shutil
from pathlib import Path

import pytest


FINAL = Path(__file__).resolve().parents[1]
SCRIPT = FINAL / "scripts/verify_research_audits.py"
AUDIT_FILES = (
    "APS_DESK_FIT.md",
    "HUMAN_ACTIONS.md",
    "NOVELTY_AUDIT.md",
    "NOVELTY_MATRIX.csv",
    "NOVELTY_SEARCH_LOG.json",
    "REFERENCE_AUDIT.csv",
    "TITLE_COLLISION_AUDIT.md",
    "main.tex",
    "references.bib",
    "release/RELEASE_STATUS.json",
    "supplement/RIGHTS_AND_ACCESS_AUDIT.md",
)


@pytest.fixture(scope="module")
def verifier_module():
    spec = importlib.util.spec_from_file_location("verify_research_audits", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copied_audits(tmp_path: Path) -> Path:
    for relative in AUDIT_FILES:
        source = FINAL / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return tmp_path


def test_current_research_audits_pass(verifier_module) -> None:
    report = verifier_module.verify(FINAL)
    assert report["status"] == "PASS"
    assert report["failures"] == []
    assert [check["status"] for check in report["checks"]] == ["PASS"] * 4


def test_strict_json_rejects_duplicate_keys(verifier_module, tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text('{"result": "PASS", "result": "PASS"}\n', encoding="utf-8")
    with pytest.raises(verifier_module.AuditFailure, match="duplicate JSON key"):
        verifier_module.load_json_strict(path)


def test_unverified_cited_reference_fails_closed(verifier_module, tmp_path: Path) -> None:
    final = copied_audits(tmp_path)
    path = final / "REFERENCE_AUDIT.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fields = list(rows[0])
    rows[0]["verified"] = "FALSE"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    report = verifier_module.verify(final)
    assert report["status"] == "FAIL"
    assert any("not strictly verified TRUE" in failure for failure in report["failures"])


def test_missing_exact_support_sentence_fails_closed(verifier_module, tmp_path: Path) -> None:
    final = copied_audits(tmp_path)
    path = final / "REFERENCE_AUDIT.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fields = list(rows[0])
    rows[0]["exact_manuscript_sentence_supported"] = "This unsupported sentence is absent."
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    report = verifier_module.verify(final)
    assert report["status"] == "FAIL"
    assert any("support sentence is absent" in failure for failure in report["failures"])


def test_ready_decision_conflicts_with_unresolved_rights(verifier_module, tmp_path: Path) -> None:
    final = copied_audits(tmp_path)
    path = final / "APS_DESK_FIT.md"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("NOT READY — DO NOT SUBMIT", "READY FOR SUBMISSION", 1), encoding="utf-8")
    report = verifier_module.verify(final)
    assert report["status"] == "FAIL"
    assert any("APS desk decision" in failure for failure in report["failures"])

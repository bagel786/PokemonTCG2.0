from __future__ import annotations

from pathlib import Path

import pytest

from resource_envelope_study.canonical import hash_json
from resource_envelope_study.period_journal import (
    atomic_write_new,
    build_period_journal,
    discover_period_journals,
    period_journal_path,
    validate_period_journal_common,
)


def _fixture() -> tuple[list[dict], list[dict], dict]:
    rows = [{"case_id": "case-1"}, {"case_id": "case-2"}]
    results = [
        {"case_id": row["case_id"], "artifact_sha256": hash_json(row)}
        for row in rows
    ]
    episode = {
        "load_batch_id": "batch-1",
        "metadata_hash": hash_json({"episode": 1}),
    }
    return rows, results, episode


def test_period_journal_is_immutable_canonical_and_discoverable(tmp_path: Path) -> None:
    rows, results, episode = _fixture()
    manifest_hash = "a" * 64
    journal = build_period_journal(
        experiment="pokemon",
        manifest_content_hash=manifest_hash,
        phase="pilot",
        load_batch_id="batch-1",
        load_condition="idle",
        period_rows=rows,
        case_results=results,
        resource_episode=episode,
    )
    validate_period_journal_common(
        journal,
        experiment="pokemon",
        manifest_content_hash=manifest_hash,
        phase="pilot",
        load_batch_id="batch-1",
        load_condition="idle",
        period_case_ids=["case-1", "case-2"],
    )
    path = period_journal_path(tmp_path, "batch-1", "idle")
    atomic_write_new(path, journal)
    found = discover_period_journals(tmp_path)
    assert found == [(path, journal)]
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        atomic_write_new(path, journal)


def test_period_journal_rejects_tampering_and_unsafe_paths(tmp_path: Path) -> None:
    rows, results, episode = _fixture()
    journal = build_period_journal(
        experiment="ising",
        manifest_content_hash="b" * 64,
        phase="final",
        load_batch_id="batch-1",
        load_condition="loaded",
        period_rows=rows,
        case_results=results,
        resource_episode=episode,
    )
    journal["case_results"][0]["artifact_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="content hash mismatch"):
        validate_period_journal_common(
            journal,
            experiment="ising",
            manifest_content_hash="b" * 64,
            phase="final",
            load_batch_id="batch-1",
            load_condition="loaded",
            period_case_ids=["case-1", "case-2"],
        )
    with pytest.raises(ValueError, match="unsafe"):
        period_journal_path(tmp_path, "../escape", "idle")

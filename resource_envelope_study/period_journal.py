"""Crash-durable evidence for one completed half of a paired load batch."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from .canonical import canonical_json_bytes, hash_json


PERIOD_JOURNAL_SCHEMA_VERSION = "load-period-journal-1.0.0"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


def period_journal_path(
    output_dir: str | Path, batch_id: str, load_condition: str
) -> Path:
    if _SAFE_ID.fullmatch(batch_id) is None:
        raise ValueError("load-batch ID is unsafe for a period-journal path")
    if load_condition not in {"idle", "loaded"}:
        raise ValueError("period journal requires idle or loaded condition")
    return (
        Path(output_dir).resolve()
        / "period_journals"
        / batch_id
        / f"{load_condition}.json"
    )


def build_period_journal(
    *,
    experiment: str,
    manifest_content_hash: str,
    phase: str,
    load_batch_id: str,
    load_condition: str,
    period_rows: Sequence[Mapping[str, Any]],
    case_results: Sequence[Mapping[str, Any]],
    resource_episode: Mapping[str, Any],
) -> dict[str, Any]:
    journal: dict[str, Any] = {
        "schema_version": PERIOD_JOURNAL_SCHEMA_VERSION,
        "experiment": str(experiment),
        "manifest_content_hash": str(manifest_content_hash),
        "phase": str(phase),
        "load_batch_id": str(load_batch_id),
        "load_condition": str(load_condition),
        "period_case_ids": [str(row["case_id"]) for row in period_rows],
        "case_result_hashes": [
            str(result["artifact_sha256"]) for result in case_results
        ],
        "resource_episode_hash": str(resource_episode["metadata_hash"]),
        "case_results": [dict(result) for result in case_results],
        "resource_episode": dict(resource_episode),
        "terminal_status": "period_complete",
    }
    journal["content_hash"] = hash_json(journal)
    return journal


def validate_period_journal_common(
    journal: Mapping[str, Any],
    *,
    experiment: str,
    manifest_content_hash: str,
    phase: str,
    load_batch_id: str,
    load_condition: str,
    period_case_ids: Sequence[str],
) -> None:
    required = {
        "schema_version",
        "experiment",
        "manifest_content_hash",
        "phase",
        "load_batch_id",
        "load_condition",
        "period_case_ids",
        "case_result_hashes",
        "resource_episode_hash",
        "case_results",
        "resource_episode",
        "terminal_status",
        "content_hash",
    }
    if not isinstance(journal, Mapping) or set(journal) != required:
        raise ValueError("period journal has unexpected fields")
    expected = {
        "schema_version": PERIOD_JOURNAL_SCHEMA_VERSION,
        "experiment": experiment,
        "manifest_content_hash": manifest_content_hash,
        "phase": phase,
        "load_batch_id": load_batch_id,
        "load_condition": load_condition,
        "period_case_ids": list(period_case_ids),
        "terminal_status": "period_complete",
    }
    mismatches = [key for key, value in expected.items() if journal.get(key) != value]
    if mismatches:
        raise ValueError(f"period journal identity mismatch: {sorted(mismatches)}")
    payload = dict(journal)
    supplied_hash = payload.pop("content_hash")
    if supplied_hash != hash_json(payload):
        raise ValueError("period journal content hash mismatch")
    results = journal.get("case_results")
    if not isinstance(results, list) or len(results) != len(period_case_ids):
        raise ValueError("period journal result cardinality mismatch")
    result_hashes = [result.get("artifact_sha256") for result in results]
    if journal.get("case_result_hashes") != result_hashes:
        raise ValueError("period journal result hashes do not reconcile")
    episode = journal.get("resource_episode")
    if not isinstance(episode, Mapping):
        raise ValueError("period journal lacks a resource episode")
    if journal.get("resource_episode_hash") != episode.get("metadata_hash"):
        raise ValueError("period journal resource-episode hash does not reconcile")


def atomic_write_new(path: str | Path, value: Mapping[str, Any]) -> None:
    """Publish one immutable journal with file and directory durability."""

    destination = Path(path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite period journal {destination}")
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    if temporary.exists():
        raise FileExistsError(f"stale period-journal temporary exists: {temporary}")
    try:
        with temporary.open("xb") as handle:
            handle.write(canonical_json_bytes(dict(value)))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        # Preserve an already-published destination.  Only the private
        # temporary is safe to discard.
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def load_period_journal(path: str | Path) -> dict[str, Any]:
    source = Path(path).resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read period journal {source}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"period journal is not an object: {source}")
    if source.read_bytes() != canonical_json_bytes(value):
        raise ValueError(f"period journal is not canonical JSON: {source}")
    return value


def discover_period_journals(output_dir: str | Path) -> list[tuple[Path, dict[str, Any]]]:
    root = Path(output_dir).resolve() / "period_journals"
    if not root.exists():
        return []
    unexpected = sorted(
        path for path in root.rglob("*") if path.is_file() and path.suffix != ".json"
    )
    if unexpected:
        raise RuntimeError(
            f"unexpected files in period-journal evidence: {[str(path) for path in unexpected]}"
        )
    return [(path, load_period_journal(path)) for path in sorted(root.rglob("*.json"))]

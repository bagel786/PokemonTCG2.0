#!/usr/bin/env python3
"""Build the episode-atomic, floor-focused d842 correction corpus.

Only independently repeat-certified development corrections are accepted.  A
whole episode is retained when the historical result was a loss or the agent
actually went second.  The semantic disagreement bank is used solely to
verify provenance and derive public action-family/aggregate matchup coverage;
its opponent metadata is never copied into a training row.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.analyze_d842_floor_failures import action_family as disagreement_action_family
from scripts.build_grim_policy_disagreements import semantic_action
from scripts.intersect_complete_turn_corrections import (
    CERTIFICATION_WORLDS,
    FROZEN_D842_MODEL_SHA256,
    FROZEN_GRIM_DECK_CANONICAL_SHA256,
    canonical_json,
    decision_coordinate,
    expected_decision_id,
    expected_record_id,
    sha256_file,
    stable_json_id,
    validate_row as validate_correction_row,
)
DEFAULT_INTERSECTION = (
    ROOT / "artifacts" / "grim_complete_turn_corrections" / "development_intersection.jsonl.gz"
)
DEFAULT_DISAGREEMENTS = (
    ROOT / "artifacts" / "grim_policy_disagreements" / "disagreements.jsonl.gz"
)
DEFAULT_OUTPUT = (
    ROOT / "artifacts" / "grim_complete_turn_corrections" / "floor_development.jsonl.gz"
)

FROZEN_ARCHIVE_SHA256 = "3ECB0BBF119E23C31905E39E19ECA8F6145104AAEFFC0A5675D2FE03855BB458"
DEVELOPMENT_SPLIT = "development"
PROTECTED_PATH_PARTS = ("calibration", "holdout", "sealed")

# These names are intentionally public-policy concepts rather than card/deck
# identities.  ``attack_over_end`` is an attack/target decision for coverage.
REQUIRED_ACTION_FAMILIES = (
    "conversion_recovery",
    "setup_bench",
    "energy",
    "attack_target",
    "prize_counters",
    "retreat",
)
ACTION_FAMILY_MAP = {
    "conversion_or_recovery": "conversion_recovery",
    "setup_or_bench": "setup_bench",
    "energy_allocation": "energy",
    "attack_or_target": "attack_target",
    "attack_over_end": "attack_target",
    "prize_targeting_or_counters": "prize_counters",
    "promotion_or_retreat": "retreat",
}
DEFAULT_FAMILY_MINIMA = {family: 1 for family in REQUIRED_ACTION_FAMILIES}


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdefABCDEF" for character in text)


def _protected_path(path: str | Path, *, label: str) -> Path:
    resolved = Path(path).resolve()
    folded = str(resolved).casefold()
    if any(part in folded for part in PROTECTED_PATH_PARTS):
        raise ValueError(f"refusing calibration/sealed/holdout {label}: {resolved}")
    return resolved


def _declared_path(value: Any, manifest_path: Path) -> Path:
    declared = Path(str(value or ""))
    if not declared.is_absolute():
        declared = manifest_path.parent / declared
    return declared.resolve()


def intersection_manifest_path(path: str | Path) -> Path:
    return Path(path).with_suffix(".manifest.json")


def disagreement_manifest_path(path: str | Path) -> Path:
    return Path(path).with_name("manifest.json")


def _read_manifest(path: str | Path, *, label: str) -> tuple[Path, dict, str]:
    resolved = _protected_path(path, label=label)
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {label}: {resolved}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain one JSON object: {resolved}")
    return resolved, value, sha256_file(resolved)


def _validate_intersection_manifest(
    corpus: Path,
    manifest_path: Path,
    manifest: Mapping[str, Any],
    corpus_sha256: str,
    disagreement_sha256: str,
) -> Mapping[str, Any]:
    provenance = manifest.get("provenance")
    counts = manifest.get("counts")
    inputs = manifest.get("inputs")
    if not isinstance(provenance, dict) or not isinstance(counts, dict) or not isinstance(inputs, list):
        raise ValueError("intersection manifest is missing provenance/count/input records")
    splits = provenance.get("splits")
    config = provenance.get("config")
    input_rows = counts.get("input_rows")
    retained_count = int(counts.get("retained_corrections", -1))
    dropped_count = int(counts.get("dropped_correction_records", -1))
    union_count = int(counts.get("union_correction_records", -1))
    if (
        int(manifest.get("schema_version", 0)) != 1
        or manifest.get("status") != "complete"
        or manifest.get("passed") is not True
        or manifest.get("source") != "exact_multi_pass_complete_turn_intersection"
        or manifest.get("sealed_holdout_used") is not False
        or _declared_path(manifest.get("output"), manifest_path) != corpus
        or str(manifest.get("output_sha256") or "").upper() != corpus_sha256
        or splits != [DEVELOPMENT_SPLIT]
        or not isinstance(config, dict)
        or int(config.get("worlds", 0)) != CERTIFICATION_WORLDS
        or int(provenance.get("certification_repeats", 0)) < 3
        or str(provenance.get("model_sha256") or "").upper() != FROZEN_D842_MODEL_SHA256
        or str(provenance.get("hero_deck_canonical_sha256") or "").upper()
        != FROZEN_GRIM_DECK_CANONICAL_SHA256
        or not _is_sha256(provenance.get("model_behavior_sha256"))
        or str(provenance.get("source_input_sha256") or "").upper() != disagreement_sha256
        or int(counts.get("input_passes", 0)) < 2
        or len(inputs) != int(counts.get("input_passes", -1))
        or not isinstance(input_rows, list)
        or len(input_rows) != len(inputs)
        or retained_count < 0
        or dropped_count < 0
        or retained_count + dropped_count != union_count
    ):
        raise ValueError("intersection manifest failed hash/split/model/deck provenance checks")
    distinct_inputs: set[str] = set()
    for index, item in enumerate(inputs):
        if (
            not isinstance(item, dict)
            or not str(item.get("file") or "").strip()
            or not str(item.get("manifest") or "").strip()
            or not _is_sha256(item.get("sha256"))
            or not _is_sha256(item.get("manifest_sha256"))
            or int(item.get("rows", -1)) < 0
            or int(item.get("rows", -1)) != int(input_rows[index])
        ):
            raise ValueError("intersection manifest contains an invalid independent-pass record")
        pass_path = _protected_path(item.get("file", ""), label="intersection source pass")
        _protected_path(item.get("manifest", ""), label="intersection source-pass manifest")
        distinct_inputs.add(str(pass_path).casefold())
    if len(distinct_inputs) != len(inputs):
        raise ValueError("intersection manifest does not name distinct independent passes")
    return provenance


def _validate_disagreement_manifest(
    bank: Path,
    manifest_path: Path,
    manifest: Mapping[str, Any],
    bank_sha256: str,
) -> frozenset[str]:
    baseline = manifest.get("baseline")
    rows_by_split = manifest.get("rows_by_split")
    candidates = manifest.get("candidates")
    if (
        not isinstance(baseline, dict)
        or not isinstance(rows_by_split, dict)
        or not isinstance(candidates, list)
    ):
        raise ValueError("semantic disagreement manifest is missing policy/split provenance")
    try:
        split_counts = {str(key): int(value) for key, value in rows_by_split.items()}
    except (TypeError, ValueError) as exc:
        raise ValueError("semantic disagreement manifest has invalid split counts") from exc
    if (
        int(manifest.get("schema_version", 0)) != 1
        or manifest.get("status") != "complete"
        or manifest.get("holdout_read") is not False
        or manifest.get("native_search_executed") is not False
        or manifest.get("alignment") != "observation_t_to_same_seat_action_t_plus_1"
        or manifest.get("strict_historical") is not True
        or manifest.get("strict_historical_criterion")
        != "semantic_action_identity_not_temporary_option_index"
        or set(map(str, manifest.get("allowed_input_splits") or []))
        != {DEVELOPMENT_SPLIT, "calibration"}
        or _declared_path(manifest.get("output_file"), manifest_path) != bank
        or str(manifest.get("output_sha256") or "").upper() != bank_sha256
        or str(baseline.get("model_sha256") or "").upper() != FROZEN_D842_MODEL_SHA256
        or str(baseline.get("deck_canonical_sha256") or "").upper()
        != FROZEN_GRIM_DECK_CANONICAL_SHA256
        or str(baseline.get("reference_archive_sha256") or "").upper()
        != FROZEN_ARCHIVE_SHA256
        or baseline.get("native_search_executed") not in {None, False}
        or set(split_counts) - {DEVELOPMENT_SPLIT, "calibration"}
        or any(value < 0 for value in split_counts.values())
        or int(split_counts.get(DEVELOPMENT_SPLIT, 0)) <= 0
        or int(manifest.get("disagreement_rows", -1)) != sum(split_counts.values())
        or int(manifest.get("historical_semantic_agreement", -1))
        != int(manifest.get("decisions", -2))
    ):
        raise ValueError("semantic disagreement manifest failed hash/alignment/model/deck checks")
    candidate_names: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("semantic disagreement manifest has invalid candidate provenance")
        name = str(candidate.get("name") or "")
        if (
            not name
            or name in candidate_names
            or str(candidate.get("deck_canonical_sha256") or "").upper()
            != FROZEN_GRIM_DECK_CANONICAL_SHA256
            or candidate.get("native_search_executed") is not False
        ):
            raise ValueError("semantic disagreement manifest has invalid candidate provenance")
        candidate_names.add(name)
    if not candidate_names:
        raise ValueError("semantic disagreement manifest has no proposer policies")
    return frozenset(candidate_names)


def _canonical_gzip_rows(path: Path):
    try:
        with gzip.open(path, "rb") as handle:
            for line_number, raw in enumerate(handle, 1):
                if not raw.strip():
                    raise ValueError(f"{path}:{line_number}: blank rows are forbidden")
                try:
                    row = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError(f"{path}:{line_number}: invalid JSON row") from exc
                if not isinstance(row, dict):
                    raise ValueError(f"{path}:{line_number}: expected an object")
                # The existing miner/intersection writer uses TextIOWrapper;
                # on Windows its otherwise canonical records end in CRLF.
                # Accept either newline convention, while requiring the JSON
                # payload itself to be byte-canonical, and retain the original
                # record bytes for the training-output subset.
                newline = b"\r\n" if raw.endswith(b"\r\n") else b"\n" if raw.endswith(b"\n") else b""
                canonical = canonical_json(row).encode("utf-8")
                if not newline or raw[: -len(newline)] != canonical:
                    raise ValueError(f"{path}:{line_number}: row is not byte-canonical JSON")
                yield line_number, row, raw
    except (OSError, EOFError) as exc:
        raise ValueError(f"cannot read gzip corpus {path}") from exc


@dataclass(frozen=True)
class CertifiedRow:
    row: dict
    canonical_line: bytes


def _correction_validation_manifest(provenance: Mapping[str, Any]) -> dict:
    return {
        "config": provenance["config"],
        "certification_repeats": provenance["certification_repeats"],
        "model_sha256": provenance["model_sha256"],
        "model_behavior_sha256": provenance["model_behavior_sha256"],
    }


def _load_corrections(
    corpus: Path,
    manifest: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> list[CertifiedRow]:
    validation_manifest = _correction_validation_manifest(provenance)
    rows: list[CertifiedRow] = []
    record_ids: set[str] = set()
    decisions: dict[tuple[str, int, int], str] = {}
    previous_record_id: str | None = None
    for line_number, row, canonical_line in _canonical_gzip_rows(corpus):
        validate_correction_row(row, validation_manifest)
        if row.get("split") != DEVELOPMENT_SPLIT:
            raise ValueError(f"{corpus}:{line_number}: refusing non-development correction")
        record_id = str(row["correction_record_id"]).upper()
        coordinate = decision_coordinate(row)
        if record_id in record_ids:
            raise ValueError(f"duplicate correction_record_id: {record_id}")
        if coordinate in decisions:
            raise ValueError(f"multiple certified labels for one decision: {coordinate}")
        if previous_record_id is not None and record_id <= previous_record_id:
            raise ValueError("intersection corrections are not in canonical record-id order")
        if str(row.get("team")) != "Larps":
            raise ValueError(f"unexpected correction team provenance for {record_id}")
        record_ids.add(record_id)
        decisions[coordinate] = record_id
        previous_record_id = record_id
        rows.append(CertifiedRow(row=row, canonical_line=canonical_line))
    counts = manifest["counts"]
    coverage = manifest.get("coverage") or {}
    if (
        len(rows) != int(counts.get("retained_corrections", -1))
        or len(rows) != int(coverage.get("decision_boundaries", -1))
        or len({str(item.row["episode_id"]) for item in rows})
        != int(coverage.get("episodes", -1))
    ):
        raise ValueError("intersection row count/episode coverage does not match its manifest")
    declared_order = {str(key): int(value) for key, value in (coverage.get("by_actual_order") or {}).items()}
    actual_order = Counter(str(item.row["actual_order"]) for item in rows)
    declared_proposers = {str(key): int(value) for key, value in (coverage.get("by_proposer") or {}).items()}
    actual_proposers = Counter(
        proposer for item in rows for proposer in sorted(set(map(str, item.row["proposers"])))
    )
    if declared_order != dict(sorted(actual_order.items())) or declared_proposers != dict(
        sorted(actual_proposers.items())
    ):
        raise ValueError("intersection order/proposer coverage does not match its manifest")
    return rows


def _require_int_action(value: Any, *, label: str) -> list[int]:
    if not isinstance(value, list) or any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        raise ValueError(f"{label} must be list[int]")
    if len(value) != len(set(value)) or any(item < 0 for item in value):
        raise ValueError(f"{label} contains duplicate or negative option indices")
    return value


def _validate_disagreement_row(row: dict, *, line_number: int, path: Path) -> None:
    required = (
        "record_id",
        "split",
        "episode_id",
        "hero_seat",
        "replay_step_t",
        "historical_action_step_t_plus_1",
        "actual_first_player",
        "actual_order",
        "outcome",
        "target",
        "observation",
        "observation_sha256",
        "features",
        "historical_action",
        "historical_semantic",
        "baseline_action",
        "baseline_semantic",
        "baseline_semantic_id",
        "candidate_action",
        "candidate_semantic",
        "candidate_semantic_id",
        "proposers",
        "proposer_actions",
        "semantic_pair_id",
        "semantic_action_pair_id",
    )
    missing = [key for key in required if row.get(key) is None]
    if missing:
        raise ValueError(f"{path}:{line_number}: disagreement row is missing {','.join(missing)}")
    current = row["observation"].get("current") if isinstance(row["observation"], dict) else None
    if not isinstance(current, dict):
        raise ValueError(f"{path}:{line_number}: observation has no public current state")
    hero_seat = int(row.get("hero_seat", -1))
    actual_first_player = int(row.get("actual_first_player", -1))
    expected_order = "first" if actual_first_player == hero_seat else "second"
    if (
        int(row.get("schema_version", 0)) != 1
        or row.get("record_type") != "semantic_disagreement"
        or row.get("split") != DEVELOPMENT_SPLIT
        or str(row.get("actual_order")) not in {"first", "second"}
        or str(row.get("outcome")) not in {"win", "loss"}
        or int(row.get("target", -1)) != int(row.get("outcome") == "win")
        or hero_seat not in {0, 1}
        or actual_first_player not in {0, 1}
        or int(current.get("yourIndex", -1)) != hero_seat
        or int(current.get("firstPlayer", -1)) != actual_first_player
        or str(row.get("actual_order")) != expected_order
        or int(row.get("historical_action_step_t_plus_1", -1))
        != int(row.get("replay_step_t", -2)) + 1
        or row.get("historical_semantically_agrees_with_baseline") is not True
        or row.get("historical_semantic") != row.get("baseline_semantic")
    ):
        raise ValueError(f"{path}:{line_number}: invalid development disagreement provenance")

    observation = row["observation"]
    observation_id = stable_json_id(observation)
    baseline_id = stable_json_id(row["baseline_semantic"])
    candidate_id = stable_json_id(row["candidate_semantic"])
    expected_pair = stable_json_id(
        {
            "observation_sha256": observation_id,
            "baseline_semantic_id": baseline_id,
            "candidate_semantic_id": candidate_id,
        }
    )
    expected_action_pair = stable_json_id(
        {"baseline": row["baseline_semantic"], "candidate": row["candidate_semantic"]}
    )
    expected_record = stable_json_id(
        {
            "split": DEVELOPMENT_SPLIT,
            "episode_id": str(row["episode_id"]),
            "hero_seat": int(row["hero_seat"]),
            "replay_step_t": int(row["replay_step_t"]),
            "semantic_pair_id": expected_pair,
        }
    )
    if (
        str(row["observation_sha256"]).upper() != observation_id
        or str(row["baseline_semantic_id"]).upper() != baseline_id
        or str(row["candidate_semantic_id"]).upper() != candidate_id
        or str(row["semantic_pair_id"]).upper() != expected_pair
        or str(row["semantic_action_pair_id"]).upper() != expected_action_pair
        or str(row["record_id"]).upper() != expected_record
    ):
        raise ValueError(f"{path}:{line_number}: disagreement row identity mismatch")

    baseline_action = _require_int_action(row["baseline_action"], label="baseline_action")
    candidate_action = _require_int_action(row["candidate_action"], label="candidate_action")
    historical_action = _require_int_action(row["historical_action"], label="historical_action")
    try:
        if semantic_action(observation, baseline_action) != row["baseline_semantic"]:
            raise ValueError("baseline action semantic mismatch")
        if semantic_action(observation, candidate_action) != row["candidate_semantic"]:
            raise ValueError("candidate action semantic mismatch")
        if semantic_action(observation, historical_action) != row["historical_semantic"]:
            raise ValueError("historical action semantic mismatch")
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{path}:{line_number}: action/semantic provenance mismatch") from exc

    proposers = list(map(str, row["proposers"]))
    proposer_actions = row["proposer_actions"]
    if (
        not proposers
        or proposers != sorted(set(proposers))
        or not isinstance(proposer_actions, dict)
        or sorted(map(str, proposer_actions)) != proposers
    ):
        raise ValueError(f"{path}:{line_number}: non-canonical proposer provenance")
    for proposer in proposers:
        action = _require_int_action(proposer_actions[proposer], label=f"proposer_actions.{proposer}")
        try:
            candidate_matches = semantic_action(observation, action) == row["candidate_semantic"]
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{path}:{line_number}: invalid proposer action provenance") from exc
        if not candidate_matches:
            raise ValueError(f"{path}:{line_number}: proposer semantic provenance mismatch")


def _load_disagreement_matches(
    bank: Path,
    manifest: Mapping[str, Any],
    correction_ids: set[str],
    allowed_proposers: frozenset[str],
) -> dict[str, dict]:
    matches: dict[str, dict] = {}
    seen_development_ids: set[str] = set()
    split_counts: Counter[str] = Counter()
    all_episode_ids: set[str] = set()
    for line_number, row, _canonical_line in _canonical_gzip_rows(bank):
        split = str(row.get("split") or "")
        if split not in {DEVELOPMENT_SPLIT, "calibration"}:
            raise ValueError(f"{bank}:{line_number}: refusing unknown/sealed split {split!r}")
        split_counts[split] += 1
        if row.get("episode_id") is not None:
            all_episode_ids.add(str(row["episode_id"]))
        if split != DEVELOPMENT_SPLIT:
            # Calibration rows are intentionally neither validated semantically
            # nor retained.  The containing file hash/count is checked only to
            # authenticate the development records against their source bank.
            continue
        _validate_disagreement_row(row, line_number=line_number, path=bank)
        if not set(map(str, row["proposers"])) <= allowed_proposers:
            raise ValueError(f"{bank}:{line_number}: proposer is absent from manifest provenance")
        record_id = str(row["record_id"]).upper()
        if record_id in seen_development_ids:
            raise ValueError(f"duplicate development disagreement record_id: {record_id}")
        seen_development_ids.add(record_id)
        if record_id in correction_ids:
            matches[record_id] = row

    declared_counts = {str(key): int(value) for key, value in manifest["rows_by_split"].items()}
    if dict(sorted(split_counts.items())) != dict(sorted(declared_counts.items())):
        raise ValueError("semantic disagreement row counts do not match its manifest")
    if len(all_episode_ids) != int(manifest.get("episodes", -1)):
        raise ValueError("semantic disagreement episode count does not match its manifest")
    missing = sorted(correction_ids - matches.keys())
    if missing:
        raise ValueError(f"certified corrections are absent from development disagreement bank: {missing[0]}")
    return matches


def _validate_join(correction: Mapping[str, Any], disagreement: Mapping[str, Any]) -> None:
    record_id = str(correction["correction_record_id"]).upper()
    exact_pairs = (
        ("episode_id", "episode_id"),
        ("seat", "hero_seat"),
        ("step", "replay_step_t"),
        ("actual_order", "actual_order"),
        ("semantic_pair_id", "semantic_pair_id"),
        ("semantic_action_pair_id", "semantic_action_pair_id"),
        ("candidate_semantic_id", "candidate_semantic_id"),
        ("baseline_semantic_id", "baseline_semantic_id"),
        ("proposers", "proposers"),
        ("action", "candidate_action"),
        ("features", "features"),
        ("observation", "observation"),
    )
    for correction_key, disagreement_key in exact_pairs:
        if correction.get(correction_key) != disagreement.get(disagreement_key):
            raise ValueError(
                f"correction/disagreement provenance mismatch for {record_id}: {correction_key}"
            )
    if record_id != str(disagreement.get("record_id") or "").upper():
        raise ValueError(f"correction/disagreement record identity mismatch for {record_id}")
    if str(correction.get("decision_id") or "").upper() != expected_decision_id(correction):
        raise ValueError(f"correction decision identity mismatch for {record_id}")
    if record_id != expected_record_id(correction):
        raise ValueError(f"correction record identity mismatch for {record_id}")
    if float(correction.get("reward")) != float(disagreement.get("target")):
        raise ValueError(f"correction/disagreement reward mismatch for {record_id}")


def public_action_family(disagreement: Mapping[str, Any]) -> tuple[str, str]:
    raw_family = disagreement_action_family(disagreement)
    return ACTION_FAMILY_MAP.get(raw_family, "other"), raw_family


def _normalize_family_minima(minima: Mapping[str, int] | None) -> dict[str, int]:
    result = dict(DEFAULT_FAMILY_MINIMA)
    for family, value in (minima or {}).items():
        if family not in REQUIRED_ACTION_FAMILIES:
            raise ValueError(f"unknown required action family: {family!r}")
        count = int(value)
        if count < 0:
            raise ValueError(f"negative action-family minimum for {family}")
        result[family] = count
    return result


class CoverageGateError(ValueError):
    def __init__(self, report: Mapping[str, Any]):
        self.report = dict(report)
        failed = ", ".join(self.report.get("failed_gates") or ["unknown"])
        super().__init__(f"floor correction corpus failed coverage gates: {failed}")


def _atomic_write_output(path: Path, rows: Sequence[CertifiedRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with temporary.open("wb") as raw:
            with gzip.GzipFile(
                filename="", mode="wb", fileobj=raw, compresslevel=6, mtime=0
            ) as compressed:
                for item in rows:
                    compressed.write(item.canonical_line)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def run(
    intersection: str | Path,
    disagreements: str | Path,
    output: str | Path,
    *,
    intersection_manifest: str | Path | None = None,
    disagreements_manifest: str | Path | None = None,
    minimum_corrections: int = 250,
    minimum_episodes: int = 30,
    family_minima: Mapping[str, int] | None = None,
) -> dict:
    if int(minimum_corrections) < 0 or int(minimum_episodes) < 0:
        raise ValueError("correction and episode minima must be nonnegative")
    normalized_minima = _normalize_family_minima(family_minima)
    intersection_path = _protected_path(intersection, label="intersection corpus")
    disagreement_path = _protected_path(disagreements, label="semantic disagreement bank")
    output_path = _protected_path(output, label="floor correction output")
    if not intersection_path.is_file() or not disagreement_path.is_file():
        missing = intersection_path if not intersection_path.is_file() else disagreement_path
        raise FileNotFoundError(missing)
    if output_path in {intersection_path, disagreement_path}:
        raise ValueError("floor corpus output must not overwrite either input")

    intersection_manifest_arg = intersection_manifest or intersection_manifest_path(intersection_path)
    disagreements_manifest_arg = disagreements_manifest or disagreement_manifest_path(disagreement_path)
    intersection_manifest_path_value, intersection_manifest_value, intersection_manifest_sha = _read_manifest(
        intersection_manifest_arg, label="intersection manifest"
    )
    disagreement_manifest_path_value, disagreement_manifest_value, disagreement_manifest_sha = _read_manifest(
        disagreements_manifest_arg, label="semantic disagreement manifest"
    )
    intersection_sha = sha256_file(intersection_path)
    disagreement_sha = sha256_file(disagreement_path)
    allowed_proposers = _validate_disagreement_manifest(
        disagreement_path,
        disagreement_manifest_path_value,
        disagreement_manifest_value,
        disagreement_sha,
    )
    provenance = _validate_intersection_manifest(
        intersection_path,
        intersection_manifest_path_value,
        intersection_manifest_value,
        intersection_sha,
        disagreement_sha,
    )

    certified = _load_corrections(intersection_path, intersection_manifest_value, provenance)
    correction_ids = {str(item.row["correction_record_id"]).upper() for item in certified}
    disagreement_rows = _load_disagreement_matches(
        disagreement_path, disagreement_manifest_value, correction_ids, allowed_proposers
    )

    grouped: dict[str, list[CertifiedRow]] = defaultdict(list)
    episode_facts: dict[str, tuple[int, str, str, str]] = {}
    for item in certified:
        correction = item.row
        record_id = str(correction["correction_record_id"]).upper()
        source = disagreement_rows[record_id]
        _validate_join(correction, source)
        episode_id = str(correction["episode_id"])
        facts = (
            int(correction["seat"]),
            str(source["actual_order"]),
            str(source["outcome"]),
            str(source.get("opponent_matchup") or "unknown"),
        )
        prior = episode_facts.setdefault(episode_id, facts)
        if prior != facts:
            raise ValueError(f"inconsistent order/outcome/matchup provenance within episode {episode_id}")
        grouped[episode_id].append(item)

    eligible_episodes = {
        episode_id
        for episode_id, (_seat, order, outcome, _matchup) in episode_facts.items()
        if outcome == "loss" or order == "second"
    }
    selected = [item for item in certified if str(item.row["episode_id"]) in eligible_episodes]
    selected_ids = {str(item.row["correction_record_id"]).upper() for item in selected}
    for episode_id, episode_rows in grouped.items():
        retained_in_episode = sum(
            str(item.row["correction_record_id"]).upper() in selected_ids for item in episode_rows
        )
        if retained_in_episode not in {0, len(episode_rows)}:
            raise AssertionError(f"episode-atomic selection failed for {episode_id}")

    correction_order: Counter[str] = Counter()
    episode_order: Counter[str] = Counter()
    correction_outcome: Counter[str] = Counter()
    episode_outcome: Counter[str] = Counter()
    matchup_counts: Counter[str] = Counter()
    proposer_counts: Counter[str] = Counter()
    source_family_counts: Counter[str] = Counter()
    family_counts: Counter[str] = Counter({family: 0 for family in REQUIRED_ACTION_FAMILIES})
    episode_criteria: Counter[str] = Counter()
    for episode_id in sorted(eligible_episodes):
        _seat, order, outcome, _matchup = episode_facts[episode_id]
        episode_order[order] += 1
        episode_outcome[outcome] += 1
        if outcome == "loss" and order == "second":
            episode_criteria["historical_loss_and_actual_second"] += 1
        elif outcome == "loss":
            episode_criteria["historical_loss_only"] += 1
        else:
            episode_criteria["actual_second_only"] += 1
    for item in selected:
        row = item.row
        source = disagreement_rows[str(row["correction_record_id"]).upper()]
        order = str(source["actual_order"])
        outcome = str(source["outcome"])
        matchup = str(source.get("opponent_matchup") or "unknown")
        family, raw_family = public_action_family(source)
        correction_order[order] += 1
        correction_outcome[outcome] += 1
        matchup_counts[matchup] += 1
        source_family_counts[raw_family] += 1
        family_counts[family] += 1
        proposer_counts.update(sorted(set(map(str, row.get("proposers") or []))))

    failed_gates: list[str] = []
    if len(selected) < int(minimum_corrections):
        failed_gates.append(f"corrections:{len(selected)}<{int(minimum_corrections)}")
    if len(eligible_episodes) < int(minimum_episodes):
        failed_gates.append(f"episodes:{len(eligible_episodes)}<{int(minimum_episodes)}")
    missing_orders = [order for order in ("first", "second") if episode_order[order] <= 0]
    if missing_orders:
        failed_gates.append("missing_actual_orders:" + ",".join(missing_orders))
    for family in REQUIRED_ACTION_FAMILIES:
        if family_counts[family] < normalized_minima[family]:
            failed_gates.append(
                f"action_family.{family}:{family_counts[family]}<{normalized_minima[family]}"
            )

    report = {
        "mode": "historical_loss_or_actual_second_episode_atomic",
        "selection": {
            "input_certified_corrections": len(certified),
            "input_certified_episodes": len(grouped),
            "retained_corrections": len(selected),
            "retained_episodes": len(eligible_episodes),
            "excluded_corrections": len(certified) - len(selected),
            "excluded_episodes": len(grouped) - len(eligible_episodes),
            "by_episode_criterion": dict(sorted(episode_criteria.items())),
        },
        "coverage": {
            "corrections_by_actual_order": {
                order: correction_order[order] for order in ("first", "second")
            },
            "episodes_by_actual_order": {order: episode_order[order] for order in ("first", "second")},
            "corrections_by_outcome": {
                outcome: correction_outcome[outcome] for outcome in ("loss", "win")
            },
            "episodes_by_outcome": {outcome: episode_outcome[outcome] for outcome in ("loss", "win")},
            "by_action_family": {
                family: family_counts[family] for family in (*REQUIRED_ACTION_FAMILIES, "other")
            },
            "by_source_action_family": dict(sorted(source_family_counts.items())),
            "by_matchup_category": dict(sorted(matchup_counts.items())),
            "by_proposer": dict(sorted(proposer_counts.items())),
        },
        "thresholds": {
            "minimum_corrections": int(minimum_corrections),
            "minimum_episodes": int(minimum_episodes),
            "require_both_actual_orders": True,
            "minimum_by_action_family": normalized_minima,
        },
        "failed_gates": failed_gates,
    }
    if failed_gates:
        raise CoverageGateError(report)

    _atomic_write_output(output_path, selected)
    output_sha = sha256_file(output_path)
    manifest = {
        "schema_version": 1,
        "status": "complete",
        "passed": True,
        "source": "floor_focused_development_corrections",
        "sealed_holdout_used": False,
        "calibration_rows_used": 0,
        "training_rows_are_unmodified_certified_rows": True,
        "source_bindings": {
            "intersection": str(intersection_path),
            "intersection_sha256": intersection_sha,
            "intersection_manifest": str(intersection_manifest_path_value),
            "intersection_manifest_sha256": intersection_manifest_sha,
            "semantic_disagreements": str(disagreement_path),
            "semantic_disagreements_sha256": disagreement_sha,
            "semantic_disagreements_manifest": str(disagreement_manifest_path_value),
            "semantic_disagreements_manifest_sha256": disagreement_manifest_sha,
            "frozen_model_sha256": FROZEN_D842_MODEL_SHA256,
            "frozen_deck_canonical_sha256": FROZEN_GRIM_DECK_CANONICAL_SHA256,
            "frozen_archive_sha256": FROZEN_ARCHIVE_SHA256,
            "model_behavior_sha256": str(provenance["model_behavior_sha256"]).upper(),
        },
        **report,
        "output": str(output_path),
        "output_sha256": output_sha,
    }
    manifest_path = intersection_manifest_path(output_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intersection", type=Path, default=DEFAULT_INTERSECTION)
    parser.add_argument("--intersection-manifest", type=Path)
    parser.add_argument("--disagreements", type=Path, default=DEFAULT_DISAGREEMENTS)
    parser.add_argument("--disagreements-manifest", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--minimum-corrections", type=int, default=250)
    parser.add_argument("--minimum-episodes", type=int, default=30)
    for family in REQUIRED_ACTION_FAMILIES:
        parser.add_argument(
            f"--minimum-{family.replace('_', '-')}",
            dest=f"minimum_family_{family}",
            type=int,
            default=DEFAULT_FAMILY_MINIMA[family],
        )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    minima = {
        family: getattr(args, f"minimum_family_{family}") for family in REQUIRED_ACTION_FAMILIES
    }
    try:
        manifest = run(
            args.intersection,
            args.disagreements,
            args.output,
            intersection_manifest=args.intersection_manifest,
            disagreements_manifest=args.disagreements_manifest,
            minimum_corrections=args.minimum_corrections,
            minimum_episodes=args.minimum_episodes,
            family_minima=minima,
        )
    except CoverageGateError as exc:
        print(json.dumps(exc.report, indent=2, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

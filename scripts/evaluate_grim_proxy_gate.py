#!/usr/bin/env python3
"""Fail-closed semantic agreement gate for a frozen-d842 successor.

The gate consumes labels that survived *independent* complete-turn mining
passes.  It never compares transient option indices: the label, frozen d842,
and candidate selections are resolved to public semantic actions first.

Calibration and the sealed holdout are deliberately opt-in.  Callers must
name exactly one with ``--expected-split``; a sealed run additionally needs a
passing calibration manifest for the identical candidate bytes.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

import numpy as np

from cg.api import to_observation_class
from ptcg_ai.features import encode_observation
from ptcg_ai.model import NumpyPolicyModel
from ptcg_ai.safety import sanitize_selection
from scripts.build_grim_policy_disagreements import (
    semantic_action as observation_semantic_action,
)
from scripts.build_grim_policy_disagreements import validate_action
from scripts.intersect_complete_turn_corrections import (
    FORBIDDEN_METADATA_KEYS,
    FROZEN_D842_MODEL_SHA256,
    FROZEN_GRIM_DECK_CANONICAL_SHA256,
    canonical_json,
    expected_decision_id,
    expected_record_id,
    manifest_path_for,
    sha256_file,
    stable_json_id,
)
from training.train_correction_only import (
    LEGACY_D842_BEHAVIOR_SHA256,
    LEGACY_D842_SCHEMA3_FILE_SHA256,
    load_certified_corrections,
    model_behavior_digest,
)


CERTIFICATION_WORLDS = 8
EVALUATION_SPLITS = frozenset({"calibration", "untouched_holdout"})
TRAINING_SPLIT = "development"
ONE_SIDED_ALPHA = 0.05
BOOTSTRAP_SAMPLES = 20_000
BOOTSTRAP_SEED = 842
TRAINABLE_ARRAYS = frozenset({"score_w", "score_b", "count_w", "count_b"})

THRESHOLDS = {
    "overall_point_lift": 0.08,
    "overall_one_sided_95_lower": 0.04,
    "second_point_lift": 0.08,
    "second_one_sided_95_lower": 0.02,
    "first_one_sided_95_lower": -0.01,
}


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdefABCDEF" for character in text)


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _read_jsonl_gz(path: Path) -> list[dict]:
    rows: list[dict] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"expected an object at {path}:{line_number}")
            rows.append(value)
    return rows


def _walk_forbidden_metadata(value: Any, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = "".join(
                character for character in str(raw_key).casefold() if character.isalnum()
            )
            if key in FORBIDDEN_METADATA_KEYS:
                location = ".".join((*path, str(raw_key)))
                raise ValueError(f"hidden or identity metadata is forbidden in proxy row: {location}")
            _walk_forbidden_metadata(child, (*path, str(raw_key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_forbidden_metadata(child, (*path, str(index)))


def _world_comparison(world: Mapping[str, Any]) -> int:
    try:
        baseline = tuple(float(value) for value in world["baseline"])
        candidate = tuple(float(value) for value in world["candidate"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid public certification vector") from exc
    if not baseline or len(baseline) != len(candidate):
        raise ValueError("baseline/candidate certification vectors have unequal coverage")
    if not all(math.isfinite(value) for value in (*baseline, *candidate)):
        raise ValueError("certification vector contains a non-finite value")
    return (candidate > baseline) - (candidate < baseline)


def _decision_coordinate(row: Mapping[str, Any]) -> tuple[str, int, int]:
    episode = row.get("episode_id")
    if episode is None or not str(episode).strip():
        raise ValueError("certified row is missing episode_id")
    if row.get("seat") is None or row.get("step") is None:
        raise ValueError(f"certified row {episode!r} is missing seat or step")
    seat, step = int(row["seat"]), int(row["step"])
    if seat not in (0, 1) or step < 0:
        raise ValueError(f"invalid decision coordinate: {(episode, seat, step)}")
    return str(episode), seat, step


def _validate_certified_row(row: dict, manifest: Mapping[str, Any], expected_split: str) -> None:
    required = (
        "action",
        "actual_order",
        "baseline_semantic_id",
        "candidate_semantic_id",
        "correction",
        "correction_record_id",
        "decision_id",
        "episode_id",
        "features",
        "observation",
        "proposers",
        "semantic_action_pair_id",
        "semantic_pair_id",
        "source",
        "split",
        "seat",
        "step",
    )
    missing = [name for name in required if row.get(name) is None]
    if missing:
        raise ValueError(f"certified row is missing required fields: {','.join(missing)}")
    _walk_forbidden_metadata(row)
    if row["source"] != "complete_turn_multi_policy_correction":
        raise ValueError(f"unknown correction source: {row['source']!r}")
    if str(row["split"]) != expected_split:
        raise ValueError(
            f"label split {row['split']!r} does not match explicitly requested {expected_split!r}"
        )
    if str(row["actual_order"]) not in {"first", "second"}:
        raise ValueError("certified row has missing or unknown actual_order")
    if str(row["decision_id"]).upper() != expected_decision_id(row):
        raise ValueError("decision identity mismatch")
    if str(row["correction_record_id"]).upper() != expected_record_id(row):
        raise ValueError("correction record identity mismatch")

    observation_sha256 = stable_json_id(row["observation"])
    expected_pair = stable_json_id(
        {
            "observation_sha256": observation_sha256,
            "baseline_semantic_id": str(row["baseline_semantic_id"]),
            "candidate_semantic_id": str(row["candidate_semantic_id"]),
        }
    )
    if str(row["semantic_pair_id"]).upper() != expected_pair:
        raise ValueError("observation-bound semantic identity mismatch")
    for name in (
        "baseline_semantic_id",
        "candidate_semantic_id",
        "semantic_pair_id",
        "semantic_action_pair_id",
    ):
        if not _is_sha256(row[name]):
            raise ValueError(f"invalid {name}")
    proposers = list(map(str, row["proposers"]))
    if not proposers or proposers != sorted(set(proposers)):
        raise ValueError("non-canonical proposer provenance")
    try:
        action = [int(index) for index in row["action"]]
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid correction action") from exc
    if action != row["action"] or any(index < 0 for index in action):
        raise ValueError("invalid correction action")

    correction = row["correction"]
    if not isinstance(correction, Mapping):
        raise ValueError("invalid certification payload")
    config = manifest.get("config") or {}
    repeat_count = int(manifest.get("certification_repeats", 0))
    decision = correction.get("decision") or {}
    coverage = correction.get("coverage") or {}
    worlds = correction.get("worlds") or []
    comparisons = correction.get("per_world_comparisons") or []
    repeated_vectors = correction.get("per_world_vectors") or []
    actual_comparisons = [_world_comparison(world) for world in worlds]
    if (
        int(config.get("worlds", 0)) != CERTIFICATION_WORLDS
        or repeat_count < 3
        or correction.get("teacher") != "equal_coverage_complete_current_turn_v1"
        or correction.get("baseline") != "frozen_d842"
        or str(correction.get("baseline_model_sha256") or "").upper()
        != FROZEN_D842_MODEL_SHA256
        or str(correction.get("anchor_sha256") or "").upper() != FROZEN_D842_MODEL_SHA256
        or str(correction.get("anchor_behavior_sha256") or "").upper()
        != LEGACY_D842_BEHAVIOR_SHA256
        or int(correction.get("certification_repeat_count", 0)) != repeat_count
        or correction.get("coverage_complete") is not True
        or correction.get("all_worlds_nonnegative") is not True
        or correction.get("errors") != []
        or decision.get("admitted") is not True
        or decision.get("reason") != "admitted"
        or int(decision.get("expected_worlds", 0)) != CERTIFICATION_WORLDS
        or int(decision.get("covered_worlds", 0)) != CERTIFICATION_WORLDS
        or int(decision.get("noninferior_worlds", 0)) != CERTIFICATION_WORLDS
        or int(decision.get("required_strict_worlds", 0)) != 4
        or int(coverage.get("baseline", 0)) != CERTIFICATION_WORLDS
        or int(coverage.get("candidate", 0)) != CERTIFICATION_WORLDS
        or len(worlds) != CERTIFICATION_WORLDS
        or [int(value) for value in comparisons] != actual_comparisons
        or repeated_vectors != worlds
        or any(value < 0 for value in actual_comparisons)
        or sum(value > 0 for value in actual_comparisons) < 4
        or int(correction.get("strict_better_worlds", -1))
        != sum(value > 0 for value in actual_comparisons)
        or int(decision.get("strict_better_worlds", -1))
        != sum(value > 0 for value in actual_comparisons)
    ):
        raise ValueError("incomplete or inconsistent eight-world certification")
    if [int(world.get("world_index", -1)) for world in worlds] != list(range(8)):
        raise ValueError("non-canonical certification world coverage")
    if not _is_sha256(correction.get("certification_signature")):
        raise ValueError("invalid repeat-stability signature")
    if not _is_sha256(correction.get("public_boundary_hash")):
        raise ValueError("invalid public boundary hash")


@dataclass(frozen=True)
class CertificationPass:
    path: Path
    sha256: str
    manifest_path: Path
    manifest_sha256: str
    manifest: dict
    rows: dict[str, dict]
    decisions: dict[tuple[str, int, int], str]


@dataclass(frozen=True)
class CertifiedBank:
    path: Path
    sha256: str
    manifest_path: Path
    manifest_sha256: str
    manifest: dict
    rows: tuple[dict, ...]
    input_passes: tuple[CertificationPass, ...]


def _load_pass(path: Path, expected_split: str) -> CertificationPass:
    path = path.resolve()
    manifest_path = manifest_path_for(path).resolve()
    if not path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError(f"certification pass or manifest is missing: {path}")
    file_hash = sha256_file(path)
    manifest_hash = sha256_file(manifest_path)
    manifest = _read_json(manifest_path)
    config = manifest.get("config") or {}
    sealed_expected = expected_split == "untouched_holdout"
    if (
        manifest.get("passed") is not True
        or manifest.get("sealed_holdout_used") is not sealed_expected
        or int(manifest.get("integrity_failures", -1)) != 0
        or int(manifest.get("worker_exceptions", -1)) != 0
        or Path(str(manifest.get("output") or "")).resolve() != path
        or str(manifest.get("output_sha256") or "").upper() != file_hash
        or list(map(str, manifest.get("splits") or [])) != [expected_split]
        or int(config.get("worlds", 0)) != CERTIFICATION_WORLDS
        or int(manifest.get("certification_repeats", 0)) < 3
        or int(config.get("certification_repeats", manifest.get("certification_repeats", 0)))
        != int(manifest.get("certification_repeats", 0))
        or str(manifest.get("model_sha256") or "").upper() != FROZEN_D842_MODEL_SHA256
        or str(manifest.get("model_behavior_sha256") or "").upper()
        != LEGACY_D842_BEHAVIOR_SHA256
        or str(manifest.get("hero_deck_canonical_sha256") or "").upper()
        != FROZEN_GRIM_DECK_CANONICAL_SHA256
        or not _is_sha256(manifest.get("input_sha256"))
    ):
        raise ValueError(f"certification pass manifest failed integrity checks: {manifest_path}")

    rows: dict[str, dict] = {}
    decisions: dict[tuple[str, int, int], str] = {}
    for row in _read_jsonl_gz(path):
        _validate_certified_row(row, manifest, expected_split)
        record_id = str(row["correction_record_id"]).upper()
        coordinate = _decision_coordinate(row)
        if record_id in rows:
            raise ValueError(f"duplicate correction record in {path}: {record_id}")
        if coordinate in decisions:
            raise ValueError(f"multiple labels for episode-seat-step in {path}: {coordinate}")
        rows[record_id] = row
        decisions[coordinate] = record_id
    if len(rows) != int(manifest.get("admitted_corrections", -1)):
        raise ValueError(f"certification pass row count mismatch: {path}")
    declared_signatures = manifest.get("admitted_certification_signatures")
    actual_signatures = {
        record_id: str(row["correction"]["certification_signature"]).upper()
        for record_id, row in sorted(rows.items())
    }
    if not isinstance(declared_signatures, Mapping) or {
        str(key).upper(): str(value).upper() for key, value in declared_signatures.items()
    } != actual_signatures:
        raise ValueError(f"certification signature map mismatch: {path}")
    return CertificationPass(
        path=path,
        sha256=file_hash,
        manifest_path=manifest_path,
        manifest_sha256=manifest_hash,
        manifest=manifest,
        rows=rows,
        decisions=decisions,
    )


def _pass_provenance(pass_: CertificationPass) -> dict:
    manifest = pass_.manifest
    return {
        "source_input_sha256": str(manifest["input_sha256"]).upper(),
        "model_sha256": str(manifest["model_sha256"]).upper(),
        "model_behavior_sha256": str(manifest["model_behavior_sha256"]).upper(),
        "hero_deck_canonical_sha256": str(manifest["hero_deck_canonical_sha256"]).upper(),
        "splits": list(map(str, manifest["splits"])),
        "shard_index": int(manifest.get("shard_index", 0)),
        "shard_count": int(manifest.get("shard_count", 1)),
        "selected_records": int(manifest.get("selected_records", -1)),
        "decision_boundaries_evaluated": int(manifest.get("decision_boundaries_evaluated", -1)),
        "certification_repeats": int(manifest["certification_repeats"]),
        "config": manifest["config"],
    }


def _exact_intersection(passes: Sequence[CertificationPass]) -> list[dict]:
    if len(passes) < 2:
        raise ValueError("at least two independent certification passes are required")
    provenance = _pass_provenance(passes[0])
    if any(_pass_provenance(pass_) != provenance for pass_ in passes[1:]):
        raise ValueError("certification pass provenance/configuration mismatch")
    record_ids = sorted(set().union(*(pass_.rows for pass_ in passes)))
    retained: list[dict] = []
    for record_id in record_ids:
        rows = [pass_.rows.get(record_id) for pass_ in passes]
        if any(row is None for row in rows):
            continue
        concrete = [row for row in rows if row is not None]
        if len({canonical_json(row) for row in concrete}) == 1:
            retained.append(concrete[0])
    retained.sort(key=lambda row: str(row["correction_record_id"]).upper())
    coordinates: set[tuple[str, int, int]] = set()
    for row in retained:
        coordinate = _decision_coordinate(row)
        if coordinate in coordinates:
            raise ValueError(f"intersection has multiple labels for {coordinate}")
        coordinates.add(coordinate)
    return retained


def load_certified_bank(path: str | Path, *, expected_split: str) -> CertifiedBank:
    if expected_split not in {TRAINING_SPLIT, *EVALUATION_SPLITS}:
        raise ValueError(f"unsupported certified split: {expected_split!r}")
    path = Path(path).resolve()
    manifest_path = manifest_path_for(path).resolve()
    if not path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError(f"intersection bank or manifest is missing: {path}")
    bank_hash = sha256_file(path)
    manifest_hash = sha256_file(manifest_path)
    manifest = _read_json(manifest_path)
    sealed_expected = expected_split == "untouched_holdout"
    provenance = manifest.get("provenance") or {}
    input_records = manifest.get("inputs") or []
    if (
        int(manifest.get("schema_version", 0)) != 1
        or manifest.get("status") != "complete"
        or manifest.get("source") != "exact_multi_pass_complete_turn_intersection"
        or manifest.get("sealed_holdout_used") is not sealed_expected
        or Path(str(manifest.get("output") or "")).resolve() != path
        or str(manifest.get("output_sha256") or "").upper() != bank_hash
        or str(provenance.get("model_sha256") or "").upper() != FROZEN_D842_MODEL_SHA256
        or str(provenance.get("model_behavior_sha256") or "").upper()
        != LEGACY_D842_BEHAVIOR_SHA256
        or str(provenance.get("hero_deck_canonical_sha256") or "").upper()
        != FROZEN_GRIM_DECK_CANONICAL_SHA256
        or list(map(str, provenance.get("splits") or [])) != [expected_split]
        or int(provenance.get("certification_repeats", 0)) < 3
        or int((provenance.get("config") or {}).get("worlds", 0)) != CERTIFICATION_WORLDS
        or not isinstance(input_records, list)
        or len(input_records) < 2
    ):
        raise ValueError(f"intersection manifest failed integrity checks: {manifest_path}")

    passes: list[CertificationPass] = []
    seen_paths: set[Path] = set()
    seen_manifests: set[Path] = set()
    for reference in input_records:
        if not isinstance(reference, Mapping):
            raise ValueError("invalid intersection input reference")
        pass_path = Path(str(reference.get("file") or "")).resolve()
        pass_manifest_path = Path(str(reference.get("manifest") or "")).resolve()
        if pass_path in seen_paths or pass_manifest_path in seen_manifests:
            raise ValueError("intersection repeats a certification pass")
        seen_paths.add(pass_path)
        seen_manifests.add(pass_manifest_path)
        loaded = _load_pass(pass_path, expected_split)
        if (
            loaded.manifest_path != pass_manifest_path
            or str(reference.get("sha256") or "").upper() != loaded.sha256
            or str(reference.get("manifest_sha256") or "").upper() != loaded.manifest_sha256
            or int(reference.get("rows", -1)) != len(loaded.rows)
        ):
            raise ValueError("intersection input reference failed hash/path checks")
        passes.append(loaded)
    if len({item.manifest_sha256 for item in passes}) != len(passes):
        raise ValueError("certification passes do not have distinct run manifests")
    if _pass_provenance(passes[0]) != provenance:
        raise ValueError("intersection provenance does not match its certification passes")

    expected_rows = _exact_intersection(passes)
    actual_rows = _read_jsonl_gz(path)
    for row in actual_rows:
        _validate_certified_row(row, passes[0].manifest, expected_split)
    if [canonical_json(row) for row in actual_rows] != [canonical_json(row) for row in expected_rows]:
        raise ValueError("intersection output is not the exact independent-pass intersection")
    if not actual_rows:
        raise ValueError("certified proxy bank is empty")
    counts = manifest.get("counts") or {}
    coverage = manifest.get("coverage") or {}
    if (
        int(counts.get("input_passes", -1)) != len(passes)
        or int(counts.get("retained_corrections", -1)) != len(actual_rows)
        or int(coverage.get("episodes", -1))
        != len({str(row["episode_id"]) for row in actual_rows})
        or int(coverage.get("decision_boundaries", -1)) != len(actual_rows)
    ):
        raise ValueError("intersection manifest count/coverage mismatch")

    episode_splits: dict[str, str] = {}
    episode_orders: dict[str, str] = {}
    coordinates: set[tuple[str, int, int]] = set()
    for row in actual_rows:
        episode = str(row["episode_id"])
        split = str(row["split"])
        order = str(row["actual_order"])
        if episode in episode_splits and episode_splits[episode] != split:
            raise ValueError(f"episode crosses whole-episode splits: {episode}")
        if episode in episode_orders and episode_orders[episode] != order:
            raise ValueError(f"episode has conflicting actual order: {episode}")
        episode_splits[episode] = split
        episode_orders[episode] = order
        coordinate = _decision_coordinate(row)
        if coordinate in coordinates:
            raise ValueError(f"multiple labels for episode-seat-step: {coordinate}")
        coordinates.add(coordinate)
    return CertifiedBank(
        path=path,
        sha256=bank_hash,
        manifest_path=manifest_path,
        manifest_sha256=manifest_hash,
        manifest=manifest,
        rows=tuple(actual_rows),
        input_passes=tuple(passes),
    )


def _model_arrays(path: Path) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as loaded:
        arrays = {name: np.asarray(loaded[name]) for name in loaded.files}
    if "model_schema_version" not in arrays:
        raise ValueError(f"model has no schema version: {path}")
    for name, value in arrays.items():
        if value.dtype.kind not in "biuf":
            raise ValueError(f"model array {name} has unsupported dtype {value.dtype}")
        if value.dtype.kind in "f" and not np.isfinite(value).all():
            raise ValueError(f"model array {name} contains a non-finite value")
    return arrays


def verify_models(anchor_path: Path, candidate_path: Path, training_anchor_path: Path) -> dict:
    anchor_path = anchor_path.resolve()
    candidate_path = candidate_path.resolve()
    training_anchor_path = training_anchor_path.resolve()
    for label, path in (
        ("frozen anchor", anchor_path),
        ("candidate", candidate_path),
        ("training anchor", training_anchor_path),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} model does not exist: {path}")
    anchor_hash = sha256_file(anchor_path)
    candidate_hash = sha256_file(candidate_path)
    training_anchor_hash = sha256_file(training_anchor_path)
    if anchor_hash != FROZEN_D842_MODEL_SHA256:
        raise ValueError("frozen anchor is not the exact d842 model artifact")
    if model_behavior_digest(anchor_path) != LEGACY_D842_BEHAVIOR_SHA256:
        raise ValueError("frozen anchor behavior digest mismatch")
    if training_anchor_hash != LEGACY_D842_SCHEMA3_FILE_SHA256:
        raise ValueError("training anchor is not the exact behavior-preserving schema-3 d842 artifact")
    if model_behavior_digest(training_anchor_path) != LEGACY_D842_BEHAVIOR_SHA256:
        raise ValueError("training anchor behavior digest mismatch")
    if candidate_hash == anchor_hash:
        raise ValueError("candidate is byte-identical to the frozen anchor")

    anchor_arrays = _model_arrays(anchor_path)
    training_arrays = _model_arrays(training_anchor_path)
    candidate_arrays = _model_arrays(candidate_path)
    if int(np.asarray(anchor_arrays["model_schema_version"]).item()) != 2:
        raise ValueError("exact d842 anchor must be schema 2")
    if int(np.asarray(training_arrays["model_schema_version"]).item()) != 3:
        raise ValueError("behavior-preserving training anchor must be schema 3")
    if int(np.asarray(candidate_arrays["model_schema_version"]).item()) != 3:
        raise ValueError("candidate model must be schema 3")
    if set(candidate_arrays) != set(training_arrays):
        raise ValueError("candidate schema arrays do not match the schema-3 anchor")
    for name in sorted(training_arrays):
        if candidate_arrays[name].shape != training_arrays[name].shape:
            raise ValueError(f"candidate array shape mismatch: {name}")
        if name not in TRAINABLE_ARRAYS and not np.array_equal(
            candidate_arrays[name], training_arrays[name]
        ):
            raise ValueError(f"non-correction model array changed: {name}")
    return {
        "anchor_path": str(anchor_path),
        "anchor_sha256": anchor_hash,
        "anchor_behavior_sha256": LEGACY_D842_BEHAVIOR_SHA256,
        "training_anchor_path": str(training_anchor_path),
        "training_anchor_sha256": training_anchor_hash,
        "candidate_path": str(candidate_path),
        "candidate_sha256": candidate_hash,
        "candidate_schema": 3,
        "permitted_trainable_arrays": sorted(TRAINABLE_ARRAYS),
    }


def verify_candidate_manifest(
    path: str | Path,
    *,
    candidate_path: Path,
    training_bank: CertifiedBank,
) -> tuple[dict, Path]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"candidate training manifest does not exist: {path}")
    manifest = _read_json(path)
    candidate_hash = sha256_file(candidate_path)
    dataset = manifest.get("dataset") or {}
    settings = manifest.get("settings") or {}
    runs = manifest.get("runs") or []
    matching = [
        run
        for run in runs
        if isinstance(run, Mapping)
        and run.get("qualified") is True
        and str(run.get("sha256") or "").upper() == candidate_hash
    ]
    if (
        manifest.get("qualified") is not True
        or manifest.get("prototype") is not False
        or len(matching) != 1
        or str(dataset.get("corrections_sha256") or "").upper() != training_bank.sha256
        or str(dataset.get("anchor_behavior_sha256") or "").upper()
        != LEGACY_D842_BEHAVIOR_SHA256
        or str(dataset.get("anchor_sha256") or "").upper() != LEGACY_D842_SCHEMA3_FILE_SHA256
        or dataset.get("split_unit") != "episode_id across corrections and rehearsal"
        or dataset.get("rehearsal_labels") != "recomputed from anchor; replay actions ignored"
        or set(map(str, settings.get("trainable_modules") or [])) != {"score", "count"}
        or set(map(str, matching[0].get("trainable_parameters") or [])) != {"score", "count"}
        or str(matching[0].get("anchor_sha256") or "").upper()
        != LEGACY_D842_SCHEMA3_FILE_SHA256
    ):
        raise ValueError("candidate training manifest failed correction-only provenance checks")
    anchor_path = Path(str(dataset.get("anchor") or "")).resolve()
    if not anchor_path.is_file() or sha256_file(anchor_path) != LEGACY_D842_SCHEMA3_FILE_SHA256:
        raise ValueError("candidate manifest's schema-3 anchor is missing or changed")

    # The certified intersection is the immutable input corpus, but the
    # correction-only trainer intentionally projects it through its own exact
    # semantic contract before splitting.  In particular, legacy schema-3
    # features cannot distinguish some PLAY choices that the richer public
    # observation semantic can distinguish.  Recompute that projection from
    # the hash-bound raw bank and exact schema-3 anchor rather than incorrectly
    # requiring the trainer's projected count to equal the raw row count.
    try:
        projected_corrections = load_certified_corrections(
            training_bank.path,
            NumpyPolicyModel(anchor_path),
            anchor_path,
        )
    except Exception as exc:
        raise ValueError(
            "candidate manifest's trainer-valid correction projection could not be reproduced"
        ) from exc
    projected_episodes = {
        str(row["episode_id"]) for row in projected_corrections
    }
    if (
        not projected_corrections
        or int(dataset.get("unique_corrections", -1)) != len(projected_corrections)
        or int(dataset.get("correction_episode_groups", -1)) != len(projected_episodes)
    ):
        raise ValueError(
            "candidate training manifest's trainer-valid projection counts do not match "
            "the certified development bank"
        )
    declared_output = Path(str(matching[0].get("output") or "")).resolve()
    if declared_output != candidate_path.resolve():
        raise ValueError("candidate path does not match its qualified training run")
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "qualified_run_seed": matching[0].get("seed"),
        "training_corrections_sha256": training_bank.sha256,
        "training_raw_certified_records": len(training_bank.rows),
        "training_projected_corrections": len(projected_corrections),
        "training_projected_episodes": len(projected_episodes),
        "training_projection_digest": stable_json_id(
            sorted(
                (
                    str(row["episode_id"]),
                    int(row["seat"]),
                    int(row["step"]),
                )
                for row in projected_corrections
            )
        ),
    }, anchor_path


def _runtime_action(model: NumpyPolicyModel, obs, features) -> list[int]:
    logits, count_logits, _ = model.predict(features)
    if not np.isfinite(logits).all() or not np.isfinite(count_logits).all():
        raise ValueError("model produced non-finite policy logits")
    if not len(logits):
        return []
    ranked = np.argsort(-logits).astype(int).tolist()
    minimum = int(obs.select.minCount)
    maximum = min(int(obs.select.maxCount), len(count_logits) - 1)
    desired = maximum if minimum == maximum else minimum + int(
        np.argmax(count_logits[minimum : maximum + 1])
    )
    return sanitize_selection(obs.select, ranked, desired)


def _semantic_id(value: Mapping[str, Any]) -> str:
    return stable_json_id(value)


def score_rows(
    rows: Iterable[dict],
    *,
    anchor_path: Path,
    candidate_path: Path,
) -> tuple[list[dict], list[dict], int]:
    anchor = NumpyPolicyModel(anchor_path)
    candidate = NumpyPolicyModel(candidate_path)
    records: list[dict] = []
    errors: list[dict] = []
    invalid = 0
    for row in rows:
        coordinate = _decision_coordinate(row)
        try:
            observation = row["observation"]
            obs = to_observation_class(observation)
            if obs.select is None or obs.current is None:
                raise ValueError("certified decision is not actionable")
            anchor_features = encode_observation(obs, 2)
            candidate_features = encode_observation(obs, 3)
            if canonical_json(anchor_features.to_json()) != canonical_json(row["features"]):
                raise ValueError("stored features do not match fresh public schema-2 encoding")
            label_action = validate_action(observation, row["action"], policy_name="certified_label")
            anchor_action = _runtime_action(anchor, obs, anchor_features)
            candidate_action = _runtime_action(candidate, obs, candidate_features)
            for name, action in (("frozen_d842", anchor_action), ("candidate", candidate_action)):
                try:
                    validate_action(observation, action, policy_name=name)
                except ValueError:
                    invalid += 1
                    raise
            label_semantic = observation_semantic_action(observation, label_action)
            anchor_semantic = observation_semantic_action(observation, anchor_action)
            candidate_semantic = observation_semantic_action(observation, candidate_action)
            label_semantic_id = _semantic_id(label_semantic)
            anchor_semantic_id = _semantic_id(anchor_semantic)
            if label_semantic_id != str(row["candidate_semantic_id"]).upper():
                raise ValueError("certified label semantic digest mismatch")
            if anchor_semantic_id != str(row["baseline_semantic_id"]).upper():
                raise ValueError("fresh frozen-d842 behavior does not match label provenance")
            if anchor_semantic == label_semantic:
                raise ValueError("certified correction is semantically equal to frozen d842")
            records.append(
                {
                    "decision_id": str(row["decision_id"]).upper(),
                    "episode_id": coordinate[0],
                    "seat": coordinate[1],
                    "step": coordinate[2],
                    "actual_order": str(row["actual_order"]),
                    "label_semantic_id": label_semantic_id,
                    "anchor_semantic_id": anchor_semantic_id,
                    "candidate_semantic_id": _semantic_id(candidate_semantic),
                    "anchor_match": int(anchor_semantic == label_semantic),
                    "candidate_match": int(candidate_semantic == label_semantic),
                }
            )
        except Exception as exc:
            errors.append(
                {
                    "decision": list(coordinate),
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
            )
    records.sort(key=lambda row: (row["episode_id"], row["seat"], row["step"], row["decision_id"]))
    errors.sort(key=lambda row: canonical_json(row))
    return records, errors, invalid


def decision_digest(records: Sequence[Mapping[str, Any]]) -> str:
    return hashlib.sha256(canonical_json(list(records)).encode("utf-8")).hexdigest().upper()


def clustered_lower_bound(
    records: Sequence[Mapping[str, Any]],
    *,
    samples: int = BOOTSTRAP_SAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> float:
    """Deterministic one-sided 95% percentile bound, resampling whole episodes."""
    if samples <= 0:
        raise ValueError("bootstrap sample count must be positive")
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in records:
        grouped[str(row["episode_id"])].append(row)
    if not grouped:
        raise ValueError("cannot bootstrap an empty episode stratum")
    clusters = [grouped[key] for key in sorted(grouped)]
    deltas = np.asarray(
        [sum(int(row["candidate_match"]) - int(row["anchor_match"]) for row in cluster) for cluster in clusters],
        dtype=np.float64,
    )
    counts = np.asarray([len(cluster) for cluster in clusters], dtype=np.float64)
    rng = np.random.default_rng(seed)
    values = np.empty(samples, dtype=np.float64)
    # Chunking bounds memory for large certified banks while preserving the RNG
    # stream and therefore the exact digest across repeated runs.
    cursor = 0
    while cursor < samples:
        size = min(2048, samples - cursor)
        sampled = rng.integers(0, len(clusters), size=(size, len(clusters)))
        values[cursor : cursor + size] = deltas[sampled].sum(axis=1) / counts[sampled].sum(axis=1)
        cursor += size
    return float(np.quantile(values, ONE_SIDED_ALPHA))


def _stratum(
    records: Sequence[Mapping[str, Any]],
    name: str,
    *,
    bootstrap_samples: int = BOOTSTRAP_SAMPLES,
) -> dict:
    if not records:
        raise ValueError(f"proxy stratum is empty: {name}")
    count = len(records)
    anchor_matches = sum(int(row["anchor_match"]) for row in records)
    candidate_matches = sum(int(row["candidate_match"]) for row in records)
    lift = (candidate_matches - anchor_matches) / count
    lower = clustered_lower_bound(records, samples=bootstrap_samples)
    return {
        "decisions": count,
        "episode_clusters": len({str(row["episode_id"]) for row in records}),
        "frozen_d842_agreement": anchor_matches / count,
        "candidate_agreement": candidate_matches / count,
        "candidate_minus_d842": lift,
        "candidate_minus_d842_points": 100.0 * lift,
        "one_sided_95_lower": lower,
        "one_sided_95_lower_points": 100.0 * lower,
    }


def _verify_frozen_calibration(
    path: Path,
    *,
    candidate_sha256: str,
    candidate_manifest_sha256: str,
    training_bank_sha256: str,
) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"calibration gate manifest does not exist: {path}")
    report = _read_json(path)
    declared_digest = str(report.get("manifest_digest_sha256") or "").upper()
    payload = dict(report)
    payload.pop("manifest_digest_sha256", None)
    actual_digest = stable_json_id(payload)
    provenance = report.get("provenance") or {}
    if (
        report.get("status") != "complete"
        or report.get("passed") is not True
        or report.get("expected_split") != "calibration"
        or declared_digest != actual_digest
        or str(provenance.get("candidate_sha256") or "").upper() != candidate_sha256
        or str(provenance.get("candidate_manifest_sha256") or "").upper()
        != candidate_manifest_sha256
        or str(provenance.get("training_bank_sha256") or "").upper()
        != training_bank_sha256
    ):
        raise ValueError("sealed evaluation candidate is not frozen by a passing calibration gate")
    return {"path": str(path.resolve()), "sha256": sha256_file(path), "manifest_digest_sha256": actual_digest}


def run(
    *,
    labels_path: str | Path,
    training_labels_path: str | Path,
    anchor_path: str | Path,
    candidate_path: str | Path,
    candidate_manifest_path: str | Path,
    expected_split: str,
    output_path: str | Path,
    calibration_gate_manifest: str | Path | None = None,
    bootstrap_samples: int = BOOTSTRAP_SAMPLES,
) -> dict:
    if expected_split not in EVALUATION_SPLITS:
        raise ValueError("expected_split must explicitly be calibration or untouched_holdout")
    if expected_split == "untouched_holdout" and calibration_gate_manifest is None:
        raise ValueError("untouched_holdout requires a passing calibration gate manifest")
    if expected_split == "calibration" and calibration_gate_manifest is not None:
        raise ValueError("calibration_gate_manifest is only valid for untouched_holdout")
    labels = load_certified_bank(labels_path, expected_split=expected_split)
    training = load_certified_bank(training_labels_path, expected_split=TRAINING_SPLIT)
    evaluation_episodes = {str(row["episode_id"]) for row in labels.rows}
    training_episodes = {str(row["episode_id"]) for row in training.rows}
    overlap = sorted(evaluation_episodes & training_episodes)
    if overlap:
        raise ValueError(f"training/evaluation episode leakage: {overlap[:10]}")

    candidate_path = Path(candidate_path).resolve()
    manifest_provenance, training_anchor_path = verify_candidate_manifest(
        candidate_manifest_path,
        candidate_path=candidate_path,
        training_bank=training,
    )
    model_provenance = verify_models(
        Path(anchor_path), candidate_path, training_anchor_path
    )
    frozen_calibration = None
    if calibration_gate_manifest is not None:
        frozen_calibration = _verify_frozen_calibration(
            Path(calibration_gate_manifest).resolve(),
            candidate_sha256=model_provenance["candidate_sha256"],
            candidate_manifest_sha256=manifest_provenance["sha256"],
            training_bank_sha256=training.sha256,
        )

    # Recompute frozen-anchor behavior on every label that was allowed to
    # influence training as well.  The candidate need not agree with those
    # labels here, but both models must execute legally and the stored public
    # features/baseline semantic IDs must reproduce exactly.
    training_records, training_errors, training_invalid = score_rows(
        training.rows,
        anchor_path=Path(anchor_path),
        candidate_path=candidate_path,
    )
    if (
        len(training_records) != len(training.rows)
        or training_errors
        or training_invalid
    ):
        raise ValueError(
            "training correction bank failed fresh anchor/candidate execution audit: "
            f"records={len(training_records)}/{len(training.rows)}, "
            f"exceptions={len(training_errors)}, invalid={training_invalid}"
        )

    first_records, first_errors, first_invalid = score_rows(
        labels.rows,
        anchor_path=Path(anchor_path),
        candidate_path=candidate_path,
    )
    second_records, second_errors, second_invalid = score_rows(
        labels.rows,
        anchor_path=Path(anchor_path),
        candidate_path=candidate_path,
    )
    first_digest = decision_digest(first_records)
    second_digest = decision_digest(second_records)
    deterministic = (
        first_digest == second_digest
        and first_errors == second_errors
        and first_invalid == second_invalid
    )
    complete = len(first_records) == len(labels.rows)
    strata: dict[str, dict] = {}
    if complete and not first_errors and first_invalid == 0:
        strata["overall"] = _stratum(
            first_records, "overall", bootstrap_samples=bootstrap_samples
        )
        for order in ("first", "second"):
            part = [row for row in first_records if row["actual_order"] == order]
            if part:
                strata[order] = _stratum(
                    part,
                    order,
                    bootstrap_samples=bootstrap_samples,
                )

    overall_stats = strata.get("overall") or {}
    first_stats = strata.get("first") or {}
    second_stats = strata.get("second") or {}

    strength_checks = {
        "overall_point_lift_at_least_8pp": bool(
            overall_stats
            and overall_stats["candidate_minus_d842"] >= THRESHOLDS["overall_point_lift"]
        ),
        "overall_lower_at_least_4pp": bool(
            overall_stats
            and overall_stats["one_sided_95_lower"]
            >= THRESHOLDS["overall_one_sided_95_lower"]
        ),
        "second_point_lift_at_least_8pp": bool(
            second_stats
            and second_stats["candidate_minus_d842"] >= THRESHOLDS["second_point_lift"]
        ),
        "second_lower_at_least_2pp": bool(
            second_stats
            and second_stats["one_sided_95_lower"]
            >= THRESHOLDS["second_one_sided_95_lower"]
        ),
        "first_lower_no_worse_than_minus_1pp": bool(
            first_stats
            and first_stats["one_sided_95_lower"] >= THRESHOLDS["first_one_sided_95_lower"]
        ),
    }
    safety_checks = {
        "all_labels_evaluated": complete,
        "zero_exceptions": not first_errors and not second_errors,
        "zero_invalid_selections": first_invalid == second_invalid == 0,
        "repeat_decision_digest_identical": deterministic,
        "whole_episode_train_eval_disjoint": not overlap,
        "both_actual_order_strata_present": bool(first_stats and second_stats),
    }
    passed = all(strength_checks.values()) and all(safety_checks.values())
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "complete",
        "passed": passed,
        "expected_split": expected_split,
        "scoring_unit": "exact public semantic action (independent of temporary option index)",
        "confidence_method": {
            "name": "deterministic whole-episode cluster percentile bootstrap",
            "one_sided_alpha": ONE_SIDED_ALPHA,
            "samples": bootstrap_samples,
            "seed": BOOTSTRAP_SEED,
        },
        "thresholds": THRESHOLDS,
        "strength_checks": strength_checks,
        "safety_checks": safety_checks,
        "strata": strata,
        "audit": {
            "certified_labels": len(labels.rows),
            "evaluated_records": len(first_records),
            "evaluation_episodes": len(evaluation_episodes),
            "training_episodes": len(training_episodes),
            "training_execution_records": len(training_records),
            "training_decision_digest": decision_digest(training_records),
            "exceptions": first_errors,
            "invalid_selections": first_invalid,
            "decision_digest": first_digest,
            "repeat_decision_digest": second_digest,
        },
        "provenance": {
            "anchor_sha256": model_provenance["anchor_sha256"],
            "anchor_behavior_sha256": model_provenance["anchor_behavior_sha256"],
            "candidate_sha256": model_provenance["candidate_sha256"],
            "candidate_schema": model_provenance["candidate_schema"],
            "candidate_manifest_sha256": manifest_provenance["sha256"],
            "training_bank_sha256": training.sha256,
            "training_bank_manifest_sha256": training.manifest_sha256,
            "training_raw_certified_records": manifest_provenance[
                "training_raw_certified_records"
            ],
            "training_projected_corrections": manifest_provenance[
                "training_projected_corrections"
            ],
            "training_projected_episodes": manifest_provenance[
                "training_projected_episodes"
            ],
            "training_projection_digest": manifest_provenance[
                "training_projection_digest"
            ],
            "evaluation_bank_sha256": labels.sha256,
            "evaluation_bank_manifest_sha256": labels.manifest_sha256,
            "independent_certification_passes": len(labels.input_passes),
            "training_evaluation_episode_overlap": 0,
            "frozen_calibration": frozen_calibration,
        },
    }
    # The digest covers every result field except the digest itself.  No wall
    # clocks, process IDs, or iteration-order-dependent values enter the file.
    report["manifest_digest_sha256"] = stable_json_id(report)
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--training-labels", type=Path, required=True)
    parser.add_argument("--anchor", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument(
        "--expected-split",
        choices=sorted(EVALUATION_SPLITS),
        required=True,
        help="Explicitly authorize calibration or the sealed untouched holdout.",
    )
    parser.add_argument("--calibration-gate-manifest", type=Path)
    parser.add_argument("--bootstrap-samples", type=int, default=BOOTSTRAP_SAMPLES)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(
        labels_path=args.labels,
        training_labels_path=args.training_labels,
        anchor_path=args.anchor,
        candidate_path=args.candidate,
        candidate_manifest_path=args.candidate_manifest,
        expected_split=args.expected_split,
        output_path=args.output,
        calibration_gate_manifest=args.calibration_gate_manifest,
        bootstrap_samples=args.bootstrap_samples,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

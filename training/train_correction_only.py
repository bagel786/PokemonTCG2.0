#!/usr/bin/env python3
"""Conservative correction-only fine-tuning around a frozen policy.

This trainer deliberately does not imitate replay winners.  Search-certified
corrections supply the only labels that may differ from the anchor; every
rehearsal label is recomputed from the anchor itself.  A checkpoint is emitted
only when it stays inside an explicit decision-change budget on held-out
rehearsal states.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import heapq
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable, Iterator, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np
import torch
from torch.nn import functional as F

from ptcg_ai.features import (
    DecisionFeatures,
    MAX_SELECT_COUNT,
    V2_GLOBAL_SIZE,
    V3_OPTION_NUMERIC_SIZE,
)
from ptcg_ai.model import NumpyPolicyModel
from training.lucario_data import deterministic_gzip_text, sha256_file
from training.replay_refresh import policy_distillation_loss, set_trainable_modules
from training.schema3 import pad_schema3
from training.train_bc import (
    PolicyNet,
    collate,
    export_npz,
    load_npz_weights,
    masked_count_loss,
    move,
    policy_loss,
)


DEFAULT_TRAINABLE_MODULES = ("score", "count")
LEGACY_D842_BEHAVIOR_SHA256 = "509A2D2DD655C33FCFA2803C2A973A6E285AA8D9215A960F7B4C2B67282BAB72"
LEGACY_D842_SCHEMA2_FILE_SHA256 = "D842F85ABFC44AF9F41979F91795E22C92C179B62E04D5A0A2F9C734E70AF1C3"
LEGACY_D842_SCHEMA3_FILE_SHA256 = "2715C6FDB8A85404ABCFF183FD3A61B419DA1402F11A29BA51676753C57A6B1B"
CERTIFICATION_WORLDS = 8


def episode_key(row: dict) -> str:
    episode = row.get("episode_id")
    if episode is None or str(episode).strip() == "":
        raise ValueError("row is missing episode_id; episode-atomic splitting is impossible")
    return str(episode)


def row_key(row: dict) -> str:
    episode = episode_key(row)
    if row.get("seat") is None or row.get("step") is None:
        raise ValueError(f"row {episode!r} is missing seat or step")
    return f"{episode}:{int(row['seat'])}:{int(row['step'])}"


def stable_fraction(value: str) -> float:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def model_behavior_digest(path: str | Path) -> str:
    """Hash inference arrays while normalizing a zero-padded schema-3 anchor.

    NPZ container hashes change when the same arrays are repacked.  Legacy
    corrections identify the exact d842 behavior, so their compatibility check
    uses this canonical array digest instead of a filename or ZIP timestamp.
    """

    with np.load(path, allow_pickle=False) as arrays:
        version = int(np.asarray(arrays.get("model_schema_version", 1)).item())
        digest = hashlib.sha256()
        for name in sorted(item for item in arrays.files if item != "model_schema_version"):
            value = np.asarray(arrays[name])
            if name == "numeric_w" and version == 3:
                if value.shape[0] != V3_OPTION_NUMERIC_SIZE or np.count_nonzero(value[-1]) != 0:
                    raise ValueError("schema-3 anchor is not a behavior-preserving zero-pad")
                value = value[:-1]
            value = np.ascontiguousarray(value)
            digest.update(name.encode("utf-8") + b"\0")
            digest.update(value.dtype.str.encode("ascii") + b"\0")
            digest.update(str(value.shape).encode("ascii") + b"\0")
            digest.update(value.tobytes())
    return digest.hexdigest().upper()


def migrate_features_to_schema3(features: dict) -> dict:
    """Return a schema-3 copy without changing schema-2 model behavior."""
    result = copy.deepcopy(features)
    version = int(result.get("feature_version", 1))
    if version not in (2, 3):
        raise ValueError(f"expected schema-2/3 features, got {version}")
    if len(result.get("global", [])) != V2_GLOBAL_SIZE:
        raise ValueError(
            f"schema-2/3 global vector needs {V2_GLOBAL_SIZE} values, "
            f"got {len(result.get('global', []))}"
        )
    for option in result.get("options", []):
        numeric = list(option.get("numeric", []))
        if version == 2:
            numeric.append(0.0)
        if len(numeric) != V3_OPTION_NUMERIC_SIZE:
            raise ValueError(
                f"schema-3 option needs {V3_OPTION_NUMERIC_SIZE} numeric values, got {len(numeric)}"
            )
        option["numeric"] = numeric
    result["feature_version"] = 3
    encoded = DecisionFeatures.from_json(result)
    numeric_values = [value for option in encoded.options for value in option.numeric]
    if not all(math.isfinite(float(value)) for value in [*encoded.global_features, *numeric_values]):
        raise ValueError("features contain non-finite numeric values")
    return result


def model_action(model: NumpyPolicyModel, features: dict) -> list[int]:
    encoded = DecisionFeatures.from_json(features)
    logits, count_logits, _ = model.predict(encoded)
    if not len(logits):
        return []
    # Match the frozen runtime byte-for-byte.  It uses NumPy's default argsort,
    # including its deterministic tie behavior.
    ranked = np.argsort(-logits).astype(int).tolist()
    minimum = int(round(float(features["global"][28]) * MAX_SELECT_COUNT))
    maximum = int(round(float(features["global"][29]) * MAX_SELECT_COUNT))
    minimum = max(0, min(minimum, len(ranked), len(count_logits) - 1))
    maximum = max(minimum, min(maximum, len(ranked), len(count_logits) - 1))
    if minimum == maximum:
        desired = maximum
    else:
        desired = minimum + int(np.argmax(count_logits[minimum : maximum + 1]))
    return ranked[:desired]


def semantic_action(features: dict, action: Sequence[int]) -> tuple:
    """Represent an action independently of transient option-list positions."""
    options = features.get("options", [])
    selected = []
    for index in action:
        if not 0 <= int(index) < len(options):
            raise ValueError(f"invalid action index {index} for {len(options)} options")
        selected.append(_semantic_option(options[int(index)]))
    return tuple(selected)


def _semantic_option(option: dict) -> tuple:
    numeric = list(option.get("numeric", []))
    # Positions 9..11 encode transient source/target/sub-card indices.  All
    # other components describe the semantic choice (including NUMBER, count,
    # target health, owner, and the schema-3 nullification flag).
    stable_numeric = tuple(
        float(value) for index, value in enumerate(numeric) if index not in (9, 10, 11)
    )
    return (
        int(option.get("option_type", -1)),
        int(option.get("context", -1)),
        int(option.get("source_card", 0)),
        int(option.get("target_card", 0)),
        int(option.get("attack_id", 0)),
        int(option.get("area", 0)),
        int(option.get("in_play_area", 0)),
        int(option.get("source_serial", 0)),
        int(option.get("target_serial", 0)),
        stable_numeric,
    )


def semantic_equivalence_sets(features: dict, action: Sequence[int]) -> list[list[int]]:
    """Return every option index equivalent to each selected semantic action.

    The engine can expose duplicate options whose only differences are
    temporary list positions.  Treating one arbitrary index as the sole label
    creates both a false training penalty and a false audit miss.
    """

    options = features.get("options", [])
    semantics = [_semantic_option(option) for option in options]
    groups: list[list[int]] = []
    for raw_index in action:
        index = int(raw_index)
        if not 0 <= index < len(options):
            raise ValueError(f"invalid action index {index} for {len(options)} options")
        group = [candidate for candidate, value in enumerate(semantics) if value == semantics[index]]
        if not group:
            raise AssertionError("the selected option must belong to its semantic equivalence set")
        groups.append(group)
    return groups


def _project_row(row: dict, *, source: str, weight: float) -> dict:
    features = migrate_features_to_schema3(row["features"])
    result = {
        "episode_id": row.get("episode_id"),
        "seat": int(row.get("seat", 0)),
        "step": int(row.get("step", 0)),
        "action": [int(index) for index in row.get("action", [])],
        "reward": float(row.get("reward", 0.0)),
        "features": features,
        "sample_weight": float(weight),
        "sample_source": source,
        "opponent_archetype": row.get("opponent_archetype", "unknown"),
    }
    if row.get("correction") is not None:
        result["correction"] = row["correction"]
    if source == "correction":
        # Recompute this from trusted features and the certified action.  Never
        # trust a producer-provided equivalence set.
        result["action_equivalence"] = semantic_equivalence_sets(
            features, result["action"]
        )
    return result


def _declared_anchor_matches(
    raw: dict,
    correction: dict,
    *,
    anchor_file_sha256: str,
    anchor_behavior_sha256: str,
) -> bool:
    behavior = correction.get("anchor_behavior_sha256") or raw.get("anchor_behavior_sha256")
    if behavior is not None:
        return str(behavior).upper() == anchor_behavior_sha256
    file_hash = correction.get("anchor_sha256") or raw.get("anchor_sha256")
    if file_hash is None:
        return False
    declared = str(file_hash).upper()
    if declared == anchor_file_sha256:
        return True
    return (
        anchor_behavior_sha256 == LEGACY_D842_BEHAVIOR_SHA256
        and declared in {LEGACY_D842_SCHEMA2_FILE_SHA256, LEGACY_D842_SCHEMA3_FILE_SHA256}
    )


def _certification_kind(
    raw: dict,
    *,
    anchor_file_sha256: str,
    anchor_behavior_sha256: str,
) -> str | None:
    """Validate complete paired coverage and exact-anchor provenance."""

    correction = raw.get("correction") or {}
    if correction.get("errors") or raw.get("errors"):
        return None
    decision = correction.get("decision")
    if isinstance(decision, dict):
        expected = int(decision.get("expected_worlds", 0))
        coverage = correction.get("coverage") or {}
        worlds = correction.get("worlds") or []
        strict = int(decision.get("strict_better_worlds", -1))
        if (
            decision.get("admitted") is not True
            or decision.get("reason") != "admitted"
            or expected != CERTIFICATION_WORLDS
            or int(coverage.get("baseline", -1)) != expected
            or int(coverage.get("candidate", -1)) != expected
            or len(worlds) != expected
            or int(decision.get("covered_worlds", -1)) != expected
            or int(decision.get("noninferior_worlds", -1)) != expected
            or strict < math.ceil(expected / 2)
            or not _declared_anchor_matches(
                raw,
                correction,
                anchor_file_sha256=anchor_file_sha256,
                anchor_behavior_sha256=anchor_behavior_sha256,
            )
        ):
            return None
        return "complete_turn_v1"

    # Compatibility for the existing 42-row B2 bank is deliberately pinned to
    # exact d842 behavior and its one known teacher contract.  Arbitrary files
    # cannot acquire this exception merely by using the same metadata strings.
    deltas = correction.get("per_world_deltas") or []
    try:
        values = [float(value) for value in deltas]
    except (TypeError, ValueError):
        return None
    if (
        anchor_behavior_sha256 != LEGACY_D842_BEHAVIOR_SHA256
        or correction.get("teacher") != "multi_determinization_search"
        or correction.get("baseline") != "d842_schema3"
        or correction.get("all_worlds_nonnegative") is not True
        or len(values) != CERTIFICATION_WORLDS
        or not all(math.isfinite(value) and value >= 0 for value in values)
        or sum(value > 0 for value in values) < math.ceil(CERTIFICATION_WORLDS / 2)
    ):
        return None
    return "legacy_b2_exact_d842"


def load_certified_corrections(
    path: str | Path,
    anchor: NumpyPolicyModel,
    anchor_path: str | Path,
) -> list[dict]:
    """Load unique, complete-coverage corrections that actually differ from anchor."""
    anchor_file_sha256 = sha256_file(anchor_path).upper()
    anchor_behavior_sha256 = model_behavior_digest(anchor_path)
    retained: dict[str, dict[tuple, dict]] = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            raw = json.loads(line)
            kind = _certification_kind(
                raw,
                anchor_file_sha256=anchor_file_sha256,
                anchor_behavior_sha256=anchor_behavior_sha256,
            )
            if kind is None:
                continue
            features = migrate_features_to_schema3(raw["features"])
            baseline = model_action(anchor, features)
            challenger = [int(index) for index in raw.get("action", [])]
            challenger_semantic = semantic_action(features, challenger)
            if semantic_action(features, baseline) == challenger_semantic:
                continue
            projected = _project_row(raw, source="correction", weight=1.0)
            projected["certification_kind"] = kind
            boundary = retained.setdefault(row_key(raw), {})
            existing = boundary.get(challenger_semantic)
            if existing is not None and json.dumps(
                existing, sort_keys=True, separators=(",", ":")
            ) != json.dumps(projected, sort_keys=True, separators=(",", ":")):
                raise ValueError(f"conflicting duplicate certified row: {row_key(raw)}")
            boundary.setdefault(challenger_semantic, projected)
    ambiguous = {key: candidates for key, candidates in retained.items() if len(candidates) != 1}
    if ambiguous:
        raise ValueError(
            "certified corpus contains conflicting challenger labels for "
            f"{len(ambiguous)} decision boundaries"
        )
    return [next(iter(retained[key].values())) for key in sorted(retained)]


def iter_rehearsal_split(
    path: str | Path,
    *,
    split: str,
    holdout_fraction: float,
    validation_fraction: float = 0.0,
    excluded_episodes: frozenset[str] = frozenset(),
) -> Iterator[dict]:
    """Stream an episode-atomic split, excluding every correction episode."""
    if split not in {"train", "validation", "holdout"}:
        raise ValueError(f"unknown rehearsal split: {split!r}")
    if not 0 <= validation_fraction < 1 - holdout_fraction:
        raise ValueError("validation fraction must leave a nonempty training fraction")
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            raw = json.loads(line)
            episode = episode_key(raw)
            if episode in excluded_episodes:
                continue
            is_holdout = stable_fraction(f"episode-split:{episode}") < holdout_fraction
            is_validation = (
                not is_holdout
                and validation_fraction > 0
                and stable_fraction(f"episode-validation:{episode}")
                < validation_fraction / (1.0 - holdout_fraction)
            )
            assigned = "holdout" if is_holdout else "validation" if is_validation else "train"
            if split != assigned:
                continue
            yield raw


def relabel_rehearsal_rows(rows: Iterable[dict], anchor: NumpyPolicyModel) -> list[dict]:
    """Ignore replay actions and replace them with exact anchor decisions."""
    result = []
    for raw in rows:
        projected = _project_row(raw, source="anchor_rehearsal", weight=1.0)
        projected["action"] = model_action(anchor, projected["features"])
        result.append(projected)
    return result


def select_stable(rows: Iterable[dict], limit: int, namespace: str) -> list[dict]:
    """Select the lowest stable hashes, independent of input ordering."""
    if limit < 0:
        raise ValueError("stable sample limit cannot be negative")
    if limit == 0:
        return []
    # Bounded max-heap: the smallest negative value is the largest digest,
    # which is the row evicted when a smaller stable digest arrives.
    selected: list[tuple[int, str, dict]] = []
    seen: dict[str, str] = {}
    for row in rows:
        key = row_key(row)
        row_digest = hashlib.sha256(
            json.dumps(row, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if key in seen:
            if seen[key] != row_digest:
                raise ValueError(f"conflicting duplicate rehearsal row: {key}")
            continue
        seen[key] = row_digest
        score = int.from_bytes(
            hashlib.sha256(f"{namespace}:{key}".encode("utf-8")).digest(), "big"
        )
        item = (-score, key, row)
        if len(selected) < limit:
            heapq.heappush(selected, item)
        elif score < -selected[0][0]:
            heapq.heapreplace(selected, item)
    return [row for _, _, row in sorted(selected, key=lambda item: (-item[0], item[1]))]


def correction_split(rows: Sequence[dict], split: str, holdout_fraction: float) -> list[dict]:
    if split not in {"train", "holdout"}:
        raise ValueError(f"unknown correction split: {split!r}")
    result = []
    for row in rows:
        episode = episode_key(row)
        is_holdout = stable_fraction(f"episode-split:{episode}") < holdout_fraction
        if (split == "holdout") == is_holdout:
            result.append(row)
    return result


def correction_partition(
    rows: Sequence[dict],
    split: str,
    holdout_fraction: float,
    validation_fraction: float,
) -> list[dict]:
    """Create deterministic train/validation/final-holdout episode partitions.

    The holdout assignment intentionally retains the historical
    ``episode-split`` namespace.  Validation is carved only from the former
    training population, so an already-observed internal holdout is never used
    for checkpoint or hyperparameter selection.
    """

    if split not in {"train", "validation", "holdout"}:
        raise ValueError(f"unknown correction partition: {split!r}")
    if not 0 < holdout_fraction < 1:
        raise ValueError("holdout fraction must be between zero and one")
    if not 0 < validation_fraction < 1 - holdout_fraction:
        raise ValueError("validation fraction must leave a nonempty training fraction")
    episodes = sorted({episode_key(row) for row in rows})
    if len(episodes) < 3:
        raise ValueError("nested correction selection requires at least three episode groups")
    assignment: dict[str, str] = {}
    for episode in episodes:
        if stable_fraction(f"episode-split:{episode}") < holdout_fraction:
            assignment[episode] = "holdout"
        elif (
            stable_fraction(f"episode-validation:{episode}")
            < validation_fraction / (1.0 - holdout_fraction)
        ):
            assignment[episode] = "validation"
        else:
            assignment[episode] = "train"

    # Hash buckets can be empty in small prototype corpora.  Repair them by
    # moving whole episodes, never individual decisions, in a stable order.
    def stable_episode_order(namespace: str, candidates: Iterable[str]) -> list[str]:
        return sorted(
            candidates,
            key=lambda episode: (
                stable_fraction(f"{namespace}:{episode}"),
                episode,
            ),
        )

    for needed in ("holdout", "validation", "train"):
        if needed in assignment.values():
            continue
        donors = [
            episode
            for episode in episodes
            if sum(value == assignment[episode] for value in assignment.values()) > 1
        ]
        if not donors:
            raise ValueError("unable to form three nonempty episode-atomic correction partitions")
        chosen = stable_episode_order(f"repair-{needed}", donors)[0]
        assignment[chosen] = needed
    return [row for row in rows if assignment[episode_key(row)] == split]


def write_dataset(path: Path, rows: Iterable[dict]) -> int:
    count = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with deterministic_gzip_text(path) as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
            count += 1
    return count


def read_rows(path: str | Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def batches(rows: Sequence[dict], batch_size: int, seed: int) -> Iterator[list[dict]]:
    order = list(range(len(rows)))
    random.Random(seed).shuffle(order)
    for start in range(0, len(order), batch_size):
        yield [rows[index] for index in order[start : start + batch_size]]


def stratified_batches(
    rows: Sequence[dict], batch_size: int, seed: int
) -> Iterator[list[dict]]:
    """Yield deterministic mixed batches with correction signal in every step.

    Rehearsal can outnumber corrections by two orders of magnitude.  Ordinary
    shuffling therefore creates all-rehearsal optimizer steps that sharpen the
    anchor's argmax without learning a correction.  This scheduler preserves
    the bounded dataset and cycles only the smaller correction population when
    needed to pair every rehearsal partition with at least one correction.
    """

    if batch_size <= 0:
        raise ValueError("batch size must be positive")
    correction_rows = [row for row in rows if row.get("sample_source") == "correction"]
    rehearsal_rows = [row for row in rows if row.get("sample_source") == "anchor_rehearsal"]
    unknown = len(rows) - len(correction_rows) - len(rehearsal_rows)
    if unknown:
        raise ValueError(f"found {unknown} rows with an untrusted sample source")
    if not correction_rows:
        raise ValueError("stratified correction training requires correction rows")
    if rehearsal_rows and batch_size < 2:
        raise ValueError("mixed correction/rehearsal batches require batch size at least two")

    rng = random.Random(seed)
    corrections = list(correction_rows)
    rehearsals = list(rehearsal_rows)
    rng.shuffle(corrections)
    rng.shuffle(rehearsals)
    if not rehearsals:
        yield from batches(corrections, batch_size, seed)
        return

    # This is the smallest number of batches that has room for every unique
    # row and reserves at least one correction slot per batch.
    steps = max(
        math.ceil((len(corrections) + len(rehearsals)) / batch_size),
        math.ceil(len(rehearsals) / (batch_size - 1)),
    )
    assigned: list[list[dict]] = [[] for _ in range(steps)]
    if len(corrections) >= steps:
        for index, row in enumerate(corrections):
            assigned[index % steps].append(row)
    else:
        for index in range(steps):
            assigned[index].append(corrections[index % len(corrections)])

    rehearsal_index = 0
    # Fill in rounds to avoid a large tail batch and to keep every batch at or
    # below the requested bound.
    while rehearsal_index < len(rehearsals):
        made_progress = False
        for chunk in assigned:
            if rehearsal_index >= len(rehearsals):
                break
            if len(chunk) < batch_size:
                chunk.append(rehearsals[rehearsal_index])
                rehearsal_index += 1
                made_progress = True
        if not made_progress:
            raise AssertionError("stratified batch capacity calculation was insufficient")
    for index, chunk in enumerate(assigned):
        random.Random(f"{seed}:batch:{index}").shuffle(chunk)
        if not any(row.get("sample_source") == "correction" for row in chunk):
            raise AssertionError("an optimizer batch lost its correction signal")
        yield chunk


def correction_collate(rows: Sequence[dict]) -> dict:
    """Collate rows and attach trusted correction/equivalence metadata."""

    batch = collate(rows)
    mask = []
    equivalence = []
    for row in rows:
        source = row.get("sample_source")
        if source not in {"correction", "anchor_rehearsal"}:
            raise ValueError(f"untrusted correction-only sample source: {source!r}")
        is_correction = source == "correction"
        mask.append(is_correction)
        computed = semantic_equivalence_sets(row["features"], row["action"])
        if is_correction and row.get("action_equivalence") is not None:
            declared = [[int(value) for value in group] for group in row["action_equivalence"]]
            if declared != computed:
                raise ValueError("stored correction equivalence does not match trusted features")
        equivalence.append(computed)
    batch["correction_mask"] = torch.tensor(mask, dtype=torch.bool)
    batch["action_equivalence"] = equivalence
    return batch


@torch.no_grad()
def decision_audit(
    model: PolicyNet,
    anchor: PolicyNet,
    correction_rows: Sequence[dict],
    rehearsal_rows: Sequence[dict],
    device: torch.device,
    batch_size: int,
) -> dict:
    model.eval()
    anchor.eval()
    totals = Counter()

    def consume(rows: Sequence[dict], kind: str) -> None:
        for chunk_start in range(0, len(rows), batch_size):
            chunk = list(rows[chunk_start : chunk_start + batch_size])
            batch = move(collate(chunk), device)
            student_logits, student_counts, _ = model(batch)
            anchor_logits, anchor_counts, _ = anchor(batch)
            for index, row in enumerate(chunk):
                student_action = _torch_decision(student_logits, student_counts, batch, index)
                anchor_action = _torch_decision(anchor_logits, anchor_counts, batch, index)
                label = [int(value) for value in row["action"]]
                student_semantic = semantic_action(row["features"], student_action)
                anchor_semantic = semantic_action(row["features"], anchor_action)
                label_semantic = semantic_action(row["features"], label)
                totals[f"{kind}_records"] += 1
                totals[f"{kind}_label_exact"] += int(student_action == label)
                totals[f"{kind}_label_semantic"] += int(student_semantic == label_semantic)
                totals[f"{kind}_anchor_exact"] += int(student_action == anchor_action)
                totals[f"{kind}_anchor_semantic"] += int(student_semantic == anchor_semantic)
                totals[f"{kind}_base_label_exact"] += int(anchor_action == label)
                totals[f"{kind}_base_label_semantic"] += int(anchor_semantic == label_semantic)

    consume(correction_rows, "correction")
    consume(rehearsal_rows, "rehearsal")
    return _finalize_audit(totals)


def _finalize_audit(totals: Counter) -> dict:
    result = dict(totals)
    for kind in ("correction", "rehearsal"):
        denominator = max(1, totals[f"{kind}_records"])
        # Corrections are semantic labels because duplicate engine options can
        # differ only by transient list positions.  Rehearsal identity remains
        # exact runtime action bytes, including ordering and concrete indices.
        label_key = f"{kind}_label_semantic" if kind == "correction" else f"{kind}_label_exact"
        anchor_key = f"{kind}_anchor_semantic" if kind == "correction" else f"{kind}_anchor_exact"
        base_key = (
            f"{kind}_base_label_semantic"
            if kind == "correction"
            else f"{kind}_base_label_exact"
        )
        result[f"{kind}_label_rate"] = totals[label_key] / denominator
        result[f"{kind}_anchor_identity"] = totals[f"{kind}_anchor_exact"] / denominator
        result[f"{kind}_semantic_anchor_identity"] = totals[anchor_key] / denominator
        result[f"{kind}_base_label_rate"] = totals[base_key] / denominator
        result[f"{kind}_changed"] = totals[f"{kind}_records"] - totals[f"{kind}_anchor_exact"]
    result["correction_lift"] = (
        result["correction_label_rate"] - result["correction_base_label_rate"]
    )
    result["rehearsal_change_rate"] = 1.0 - result["rehearsal_anchor_identity"]
    return result


@torch.no_grad()
def numpy_decision_audit(
    model: NumpyPolicyModel,
    anchor: NumpyPolicyModel,
    correction_rows: Sequence[dict],
    rehearsal_rows: Sequence[dict],
) -> dict:
    """Audit the exported inference artifact, not its float32 training copy."""

    totals = Counter()
    for kind, rows in (("correction", correction_rows), ("rehearsal", rehearsal_rows)):
        for row in rows:
            student_action = model_action(model, row["features"])
            anchor_action = model_action(anchor, row["features"])
            label = [int(value) for value in row["action"]]
            student_semantic = semantic_action(row["features"], student_action)
            anchor_semantic = semantic_action(row["features"], anchor_action)
            label_semantic = semantic_action(row["features"], label)
            totals[f"{kind}_records"] += 1
            totals[f"{kind}_label_exact"] += int(student_action == label)
            totals[f"{kind}_label_semantic"] += int(student_semantic == label_semantic)
            totals[f"{kind}_anchor_exact"] += int(student_action == anchor_action)
            totals[f"{kind}_anchor_semantic"] += int(student_semantic == anchor_semantic)
            totals[f"{kind}_base_label_exact"] += int(anchor_action == label)
            totals[f"{kind}_base_label_semantic"] += int(anchor_semantic == label_semantic)
    return _finalize_audit(totals)


def audit_eligible(
    audit: dict,
    *,
    max_change_rate: float,
    min_correction_lift: float,
) -> tuple[bool, int]:
    """Apply an integer decision-change budget and exact-label integrity gates."""

    rehearsal_records = int(audit.get("rehearsal_records", 0))
    correction_records = int(audit.get("correction_records", 0))
    correction_base_semantic = int(
        audit.get(
            "correction_base_label_semantic",
            audit.get("correction_base_label_exact", correction_records + 1),
        )
    )
    budget = int(math.floor(max_change_rate * rehearsal_records + 1e-12))
    eligible = (
        rehearsal_records > 0
        and correction_records > 0
        and int(audit.get("rehearsal_changed", rehearsal_records + 1)) <= budget
        and int(audit.get("rehearsal_base_label_exact", -1)) == rehearsal_records
        and correction_base_semantic == 0
        and float(audit.get("correction_lift", -math.inf)) >= min_correction_lift
    )
    return eligible, budget


def _torch_decision(logits: torch.Tensor, counts: torch.Tensor, batch: dict, index: int) -> list[int]:
    start, end = batch["record_options"][index]
    ranked = np.argsort(-logits[start:end].detach().cpu().numpy()).astype(int).tolist()
    minimum = int(round(float(batch["global"][index, 28].cpu()) * MAX_SELECT_COUNT))
    maximum = int(round(float(batch["global"][index, 29].cpu()) * MAX_SELECT_COUNT))
    minimum = max(0, min(minimum, len(ranked), counts.shape[1] - 1))
    maximum = max(minimum, min(maximum, len(ranked), counts.shape[1] - 1))
    desired = maximum if minimum == maximum else minimum + int(
        np.argmax(counts[index, minimum : maximum + 1].detach().cpu().numpy())
    )
    return ranked[:desired]


def correction_objective(
    student_logits: torch.Tensor,
    student_counts: torch.Tensor,
    teacher_logits: torch.Tensor,
    teacher_counts: torch.Tensor,
    batch: dict,
    distill_weight: float,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    """Apply hard labels only to corrections and anchor KL to every row.

    Correction cross entropy is divided by the number of correction records,
    not the total mixed-batch population.  Thus adding rehearsal examples can
    strengthen the anchor KL but can neither sharpen the anchor argmax through
    hard-label CE nor dilute the correction gradient.  ``sample_weight`` is an
    explicit correction-pressure multiplier and never weights KL.
    """

    record_count = len(batch["record_options"])
    correction_mask = batch.get("correction_mask")
    if correction_mask is None:
        # Backward compatibility for direct callers that provide an
        # all-correction batch.  The production collator always sets the mask.
        correction_mask = torch.ones(record_count, dtype=torch.bool, device=student_counts.device)
    else:
        correction_mask = correction_mask.to(device=student_counts.device, dtype=torch.bool)
    if correction_mask.numel() != record_count:
        raise ValueError("correction mask does not match the batch record count")
    correction_count = correction_mask.float().sum().clamp_min(1.0)

    equivalence = batch.get("action_equivalence")
    if equivalence is None:
        equivalence = [[[int(action)] for action in actions] for actions in batch["record_actions"]]
    if len(equivalence) != record_count:
        raise ValueError("action equivalence metadata does not match the batch record count")

    action_terms = []
    for record_index, (start, end) in enumerate(batch["record_options"]):
        if not bool(correction_mask[record_index].item()):
            continue
        local = student_logits[start:end]
        groups = equivalence[record_index]
        actions = batch["record_actions"][record_index]
        if len(groups) != len(actions):
            raise ValueError("semantic label groups do not match the correction action length")
        if not actions:
            continue
        available = torch.ones(len(local), dtype=torch.bool, device=local.device)
        terms = []
        for group in groups:
            valid = sorted({int(index) for index in group if 0 <= int(index) < len(local)})
            valid = [index for index in valid if bool(available[index].item())]
            if not valid:
                raise ValueError("semantic correction label has no available equivalent option")
            masked = local.masked_fill(~available, -torch.inf)
            log_probabilities = F.log_softmax(masked, dim=0)
            group_index = torch.tensor(valid, dtype=torch.long, device=local.device)
            terms.append(-torch.logsumexp(log_probabilities[group_index], dim=0))
            # Continue the ranking objective down the semantic path the model
            # itself currently prefers.  This accepts any equivalent concrete
            # index and handles repeated semantic choices without reusing one.
            chosen_local = int(torch.argmax(local[group_index]).item())
            available[valid[chosen_local]] = False
        action_terms.append(
            torch.stack(terms).mean() * batch["weights"][record_index]
        )
    action = (
        torch.stack(action_terms).sum() / correction_count
        if action_terms
        else student_logits.sum() * 0.0
    )

    last_class = student_counts.shape[1] - 1
    minimum = torch.round(batch["global"][:, 28] * MAX_SELECT_COUNT).long().clamp(0, last_class)
    maximum = torch.round(batch["global"][:, 29] * MAX_SELECT_COUNT).long().clamp(0, last_class)
    maximum = torch.maximum(maximum, minimum)
    classes = torch.arange(student_counts.shape[1], device=student_counts.device).unsqueeze(0)
    valid_counts = (classes >= minimum.unsqueeze(1)) & (classes <= maximum.unsqueeze(1))
    valid_counts.scatter_(1, batch["counts"].unsqueeze(1), True)
    masked_counts = student_counts.masked_fill(~valid_counts, -torch.inf)
    raw_count = F.cross_entropy(masked_counts, batch["counts"], reduction="none")
    correction_weights = batch["weights"] * correction_mask.to(batch["weights"].dtype)
    count = (raw_count * correction_weights).sum() / correction_count

    distill_batch = dict(batch)
    distill_batch["weights"] = torch.ones_like(batch["weights"])
    action_kl, count_kl = policy_distillation_loss(
        student_logits,
        student_counts,
        teacher_logits,
        teacher_counts,
        distill_batch,
    )
    loss = action + 0.25 * count + distill_weight * (action_kl + 0.25 * count_kl)
    return loss, {
        "action": action,
        "count": count,
        "action_kl": action_kl,
        "count_kl": count_kl,
    }


def train_seed(
    *,
    anchor_path: Path,
    train_rows: Sequence[dict],
    correction_validation: Sequence[dict] | None = None,
    rehearsal_validation: Sequence[dict] | None = None,
    correction_holdout: Sequence[dict] | None,
    rehearsal_holdout: Sequence[dict] | None,
    output: Path,
    seed: int,
    epochs: int,
    batch_size: int,
    learning_rate: float,
    distill_weight: float,
    correction_weight: float,
    trainable_modules: tuple[str, ...],
    max_change_rate: float,
    min_correction_lift: float,
    device_name: str,
    evaluate_final_holdout: bool = True,
) -> dict:
    if not train_rows:
        raise ValueError("correction-only training requires nonempty training rows")
    if correction_validation is None or rehearsal_validation is None:
        # Legacy callers did not have a distinct selection split.  Refuse to
        # silently reuse final holdout in production; this compatibility path
        # is limited to callers that explicitly pass separate sequences below.
        raise ValueError("distinct correction and rehearsal validation splits are required")
    if not correction_validation or not rehearsal_validation:
        raise ValueError("both correction and rehearsal validation splits must be nonempty")
    if evaluate_final_holdout and (not correction_holdout or not rehearsal_holdout):
        raise ValueError("both correction and rehearsal final holdout splits must be nonempty")
    if epochs <= 0 or batch_size <= 0:
        raise ValueError("epochs and batch_size must be positive")
    if learning_rate <= 0 or correction_weight <= 0 or distill_weight < 0:
        raise ValueError("loss weights and learning rate are invalid")
    if NumpyPolicyModel(anchor_path).feature_version != 3:
        raise ValueError("training anchor must be schema 3")
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    device = torch.device(device_name if device_name != "auto" else ("cuda" if torch.cuda.is_available() else "cpu"))
    teacher = PolicyNet(3)
    student = PolicyNet(3)
    load_npz_weights(teacher, anchor_path)
    load_npz_weights(student, anchor_path)
    teacher.eval().to(device)
    for parameter in teacher.parameters():
        parameter.requires_grad = False
    trainable = set_trainable_modules(student, trainable_modules)
    frozen_before = {
        name: value.detach().cpu().clone()
        for name, value in student.state_dict().items()
        if name.split(".", 1)[0] not in trainable_modules
    }
    student.to(device)
    optimizer = torch.optim.AdamW(
        [parameter for parameter in student.parameters() if parameter.requires_grad],
        lr=learning_rate,
        weight_decay=1e-6,
    )
    weighted_rows = []
    for row in train_rows:
        row = copy.deepcopy(row)
        source = row.get("sample_source")
        if source == "correction":
            row["sample_weight"] = correction_weight
        elif source == "anchor_rehearsal":
            row["sample_weight"] = 1.0
        else:
            raise ValueError(f"untrusted correction-only sample source: {source!r}")
        weighted_rows.append(row)
    best = None
    history = []
    for epoch in range(1, epochs + 1):
        student.train()
        loss_total = records = 0
        for rows in stratified_batches(weighted_rows, batch_size, seed + epoch):
            batch = move(correction_collate(rows), device)
            student_logits, student_counts, _ = student(batch)
            with torch.no_grad():
                teacher_logits, teacher_counts, _ = teacher(batch)
            loss, components = correction_objective(
                student_logits,
                student_counts,
                teacher_logits,
                teacher_counts,
                batch,
                distill_weight,
            )
            if not torch.isfinite(loss):
                diagnostics = {
                    name: float(value.detach().cpu()) for name, value in components.items()
                }
                raise FloatingPointError(
                    f"non-finite correction-only loss: {json.dumps(diagnostics, sort_keys=True)}"
                )
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                [parameter for parameter in student.parameters() if parameter.requires_grad], 0.5
            )
            optimizer.step()
            loss_total += float(loss.detach().cpu()) * len(rows)
            records += len(rows)
        audit = decision_audit(
            student,
            teacher,
            correction_validation,
            rehearsal_validation,
            device,
            batch_size,
        )
        eligible, change_budget = audit_eligible(
            audit,
            max_change_rate=max_change_rate,
            min_correction_lift=min_correction_lift,
        )
        record = {
            "epoch": epoch,
            "loss": loss_total / max(1, records),
            "records": records,
            "eligible": eligible,
            "rehearsal_change_budget": change_budget,
            **audit,
        }
        history.append(record)
        print(json.dumps({"seed": seed, **record}, sort_keys=True), flush=True)
        rank = (audit["correction_lift"], -audit["rehearsal_change_rate"], -epoch)
        if eligible and (best is None or rank > best[0]):
            best = (
                rank,
                {name: value.detach().cpu().clone() for name, value in student.state_dict().items()},
                record,
            )
    if best is None:
        return {
            "seed": seed,
            "qualified": False,
            "reason": "no checkpoint met correction-lift and change-budget gates",
            "history": history,
        }
    student.load_state_dict(best[1])
    for name, before in frozen_before.items():
        if not torch.equal(before, student.state_dict()[name].detach().cpu()):
            raise AssertionError(f"frozen parameter changed: {name}")
    export_npz(student.cpu(), output)
    validation_artifact_audit = numpy_decision_audit(
        NumpyPolicyModel(output),
        NumpyPolicyModel(anchor_path),
        correction_validation,
        rehearsal_validation,
    )
    validation_artifact_eligible, validation_artifact_budget = audit_eligible(
        validation_artifact_audit,
        max_change_rate=max_change_rate,
        min_correction_lift=min_correction_lift,
    )
    validation_artifact_audit["rehearsal_change_budget"] = validation_artifact_budget
    if not validation_artifact_eligible:
        output.unlink(missing_ok=True)
        return {
            "seed": seed,
            "qualified": False,
            "reason": "exported float16 artifact failed validation correction-lift/change-budget gates",
            "best": best[2],
            "validation_artifact_audit": validation_artifact_audit,
            "artifact_audit": validation_artifact_audit,
            "history": history,
        }
    result = {
        "seed": seed,
        "qualified": True,
        "qualification_stage": "validation_export",
        "output": str(output.resolve()),
        "sha256": sha256_file(output),
        "anchor_sha256": sha256_file(anchor_path),
        "trainable_parameters": list(trainable),
        "best": best[2],
        "validation_artifact_audit": validation_artifact_audit,
        "artifact_audit": validation_artifact_audit,
        "history": history,
    }
    if not evaluate_final_holdout:
        result["final_holdout_evaluated"] = False
        return result

    holdout_artifact_audit = numpy_decision_audit(
        NumpyPolicyModel(output),
        NumpyPolicyModel(anchor_path),
        correction_holdout or [],
        rehearsal_holdout or [],
    )
    holdout_artifact_eligible, holdout_artifact_budget = audit_eligible(
        holdout_artifact_audit,
        max_change_rate=max_change_rate,
        min_correction_lift=min_correction_lift,
    )
    holdout_artifact_audit["rehearsal_change_budget"] = holdout_artifact_budget
    result.update({
        "qualified": holdout_artifact_eligible,
        "qualification_stage": "final_holdout",
        "final_holdout_evaluated": True,
        "holdout_artifact_audit": holdout_artifact_audit,
        "artifact_audit": holdout_artifact_audit,
    })
    if not holdout_artifact_eligible:
        output.unlink(missing_ok=True)
        result["reason"] = (
            "exported float16 artifact failed final-holdout correction-lift/change-budget gates"
        )
        result.pop("output", None)
        result.pop("sha256", None)
    return result


def select_and_gate_final_holdout(
    runs: list[dict],
    *,
    anchor_path: Path,
    correction_holdout_path: Path,
    rehearsal_holdout_path: Path,
    max_change_rate: float,
    min_correction_lift: float,
) -> int | None:
    """Select by validation, then open and evaluate the final holdout once."""

    eligible = [index for index, run in enumerate(runs) if run.get("qualified")]
    if not eligible:
        return None

    def selection_key(index: int) -> tuple:
        run = runs[index]
        audit = run["validation_artifact_audit"]
        return (
            float(audit["correction_lift"]),
            -float(audit["rehearsal_change_rate"]),
            -int(run["seed"]),
        )

    selected = max(eligible, key=selection_key)
    for index in eligible:
        if index == selected:
            continue
        runs[index]["validation_qualified"] = True
        runs[index]["qualified"] = False
        runs[index]["selected_for_final_holdout"] = False
        runs[index]["reason"] = "validation-qualified checkpoint was not selected"

    # Deliberately defer reading these files until seed/epoch selection is
    # frozen.  No alternative candidate is tried if this one fails.
    correction_holdout = read_rows(correction_holdout_path)
    rehearsal_holdout = read_rows(rehearsal_holdout_path)
    run = runs[selected]
    audit = numpy_decision_audit(
        NumpyPolicyModel(run["output"]),
        NumpyPolicyModel(anchor_path),
        correction_holdout,
        rehearsal_holdout,
    )
    passed, budget = audit_eligible(
        audit,
        max_change_rate=max_change_rate,
        min_correction_lift=min_correction_lift,
    )
    audit["rehearsal_change_budget"] = budget
    run.update({
        "validation_qualified": True,
        "qualified": passed,
        "qualification_stage": "final_holdout",
        "selected_for_final_holdout": True,
        "final_holdout_evaluated": True,
        "holdout_artifact_audit": audit,
        "artifact_audit": audit,
    })
    if not passed:
        Path(run["output"]).unlink(missing_ok=True)
        run["reason"] = (
            "selected float16 artifact failed final-holdout correction-lift/change-budget gates"
        )
        run.pop("output", None)
        run.pop("sha256", None)
    return selected


def prepare(
    *,
    anchor_path: Path,
    corrections_path: Path,
    rehearsal_path: Path,
    output_dir: Path,
    rehearsal_train: int,
    rehearsal_holdout: int,
    holdout_fraction: float,
    validation_fraction: float = 0.0,
    rehearsal_validation: int | None = None,
    include_validation: bool = False,
) -> tuple:
    if not 0 < holdout_fraction < 1:
        raise ValueError("holdout_fraction must be between zero and one")
    if rehearsal_train <= 0 or rehearsal_holdout <= 0:
        raise ValueError("bounded rehearsal train and holdout sizes must be positive")
    if include_validation:
        if not 0 < validation_fraction < 1 - holdout_fraction:
            raise ValueError("validation fraction must leave a nonempty training fraction")
        if rehearsal_validation is None or rehearsal_validation <= 0:
            raise ValueError("bounded rehearsal validation size must be positive")
    anchor = NumpyPolicyModel(anchor_path)
    if anchor.feature_version != 3:
        raise ValueError("anchor must be behavior-preserving schema 3")
    corrections = load_certified_corrections(corrections_path, anchor, anchor_path)
    if not corrections:
        raise ValueError("no corrections passed complete-coverage and exact-anchor certification")
    validation_corrections: list[dict] = []
    if include_validation:
        train_corrections = correction_partition(
            corrections, "train", holdout_fraction, validation_fraction
        )
        validation_corrections = correction_partition(
            corrections, "validation", holdout_fraction, validation_fraction
        )
        holdout_corrections = correction_partition(
            corrections, "holdout", holdout_fraction, validation_fraction
        )
    else:
        train_corrections = correction_split(corrections, "train", holdout_fraction)
        holdout_corrections = correction_split(corrections, "holdout", holdout_fraction)
        # Preserve the original two-way prototype behavior for API callers.
        if corrections and not holdout_corrections:
            held_episode = min({str(row.get("episode_id")) for row in corrections})
            holdout_corrections = [
                row for row in corrections if str(row.get("episode_id")) == held_episode
            ]
            train_corrections = [
                row for row in corrections if str(row.get("episode_id")) != held_episode
            ]
        if corrections and not train_corrections:
            train_episode = min({episode_key(row) for row in corrections})
            train_corrections = [
                row for row in corrections if episode_key(row) == train_episode
            ]
            holdout_corrections = [
                row for row in corrections if episode_key(row) != train_episode
            ]
        if not train_corrections or not holdout_corrections:
            raise ValueError(
                "certified corrections require at least two episode groups for leakage-free training"
            )
    correction_episodes = frozenset(episode_key(row) for row in corrections)
    train_rehearsal = relabel_rehearsal_rows(
        select_stable(
            iter_rehearsal_split(
                rehearsal_path,
                split="train",
                holdout_fraction=holdout_fraction,
                validation_fraction=validation_fraction if include_validation else 0.0,
                excluded_episodes=correction_episodes,
            ),
            rehearsal_train,
            "rehearsal-train",
        ),
        anchor,
    )
    holdout_rehearsal = relabel_rehearsal_rows(
        select_stable(
            iter_rehearsal_split(
                rehearsal_path,
                split="holdout",
                holdout_fraction=holdout_fraction,
                validation_fraction=validation_fraction if include_validation else 0.0,
                excluded_episodes=correction_episodes,
            ),
            rehearsal_holdout,
            "rehearsal-holdout",
        ),
        anchor,
    )
    validation_rehearsal: list[dict] = []
    if include_validation:
        validation_rehearsal = relabel_rehearsal_rows(
            select_stable(
                iter_rehearsal_split(
                    rehearsal_path,
                    split="validation",
                    holdout_fraction=holdout_fraction,
                    validation_fraction=validation_fraction,
                    excluded_episodes=correction_episodes,
                ),
                int(rehearsal_validation),
                "rehearsal-validation",
            ),
            anchor,
        )
    if not train_rehearsal or not holdout_rehearsal:
        raise ValueError("bounded rehearsal sampling produced an empty train or holdout split")
    if include_validation and not validation_rehearsal:
        raise ValueError("bounded rehearsal sampling produced an empty validation split")
    output_dir.mkdir(parents=True, exist_ok=True)
    train_path = output_dir / "train.jsonl.gz"
    correction_holdout_path = output_dir / "correction_holdout.jsonl.gz"
    rehearsal_holdout_path = output_dir / "rehearsal_holdout.jsonl.gz"
    correction_validation_path = output_dir / "correction_validation.jsonl.gz"
    rehearsal_validation_path = output_dir / "rehearsal_validation.jsonl.gz"
    counts = {
        "unique_corrections": len(corrections),
        "train_corrections": len(train_corrections),
        "holdout_corrections": len(holdout_corrections),
        "validation_corrections": len(validation_corrections),
        "train_rehearsal": len(train_rehearsal),
        "holdout_rehearsal": len(holdout_rehearsal),
        "validation_rehearsal": len(validation_rehearsal),
        "correction_episode_groups": len(correction_episodes),
    }
    write_dataset(train_path, sorted(train_corrections + train_rehearsal, key=row_key))
    write_dataset(correction_holdout_path, sorted(holdout_corrections, key=row_key))
    write_dataset(rehearsal_holdout_path, sorted(holdout_rehearsal, key=row_key))
    if include_validation:
        write_dataset(
            correction_validation_path, sorted(validation_corrections, key=row_key)
        )
        write_dataset(
            rehearsal_validation_path, sorted(validation_rehearsal, key=row_key)
        )
    manifest = {
        **counts,
        "anchor": str(anchor_path.resolve()),
        "anchor_sha256": sha256_file(anchor_path),
        "corrections_sha256": sha256_file(corrections_path),
        "rehearsal_sha256": sha256_file(rehearsal_path),
        "train_sha256": sha256_file(train_path),
        "correction_holdout_sha256": sha256_file(correction_holdout_path),
        "rehearsal_holdout_sha256": sha256_file(rehearsal_holdout_path),
        "rehearsal_labels": "recomputed from anchor; replay actions ignored",
        "split_unit": "episode_id across corrections and rehearsal",
        "checkpoint_selection_split": "validation" if include_validation else "holdout",
        "final_internal_gate_split": "holdout",
        "rehearsal_excluded_correction_episodes": len(correction_episodes),
        "certification_kinds": dict(Counter(row["certification_kind"] for row in corrections)),
        "anchor_behavior_sha256": model_behavior_digest(anchor_path),
        "holdout_fraction": holdout_fraction,
        "validation_fraction": validation_fraction if include_validation else 0.0,
    }
    if include_validation:
        manifest.update({
            "correction_validation_sha256": sha256_file(correction_validation_path),
            "rehearsal_validation_sha256": sha256_file(rehearsal_validation_path),
        })
    (output_dir / "dataset_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    if include_validation:
        return (
            train_path,
            correction_validation_path,
            rehearsal_validation_path,
            correction_holdout_path,
            rehearsal_holdout_path,
            manifest,
        )
    return train_path, correction_holdout_path, rehearsal_holdout_path, manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor", default="artifacts/recovery_schema3/d842_schema3_zero_init.npz")
    parser.add_argument("--corrections", default="artifacts/recovery_training/b2_corrections.jsonl.gz")
    parser.add_argument("--rehearsal", default="artifacts/overnight_pipeline_output/afbc_data/d842_rehearsal.jsonl.gz")
    parser.add_argument("--output-dir", default="artifacts/correction_only")
    parser.add_argument("--seeds", default="20260810,20260811,20260812")
    parser.add_argument("--minimum-corrections", type=int, default=250)
    parser.add_argument("--allow-prototype", action="store_true")
    parser.add_argument("--rehearsal-train", type=int, default=20_000)
    parser.add_argument("--rehearsal-validation", type=int, default=5_000)
    parser.add_argument("--rehearsal-holdout", type=int, default=10_000)
    parser.add_argument("--holdout-fraction", type=float, default=0.20)
    parser.add_argument("--validation-fraction", type=float, default=0.15)
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--distill-weight", type=float, default=4.0)
    parser.add_argument("--correction-weight", type=float, default=8.0)
    parser.add_argument("--trainable-modules", default=",".join(DEFAULT_TRAINABLE_MODULES))
    parser.add_argument("--max-change-rate", type=float, default=0.01)
    parser.add_argument("--min-correction-lift", type=float, default=0.08)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()
    if not 0 < args.holdout_fraction < 1:
        raise ValueError("holdout-fraction must be between zero and one")
    if not 0 < args.validation_fraction < 1 - args.holdout_fraction:
        raise ValueError("validation-fraction must leave a nonempty training fraction")
    if not 0 <= args.max_change_rate <= 1 or not 0 <= args.min_correction_lift <= 1:
        raise ValueError("rate gates must be between zero and one")
    if args.minimum_corrections < 0:
        raise ValueError("minimum-corrections cannot be negative")
    if (
        args.rehearsal_train <= 0
        or args.rehearsal_validation <= 0
        or args.rehearsal_holdout <= 0
    ):
        raise ValueError("rehearsal sample limits must be positive and bounded")
    if args.epochs <= 0 or args.batch_size <= 0 or args.learning_rate <= 0:
        raise ValueError("epochs, batch-size, and learning-rate must be positive")
    if args.correction_weight <= 0 or args.distill_weight < 0:
        raise ValueError("correction-weight must be positive and distill-weight nonnegative")
    seeds = [int(value) for value in args.seeds.split(",") if value.strip()]
    modules = tuple(value.strip() for value in args.trainable_modules.split(",") if value.strip())
    if not seeds or not modules:
        raise ValueError("at least one seed and one trainable module are required")
    anchor_path = Path(args.anchor)
    corrections_path = Path(args.corrections)
    rehearsal_path = Path(args.rehearsal)
    for label, path in (
        ("anchor", anchor_path),
        ("corrections", corrections_path),
        ("rehearsal", rehearsal_path),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} artifact does not exist: {path}")
    if NumpyPolicyModel(anchor_path).feature_version == 2:
        migrated = Path(args.output_dir) / "anchor_schema3.npz"
        pad_schema3(anchor_path, migrated)
        anchor_path = migrated
    (
        train_path,
        correction_validation_path,
        rehearsal_validation_path,
        correction_holdout_path,
        rehearsal_holdout_path,
        manifest,
    ) = prepare(
        anchor_path=anchor_path,
        corrections_path=corrections_path,
        rehearsal_path=rehearsal_path,
        output_dir=Path(args.output_dir) / "dataset",
        rehearsal_train=args.rehearsal_train,
        rehearsal_validation=args.rehearsal_validation,
        rehearsal_holdout=args.rehearsal_holdout,
        holdout_fraction=args.holdout_fraction,
        validation_fraction=args.validation_fraction,
        include_validation=True,
    )
    if manifest["unique_corrections"] < args.minimum_corrections and not args.allow_prototype:
        result = {
            "qualified": False,
            "reason": (
                f"only {manifest['unique_corrections']} certified corrections; "
                f"minimum is {args.minimum_corrections}"
            ),
            "dataset": manifest,
        }
        (Path(args.output_dir) / "training_manifest.json").write_text(
            json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(json.dumps(result, sort_keys=True))
        return 2
    train_rows = read_rows(train_path)
    correction_validation = read_rows(correction_validation_path)
    rehearsal_validation = read_rows(rehearsal_validation_path)
    runs = []
    for seed in seeds:
        runs.append(train_seed(
            anchor_path=anchor_path,
            train_rows=train_rows,
            correction_validation=correction_validation,
            rehearsal_validation=rehearsal_validation,
            correction_holdout=None,
            rehearsal_holdout=None,
            output=Path(args.output_dir) / f"seed_{seed}" / "policy_weights.npz",
            seed=seed,
            epochs=args.epochs,
            batch_size=args.batch_size,
            learning_rate=args.learning_rate,
            distill_weight=args.distill_weight,
            correction_weight=args.correction_weight,
            trainable_modules=modules,
            max_change_rate=args.max_change_rate,
            min_correction_lift=args.min_correction_lift,
            device_name=args.device,
            evaluate_final_holdout=False,
        ))
    selected_run = select_and_gate_final_holdout(
        runs,
        anchor_path=anchor_path,
        correction_holdout_path=correction_holdout_path,
        rehearsal_holdout_path=rehearsal_holdout_path,
        max_change_rate=args.max_change_rate,
        min_correction_lift=args.min_correction_lift,
    )
    result = {
        "qualified": selected_run is not None and bool(runs[selected_run]["qualified"]),
        "selected_run_index": selected_run,
        "prototype": manifest["unique_corrections"] < args.minimum_corrections,
        "dataset": manifest,
        "settings": {
            "seeds": seeds,
            "epochs": args.epochs,
            "validation_fraction": args.validation_fraction,
            "learning_rate": args.learning_rate,
            "distill_weight": args.distill_weight,
            "correction_weight": args.correction_weight,
            "trainable_modules": modules,
            "max_change_rate": args.max_change_rate,
            "min_correction_lift": args.min_correction_lift,
        },
        "runs": runs,
    }
    (Path(args.output_dir) / "training_manifest.json").write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Certify multi-policy disagreements at an equal complete-turn boundary.

This is an offline teacher only.  Hidden opponent deck identities are taken
from replay handshakes to create determinizations; neither those identities nor
the search procedure are required by a trained runtime policy.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Iterator

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

import numpy as np

from cg.api import to_observation_class
from ptcg_ai.features import V3_OPTION_NUMERIC_SIZE, encode_observation
from ptcg_ai.model import NumpyPolicyModel
from ptcg_ai.safety import sanitize_selection
from training.complete_turn_corrections import (
    CorrectionConfig,
    evaluate_complete_turn_correction,
)
from training.lucario_data import deterministic_gzip_text


DEFAULT_INPUT = ROOT / "artifacts" / "grim_policy_disagreements" / "disagreements.jsonl.gz"
DEFAULT_MODEL = ROOT / "artifacts" / "overnight_grim_20260730" / "grim_selected.npz"
DEFAULT_OUTPUT = ROOT / "artifacts" / "grim_complete_turn_corrections" / "corrections.jsonl.gz"
DEFAULT_HERO_DECK = ROOT / "artifacts" / "recovery_probes" / "extracted" / "control" / "deck.csv"
FROZEN_D842_MODEL_SHA256 = "D842F85ABFC44AF9F41979F91795E22C92C179B62E04D5A0A2F9C734E70AF1C3"
FROZEN_GRIM_DECK_CANONICAL_SHA256 = "C20A8A46F5C635773754F03103652F5C534B13DC622448ED2255A97234C103AF"
CERTIFICATION_WORLDS = 8

_WORKER_MODEL: NumpyPolicyModel | None = None
_WORKER_CONFIG: CorrectionConfig | None = None
_WORKER_HERO_DECK: tuple[int, ...] | None = None
_WORKER_REPEATS: int | None = None


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def model_behavior_digest(path: str | Path) -> str:
    """Hash model arrays while normalizing a behavior-preserving schema-3 pad.

    The correction trainer migrates the frozen schema-2 anchor to schema 3
    before loading corrections.  Recording this canonical behavior hash keeps
    provenance exact across that container/schema migration.
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


def load_frozen_hero_deck(path: str | Path) -> tuple[int, ...]:
    try:
        deck = tuple(int(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip())
    except (OSError, ValueError) as exc:
        raise ValueError(f"invalid hero deck {path}: {exc}") from exc
    if len(deck) != 60:
        raise ValueError(f"hero deck must contain exactly 60 cards, got {len(deck)}")
    canonical = tuple(sorted(deck))
    digest = hashlib.sha256(",".join(map(str, canonical)).encode("ascii")).hexdigest().upper()
    if digest != FROZEN_GRIM_DECK_CANONICAL_SHA256:
        raise ValueError(
            f"hero deck hash mismatch: {digest}; expected {FROZEN_GRIM_DECK_CANONICAL_SHA256}"
        )
    return deck


def verify_source_manifest(input_path: str | Path, input_sha256: str) -> tuple[Path, str, dict]:
    """Fail closed unless input is the untouched output of the strict builder."""

    input_path = Path(input_path).resolve()
    manifest_path = input_path.with_name("manifest.json")
    if not manifest_path.is_file():
        raise FileNotFoundError(f"disagreement source manifest is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    baseline = manifest.get("baseline") or {}
    candidates = manifest.get("candidates") or []
    if (
        manifest.get("schema_version") != 1
        or manifest.get("status") != "complete"
        or manifest.get("holdout_read") is not False
        or manifest.get("strict_historical") is not True
        or manifest.get("native_search_executed") is not False
        or manifest.get("output_file") != input_path.name
        or str(manifest.get("output_sha256") or "").upper() != input_sha256.upper()
        or str(baseline.get("model_sha256") or "").upper() != FROZEN_D842_MODEL_SHA256
        or str(baseline.get("deck_canonical_sha256") or "").upper()
        != FROZEN_GRIM_DECK_CANONICAL_SHA256
        or not candidates
        or any(
            str(candidate.get("deck_canonical_sha256") or "").upper()
            != FROZEN_GRIM_DECK_CANONICAL_SHA256
            for candidate in candidates
        )
    ):
        raise ValueError("disagreement source manifest failed frozen-policy integrity checks")
    return manifest_path, sha256_file(manifest_path), manifest


def stable_key(row: dict) -> str:
    """Return a unique candidate-at-decision key, never a global action-pair key."""
    if row.get("record_id"):
        return str(row["record_id"])
    return hashlib.sha256(
        json.dumps(
            {
                "episode": row.get("episode_id"),
                "seat": row.get("hero_seat"),
                "step": row.get("replay_step_t", row.get("step")),
                "observation": row.get("observation_sha256"),
                "candidate": row.get("candidate_semantic_id", row.get("candidate_semantic")),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest().upper()


def _stable_json_id(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest().upper()


def validate_input_row(row: dict) -> None:
    """Validate the builder/miner identity scopes before native work starts."""

    required = (
        "record_id",
        "episode_id",
        "hero_seat",
        "replay_step_t",
        "observation",
        "observation_sha256",
        "features",
        "baseline_action",
        "baseline_semantic",
        "baseline_semantic_id",
        "candidate_action",
        "candidate_semantic",
        "candidate_semantic_id",
        "semantic_pair_id",
        "semantic_action_pair_id",
        "opponent_deck",
        "opponent_deck_canonical_sha256",
        "proposers",
        "proposer_actions",
    )
    missing = [name for name in required if row.get(name) is None]
    if missing:
        raise ValueError(f"disagreement row is missing required fields: {','.join(missing)}")
    if row.get("schema_version") != 1 or row.get("record_type") != "semantic_disagreement":
        raise ValueError("disagreement row has an unknown schema or record type")
    split = str(row.get("split"))
    if split not in {"development", "calibration"}:
        raise ValueError(f"refusing protected or unknown disagreement split: {split!r}")
    observation_id = _stable_json_id(row["observation"])
    baseline_id = _stable_json_id(row["baseline_semantic"])
    candidate_id = _stable_json_id(row["candidate_semantic"])
    action_pair_id = _stable_json_id({
        "baseline": row["baseline_semantic"],
        "candidate": row["candidate_semantic"],
    })
    semantic_pair_id = _stable_json_id({
        "observation_sha256": observation_id,
        "baseline_semantic_id": baseline_id,
        "candidate_semantic_id": candidate_id,
    })
    record_id = _stable_json_id({
        "split": split,
        "episode_id": str(row["episode_id"]),
        "hero_seat": int(row["hero_seat"]),
        "replay_step_t": int(row["replay_step_t"]),
        "semantic_pair_id": semantic_pair_id,
    })
    declared = {
        "observation_sha256": observation_id,
        "baseline_semantic_id": baseline_id,
        "candidate_semantic_id": candidate_id,
        "semantic_action_pair_id": action_pair_id,
        "semantic_pair_id": semantic_pair_id,
        "record_id": record_id,
    }
    mismatches = [
        name
        for name, expected in declared.items()
        if str(row.get(name) or "").upper() != expected
    ]
    if mismatches:
        raise ValueError(f"disagreement identity mismatch: {','.join(mismatches)}")
    opponent_deck = tuple(int(card) for card in row["opponent_deck"])
    if len(opponent_deck) != 60:
        raise ValueError("opponent deck must contain exactly 60 cards")
    opponent_hash = hashlib.sha256(
        ",".join(map(str, sorted(opponent_deck))).encode("ascii")
    ).hexdigest().upper()
    if str(row["opponent_deck_canonical_sha256"]).upper() != opponent_hash:
        raise ValueError("opponent deck hash does not match the certification input")
    proposers = list(map(str, row["proposers"]))
    proposer_actions = row["proposer_actions"]
    if proposers != sorted(set(proposers)) or sorted(map(str, proposer_actions)) != proposers:
        raise ValueError("proposer names/actions are not canonical and complete")
    representative = list(min(tuple(map(int, proposer_actions[name])) for name in proposers))
    if representative != list(map(int, row["candidate_action"])):
        raise ValueError("candidate action is not the canonical proposer representative")


def decision_key(row: dict) -> str:
    """Identify the trainer's episode/seat/step decision boundary.

    The observation digest is deliberately not part of this key: the trainer
    enforces uniqueness at exactly this coordinate.  Conflicting observation
    digests at one coordinate are rejected separately instead of becoming two
    labels that only fail much later during training.
    """
    episode = row.get("episode_id")
    seat = row.get("hero_seat", row.get("seat"))
    step = row.get("replay_step_t", row.get("step"))
    if episode is None or str(episode).strip() == "" or seat is None or step is None:
        raise ValueError("disagreement row is missing episode_id, seat, or step")
    return hashlib.sha256(
        json.dumps(
            {
                "episode": str(episode),
                "seat": int(seat),
                "step": int(step),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest().upper()


def stable_shard(key: str, count: int) -> int:
    if count <= 0:
        raise ValueError("shard count must be positive")
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:16], 16) % count


def row_priority(row: dict) -> tuple:
    """Losses, second-order states, and broad proposer consensus first."""
    return (
        0 if str(row.get("outcome")) == "loss" else 1,
        0 if str(row.get("actual_order")) == "second" else 1,
        -len(row.get("proposers") or []),
        stable_key(row),
    )


def iter_input_rows(path: str | Path) -> Iterator[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("split") == "untouched_holdout":
                raise ValueError("sealed untouched holdout appeared in miner input")
            validate_input_row(row)
            yield row


def select_rows(
    rows: Iterable[dict],
    *,
    allowed_splits: set[str],
    shard_index: int,
    shard_count: int,
    max_records: int,
) -> list[dict]:
    if "untouched_holdout" in allowed_splits:
        raise ValueError("untouched holdout cannot be mined")
    if not 0 <= shard_index < shard_count:
        raise ValueError("shard-index must be in [0, shard-count)")
    seen: dict[str, str] = {}
    selected = []
    for row in rows:
        if str(row.get("split")) not in allowed_splits:
            continue
        key = stable_key(row)
        row_digest = hashlib.sha256(
            json.dumps(row, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest().upper()
        if key in seen:
            if seen[key] != row_digest:
                raise ValueError(f"conflicting duplicate disagreement record: {key}")
            continue
        seen[key] = row_digest
        # Keep every challenger for a decision together so cross-shard merges
        # can never create multiple labels for the same episode/seat/step.
        if stable_shard(decision_key(row), shard_count) != shard_index:
            continue
        selected.append(row)

    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in selected:
        grouped[decision_key(row)].append(row)
    for candidates in grouped.values():
        candidates.sort(key=lambda item: (row_priority(item), stable_key(item)))
    ordered_groups = sorted(
        grouped.values(),
        key=lambda candidates: (row_priority(candidates[0]), decision_key(candidates[0])),
    )
    if max_records <= 0:
        return [row for candidates in ordered_groups for row in candidates]

    bounded = []
    for candidates in ordered_groups:
        # A cap is a resource limit, never permission to evaluate only part of
        # a decision's candidate set and bias the eventual label selection.
        if len(bounded) + len(candidates) <= max_records:
            bounded.extend(candidates)
    return bounded


def d842_action(model: NumpyPolicyModel, obs) -> list[int]:
    features = encode_observation(obs, model.feature_version)
    logits, count_logits, _ = model.predict(features)
    if not len(logits):
        return []
    ranked = np.argsort(-logits).astype(int).tolist()
    minimum = int(obs.select.minCount)
    maximum = min(int(obs.select.maxCount), len(count_logits) - 1, len(ranked))
    desired = maximum if minimum == maximum else minimum + int(
        np.argmax(count_logits[minimum : maximum + 1])
    )
    return sanitize_selection(obs.select, ranked, desired)


def _init_worker(model_path: str, hero_deck: list[int], config_values: dict, repeats: int) -> None:
    global _WORKER_MODEL, _WORKER_CONFIG, _WORKER_HERO_DECK, _WORKER_REPEATS
    _WORKER_MODEL = NumpyPolicyModel(model_path)
    _WORKER_CONFIG = CorrectionConfig(**config_values)
    _WORKER_HERO_DECK = tuple(map(int, hero_deck))
    if repeats < 3:
        raise ValueError("certification requires at least three identical repeats")
    _WORKER_REPEATS = int(repeats)


def _selector_factory():
    # The closure is fresh for every branch and carries no mutable turn state.
    model = _WORKER_MODEL
    if model is None:
        raise RuntimeError("worker model was not initialized")
    return lambda obs: d842_action(model, obs)


def _world_comparisons(evaluation) -> list[dict]:
    rows = []
    for world in evaluation.worlds:
        baseline = world.baseline.values()
        candidate = world.candidate.values()
        rows.append({
            "world_index": world.world_index,
            "seed": world.seed,
            "baseline": list(baseline),
            "candidate": list(candidate),
            "lexicographic_comparison": (candidate > baseline) - (candidate < baseline),
            "baseline_steps": world.baseline_steps,
            "candidate_steps": world.candidate_steps,
        })
    return rows


def _evaluation_payload(evaluation) -> dict:
    raw = evaluation.to_dict()
    return {
        "admitted": evaluation.admitted,
        "reason": evaluation.reason,
        "baseline_action": raw["baseline_action"],
        "candidate_action": raw["candidate_action"],
        "decision": raw["decision"],
        "boundary_hash": evaluation.boundary_hash,
        "coverage": evaluation.coverage,
        "worlds": _world_comparisons(evaluation),
        "errors": list(evaluation.errors),
    }


def certification_signature(payload: dict) -> str:
    """Hash every admission-relevant output from one identical oracle run."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest().upper()


def evaluate_row(row: dict) -> dict:
    if (
        _WORKER_MODEL is None
        or _WORKER_CONFIG is None
        or _WORKER_HERO_DECK is None
        or _WORKER_REPEATS is None
    ):
        raise RuntimeError("worker was not initialized")
    try:
        obs = to_observation_class(row["observation"])
        baseline = d842_action(_WORKER_MODEL, obs)
        declared_baseline = [int(index) for index in row.get("baseline_action", [])]
        if baseline != declared_baseline:
            return {
                "key": stable_key(row),
                "admitted": False,
                "reason": "baseline_replay_mismatch",
                "worker_error": None,
            }
        candidate = [int(index) for index in row["candidate_action"]]
        # Never trust or persist a per-record hero list.  Every comparison uses
        # the one startup-verified frozen original deck.
        hero_deck = list(_WORKER_HERO_DECK)
        opponent_deck = [int(card) for card in row["opponent_deck"]]
        payloads = []
        signatures = []
        for _repeat in range(_WORKER_REPEATS):
            evaluation = evaluate_complete_turn_correction(
                obs,
                baseline,
                candidate,
                hero_deck,
                opponent_deck,
                _selector_factory,
                config=_WORKER_CONFIG,
            )
            payload = _evaluation_payload(evaluation)
            payloads.append(payload)
            signatures.append(certification_signature(payload))
        if len(set(signatures)) != 1:
            return {
                "key": stable_key(row),
                "admitted": False,
                "reason": "nondeterministic_repeats",
                "repeat_count": _WORKER_REPEATS,
                "repeat_signature": None,
                "repeat_signatures": signatures,
                "worker_error": None,
            }
        return {
            "key": stable_key(row),
            **payloads[0],
            "repeat_count": _WORKER_REPEATS,
            "repeat_signature": signatures[0],
            "repeat_signatures": signatures,
            "worker_error": None,
        }
    except Exception as exc:
        return {
            "key": stable_key(row),
            "admitted": False,
            "reason": "worker_exception",
            "worker_error": f"{type(exc).__name__}: {exc}",
        }


def _observation_semantic_pair_id(source: dict) -> str:
    declared = source.get("semantic_pair_id")
    if declared:
        return str(declared)
    return hashlib.sha256(
        json.dumps(
            {
                "observation_sha256": source.get("observation_sha256"),
                "baseline_semantic_id": source.get("baseline_semantic_id"),
                "candidate_semantic_id": source.get("candidate_semantic_id"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest().upper()


def _global_semantic_action_pair_id(source: dict) -> str:
    declared = source.get("semantic_action_pair_id")
    if declared:
        return str(declared)
    return hashlib.sha256(
        json.dumps(
            {
                "baseline_semantic_id": source.get("baseline_semantic_id"),
                "candidate_semantic_id": source.get("candidate_semantic_id"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest().upper()


def correction_output_row(
    source: dict,
    result: dict,
    model_hash: str,
    model_behavior_hash: str,
) -> dict:
    if result.get("admitted") is not True:
        raise ValueError("only admitted oracle results can become correction labels")
    worlds = result["worlds"]
    comparisons = [int(world["lexicographic_comparison"]) for world in worlds]
    decision = result["decision"]
    expected_worlds = int(decision.get("expected_worlds", 0))
    if (
        expected_worlds != CERTIFICATION_WORLDS
        or len(worlds) != expected_worlds
        or result["coverage"].get("baseline") != expected_worlds
        or result["coverage"].get("candidate") != expected_worlds
    ):
        raise ValueError("admitted result does not have exact eight-world paired coverage")
    repeat_count = int(result.get("repeat_count", 0))
    repeat_signature = str(result.get("repeat_signature") or "")
    repeat_signatures = list(result.get("repeat_signatures") or [])
    if (
        repeat_count < 3
        or len(repeat_signatures) != repeat_count
        or len(set(map(str, repeat_signatures))) != 1
        or repeat_signature != str(repeat_signatures[0])
    ):
        raise ValueError("admitted result is missing repeated-certification proof")
    output = {
        "episode_id": source.get("episode_id"),
        "team": "Larps",
        "seat": int(source.get("hero_seat", source.get("seat", 0))),
        "step": int(source.get("replay_step_t", source.get("step", 0))),
        "action": [int(index) for index in source["candidate_action"]],
        "reward": float(source.get("target", 0)),
        "features": source["features"],
        "observation": source["observation"],
        "source": "complete_turn_multi_policy_correction",
        "split": source.get("split"),
        "actual_order": source.get("actual_order"),
        "correction_record_id": stable_key(source),
        "decision_id": decision_key(source),
        # These intentionally preserve the builder's three scopes: record,
        # observation-bound semantic pair, and global semantic action pair.
        "semantic_pair_id": _observation_semantic_pair_id(source),
        "semantic_action_pair_id": _global_semantic_action_pair_id(source),
        "candidate_semantic_id": source.get("candidate_semantic_id"),
        "baseline_semantic_id": source.get("baseline_semantic_id"),
        "proposers": sorted(map(str, source.get("proposers") or [])),
        "correction": {
            "teacher": "equal_coverage_complete_current_turn_v1",
            "baseline": "frozen_d842",
            "baseline_model_sha256": model_hash,
            "anchor_sha256": model_hash,
            "anchor_behavior_sha256": model_behavior_hash,
            "certification_repeat_count": repeat_count,
            "certification_signature": repeat_signature,
            "decision": decision,
            "coverage": result["coverage"],
            "worlds": worlds,
            "errors": list(result.get("errors") or []),
            "coverage_complete": (
                result["coverage"].get("baseline") == expected_worlds
                and result["coverage"].get("candidate") == expected_worlds
            ),
            "all_worlds_nonnegative": all(value >= 0 for value in comparisons),
            "strict_better_worlds": sum(value > 0 for value in comparisons),
            "per_world_comparisons": comparisons,
            "per_world_vectors": worlds,
            "public_boundary_hash": result["boundary_hash"],
        },
    }
    return output


def robust_candidate_rank(source: dict, result: dict) -> tuple:
    """Rank multiple certified labels for one prompt without hidden metadata."""
    candidate_vectors = [tuple(map(float, world["candidate"])) for world in result["worlds"]]
    worst_world = min(candidate_vectors)
    return (
        worst_world,
        int(result["decision"].get("strict_better_worlds", 0)),
        len(set(map(str, source.get("proposers") or []))),
        str(source.get("candidate_semantic_id") or stable_key(source)),
    )


def select_unique_corrections(results: Iterable[tuple[dict, dict]]) -> tuple[list[tuple[dict, dict]], int]:
    """Keep exactly one deterministic certified challenger per decision boundary."""
    grouped: dict[str, list[tuple[dict, dict]]] = defaultdict(list)
    for source, result in results:
        if result.get("admitted"):
            grouped[decision_key(source)].append((source, result))
    for key, candidates in grouped.items():
        observations = {str(source.get("observation_sha256") or "") for source, _result in candidates}
        baselines = {str(source.get("baseline_semantic_id") or "") for source, _result in candidates}
        if "" in observations or len(observations) != 1:
            raise ValueError(f"conflicting or missing observations at decision boundary {key}")
        if "" in baselines or len(baselines) != 1:
            raise ValueError(f"conflicting or missing baselines at decision boundary {key}")
    selected = [max(candidates, key=lambda item: robust_candidate_rank(*item)) for candidates in grouped.values()]
    selected.sort(key=lambda item: stable_key(item[0]))
    ambiguous = sum(len(candidates) > 1 for candidates in grouped.values())
    return selected, ambiguous


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--hero-deck", type=Path, default=DEFAULT_HERO_DECK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--splits", default="development")
    parser.add_argument("--workers", type=int, default=max(1, min(8, os.cpu_count() or 1)))
    parser.add_argument("--worlds", type=int, default=8)
    parser.add_argument("--certification-repeats", type=int, default=3)
    parser.add_argument("--max-turn-steps", type=int, default=64)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--seed", type=int, default=20260810)
    parser.add_argument("--max-records", type=int, default=0)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    args = parser.parse_args()
    if args.workers <= 0:
        raise ValueError("workers must be positive")
    if args.worlds != CERTIFICATION_WORLDS:
        raise ValueError(f"trainer contract requires exactly {CERTIFICATION_WORLDS} worlds")
    if args.certification_repeats < 3:
        raise ValueError("certification-repeats must be at least three")
    if args.max_records < 0:
        raise ValueError("max-records cannot be negative")
    allowed_splits = {value.strip() for value in args.splits.split(",") if value.strip()}
    if not allowed_splits or not allowed_splits <= {"development", "calibration"}:
        raise ValueError("splits must be a nonempty subset of development,calibration")
    model_hash = sha256_file(args.model)
    if model_hash != FROZEN_D842_MODEL_SHA256:
        raise ValueError(
            f"model hash mismatch: {model_hash}; expected frozen d842 {FROZEN_D842_MODEL_SHA256}"
        )
    model_behavior_hash = model_behavior_digest(args.model)
    hero_deck = load_frozen_hero_deck(args.hero_deck)
    rows = select_rows(
        iter_input_rows(args.input),
        allowed_splits=allowed_splits,
        shard_index=args.shard_index,
        shard_count=args.shard_count,
        max_records=args.max_records,
    )
    config = CorrectionConfig(
        worlds=args.worlds,
        max_turn_steps=args.max_turn_steps,
        timeout_seconds=args.timeout_seconds,
        seed=args.seed,
    )
    config_values = {
        "worlds": config.worlds,
        "max_turn_steps": config.max_turn_steps,
        "timeout_seconds": config.timeout_seconds,
        "seed": config.seed,
        "manual_coin": config.manual_coin,
    }
    results = []
    started = time.time()
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=args.workers,
        initializer=_init_worker,
        initargs=(
            str(args.model.resolve()),
            list(hero_deck),
            config_values,
            args.certification_repeats,
        ),
    ) as pool:
        futures = {pool.submit(evaluate_row, row): row for row in rows}
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            result = future.result()
            results.append((futures[future], result))
            if index % 25 == 0 or index == len(rows):
                print(json.dumps({
                    "completed": index,
                    "total": len(rows),
                    "admitted": sum(item[1]["admitted"] for item in results),
                    "elapsed_seconds": round(time.time() - started, 1),
                }), flush=True)
    results.sort(key=lambda item: stable_key(item[0]))
    admitted_candidates = [(row, result) for row, result in results if result["admitted"]]
    selected_corrections, ambiguous_decisions = select_unique_corrections(results)
    admitted = [
        correction_output_row(row, result, model_hash, model_behavior_hash)
        for row, result in selected_corrections
    ]
    worker_errors = [result for _row, result in results if result.get("worker_error")]
    reason_counts = Counter(result["reason"] for _row, result in results)
    by_order = Counter(str(row.get("actual_order")) for row, _result in selected_corrections)
    by_matchup = Counter(str(row.get("opponent_matchup")) for row, _result in selected_corrections)
    by_proposer = Counter(
        proposer
        for row, _result in selected_corrections
        for proposer in sorted(set(map(str, row.get("proposers") or [])))
    )
    admitted_signatures = {
        stable_key(row): str(result["repeat_signature"])
        for row, result in selected_corrections
    }
    stable_signature_rows = sorted(
        (stable_key(row), str(result["repeat_signature"]))
        for row, result in results
        if result.get("repeat_signature") is not None
    )
    stable_signature_digest = hashlib.sha256(
        json.dumps(stable_signature_rows, separators=(",", ":")).encode("utf-8")
    ).hexdigest().upper()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with deterministic_gzip_text(args.output) as handle:
        for row in admitted:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    manifest = {
        "input": str(args.input.resolve()),
        "input_sha256": sha256_file(args.input),
        "output": str(args.output.resolve()),
        "output_sha256": sha256_file(args.output),
        "model": str(args.model.resolve()),
        "model_sha256": model_hash,
        "model_behavior_sha256": model_behavior_hash,
        "hero_deck": str(args.hero_deck.resolve()),
        "hero_deck_canonical_sha256": FROZEN_GRIM_DECK_CANONICAL_SHA256,
        "splits": sorted(allowed_splits),
        "sealed_holdout_used": False,
        "shard_index": args.shard_index,
        "shard_count": args.shard_count,
        "selected_records": len(rows),
        "admitted_candidates_before_decision_deduplication": len(admitted_candidates),
        "admitted_corrections": len(admitted),
        "decision_boundaries_with_multiple_admitted_candidates": ambiguous_decisions,
        "decision_boundaries_evaluated": len({decision_key(row) for row in rows}),
        "certification_repeats": args.certification_repeats,
        "admitted_certification_signatures": dict(sorted(admitted_signatures.items())),
        "stable_repeat_signature_digest": stable_signature_digest,
        "repeat_stable_records": sum(
            result.get("repeat_signature") is not None for _row, result in results
        ),
        "repeat_nondeterministic_records": reason_counts.get("nondeterministic_repeats", 0),
        "reasons": dict(sorted(reason_counts.items())),
        "admitted_by_actual_order": dict(sorted(by_order.items())),
        "admitted_by_matchup": dict(sorted(by_matchup.items())),
        "admitted_by_proposer": dict(sorted(by_proposer.items())),
        "worker_exceptions": len(worker_errors),
        "first_worker_exceptions": worker_errors[:20],
        "config": config_values,
        "integrity_failures": len(worker_errors) + reason_counts.get("baseline_replay_mismatch", 0),
        "passed": (
            len(worker_errors) == 0
            and reason_counts.get("baseline_replay_mismatch", 0) == 0
        ),
    }
    manifest_path = args.output.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if manifest["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

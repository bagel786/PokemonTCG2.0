#!/usr/bin/env python3
"""Development-only native reality check for ``RuntimeProofDirector``.

This audit deliberately opens only the frozen development shard.  It replays
every exact d842 hero decision in episode order, scans every narrow runtime
trigger, and executes a deterministic bounded stride sample against the real
``search_begin_input`` payload and native backend.  Two independently reset
passes must produce identical classification and decision digests; latency is
reported but excluded from both digests.

The script is diagnostic only.  It does not inspect calibration/holdout data,
wire the director into an agent, build a package, or upload anything.
"""

from __future__ import annotations

import argparse
import dataclasses
import gzip
import hashlib
import json
import math
import sys
import time
from collections import Counter
from enum import IntEnum
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

import numpy as np

from cg.api import AreaType, LogType, to_observation_class
from ptcg_ai.features import encode_observation
from ptcg_ai.model import NumpyPolicyModel
from ptcg_ai.proof_search import public_state_digest, semantic_action_key
from ptcg_ai.runtime_proof_director import RuntimeProofConfig, RuntimeProofDirector
import ptcg_ai.runtime_proof_director as runtime
from ptcg_ai.safety import sanitize_selection
from scripts.audit_grim_proof_search import iter_replay_aligned_decisions
from scripts.build_grim_5k_training_bank import deck_hash, replay_decks


DEFAULT_ARCHIVE = ROOT / "grimmsnarl_5k_reference.tar.gz"
DEFAULT_MODEL = ROOT / "artifacts" / "overnight_grim_20260730" / "grim_selected.npz"
DEFAULT_DECK = ROOT / "artifacts" / "recovery_probes" / "extracted" / "control" / "deck.csv"
DEFAULT_BANK = ROOT / "artifacts" / "grim_5k_training_bank"
DEFAULT_OUTPUT = ROOT / "artifacts" / "grim_runtime_terminal" / "development_native_audit.json"

FROZEN_ARCHIVE_SHA256 = "3ECB0BBF119E23C31905E39E19ECA8F6145104AAEFFC0A5675D2FE03855BB458"
FROZEN_MODEL_SHA256 = "D842F85ABFC44AF9F41979F91795E22C92C179B62E04D5A0A2F9C734E70AF1C3"
FROZEN_RAW_DECK_SHA256 = "92B92BAC9F9163ECFF933B3DC39294D2CC154C8684F3C8497877661419EBC59D"
FROZEN_CANONICAL_DECK_SHA256 = "C20A8A46F5C635773754F03103652F5C534B13DC622448ED2255A97234C103AF"
FROZEN_BANK_ID = "23AFC7C9FE4F5E155CCF028E03315FA252D38E3ED085B57F0D18A801CC730247"
FROZEN_DEVELOPMENT_SHA256 = "3AB24F80E318FBCC6656A757C41BBE17ACD3D63CD13E95405ECD80B8C80813B5"
FROZEN_ENGINE_HASHES = {
    "api.py": "593F1298E52A635F90F8F505A52113E9AF114F444C293404E37906F18EE06CED",
    "cg.dll": "EAE88634E26DC31D94150A4D8202FC9D32596B8C688EF67E14CB4088CD4D5771",
    "libcg.so": "D16244A3157FC55C3314F08DCC7C5179168697D78C105B95C7DEBD556B764BB7",
}


class AuditError(RuntimeError):
    """A frozen-input, cleanup, or repeatability requirement failed."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def _jsonable(value: Any) -> Any:
    if isinstance(value, IntEnum):
        return int(value)
    if dataclasses.is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _integer(value: Any, default: int = -1) -> int:
    try:
        return int(value.value) if isinstance(value, IntEnum) else int(value)
    except (TypeError, ValueError):
        return default


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    index = min(len(ordered) - 1, max(0, int(math.ceil(fraction * len(ordered))) - 1))
    return ordered[index]


def d842_action(model: NumpyPolicyModel, obs: Any) -> list[int]:
    """Match the frozen archive's NumPy ranking/count/sanitization path."""

    features = encode_observation(obs, model.feature_version)
    logits, count_logits, _ = model.predict(features)
    if not len(logits):
        return []
    # The frozen submission uses NumPy's default argsort; do not change kind.
    ranked = np.argsort(-logits).astype(int).tolist()
    minimum = int(obs.select.minCount)
    maximum = min(int(obs.select.maxCount), len(count_logits) - 1, len(ranked))
    desired = (
        maximum
        if minimum == maximum
        else minimum + int(np.argmax(count_logits[minimum : maximum + 1]))
    )
    return sanitize_selection(obs.select, ranked, desired)


def selected_by_stride(ordinal: int, *, limit: int, stride: int, offset: int) -> bool:
    """Return whether a zero-based trigger ordinal belongs to the bounded sample."""

    if limit <= 0 or ordinal < offset:
        return False
    return (ordinal - offset) % stride == 0 and (ordinal - offset) // stride < limit


def _assert_exact(path: Path, expected: str, label: str) -> str:
    actual = sha256_file(path)
    if actual != expected:
        raise AuditError(f"{label} hash mismatch: expected {expected}, got {actual}")
    return actual


def _resolve_within(root: Path, relative: str) -> Path:
    resolved_root = root.resolve()
    resolved = (resolved_root / relative).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise AuditError(f"replay escapes declared source root: {relative}") from exc
    return resolved


def load_development_units(bank: Path) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, str]]:
    """Open only the hash-locked development shard and validate every row."""

    manifest_path = bank / "manifest.json"
    development_path = bank / "development.jsonl.gz"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    development_hash = _assert_exact(
        development_path,
        FROZEN_DEVELOPMENT_SHA256,
        "development shard",
    )
    development = (manifest.get("splits") or {}).get("development") or {}
    if (
        manifest.get("bank_id") != FROZEN_BANK_ID
        or manifest.get("frozen_model_sha256") != FROZEN_MODEL_SHA256
        or manifest.get("expected_deck_canonical_sha256") != FROZEN_CANONICAL_DECK_SHA256
        or development.get("split") != "development"
        or development.get("shard") != "development.jsonl.gz"
        or str(development.get("shard_sha256") or "").upper() != FROZEN_DEVELOPMENT_SHA256
        or development.get("training_use") != "allowed"
        or bool(development.get("untouched"))
    ):
        raise AuditError("bank manifest is not the frozen development-only contract")

    rows: list[dict[str, Any]] = []
    with gzip.open(development_path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            row = json.loads(line)
            if (
                row.get("split") != "development"
                or row.get("frozen_model_sha256") != FROZEN_MODEL_SHA256
                or row.get("hero_deck_canonical_sha256") != FROZEN_CANONICAL_DECK_SHA256
                or not bool(row.get("required_labels_complete"))
            ):
                raise AuditError(f"development row {line_number} violates the frozen contract")
            rows.append(row)
    if len(rows) != int(development.get("units", -1)):
        raise AuditError("development row count does not match its manifest")
    rows.sort(key=lambda row: (str(row["episode_id"]), int(row["hero_seat"])))
    return rows, manifest, {
        "bank_manifest_sha256": sha256_file(manifest_path),
        "development_shard_sha256": development_hash,
    }


def verify_inputs(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any], tuple[int, ...], dict[str, Any]]:
    archive_hash = _assert_exact(args.archive, FROZEN_ARCHIVE_SHA256, "reference archive")
    model_hash = _assert_exact(args.model, FROZEN_MODEL_SHA256, "frozen d842 model")
    raw_deck_hash = _assert_exact(args.deck, FROZEN_RAW_DECK_SHA256, "raw deck")
    try:
        hero_deck = tuple(
            int(line)
            for line in args.deck.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    except (OSError, ValueError) as exc:
        raise AuditError(f"invalid deck: {exc}") from exc
    if len(hero_deck) != 60 or deck_hash(hero_deck) != FROZEN_CANONICAL_DECK_SHA256:
        raise AuditError("deck is not the exact frozen 60-card canonical list")

    units, manifest, bank_hashes = load_development_units(args.bank)
    engine_hashes: dict[str, str] = {}
    for name, expected in FROZEN_ENGINE_HASHES.items():
        engine_hashes[name] = _assert_exact(ROOT / "vendor" / "cg" / name, expected, f"engine {name}")

    replay_root = Path(manifest["source_replay_root"])
    replay_hash_rows = []
    for unit in units:
        replay_path = _resolve_within(replay_root, str(unit["replay_path"]))
        if replay_path.stat().st_size != int(unit["replay_bytes"]):
            raise AuditError(f"replay byte count mismatch: {unit['episode_id']}")
        actual = sha256_file(replay_path)
        if actual != str(unit["replay_sha256"]).upper():
            raise AuditError(f"replay hash mismatch: {unit['episode_id']}")
        replay_hash_rows.append(
            {
                "episode_id": str(unit["episode_id"]),
                "hero_seat": int(unit["hero_seat"]),
                "replay_sha256": actual,
            }
        )

    provenance = {
        "archive_sha256": archive_hash,
        "model_sha256": model_hash,
        "raw_deck_sha256": raw_deck_hash,
        "canonical_deck_sha256": deck_hash(hero_deck),
        "bank_id": manifest["bank_id"],
        **bank_hashes,
        "development_units": len(units),
        "replay_set_digest_sha256": canonical_sha256(replay_hash_rows),
        "engine_sha256": engine_hashes,
        "runtime_module_sha256": sha256_file(Path(runtime.__file__)),
    }
    return units, manifest, hero_deck, provenance


def _log_fingerprint(log: Any) -> str:
    return canonical_sha256(_jsonable(log))


def _taint_causes(
    root_obs: Any,
    child_obs: Any,
    *,
    root_player: int,
    terminal_win: bool,
) -> list[dict[str, str]]:
    """Mirror the director's non-configurable hidden-information taint rule."""

    causes: list[dict[str, str]] = []
    select = getattr(child_obs, "select", None)
    current = getattr(child_obs, "current", None)
    root_prizes = runtime._prize_counts(root_obs)
    child_prizes = runtime._prize_counts(child_obs)
    if root_prizes is None or child_prizes is None:
        causes.append({"reason": "invalid_prize_counts", "log": ""})
        final_prize_take = False
    else:
        opponent = 1 - root_player
        final_prize_take = (
            terminal_win
            and root_prizes[root_player] > 0
            and child_prizes[root_player] == 0
            and child_prizes[opponent] == root_prizes[opponent]
        )
        if child_prizes != root_prizes and not final_prize_take:
            causes.append({"reason": "nonterminal_or_opaque_prize_count_motion", "log": ""})
    if select is not None and getattr(select, "deck", None) is not None:
        causes.append({"reason": "selection_deck", "log": ""})
    if current is not None and getattr(current, "looking", None) is not None:
        causes.append({"reason": "looking_state", "log": ""})
    for log in (getattr(child_obs, "logs", None) or []):
        log_type = _integer(getattr(log, "type", None))
        fingerprint = _log_fingerprint(log)
        if log_type in runtime._RANDOM_LOG_TYPES:
            causes.append({"reason": f"random_log:{log_type}", "log": fingerprint})
            continue
        if log_type not in runtime._MOVE_LOG_TYPES:
            continue
        source = _integer(getattr(log, "fromArea", None))
        target = _integer(getattr(log, "toArea", None))
        owner = _integer(getattr(log, "playerIndex", None))
        areas = {source, target}
        if int(AreaType.DECK) in areas or int(AreaType.LOOKING) in areas:
            causes.append({"reason": "hidden_deck_or_looking_move", "log": fingerprint})
            continue
        if int(AreaType.PRIZE) in areas:
            ordinary_terminal_take = (
                final_prize_take
                and owner == root_player
                and source == int(AreaType.PRIZE)
                and target == int(AreaType.HAND)
            )
            if not ordinary_terminal_take:
                causes.append({"reason": "nonterminal_or_opaque_prize_move", "log": fingerprint})
                continue
        if int(AreaType.HAND) in areas and owner != root_player:
            causes.append({"reason": "opponent_hand_move", "log": fingerprint})
    return causes


class AuditedNativeBackend:
    """Transparent native backend wrapper with branch and cleanup evidence."""

    def __init__(self) -> None:
        self.inner = runtime._CgRuntimeSearchBackend()
        self.counts: Counter[str] = Counter()
        self.active: dict[int, str] = {}
        self.roots: dict[int, Any] = {}
        self.branch_events: list[dict[str, Any]] = []
        self.instrumentation_errors: list[str] = []

    @staticmethod
    def _state_id(state: Any) -> int:
        value = getattr(state, "searchId", None)
        if value is None:
            raise AuditError("native state is missing searchId")
        return int(value)

    def snapshot(self) -> dict[str, int]:
        return {
            **dict(self.counts),
            "branch_event_count": len(self.branch_events),
            "instrumentation_error_count": len(self.instrumentation_errors),
            "active_count": len(self.active),
        }

    def begin(self, obs: Any, determinization: Mapping[str, Sequence[int]]) -> Any:
        self.counts["begin_attempts"] += 1
        try:
            state = self.inner.begin(obs, determinization)
            search_id = self._state_id(state)
            if search_id in self.active:
                raise AuditError("native begin returned an already-active state ID")
            self.active[search_id] = "root"
            self.roots[search_id] = obs
            self.counts["begin_successes"] += 1
            return state
        except Exception:
            self.counts["begin_errors"] += 1
            raise

    def step(self, search_id: int, action: Sequence[int]) -> Any:
        self.counts["step_attempts"] += 1
        root_obs = self.roots.get(int(search_id))
        try:
            state = self.inner.step(int(search_id), action)
            child_id = self._state_id(state)
            if child_id in self.active:
                raise AuditError("native step returned an already-active state ID")
            self.active[child_id] = "child"
            self.counts["step_successes"] += 1
            try:
                if root_obs is None:
                    raise AuditError("instrumentation could not resolve native root")
                child_obs = state.observation
                root_player = int(root_obs.current.yourIndex)
                evidence = runtime._branch_evidence(root_obs, child_obs, root_player)
                terminal_win = evidence.result == root_player
                child_causes = _taint_causes(
                    root_obs,
                    child_obs,
                    root_player=root_player,
                    terminal_win=terminal_win,
                )
                root_causes = _taint_causes(
                    root_obs,
                    root_obs,
                    root_player=root_player,
                    terminal_win=False,
                )
                root_cause_logs = Counter(
                    (cause["reason"], cause["log"])
                    for cause in root_causes
                    if cause["log"]
                )
                preexisting = []
                remaining = root_cause_logs.copy()
                for cause in child_causes:
                    key = (cause["reason"], cause["log"])
                    if cause["log"] and remaining[key] > 0:
                        preexisting.append(cause)
                        remaining[key] -= 1
                root_logs = [_log_fingerprint(log) for log in (getattr(root_obs, "logs", None) or [])]
                child_logs = [_log_fingerprint(log) for log in (getattr(child_obs, "logs", None) or [])]
                child_current = child_obs.current
                turn_boundary_types = sorted(
                    {
                        _integer(getattr(log, "type", None))
                        for log in (getattr(child_obs, "logs", None) or [])
                        if _integer(getattr(log, "type", None)) in runtime._TURN_BOUNDARY_LOG_TYPES
                    }
                )
                self.branch_events.append(
                    {
                        "action": list(map(int, action)),
                        "result": int(evidence.result),
                        "terminal_win": terminal_win,
                        "same_turn": bool(evidence.same_turn),
                        "tainted": bool(evidence.tainted),
                        "public_digest": evidence.public_digest,
                        "root_turn": _integer(getattr(root_obs.current, "turn", None)),
                        "child_turn": _integer(getattr(child_current, "turn", None)),
                        "turn_boundary_log_types": turn_boundary_types,
                        "root_log_count": len(root_logs),
                        "child_log_count": len(child_logs),
                        "child_logs_start_with_root_logs": (
                            len(child_logs) >= len(root_logs)
                            and child_logs[: len(root_logs)] == root_logs
                        ),
                        "taint_reasons": [cause["reason"] for cause in child_causes],
                        "preexisting_root_taint_reasons": [
                            cause["reason"] for cause in preexisting
                        ],
                        "all_taint_causes_preexisting": bool(child_causes)
                        and len(preexisting) == len(child_causes),
                    }
                )
            except Exception as exc:
                self.instrumentation_errors.append(f"{type(exc).__name__}: {exc}")
            return state
        except Exception:
            self.counts["step_errors"] += 1
            raise

    def release(self, search_id: int) -> None:
        self.counts["release_attempts"] += 1
        try:
            self.inner.release(int(search_id))
            self.counts["release_successes"] += 1
            self.active.pop(int(search_id), None)
            self.roots.pop(int(search_id), None)
        except Exception:
            self.counts["release_errors"] += 1
            raise

    def end(self) -> None:
        self.counts["end_attempts"] += 1
        try:
            self.inner.end()
            self.counts["end_successes"] += 1
        except Exception:
            self.counts["end_errors"] += 1
            raise

    def cleanup_ok(self) -> bool:
        return (
            not self.active
            and not self.instrumentation_errors
            and self.counts["release_errors"] == 0
            and self.counts["end_errors"] == 0
            and self.counts["release_successes"]
            == self.counts["begin_successes"] + self.counts["step_successes"]
            and self.counts["end_attempts"] == self.counts["begin_attempts"]
        )


def _counter_delta(after: Mapping[str, int], before: Mapping[str, int]) -> dict[str, int]:
    return {
        key: int(after.get(key, 0)) - int(before.get(key, 0))
        for key in sorted(set(after) | set(before))
        if int(after.get(key, 0)) - int(before.get(key, 0))
    }


def summarize_branches(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    totals: Counter[str] = Counter()
    taint_reasons: Counter[str] = Counter()
    for event in events:
        totals["branches"] += 1
        if event["tainted"]:
            totals["tainted_branches"] += 1
        if event["all_taint_causes_preexisting"]:
            totals["tainted_only_by_preexisting_root_logs"] += 1
        if event["child_logs_start_with_root_logs"] and event["root_log_count"]:
            totals["branches_with_accumulated_root_log_prefix"] += 1
        if event["terminal_win"]:
            totals["terminal_win_branches"] += 1
            if event["same_turn"]:
                totals["same_turn_terminal_win_branches"] += 1
            else:
                totals["terminal_win_rejected_as_not_same_turn"] += 1
            if event["tainted"]:
                totals["tainted_terminal_win_branches"] += 1
            else:
                totals["clean_terminal_win_branches"] += 1
        for reason in event["taint_reasons"]:
            taint_reasons[str(reason)] += 1
    return {
        "totals": dict(sorted(totals.items())),
        "taint_reasons": dict(sorted(taint_reasons.items())),
        "all_native_branches_tainted": bool(events)
        and totals["tainted_branches"] == len(events),
    }


def _semantic(obs: Any, action: Sequence[int]) -> Any:
    # Match RuntimeProofDirector's public candidate view.  In particular, do
    # not leak hero-hand or identified-prize identities into audit semantics.
    semantic_obs = (
        runtime._candidate_public_view(obs)
        if hasattr(runtime, "_candidate_public_view")
        else obs
    )
    return json.loads(semantic_action_key(semantic_obs, action))


def _pass_digests(
    classification_rows: Sequence[Mapping[str, Any]],
    decision_rows: Sequence[Mapping[str, Any]],
) -> tuple[str, str]:
    """Hash deterministic evidence only; callers never pass latency fields."""

    return canonical_sha256(classification_rows), canonical_sha256(decision_rows)


def _classification_projection(row: Mapping[str, Any]) -> dict[str, Any]:
    """Keep policy classification but separate native RNG trace identities."""

    projected = dict(row)
    projected.pop("branch_events", None)
    return projected


def _native_trace_projection(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "episode_id": row.get("episode_id"),
        "hero_seat": row.get("hero_seat"),
        "replay_step_t": row.get("replay_step_t"),
        "trigger_ordinal": row.get("trigger_ordinal"),
        "branch_events": row.get("branch_events") or [],
    }


def run_pass(
    pass_index: int,
    *,
    args: argparse.Namespace,
    units: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
    hero_deck: Sequence[int],
) -> dict[str, Any]:
    model = NumpyPolicyModel(args.model)
    config = RuntimeProofConfig(
        worlds=args.worlds,
        max_candidates=args.max_candidates,
        timeout_seconds=args.timeout_ms / 1000.0,
        max_search_calls_per_game=args.max_search_calls_per_game,
        max_native_roots_per_game=args.max_native_roots_per_game,
        max_native_steps_per_game=args.max_native_steps_per_game,
        max_cumulative_seconds_per_game=args.max_cumulative_ms_per_game / 1000.0,
    )
    backend = AuditedNativeBackend()
    replay_root = Path(manifest["source_replay_root"])
    totals: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    trigger_reason_counts: Counter[str] = Counter()
    branch_totals: Counter[str] = Counter()
    taint_reason_counts: Counter[str] = Counter()
    latencies: list[float] = []
    execution_records: list[dict[str, Any]] = []
    changed_records: list[dict[str, Any]] = []
    classification_rows: list[dict[str, Any]] = []
    decision_rows: list[dict[str, Any]] = []
    winning_endpoint_records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    trigger_ordinal = 0
    started = time.perf_counter()

    for unit in units:
        totals["episodes"] += 1
        director = RuntimeProofDirector(hero_deck, config=config, backend=backend)
        # Explicitly exercise the public reset boundary once per episode.
        director.reset()
        totals["director_resets"] += 1
        replay_path = _resolve_within(replay_root, str(unit["replay_path"]))
        replay = json.loads(replay_path.read_text(encoding="utf-8"))
        decks = replay_decks(replay)
        hero_seat = int(unit["hero_seat"])
        if deck_hash(decks[hero_seat]) != FROZEN_CANONICAL_DECK_SHA256:
            raise AuditError(f"hero handshake deck mismatch: {unit['episode_id']}")

        episode_last_decision: dict[str, Any] | None = None
        for aligned in iter_replay_aligned_decisions(replay, hero_seat):
            totals["decisions"] += 1
            key = {
                "episode_id": str(unit["episode_id"]),
                "hero_seat": hero_seat,
                "replay_step_t": int(aligned.observation_step_t),
            }
            try:
                raw_obs = dict(aligned.observation)
                if not raw_obs.get("search_begin_input"):
                    raise AuditError("exact replay observation is missing search_begin_input")
                obs = to_observation_class(raw_obs)
                baseline = d842_action(model, obs)
                baseline_semantic = _semantic(obs, baseline)
                candidates = runtime._candidate_set(obs, tuple(baseline), config)
                candidate_rows = [
                    {
                        "reason": candidate.reason,
                        "semantic": json.loads(candidate.key),
                    }
                    for candidate in candidates
                ]
                trigger = len(candidates) > 1
                episode_last_decision = {
                    **key,
                    "trigger": trigger,
                    "candidate_reasons": [candidate.reason for candidate in candidates],
                    "select_type": _integer(getattr(obs.select, "type", None)),
                    "select_context": _integer(getattr(obs.select, "context", None)),
                    "hero_prizes_remaining": len(
                        getattr(obs.current.players[hero_seat], "prize", None) or []
                    ),
                }
                replay_exact = list(aligned.historical_action) == baseline
                replay_semantic_exact = _semantic(obs, aligned.historical_action) == baseline_semantic
                totals["historical_index_exact"] += int(replay_exact)
                totals["historical_semantic_exact"] += int(replay_semantic_exact)
                base_classification: dict[str, Any] = {
                    **key,
                    "public_state_digest": public_state_digest(obs),
                    "baseline_semantic": baseline_semantic,
                    "candidate_rows": candidate_rows,
                    "trigger": trigger,
                    "sampled": False,
                    "status": "not_triggered" if not trigger else "scanned_only",
                    "reason": "no_semantic_alternative" if not trigger else "stride_not_selected",
                    "error_type": None,
                    "coverage": 0,
                    "cleanup_ok": True,
                    "branch_summary": {"totals": {}, "taint_reasons": {}, "all_native_branches_tainted": False},
                }
                if not trigger:
                    totals["not_triggered"] += 1
                    classification_rows.append(base_classification)
                    continue

                current_ordinal = trigger_ordinal
                trigger_ordinal += 1
                totals["trigger_opportunities"] += 1
                for candidate in candidates:
                    if not candidate.is_baseline:
                        trigger_reason_counts[candidate.reason] += 1
                sampled = selected_by_stride(
                    current_ordinal,
                    limit=args.sample_size,
                    stride=args.stride,
                    offset=args.offset,
                )
                base_classification["trigger_ordinal"] = current_ordinal
                base_classification["sampled"] = sampled
                if not sampled:
                    classification_rows.append(base_classification)
                    continue

                totals["sampled"] += 1
                before_snapshot = backend.snapshot()
                branch_start = len(backend.branch_events)
                call_started = time.perf_counter()
                selected = director.choose(obs, baseline)
                latency_ms = (time.perf_counter() - call_started) * 1000.0
                latencies.append(latency_ms)
                telemetry = director.telemetry["last"]
                branch_events = backend.branch_events[branch_start:]
                branch_summary = summarize_branches(branch_events)
                for name, count in branch_summary["totals"].items():
                    branch_totals[name] += int(count)
                for name, count in branch_summary["taint_reasons"].items():
                    taint_reason_counts[name] += int(count)
                after_snapshot = backend.snapshot()
                native_delta = _counter_delta(after_snapshot, before_snapshot)
                cleanup_ok = (
                    backend.cleanup_ok()
                    and int(native_delta.get("active_count", 0)) == 0
                    and telemetry["reason"] != "cleanup_error"
                )
                selected_semantic = _semantic(obs, selected)
                changed = selected_semantic != baseline_semantic
                status_counts[str(telemetry["status"])] += 1
                reason_counts[str(telemetry["reason"])] += 1
                totals["overrides"] += int(changed)
                totals["cleanup_failures"] += int(not cleanup_ok)
                totals["all_branch_tainted_calls"] += int(
                    branch_summary["all_native_branches_tainted"]
                )
                totals["calls_with_terminal_branch"] += int(
                    branch_summary["totals"].get("terminal_win_branches", 0) > 0
                )
                totals["calls_with_same_turn_terminal_branch"] += int(
                    branch_summary["totals"].get("same_turn_terminal_win_branches", 0) > 0
                )
                totals["calls_with_terminal_rejected_not_same_turn"] += int(
                    branch_summary["totals"].get("terminal_win_rejected_as_not_same_turn", 0) > 0
                )

                deterministic_record = {
                    **key,
                    "trigger_ordinal": current_ordinal,
                    "public_state_digest": base_classification["public_state_digest"],
                    "baseline_semantic": baseline_semantic,
                    "selected_semantic": selected_semantic,
                    "changed": changed,
                    "status": str(telemetry["status"]),
                    "reason": str(telemetry["reason"]),
                    "error_type": telemetry["error_type"],
                    "candidate_count": int(telemetry["candidate_count"]),
                    "coverage": int(telemetry["coverage"]),
                    "cleanup_ok": cleanup_ok,
                    "native_delta": native_delta,
                    "branch_summary": branch_summary,
                    "branch_events": branch_events,
                }
                decision_rows.append(
                    {
                        **key,
                        "trigger_ordinal": current_ordinal,
                        "public_state_digest": base_classification["public_state_digest"],
                        "baseline_semantic": baseline_semantic,
                        "selected_semantic": selected_semantic,
                        "changed": changed,
                    }
                )
                base_classification.update(
                    {
                        "status": deterministic_record["status"],
                        "reason": deterministic_record["reason"],
                        "error_type": deterministic_record["error_type"],
                        "coverage": deterministic_record["coverage"],
                        "cleanup_ok": cleanup_ok,
                        "branch_summary": branch_summary,
                        "branch_events": branch_events,
                    }
                )
                classification_rows.append(base_classification)
                execution_record = {
                    **deterministic_record,
                    "baseline_action": list(baseline),
                    "selected_action": list(selected),
                    "latency_ms": latency_ms,
                }
                execution_records.append(execution_record)
                if changed:
                    changed_records.append(execution_record)
            except Exception as exc:
                totals["exceptions"] += 1
                error = {**key, "error": f"{type(exc).__name__}: {exc}"}
                errors.append(error)
                classification_rows.append(
                    {
                        **key,
                        "status": "audit_error",
                        "reason": "exception",
                        "error_type": type(exc).__name__,
                    }
                )

        # Outcome is consulted only after every decision has been classified;
        # it never affects candidate generation, stride selection, or search.
        if str(unit.get("outcome")) == "win":
            totals["winning_episodes"] += 1
            if episode_last_decision is None:
                totals["winning_episodes_missing_hero_decision"] += 1
            else:
                winning_endpoint_records.append(episode_last_decision)
                totals["winning_last_hero_decision_triggered"] += int(
                    episode_last_decision["trigger"]
                )
                totals["winning_last_hero_decision_no_semantic_alternative"] += int(
                    not episode_last_decision["trigger"]
                )

    deterministic_classifications = [
        _classification_projection(row) for row in classification_rows
    ]
    native_trace_rows = [
        _native_trace_projection(row)
        for row in classification_rows
        if row.get("sampled")
    ]
    classification_digest, decision_digest = _pass_digests(
        deterministic_classifications,
        decision_rows,
    )
    native_trace_digest = canonical_sha256(native_trace_rows)
    genuine_terminal_branches = int(branch_totals.get("terminal_win_branches", 0))
    zero_override_explained = bool(totals["overrides"] > 0 or genuine_terminal_branches == 0)
    return {
        "pass_index": pass_index,
        "totals": dict(sorted(totals.items())),
        "status_counts": dict(sorted(status_counts.items())),
        "reason_counts": dict(sorted(reason_counts.items())),
        "trigger_reason_counts": dict(sorted(trigger_reason_counts.items())),
        "branch_totals": dict(sorted(branch_totals.items())),
        "taint_reason_counts": dict(sorted(taint_reason_counts.items())),
        "native_totals": backend.snapshot(),
        "native_cleanup_ok": backend.cleanup_ok(),
        "latency_ms": {
            "count": len(latencies),
            "median": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
            "max": max(latencies, default=0.0),
        },
        "classification_digest_sha256": classification_digest,
        "decision_digest_sha256": decision_digest,
        "native_rng_order_trace_digest_sha256": native_trace_digest,
        "zero_override_explained_by_no_genuine_terminal_branch": zero_override_explained,
        "execution_records": execution_records,
        "changed_records": changed_records,
        "winning_terminal_endpoint_records": winning_endpoint_records,
        "errors": errors,
        "elapsed_seconds": time.perf_counter() - started,
        "_classification_rows": deterministic_classifications,
        "_decision_rows": decision_rows,
        "_native_trace_rows": native_trace_rows,
    }


def compare_passes(first: Mapping[str, Any], second: Mapping[str, Any]) -> dict[str, Any]:
    classification_match = (
        first["classification_digest_sha256"] == second["classification_digest_sha256"]
    )
    decision_match = first["decision_digest_sha256"] == second["decision_digest_sha256"]
    native_trace_match = (
        first["native_rng_order_trace_digest_sha256"]
        == second["native_rng_order_trace_digest_sha256"]
    )
    mismatches: list[dict[str, Any]] = []
    first_rows = first.get("_classification_rows") or []
    second_rows = second.get("_classification_rows") or []
    for index in range(max(len(first_rows), len(second_rows))):
        left = first_rows[index] if index < len(first_rows) else None
        right = second_rows[index] if index < len(second_rows) else None
        if left != right:
            mismatches.append(
                {
                    "row_index": index,
                    "pass_1_sha256": canonical_sha256(left),
                    "pass_2_sha256": canonical_sha256(right),
                    "episode_id": (left or right or {}).get("episode_id"),
                    "replay_step_t": (left or right or {}).get("replay_step_t"),
                    "pass_1_status": (left or {}).get("status"),
                    "pass_2_status": (right or {}).get("status"),
                    "pass_1_reason": (left or {}).get("reason"),
                    "pass_2_reason": (right or {}).get("reason"),
                }
            )
            if len(mismatches) >= 20:
                break
    return {
        "classification_digest_match": classification_match,
        "decision_digest_match": decision_match,
        "native_rng_order_trace_digest_match": native_trace_match,
        "required_repeatability_passed": classification_match and decision_match,
        "classification_mismatch_examples": mismatches,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--deck", type=Path, default=DEFAULT_DECK)
    parser.add_argument("--bank", type=Path, default=DEFAULT_BANK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sample-size", type=_nonnegative_int, default=100)
    parser.add_argument("--stride", type=_positive_int, default=17)
    parser.add_argument("--offset", type=_nonnegative_int, default=0)
    parser.add_argument("--worlds", type=_positive_int, default=2)
    parser.add_argument("--max-candidates", type=_positive_int, default=3)
    parser.add_argument("--timeout-ms", type=float, default=50.0)
    parser.add_argument("--max-search-calls-per-game", type=_positive_int, default=8)
    parser.add_argument("--max-native-roots-per-game", type=_positive_int, default=32)
    parser.add_argument("--max-native-steps-per-game", type=_positive_int, default=96)
    parser.add_argument("--max-cumulative-ms-per-game", type=float, default=1000.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not math.isfinite(args.timeout_ms) or args.timeout_ms <= 0:
        raise AuditError("timeout-ms must be finite and positive")
    if not math.isfinite(args.max_cumulative_ms_per_game) or args.max_cumulative_ms_per_game <= 0:
        raise AuditError("max-cumulative-ms-per-game must be finite and positive")

    started = time.perf_counter()
    units, manifest, hero_deck, provenance = verify_inputs(args)
    passes = [
        run_pass(
            pass_index,
            args=args,
            units=units,
            manifest=manifest,
            hero_deck=hero_deck,
        )
        for pass_index in (1, 2)
    ]
    comparison = compare_passes(passes[0], passes[1])
    for audit_pass in passes:
        audit_pass.pop("_classification_rows", None)
        audit_pass.pop("_decision_rows", None)
        audit_pass.pop("_native_trace_rows", None)

    errors = sum(len(audit_pass["errors"]) for audit_pass in passes)
    cleanup_ok = all(bool(audit_pass["native_cleanup_ok"]) for audit_pass in passes)
    terminal_coverage_ok = all(
        bool(audit_pass["zero_override_explained_by_no_genuine_terminal_branch"])
        for audit_pass in passes
    )
    status = (
        "passed"
        if (
            comparison["required_repeatability_passed"]
            and not errors
            and cleanup_ok
            and terminal_coverage_ok
        )
        else "failed_closed"
    )
    output = {
        "schema_version": 1,
        "status": status,
        "scope": {
            "split": "development",
            "calibration_read": False,
            "holdout_read": False,
            "native_search": True,
            "real_search_begin_input": True,
            "runtime_terminal_only_unchanged": True,
            "hidden_taint_rule_unchanged": True,
            "wired": False,
            "packaged": False,
            "uploaded": False,
        },
        "provenance": provenance,
        "config": {
            "passes": 2,
            "sample_size": args.sample_size,
            "stride": args.stride,
            "offset": args.offset,
            "worlds": args.worlds,
            "max_candidates": args.max_candidates,
            "timeout_ms": args.timeout_ms,
            "max_search_calls_per_game": args.max_search_calls_per_game,
            "max_native_roots_per_game": args.max_native_roots_per_game,
            "max_native_steps_per_game": args.max_native_steps_per_game,
            "max_cumulative_ms_per_game": args.max_cumulative_ms_per_game,
        },
        "repeatability": comparison,
        "terminal_coverage_requirement_passed": terminal_coverage_ok,
        "passes": passes,
        "elapsed_seconds": time.perf_counter() - started,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        "status": status,
        "output": str(args.output),
        "repeatability": comparison,
        "pass_totals": [audit_pass["totals"] for audit_pass in passes],
        "pass_reasons": [audit_pass["reason_counts"] for audit_pass in passes],
        "pass_branch_totals": [audit_pass["branch_totals"] for audit_pass in passes],
        "pass_latency_ms": [audit_pass["latency_ms"] for audit_pass in passes],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Outcome-blind capture and replay contracts for independent public states.

The engine's ``search_begin_input`` is an opaque, raw-memory-derived byte
string.  A captured artifact retains that string exactly.  It is never decoded,
normalized, masked, or regenerated for a measured replay.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Mapping

from .canonical import (
    canonical_json_bytes,
    hash_file,
    hash_json,
    sha256_bytes,
    write_canonical_json,
)
from .game import FixedAnchorAgent, _combination_count, _forced_order
from .adapters.native_backend import SeededGameBackend


CAPTURE_SCHEMA_VERSION = "captured-decision-state-1.1.0"
FROZEN_CAPTURE_SCHEMA_VERSION = "frozen-captured-decision-artifact-1.0.0"


@dataclass(frozen=True)
class CapturedDecisionState:
    schema_version: str
    state_id: str
    source_game_id: str
    source_environment_seed: int
    source_physical_seat: int
    source_play_order: int
    target_eligible_index: int
    observed_eligible_index: int
    history_prefix: tuple[dict[str, Any], ...]
    public_semantic_hash: str
    search_begin_input_hash: str
    search_begin_input_byte_count: int
    raw_state: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["history_prefix"] = list(self.history_prefix)
        return payload

    @property
    def artifact_hash(self) -> str:
        return hash_json(self.to_dict())

    @property
    def search_begin_input_bytes(self) -> bytes:
        """Return the exact captured opaque bytes after verifying their digest."""

        serialized = self.raw_state.get("search_begin_input")
        if not isinstance(serialized, str) or not serialized:
            raise RuntimeError("captured state lacks search_begin_input")
        try:
            opaque = serialized.encode("ascii")
        except UnicodeEncodeError as exc:
            raise RuntimeError("captured search_begin_input is not ASCII") from exc
        if len(opaque) != self.search_begin_input_byte_count:
            raise RuntimeError("captured search_begin_input byte count mismatch")
        if sha256_bytes(opaque) != self.search_begin_input_hash:
            raise RuntimeError("captured search_begin_input SHA-256 mismatch")
        return opaque

    def validate(self) -> None:
        if self.schema_version != CAPTURE_SCHEMA_VERSION:
            raise RuntimeError(f"unsupported captured-state schema: {self.schema_version}")
        if self.observed_eligible_index != self.target_eligible_index:
            raise RuntimeError("captured state is not the predeclared eligible ordinal")
        if hash_json(_public_state(self.raw_state)) != self.public_semantic_hash:
            raise RuntimeError("captured public semantic hash mismatch")
        self.search_begin_input_bytes

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CapturedDecisionState":
        expected = {field.name for field in fields(cls)}
        observed = set(map(str, value))
        if observed != expected:
            raise RuntimeError(
                "captured-state fields differ from schema: "
                f"missing={sorted(expected - observed)}, "
                f"unknown={sorted(observed - expected)}"
            )
        payload = dict(value)
        history = payload.get("history_prefix")
        if not isinstance(history, (list, tuple)):
            raise RuntimeError("captured history_prefix must be an array")
        payload["history_prefix"] = tuple(dict(item) for item in history)
        raw_state = payload.get("raw_state")
        if not isinstance(raw_state, Mapping):
            raise RuntimeError("captured raw_state must be an object")
        payload["raw_state"] = dict(raw_state)
        state = cls(**payload)
        state.validate()
        return state


def _public_state(raw: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in raw.items() if key != "search_begin_input"}


def capture_anchor_state(
    *,
    engine_path: str | Path,
    deck_path: str | Path,
    model_path: str | Path,
    source_environment_seed: int,
    target_eligible_index: int,
    physical_seat: int,
    play_order: int,
    max_decisions: int = 2_000,
) -> CapturedDecisionState:
    """Capture exactly one predeclared eligible state from one source game.

    Both seats follow the same fixed no-search anchor.  The target is an
    eligible-decision ordinal chosen before play; no value, action effect, or
    game outcome enters state selection.
    """

    if isinstance(target_eligible_index, bool) or not isinstance(target_eligible_index, int):
        raise ValueError("target_eligible_index must be an integer")
    if target_eligible_index < 0:
        raise ValueError("target_eligible_index cannot be negative")
    if physical_seat not in {0, 1} or play_order not in {0, 1}:
        raise ValueError("physical_seat and play_order must be binary")
    engine = SeededGameBackend(engine_path)
    anchor = FixedAnchorAgent(deck_path, model_path)
    battle_ptr = 0
    history: list[dict[str, Any]] = []
    eligible_index = 0
    try:
        battle_ptr, raw = engine.start(
            anchor.deck,
            anchor.deck,
            int(source_environment_seed),
        )
        for decision_index in range(max_decisions):
            from cg.api import SelectContext, to_observation_class

            observation = to_observation_class(raw)
            current = observation.current
            if current is not None and int(current.result) >= 0:
                raise RuntimeError(
                    "source game terminated before the frozen eligible-decision ordinal"
                )
            select = observation.select
            if select is None:
                raise RuntimeError("source game produced no selection")
            possible = _combination_count(
                len(select.option), int(select.minCount), int(select.maxCount)
            )
            is_forced_order = select.context == SelectContext.IS_FIRST
            if possible > 1 and not is_forced_order:
                if eligible_index == target_eligible_index:
                    serialized = raw.get("search_begin_input")
                    if not isinstance(serialized, str) or not serialized:
                        raise RuntimeError("captured state lacks search_begin_input")
                    state_id = f"state-{hash_json({'seed': source_environment_seed, 'target': target_eligible_index, 'seat': physical_seat, 'order': play_order})[:20]}"
                    source_game_id = f"source-{hash_json({'seed': source_environment_seed, 'seat': physical_seat, 'order': play_order})[:20]}"
                    return CapturedDecisionState(
                        schema_version=CAPTURE_SCHEMA_VERSION,
                        state_id=state_id,
                        source_game_id=source_game_id,
                        source_environment_seed=int(source_environment_seed),
                        source_physical_seat=physical_seat,
                        source_play_order=play_order,
                        target_eligible_index=target_eligible_index,
                        observed_eligible_index=eligible_index,
                        history_prefix=tuple(history),
                        public_semantic_hash=hash_json(_public_state(raw)),
                        search_begin_input_hash=sha256_bytes(serialized.encode("ascii")),
                        search_begin_input_byte_count=len(serialized.encode("ascii")),
                        raw_state=dict(raw),
                    )
                eligible_index += 1
            if is_forced_order:
                action = _forced_order(select, physical_seat, play_order)
            else:
                action = anchor(raw)
            history.append(
                {
                    "decision_index": decision_index,
                    "acting_seat": (
                        None if current is None else int(current.yourIndex)
                    ),
                    "public_state_hash": hash_json(_public_state(raw)),
                    "action": list(action),
                }
            )
            raw = engine.select(battle_ptr, action)
        raise RuntimeError("source game exceeded decision cap before frozen state")
    finally:
        if battle_ptr:
            engine.finish(battle_ptr)


def write_frozen_captured_state(
    path: str | Path,
    state: CapturedDecisionState,
) -> str:
    """Freeze one capture, including its exact opaque string, as canonical JSON.

    Returns the SHA-256 of the complete artifact file.  The embedded state hash
    independently binds every field, including the opaque byte digest/count and
    the unmodified ``raw_state`` string.
    """

    state.validate()
    payload = {
        "schema_version": FROZEN_CAPTURE_SCHEMA_VERSION,
        "captured_state_artifact_hash": state.artifact_hash,
        "captured_state": state.to_dict(),
    }
    return write_canonical_json(path, payload)


def load_frozen_captured_state(
    path: str | Path,
    *,
    expected_file_sha256: str | None = None,
) -> CapturedDecisionState:
    """Load a frozen capture and fail if either artifact or opaque bytes changed.

    Scientific replay callers must supply ``expected_file_sha256``.  Omitting
    it is supported only for inspection/recovery, and canonical byte encoding
    plus both embedded hashes are still mandatory.
    """

    artifact_path = Path(path)
    if expected_file_sha256 is not None and hash_file(artifact_path) != expected_file_sha256:
        raise RuntimeError("frozen captured-state file SHA-256 mismatch")
    try:
        artifact_bytes = artifact_path.read_bytes()
        payload = json.loads(artifact_bytes.decode("ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("cannot read frozen captured-state artifact") from exc
    if canonical_json_bytes(payload) != artifact_bytes:
        raise RuntimeError("frozen captured-state artifact is not canonical JSON bytes")
    if not isinstance(payload, Mapping) or set(payload) != {
        "schema_version",
        "captured_state_artifact_hash",
        "captured_state",
    }:
        raise RuntimeError("frozen captured-state wrapper differs from schema")
    if payload.get("schema_version") != FROZEN_CAPTURE_SCHEMA_VERSION:
        raise RuntimeError("unsupported frozen captured-state wrapper schema")
    captured = payload.get("captured_state")
    if not isinstance(captured, Mapping):
        raise RuntimeError("frozen captured-state wrapper lacks captured_state")
    state = CapturedDecisionState.from_dict(captured)
    if payload.get("captured_state_artifact_hash") != state.artifact_hash:
        raise RuntimeError("frozen captured-state embedded artifact hash mismatch")
    return state


def assert_semantic_replay(left: CapturedDecisionState, right: CapturedDecisionState) -> None:
    """Strictly compare two loads/replays of the *same frozen artifact*.

    Despite the historical function name, this is intentionally byte-strict:
    it is not the predicate for two independent engine recaptures.
    """

    left.validate()
    right.validate()
    field_names = tuple(field.name for field in fields(CapturedDecisionState))
    mismatched = [
        name for name in field_names if getattr(left, name) != getattr(right, name)
    ]
    if mismatched:
        raise RuntimeError(f"captured-state semantic replay mismatch: {mismatched}")


def assert_independent_recapture_semantics(
    left: CapturedDecisionState,
    right: CapturedDecisionState,
) -> None:
    """Compare independent recaptures without asserting opaque-byte identity.

    This predicate is limited to the public state and the deterministic source
    history that reached it.  Fixed-work state/action/work/status/cleanup output
    equivalence is a separate required executor gate.  Passing this function
    never permits replacing the already frozen opaque bytes with a recapture.
    """

    left.validate()
    right.validate()
    fields = (
        "state_id",
        "source_game_id",
        "source_environment_seed",
        "source_physical_seat",
        "source_play_order",
        "target_eligible_index",
        "observed_eligible_index",
        "history_prefix",
        "public_semantic_hash",
    )
    mismatched = [name for name in fields if getattr(left, name) != getattr(right, name)]
    if _public_state(left.raw_state) != _public_state(right.raw_state):
        mismatched.append("public_raw_state")
    if mismatched:
        raise RuntimeError(f"independent captured-state semantic mismatch: {mismatched}")

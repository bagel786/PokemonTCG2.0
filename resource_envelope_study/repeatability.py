"""Deterministic frozen-state repeatability-panel manifests.

The manifest is an execution contract, not an executor.  Each target-state row
binds a captured artifact, one agent seed, a resource envelope, a repeat, and an
independently restarted session.  Persistent rows additionally bind a frozen
history prefix and pseudo-sequence slot that an acquisition adapter must replay
before measuring the target state.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from itertools import product
from typing import Any, Iterable, Mapping, Sequence

from .canonical import derive_u32, derive_u64, deterministic_shuffle, hash_json


REPEAT_COUNT = 10
REQUIRED_EXCLUSION_BANKS = frozenset({"calibration", "gate", "final", "reserve"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RepeatabilityError(RuntimeError):
    """The frozen-state panel is incomplete, ambiguous, or seed-overlapping."""


@dataclass(frozen=True)
class FrozenStateSpec:
    """Immutable captured state plus its process-warmth history contract."""

    state_id: str
    source_game_id: str
    state_artifact_sha256: str
    state_seed: int
    history_prefix_sha256: str
    history_seed: int
    history_length: int
    pseudo_sequence_slot: int

    def validate(self, *, persistent_sequence_length: int) -> None:
        if not self.state_id or not self.source_game_id:
            raise ValueError("state and source-game IDs must be nonempty")
        _require_sha256(self.state_artifact_sha256, "state_artifact_sha256")
        _require_sha256(self.history_prefix_sha256, "history_prefix_sha256")
        _require_seed(self.state_seed, "state_seed")
        _require_seed(self.history_seed, "history_seed")
        if isinstance(self.history_length, bool) or not isinstance(self.history_length, int):
            raise ValueError("history_length must be an integer")
        if isinstance(self.pseudo_sequence_slot, bool) or not isinstance(
            self.pseudo_sequence_slot, int
        ):
            raise ValueError("pseudo_sequence_slot must be an integer")
        if self.history_length < 0 or self.history_length != self.pseudo_sequence_slot:
            raise ValueError("history length must equal the frozen pseudo-sequence slot")
        if not 0 <= self.pseudo_sequence_slot < persistent_sequence_length:
            raise ValueError("pseudo-sequence slot is outside the persistent-session bound")


@dataclass(frozen=True)
class EnvelopeSpec:
    """One predeclared load/lifecycle envelope."""

    envelope_id: str
    budget_mode: str
    load_condition: str
    lifecycle: str
    resource_profile_sha256: str

    def validate(self) -> None:
        if not self.envelope_id:
            raise ValueError("envelope_id must be nonempty")
        if self.budget_mode not in {"wall_clock", "fixed_work"}:
            raise ValueError("repeatability budget must be wall_clock or fixed_work")
        if self.load_condition not in {"idle", "loaded"}:
            raise ValueError("repeatability envelope load must be idle or loaded")
        if self.lifecycle not in {"fresh", "persistent"}:
            raise ValueError("repeatability lifecycle must be fresh or persistent")
        _require_sha256(self.resource_profile_sha256, "resource_profile_sha256")


@dataclass(frozen=True)
class RepeatabilityConfig:
    bank_id: str
    master_seed: int
    agents: tuple[str, ...]
    envelopes: tuple[EnvelopeSpec, ...]
    wall_clock_budget_ns: int
    fixed_work_by_agent: dict[str, int]
    target_state_count: int = 100
    repeats: int = REPEAT_COUNT
    load_batch_count: int = 20
    persistent_sequence_length: int = 8

    def validate(self) -> None:
        if not self.bank_id:
            raise ValueError("repeatability bank_id must be nonempty")
        _require_seed(self.master_seed, "master_seed", maximum=(1 << 64) - 1)
        if len(self.agents) != 3 or len(set(self.agents)) != 3:
            raise ValueError("repeatability panel requires exactly three unique agents")
        if any(not agent for agent in self.agents):
            raise ValueError("agent IDs must be nonempty")
        if not self.envelopes:
            raise ValueError("repeatability panel requires at least one envelope")
        for envelope in self.envelopes:
            envelope.validate()
        if len({envelope.envelope_id for envelope in self.envelopes}) != len(self.envelopes):
            raise ValueError("envelope IDs must be unique")
        cells = {
            (envelope.budget_mode, envelope.load_condition, envelope.lifecycle)
            for envelope in self.envelopes
        }
        if len(cells) != len(self.envelopes):
            raise ValueError("budget/load/lifecycle envelope cells must be unique")
        lifecycles = {envelope.lifecycle for envelope in self.envelopes}
        required_cells = set(
            product(
                ("wall_clock", "fixed_work"),
                ("idle", "loaded"),
                lifecycles,
            )
        )
        if cells != required_cells:
            raise ValueError(
                "envelopes must form budget_mode x load_condition x selected-lifecycle cells"
            )
        if isinstance(self.wall_clock_budget_ns, bool) or not isinstance(
            self.wall_clock_budget_ns, int
        ) or self.wall_clock_budget_ns <= 0:
            raise ValueError("wall_clock_budget_ns must be a positive integer")
        if set(self.fixed_work_by_agent) != set(self.agents):
            raise ValueError("fixed-work counts must name every and only panel agent")
        for agent, value in self.fixed_work_by_agent.items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"fixed-work count for {agent} must be a positive integer")
        if self.target_state_count <= 0:
            raise ValueError("target_state_count must be positive")
        if self.repeats != REPEAT_COUNT:
            raise ValueError(f"repeatability panel requires exactly {REPEAT_COUNT} repeats")
        if self.load_batch_count <= 0:
            raise ValueError("load_batch_count must be positive")
        if self.target_state_count * self.repeats < self.load_batch_count:
            raise ValueError("not enough state-repeat assignments to represent every load batch")
        if self.persistent_sequence_length <= 0:
            raise ValueError("persistent_sequence_length must be positive")


def _require_sha256(value: str, label: str) -> None:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 hex digest")


def _require_seed(value: int, label: str, *, maximum: int = (1 << 32) - 1) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise ValueError(f"{label} must be an integer in [0, {maximum}]")


def _normalize_exclusions(
    ledger: Mapping[str, Iterable[int]],
) -> dict[str, list[int]]:
    if not isinstance(ledger, Mapping):
        raise ValueError("seed exclusion ledger must be a mapping")
    missing = REQUIRED_EXCLUSION_BANKS - set(map(str, ledger))
    if missing:
        raise ValueError(f"seed exclusion ledger lacks required banks: {sorted(missing)}")
    normalized: dict[str, list[int]] = {}
    for raw_name, raw_values in sorted(ledger.items(), key=lambda item: str(item[0])):
        name = str(raw_name)
        if not name:
            raise ValueError("seed exclusion bank names must be nonempty")
        values: list[int] = []
        for value in raw_values:
            _require_seed(value, f"excluded seed in {name}", maximum=(1 << 64) - 1)
            values.append(int(value))
        normalized[name] = sorted(set(values))
    return normalized


def _assert_unique(values: Iterable[int], label: str) -> set[int]:
    materialized = list(map(int, values))
    if len(materialized) != len(set(materialized)):
        raise RepeatabilityError(f"seed collision within {label} stream")
    return set(materialized)


def _assert_stream_disjoint(streams: Mapping[str, Iterable[int]]) -> None:
    owner: dict[int, str] = {}
    for stream, values in streams.items():
        unique = _assert_unique(values, stream)
        for value in unique:
            prior = owner.get(value)
            if prior is not None:
                raise RepeatabilityError(
                    f"seed value {value} collides across {prior} and {stream}"
                )
            owner[value] = stream


def _assert_excluded(seeds: Iterable[int], ledger: Mapping[str, Sequence[int]]) -> None:
    used = set(map(int, seeds))
    for bank, values in ledger.items():
        overlap = sorted(used & set(map(int, values)))
        if overlap:
            raise RepeatabilityError(
                f"repeatability seeds overlap excluded bank {bank}: {overlap[:5]}"
            )


def build_repeatability_manifest(
    config: RepeatabilityConfig,
    states: Sequence[FrozenStateSpec],
    *,
    excluded_seed_ledger: Mapping[str, Iterable[int]],
) -> dict[str, Any]:
    """Build the exact state x agent x envelope x ten-repeat panel."""

    config.validate()
    ordered_states = sorted(states, key=lambda state: state.state_id)
    if len(ordered_states) != config.target_state_count:
        raise ValueError(
            f"received {len(ordered_states)} states, expected {config.target_state_count}"
        )
    for state in ordered_states:
        state.validate(persistent_sequence_length=config.persistent_sequence_length)
    if len({state.state_id for state in ordered_states}) != len(ordered_states):
        raise ValueError("repeatability state IDs must be unique")
    if len({state.source_game_id for state in ordered_states}) != len(ordered_states):
        raise ValueError("repeatability permits at most one state per source game")
    if len({state.state_seed for state in ordered_states}) != len(ordered_states):
        raise ValueError("repeatability state seeds must be unique")
    if len({state.history_seed for state in ordered_states}) != len(ordered_states):
        raise ValueError("repeatability history seeds must be unique")

    exclusions = _normalize_exclusions(excluded_seed_ledger)
    agent_seed_by_key = {
        (state.state_id, agent_id): derive_u32(
            config.master_seed,
            f"repeatability-agent:{config.bank_id}",
            state.state_id,
            agent_id,
        )
        for state in ordered_states
        for agent_id in config.agents
    }
    load_seed_by_batch = {
        batch_index: derive_u32(
            config.master_seed,
            f"repeatability-load:{config.bank_id}",
            batch_index,
        )
        for batch_index in range(config.load_batch_count)
    }
    randomized_batches = deterministic_shuffle(
        list(range(config.load_batch_count)),
        config.master_seed,
        f"repeatability-load-order-assignment:{config.bank_id}",
    )
    load_order_by_batch = {
        batch_index: (
            "idle_then_loaded" if assignment_index % 2 == 0 else "loaded_then_idle"
        )
        for assignment_index, batch_index in enumerate(randomized_batches)
    }

    rows: list[dict[str, Any]] = []
    schedule_seeds: list[int] = []
    session_seeds: list[int] = []
    for state_index, state in enumerate(ordered_states):
        for repeat_index in range(config.repeats):
            assignment_index = state_index * config.repeats + repeat_index
            load_batch_index = assignment_index % config.load_batch_count
            load_batch_id = f"{config.bank_id}-load-pair-{load_batch_index:03d}"
            load_seed = load_seed_by_batch[load_batch_index]
            load_period_order = load_order_by_batch[load_batch_index]
            for agent_id, envelope in product(config.agents, config.envelopes):
                agent_seed = agent_seed_by_key[(state.state_id, agent_id)]
                session_seed = derive_u64(
                    config.master_seed,
                    f"repeatability-session:{config.bank_id}",
                    state.state_id,
                    agent_id,
                    envelope.envelope_id,
                    repeat_index,
                )
                schedule_seed = derive_u64(
                    config.master_seed,
                    f"repeatability-schedule:{config.bank_id}",
                    state.state_id,
                    agent_id,
                    envelope.envelope_id,
                    repeat_index,
                )
                session_seeds.append(session_seed)
                schedule_seeds.append(schedule_seed)
                session_id = (
                    f"{config.bank_id}-session-"
                    f"{hash_json({'state': state.state_id, 'agent': agent_id, 'envelope': envelope.envelope_id, 'repeat': repeat_index})[:20]}"
                )
                rows.append(
                    {
                        "schema_version": "repeatability-row-1.0.0",
                        "repeatability_case_id": "",
                        "bank_id": config.bank_id,
                        "inference_unit_id": state.state_id,
                        "state_id": state.state_id,
                        "source_game_id": state.source_game_id,
                        "state_artifact_sha256": state.state_artifact_sha256,
                        "state_seed": state.state_seed,
                        "history_prefix_sha256": state.history_prefix_sha256,
                        "history_seed": state.history_seed,
                        "history_length": state.history_length,
                        "pseudo_sequence_slot": state.pseudo_sequence_slot,
                        "sequence_index": state.pseudo_sequence_slot,
                        "agent_id": agent_id,
                        "agent_seed": agent_seed,
                        "envelope_id": envelope.envelope_id,
                        "resource_profile_sha256": envelope.resource_profile_sha256,
                        "load_condition": envelope.load_condition,
                        "lifecycle": envelope.lifecycle,
                        "budget_mode": envelope.budget_mode,
                        "requested_budget_ns": (
                            config.wall_clock_budget_ns
                            if envelope.budget_mode == "wall_clock"
                            else None
                        ),
                        "requested_work_units": (
                            config.fixed_work_by_agent[agent_id]
                            if envelope.budget_mode == "fixed_work"
                            else None
                        ),
                        "repeat_index": repeat_index,
                        "session_id": session_id,
                        "process_instance_id": session_id,
                        "session_seed": session_seed,
                        "schedule_seed": schedule_seed,
                        "load_batch_id": load_batch_id,
                        "load_seed": load_seed,
                        "load_period_order": load_period_order,
                        "execution_index": -1,
                    }
                )

    streams = {
        "master": [config.master_seed],
        "state": [state.state_seed for state in ordered_states],
        "history": [state.history_seed for state in ordered_states],
        "agent": list(agent_seed_by_key.values()),
        "load": list(load_seed_by_batch.values()),
        "session": session_seeds,
        "schedule": schedule_seeds,
    }
    _assert_stream_disjoint(streams)
    all_used = {seed for values in streams.values() for seed in values}
    _assert_excluded(all_used, exclusions)

    rows_by_batch: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        rows_by_batch[str(row["load_batch_id"])].append(row)
    ordered_rows: list[dict[str, Any]] = []
    batch_ids = deterministic_shuffle(
        sorted(rows_by_batch),
        config.master_seed,
        f"repeatability-batch-order:{config.bank_id}",
    )
    for batch_id in batch_ids:
        batch_rows = rows_by_batch[batch_id]
        period_order = str(batch_rows[0]["load_period_order"])
        condition_order = (
            ("idle", "loaded")
            if period_order == "idle_then_loaded"
            else ("loaded", "idle")
        )
        for condition in condition_order:
            period_rows = [row for row in batch_rows if row["load_condition"] == condition]
            ordered_rows.extend(
                deterministic_shuffle(
                    period_rows,
                    config.master_seed,
                    f"repeatability-within:{config.bank_id}:{batch_id}:{condition}",
                )
            )

    for execution_index, row in enumerate(ordered_rows):
        row["execution_index"] = execution_index
        identity = {key: value for key, value in row.items() if key != "repeatability_case_id"}
        row["repeatability_case_id"] = f"repeat-{hash_json(identity)[:24]}"

    state_inventory = [asdict(state) for state in ordered_states]
    manifest: dict[str, Any] = {
        "schema_version": "repeatability-manifest-1.0.0",
        "config": asdict(config),
        "design": {
            "inference_unit": "frozen_state",
            "factorial": "state x agent x (budget x load x lifecycle envelope) x repeat",
            "expected_rows": (
                config.target_state_count
                * len(config.agents)
                * len(config.envelopes)
                * config.repeats
            ),
            "one_state_per_source_game": True,
            "independently_restarted_session_per_row": True,
            "persistent_history_required": True,
        },
        "states": state_inventory,
        "state_inventory_hash": hash_json(state_inventory),
        "excluded_seed_ledger": exclusions,
        "excluded_seed_ledger_hash": hash_json(exclusions),
        "seed_inventory": {name: sorted(values) for name, values in streams.items()},
        "rows": ordered_rows,
    }
    manifest["content_hash"] = hash_json(manifest)
    validate_repeatability_manifest(manifest)
    return manifest


def verify_repeatability_content_hash(manifest: Mapping[str, Any]) -> None:
    supplied = manifest.get("content_hash")
    if not isinstance(supplied, str):
        raise RepeatabilityError("repeatability manifest lacks content_hash")
    payload = dict(manifest)
    payload.pop("content_hash", None)
    expected = hash_json(payload)
    if supplied != expected:
        raise RepeatabilityError(
            f"repeatability content hash mismatch: supplied={supplied}, expected={expected}"
        )


def validate_repeatability_manifest(manifest: Mapping[str, Any]) -> None:
    verify_repeatability_content_hash(manifest)
    config_data = dict(manifest.get("config", {}))
    config_data["envelopes"] = tuple(
        EnvelopeSpec(**dict(value)) for value in config_data.get("envelopes", [])
    )
    config_data["agents"] = tuple(config_data.get("agents", []))
    config = RepeatabilityConfig(**config_data)
    config.validate()
    states = [FrozenStateSpec(**dict(value)) for value in manifest.get("states", [])]
    if len(states) != config.target_state_count:
        raise RepeatabilityError("repeatability state inventory has the wrong cardinality")
    for state in states:
        state.validate(persistent_sequence_length=config.persistent_sequence_length)
    if len({state.state_id for state in states}) != len(states):
        raise RepeatabilityError("repeatability state IDs are not unique")
    if len({state.source_game_id for state in states}) != len(states):
        raise RepeatabilityError("more than one state came from a source game")
    if manifest.get("state_inventory_hash") != hash_json([asdict(state) for state in states]):
        raise RepeatabilityError("repeatability state inventory hash mismatch")

    rows = list(manifest.get("rows", []))
    expected_count = (
        len(states) * len(config.agents) * len(config.envelopes) * config.repeats
    )
    if len(rows) != expected_count:
        raise RepeatabilityError(
            f"repeatability row count {len(rows)} does not equal {expected_count}"
        )
    state_by_id = {state.state_id: state for state in states}
    envelope_by_id = {envelope.envelope_id: envelope for envelope in config.envelopes}
    expected_keys = set(
        product(
            state_by_id,
            config.agents,
            envelope_by_id,
            range(config.repeats),
        )
    )
    observed_keys: set[tuple[str, str, str, int]] = set()
    agent_seed_by_key: dict[tuple[str, str], set[int]] = defaultdict(set)
    load_assignment_by_state_repeat: dict[tuple[str, int], set[tuple[str, int]]] = defaultdict(set)
    load_seed_by_batch: dict[str, set[int]] = defaultdict(set)
    state_seed_by_id: dict[str, set[int]] = defaultdict(set)
    history_seed_by_id: dict[str, set[int]] = defaultdict(set)
    for row in rows:
        key = (
            str(row["state_id"]),
            str(row["agent_id"]),
            str(row["envelope_id"]),
            int(row["repeat_index"]),
        )
        if key in observed_keys:
            raise RepeatabilityError(f"duplicate repeatability assignment: {key}")
        observed_keys.add(key)
        state = state_by_id.get(key[0])
        envelope = envelope_by_id.get(key[2])
        if state is None or envelope is None:
            raise RepeatabilityError("repeatability row references unknown state/envelope")
        if row.get("inference_unit_id") != state.state_id:
            raise RepeatabilityError("state is not retained as the inference unit")
        for field in (
            "source_game_id",
            "state_artifact_sha256",
            "state_seed",
            "history_prefix_sha256",
            "history_seed",
            "history_length",
            "pseudo_sequence_slot",
        ):
            if row.get(field) != getattr(state, field):
                raise RepeatabilityError(f"row state provenance mismatch in {field}")
        if int(row.get("sequence_index")) != state.pseudo_sequence_slot:
            raise RepeatabilityError("pseudo and execution sequence slots disagree")
        if (
            row.get("budget_mode") != envelope.budget_mode
            or row.get("load_condition") != envelope.load_condition
            or row.get("lifecycle") != envelope.lifecycle
            or row.get("resource_profile_sha256") != envelope.resource_profile_sha256
        ):
            raise RepeatabilityError("row envelope differs from its frozen envelope spec")
        if envelope.budget_mode == "fixed_work":
            if row.get("requested_budget_ns") is not None:
                raise RepeatabilityError("fixed-work repeatability row carries a deadline")
            if int(row.get("requested_work_units")) != config.fixed_work_by_agent[key[1]]:
                raise RepeatabilityError("repeatability row has the wrong fixed-work count")
        else:
            if row.get("requested_work_units") is not None:
                raise RepeatabilityError("wall-clock repeatability row carries a work count")
            if int(row.get("requested_budget_ns")) != config.wall_clock_budget_ns:
                raise RepeatabilityError("repeatability row has the wrong wall-clock budget")
        if row.get("session_id") != row.get("process_instance_id"):
            raise RepeatabilityError("session and process-instance IDs disagree")
        agent_seed_by_key[(key[0], key[1])].add(int(row["agent_seed"]))
        state_seed_by_id[key[0]].add(int(row["state_seed"]))
        history_seed_by_id[key[0]].add(int(row["history_seed"]))
        load_assignment_by_state_repeat[(key[0], key[3])].add(
            (str(row["load_batch_id"]), int(row["load_seed"]))
        )
        load_seed_by_batch[str(row["load_batch_id"])].add(int(row["load_seed"]))
    if observed_keys != expected_keys:
        raise RepeatabilityError("repeatability factorial is incomplete")
    if any(len(values) != 1 for values in agent_seed_by_key.values()):
        raise RepeatabilityError("agent seed changes across repeats or envelopes")
    if any(len(values) != 1 for values in load_assignment_by_state_repeat.values()):
        raise RepeatabilityError("matched envelopes do not share a load assignment")
    if any(len(values) != 1 for values in load_seed_by_batch.values()):
        raise RepeatabilityError("a load batch has multiple load seeds")
    if any(len(values) != 1 for values in state_seed_by_id.values()):
        raise RepeatabilityError("state seed changes across panel rows")
    if any(len(values) != 1 for values in history_seed_by_id.values()):
        raise RepeatabilityError("history seed changes across panel rows")

    case_ids = [str(row["repeatability_case_id"]) for row in rows]
    session_ids = [str(row["session_id"]) for row in rows]
    if len(case_ids) != len(set(case_ids)):
        raise RepeatabilityError("repeatability case IDs are not unique")
    if len(session_ids) != len(set(session_ids)):
        raise RepeatabilityError("repeatability sessions are not independently restarted")
    if sorted(int(row["execution_index"]) for row in rows) != list(range(len(rows))):
        raise RepeatabilityError("repeatability execution indexes are not a bijection")
    if len(load_seed_by_batch) != config.load_batch_count:
        raise RepeatabilityError("repeatability manifest does not represent every load batch")
    order_by_batch: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        order_by_batch[str(row["load_batch_id"])].add(str(row["load_period_order"]))
    if any(len(values) != 1 for values in order_by_batch.values()):
        raise RepeatabilityError("a load batch has multiple AB/BA assignments")
    order_counts = defaultdict(int)
    for values in order_by_batch.values():
        order_counts[next(iter(values))] += 1
    if abs(order_counts["idle_then_loaded"] - order_counts["loaded_then_idle"]) > 1:
        raise RepeatabilityError("AB/BA load-period assignment is not balanced")

    exclusions = _normalize_exclusions(manifest.get("excluded_seed_ledger", {}))
    streams = {
        "master": [config.master_seed],
        "state": [state.state_seed for state in states],
        "history": [state.history_seed for state in states],
        "agent": [next(iter(values)) for values in agent_seed_by_key.values()],
        "load": [next(iter(values)) for values in load_seed_by_batch.values()],
        "session": [int(row["session_seed"]) for row in rows],
        "schedule": [int(row["schedule_seed"]) for row in rows],
    }
    _assert_stream_disjoint(streams)
    _assert_excluded(
        {seed for values in streams.values() for seed in values},
        exclusions,
    )
    expected_inventory = {name: sorted(values) for name, values in streams.items()}
    if manifest.get("seed_inventory") != expected_inventory:
        raise RepeatabilityError("repeatability seed inventory does not reconcile")
    if manifest.get("design", {}).get("expected_rows") != expected_count:
        raise RepeatabilityError("repeatability design row count does not reconcile")

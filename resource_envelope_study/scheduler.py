"""Deterministic matched-block schedules with explicit assignment hierarchy."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from itertools import product
import re
from typing import Any, Iterable

from .canonical import derive_u32, derive_u64, deterministic_shuffle, hash_json


BUDGET_MODES = ("wall_clock", "fixed_work")
LOAD_CONDITIONS = ("idle", "loaded")
LIFECYCLES = ("fresh", "persistent")
REQUIRED_ARTIFACT_HASH_KEYS = frozenset(
    {
        "engine_binary",
        "engine_source",
        "hero_deck",
        "hero_model",
        "opponent_deck",
        "opponent_model",
        "run_config",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _strict_positive_integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


@dataclass(frozen=True)
class ScheduleConfig:
    phase: str
    master_seed: int
    agents: tuple[str, ...]
    block_count: int
    paired_load_batches: int
    minimum_persistent_sessions: int
    persistent_sequence_length: int
    wall_clock_budget_ns: int | None = None
    fixed_work_by_agent: dict[str, int] | None = None
    artifact_hashes: dict[str, str] | None = None

    def validate(self) -> None:
        if self.phase not in {"smoke", "pilot", "final"}:
            raise ValueError(f"unsupported phase: {self.phase}")
        if len(self.agents) < 3:
            raise ValueError("the primary study requires at least three agents")
        if len(set(self.agents)) != len(self.agents):
            raise ValueError("agent identifiers must be unique")
        _strict_positive_integer(self.block_count, "block_count")
        _strict_positive_integer(self.paired_load_batches, "paired_load_batches")
        _strict_positive_integer(
            self.minimum_persistent_sessions, "minimum_persistent_sessions"
        )
        _strict_positive_integer(
            self.persistent_sequence_length, "persistent_sequence_length"
        )
        if isinstance(self.master_seed, bool) or not isinstance(self.master_seed, int):
            raise ValueError("master_seed must be an integer")
        if self.wall_clock_budget_ns is not None:
            _strict_positive_integer(self.wall_clock_budget_ns, "wall_clock_budget_ns")
        if self.phase in {"pilot", "final"}:
            if self.paired_load_batches < 20:
                raise ValueError(
                    f"{self.phase} schedule requires at least 20 paired load batches"
                )
            if self.minimum_persistent_sessions < 20:
                raise ValueError(
                    f"{self.phase} schedule requires at least 20 persistent sessions per cell"
                )
            if self.persistent_sequence_length < 2:
                raise ValueError(
                    f"{self.phase} schedule requires persistent sequences of length at least two"
                )
            if self.block_count < 4 * self.paired_load_batches:
                raise ValueError(
                    f"{self.phase} schedule requires at least four blocks per paired load batch"
                )
            if self.wall_clock_budget_ns is None or not self.fixed_work_by_agent:
                raise ValueError(
                    f"{self.phase} schedule requires frozen time and fixed-work budgets"
                )
            if not self.artifact_hashes:
                raise ValueError(f"{self.phase} schedule requires frozen artifact hashes")
            if set(self.artifact_hashes) != REQUIRED_ARTIFACT_HASH_KEYS:
                raise ValueError(
                    f"{self.phase} artifact hashes must contain exactly "
                    f"{sorted(REQUIRED_ARTIFACT_HASH_KEYS)}"
                )
        if self.fixed_work_by_agent is not None:
            if set(self.fixed_work_by_agent) != set(self.agents):
                raise ValueError("fixed-work calibration must name every and only scheduled agent")
            for agent_id, value in self.fixed_work_by_agent.items():
                _strict_positive_integer(value, f"fixed_work_by_agent[{agent_id!r}]")
        if self.artifact_hashes is not None:
            invalid = {
                key: value
                for key, value in self.artifact_hashes.items()
                if not isinstance(key, str)
                or not isinstance(value, str)
                or _SHA256_RE.fullmatch(value) is None
            }
            if invalid:
                raise ValueError(f"invalid SHA-256 artifact hashes: {sorted(invalid)}")


def _base_assignments(config: ScheduleConfig) -> list[dict[str, Any]]:
    """Build lifecycle-matched cases before process/session allocation."""

    cases: list[dict[str, Any]] = []
    # Force exact/near-exact AB/BA balance rather than relying on hash parity.
    batch_indexes = list(range(config.paired_load_batches))
    ordered_for_period = deterministic_shuffle(
        batch_indexes, config.master_seed, "load-period-balance"
    )
    idle_first_count = (config.paired_load_batches + 1) // 2
    idle_first = set(ordered_for_period[:idle_first_count])
    for block_index in range(config.block_count):
        block_id = f"{config.phase}-block-{block_index:05d}"
        # Four distinct strata: physical seat x actual first/second play order.
        stratum = block_index % 4
        physical_seat = stratum % 2
        play_order = stratum // 2
        replicate = block_index // 4
        # Spread every seat/order stratum across batches.  The former modulo
        # assignment made batch and stratum perfectly confounded whenever the
        # batch count was divisible by four.
        stratum_offset = derive_u64(config.master_seed, "batch_stratum_offset", stratum) % config.paired_load_batches
        load_batch_index = (replicate + stratum_offset) % config.paired_load_batches
        load_batch_id = f"{config.phase}-load-pair-{load_batch_index:03d}"
        load_period_order = (
            "idle_then_loaded" if load_batch_index in idle_first else "loaded_then_idle"
        )
        environment_seed = derive_u32(config.master_seed, "environment", block_id)
        schedule_seed = derive_u64(config.master_seed, "schedule", block_id)
        load_seed = derive_u32(config.master_seed, "load", load_batch_id)
        for agent_id, budget_mode, load_condition in product(
            config.agents, BUDGET_MODES, LOAD_CONDITIONS
        ):
            pair_id = f"{block_id}:{agent_id}:{budget_mode}:{load_condition}"
            sequence_pair_id = f"{block_id}:{agent_id}:{budget_mode}"
            agent_seed = derive_u32(config.master_seed, "agent", block_id, agent_id)
            for lifecycle in LIFECYCLES:
                cases.append(
                    {
                        "schema_version": "schedule-row-1.0.0",
                        "phase": config.phase,
                        "case_id": "",
                        "block_id": block_id,
                        "block_index": block_index,
                        "agent_id": agent_id,
                        "budget_mode": budget_mode,
                        "load_condition": load_condition,
                        "lifecycle": lifecycle,
                        "physical_seat": physical_seat,
                        "play_order": play_order,
                        "environment_seed": environment_seed,
                        "agent_seed": agent_seed,
                        "schedule_seed": schedule_seed,
                        "load_seed": load_seed,
                        "load_batch_id": load_batch_id,
                        "load_period_order": load_period_order,
                        "lifecycle_pair_id": pair_id,
                        "sequence_pair_id": sequence_pair_id,
                        "session_bundle_id": "",
                        "lifecycle_id": "",
                        "process_instance_id": "",
                        "sequence_index": -1,
                        "execution_index": -1,
                        "requested_budget_ns": (
                            config.wall_clock_budget_ns if budget_mode == "wall_clock" else None
                        ),
                        "requested_work_units": (
                            (config.fixed_work_by_agent or {}).get(agent_id)
                            if budget_mode == "fixed_work"
                            else None
                        ),
                    }
                )
    return cases


def build_schedule(config: ScheduleConfig) -> dict[str, Any]:
    """Return a canonicalizable schedule manifest.

    Fresh and persistent cases receive the same pseudo-sequence slot.  A fresh
    case nevertheless has a unique process ID; a persistent process serves no
    more than ``persistent_sequence_length`` cases and must reset all
    scientific state between them.
    """

    config.validate()
    rows = _base_assignments(config)
    # Sessions are nested within a paired load batch and load period.  A
    # process therefore never leaks warm state from idle into loaded (or vice
    # versa), and the resampling hierarchy is executable rather than crossed.
    # A common block bundle and sequence slot are copied to every
    # agent x budget x load x lifecycle cell.  Condition-specific persistent
    # PIDs remain distinct, but warmth position is exactly matched and the
    # planned load-pair -> bundle -> block hierarchy is real.
    blocks_by_batch: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        if row["agent_id"] == config.agents[0] and row["budget_mode"] == BUDGET_MODES[0]:
            if row["load_condition"] == LOAD_CONDITIONS[0] and row["lifecycle"] == LIFECYCLES[0]:
                blocks_by_batch[row["load_batch_id"]].append(row["block_id"])
    block_slot: dict[str, tuple[str, int]] = {}
    for batch_id, block_ids in sorted(blocks_by_batch.items()):
        ordered_blocks = deterministic_shuffle(
            sorted(set(block_ids)),
            config.master_seed,
            f"persistent-bundle-order:{batch_id}",
        )
        for offset in range(0, len(ordered_blocks), config.persistent_sequence_length):
            bundle_index = offset // config.persistent_sequence_length
            bundle_id = f"{config.phase}-bundle-{batch_id}-{bundle_index:03d}"
            for sequence_index, block_id in enumerate(
                ordered_blocks[offset : offset + config.persistent_sequence_length]
            ):
                block_slot[block_id] = (bundle_id, sequence_index)

    for row in rows:
        bundle_id, sequence_index = block_slot[row["block_id"]]
        row["session_bundle_id"] = bundle_id
        row["sequence_index"] = sequence_index
        if row["lifecycle"] == "persistent":
            process_id = (
                f"{bundle_id}:{row['agent_id']}:{row['budget_mode']}:"
                f"{row['load_condition']}"
            )
            row["lifecycle_id"] = process_id
            row["process_instance_id"] = process_id
        else:
            process_id = f"{config.phase}-fresh-{hash_json(row['lifecycle_pair_id'])[:16]}"
            row["lifecycle_id"] = process_id
            row["process_instance_id"] = process_id

    # A load pair is an independently launched loaded episode and its paired
    # idle period.  AB/BA is frozen per pair; execution is randomized within a
    # period, never by looking at outcomes.
    ordered: list[dict[str, Any]] = []
    by_batch: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_batch[row["load_batch_id"]].append(row)
    batch_ids = deterministic_shuffle(sorted(by_batch), config.master_seed, "load-batch-order")
    for batch_id in batch_ids:
        batch_rows = by_batch[batch_id]
        period_order = batch_rows[0]["load_period_order"]
        load_order = LOAD_CONDITIONS if period_order == "idle_then_loaded" else tuple(reversed(LOAD_CONDITIONS))
        for load_condition in load_order:
            period_rows = [row for row in batch_rows if row["load_condition"] == load_condition]
            execution_units: list[list[dict[str, Any]]] = []
            persistent_by_process: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in period_rows:
                if row["lifecycle"] == "persistent":
                    persistent_by_process[row["process_instance_id"]].append(row)
                else:
                    execution_units.append([row])
            execution_units.extend(
                sorted(group, key=lambda row: row["sequence_index"])
                for group in persistent_by_process.values()
            )
            shuffled_units = deterministic_shuffle(
                execution_units,
                config.master_seed,
                f"within:{batch_id}:{load_condition}",
            )
            for unit in shuffled_units:
                ordered.extend(unit)
    for execution_index, row in enumerate(ordered):
        row["execution_index"] = execution_index
        row["case_id"] = f"{config.phase}-case-{hash_json({k: v for k, v in row.items() if k != 'case_id'})[:20]}"

    manifest = {
        "schema_version": "schedule-manifest-1.0.0",
        "config": asdict(config),
        "design": {
            "budget_modes": list(BUDGET_MODES),
            "load_conditions": list(LOAD_CONDITIONS),
            "lifecycles": list(LIFECYCLES),
            "rows_per_complete_block": len(config.agents) * 8,
            "independent_unit": "matched_seed_seat_play_order_block",
            "load_assignment_unit": "paired_load_batch",
            "persistent_assignment_unit": "independently_restarted_bounded_session",
            "minimum_persistent_sessions_scope": "per_agent_budget_load_cell",
            "session_bundle_role": "common_warmth_slot_across_all_factorial_cells",
        },
        "rows": ordered,
    }
    manifest["content_hash"] = hash_json(manifest)
    validate_schedule(manifest)
    return manifest


def validate_schedule(manifest: dict[str, Any]) -> None:
    verify_schedule_content_hash(manifest)
    rows = manifest.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("schedule has no rows")
    config_dict = manifest.get("config", {})
    if not isinstance(config_dict, dict):
        raise ValueError("schedule config must be an object")
    parsed_config = ScheduleConfig(
        **{
            **config_dict,
            "agents": tuple(config_dict.get("agents", ())),
        }
    )
    parsed_config.validate()
    agents = tuple(config_dict.get("agents", ()))
    expected_cells = set(product(agents, BUDGET_MODES, LOAD_CONDITIONS, LIFECYCLES))
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["phase"] != parsed_config.phase:
            raise ValueError("schedule row phase differs from config")
        if row["agent_id"] not in agents:
            raise ValueError(f"unknown scheduled agent: {row['agent_id']}")
        if row["budget_mode"] == "wall_clock":
            if row["requested_budget_ns"] != parsed_config.wall_clock_budget_ns:
                raise ValueError("wall-clock row differs from frozen deadline")
            if row["requested_work_units"] is not None:
                raise ValueError("wall-clock row contains a fixed-work count")
        elif row["budget_mode"] == "fixed_work":
            expected_work = (parsed_config.fixed_work_by_agent or {}).get(row["agent_id"])
            if row["requested_work_units"] != expected_work:
                raise ValueError("fixed-work row differs from frozen agent calibration")
            if row["requested_budget_ns"] is not None:
                raise ValueError("fixed-work row contains a wall-clock deadline")
        else:
            raise ValueError(f"unsupported row budget mode: {row['budget_mode']}")
        grouped[row["block_id"]].append(row)
    for block_id, block_rows in grouped.items():
        cells = {
            (row["agent_id"], row["budget_mode"], row["load_condition"], row["lifecycle"])
            for row in block_rows
        }
        if cells != expected_cells:
            raise ValueError(f"block {block_id} is not factorially complete")
        invariant_fields = ("environment_seed", "physical_seat", "play_order")
        for field in invariant_fields:
            if len({row[field] for row in block_rows}) != 1:
                raise ValueError(f"block {block_id} is not matched on {field}")
        for field in ("load_batch_id", "load_period_order", "load_seed", "session_bundle_id", "sequence_index"):
            if len({row[field] for row in block_rows}) != 1:
                raise ValueError(f"block {block_id} is not matched on {field}")
    case_ids = [row["case_id"] for row in rows]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("case IDs are not unique")
    if sorted(row["execution_index"] for row in rows) != list(range(len(rows))):
        raise ValueError("execution indexes are not a bijection")
    persistent_counts = Counter(
        row["process_instance_id"] for row in rows if row["lifecycle"] == "persistent"
    )
    maximum = int(config_dict["persistent_sequence_length"])
    if persistent_counts and max(persistent_counts.values()) > maximum:
        raise ValueError("persistent process exceeds frozen sequence bound")
    persistent_rows_by_process: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["lifecycle"] == "persistent":
            persistent_rows_by_process[row["process_instance_id"]].append(row)
    for process_id, process_rows in persistent_rows_by_process.items():
        cells = {
            (
                row["load_batch_id"],
                row["load_condition"],
                row["agent_id"],
                row["budget_mode"],
                row["session_bundle_id"],
            )
            for row in process_rows
        }
        if len(cells) != 1:
            raise ValueError(f"persistent process {process_id} crosses a frozen cell")
        slots = sorted(row["sequence_index"] for row in process_rows)
        if slots != list(range(len(slots))):
            raise ValueError(f"persistent process {process_id} has non-contiguous slots")
    represented_batches = {row["load_batch_id"] for row in rows}
    configured_batches = int(config_dict["paired_load_batches"])
    if len(represented_batches) != configured_batches:
        raise ValueError(
            f"schedule represents {len(represented_batches)} load batches, expected {configured_batches}"
        )
    by_batch: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_batch[row["load_batch_id"]].append(row)
    for batch_id, batch_rows in by_batch.items():
        if {row["load_condition"] for row in batch_rows} != set(LOAD_CONDITIONS):
            raise ValueError(f"load batch {batch_id} lacks both paired periods")
        if len({row["load_period_order"] for row in batch_rows}) != 1:
            raise ValueError(f"load batch {batch_id} has inconsistent period order")
        block_strata = Counter(
            (block_rows[0]["physical_seat"], block_rows[0]["play_order"])
            for block_rows in (
                [row for row in batch_rows if row["block_id"] == block_id]
                for block_id in {row["block_id"] for row in batch_rows}
            )
        )
        all_strata = list(product((0, 1), (0, 1)))
        stratum_counts = [block_strata[stratum] for stratum in all_strata]
        if max(stratum_counts) - min(stratum_counts) > 1:
            raise ValueError(f"load batch {batch_id} is imbalanced on seat/play-order strata")
    for pair_id in {row["lifecycle_pair_id"] for row in rows}:
        pair = [row for row in rows if row["lifecycle_pair_id"] == pair_id]
        if len(pair) != 2 or {row["lifecycle"] for row in pair} != set(LIFECYCLES):
            raise ValueError(f"lifecycle pair {pair_id} is incomplete")
        if len({row["sequence_index"] for row in pair}) != 1:
            raise ValueError(f"lifecycle pair {pair_id} lacks matched sequence slot")
    for sequence_pair_id in {row["sequence_pair_id"] for row in rows}:
        sequence_rows = [row for row in rows if row["sequence_pair_id"] == sequence_pair_id]
        if len(sequence_rows) != 4:
            raise ValueError(f"sequence pair {sequence_pair_id} is incomplete")
        if len({row["sequence_index"] for row in sequence_rows}) != 1:
            raise ValueError(f"sequence pair {sequence_pair_id} is not matched across load/lifecycle")
    order_counts = Counter(
        next(iter({row["load_period_order"] for row in batch_rows}))
        for batch_rows in by_batch.values()
    )
    if abs(order_counts["idle_then_loaded"] - order_counts["loaded_then_idle"]) > 1:
        raise ValueError("AB/BA period orders are not near-exactly balanced")
    sessions_by_cell: Counter[tuple[str, str, str]] = Counter()
    for process_rows in persistent_rows_by_process.values():
        first = process_rows[0]
        sessions_by_cell[(first["agent_id"], first["budget_mode"], first["load_condition"])] += 1
    for cell in product(agents, BUDGET_MODES, LOAD_CONDITIONS):
        if sessions_by_cell[cell] < int(config_dict["minimum_persistent_sessions"]):
            raise ValueError(
                f"lifecycle cell {cell} has only {sessions_by_cell[cell]} sessions, "
                f"below {config_dict['minimum_persistent_sessions']}"
            )
    if config_dict.get("phase") in {"pilot", "final"}:
        if len(represented_batches) < 20:
            raise ValueError(
                f"{config_dict.get('phase')} schedule has fewer than 20 represented load pairs"
            )
        for batch_id, batch_rows in by_batch.items():
            strata = {
                (row["physical_seat"], row["play_order"])
                for row in batch_rows
            }
            if strata != set(product((0, 1), (0, 1))):
                raise ValueError(
                    f"{config_dict.get('phase')} load batch {batch_id} lacks all four strata"
                )
        non_singleton_by_cell: Counter[tuple[str, str, str]] = Counter()
        for process_id, count in persistent_counts.items():
            if count < 2:
                continue
            process_rows = [row for row in rows if row["process_instance_id"] == process_id]
            cell = (
                process_rows[0]["agent_id"],
                process_rows[0]["budget_mode"],
                process_rows[0]["load_condition"],
            )
            non_singleton_by_cell[cell] += 1
        for cell in product(agents, BUDGET_MODES, LOAD_CONDITIONS):
            if non_singleton_by_cell[cell] < 20:
                raise ValueError(
                    f"final lifecycle cell {cell} has only {non_singleton_by_cell[cell]} "
                    "non-singleton persistent sessions"
                )


def verify_schedule_content_hash(manifest: dict[str, Any]) -> None:
    supplied = manifest.get("content_hash")
    if not isinstance(supplied, str):
        raise ValueError("schedule lacks content_hash")
    payload = dict(manifest)
    payload.pop("content_hash", None)
    expected = hash_json(payload)
    if supplied != expected:
        raise ValueError(f"schedule content hash mismatch: supplied={supplied}, expected={expected}")


def schedule_rows(manifest: dict[str, Any], *, execution_order: bool = True) -> Iterable[dict[str, Any]]:
    rows = list(manifest["rows"])
    return sorted(rows, key=lambda row: row["execution_index"]) if execution_order else rows

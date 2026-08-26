"""Outcome-blind, seed-disjoint calibration-bank construction.

This module deliberately stops at manifests and deterministic selectors.  It
does not execute games or import acquisition code.  Callers must convert each
completed calibration case into the small, explicitly outcome-free record
accepted by :func:`select_deadline` or :func:`select_fixed_work_counts`.
"""

from __future__ import annotations

import math
import re
import statistics
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Sequence

from .canonical import derive_u32, deterministic_shuffle, hash_json


DEADLINE_WHITELIST_MS = (10, 25, 50, 100)
CALIBRATION_ROLES = frozenset({"deadline_selection", "fixed_work"})
REQUIRED_EXCLUSION_BANKS = frozenset({"gate", "final", "reserve"})
DEADLINE_BANK_EXCLUSION = "deadline_calibration"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_OUTCOME_KEY_PARTS = (
    "action",
    "draw",
    "loss",
    "outcome",
    "policy",
    "rank",
    "regret",
    "score",
    "trace",
    "trajectory",
    "value",
    "win",
    "winner",
)
_CALIBRATION_RECORD_FIELDS = frozenset(
    {
        "calibration_case_id",
        "agent_id",
        "state_id",
        "block_id",
        "requested_budget_ns",
        "completed_work_units",
        "search_wall_ns",
        "overshoot_ns",
        "terminal_status",
        "eligible",
    }
)


class CalibrationError(RuntimeError):
    """A calibration input or gate violates the frozen contract."""


@dataclass(frozen=True)
class CalibrationState:
    """One preselected, search-eligible state and its provenance."""

    state_id: str
    source_game_id: str
    state_artifact_sha256: str
    state_seed: int
    eligibility_sha256: str

    def validate(self) -> None:
        if not self.state_id or not self.source_game_id:
            raise ValueError("calibration state and source-game IDs must be nonempty")
        _require_sha256(self.state_artifact_sha256, "state_artifact_sha256")
        _require_sha256(self.eligibility_sha256, "eligibility_sha256")
        _require_seed(self.state_seed, "state_seed")


@dataclass(frozen=True)
class CalibrationConfig:
    """Configuration for one independent calibration bank.

    ``deadline_selection`` banks contain every deadline in the immutable
    whitelist.  A later, independent ``fixed_work`` bank contains only the
    selected deadline and binds the selector artifact by hash.
    """

    bank_id: str
    role: str
    master_seed: int
    agents: tuple[str, ...]
    deadline_ms: int | None = None
    deadline_selection_hash: str | None = None

    def validate(self) -> None:
        if not self.bank_id:
            raise ValueError("bank_id must be nonempty")
        if self.role not in CALIBRATION_ROLES:
            raise ValueError(f"unknown calibration role: {self.role}")
        if len(self.agents) != 3 or len(set(self.agents)) != 3:
            raise ValueError("calibration requires exactly three unique agents")
        if any(not agent for agent in self.agents):
            raise ValueError("agent IDs must be nonempty")
        _require_seed(self.master_seed, "master_seed", maximum=(1 << 64) - 1)
        if self.role == "deadline_selection":
            if self.deadline_ms is not None or self.deadline_selection_hash is not None:
                raise ValueError("deadline-selection banks cannot bind a prior selection")
        else:
            if self.deadline_ms not in DEADLINE_WHITELIST_MS:
                raise ValueError("fixed-work calibration deadline is outside the frozen whitelist")
            if self.deadline_selection_hash is None:
                raise ValueError("fixed-work bank must bind the deadline-selection artifact")
            _require_sha256(self.deadline_selection_hash, "deadline_selection_hash")


@dataclass(frozen=True)
class DeadlineCriteria:
    """Frozen, outcome-blind deadline eligibility thresholds."""

    minimum_valid_states_per_agent: int
    maximum_zero_work_fraction: float
    maximum_p99_overshoot_fraction: float
    maximum_single_overshoot_fraction: float
    maximum_p95_search_wall_fraction: float
    minimum_median_completed_work: float = 1.0

    def validate(self) -> None:
        if self.minimum_valid_states_per_agent <= 0:
            raise ValueError("minimum_valid_states_per_agent must be positive")
        for name in (
            "maximum_zero_work_fraction",
            "maximum_p99_overshoot_fraction",
            "maximum_single_overshoot_fraction",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        if (
            not math.isfinite(self.maximum_p95_search_wall_fraction)
            or self.maximum_p95_search_wall_fraction <= 0.0
        ):
            raise ValueError("maximum_p95_search_wall_fraction must be positive")
        if (
            not math.isfinite(self.minimum_median_completed_work)
            or self.minimum_median_completed_work <= 0.0
        ):
            raise ValueError("minimum_median_completed_work must be positive")


def _require_sha256(value: str, label: str) -> None:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 hex digest")


def _require_seed(value: int, label: str, *, maximum: int = (1 << 32) - 1) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise ValueError(f"{label} must be an integer in [0, {maximum}]")


def _normalized_exclusion_ledger(
    ledger: Mapping[str, Iterable[int]],
    *,
    required_banks: frozenset[str],
) -> dict[str, list[int]]:
    if not isinstance(ledger, Mapping):
        raise ValueError("seed exclusion ledger must be a mapping")
    missing = required_banks - set(map(str, ledger))
    if missing:
        raise ValueError(f"seed exclusion ledger lacks required banks: {sorted(missing)}")
    normalized: dict[str, list[int]] = {}
    for raw_name, raw_values in sorted(ledger.items(), key=lambda item: str(item[0])):
        name = str(raw_name)
        if not name:
            raise ValueError("seed exclusion bank names must be nonempty")
        values: list[int] = []
        for raw_value in raw_values:
            _require_seed(raw_value, f"excluded seed in {name}", maximum=(1 << 64) - 1)
            values.append(int(raw_value))
        normalized[name] = sorted(set(values))
    return normalized


def collect_persisted_seeds(value: Any) -> set[int]:
    """Collect persisted ``*_seed`` values from another bank manifest.

    Exclusion ledgers embedded in that manifest are intentionally skipped, so
    this returns seeds used by the bank rather than every seed it excluded.
    """

    result: set[int] = set()

    def walk(node: Any) -> None:
        if isinstance(node, Mapping):
            for raw_key, item in node.items():
                key = str(raw_key)
                if key == "excluded_seed_ledger":
                    continue
                if key == "master_seed" or key.endswith("_seed"):
                    if isinstance(item, bool) or not isinstance(item, int):
                        raise ValueError(f"persisted seed field {key} is not an integer")
                    if item < 0:
                        raise ValueError(f"persisted seed field {key} is negative")
                    result.add(int(item))
                else:
                    walk(item)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item)

    walk(value)
    return result


def _assert_disjoint_streams(streams: Mapping[str, Iterable[int]]) -> None:
    owner: dict[int, str] = {}
    for stream, raw_values in streams.items():
        values = list(map(int, raw_values))
        if len(values) != len(set(values)):
            raise CalibrationError(f"seed collision within {stream} stream")
        for value in values:
            prior = owner.get(value)
            if prior is not None:
                raise CalibrationError(f"seed value {value} collides across {prior} and {stream}")
            owner[value] = stream


def _assert_excluded(seeds: Iterable[int], ledger: Mapping[str, Sequence[int]]) -> None:
    used = set(map(int, seeds))
    for bank, values in ledger.items():
        overlap = sorted(used & set(map(int, values)))
        if overlap:
            raise CalibrationError(
                f"calibration seeds overlap excluded bank {bank}: {overlap[:5]}"
            )


def _deadline_set(config: CalibrationConfig) -> tuple[int, ...]:
    if config.role == "deadline_selection":
        return DEADLINE_WHITELIST_MS
    assert config.deadline_ms is not None
    return (config.deadline_ms,)


def _required_exclusion_banks(config: CalibrationConfig) -> frozenset[str]:
    if config.role == "fixed_work":
        return REQUIRED_EXCLUSION_BANKS | {DEADLINE_BANK_EXCLUSION}
    return REQUIRED_EXCLUSION_BANKS


def build_calibration_manifest(
    config: CalibrationConfig,
    states: Sequence[CalibrationState],
    *,
    excluded_seed_ledger: Mapping[str, Iterable[int]],
) -> dict[str, Any]:
    """Build an idle/fresh/wall-clock-only calibration manifest."""

    config.validate()
    ordered_states = sorted(states, key=lambda state: state.state_id)
    if not ordered_states:
        raise ValueError("calibration bank requires at least one state")
    for state in ordered_states:
        state.validate()
    if len({state.state_id for state in ordered_states}) != len(ordered_states):
        raise ValueError("calibration state IDs must be unique")
    if len({state.source_game_id for state in ordered_states}) != len(ordered_states):
        raise ValueError("calibration permits at most one state per source game")
    if len({state.state_seed for state in ordered_states}) != len(ordered_states):
        raise ValueError("calibration state seeds must be unique")

    exclusions = _normalized_exclusion_ledger(
        excluded_seed_ledger,
        required_banks=_required_exclusion_banks(config),
    )
    deadlines = _deadline_set(config)
    agent_seed_by_key: dict[tuple[str, str], int] = {}
    schedule_seeds: list[int] = []
    rows: list[dict[str, Any]] = []
    for block_index, state in enumerate(ordered_states):
        block_id = f"{config.bank_id}-block-{block_index:05d}"
        for agent_id in config.agents:
            agent_key = (state.state_id, agent_id)
            agent_seed = derive_u32(
                config.master_seed,
                f"calibration-agent:{config.role}:{config.bank_id}",
                state.state_id,
                agent_id,
            )
            agent_seed_by_key[agent_key] = agent_seed
            for deadline_ms in deadlines:
                schedule_seed = derive_u32(
                    config.master_seed,
                    f"calibration-schedule:{config.role}:{config.bank_id}",
                    state.state_id,
                    agent_id,
                    deadline_ms,
                )
                schedule_seeds.append(schedule_seed)
                rows.append(
                    {
                        "schema_version": "calibration-row-1.0.0",
                        "calibration_case_id": "",
                        "bank_id": config.bank_id,
                        "role": config.role,
                        "block_id": block_id,
                        "block_index": block_index,
                        "state_id": state.state_id,
                        "source_game_id": state.source_game_id,
                        "state_artifact_sha256": state.state_artifact_sha256,
                        "eligibility_sha256": state.eligibility_sha256,
                        "state_seed": state.state_seed,
                        "agent_id": agent_id,
                        "agent_seed": agent_seed,
                        "schedule_seed": schedule_seed,
                        "budget_mode": "wall_clock",
                        "load_condition": "idle",
                        "lifecycle": "fresh",
                        "deadline_ms": deadline_ms,
                        "requested_budget_ns": deadline_ms * 1_000_000,
                        "execution_index": -1,
                    }
                )

    streams = {
        "master": [config.master_seed],
        "state": [state.state_seed for state in ordered_states],
        "agent": list(agent_seed_by_key.values()),
        "schedule": schedule_seeds,
    }
    _assert_disjoint_streams(streams)
    all_used = {seed for values in streams.values() for seed in values}
    _assert_excluded(all_used, exclusions)

    shuffled = deterministic_shuffle(
        rows,
        config.master_seed,
        f"calibration-execution:{config.role}:{config.bank_id}",
    )
    for execution_index, row in enumerate(shuffled):
        row["execution_index"] = execution_index
        identity = {key: value for key, value in row.items() if key != "calibration_case_id"}
        row["calibration_case_id"] = f"cal-{hash_json(identity)[:24]}"

    source_states = [asdict(state) for state in ordered_states]
    manifest: dict[str, Any] = {
        "schema_version": "calibration-manifest-1.0.0",
        "config": asdict(config),
        "design": {
            "conditions": {
                "budget_mode": "wall_clock",
                "load_condition": "idle",
                "lifecycle": "fresh",
            },
            "deadline_whitelist_ms": list(DEADLINE_WHITELIST_MS),
            "block_weighting": "one preselected eligible state per source-game block",
            "competitive_outcomes_available_to_selector": False,
        },
        "states": source_states,
        "source_states_hash": hash_json(source_states),
        "excluded_seed_ledger": exclusions,
        "excluded_seed_ledger_hash": hash_json(exclusions),
        "seed_inventory": {name: sorted(values) for name, values in streams.items()},
        "rows": shuffled,
    }
    manifest["content_hash"] = hash_json(manifest)
    validate_calibration_manifest(manifest)
    return manifest


def verify_calibration_content_hash(manifest: Mapping[str, Any]) -> None:
    supplied = manifest.get("content_hash")
    if not isinstance(supplied, str):
        raise CalibrationError("calibration manifest lacks content_hash")
    payload = dict(manifest)
    payload.pop("content_hash", None)
    expected = hash_json(payload)
    if supplied != expected:
        raise CalibrationError(
            f"calibration content hash mismatch: supplied={supplied}, expected={expected}"
        )


def validate_calibration_manifest(manifest: Mapping[str, Any]) -> None:
    verify_calibration_content_hash(manifest)
    config = CalibrationConfig(**dict(manifest.get("config", {})))
    config.validate()
    states = [CalibrationState(**dict(value)) for value in manifest.get("states", [])]
    if not states:
        raise CalibrationError("calibration manifest has no source states")
    for state in states:
        state.validate()
    if len({state.state_id for state in states}) != len(states):
        raise CalibrationError("calibration manifest repeats a state ID")
    if len({state.source_game_id for state in states}) != len(states):
        raise CalibrationError("calibration manifest uses multiple states from one source game")
    if manifest.get("source_states_hash") != hash_json([asdict(state) for state in states]):
        raise CalibrationError("calibration source-state inventory hash mismatch")

    deadlines = _deadline_set(config)
    rows = list(manifest.get("rows", []))
    expected_count = len(states) * len(config.agents) * len(deadlines)
    if len(rows) != expected_count:
        raise CalibrationError(
            f"calibration row count {len(rows)} does not equal expected {expected_count}"
        )
    expected_keys = {
        (state.state_id, agent_id, deadline_ms)
        for state in states
        for agent_id in config.agents
        for deadline_ms in deadlines
    }
    observed_keys: set[tuple[str, str, int]] = set()
    state_by_id = {state.state_id: state for state in states}
    agent_seed_by_key: dict[tuple[str, str], set[int]] = {}
    for row in rows:
        if row.get("budget_mode") != "wall_clock":
            raise CalibrationError("calibration row is not wall-clock")
        if row.get("load_condition") != "idle" or row.get("lifecycle") != "fresh":
            raise CalibrationError("calibration row escaped idle/fresh envelope")
        state_id = str(row["state_id"])
        agent_id = str(row["agent_id"])
        deadline_ms = int(row["deadline_ms"])
        key = (state_id, agent_id, deadline_ms)
        if key in observed_keys:
            raise CalibrationError(f"duplicate calibration assignment: {key}")
        observed_keys.add(key)
        state = state_by_id.get(state_id)
        if state is None:
            raise CalibrationError(f"row references unknown state {state_id}")
        if (
            row.get("source_game_id") != state.source_game_id
            or row.get("state_artifact_sha256") != state.state_artifact_sha256
            or row.get("eligibility_sha256") != state.eligibility_sha256
            or int(row.get("state_seed")) != state.state_seed
        ):
            raise CalibrationError(f"row provenance differs from state inventory: {state_id}")
        if int(row.get("requested_budget_ns")) != deadline_ms * 1_000_000:
            raise CalibrationError("deadline milliseconds and nanoseconds disagree")
        agent_seed_by_key.setdefault((state_id, agent_id), set()).add(int(row["agent_seed"]))
    if observed_keys != expected_keys:
        raise CalibrationError("calibration factorial assignments are incomplete")
    if any(len(values) != 1 for values in agent_seed_by_key.values()):
        raise CalibrationError("agent seed changed across candidate deadlines")
    case_ids = [str(row["calibration_case_id"]) for row in rows]
    if len(case_ids) != len(set(case_ids)):
        raise CalibrationError("calibration case IDs are not unique")
    if sorted(int(row["execution_index"]) for row in rows) != list(range(len(rows))):
        raise CalibrationError("calibration execution indexes are not a bijection")

    exclusions = _normalized_exclusion_ledger(
        manifest.get("excluded_seed_ledger", {}),
        required_banks=_required_exclusion_banks(config),
    )
    streams = {
        "master": [config.master_seed],
        "state": [state.state_seed for state in states],
        "agent": [next(iter(values)) for values in agent_seed_by_key.values()],
        "schedule": [int(row["schedule_seed"]) for row in rows],
    }
    _assert_disjoint_streams(streams)
    _assert_excluded(
        {seed for values in streams.values() for seed in values},
        exclusions,
    )
    if manifest.get("seed_inventory") != {
        name: sorted(values) for name, values in streams.items()
    }:
        raise CalibrationError("calibration seed inventory does not reconcile")


def _has_competitive_outcome_key(key: str) -> bool:
    normalized = key.lower()
    return any(part in normalized for part in _OUTCOME_KEY_PARTS)


def _normalize_records(
    manifest: Mapping[str, Any],
    records: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    verify_calibration_content_hash(manifest)
    rows_by_id = {
        str(row["calibration_case_id"]): row
        for row in manifest.get("rows", [])
    }
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in records:
        keys = set(map(str, raw))
        leaked = sorted(key for key in keys if _has_competitive_outcome_key(key))
        if leaked:
            raise CalibrationError(
                f"competitive outcome fields are forbidden in calibration input: {leaked}"
            )
        unknown = keys - _CALIBRATION_RECORD_FIELDS
        missing = _CALIBRATION_RECORD_FIELDS - keys
        if unknown or missing:
            raise CalibrationError(
                f"calibration record schema mismatch: unknown={sorted(unknown)}, "
                f"missing={sorted(missing)}"
            )
        item = {key: raw[key] for key in sorted(_CALIBRATION_RECORD_FIELDS)}
        case_id = str(item["calibration_case_id"])
        if case_id in seen:
            raise CalibrationError(f"duplicate calibration result: {case_id}")
        seen.add(case_id)
        scheduled = rows_by_id.get(case_id)
        if scheduled is None:
            raise CalibrationError(f"unexpected calibration result: {case_id}")
        for field in ("agent_id", "state_id", "block_id", "requested_budget_ns"):
            if item[field] != scheduled[field]:
                raise CalibrationError(f"calibration result {case_id} disagrees on {field}")
        for field in (
            "requested_budget_ns",
            "completed_work_units",
            "search_wall_ns",
            "overshoot_ns",
        ):
            value = item[field]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise CalibrationError(f"calibration result {case_id} has invalid {field}")
        if not isinstance(item["eligible"], bool):
            raise CalibrationError(f"calibration result {case_id} has non-boolean eligibility")
        if not isinstance(item["terminal_status"], str):
            raise CalibrationError(f"calibration result {case_id} has invalid terminal status")
        normalized.append(item)
    missing_ids = sorted(set(rows_by_id) - seen)
    if missing_ids:
        raise CalibrationError(f"calibration results are incomplete: {missing_ids[:5]}")
    normalized.sort(key=lambda item: str(item["calibration_case_id"]))
    return normalized, hash_json(normalized)


def _nearest_rank(values: Sequence[int], probability: float) -> int:
    if not values:
        raise CalibrationError("quantile requested for empty values")
    ordered = sorted(map(int, values))
    index = max(0, min(len(ordered) - 1, math.ceil(probability * len(ordered)) - 1))
    return ordered[index]


def _with_content_hash(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["content_hash"] = hash_json(result)
    return result


def verify_selector_content_hash(result: Mapping[str, Any]) -> None:
    supplied = result.get("content_hash")
    if not isinstance(supplied, str):
        raise CalibrationError("selector result lacks content_hash")
    payload = dict(result)
    payload.pop("content_hash", None)
    expected = hash_json(payload)
    if supplied != expected:
        raise CalibrationError("selector result content hash mismatch")


def select_deadline(
    manifest: Mapping[str, Any],
    records: Iterable[Mapping[str, Any]],
    criteria: DeadlineCriteria,
) -> dict[str, Any]:
    """Choose the smallest passing frozen deadline without competitive outcomes."""

    criteria.validate()
    validate_calibration_manifest(manifest)
    config = CalibrationConfig(**dict(manifest["config"]))
    if config.role != "deadline_selection":
        raise CalibrationError("deadline selection requires a deadline-selection bank")
    normalized, records_hash = _normalize_records(manifest, records)
    by_deadline_agent: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for record in normalized:
        deadline_ms = int(record["requested_budget_ns"]) // 1_000_000
        by_deadline_agent.setdefault((deadline_ms, str(record["agent_id"])), []).append(record)

    candidate_metrics: dict[str, Any] = {}
    selected: int | None = None
    for deadline_ms in DEADLINE_WHITELIST_MS:
        budget_ns = deadline_ms * 1_000_000
        deadline_passes = True
        per_agent: dict[str, Any] = {}
        for agent_id in config.agents:
            items = by_deadline_agent.get((deadline_ms, agent_id), [])
            invalid = [
                item
                for item in items
                if not item["eligible"]
                or item["terminal_status"] not in {"ok", "deadline_no_work"}
            ]
            valid = [item for item in items if item not in invalid]
            completed = [int(item["completed_work_units"]) for item in valid]
            overshoot = [int(item["overshoot_ns"]) for item in valid]
            search_wall = [int(item["search_wall_ns"]) for item in valid]
            zero_fraction = (
                sum(value == 0 for value in completed) / len(completed)
                if completed
                else 1.0
            )
            median_work = float(statistics.median(completed)) if completed else 0.0
            p99_overshoot = _nearest_rank(overshoot, 0.99) if overshoot else budget_ns
            maximum_overshoot = max(overshoot, default=budget_ns)
            p95_search_wall = _nearest_rank(search_wall, 0.95) if search_wall else 2 * budget_ns
            checks = {
                "record_count_complete": len(items) == len(manifest["states"]),
                "minimum_valid_states": len(valid) >= criteria.minimum_valid_states_per_agent,
                "no_invalid_attempts": not invalid,
                "zero_work": zero_fraction <= criteria.maximum_zero_work_fraction,
                "median_work": median_work >= criteria.minimum_median_completed_work,
                "p99_overshoot": (
                    p99_overshoot / budget_ns
                    <= criteria.maximum_p99_overshoot_fraction
                ),
                "maximum_overshoot": (
                    maximum_overshoot / budget_ns
                    <= criteria.maximum_single_overshoot_fraction
                ),
                "p95_search_wall": (
                    p95_search_wall / budget_ns
                    <= criteria.maximum_p95_search_wall_fraction
                ),
            }
            passes = all(checks.values())
            deadline_passes = deadline_passes and passes
            per_agent[agent_id] = {
                "passes": passes,
                "checks": checks,
                "scheduled_records": len(items),
                "valid_records": len(valid),
                "invalid_records": len(invalid),
                "zero_work_fraction": zero_fraction,
                "median_completed_work": median_work,
                "p99_overshoot_ns": p99_overshoot,
                "maximum_overshoot_ns": maximum_overshoot,
                "p95_search_wall_ns": p95_search_wall,
            }
        candidate_metrics[str(deadline_ms)] = {
            "passes": deadline_passes,
            "per_agent": per_agent,
        }
        if deadline_passes and selected is None:
            selected = deadline_ms

    if selected is None:
        raise CalibrationError(
            "no frozen deadline passed the outcome-blind latency/work criteria: "
            f"{hash_json(candidate_metrics)}"
        )
    return _with_content_hash(
        {
            "schema_version": "deadline-selection-1.0.0",
            "bank_id": config.bank_id,
            "selected_deadline_ms": selected,
            "deadline_whitelist_ms": list(DEADLINE_WHITELIST_MS),
            "selection_rule": "smallest_whitelisted_deadline_passing_every_agent",
            "criteria": asdict(criteria),
            "candidate_metrics": candidate_metrics,
            "input_manifest_content_hash": manifest["content_hash"],
            "input_records_sha256": records_hash,
            "competitive_outcome_fields_consumed": [],
        }
    )


def _half_up_integer_median(values: Sequence[int]) -> int:
    if not values:
        raise CalibrationError("cannot calibrate a median from no values")
    ordered = sorted(map(int, values))
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle] + 1) // 2


def select_fixed_work_counts(
    manifest: Mapping[str, Any],
    records: Iterable[Mapping[str, Any]],
    deadline_selection: Mapping[str, Any],
    *,
    minimum_complete_blocks: int,
) -> dict[str, Any]:
    """Select one exact work count per agent from equal-weight complete blocks."""

    if minimum_complete_blocks <= 0:
        raise ValueError("minimum_complete_blocks must be positive")
    validate_calibration_manifest(manifest)
    verify_selector_content_hash(deadline_selection)
    config = CalibrationConfig(**dict(manifest["config"]))
    if config.role != "fixed_work":
        raise CalibrationError("fixed-work counts require an independent fixed-work bank")
    if config.deadline_selection_hash != deadline_selection["content_hash"]:
        raise CalibrationError("fixed-work bank does not bind this deadline-selection artifact")
    selected_deadline = int(deadline_selection["selected_deadline_ms"])
    if config.deadline_ms != selected_deadline:
        raise CalibrationError("fixed-work bank deadline differs from selected deadline")

    normalized, records_hash = _normalize_records(manifest, records)
    row_by_case = {
        str(row["calibration_case_id"]): row
        for row in manifest["rows"]
    }
    by_block_agent: dict[tuple[str, str], dict[str, Any]] = {}
    for record in normalized:
        row = row_by_case[str(record["calibration_case_id"])]
        by_block_agent[(str(row["block_id"]), str(row["agent_id"]))] = record

    block_ids = sorted({str(row["block_id"]) for row in manifest["rows"]})
    included: list[str] = []
    excluded: dict[str, list[str]] = {}
    values_by_agent: dict[str, dict[str, int]] = {agent: {} for agent in config.agents}
    for block_id in block_ids:
        reasons: list[str] = []
        block_values: dict[str, int] = {}
        for agent_id in config.agents:
            record = by_block_agent.get((block_id, agent_id))
            if record is None:
                reasons.append(f"{agent_id}:missing")
                continue
            if not record["eligible"]:
                reasons.append(f"{agent_id}:ineligible")
            elif record["terminal_status"] != "ok":
                reasons.append(f"{agent_id}:{record['terminal_status']}")
            elif int(record["completed_work_units"]) <= 0:
                reasons.append(f"{agent_id}:zero_work")
            else:
                block_values[agent_id] = int(record["completed_work_units"])
        if reasons:
            excluded[block_id] = reasons
            continue
        included.append(block_id)
        for agent_id, value in block_values.items():
            values_by_agent[agent_id][block_id] = value

    if len(included) < minimum_complete_blocks:
        raise CalibrationError(
            f"only {len(included)} complete calibration blocks; "
            f"minimum is {minimum_complete_blocks}"
        )
    fixed_work = {
        agent_id: _half_up_integer_median(
            [values_by_agent[agent_id][block_id] for block_id in included]
        )
        for agent_id in config.agents
    }
    return _with_content_hash(
        {
            "schema_version": "fixed-work-calibration-1.0.0",
            "bank_id": config.bank_id,
            "selected_deadline_ms": selected_deadline,
            "fixed_work_by_agent": fixed_work,
            "rounding_rule": "block_equal_median_even_midpoint_round_half_up",
            "included_block_ids": included,
            "excluded_blocks": excluded,
            "per_agent_block_values": values_by_agent,
            "minimum_complete_blocks": minimum_complete_blocks,
            "input_manifest_content_hash": manifest["content_hash"],
            "source_states_hash": manifest["source_states_hash"],
            "input_records_sha256": records_hash,
            "deadline_selection_content_hash": deadline_selection["content_hash"],
            "competitive_outcome_fields_consumed": [],
        }
    )

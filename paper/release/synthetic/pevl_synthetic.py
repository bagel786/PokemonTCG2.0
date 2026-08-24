#!/usr/bin/env python3
"""Deterministic demonstrations for the Paired Evaluation Validity Ladder.

The simulator keeps each modeled system deliberately small. Its purpose is to
make coupling failures inspectable, not to approximate the restricted case-study
engine. Clocks and process states are injected so every released artifact is
bit-for-bit reproducible.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "1.1.0"
UINT32_MODULUS = 1 << 32
DEFAULT_SEED = 730_241
CONVERSION_RULE = "requested_seed modulo 2**32"
RNG_STREAM_ID = "pevl-synthetic-stream-v1"

LEVELS = (
    (1, "artifact_identity", "evidence_gate"),
    (2, "seed_namespace_integrity", "evidence_gate"),
    (3, "schedule_parity", "evidence_gate"),
    (4, "identical_arm_record_parity", "evidence_gate"),
    (5, "repeat_and_worker_parity", "evidence_gate"),
    (6, "stochastic_source_audit", "evidence_gate"),
    (7, "cross_arm_event_alignment", "evidence_gate"),
    (8, "statistical_admission", "admission_decision"),
)

GATE_STATUSES = {"pass", "fail", "blocked"}
ADMISSION_STATUSES = {"admit", "downgrade", "suppress"}
EXPECTED_CATCHES = {
    "clean_deterministic": [],
    "stateful_draw_shift": [7],
    "wall_clock_search": [4, 5, 6],
    "process_global_state": [4, 5, 6],
    "uint32_seed_conversion": [2],
}


def canonical_json_bytes(value: Any) -> bytes:
    """Return the canonical UTF-8 representation used by every digest."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def object_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def uint32_seed(requested_seed: int) -> int:
    """Match narrowing by an unsigned 32-bit engine boundary."""

    return requested_seed % UINT32_MODULUS


def _counter_uint64(seed: int, counter: int) -> int:
    """One draw from the testbed's mutable, counter-indexed random stream."""

    payload = canonical_json_bytes(
        {
            "counter": counter,
            "domain": "pevl-stateful-stream-v1",
            "seed_uint32": uint32_seed(seed),
        }
    )
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def event_keyed_uint64(seed: int, event_key: str) -> int:
    """Generate one random quantity from a semantic event identity.

    This counter-based construction is the white-box remedy for the draw-shift
    scenario: adding an unrelated event does not move another event to a
    different position in a mutable stream.
    """

    payload = canonical_json_bytes(
        {
            "domain": "pevl-event-keyed-v1",
            "event_key": event_key,
            "seed_uint32": uint32_seed(seed),
        }
    )
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _hex64(value: int) -> str:
    return f"{value:016x}"


def _trace_digest(trace: Sequence[Mapping[str, Any]]) -> str:
    return object_sha256(list(trace))


def _common_events(events: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    return {
        str(row["event_key"]): str(row["random_value"])
        for row in events
        if bool(row["shared_exogenous_event"])
    }


def _make_record(trace: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    trace_rows = [dict(row) for row in trace]
    actions = [str(row["action"]) for row in trace_rows]
    states = [str(row["public_state"]) for row in trace_rows]
    action_score = sum(int(action.rsplit("_", 1)[1]) for action in actions)
    return {
        "action_sequence": actions,
        "decision_count": len(trace_rows),
        "errors": {"opponent_policy": 0, "subject_policy": 0},
        "outcome": "win" if action_score % 2 else "loss",
        "public_state_sequence": states,
        "trace": trace_rows,
        "trace_sha256": _trace_digest(trace_rows),
    }


def _first_trace_divergence(
    left: Sequence[Mapping[str, Any]],
    right: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    for index in range(max(len(left), len(right))):
        left_row = dict(left[index]) if index < len(left) else None
        right_row = dict(right[index]) if index < len(right) else None
        if left_row != right_row:
            return {"index": index, "left": left_row, "right": right_row}
    return None


def _record_parity(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> dict[str, Any]:
    compared_fields = (
        "outcome",
        "errors",
        "decision_count",
        "action_sequence",
        "public_state_sequence",
        "trace_sha256",
    )
    equality = {field: left[field] == right[field] for field in compared_fields}
    return {
        "all_compared_fields_equal": all(equality.values()),
        "compared_fields_in_strength_order": list(compared_fields),
        "field_equality": equality,
        "first_trace_divergence": _first_trace_divergence(
            left["trace"], right["trace"]
        ),
        "left_trace_sha256": left["trace_sha256"],
        "right_trace_sha256": right["trace_sha256"],
    }


def simulate_random_stream(
    seed: int,
    *,
    intervention_draw: bool,
    event_keyed: bool,
) -> dict[str, Any]:
    """Simulate a trajectory with mutable-stream or event-keyed randomness."""

    shared_keys = (
        "setup:weather",
        "turn:0:accuracy",
        "turn:0:damage",
        "turn:1:accuracy",
        "turn:1:damage",
    )
    event_order = [shared_keys[0]]
    if intervention_draw:
        event_order.append("intervention:diagnostic_probe")
    event_order.extend(shared_keys[1:])

    events: list[dict[str, Any]] = []
    for position, event_key in enumerate(event_order):
        value = (
            event_keyed_uint64(seed, event_key)
            if event_keyed
            else _counter_uint64(seed, position)
        )
        events.append(
            {
                "event_key": event_key,
                "position": position,
                "random_value": _hex64(value),
                "shared_exogenous_event": event_key in shared_keys,
            }
        )

    shared_values = _common_events(events)
    weather = int(shared_values["setup:weather"], 16) % 3
    trace = []
    for turn in (0, 1):
        accuracy = int(shared_values[f"turn:{turn}:accuracy"], 16)
        damage = int(shared_values[f"turn:{turn}:damage"], 16)
        trace.append(
            {
                "action": f"move_{(accuracy ^ damage) % 4}",
                "public_state": f"weather_{weather}:turn_{turn}",
                "step": turn,
            }
        )
    record = _make_record(trace)
    return {
        "event_log_sha256": _trace_digest(events),
        "events": events,
        "record": record,
        "shared_event_values": shared_values,
        "trace": record["trace"],
        "trace_sha256": record["trace_sha256"],
    }


def simulate_wall_clock_search(seed: int, *, clock_ticks: int) -> dict[str, Any]:
    """Model deadline-limited search using an injected monotonic-clock profile.

    ``clock_ticks`` is scripted rather than measured. A live clock would make
    the fixture unverifiable byte-for-byte; the profile preserves the dependency
    between available time, search depth, and selected action.
    """

    if clock_ticks <= 0:
        raise ValueError("clock_ticks must be positive")
    proposals = [_counter_uint64(seed, index) % 4 for index in range(clock_ticks)]
    action = f"move_{(proposals[0] + clock_ticks) % 4}"
    record = _make_record(
        [{"action": action, "public_state": "root", "step": 0}]
    )
    return {
        "action": action,
        "clock_ticks": clock_ticks,
        "record": record,
        "search_depth": clock_ticks,
        "trace": record["trace"],
        "trace_sha256": record["trace_sha256"],
    }


def simulate_process_global_state(
    seed: int,
    *,
    starting_counter: int,
) -> dict[str, Any]:
    """Model a package whose decision depends on process-local mutable state."""

    offset = _counter_uint64(seed, 0) % 4
    action = f"move_{(offset + starting_counter) % 4}"
    record = _make_record(
        [{"action": action, "public_state": "root", "step": 0}]
    )
    return {
        "action": action,
        "ending_counter": starting_counter + 1,
        "record": record,
        "starting_counter": starting_counter,
        "trace": record["trace"],
        "trace_sha256": record["trace_sha256"],
    }


def _artifact_hash(label: str) -> str:
    return sha256_bytes(f"pevl-synthetic-artifact-v1:{label}".encode("ascii"))


def _artifact_evidence(mode: str, *, distinct_arms: bool = False) -> dict[str, Any]:
    control_hash = _artifact_hash("control-policy")
    candidate_hash = (
        _artifact_hash(f"candidate-policy:{mode}")
        if distinct_arms
        else control_hash
    )
    return {
        "artifact_hashes": {
            "candidate_policy_sha256": candidate_hash,
            "control_policy_sha256": control_hash,
            "engine_sha256": _artifact_hash("engine"),
            "implementation_sha256": _artifact_hash("implementation-v1.1.0"),
            "mode_configuration_sha256": _artifact_hash(mode),
            "opponent_sha256": _artifact_hash("opponent"),
            "protocol_sha256": _artifact_hash("protocol-v1.1.0"),
        },
        "configuration": {
            "decision_budget": 8,
            "environment": {},
            "process_start_method": "spawn",
            "worker_count": 1,
        },
        "fixture_identity_note": (
            "Synthetic identifiers illustrate the required record; they do not "
            "identify an external engine or agent."
        ),
        "implementation_version": SCHEMA_VERSION,
        "protocol_id": "pevl-synthetic-protocol-v1.1.0",
        "repository_commit": None,
        "standalone_identity_basis": "implementation_sha256",
    }


def _seed_evidence(requested_seeds: Sequence[int]) -> dict[str, Any]:
    rows = [
        {
            "engine_seed_uint32": uint32_seed(seed),
            "requested_seed": seed,
            "rng_stream_id": RNG_STREAM_ID,
        }
        for seed in requested_seeds
    ]
    by_engine_seed: dict[int, list[int]] = {}
    for row in rows:
        by_engine_seed.setdefault(row["engine_seed_uint32"], []).append(
            row["requested_seed"]
        )
    collisions = [
        {
            "engine_seed_uint32": engine_seed,
            "requested_seeds": seeds,
        }
        for engine_seed, seeds in sorted(by_engine_seed.items())
        if len(seeds) > 1
    ]
    return {
        "conversion_rule": CONVERSION_RULE,
        "rng_stream_id": RNG_STREAM_ID,
        "schedule_rows": rows,
        "unintended_collisions": collisions,
        "unique_engine_seeds": not collisions,
    }


def _schedule(
    seed: int = DEFAULT_SEED,
    *,
    search_configuration: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "actual_order": "first",
        "engine_seed_uint32": uint32_seed(seed),
        "enqueue_position": 0,
        "environment": {},
        "initial_state_controls": {"scenario": "root_v1"},
        "maximum_decisions": 8,
        "opponent": "synthetic_opponent_v1",
        "physical_seat": 0,
        "process_start_method": "spawn",
        "requested_seed": seed,
        "search_configuration": dict(search_configuration or {"mode": "fixed"}),
        "worker_count": 1,
    }
    return {**payload, "schedule_fingerprint_sha256": object_sha256(payload)}


def _schedule_parity_evidence(schedule: Mapping[str, Any]) -> dict[str, Any]:
    candidate = dict(schedule)
    control = dict(schedule)
    return {
        "all_prespecified_fields_equal": candidate == control,
        "candidate": candidate,
        "complete_expected_cells": True,
        "control": control,
        "expected_arm_records": 2,
        "observed_arm_records": 2,
        "pair_schedule_fingerprint_sha256": object_sha256(
            {"candidate": candidate, "control": control}
        ),
    }


def _audit_row(
    level: int,
    status: str,
    summary: str,
    evidence: Mapping[str, Any],
    *,
    catches_failure: bool = False,
) -> dict[str, Any]:
    names = {number: name for number, name, _kind in LEVELS}
    if level not in names:
        raise ValueError(f"unknown PEVL level: {level}")
    valid_statuses = GATE_STATUSES if level < 8 else ADMISSION_STATUSES
    if status not in valid_statuses:
        raise ValueError(f"unsupported status {status!r} for PEVL level {level}")
    if catches_failure and (status != "fail" or level == 8):
        raise ValueError("only evidence-gate failures can catch a mode")
    evidence_dict = dict(evidence)
    return {
        "catches_failure": catches_failure,
        "evidence": evidence_dict,
        "evidence_sha256": object_sha256(evidence_dict),
        "level": level,
        "level_name": names[level],
        "status": status,
        "summary": summary,
    }


def _admission_evidence(
    decision: str,
    *,
    claim_class: str,
    permitted_wording: str,
    forbidden_wording: str,
    redesign_rule: str,
) -> dict[str, Any]:
    return {
        "analysis_unit": "scheduled_seed_condition",
        "claim_class": claim_class,
        "decision": decision,
        "estimand": "arm difference over the exact synthetic fixture population",
        "forbidden_wording": forbidden_wording,
        "interval_or_test": "not_applicable_deterministic_counterexample",
        "optional_stopping": "forbidden",
        "permitted_wording": permitted_wording,
        "redesign_rule": redesign_rule,
        "target_population": "the prespecified synthetic seeds and execution profiles",
    }


def _finish_mode(
    mode: str,
    description: str,
    audits: Iterable[dict[str, Any]],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    audit_rows = list(audits)
    if [row["level"] for row in audit_rows] != list(range(1, 9)):
        raise AssertionError(f"{mode} does not contain exactly levels 1--8")
    caught_by = [row["level"] for row in audit_rows if row["catches_failure"]]
    if caught_by != EXPECTED_CATCHES[mode]:
        raise AssertionError(
            f"{mode} catch matrix drifted: expected {EXPECTED_CATCHES[mode]}, "
            f"got {caught_by}"
        )
    return {
        "audit": audit_rows,
        "caught_by_levels": caught_by,
        "description": description,
        "evidence": dict(evidence),
        "first_catching_level": caught_by[0] if caught_by else None,
        "mode": mode,
    }


def _clean_mode() -> dict[str, Any]:
    run_a = simulate_random_stream(
        DEFAULT_SEED, intervention_draw=False, event_keyed=True
    )
    run_b = simulate_random_stream(
        DEFAULT_SEED, intervention_draw=False, event_keyed=True
    )
    schedule = _schedule()
    parity = _record_parity(run_a["record"], run_b["record"])
    audits = [
        _audit_row(
            1,
            "pass",
            "Synthetic artifact and configuration identities are complete.",
            _artifact_evidence("clean_deterministic"),
        ),
        _audit_row(
            2,
            "pass",
            "Requested and consumed seeds are recorded and unique.",
            _seed_evidence([DEFAULT_SEED]),
        ),
        _audit_row(
            3,
            "pass",
            "Both arms use the same complete, fingerprinted schedule.",
            _schedule_parity_evidence(schedule),
        ),
        _audit_row(
            4,
            "pass",
            "Byte-identical arms match through the complete public trace.",
            parity,
        ),
        _audit_row(
            5,
            "pass",
            "Serial repeats and the scripted worker profile preserve each arm trace.",
            {
                "arms_tested": ["control", "candidate"],
                "execution_profiles": [
                    "serial_fresh_process_1",
                    "serial_fresh_process_2",
                    "workers_4_fresh_pool",
                ],
                "trace_sha256_by_profile": {
                    "serial_fresh_process_1": run_a["trace_sha256"],
                    "serial_fresh_process_2": run_b["trace_sha256"],
                    "workers_4_fresh_pool": run_b["trace_sha256"],
                },
            },
        ),
        _audit_row(
            6,
            "pass",
            "The only stochastic source is event-keyed and explicitly seeded.",
            {
                "controlled_sources": ["sha256_event_keyed_randomness"],
                "residual_risks": [],
                "uncontrolled_sources": [],
            },
        ),
        _audit_row(
            7,
            "pass",
            "All logged shared event keys map to the same random quantities.",
            {
                "aligned": True,
                "covered_event_keys": sorted(run_a["shared_event_values"]),
                "shared_event_values_sha256": object_sha256(
                    run_a["shared_event_values"]
                ),
            },
        ),
        _audit_row(
            8,
            "admit",
            "The fixture admits an event-aligned CRN demonstration.",
            _admission_evidence(
                "admit_event_aligned",
                claim_class="event_aligned_crn_demonstration",
                permitted_wording=(
                    "Shared logged exogenous events are event-aligned in this fixture."
                ),
                forbidden_wording="Universal alignment outside the logged event set.",
                redesign_rule="No redesign required for this fixture claim.",
            ),
        ),
    ]
    return _finish_mode(
        "clean_deterministic",
        "A deterministic, event-keyed paired evaluation.",
        audits,
        {"run_a": run_a, "run_b": run_b},
    )


def _draw_shift_mode() -> dict[str, Any]:
    control = simulate_random_stream(
        DEFAULT_SEED, intervention_draw=False, event_keyed=False
    )
    treatment = simulate_random_stream(
        DEFAULT_SEED, intervention_draw=True, event_keyed=False
    )
    control_repeat = simulate_random_stream(
        DEFAULT_SEED, intervention_draw=False, event_keyed=False
    )
    treatment_repeat = simulate_random_stream(
        DEFAULT_SEED, intervention_draw=True, event_keyed=False
    )
    shared_keys = sorted(control["shared_event_values"])
    mismatches = [
        {
            "control_value": control["shared_event_values"][key],
            "event_key": key,
            "treatment_value": treatment["shared_event_values"][key],
        }
        for key in shared_keys
        if control["shared_event_values"][key]
        != treatment["shared_event_values"][key]
    ]

    remediated_control = simulate_random_stream(
        DEFAULT_SEED, intervention_draw=False, event_keyed=True
    )
    remediated_treatment = simulate_random_stream(
        DEFAULT_SEED, intervention_draw=True, event_keyed=True
    )
    remediation_mismatches = [
        key
        for key in shared_keys
        if remediated_control["shared_event_values"][key]
        != remediated_treatment["shared_event_values"][key]
    ]
    if not mismatches or remediation_mismatches:
        raise AssertionError("draw-shift demonstration or remediation is ineffective")

    schedule = _schedule()
    audits = [
        _audit_row(
            1,
            "pass",
            "Treatment, control, engine, opponent, and protocol identities are recorded.",
            _artifact_evidence("stateful_draw_shift", distinct_arms=True),
        ),
        _audit_row(
            2,
            "pass",
            "The exact consumed seed and stream identifier are unique and recorded.",
            _seed_evidence([DEFAULT_SEED]),
        ),
        _audit_row(
            3,
            "pass",
            "Treatment and control begin from the same fingerprinted schedule.",
            _schedule_parity_evidence(schedule),
        ),
        _audit_row(
            4,
            "pass",
            "Each arm exactly reproduces all compared record fields.",
            {
                "arms_tested": ["control", "treatment"],
                "control_repeat_parity": _record_parity(
                    control["record"], control_repeat["record"]
                ),
                "treatment_repeat_parity": _record_parity(
                    treatment["record"], treatment_repeat["record"]
                ),
            },
        ),
        _audit_row(
            5,
            "pass",
            "Both arms reproduce across the scripted execution profiles.",
            {
                "arms_tested": ["control", "treatment"],
                "execution_profiles": ["serial_repeat", "workers_4_fresh_pool"],
                "profile_trace_sha256": {
                    "control": control["trace_sha256"],
                    "treatment": treatment["trace_sha256"],
                },
            },
        ),
        _audit_row(
            6,
            "pass",
            "The mutable stream is inventoried and reproducible; that does not prove event alignment.",
            {
                "controlled_sources": ["sha256_counter_indexed_stateful_stream"],
                "residual_risks": ["cross_arm_draw_position_shift"],
                "uncontrolled_sources": [],
            },
        ),
        _audit_row(
            7,
            "fail",
            "One treatment-only draw shifts later shared event quantities.",
            {
                "mismatched_common_events": mismatches,
                "mismatched_count": len(mismatches),
                "shared_event_count": len(shared_keys),
            },
            catches_failure=True,
        ),
        _audit_row(
            8,
            "downgrade",
            "Only bounded seed-matched wording is admitted; CRN wording is suppressed.",
            _admission_evidence(
                "downgrade_to_seed_matched_only",
                claim_class="seed_matched_non_counterfactual_demonstration",
                permitted_wording=(
                    "The arms used the same scheduled seed, but shared events were "
                    "not held fixed."
                ),
                forbidden_wording="Event-aligned CRN or counterfactual comparison.",
                redesign_rule=(
                    "Use event-keyed randomness or repeated independent evaluation "
                    "before making a stronger claim."
                ),
            ),
        ),
    ]
    return _finish_mode(
        "stateful_draw_shift",
        "A deterministic intervention adds one draw and shifts later event meanings.",
        audits,
        {
            "control": control,
            "event_keyed_remediation": {
                "aligned_common_events": not remediation_mismatches,
                "covered_event_keys": shared_keys,
                "level_7_status_after_remediation": "pass",
                "method": "sha256(seed_uint32, semantic_event_key)",
                "mismatched_common_event_keys": remediation_mismatches,
                "remediated_control_event_values_sha256": object_sha256(
                    remediated_control["shared_event_values"]
                ),
                "remediated_treatment_event_values_sha256": object_sha256(
                    remediated_treatment["shared_event_values"]
                ),
            },
            "treatment": treatment,
        },
    )


def _wall_clock_mode() -> dict[str, Any]:
    serial_a = simulate_wall_clock_search(DEFAULT_SEED, clock_ticks=5)
    serial_b = simulate_wall_clock_search(DEFAULT_SEED, clock_ticks=4)
    contended = simulate_wall_clock_search(DEFAULT_SEED, clock_ticks=2)
    parity = _record_parity(serial_a["record"], serial_b["record"])
    if parity["all_compared_fields_equal"]:
        raise AssertionError("scripted clock profiles must produce divergent records")
    schedule = _schedule(
        search_configuration={
            "deadline_type": "monotonic_clock",
            "declared_budget_ticks": 5,
        }
    )
    audits = [
        _audit_row(1, "pass", "The byte-identical A/A artifacts are recorded.", _artifact_evidence("wall_clock_search")),
        _audit_row(2, "pass", "The exact consumed seed and stream are recorded.", _seed_evidence([DEFAULT_SEED])),
        _audit_row(3, "pass", "Declared schedule fields and fingerprints match.", _schedule_parity_evidence(schedule)),
        _audit_row(4, "fail", "Identical arms diverge in the public-state/action record under hidden timing variation.", parity, catches_failure=True),
        _audit_row(
            5,
            "fail",
            "Repeated serial and contended worker profiles both expose timing-sensitive traces.",
            {
                "arms_tested": ["byte_identical_a", "byte_identical_b"],
                "execution_profiles": {
                    "serial_fresh_process_1": {"clock_ticks": 5, "trace_sha256": serial_a["trace_sha256"]},
                    "serial_fresh_process_2": {"clock_ticks": 4, "trace_sha256": serial_b["trace_sha256"]},
                    "workers_4_contended_pool": {"clock_ticks": 2, "trace_sha256": contended["trace_sha256"]},
                },
                "serial_repeat_equal": serial_a["trace_sha256"] == serial_b["trace_sha256"],
                "serial_vs_contended_equal": serial_a["trace_sha256"] == contended["trace_sha256"],
            },
            catches_failure=True,
        ),
        _audit_row(
            6,
            "fail",
            "Source audit identifies a monotonic-clock deadline as a controlled divergence mechanism.",
            {
                "controlled_intervention": "injected_available_clock_ticks",
                "controlled_sources": ["sha256_counter_stream"],
                "residual_risks": [],
                "uncontrolled_sources": ["available_search_time_in_live_systems"],
            },
            catches_failure=True,
        ),
        _audit_row(7, "blocked", "Event alignment is not assessed after trace parity fails.", {"reason": "level_4_failure"}),
        _audit_row(
            8,
            "suppress",
            "The affected paired contrast is not admitted.",
            _admission_evidence(
                "suppress_paired_contrast",
                claim_class="parity_failure_only",
                permitted_wording="Trace divergence is associated with the injected timing profile.",
                forbidden_wording="A valid paired mechanistic treatment contrast.",
                redesign_rule="Freeze a validated context or model execution variability using repeated independent runs.",
            ),
        ),
    ]
    return _finish_mode(
        "wall_clock_search",
        "An injected clock profile changes deadline-limited search depth and action.",
        audits,
        {
            "contended_worker_profile": contended,
            "reference_serial": serial_a,
            "repeated_serial": serial_b,
            "scripted_clock_note": "Clock ticks are injected to make the failure fixture deterministic.",
        },
    )


def _process_state_mode() -> dict[str, Any]:
    fresh_a = simulate_process_global_state(DEFAULT_SEED, starting_counter=0)
    fresh_b = simulate_process_global_state(DEFAULT_SEED, starting_counter=0)
    reused_worker = simulate_process_global_state(DEFAULT_SEED, starting_counter=1)
    parity = _record_parity(fresh_a["record"], reused_worker["record"])
    if parity["all_compared_fields_equal"]:
        raise AssertionError("process-global state fixture must diverge")
    schedule = _schedule()
    audits = [
        _audit_row(1, "pass", "The byte-identical A/A artifacts are recorded.", _artifact_evidence("process_global_state")),
        _audit_row(2, "pass", "The exact consumed seed and stream are recorded.", _seed_evidence([DEFAULT_SEED])),
        _audit_row(3, "pass", "Declared schedule fields and fingerprints match.", _schedule_parity_evidence(schedule)),
        _audit_row(4, "fail", "Identical arms diverge when a worker inherits process-local state.", parity, catches_failure=True),
        _audit_row(
            5,
            "fail",
            "Fresh-process repeats agree, but reused-worker execution diverges.",
            {
                "arms_tested": ["byte_identical_a", "byte_identical_b"],
                "execution_profiles": {
                    "fresh_process_1": {"starting_counter": 0, "trace_sha256": fresh_a["trace_sha256"]},
                    "fresh_process_2": {"starting_counter": 0, "trace_sha256": fresh_b["trace_sha256"]},
                    "reused_worker": {"starting_counter": 1, "trace_sha256": reused_worker["trace_sha256"]},
                },
                "fresh_process_repeat_equal": fresh_a["trace_sha256"] == fresh_b["trace_sha256"],
                "fresh_vs_reused_equal": fresh_a["trace_sha256"] == reused_worker["trace_sha256"],
            },
            catches_failure=True,
        ),
        _audit_row(
            6,
            "fail",
            "Source audit identifies mutable process-global state as the controlled mechanism.",
            {
                "controlled_intervention": "injected_worker_starting_counter",
                "controlled_sources": ["sha256_counter_stream"],
                "residual_risks": [],
                "uncontrolled_sources": ["worker_reuse_history_in_live_systems"],
            },
            catches_failure=True,
        ),
        _audit_row(7, "blocked", "Event alignment is not assessed after trace parity fails.", {"reason": "level_4_failure"}),
        _audit_row(
            8,
            "suppress",
            "The affected paired contrast is not admitted.",
            _admission_evidence(
                "suppress_paired_contrast",
                claim_class="parity_failure_only",
                permitted_wording="Trace divergence is associated with injected process history.",
                forbidden_wording="A valid paired mechanistic treatment contrast.",
                redesign_rule="Use fresh processes or model process-history variability with repeated independent runs.",
            ),
        ),
    ]
    return _finish_mode(
        "process_global_state",
        "A reused worker carries a mutable package-level counter into a run.",
        audits,
        {"fresh_a": fresh_a, "fresh_b": fresh_b, "reused_worker": reused_worker},
    )


def _seed_conversion_mode() -> dict[str, Any]:
    requested = [17, UINT32_MODULUS + 17]
    engine_seeds = [uint32_seed(seed) for seed in requested]
    executions = [
        {
            "first": simulate_random_stream(
                seed, intervention_draw=False, event_keyed=True
            ),
            "repeat": simulate_random_stream(
                seed, intervention_draw=False, event_keyed=True
            ),
        }
        for seed in requested
    ]
    seed_evidence = _seed_evidence(requested)
    collision = not seed_evidence["unique_engine_seeds"]
    if (
        not collision
        or executions[0]["first"]["trace_sha256"]
        != executions[1]["first"]["trace_sha256"]
    ):
        raise AssertionError("uint32 fixture must collapse to one engine trajectory")
    schedules = [_schedule(seed) for seed in requested]
    audits = [
        _audit_row(1, "pass", "Engine adapter and seed-schedule identities are recorded.", _artifact_evidence("uint32_seed_conversion")),
        _audit_row(2, "fail", "Distinct requested seeds collide after uint32 conversion.", seed_evidence, catches_failure=True),
        _audit_row(
            3,
            "pass",
            "Each within-seed arm still receives an equal fingerprinted schedule.",
            {
                "all_within_pair_schedules_equal": True,
                "complete_expected_cells": True,
                "scheduled_units": [_schedule_parity_evidence(schedule) for schedule in schedules],
            },
        ),
        _audit_row(
            4,
            "pass",
            "Each scheduled unit passes A/A record parity, which cannot reveal a cross-unit seed collision.",
            {
                "colliding_cross_unit_trace_sha256": executions[0]["first"]["trace_sha256"],
                "scheduled_unit_parity": [
                    {
                        "requested_seed": seed,
                        "record_parity": _record_parity(
                            execution["first"]["record"],
                            execution["repeat"]["record"],
                        ),
                    }
                    for seed, execution in zip(requested, executions)
                ],
            },
        ),
        _audit_row(5, "pass", "Scripted worker profiles do not alter this conversion fixture.", {"arms_tested": ["control", "candidate"], "worker_profile_parity": True}),
        _audit_row(6, "pass", "The deterministic conversion boundary and random source are inventoried.", {"controlled_sources": ["uint32_seed_conversion", "sha256_event_keyed_randomness"], "residual_risks": ["namespace_collision"], "uncontrolled_sources": []}),
        _audit_row(7, "pass", "Within each pair, logged semantic events remain aligned despite cross-unit collision.", {"namespace_uniqueness_restored": False, "within_pair_event_alignment": True}),
        _audit_row(
            8,
            "suppress",
            "The collided schedule is rejected before statistical analysis.",
            _admission_evidence(
                "reject_seed_schedule",
                claim_class="seed_namespace_failure_only",
                permitted_wording="Distinct requested seeds collided after conversion.",
                forbidden_wording="Independent or distinct engine-seed units.",
                redesign_rule="Construct a collision-free engine-seed schedule and rerun.",
            ),
        ),
    ]
    return _finish_mode(
        "uint32_seed_conversion",
        "Two requested seeds narrow to the same uint32 engine seed.",
        audits,
        {
            "collision": collision,
            "conversion_rows": [
                {
                    "engine_seed_uint32": engine_seed,
                    "requested_seed": requested_seed,
                    "trace_sha256": execution["first"]["trace_sha256"],
                }
                for requested_seed, engine_seed, execution in zip(
                    requested, engine_seeds, executions
                )
            ],
        },
    )


def validate_report(report: Mapping[str, Any]) -> list[str]:
    """Perform dependency-free structural and semantic validation."""

    failures: list[str] = []
    expected_levels = list(range(1, 9))
    expected_level_rows = [
        {
            "kind": kind,
            "level": level,
            "level_name": level_name,
            "valid_statuses": sorted(
                GATE_STATUSES if level < 8 else ADMISSION_STATUSES
            ),
        }
        for level, level_name, kind in LEVELS
    ]
    if report.get("framework") != "Paired Evaluation Validity Ladder":
        failures.append("framework mismatch")
    if report.get("testbed") != "pevl_synthetic_coupling_validation":
        failures.append("testbed mismatch")
    modes = report.get("modes")
    if not isinstance(modes, list):
        failures.append("modes must be a list")
        return failures
    if report.get("schema_version") != SCHEMA_VERSION:
        failures.append("schema_version mismatch")
    if report.get("levels") != expected_level_rows:
        failures.append("level definitions mismatch")
    mode_names = [
        mode.get("mode") if isinstance(mode, Mapping) else None for mode in modes
    ]
    if sorted(name for name in mode_names if isinstance(name, str)) != sorted(
        EXPECTED_CATCHES
    ) or len(mode_names) != len(EXPECTED_CATCHES):
        failures.append("modes must contain each fixture exactly once")
    for mode in modes:
        if not isinstance(mode, Mapping):
            failures.append("each mode must be an object")
            continue
        name = mode.get("mode")
        audits = mode.get("audit")
        if name not in EXPECTED_CATCHES:
            failures.append(f"unknown mode: {name}")
            continue
        if not isinstance(audits, list):
            failures.append(f"{name}: audit must be a list")
            continue
        audit_levels = [
            row.get("level") if isinstance(row, Mapping) else None
            for row in audits
        ]
        if audit_levels != expected_levels:
            failures.append(f"{name}: levels must be exactly 1--8")
            continue
        for row in audits:
            if not isinstance(row, Mapping):
                failures.append(f"{name}: every audit row must be an object")
                continue
            level = row["level"]
            statuses = GATE_STATUSES if level < 8 else ADMISSION_STATUSES
            if row.get("status") not in statuses:
                failures.append(f"{name}: invalid level-{level} status")
            if row.get("evidence_sha256") != object_sha256(row.get("evidence")):
                failures.append(f"{name}: level-{level} evidence digest mismatch")
            if row.get("catches_failure") and (
                level == 8 or row.get("status") != "fail"
            ):
                failures.append(f"{name}: invalid catching-level marker at {level}")
        caught = [row["level"] for row in audits if row.get("catches_failure")]
        if caught != EXPECTED_CATCHES[name]:
            failures.append(f"{name}: caught_by_levels does not match fixture")
        if mode.get("caught_by_levels") != caught:
            failures.append(f"{name}: stored caught_by_levels mismatch")
        expected_first = caught[0] if caught else None
        if mode.get("first_catching_level") != expected_first:
            failures.append(f"{name}: first_catching_level mismatch")
    return failures


def build_report() -> dict[str, Any]:
    """Build and validate the deterministic report without filesystem access."""

    report = {
        "framework": "Paired Evaluation Validity Ladder",
        "levels": [
            {
                "kind": kind,
                "level": level,
                "level_name": level_name,
                "valid_statuses": sorted(
                    GATE_STATUSES if level < 8 else ADMISSION_STATUSES
                ),
            }
            for level, level_name, kind in LEVELS
        ],
        "modes": [
            _clean_mode(),
            _draw_shift_mode(),
            _wall_clock_mode(),
            _process_state_mode(),
            _seed_conversion_mode(),
        ],
        "schema_version": SCHEMA_VERSION,
        "status_semantics": {
            "levels_1_to_7": {
                "blocked": "not assessed because a prerequisite gate failed",
                "fail": "required evidence failed",
                "pass": "required evidence passed within the fixture boundary",
            },
            "level_8": {
                "admit": "the strongest prespecified fixture claim is admitted",
                "downgrade": "only a weaker prespecified claim is admitted",
                "suppress": "the affected paired claim is not admitted",
            },
        },
        "testbed": "pevl_synthetic_coupling_validation",
    }
    failures = validate_report(report)
    if failures:
        raise AssertionError("invalid generated report: " + "; ".join(failures))
    return report


def results_schema() -> dict[str, Any]:
    """Return the published JSON Schema for the machine-readable report."""

    return {
        "$id": "urn:pevl:synthetic-results:1.1.0",
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": False,
        "properties": {
            "framework": {"const": "Paired Evaluation Validity Ladder"},
            "levels": {
                "items": {"$ref": "#/$defs/level"},
                "maxItems": 8,
                "minItems": 8,
                "type": "array",
            },
            "modes": {
                "items": {"$ref": "#/$defs/mode"},
                "maxItems": 5,
                "minItems": 5,
                "type": "array",
                "uniqueItems": True,
            },
            "schema_version": {"const": SCHEMA_VERSION},
            "status_semantics": {"type": "object"},
            "testbed": {"const": "pevl_synthetic_coupling_validation"},
        },
        "required": [
            "framework",
            "levels",
            "modes",
            "schema_version",
            "status_semantics",
            "testbed",
        ],
        "title": "PEVL synthetic coupling-validation results",
        "type": "object",
        "$defs": {
            "audit": {
                "additionalProperties": False,
                "allOf": [
                    {
                        "if": {
                            "properties": {"level": {"maximum": 7}},
                            "required": ["level"],
                        },
                        "then": {
                            "properties": {
                                "status": {
                                    "enum": ["blocked", "fail", "pass"]
                                }
                            }
                        },
                    },
                    {
                        "if": {
                            "properties": {"level": {"const": 8}},
                            "required": ["level"],
                        },
                        "then": {
                            "properties": {
                                "catches_failure": {"const": False},
                                "status": {
                                    "enum": ["admit", "downgrade", "suppress"]
                                },
                            }
                        },
                    },
                ],
                "properties": {
                    "catches_failure": {"type": "boolean"},
                    "evidence": {"type": "object"},
                    "evidence_sha256": {"pattern": "^[0-9a-f]{64}$", "type": "string"},
                    "level": {"maximum": 8, "minimum": 1, "type": "integer"},
                    "level_name": {"type": "string"},
                    "status": {
                        "enum": [
                            "admit",
                            "blocked",
                            "downgrade",
                            "fail",
                            "pass",
                            "suppress",
                        ]
                    },
                    "summary": {"type": "string"},
                },
                "required": [
                    "catches_failure",
                    "evidence",
                    "evidence_sha256",
                    "level",
                    "level_name",
                    "status",
                    "summary",
                ],
                "type": "object",
            },
            "level": {
                "additionalProperties": False,
                "properties": {
                    "kind": {"enum": ["admission_decision", "evidence_gate"]},
                    "level": {"maximum": 8, "minimum": 1, "type": "integer"},
                    "level_name": {"type": "string"},
                    "valid_statuses": {"items": {"type": "string"}, "type": "array"},
                },
                "required": ["kind", "level", "level_name", "valid_statuses"],
                "type": "object",
            },
            "mode": {
                "additionalProperties": False,
                "properties": {
                    "audit": {
                        "items": {"$ref": "#/$defs/audit"},
                        "maxItems": 8,
                        "minItems": 8,
                        "type": "array",
                    },
                    "caught_by_levels": {
                        "items": {"maximum": 7, "minimum": 1, "type": "integer"},
                        "type": "array",
                    },
                    "description": {"type": "string"},
                    "evidence": {"type": "object"},
                    "first_catching_level": {
                        "maximum": 7,
                        "minimum": 1,
                        "type": ["integer", "null"]
                    },
                    "mode": {"enum": sorted(EXPECTED_CATCHES)},
                },
                "required": [
                    "audit",
                    "caught_by_levels",
                    "description",
                    "evidence",
                    "first_catching_level",
                    "mode",
                ],
                "type": "object",
            },
        },
    }


def render_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def render_csv(report: Mapping[str, Any]) -> str:
    output = io.StringIO(newline="")
    fieldnames = (
        "mode",
        "level",
        "level_name",
        "level_kind",
        "status",
        "catches_failure",
        "evidence_sha256",
        "summary",
    )
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    level_kinds = {row["level"]: row["kind"] for row in report["levels"]}
    for mode in report["modes"]:
        for audit in mode["audit"]:
            writer.writerow(
                {
                    "mode": mode["mode"],
                    "level": audit["level"],
                    "level_name": audit["level_name"],
                    "level_kind": level_kinds[audit["level"]],
                    "status": audit["status"],
                    "catches_failure": str(audit["catches_failure"]).lower(),
                    "evidence_sha256": audit["evidence_sha256"],
                    "summary": audit["summary"],
                }
            )
    return output.getvalue()


def rendered_outputs() -> dict[str, str]:
    report = build_report()
    primary = {
        "pevl_matrix.csv": render_csv(report),
        "pevl_results.json": render_json(report),
        "pevl_results.schema.json": render_json(results_schema()),
    }
    manifest = "".join(
        f"{sha256_bytes(content.encode('utf-8'))}  {name}\n"
        for name, content in sorted(primary.items())
    )
    return {**primary, "MANIFEST.sha256": manifest}


def write_outputs(output_dir: Path) -> None:
    if output_dir.is_symlink():
        raise ValueError(f"output directory must not be a symlink: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in rendered_outputs().items():
        path = output_dir / name
        if path.is_symlink():
            raise ValueError(f"refusing to overwrite symlink: {path}")
        path.write_bytes(content.encode("utf-8"))


def verify_outputs(output_dir: Path) -> list[str]:
    expected = rendered_outputs()
    if output_dir.is_symlink():
        return [f"output directory is a symlink: {output_dir}"]
    if output_dir.exists() and not output_dir.is_dir():
        return [f"not a directory: {output_dir}"]
    if not output_dir.exists():
        return [f"missing {name}" for name in sorted(expected)]

    failures: list[str] = []
    expected_names = set(expected)
    actual_names = {path.name for path in output_dir.iterdir()}
    for name in sorted(expected_names):
        path = output_dir / name
        if path.is_symlink():
            failures.append(f"symlink not allowed: {name}")
            continue
        if not path.is_file():
            failures.append(f"missing {name}")
            continue
        if path.read_bytes() != expected[name].encode("utf-8"):
            failures.append(f"content mismatch: {name}")
    failures.extend(
        f"unexpected entry: {name}" for name in sorted(actual_names - expected_names)
    )
    return failures


def _default_output_dir() -> Path:
    return Path(__file__).resolve().parent / "results"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate or verify deterministic PEVL synthetic artifacts."
    )
    parser.add_argument("--version", action="version", version=SCHEMA_VERSION)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("generate", "verify"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument(
            "--output-dir",
            type=Path,
            default=_default_output_dir(),
            help="artifact directory (default: sibling results directory)",
        )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "generate":
        write_outputs(args.output_dir)
        failures = verify_outputs(args.output_dir)
        if failures:
            for failure in failures:
                print(f"FAIL: {failure}")
            return 1
        for name in sorted(rendered_outputs()):
            print(args.output_dir / name)
        return 0
    failures = verify_outputs(args.output_dir)
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print(f"verified {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

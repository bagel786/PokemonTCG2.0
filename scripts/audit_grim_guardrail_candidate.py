#!/usr/bin/env python3
"""Development-only sequential audit for the narrow Grim guardrail director.

This script is deliberately incapable of reading calibration or untouched
holdout rows.  It replays every frozen-d842 development episode in order,
commits only the sanitized candidate action to the stateful director, and
scores exact public-semantic agreement on the independently certified
development corrections.  Runtime search is not part of this audit.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import random
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

import numpy as np

from cg.api import to_observation_class
from ptcg_ai.features import encode_observation
from ptcg_ai.grim_guardrails import GrimGuardrailDirector
from ptcg_ai.grim_runtime_policy import GrimRuntimePolicy
from ptcg_ai.model import NumpyPolicyModel
from ptcg_ai.safety import sanitize_selection
from scripts.audit_grim_proof_search import replay_aligned_decision
from scripts.build_grim_5k_training_bank import deck_hash
from scripts.build_grim_policy_disagreements import (
    replay_decks,
    semantic_action,
    validate_action,
)


DEVELOPMENT_SPLIT = "development"
DEFAULT_BANK = ROOT / "artifacts" / "grim_5k_training_bank"
DEFAULT_CORRECTIONS = (
    ROOT
    / "artifacts"
    / "grim_complete_turn_corrections"
    / "development_intersection.jsonl.gz"
)
DEFAULT_MODEL = ROOT / "artifacts" / "overnight_grim_20260730" / "grim_selected.npz"
DEFAULT_DECK = ROOT / "artifacts" / "recovery_probes" / "extracted" / "control" / "deck.csv"
DEFAULT_OUTPUT = (
    ROOT
    / "artifacts"
    / "grim_guardrail_candidate"
    / "development_coordinated_no_proof_audit.json"
)

BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 842
ONE_SIDED_ALPHA = 0.05
CANDIDATE_MODES = frozenset({"guardrail_only", "coordinated_no_proof"})
RUNTIME_SOURCE_FILES = (
    "ptcg_ai/card_ids.py",
    "ptcg_ai/features.py",
    "ptcg_ai/grim_guardrails.py",
    "ptcg_ai/grim_runtime_policy.py",
    "ptcg_ai/model.py",
    "ptcg_ai/prevention.json",
    "ptcg_ai/prevention.py",
    "ptcg_ai/runtime_proof_director.py",
    "ptcg_ai/safety.py",
    "ptcg_ai/tactical_shield.py",
    "ptcg_ai/view.py",
)


@dataclass(frozen=True)
class FrozenDevelopmentHashes:
    model_sha256: str
    deck_file_sha256: str
    deck_canonical_sha256: str
    bank_manifest_sha256: str
    bank_development_sha256: str
    bank_id: str
    correction_sha256: str
    correction_manifest_sha256: str
    model_behavior_sha256: str
    units: int
    decisions: int
    corrections: int


FROZEN = FrozenDevelopmentHashes(
    model_sha256="D842F85ABFC44AF9F41979F91795E22C92C179B62E04D5A0A2F9C734E70AF1C3",
    deck_file_sha256="92B92BAC9F9163ECFF933B3DC39294D2CC154C8684F3C8497877661419EBC59D",
    deck_canonical_sha256="C20A8A46F5C635773754F03103652F5C534B13DC622448ED2255A97234C103AF",
    bank_manifest_sha256="7730EFFB98D4319F4B1C94F63557783E20645E1D529BDD02969F9EB9BE54FAB4",
    bank_development_sha256="3AB24F80E318FBCC6656A757C41BBE17ACD3D63CD13E95405ECD80B8C80813B5",
    bank_id="23AFC7C9FE4F5E155CCF028E03315FA252D38E3ED085B57F0D18A801CC730247",
    correction_sha256="C9637C690DBE4EE5FA6DF6A96FE7FBD4DA44008666E866804C0C23D55ECF6F21",
    correction_manifest_sha256="F1A709CE27559330FD7E17141F076676C525621826FE2E694F445B6892685C59",
    model_behavior_sha256="509A2D2DD655C33FCFA2803C2A973A6E285AA8D9215A960F7B4C2B67282BAB72",
    units=99,
    decisions=9_018,
    corrections=440,
)


@dataclass(frozen=True)
class VerifiedInputs:
    units: tuple[dict[str, Any], ...]
    corrections: Mapping[tuple[str, int, int], dict[str, Any]]
    bank_manifest: Mapping[str, Any]
    hero_deck: tuple[int, ...]
    provenance: Mapping[str, Any]
    expected: FrozenDevelopmentHashes = FROZEN


@dataclass
class AuditPass:
    decision_rows: list[dict[str, Any]]
    correction_rows: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    invalid_actions: int
    baseline_reproduction_mismatches: int
    baseline_replay_exact_mismatches: int
    baseline_replay_semantic_mismatches: int
    episode_decision_mismatches: int
    latencies: dict[str, list[float]]

    @property
    def decision_digest(self) -> str:
        return stable_json_id(self.decision_rows)


class DisabledRuntimeProof:
    """Identity proof component proving that this proxy executes no search."""

    def __init__(self) -> None:
        self.calls = 0

    def reset(self) -> None:
        self.calls = 0

    def choose(self, _obs: Any, action: Sequence[int]) -> list[int]:
        self.calls += 1
        return list(action)

    @property
    def telemetry(self) -> dict[str, Any]:
        return {"last": {"status": "disabled", "reason": None}}


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def stable_json_id(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest().upper()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _manifest_path(corrections_path: Path) -> Path:
    return corrections_path.with_suffix(".manifest.json")


def _refuse_non_development(split: str) -> None:
    if split != DEVELOPMENT_SPLIT:
        raise ValueError(
            "this audit is hard-locked to development; refusing calibration, "
            "holdout, sealed, or unknown split"
        )


def _refuse_protected_path(path: str | Path, *, label: str) -> None:
    lowered = str(Path(path)).casefold()
    if any(token in lowered for token in ("calibration", "holdout", "sealed")):
        raise ValueError(f"refusing protected {label} path: {path}")


def _require_file_hash(path: Path, expected: str, *, label: str) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"{label} is missing: {path}")
    actual = sha256_file(path)
    if actual != expected:
        raise ValueError(f"{label} hash mismatch: expected {expected}, got {actual}")
    return actual


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return value


def _read_development_rows(path: Path, *, row_kind: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{row_kind} row {line_number} is not an object")
            if row.get("split") != DEVELOPMENT_SPLIT:
                raise ValueError(
                    f"{row_kind} row {line_number} is not development: {row.get('split')!r}"
                )
            rows.append(row)
    return rows


def _load_hero_deck(path: Path, expected: FrozenDevelopmentHashes) -> tuple[int, ...]:
    _require_file_hash(path, expected.deck_file_sha256, label="frozen deck file")
    try:
        cards = tuple(
            int(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    except ValueError as exc:
        raise ValueError("frozen deck contains a non-integer card id") from exc
    if len(cards) != 60:
        raise ValueError(f"frozen deck must contain 60 cards, got {len(cards)}")
    actual = deck_hash(cards)
    if actual != expected.deck_canonical_sha256:
        raise ValueError(
            "frozen deck canonical hash mismatch: "
            f"expected {expected.deck_canonical_sha256}, got {actual}"
        )
    return cards


def _validate_correction_row(
    row: Mapping[str, Any], expected: FrozenDevelopmentHashes
) -> tuple[str, int, int]:
    try:
        coordinate = (str(row["episode_id"]), int(row["seat"]), int(row["step"]))
        observation = row["observation"]
        action = validate_action(observation, row["action"], policy_name="certified_label")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"malformed certified correction: {exc}") from exc
    candidate_semantic_id = stable_json_id(semantic_action(observation, action))
    if candidate_semantic_id != str(row.get("candidate_semantic_id") or "").upper():
        raise ValueError(f"certified candidate semantic mismatch at {coordinate}")
    correction = row.get("correction") or {}
    decision = correction.get("decision") or {}
    if (
        decision.get("admitted") is not True
        or correction.get("coverage_complete") is not True
        or correction.get("all_worlds_nonnegative") is not True
        or str(correction.get("anchor_sha256") or "").upper() != expected.model_sha256
    ):
        raise ValueError(f"correction is not fully certified at {coordinate}")
    return coordinate


def verify_inputs(
    *,
    split: str,
    bank_dir: str | Path,
    corrections_path: str | Path,
    model_path: str | Path,
    deck_path: str | Path,
    expected: FrozenDevelopmentHashes = FROZEN,
) -> VerifiedInputs:
    """Verify every frozen development binding before policy execution."""

    # This check intentionally precedes every filesystem read.
    _refuse_non_development(split)
    bank_dir = Path(bank_dir).resolve()
    corrections_path = Path(corrections_path).resolve()
    model_path = Path(model_path).resolve()
    deck_path = Path(deck_path).resolve()
    _refuse_protected_path(bank_dir, label="bank")
    _refuse_protected_path(corrections_path, label="correction")

    model_sha256 = _require_file_hash(
        model_path, expected.model_sha256, label="frozen d842 model"
    )
    hero_deck = _load_hero_deck(deck_path, expected)

    bank_manifest_path = bank_dir / "manifest.json"
    development_path = bank_dir / "development.jsonl.gz"
    bank_manifest_sha256 = _require_file_hash(
        bank_manifest_path, expected.bank_manifest_sha256, label="training-bank manifest"
    )
    bank_development_sha256 = _require_file_hash(
        development_path, expected.bank_development_sha256, label="development bank shard"
    )
    bank_manifest = _read_json(bank_manifest_path)
    development_manifest = (bank_manifest.get("splits") or {}).get(DEVELOPMENT_SPLIT) or {}
    if (
        str(bank_manifest.get("bank_id") or "").upper() != expected.bank_id
        or str(bank_manifest.get("frozen_model_sha256") or "").upper()
        != expected.model_sha256
        or str(bank_manifest.get("expected_deck_canonical_sha256") or "").upper()
        != expected.deck_canonical_sha256
        or development_manifest.get("split") != DEVELOPMENT_SPLIT
        or str(development_manifest.get("shard_sha256") or "").upper()
        != expected.bank_development_sha256
    ):
        raise ValueError("development bank manifest failed frozen-input validation")
    units = _read_development_rows(development_path, row_kind="bank")
    units.sort(key=lambda row: (str(row.get("episode_id")), int(row.get("hero_seat", -1))))
    if len(units) != expected.units:
        raise ValueError(f"development bank unit count mismatch: {len(units)} != {expected.units}")
    unit_coordinates: set[tuple[str, int]] = set()
    for row in units:
        coordinate = (str(row.get("episode_id")), int(row.get("hero_seat", -1)))
        if coordinate in unit_coordinates:
            raise ValueError(f"duplicate development episode/seat: {coordinate}")
        unit_coordinates.add(coordinate)
        if (
            row.get("unit_type") != "whole_episode_team"
            or str(row.get("frozen_model_sha256") or "").upper() != expected.model_sha256
            or str(row.get("hero_deck_canonical_sha256") or "").upper()
            != expected.deck_canonical_sha256
            or int(row.get("hero_decisions", -1)) < 0
        ):
            raise ValueError(f"development bank row failed validation: {coordinate}")
    declared_decisions = sum(int(row["hero_decisions"]) for row in units)
    if declared_decisions != expected.decisions:
        raise ValueError(
            f"development decision count mismatch: {declared_decisions} != {expected.decisions}"
        )

    correction_manifest_path = _manifest_path(corrections_path)
    correction_sha256 = _require_file_hash(
        corrections_path, expected.correction_sha256, label="certified development corrections"
    )
    correction_manifest_sha256 = _require_file_hash(
        correction_manifest_path,
        expected.correction_manifest_sha256,
        label="certified-correction manifest",
    )
    correction_manifest = _read_json(correction_manifest_path)
    provenance = correction_manifest.get("provenance") or {}
    counts = correction_manifest.get("counts") or {}
    if (
        correction_manifest.get("status") != "complete"
        or correction_manifest.get("passed") is not True
        or correction_manifest.get("sealed_holdout_used") is not False
        or provenance.get("splits") != [DEVELOPMENT_SPLIT]
        or str(provenance.get("model_sha256") or "").upper() != expected.model_sha256
        or str(provenance.get("model_behavior_sha256") or "").upper()
        != expected.model_behavior_sha256
        or str(provenance.get("hero_deck_canonical_sha256") or "").upper()
        != expected.deck_canonical_sha256
        or str(correction_manifest.get("output_sha256") or "").upper()
        != expected.correction_sha256
        or int(counts.get("retained_corrections", -1)) != expected.corrections
    ):
        raise ValueError("certified-correction manifest failed frozen-input validation")
    correction_rows = _read_development_rows(corrections_path, row_kind="correction")
    if len(correction_rows) != expected.corrections:
        raise ValueError(
            f"certified correction count mismatch: {len(correction_rows)} != {expected.corrections}"
        )
    corrections: dict[tuple[str, int, int], dict[str, Any]] = {}
    for row in correction_rows:
        coordinate = _validate_correction_row(row, expected)
        if coordinate in corrections:
            raise ValueError(f"duplicate certified decision coordinate: {coordinate}")
        if coordinate[:2] not in unit_coordinates:
            raise ValueError(f"certified correction is outside the development bank: {coordinate}")
        unit = next(
            item
            for item in units
            if (str(item["episode_id"]), int(item["hero_seat"])) == coordinate[:2]
        )
        if str(row.get("actual_order")) != str(unit.get("actual_order")):
            raise ValueError(f"certified order disagrees with bank at {coordinate}")
        corrections[coordinate] = row

    return VerifiedInputs(
        units=tuple(units),
        corrections=corrections,
        bank_manifest=bank_manifest,
        hero_deck=hero_deck,
        provenance={
            "model_sha256": model_sha256,
            "model_behavior_sha256": expected.model_behavior_sha256,
            "deck_file_sha256": expected.deck_file_sha256,
            "deck_canonical_sha256": expected.deck_canonical_sha256,
            "bank_manifest_sha256": bank_manifest_sha256,
            "bank_id": expected.bank_id,
            "bank_development_sha256": bank_development_sha256,
            "correction_sha256": correction_sha256,
            "correction_manifest_sha256": correction_manifest_sha256,
            "runtime_source_sha256": {
                relative: sha256_file(ROOT / relative) for relative in RUNTIME_SOURCE_FILES
            },
        },
        expected=expected,
    )


def d842_intent(model: NumpyPolicyModel, obs: Any) -> tuple[list[int], int, list[int]]:
    """Return the exact original submission ranking, count, and action."""

    features = encode_observation(obs, model.feature_version)
    logits, count_logits, _ = model.predict(features)
    if not len(logits):
        return [], 0, []
    # Do not specify a sort kind: this is byte-for-byte the frozen submission's
    # tie behavior, and changing it would invalidate the control.
    ranked = np.argsort(-logits).astype(int).tolist()
    if obs.select.minCount == obs.select.maxCount:
        desired = int(obs.select.maxCount)
    else:
        minimum = int(obs.select.minCount)
        maximum = min(int(obs.select.maxCount), len(count_logits) - 1)
        desired = minimum + int(np.argmax(count_logits[minimum : maximum + 1]))
    return ranked, desired, sanitize_selection(obs.select, ranked, desired)


def _validate_guardrail_result(obs: Any, value: Any) -> tuple[list[int], int, str | None]:
    if not isinstance(value, (tuple, list)) or len(value) != 3:
        raise ValueError("guardrail apply must return (ranked, desired, reason)")
    ranked, desired, reason = value
    if (
        not isinstance(ranked, list)
        or any(isinstance(index, bool) or not isinstance(index, int) for index in ranked)
        or len(set(ranked)) != len(ranked)
        or any(index < 0 or index >= len(obs.select.option) for index in ranked)
    ):
        raise ValueError("guardrail returned a malformed current-option ranking")
    if isinstance(desired, bool) or not isinstance(desired, int):
        raise ValueError("guardrail desired count must be an integer")
    if reason is not None and (not isinstance(reason, str) or not reason.strip()):
        raise ValueError("guardrail intervention reason must be a non-empty string")
    return ranked, desired, reason


def _replay_path(unit: Mapping[str, Any], bank_manifest: Mapping[str, Any]) -> Path:
    replay_root = Path(str(bank_manifest.get("source_replay_root") or "")).resolve()
    if not replay_root.is_dir():
        raise FileNotFoundError(f"development replay root is missing: {replay_root}")
    path = (replay_root / str(unit["replay_path"])).resolve()
    try:
        path.relative_to(replay_root)
    except ValueError as exc:
        raise ValueError(f"replay path escapes development replay root: {path}") from exc
    return path


def _public_semantic_id(observation: Mapping[str, Any], action: Sequence[int]) -> str:
    return stable_json_id(semantic_action(observation, list(action)))


def _coordinator_telemetry(policy: Any) -> dict[str, Any]:
    value = policy.telemetry()
    last = value.get("last") if isinstance(value, Mapping) else None
    if not isinstance(last, Mapping):
        raise ValueError("coordinator did not expose named last-call telemetry")
    return {
        "status": str(last.get("status") or "unknown"),
        "source": str(last.get("source") or "unknown"),
        "guardrail_reason": last.get("guardrail_reason"),
        "tactical_reason": last.get("tactical_reason"),
        "suppressed_tactical_reason": last.get("suppressed_tactical_reason"),
        "proof_reason": last.get("proof_reason"),
        "error_stage": last.get("error_stage"),
        "error_type": last.get("error_type"),
    }


def _named_coordinator_reason(telemetry: Mapping[str, Any]) -> str | None:
    values = []
    for key in ("guardrail_reason", "tactical_reason", "proof_reason"):
        value = telemetry.get(key)
        if value is not None:
            values.append(f"{key.removesuffix('_reason')}:{value}")
    return "|".join(values) if values else None


def audit_pass(
    inputs: VerifiedInputs,
    *,
    model: Any,
    director_factory: Callable[[], Any] | None = None,
    intent_fn: Callable[[Any, Any], tuple[list[int], int, list[int]]] = d842_intent,
    candidate_mode: str = "guardrail_only",
) -> AuditPass:
    """Run one honest sequential pass over complete development streams."""

    if candidate_mode not in CANDIDATE_MODES:
        raise ValueError(f"unknown candidate mode: {candidate_mode}")
    if director_factory is None:
        if candidate_mode == "guardrail_only":
            director_factory = GrimGuardrailDirector
        else:
            director_factory = lambda: GrimRuntimePolicy(
                hero_deck=inputs.hero_deck,
                proof=DisabledRuntimeProof(),
            )

    decisions: list[dict[str, Any]] = []
    correction_records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    invalid_actions = 0
    baseline_mismatches = 0
    baseline_replay_exact_mismatches = 0
    baseline_replay_semantic_mismatches = 0
    episode_count_mismatches = 0
    latencies: dict[str, list[float]] = {
        "observation_conversion": [],
        "frozen_d842": [],
        "candidate_policy": [],
        "guardrail_apply_and_sanitize": [],
        "coordinator_choose": [],
        "guardrail_commit": [],
        "candidate_total": [],
    }

    for unit in inputs.units:
        episode = str(unit["episode_id"])
        seat = int(unit["hero_seat"])
        director = director_factory()
        director.reset()
        audited_in_episode = 0
        first_divergence_step: int | None = None
        public_first_player_verified = False
        try:
            path = _replay_path(unit, inputs.bank_manifest)
            payload = path.read_bytes()
            replay_sha256 = sha256_bytes(payload)
            if replay_sha256 != str(unit.get("replay_sha256") or "").upper():
                raise ValueError(f"replay hash mismatch: {replay_sha256}")
            if len(payload) != int(unit.get("replay_bytes", -1)):
                raise ValueError("replay byte count mismatch")
            replay = json.loads(payload)
            replay_episode = str((replay.get("info") or {}).get("EpisodeId") or replay.get("id") or "")
            if replay_episode != episode:
                raise ValueError(f"replay episode mismatch: {replay_episode}")
            decks = replay_decks(replay)
            if deck_hash(decks[seat]) != inputs.expected.deck_canonical_sha256:
                raise ValueError("hero replay handshake is not the frozen Grim deck")
            steps = replay.get("steps") or []
            for step_t in range(max(0, len(steps) - 1)):
                aligned = replay_aligned_decision(steps, seat, step_t)
                if aligned is None:
                    continue
                audited_in_episode += 1
                coordinate = (episode, seat, step_t)
                raw_obs = aligned.observation
                started_total = time.perf_counter_ns()
                before = time.perf_counter_ns()
                obs = to_observation_class(raw_obs)
                latencies["observation_conversion"].append(
                    (time.perf_counter_ns() - before) / 1_000_000.0
                )
                # Pregame setup legitimately uses firstPlayer == -1.  Once the
                # public state resolves the coin flip, bind it to the bank's
                # independently recorded actual order.  Never reinterpret -1
                # as seat 1 going first.
                public_first_player = int(obs.current.firstPlayer)
                if public_first_player in (0, 1):
                    public_first_player_verified = True
                    if public_first_player != int(unit["actual_first_player"]):
                        raise ValueError(
                            "public first-player state disagrees with development unit"
                        )
                current_order = str(unit["actual_order"])

                before = time.perf_counter_ns()
                ranked, desired, baseline = intent_fn(model, obs)
                latencies["frozen_d842"].append(
                    (time.perf_counter_ns() - before) / 1_000_000.0
                )
                try:
                    validate_action(raw_obs, baseline, policy_name="frozen_d842")
                except ValueError:
                    invalid_actions += 1
                    raise

                component_telemetry: dict[str, Any] = {}
                before = time.perf_counter_ns()
                if candidate_mode == "guardrail_only":
                    applied = director.apply(obs, list(ranked), int(desired))
                    new_ranked, new_desired, reason = _validate_guardrail_result(obs, applied)
                    candidate = sanitize_selection(obs.select, new_ranked, new_desired)
                    candidate_elapsed = (time.perf_counter_ns() - before) / 1_000_000.0
                    latencies["guardrail_apply_and_sanitize"].append(candidate_elapsed)
                else:
                    candidate = list(director.choose(obs, list(ranked), int(desired)))
                    component_telemetry = _coordinator_telemetry(director)
                    reason = _named_coordinator_reason(component_telemetry)
                    candidate_elapsed = (time.perf_counter_ns() - before) / 1_000_000.0
                    latencies["coordinator_choose"].append(candidate_elapsed)
                latencies["candidate_policy"].append(candidate_elapsed)
                try:
                    validate_action(raw_obs, candidate, policy_name="guardrail_candidate")
                except ValueError:
                    invalid_actions += 1
                    raise

                baseline_semantic_id = _public_semantic_id(raw_obs, baseline)
                candidate_semantic_id = _public_semantic_id(raw_obs, candidate)
                historical_action = list(aligned.historical_action)
                historical_semantic_id = _public_semantic_id(raw_obs, historical_action)
                baseline_replay_exact_changed = list(baseline) != historical_action
                baseline_replay_semantic_changed = (
                    baseline_semantic_id != historical_semantic_id
                )
                baseline_replay_exact_mismatches += int(baseline_replay_exact_changed)
                baseline_replay_semantic_mismatches += int(
                    baseline_replay_semantic_changed
                )
                semantic_changed = candidate_semantic_id != baseline_semantic_id
                if semantic_changed and reason is None:
                    raise ValueError("semantic action drift has no named guardrail reason")
                counterfactual_changed = candidate_semantic_id != historical_semantic_id
                post_counterfactual_divergence = first_divergence_step is not None
                if counterfactual_changed and first_divergence_step is None:
                    first_divergence_step = step_t

                # Commit the candidate emitted for this prompt.  The historical
                # row-t+1 action was used only to validate replay alignment and
                # is never allowed to invent director state.
                if candidate_mode == "guardrail_only":
                    before = time.perf_counter_ns()
                    director.commit(obs, list(candidate))
                    latencies["guardrail_commit"].append(
                        (time.perf_counter_ns() - before) / 1_000_000.0
                    )
                else:
                    # GrimRuntimePolicy sanitized and committed exactly once
                    # inside choose; a second audit-side commit would corrupt
                    # staged setup state.
                    latencies["guardrail_commit"].append(0.0)
                latencies["candidate_total"].append(
                    (time.perf_counter_ns() - started_total) / 1_000_000.0
                )

                observation_id = stable_json_id(raw_obs)
                record = {
                    "episode_id": episode,
                    "seat": seat,
                    "step": step_t,
                    "actual_order": current_order,
                    "observation_sha256": observation_id,
                    "baseline_semantic_id": baseline_semantic_id,
                    "candidate_semantic_id": candidate_semantic_id,
                    "historical_semantic_id": historical_semantic_id,
                    "baseline_replay_exact_changed": baseline_replay_exact_changed,
                    "baseline_replay_semantic_changed": baseline_replay_semantic_changed,
                    "exact_index_changed": list(candidate) != list(baseline),
                    "semantic_changed": semantic_changed,
                    "counterfactual_changed": counterfactual_changed,
                    "reason": reason,
                    "candidate_mode": candidate_mode,
                    "coordinator_status": component_telemetry.get("status"),
                    "coordinator_source": component_telemetry.get("source"),
                    "guardrail_reason": component_telemetry.get("guardrail_reason"),
                    "tactical_reason": component_telemetry.get("tactical_reason"),
                    "suppressed_tactical_reason": component_telemetry.get(
                        "suppressed_tactical_reason"
                    ),
                    "policy_error_stage": component_telemetry.get("error_stage"),
                    "policy_error_type": component_telemetry.get("error_type"),
                    "post_counterfactual_divergence": post_counterfactual_divergence,
                    "first_divergence_step": first_divergence_step,
                }
                decisions.append(record)

                label = inputs.corrections.get(coordinate)
                if label is not None:
                    if stable_json_id(label["observation"]) != observation_id:
                        raise ValueError("certified observation does not match replay boundary")
                    label_semantic_id = str(label["candidate_semantic_id"]).upper()
                    declared_baseline_id = str(label["baseline_semantic_id"]).upper()
                    if baseline_semantic_id != declared_baseline_id:
                        baseline_mismatches += 1
                    correction_records.append(
                        {
                            "episode_id": episode,
                            "seat": seat,
                            "step": step_t,
                            "actual_order": current_order,
                            "baseline_semantic_id": baseline_semantic_id,
                            "candidate_semantic_id": candidate_semantic_id,
                            "label_semantic_id": label_semantic_id,
                            "baseline_match": int(baseline_semantic_id == label_semantic_id),
                            "candidate_match": int(candidate_semantic_id == label_semantic_id),
                            "baseline_reproduced": baseline_semantic_id == declared_baseline_id,
                            "reason": reason,
                            "candidate_mode": candidate_mode,
                            "post_counterfactual_divergence": post_counterfactual_divergence,
                            "conservative_proxy_eligible": not post_counterfactual_divergence,
                        }
                    )
        except Exception as exc:
            errors.append(
                {
                    "episode_id": episode,
                    "seat": seat,
                    "next_step": audited_in_episode,
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
            )
        expected_decisions = int(unit["hero_decisions"])
        if audited_in_episode != expected_decisions:
            episode_count_mismatches += 1
        if audited_in_episode == expected_decisions and not public_first_player_verified:
            errors.append(
                {
                    "episode_id": episode,
                    "seat": seat,
                    "next_step": audited_in_episode,
                    "type": "ValueError",
                    "message": "public first-player state never resolved",
                }
            )

    decisions.sort(key=lambda row: (row["episode_id"], row["seat"], row["step"]))
    correction_records.sort(
        key=lambda row: (row["episode_id"], row["seat"], row["step"])
    )
    errors.sort(key=canonical_json)
    return AuditPass(
        decision_rows=decisions,
        correction_rows=correction_records,
        errors=errors,
        invalid_actions=invalid_actions,
        baseline_reproduction_mismatches=baseline_mismatches,
        baseline_replay_exact_mismatches=baseline_replay_exact_mismatches,
        baseline_replay_semantic_mismatches=baseline_replay_semantic_mismatches,
        episode_decision_mismatches=episode_count_mismatches,
        latencies=latencies,
    )


def clustered_lower_bound(
    rows: Sequence[Mapping[str, Any]],
    *,
    samples: int = BOOTSTRAP_SAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> float:
    """Deterministic one-sided bound, resampling complete episodes."""

    if samples <= 0:
        raise ValueError("bootstrap samples must be positive")
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["episode_id"])].append(row)
    if not grouped:
        raise ValueError("cannot bootstrap an empty correction stratum")
    clusters = [grouped[key] for key in sorted(grouped)]
    sufficient = [
        (
            sum(int(row["candidate_match"]) - int(row["baseline_match"]) for row in cluster),
            len(cluster),
        )
        for cluster in clusters
    ]
    rng = random.Random(seed)
    values: list[float] = []
    for _ in range(samples):
        numerator = denominator = 0
        for _cluster in sufficient:
            delta, count = sufficient[rng.randrange(len(sufficient))]
            numerator += delta
            denominator += count
        values.append(numerator / denominator)
    values.sort()
    index = min(len(values) - 1, max(0, int(ONE_SIDED_ALPHA * len(values))))
    return values[index]


def _proxy_stratum(
    rows: Sequence[Mapping[str, Any]],
    *,
    samples: int,
) -> dict[str, Any]:
    if not rows:
        raise ValueError("development proxy stratum is empty")
    count = len(rows)
    baseline_matches = sum(int(row["baseline_match"]) for row in rows)
    candidate_matches = sum(int(row["candidate_match"]) for row in rows)
    lift = (candidate_matches - baseline_matches) / count
    lower = clustered_lower_bound(rows, samples=samples)
    return {
        "decisions": count,
        "episode_clusters": len({str(row["episode_id"]) for row in rows}),
        "frozen_d842_agreement": baseline_matches / count,
        "candidate_agreement": candidate_matches / count,
        "candidate_minus_d842": lift,
        "candidate_minus_d842_points": 100.0 * lift,
        "one_sided_95_lower": lower,
        "one_sided_95_lower_points": 100.0 * lower,
    }


def _latency_summary(values: Sequence[float]) -> dict[str, float | int]:
    if not values:
        return {"count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}
    ordered = sorted(float(value) for value in values)

    def at(fraction: float) -> float:
        return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]

    return {
        "count": len(ordered),
        "mean": sum(ordered) / len(ordered),
        "p50": at(0.50),
        "p95": at(0.95),
        "p99": at(0.99),
        "max": ordered[-1],
    }


def _drift_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    exact = sum(bool(row["exact_index_changed"]) for row in rows)
    semantic = sum(bool(row["semantic_changed"]) for row in rows)
    reported = Counter(str(row["reason"]) for row in rows if row.get("reason") is not None)
    changed_reasons = Counter(
        str(row["reason"])
        for row in rows
        if row["semantic_changed"] and row.get("reason") is not None
    )
    no_op_reasons = Counter(
        str(row["reason"])
        for row in rows
        if not row["semantic_changed"] and row.get("reason") is not None
    )
    coordinator_statuses = Counter(
        str(row["coordinator_status"])
        for row in rows
        if row.get("coordinator_status") is not None
    )
    coordinator_sources = Counter(
        str(row["coordinator_source"])
        for row in rows
        if row.get("coordinator_source") is not None
    )
    guardrail_reasons = Counter(
        str(row["guardrail_reason"])
        for row in rows
        if row.get("guardrail_reason") is not None
    )
    tactical_reasons = Counter(
        str(row["tactical_reason"])
        for row in rows
        if row.get("tactical_reason") is not None
    )
    by_order: dict[str, Any] = {}
    for order in ("first", "second"):
        part = [row for row in rows if row["actual_order"] == order]
        by_order[order] = {
            "decisions": len(part),
            "semantic_changes": sum(bool(row["semantic_changed"]) for row in part),
            "semantic_change_rate": (
                sum(bool(row["semantic_changed"]) for row in part) / len(part) if part else 0.0
            ),
        }
    return {
        "decisions": len(rows),
        "exact_index_changes": exact,
        "exact_index_change_rate": exact / len(rows) if rows else 0.0,
        "public_semantic_changes": semantic,
        "public_semantic_change_rate": semantic / len(rows) if rows else 0.0,
        "candidate_vs_historical_semantic_divergences": sum(
            bool(row["counterfactual_changed"]) for row in rows
        ),
        "frozen_d842_vs_historical_exact_mismatches": sum(
            bool(row["baseline_replay_exact_changed"]) for row in rows
        ),
        "frozen_d842_vs_historical_semantic_mismatches": sum(
            bool(row["baseline_replay_semantic_changed"]) for row in rows
        ),
        "changed_episode_clusters": len(
            {str(row["episode_id"]) for row in rows if row["semantic_changed"]}
        ),
        "post_counterfactual_divergence_decisions": sum(
            bool(row.get("post_counterfactual_divergence")) for row in rows
        ),
        "post_counterfactual_divergence_episode_clusters": len(
            {
                str(row["episode_id"])
                for row in rows
                if row.get("post_counterfactual_divergence")
            }
        ),
        "first_counterfactual_divergences": [
            {
                "episode_id": str(row["episode_id"]),
                "seat": int(row["seat"]),
                "step": int(row["step"]),
                "reason": row.get("reason"),
            }
            for row in rows
            if row["counterfactual_changed"]
            and int(row["step"]) == int(row.get("first_divergence_step", -1))
        ],
        "named_reason_reports": sum(reported.values()),
        "unclassified_semantic_changes": sum(
            row["semantic_changed"] and row.get("reason") is None for row in rows
        ),
        "reported_reasons": dict(sorted(reported.items())),
        "semantic_change_reasons": dict(sorted(changed_reasons.items())),
        "semantic_noop_reasons": dict(sorted(no_op_reasons.items())),
        "coordinator_statuses": dict(sorted(coordinator_statuses.items())),
        "coordinator_sources": dict(sorted(coordinator_sources.items())),
        "guardrail_component_reasons": dict(sorted(guardrail_reasons.items())),
        "tactical_component_reasons": dict(sorted(tactical_reasons.items())),
        "coordinator_internal_error_reports": sum(
            row.get("policy_error_stage") is not None for row in rows
        ),
        "by_actual_order": by_order,
    }


def build_report(
    inputs: VerifiedInputs,
    first: AuditPass,
    second: AuditPass,
    *,
    bootstrap_samples: int,
    candidate_mode: str,
) -> dict[str, Any]:
    deterministic = first.decision_digest == second.decision_digest
    corrections_complete = (
        len(first.correction_rows) == len(inputs.corrections) == inputs.expected.corrections
    )
    decisions_complete = len(first.decision_rows) == inputs.expected.decisions
    descriptive_strata: dict[str, Any] = {}
    conservative_strata: dict[str, Any] = {}
    if corrections_complete:
        descriptive_strata["overall"] = _proxy_stratum(
            first.correction_rows, samples=bootstrap_samples
        )
        for order in ("first", "second"):
            part = [row for row in first.correction_rows if row["actual_order"] == order]
            descriptive_strata[order] = _proxy_stratum(part, samples=bootstrap_samples)
        conservative = [
            row for row in first.correction_rows if row["conservative_proxy_eligible"]
        ]
        conservative_strata["overall"] = _proxy_stratum(
            conservative, samples=bootstrap_samples
        )
        for order in ("first", "second"):
            part = [row for row in conservative if row["actual_order"] == order]
            conservative_strata[order] = _proxy_stratum(part, samples=bootstrap_samples)

    safety_checks = {
        "development_only": True,
        "runtime_search_absent": True,
        "all_development_decisions_audited": decisions_complete,
        "all_440_certified_labels_scored": corrections_complete,
        "zero_exceptions": not first.errors and not second.errors,
        "zero_invalid_actions": first.invalid_actions == second.invalid_actions == 0,
        "exact_d842_reproduced_on_all_labels": (
            first.baseline_reproduction_mismatches
            == second.baseline_reproduction_mismatches
            == 0
        ),
        "exact_d842_public_semantics_reproduced_on_all_replay_actions": (
            first.baseline_replay_semantic_mismatches
            == second.baseline_replay_semantic_mismatches
            == 0
        ),
        "complete_episode_stream_counts": (
            first.episode_decision_mismatches == second.episode_decision_mismatches == 0
        ),
        "all_semantic_drift_has_named_reason": (
            _drift_summary(first.decision_rows)["unclassified_semantic_changes"] == 0
        ),
        "zero_coordinator_internal_errors": (
            _drift_summary(first.decision_rows)["coordinator_internal_error_reports"] == 0
            and _drift_summary(second.decision_rows)["coordinator_internal_error_reports"] == 0
        ),
        "repeat_decision_digest_identical": deterministic,
    }
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "complete" if all(safety_checks.values()) else "failed",
        "passed": all(safety_checks.values()),
        "expected_split": DEVELOPMENT_SPLIT,
        "candidate_mode": candidate_mode,
        "sealed_or_calibration_rows_read": False,
        "development_proxy_only": True,
        "promotion_qualification": False,
        "runtime_search_executed": False,
        "causal_interpretation": (
            "after an episode's first candidate action divergence, subsequent replay "
            "observations follow historical d842 rather than the candidate trajectory; "
            "the full replay-sequential proxy is descriptive only, the conservative proxy "
            "excludes every later label, and direct simulated games are the causal gate"
        ),
        "scoring_unit": "exact public semantic action, independent of temporary option index",
        "confidence_method": {
            "name": "deterministic whole-episode cluster percentile bootstrap",
            "one_sided_alpha": ONE_SIDED_ALPHA,
            "samples": bootstrap_samples,
            "seed": BOOTSTRAP_SEED,
        },
        "provenance": dict(inputs.provenance),
        "scope": {
            "development_episode_streams": len(inputs.units),
            "expected_development_decisions": inputs.expected.decisions,
            "audited_development_decisions": len(first.decision_rows),
            "certified_development_labels": len(inputs.corrections),
            "scored_certified_labels": len(first.correction_rows),
        },
        "development_certified_proxy": {
            "replay_sequential_descriptive": descriptive_strata,
            "pre_divergence_conservative": conservative_strata,
            "post_divergence_labels_excluded_from_conservative": sum(
                bool(row["post_counterfactual_divergence"])
                for row in first.correction_rows
            ),
        },
        "action_drift": _drift_summary(first.decision_rows),
        "latency_ms": {
            name: _latency_summary(values) for name, values in sorted(first.latencies.items())
        },
        "repeat_latency_ms": {
            name: _latency_summary(values) for name, values in sorted(second.latencies.items())
        },
        "audit": {
            "decision_digest_sha256": first.decision_digest,
            "repeat_decision_digest_sha256": second.decision_digest,
            "invalid_actions": first.invalid_actions,
            "repeat_invalid_actions": second.invalid_actions,
            "baseline_reproduction_mismatches": first.baseline_reproduction_mismatches,
            "repeat_baseline_reproduction_mismatches": second.baseline_reproduction_mismatches,
            "baseline_replay_exact_mismatches": first.baseline_replay_exact_mismatches,
            "repeat_baseline_replay_exact_mismatches": second.baseline_replay_exact_mismatches,
            "baseline_replay_semantic_mismatches": first.baseline_replay_semantic_mismatches,
            "repeat_baseline_replay_semantic_mismatches": second.baseline_replay_semantic_mismatches,
            "baseline_replay_exact_mismatch_records": [
                {
                    "episode_id": row["episode_id"],
                    "seat": row["seat"],
                    "step": row["step"],
                    "public_semantics_equal": not row["baseline_replay_semantic_changed"],
                }
                for row in first.decision_rows
                if row["baseline_replay_exact_changed"]
            ],
            "episode_decision_count_mismatches": first.episode_decision_mismatches,
            "repeat_episode_decision_count_mismatches": second.episode_decision_mismatches,
            "errors": first.errors,
            "repeat_errors": second.errors,
        },
        "safety_checks": safety_checks,
    }
    report["report_digest_sha256"] = stable_json_id(
        {
            key: value
            for key, value in report.items()
            if key not in {"latency_ms", "repeat_latency_ms"}
        }
    )
    return report


def run(
    *,
    split: str = DEVELOPMENT_SPLIT,
    bank_dir: str | Path = DEFAULT_BANK,
    corrections_path: str | Path = DEFAULT_CORRECTIONS,
    model_path: str | Path = DEFAULT_MODEL,
    deck_path: str | Path = DEFAULT_DECK,
    output_path: str | Path | None = DEFAULT_OUTPUT,
    bootstrap_samples: int = BOOTSTRAP_SAMPLES,
    expected: FrozenDevelopmentHashes = FROZEN,
    director_factory: Callable[[], Any] | None = None,
    candidate_mode: str = "coordinated_no_proof",
) -> dict[str, Any]:
    # Refuse protected data before resolving, hashing, or opening any path.
    _refuse_non_development(split)
    if bootstrap_samples <= 0:
        raise ValueError("bootstrap samples must be positive")
    if candidate_mode not in CANDIDATE_MODES:
        raise ValueError(f"candidate_mode must be one of {sorted(CANDIDATE_MODES)}")
    if output_path is not None:
        _refuse_protected_path(output_path, label="output")
    inputs = verify_inputs(
        split=split,
        bank_dir=bank_dir,
        corrections_path=corrections_path,
        model_path=model_path,
        deck_path=deck_path,
        expected=expected,
    )
    model = NumpyPolicyModel(Path(model_path))
    first = audit_pass(
        inputs,
        model=model,
        director_factory=director_factory,
        candidate_mode=candidate_mode,
    )
    second = audit_pass(
        inputs,
        model=model,
        director_factory=director_factory,
        candidate_mode=candidate_mode,
    )
    report = build_report(
        inputs,
        first,
        second,
        bootstrap_samples=bootstrap_samples,
        candidate_mode=candidate_mode,
    )
    if output_path is not None:
        target = Path(output_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(target)
    return report


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", default=DEVELOPMENT_SPLIT)
    parser.add_argument("--bank", type=Path, default=DEFAULT_BANK)
    parser.add_argument("--corrections", type=Path, default=DEFAULT_CORRECTIONS)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--deck", type=Path, default=DEFAULT_DECK)
    parser.add_argument("--bootstrap-samples", type=_positive_int, default=BOOTSTRAP_SAMPLES)
    parser.add_argument(
        "--candidate-mode",
        choices=sorted(CANDIDATE_MODES),
        default="coordinated_no_proof",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run(
        split=args.split,
        bank_dir=args.bank,
        corrections_path=args.corrections,
        model_path=args.model,
        deck_path=args.deck,
        output_path=args.output,
        bootstrap_samples=args.bootstrap_samples,
        candidate_mode=args.candidate_mode,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

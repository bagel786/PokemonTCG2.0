#!/usr/bin/env python3
"""Replay-audit tactical proof-search coverage around frozen d842.

The audit never uses ladder ratings or replay outcomes inside the policy.  They
are read only after decisions are made to summarize where triggers occurred.
The exact opponent deck handshake is supplied as an oracle so this measures an
upper bound on search usefulness before a public-only live classifier is added.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

import numpy as np

from cg.api import to_observation_class
from ptcg_ai.features import encode_observation
from ptcg_ai.model import NumpyPolicyModel
from ptcg_ai.proof_search import (
    ProofSearchConfig,
    SelectiveProofSearch,
    public_state_digest,
    semantic_action_key,
    semantic_candidates,
)
from ptcg_ai.safety import sanitize_selection
from scripts.build_grim_5k_training_bank import deck_hash, replay_decks


DEFAULT_MODEL = ROOT / "artifacts" / "overnight_grim_20260730" / "grim_selected.npz"
DEFAULT_BANK = ROOT / "artifacts" / "grim_5k_training_bank"
DEFAULT_DECK = ROOT / "artifacts" / "recovery_probes" / "extracted" / "control" / "deck.csv"
FROZEN_D842_SHA256 = "D842F85ABFC44AF9F41979F91795E22C92C179B62E04D5A0A2F9C734E70AF1C3"
FROZEN_DECK_CANONICAL_SHA256 = "C20A8A46F5C635773754F03103652F5C534B13DC622448ED2255A97234C103AF"
AUDITABLE_SPLITS = frozenset({"development", "calibration"})


@dataclass(frozen=True)
class ReplayAlignedDecision:
    """One public observation at row t paired with its action stored at t+1."""

    observation_step_t: int
    action_step_t_plus_1: int
    observation: Mapping[str, Any]
    historical_action: tuple[int, ...]


@dataclass(frozen=True)
class FrozenD842ContinuationSelector:
    """Stateless exact-d842 selector used inside one native candidate branch."""

    model: NumpyPolicyModel

    def choose(self, obs: Any) -> list[int]:
        return d842_action(self.model, obs)


@dataclass(frozen=True)
class FrozenD842SelectorFactory:
    """Create a distinct selector wrapper for every branch and every world."""

    model: NumpyPolicyModel

    def __call__(self) -> FrozenD842ContinuationSelector:
        return FrozenD842ContinuationSelector(self.model)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def d842_action(model: NumpyPolicyModel, obs) -> list[int]:
    features = encode_observation(obs, model.feature_version)
    logits, count_logits, _ = model.predict(features)
    if not len(logits):
        return []
    # Match the frozen submission exactly; changing NumPy's sort kind can alter
    # tied logits and would make this an invalid d842 control audit.
    ranked = np.argsort(-logits).astype(int).tolist()
    minimum = int(obs.select.minCount)
    maximum = min(int(obs.select.maxCount), len(count_logits) - 1, len(ranked))
    if minimum == maximum:
        desired = maximum
    else:
        desired = minimum + int(np.argmax(count_logits[minimum : maximum + 1]))
    return sanitize_selection(obs.select, ranked, desired)


def validate_replay_aligned_action(
    raw_observation: Mapping[str, Any], raw_action: Any
) -> tuple[int, ...]:
    """Validate an action against the options in its row-t observation.

    Kaggle records the response to row ``t`` on row ``t + 1``.  Performing this
    validation before converting the observation makes a shifted or stale action
    an explicit audit error instead of silently evaluating the wrong decision.
    """

    select = raw_observation.get("select")
    if not isinstance(select, Mapping):
        raise ValueError("aligned observation has no selection")
    options = select.get("option")
    if not isinstance(options, list) or not options:
        raise ValueError("aligned observation has no legal options")
    if not isinstance(raw_action, list):
        raise ValueError("row t+1 does not contain a list action")
    if any(isinstance(index, bool) or not isinstance(index, int) for index in raw_action):
        raise ValueError("aligned action contains a non-integer option index")
    action = tuple(int(index) for index in raw_action)
    minimum = int(select.get("minCount", 0))
    maximum = int(select.get("maxCount", len(options)))
    if not minimum <= len(action) <= maximum:
        raise ValueError("aligned action violates selection count bounds")
    if len(set(action)) != len(action):
        raise ValueError("aligned action contains duplicate option indices")
    if any(index < 0 or index >= len(options) for index in action):
        raise ValueError("aligned action index is outside row-t options")
    return action


def replay_aligned_decision(
    steps: Sequence[Any], seat: int, step_t: int
) -> ReplayAlignedDecision | None:
    """Return a strictly aligned active decision, or ``None`` for a non-decision."""

    if step_t < 0 or step_t + 1 >= len(steps):
        return None
    current_step = steps[step_t]
    following_step = steps[step_t + 1]
    if not isinstance(current_step, list) or not isinstance(following_step, list):
        raise ValueError("replay step is not a per-seat list")
    if seat < 0 or seat >= len(current_step) or seat >= len(following_step):
        raise ValueError("replay step is missing the audited seat")
    current_row = current_step[seat]
    following_row = following_step[seat]
    if not isinstance(current_row, Mapping) or not isinstance(following_row, Mapping):
        raise ValueError("replay seat row is malformed")
    if str(current_row.get("status", "")).upper() != "ACTIVE":
        return None
    raw_observation = current_row.get("observation")
    if not isinstance(raw_observation, Mapping):
        raise ValueError("active replay row has no observation")
    current = raw_observation.get("current")
    select = raw_observation.get("select")
    # Deck handshakes and pre-game transport rows are not policy selections.
    if not isinstance(current, Mapping) or not isinstance(select, Mapping):
        return None
    if int(current.get("yourIndex", -1)) != seat:
        raise ValueError("row-t observation viewer does not match audited seat")
    historical_action = validate_replay_aligned_action(
        raw_observation, following_row.get("action")
    )
    return ReplayAlignedDecision(
        observation_step_t=step_t,
        action_step_t_plus_1=step_t + 1,
        observation=raw_observation,
        historical_action=historical_action,
    )


def iter_replay_aligned_decisions(
    replay: Mapping[str, Any], seat: int
) -> Iterator[ReplayAlignedDecision]:
    steps = replay.get("steps") or []
    if not isinstance(steps, list):
        raise ValueError("replay steps are malformed")
    for step_t in range(max(0, len(steps) - 1)):
        decision = replay_aligned_decision(steps, seat, step_t)
        if decision is not None:
            yield decision


def load_units(bank: Path, splits: list[str]) -> tuple[list[dict], dict]:
    manifest = json.loads((bank / "manifest.json").read_text(encoding="utf-8"))
    rows = []
    for split in splits:
        path = bank / f"{split}.jsonl.gz"
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            rows.extend(json.loads(line) for line in handle)
    rows.sort(key=lambda row: (str(row["episode_id"]), int(row["hero_seat"])))
    return rows, manifest


def replay_path(unit: dict, manifest: dict) -> Path:
    root = Path(manifest["source_replay_root"])
    return root / unit["replay_path"]


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(fraction * len(ordered))))]


def proof_attempt_signature(result: Any, obs: Any) -> dict[str, Any]:
    """Stable classification signature; latency is deliberately excluded."""

    return {
        "status": str(result.status),
        "result_reason": str(result.reason),
        "selected_semantic": json.loads(semantic_action_key(obs, result.action)),
        "strict_worlds": int(result.strict_worlds),
        "coverage": dict(sorted(result.coverage.items())),
        "errors": list(result.errors),
        "public_state_digest": str(result.public_state_digest),
    }


def proof_attempts_consistent(results: Sequence[Any], obs: Any) -> bool:
    return len({canonical_sha256(proof_attempt_signature(result, obs)) for result in results}) == 1


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank", type=Path, default=DEFAULT_BANK)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--splits", default="development,calibration")
    parser.add_argument("--scan-only", action="store_true")
    parser.add_argument(
        "--runner-mode",
        choices=("complete-turn", "one-prompt"),
        default="complete-turn",
        help="native comparison horizon; complete-turn is the certification path",
    )
    parser.add_argument("--max-episodes", type=_nonnegative_int, default=0)
    parser.add_argument("--max-decisions", type=_nonnegative_int, default=0)
    parser.add_argument("--max-search-triggers", type=_nonnegative_int, default=250)
    parser.add_argument(
        "--search-trigger-stride",
        type=_positive_int,
        default=1,
        help="search every Nth tactical trigger after the offset (deterministic)",
    )
    parser.add_argument("--search-trigger-offset", type=_nonnegative_int, default=0)
    parser.add_argument("--worlds", type=_positive_int, default=8)
    parser.add_argument("--min-strict-worlds", type=_positive_int, default=4)
    parser.add_argument("--timeout-ms", type=float, default=250.0)
    parser.add_argument("--max-candidates", type=_positive_int, default=4)
    parser.add_argument("--max-turn-steps", type=_positive_int, default=48)
    parser.add_argument(
        "--proof-repeats",
        type=_positive_int,
        default=3,
        help="identical repeated comparisons required before a proof is admitted",
    )
    parser.add_argument("--max-errors", type=_positive_int, default=100)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts" / "grim_proof_search" / "replay_audit.json",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    splits = [value.strip() for value in args.splits.split(",") if value.strip()]
    if not splits:
        raise ValueError("at least one audit split is required")
    forbidden = sorted(set(splits) - AUDITABLE_SPLITS)
    if forbidden:
        raise ValueError(
            "only development/calibration may be audited; sealed or unknown splits: "
            + ",".join(forbidden)
        )
    if not args.timeout_ms > 0:
        raise ValueError("timeout-ms must be positive")
    units, bank_manifest = load_units(args.bank, splits)
    available_units = len(units)
    if args.max_episodes:
        units = units[: args.max_episodes]

    model_sha256 = sha256_file(args.model)
    if model_sha256 != FROZEN_D842_SHA256:
        raise ValueError(
            f"model is not frozen d842: expected {FROZEN_D842_SHA256}, got {model_sha256}"
        )
    model = NumpyPolicyModel(args.model)
    config = ProofSearchConfig(
        worlds=args.worlds,
        min_strict_worlds=args.min_strict_worlds,
        max_candidates=args.max_candidates,
        timeout_seconds=args.timeout_ms / 1000.0,
    )
    hero_deck = bank_manifest.get("expected_deck") or [
        int(line) for line in DEFAULT_DECK.read_text().splitlines() if line.strip()
    ]
    hero_deck_sha256 = deck_hash(hero_deck)
    if hero_deck_sha256 != FROZEN_DECK_CANONICAL_SHA256:
        raise ValueError(
            "audit requires the exact frozen-d842 deck: expected "
            f"{FROZEN_DECK_CANONICAL_SHA256}, got {hero_deck_sha256}"
        )
    native_mode = args.runner_mode.replace("-", "_")
    search = None
    if not args.scan_only:
        search = SelectiveProofSearch(
            hero_deck=hero_deck,
            config=config,
            native_mode=native_mode,
            continuation_selector_factory=(
                FrozenD842SelectorFactory(model) if native_mode == "complete_turn" else None
            ),
            max_turn_steps=args.max_turn_steps,
        )
    totals = Counter()
    by_reason = defaultdict(Counter)
    by_order = defaultdict(Counter)
    by_matchup = defaultdict(Counter)
    by_outcome = defaultdict(Counter)
    latencies: list[float] = []
    native_attempt_latencies: list[float] = []
    errors: list[dict] = []
    changed_records = []
    search_records = []
    started = time.time()
    processed_episodes = 0
    decision_limit_reached = False

    def bump_slices(unit: Mapping[str, Any], metric: str) -> None:
        by_order[str(unit["actual_order"])][metric] += 1
        by_matchup[str(unit["opponent_matchup"])][metric] += 1
        by_outcome[str(unit["outcome"])][metric] += 1

    for unit_index, unit in enumerate(units, 1):
        processed_episodes += 1
        path = replay_path(unit, bank_manifest)
        replay = json.loads(path.read_text(encoding="utf-8"))
        decks = replay_decks(replay)
        seat = int(unit["hero_seat"])
        if deck_hash(decks[seat]) != hero_deck_sha256:
            errors.append({"episode_id": unit["episode_id"], "error": "hero_deck_mismatch"})
            continue
        opponent_deck = list(decks[1 - seat])
        opponent_deck_sha256 = deck_hash(opponent_deck)
        if opponent_deck_sha256 is None:
            errors.append({"episode_id": unit["episode_id"], "error": "missing_opponent_deck"})
            continue
        if opponent_deck_sha256 != unit.get("opponent_deck_canonical_sha256"):
            errors.append({"episode_id": unit["episode_id"], "error": "opponent_deck_mismatch"})
            continue
        steps = replay.get("steps") or []
        for step_index in range(max(0, len(steps) - 1)):
            try:
                aligned = replay_aligned_decision(steps, seat, step_index)
                if aligned is None:
                    continue
                if args.max_decisions and totals["decisions"] >= args.max_decisions:
                    decision_limit_reached = True
                    break
                raw_obs = aligned.observation
                actual = list(aligned.historical_action)
                obs = to_observation_class(raw_obs)
                root_digest = public_state_digest(obs)
                baseline = d842_action(model, obs)
                candidates = semantic_candidates(obs, baseline, max_candidates=args.max_candidates)
                totals["decisions"] += 1
                if baseline != actual:
                    totals["baseline_replay_exact_disagreements"] += 1
                if semantic_action_key(obs, baseline) != semantic_action_key(obs, actual):
                    totals["baseline_replay_disagreements"] += 1
                if len(candidates) <= 1:
                    totals["not_triggered"] += 1
                    continue
                totals["tactical_triggers"] += 1
                reasons = sorted({candidate.reason for candidate in candidates if not candidate.is_baseline})
                for reason in reasons:
                    by_reason[reason]["triggers"] += 1
                bump_slices(unit, "triggers")
                trigger_ordinal = totals["tactical_triggers"] - 1
                selected_by_stride = (
                    trigger_ordinal >= args.search_trigger_offset
                    and (trigger_ordinal - args.search_trigger_offset)
                    % args.search_trigger_stride
                    == 0
                )
                if selected_by_stride:
                    totals["stride_selected_triggers"] += 1
                if (
                    args.scan_only
                    or not selected_by_stride
                    or totals["searched"] >= args.max_search_triggers
                ):
                    continue
                totals["searched"] += 1
                bump_slices(unit, "searched")
                for reason in reasons:
                    by_reason[reason]["searched"] += 1
                assert search is not None
                attempt_results = []
                attempt_records = []
                before = time.perf_counter()
                for repeat_index in range(args.proof_repeats):
                    attempt_before = time.perf_counter()
                    attempt = search.choose(obs, baseline, opponent_deck)
                    attempt_latency = (time.perf_counter() - attempt_before) * 1000.0
                    native_attempt_latencies.append(attempt_latency)
                    signature = proof_attempt_signature(attempt, obs)
                    attempt_records.append({
                        "repeat_index": repeat_index,
                        **signature,
                        "latency_ms": attempt_latency,
                    })
                    attempt_results.append(attempt)
                latency = (time.perf_counter() - before) * 1000.0
                latencies.append(latency)
                repeat_consistent = proof_attempts_consistent(attempt_results, obs)
                primary = attempt_results[0]
                baseline_semantic = json.loads(semantic_action_key(obs, baseline))
                if repeat_consistent:
                    effective_status = primary.status
                    effective_reason = primary.reason
                    effective_action = list(primary.action)
                    effective_strict_worlds = int(primary.strict_worlds)
                    effective_coverage = dict(primary.coverage)
                    effective_errors = list(primary.errors)
                else:
                    effective_status = "abstained"
                    effective_reason = "nondeterministic_repeat"
                    effective_action = list(baseline)
                    effective_strict_worlds = 0
                    effective_coverage = {}
                    effective_errors = ["repeated proof signatures did not match"]
                    totals["repeat_signature_mismatches"] += 1
                selected_semantic = json.loads(semantic_action_key(obs, effective_action))
                digest_matches_root = all(
                    attempt.public_state_digest == root_digest for attempt in attempt_results
                )
                totals[f"status:{effective_status}"] += 1
                totals[f"result:{effective_reason}"] += 1
                bump_slices(unit, f"status:{effective_status}")
                bump_slices(unit, f"result:{effective_reason}")
                for reason in reasons:
                    by_reason[reason][f"status:{effective_status}"] += 1
                    by_reason[reason][f"result:{effective_reason}"] += 1
                search_records.append({
                    "episode_id": unit["episode_id"],
                    "submission_id": unit["submission_id"],
                    "observation_step_t": aligned.observation_step_t,
                    "historical_action_step_t_plus_1": aligned.action_step_t_plus_1,
                    "trigger_ordinal": trigger_ordinal,
                    "actual_order": unit["actual_order"],
                    "outcome": unit["outcome"],
                    "opponent_matchup": unit["opponent_matchup"],
                    "candidate_reasons": reasons,
                    "candidate_count": len(candidates),
                    "status": effective_status,
                    "result_reason": effective_reason,
                    "trigger": primary.trigger,
                    "strict_worlds": effective_strict_worlds,
                    "coverage": effective_coverage,
                    "errors": effective_errors,
                    "repeat_consistent": repeat_consistent,
                    "proof_attempts": attempt_records,
                    "public_state_digest": root_digest,
                    "proof_digest_matches_root": digest_matches_root,
                    "baseline_semantic": baseline_semantic,
                    "selected_semantic": selected_semantic,
                    "latency_ms": latency,
                })
                if effective_status == "proved":
                    totals["proved"] += 1
                    bump_slices(unit, "proved")
                    for reason in reasons:
                        by_reason[reason]["proved"] += 1
                    changed_records.append({
                        "episode_id": unit["episode_id"],
                        "submission_id": unit["submission_id"],
                        "observation_step_t": aligned.observation_step_t,
                        "historical_action_step_t_plus_1": aligned.action_step_t_plus_1,
                        "actual_order": unit["actual_order"],
                        "outcome": unit["outcome"],
                        "opponent_matchup": unit["opponent_matchup"],
                        "trigger": primary.trigger,
                        "proof_reason": effective_reason,
                        "strict_worlds": effective_strict_worlds,
                        "public_state_digest": root_digest,
                        "proof_digest_matches_root": digest_matches_root,
                        "proof_repeats": args.proof_repeats,
                        "comparison_boundary": (
                            "complete_root_actor_turn" if native_mode == "complete_turn"
                            else "one_native_prompt"
                        ),
                        "historical_semantic": json.loads(semantic_action_key(obs, actual)),
                        "baseline_semantic": baseline_semantic,
                        "candidate_semantic": selected_semantic,
                        "latency_ms": latency,
                    })
            except Exception as exc:
                totals["exceptions"] += 1
                if len(errors) < args.max_errors:
                    errors.append({
                        "episode_id": unit["episode_id"],
                        "observation_step_t": step_index,
                        "expected_action_step_t_plus_1": step_index + 1,
                        "error": f"{type(exc).__name__}: {exc}",
                    })
        if decision_limit_reached:
            break
        if unit_index % 10 == 0:
            print(json.dumps({
                "episodes": unit_index,
                "decisions": totals["decisions"],
                "triggers": totals["tactical_triggers"],
                "searched": totals["searched"],
                "proved": totals["proved"],
            }), flush=True)
    decision_digest_rows = [
        {
            "public_state_digest": row["public_state_digest"],
            "selected_semantic": row["selected_semantic"],
        }
        for row in search_records
    ]
    classification_digest_rows = [
        {
            "public_state_digest": row["public_state_digest"],
            "status": row["status"],
            "result_reason": row["result_reason"],
            "strict_worlds": row["strict_worlds"],
        }
        for row in search_records
    ]
    result = {
        "status": "scan_only" if args.scan_only else "proof_audit",
        "splits": splits,
        "sealed_holdout_used": False,
        "bank_id": bank_manifest["bank_id"],
        "bank_status": bank_manifest["bank_status"],
        "model_sha256": model_sha256,
        "frozen_d842_verified": model_sha256 == FROZEN_D842_SHA256,
        "hero_deck_canonical_sha256": hero_deck_sha256,
        "frozen_deck_verified": hero_deck_sha256 == FROZEN_DECK_CANONICAL_SHA256,
        "opponent_deck_source": "replay_handshake_oracle_upper_bound",
        "replay_alignment": "observation_step_t/action_step_t_plus_1",
        "comparison_boundary": (
            "terminal_or_complete_root_actor_turn"
            if native_mode == "complete_turn"
            else "terminal_or_equal_one_prompt_boundary"
        ),
        "continuation_policy": (
            "fresh_stateless_frozen_d842_selector_per_candidate_per_world"
            if native_mode == "complete_turn"
            else None
        ),
        "native_randomness_policy": (
            "fail_closed_on_repeated_signature_drift; independent full-audit digest match required"
            if native_mode == "complete_turn"
            else "equal-boundary diagnostic only"
        ),
        "config": {
            "runner_mode": args.runner_mode,
            "worlds": config.worlds,
            "min_strict_worlds": config.min_strict_worlds,
            "max_candidates": config.max_candidates,
            "max_turn_steps": args.max_turn_steps,
            "proof_repeats": args.proof_repeats,
            "timeout_ms": args.timeout_ms,
            "max_episodes": args.max_episodes,
            "max_decisions": args.max_decisions,
            "max_search_triggers": args.max_search_triggers,
            "search_trigger_stride": args.search_trigger_stride,
            "search_trigger_offset": args.search_trigger_offset,
        },
        "available_episodes": available_units,
        "selected_episodes": len(units),
        "processed_episodes": processed_episodes,
        "episodes": processed_episodes,
        "decision_limit_reached": decision_limit_reached,
        "totals": dict(sorted(totals.items())),
        "by_reason": {key: dict(value) for key, value in sorted(by_reason.items())},
        "by_actual_order": {key: dict(value) for key, value in sorted(by_order.items())},
        "by_matchup": {key: dict(value) for key, value in sorted(by_matchup.items())},
        "by_episode_outcome_diagnostic_only": {
            key: dict(value) for key, value in sorted(by_outcome.items())
        },
        "latency_ms": {
            "measurement": "total_for_all_required_repeats",
            "count": len(latencies),
            "median": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
            "max": max(latencies, default=0.0),
        },
        "native_attempt_latency_ms": {
            "count": len(native_attempt_latencies),
            "median": percentile(native_attempt_latencies, 0.50),
            "p95": percentile(native_attempt_latencies, 0.95),
            "p99": percentile(native_attempt_latencies, 0.99),
            "max": max(native_attempt_latencies, default=0.0),
        },
        "decision_digest_sha256": canonical_sha256(decision_digest_rows),
        "classification_digest_sha256": canonical_sha256(classification_digest_rows),
        "search_records": search_records,
        "changed_records": changed_records,
        "errors": errors,
        "elapsed_seconds": time.time() - started,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

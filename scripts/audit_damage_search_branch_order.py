#!/usr/bin/env python3
"""Audit candidate-order invariance on real late damage-target game states."""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

from cg.api import to_observation_class  # noqa: E402
from cg.game import battle_finish, battle_select, battle_start  # noqa: E402
from ptcg_ai.external import ExternalSubmissionAgent  # noqa: E402


def _audit_action(policy, obs) -> tuple[list[int], dict | None]:
    damage_module = sys.modules[policy.__class__.__module__]
    if not damage_module.damage_search_eligible(obs, min_turn=policy.min_turn):
        return policy.choose(obs), None
    greedy = policy.base.choose(obs)
    features = damage_module.encode_observation(obs, policy.model.feature_version)
    logits, count_logits, _ = policy.model.predict(features)
    if not policy.search.should_search(logits, count_logits, obs.select):
        return greedy, None
    candidates = [greedy]
    for index in np.argsort(-logits).astype(int).tolist():
        candidate = [index]
        if candidate not in candidates:
            candidates.append(candidate)
        if len(candidates) >= policy.search.max_candidates:
            break
    rng_state = policy.search._rng.getstate()
    priorities = {tuple(action): index for index, action in enumerate(candidates)}
    started = time.perf_counter()
    normal = policy.search.evaluate_candidates(
        obs, candidates, policy.hero_deck, priorities=priorities
    )
    normal_ms = (time.perf_counter() - started) * 1000.0
    policy.search._rng.setstate(rng_state)
    started = time.perf_counter()
    reverse = policy.search.evaluate_candidates(
        obs, list(reversed(candidates)), policy.hero_deck, priorities=priorities
    )
    reverse_ms = (time.perf_counter() - started) * 1000.0
    result = {
        "turn": int(obs.current.turn),
        "context": int(obs.select.context),
        "option_count": len(obs.select.option),
        "candidates": candidates,
        "normal": normal,
        "reverse": reverse,
        "invariant": normal == reverse,
        "normal_ms": normal_ms,
        "reverse_ms": reverse_ms,
    }
    return (normal if normal is not None else greedy), result


def run(args: argparse.Namespace) -> dict:
    candidate = Path(args.candidate).resolve()
    control = Path(args.control).resolve()
    deck = [int(line) for line in (candidate / "deck.csv").read_text().splitlines() if line.strip()]
    control_deck = [int(line) for line in (control / "deck.csv").read_text().splitlines() if line.strip()]
    if deck != control_deck or len(deck) != 60:
        raise ValueError("audit requires identical valid candidate/control decks")
    records: list[dict] = []
    errors: list[str] = []
    search_telemetry: Counter[str] = Counter()
    games = wins = decisions = 0
    random.seed(args.seed)
    np.random.seed(args.seed % (2**32))
    while games < args.max_games and len(records) < args.attempts:
        candidate_agent = ExternalSubmissionAgent(candidate)
        control_agent = ExternalSubmissionAgent(control)
        candidate_seat = games % 2
        decks = [deck, control_deck] if candidate_seat == 0 else [control_deck, deck]
        agents = {candidate_seat: candidate_agent, 1 - candidate_seat: control_agent}
        raw, start = battle_start(decks[0], decks[1])
        if start.errorType != 0:
            raise RuntimeError(f"engine rejected deck: {start.errorType}")
        try:
            while True:
                obs = to_observation_class(raw)
                if obs.current is not None and int(obs.current.result) >= 0:
                    wins += int(obs.current.result == candidate_seat)
                    break
                chooser = int(obs.current.yourIndex)
                if chooser == candidate_seat:
                    policy = candidate_agent.module._AGENT.policy
                    try:
                        action, record = _audit_action(policy, obs)
                        if record is not None:
                            record["game"] = games
                            record["candidate_seat"] = candidate_seat
                            records.append(record)
                    except Exception as exc:  # fail-closed audit accounting
                        errors.append(f"{type(exc).__name__}: {exc}")
                        action = candidate_agent(raw)
                else:
                    action = agents[chooser](raw)
                raw = battle_select(action)
                decisions += 1
                if decisions > args.max_games * args.max_decisions:
                    raise RuntimeError("global audit decision cap exceeded")
        finally:
            search_telemetry.update(candidate_agent.module._AGENT.policy.search.telemetry)
            battle_finish()
            candidate_agent.close()
            control_agent.close()
        games += 1
    counts = Counter(
        "invariant" if record["invariant"] else "order_sensitive" for record in records
    )
    latencies = [record[key] for record in records for key in ("normal_ms", "reverse_ms")]
    failure_keys = {
        "candidate_errors",
        "determinization_errors",
        "end_errors",
        "incomplete",
        "release_errors",
        "timeouts",
    }
    engine_failures = {
        key: search_telemetry[key] for key in failure_keys if search_telemetry[key]
    }
    result_counts = Counter(
        "both_selected"
        if record["normal"] is not None and record["reverse"] is not None
        else "both_rejected"
        if record["normal"] is None and record["reverse"] is None
        else "asymmetric"
        for record in records
    )
    result = {
        "status": "passed" if len(records) >= args.attempts and not errors and not counts["order_sensitive"] and not engine_failures else "failed",
        "requested_attempts": args.attempts,
        "audited_attempts": len(records),
        "games": games,
        "candidate_wins": wins,
        "decisions": decisions,
        "invariant": counts["invariant"],
        "order_sensitive": counts["order_sensitive"],
        "result_counts": dict(result_counts),
        "errors": errors,
        "search_telemetry": dict(search_telemetry),
        "engine_failures": engine_failures,
        "latency_ms": {
            "mean": float(np.mean(latencies)) if latencies else None,
            "p95": float(np.percentile(latencies, 95)) if latencies else None,
            "max": max(latencies) if latencies else None,
        },
        "context_counts": dict(Counter(str(record["context"]) for record in records)),
        "records": records,
        "caveat": "identical submitted Grim deck was used for opponent hidden-state determinization; public one-card Grim evidence does not prove an identical variant",
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", default=str(ROOT / "artifacts" / "elite_policy_candidates" / "a2_order_public_value_search" / "submission"))
    parser.add_argument("--control", default=str(ROOT / "artifacts" / "recovery_probes" / "extracted" / "a2"))
    parser.add_argument("--attempts", type=int, default=100)
    parser.add_argument("--max-games", type=int, default=100)
    parser.add_argument("--max-decisions", type=int, default=500)
    parser.add_argument("--seed", type=int, default=2026081162)
    parser.add_argument("--output", default=str(ROOT / "artifacts" / "elite_policy_candidates" / "a2_order_public_value_search" / "branch_order_audit.json"))
    args = parser.parse_args()
    result = run(args)
    print(json.dumps({key: value for key, value in result.items() if key != "records"}, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

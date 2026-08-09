#!/usr/bin/env python3
"""Collect schema-5 public-actor/private-critic terminal-outcome rollouts."""

from __future__ import annotations

import argparse
import gzip
import json
import math
import random
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np

from cg.api import OptionType, SelectContext, to_observation_class
from cg.game import battle_finish, battle_select, battle_start, visualize_data
from ptcg_ai.direct import DirectPolicy
from ptcg_ai.external import ExternalSubmissionAgent
from ptcg_ai.features import EVENT_HISTORY_LENGTH, encode_observation, public_state_summary
from ptcg_ai.heuristic import GrimmsnarlHeuristic
from ptcg_ai.safety import sanitize_selection
from training.private_critic import encode_private_visualize
from training.q_boost import compare_actions


def _softmax(values: np.ndarray) -> np.ndarray:
    shifted = values - np.max(values)
    probability = np.exp(shifted)
    return probability / max(1e-12, float(probability.sum()))


def sample_complete_action(obs, logits: np.ndarray, counts: np.ndarray, rng: np.random.Generator, temperature: float) -> tuple[list[int], float]:
    select = obs.select
    if select.context == SelectContext.IS_FIRST:
        yes = next(index for index, option in enumerate(select.option) if option.type == OptionType.YES)
        return [yes], 0.0
    minimum, maximum = int(select.minCount), int(select.maxCount)
    logprob = 0.0
    if minimum == maximum:
        count = minimum
    else:
        probability = _softmax(np.asarray(counts[minimum:maximum + 1], np.float64) / temperature)
        offset = int(rng.choice(len(probability), p=probability))
        count = minimum + offset
        logprob += math.log(max(1e-12, float(probability[offset])))
    available = list(range(len(logits)))
    action: list[int] = []
    for _ in range(count):
        probability = _softmax(np.asarray([logits[index] for index in available], np.float64) / temperature)
        local = int(rng.choice(len(probability), p=probability))
        logprob += math.log(max(1e-12, float(probability[local])))
        action.append(available.pop(local))
    return sanitize_selection(select, action, count), logprob


def _prepare_history(policy: DirectPolicy, obs) -> None:
    turn = int(obs.current.turn or 0)
    if turn != policy.history_turn:
        policy.history_turn = turn
        policy.history = []
        policy.pending_summary = None
        policy.pending_index = None
    else:
        policy._resolve_pending(obs)


def _remember(policy: DirectPolicy, obs, features, action) -> None:
    policy._remember(obs, features, action)


def collect_game(actor_path: Path, hero_deck: list[int], opponent_path: Path, seed: int, temperature: float, q_compare_rate: float) -> tuple[list[dict], dict]:
    opponent_deck = [int(line) for line in (opponent_path / "deck.csv").read_text().splitlines() if line.strip()]
    seat = seed % 2
    decks = [hero_deck, opponent_deck] if seat == 0 else [opponent_deck, hero_deck]
    fallback = GrimmsnarlHeuristic()
    actor = DirectPolicy(actor_path, fallback)
    opponent = ExternalSubmissionAgent(opponent_path, {})
    rng = np.random.default_rng(seed)
    records: list[dict] = []
    raw, started = battle_start(decks[0], decks[1])
    if started.errorType:
        opponent.close()
        raise RuntimeError(f"engine rejected deck: {started.errorType}")
    first_player = None
    try:
        decisions = 0
        while True:
            obs = to_observation_class(raw)
            if first_player is None and obs.current is not None and int(obs.current.firstPlayer) in (0, 1):
                first_player = int(obs.current.firstPlayer)
            if obs.current is not None and int(obs.current.result) >= 0:
                result = int(obs.current.result)
                reward = 0.0 if result == 2 else (1.0 if result == seat else -1.0)
                for row in records:
                    row["terminal_reward"] = reward
                    row["actual_order"] = "first" if first_player == seat else "second"
                return records, {
                    "reward": reward,
                    "seat": seat,
                    "actual_order": "first" if first_player == seat else "second",
                    "decisions": decisions,
                }
            actor_turn = int(obs.current.yourIndex) == seat
            if actor_turn:
                _prepare_history(actor, obs)
                features = encode_observation(obs, 5, action_history=actor.history)
                logits, counts = actor.model.predict(features)
                action, old_logprob = sample_complete_action(obs, logits, counts, rng, temperature)
                full_payload = json.loads(visualize_data())
                private = encode_private_visualize(full_payload)
                record = {
                    "features": features.to_json(),
                    "critic_features": private,
                    "action": action,
                    "old_logprob": old_logprob,
                    "terminal_reward": 0.0,
                    "baseline_action": actor.fallback.choose(obs),
                    "supported_context": True,
                    "seat": seat,
                    "actual_order": "first" if first_player == seat else "second",
                    "step": decisions,
                }
                if len(logits) >= 2 and rng.random() < q_compare_rate:
                    ranked = np.argsort(-logits, kind="stable").astype(int).tolist()
                    alternative = list(action)
                    replacement = next((index for index in ranked if index not in alternative), None)
                    if alternative and replacement is not None:
                        alternative[0] = replacement
                        alternative = sanitize_selection(obs.select, alternative, len(action))
                        if alternative != action:
                            continuation = GrimmsnarlHeuristic()
                            scores = compare_actions(obs, full_payload[-1], [action, alternative], continuation.choose)
                            probabilities = _softmax(np.asarray([sum(logits[index] for index in action), sum(logits[index] for index in alternative)], np.float64))
                            record["action_q"] = float(scores[0])
                            record["expected_sarsa_q"] = float(probabilities @ np.asarray(scores))
                            record["q_alternative"] = alternative
                            record["q_alternative_outcome"] = float(scores[1])
                records.append(record)
                _remember(actor, obs, features, action)
            else:
                action = opponent(raw)
            raw = battle_select(action)
            decisions += 1
            if decisions >= 2_000:
                raise RuntimeError("outcome rollout exceeded decision cap")
    finally:
        battle_finish()
        opponent.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actor", type=Path, required=True)
    parser.add_argument("--deck", type=Path, required=True)
    parser.add_argument("--opponent", action="append", type=Path, required=True)
    parser.add_argument("--games", type=int, default=20_000)
    parser.add_argument("--temperature", type=float, default=0.35)
    parser.add_argument("--q-compare-rate", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=2026080901)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    hero_deck = [int(line) for line in args.deck.read_text().splitlines() if line.strip()]
    if len(hero_deck) != 60:
        raise ValueError("hero deck must contain 60 cards")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    games = wins = rows = errors = 0
    with gzip.open(args.output, "wt", encoding="utf-8") as handle:
        for index in range(args.games):
            opponent = args.opponent[index % len(args.opponent)].resolve()
            try:
                records, result = collect_game(args.actor, hero_deck, opponent, args.seed + index, args.temperature, args.q_compare_rate)
            except Exception as exc:
                errors += 1
                raise RuntimeError(f"rollout {index} failed closed: {type(exc).__name__}: {exc}") from exc
            for record in records:
                record["episode_id"] = f"rl-{args.seed + index}"
                record["opponent_lineage"] = opponent.name
                handle.write(json.dumps(record, separators=(",", ":")) + "\n")
            games += 1; wins += int(result["reward"] > 0); rows += len(records)
            if games % 100 == 0:
                print(json.dumps({"games": games, "rows": rows, "win_rate": wins / games}), flush=True)
    manifest = {
        "status": "complete" if errors == 0 else "failed",
        "games": games,
        "rows": rows,
        "wins": wins,
        "errors": errors,
        "terminal_reward_only": True,
        "critic_private_actor_public": True,
        "behavior_temperature": args.temperature,
        "q_compare_rate": args.q_compare_rate,
        "seed": args.seed,
    }
    args.output.with_suffix(args.output.suffix + ".json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

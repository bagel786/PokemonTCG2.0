#!/usr/bin/env python3
"""Collect outcome-labeled self-play trajectories with the official engine."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import multiprocessing as mp
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np

from cg.api import to_observation_class
from cg.game import battle_finish, battle_select, battle_start
from ptcg_ai.agent import CompetitionAgent
from ptcg_ai.external import ExternalSubmissionAgent
from ptcg_ai.features import encode_observation
from ptcg_ai.model import NumpyPolicyModel
from ptcg_ai.safety import sanitize_selection
from training.azure_guard import enforce_azure_workload
from training.search_teacher import SearchConfig, SearchTeacherAgent


def exact_weighted_schedule(entries: list[dict], games: int, seed: int) -> list[dict]:
    """Allocate an exact largest-remainder opponent schedule, then shuffle it."""
    if games < 0 or not entries:
        raise ValueError("games must be non-negative and entries must be non-empty")
    weights = [float(entry.get("weight", 1.0)) for entry in entries]
    if any(weight < 0 for weight in weights) or sum(weights) <= 0:
        raise ValueError("opponent weights must be non-negative with a positive sum")
    total = sum(weights)
    expected = [games * weight / total for weight in weights]
    quotas = [int(math.floor(value)) for value in expected]
    rng = random.Random(seed)
    tie_breakers = [rng.random() for _ in entries]
    remainder_order = sorted(
        range(len(entries)),
        key=lambda index: (expected[index] - quotas[index], tie_breakers[index]),
        reverse=True,
    )
    for index in remainder_order[: games - sum(quotas)]:
        quotas[index] += 1
    scheduled = [entry for index, entry in enumerate(entries) for _ in range(quotas[index])]
    rng.shuffle(scheduled)
    return scheduled


def exact_binary_schedule(games: int, positive_ratio: float, seed: int) -> list[int]:
    """Return a shuffled 0/1 schedule with an exact rounded positive quota."""
    if games < 0 or not 0.0 <= positive_ratio <= 1.0:
        raise ValueError("games must be non-negative and ratio must be within [0, 1]")
    positives = int(round(games * positive_ratio))
    values = [1] * positives + [0] * (games - positives)
    random.Random(seed).shuffle(values)
    return values


def source_identifier(model: str, submission: str, name: str) -> str:
    """Stable audit identifier without embedding machine-specific absolute paths."""
    if model and Path(model).exists():
        return hashlib.sha256(Path(model).read_bytes()).hexdigest()[:16]
    if submission:
        return hashlib.sha256(str(submission).encode("utf-8")).hexdigest()[:16]
    return f"unmodeled:{name}"


def resolve_submission(value: str) -> str:
    if not value:
        return ""
    path = Path(value)
    return str((ROOT / path).resolve()) if not path.is_absolute() else str(path)


def softmax(values, temperature=1.0):
    values = np.asarray(values, dtype=np.float64) / max(1e-3, temperature)
    values -= values.max()
    probabilities = np.exp(values)
    return probabilities / probabilities.sum()


def model_action(model, obs, rng, temperature):
    features = encode_observation(obs, model.feature_version)
    logits, count_logits, value = model.predict(features)
    select = obs.select
    minimum = int(select.minCount)
    maximum = int(select.maxCount)
    trainable = minimum != maximum or (len(logits) > 1 and maximum > 0)
    count_logprob = 0.0
    if minimum == maximum:
        desired = minimum
    else:
        valid_counts = np.arange(minimum, maximum + 1)
        probabilities = softmax(np.asarray(count_logits)[valid_counts], temperature)
        desired = int(rng.choice(valid_counts, p=probabilities))
        count_logprob = float(math.log(max(1e-12, probabilities[desired - minimum])))
    available = list(range(len(logits)))
    action = []
    selection_logprob = 0.0
    for _ in range(min(desired, len(available))):
        probabilities = softmax(np.asarray(logits)[available], temperature)
        local_index = int(rng.choice(len(available), p=probabilities))
        selection_logprob += float(math.log(max(1e-12, probabilities[local_index])))
        action.append(available.pop(local_index))
    action = sanitize_selection(select, action + available, desired)
    return action, features.to_json(), count_logprob + selection_logprob, count_logprob, float(value), trainable


from ptcg_ai.blunder_detector import is_blunder


def assign_terminal_gae(trajectory, outcome: float, gae_lambda: float = 0.95, turn1_bench_reward: float = 0.0):
    """Attach terminal-only GAE with Invariant 1.7 intra-turn gamma=1.0 credit assignment."""
    gae = 0.0
    next_value = 0.0
    next_turn = None
    bench_bonus = 0.0
    if turn1_bench_reward > 0.0:
        for row in trajectory:
            gf = row.get("features", {}).get("global", [])
            if len(gf) > 14:
                turn = gf[0] * 100.0
                bench_count = gf[14] * 5.0
                if turn <= 2.0 and bench_count >= 2.0:
                    bench_bonus = turn1_bench_reward
                    break

    total_outcome = outcome + bench_bonus
    for reverse_index, row in enumerate(reversed(trajectory)):
        current_turn = row.get("turn", 0)
        # Invariant 1.7: Intra-turn decisions without turn advancement use gamma = 1.0
        if next_turn is None or current_turn == next_turn:
            gamma = 1.0
        else:
            gamma = 0.99
        value = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, row["old_value"]))))
        reward = total_outcome if reverse_index == 0 else 0.0
        delta = reward + gamma * next_value - value
        gae = delta + gamma * gae_lambda * gae
        row["advantage"] = gae
        row["return"] = total_outcome
        # Invariant 1.6: Keep value target strictly targeted to unpolluted game outcome
        row["reward"] = outcome
        next_value = value
        next_turn = current_turn
    return trajectory


def run_game(task):
    (
        game_index,
        seed,
        hero_seat,
        hero_deck_path,
        opponent_name,
        opponent_archetype,
        opponent_model_id,
        opponent_strength_tier,
        opponent_behavior_probability,
        opponent_target_probability,
        opponent_deck_path,
        opponent_model,
        opponent_submission,
        opponent_env,
        opponent_search_config,
        model_path,
        temperature,
        gae_lambda,
        turn1_bench_reward,
        policy_version,
    ) = task
    rng = np.random.default_rng(seed + game_index)
    hero_deck = [int(line) for line in Path(hero_deck_path).read_text().splitlines() if line.strip()]
    opponent_deck = [int(line) for line in Path(opponent_deck_path).read_text().splitlines() if line.strip()]
    decks = [hero_deck, opponent_deck] if hero_seat == 0 else [opponent_deck, hero_deck]
    model = NumpyPolicyModel(model_path)
    if opponent_search_config:
        if not opponent_model:
            raise ValueError(f"search teacher {opponent_name} requires a neural model")
        opponent = SearchTeacherAgent(
            opponent_deck_path,
            opponent_model,
            hero_deck_path,
            model_path,
            SearchConfig(**opponent_search_config),
        )
    elif opponent_submission:
        opponent = ExternalSubmissionAgent(opponent_submission, opponent_env)
    else:
        opponent = CompetitionAgent(opponent_deck_path, opponent_model or None)
    raw, start = battle_start(decks[0], decks[1])
    if start.errorType != 0:
        raise RuntimeError(f"engine rejected deck: {start.errorType}")
    trajectory = []
    try:
        while True:
            obs = to_observation_class(raw)
            if obs.current is not None and obs.current.result != -1:
                winner = obs.current.result
                break
            if obs.current.yourIndex == hero_seat:
                action, features, old_logprob, count_logprob, old_value, trainable = model_action(model, obs, rng, temperature)
                turn = int(getattr(obs.current, "turn", 0) or 0)
                blunder = False
                if obs.select and obs.select.option:
                    blunder = any(is_blunder(obs, obs.select.option[a]) for a in action if 0 <= a < len(obs.select.option))
                trajectory.append({
                    "episode_id": f"selfplay-{seed}-{game_index}",
                    "trajectory_id": f"selfplay-{seed}-{game_index}",
                    "decision_index": len(trajectory),
                    "seat": hero_seat,
                    "step": len(trajectory),
                    "turn": turn,
                    "deck": hero_deck,
                    "action": action,
                    "features": features,
                    "old_logprob": old_logprob,
                    "old_count_logprob": count_logprob,
                    "old_value": old_value,
                    "trainable": trainable,
                    "is_blunder": blunder,
                    "behavior_temperature": temperature,
                    "policy_version": policy_version,
                    "model_schema_version": int(model.feature_version),
                    "selection_order": action,
                    "opponent": opponent_name,
                    "opponent_archetype": opponent_archetype,
                    "opponent_model_id": opponent_model_id,
                    "opponent_strength_tier": opponent_strength_tier,
                    "behavior_sampling_probability": opponent_behavior_probability,
                    "target_sampling_probability": opponent_target_probability,
                    "matchup_group": f"{opponent_archetype}|seat{hero_seat}",
                })
            else:
                action = opponent(raw)
            raw = battle_select(action)
    finally:
        battle_finish()
        if isinstance(opponent, ExternalSubmissionAgent):
            opponent.close()
    reward = 1.0 if winner == hero_seat else 0.0
    opponent_errors = int(getattr(opponent, "errors", getattr(opponent, "search_errors", 0)))
    return assign_terminal_gae(trajectory, reward, gae_lambda, turn1_bench_reward), reward, opponent_errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--hero-deck", required=True)
    parser.add_argument("--opponent-deck", action="append", default=[])
    parser.add_argument("--league", help="weighted opponent league JSON")
    parser.add_argument("--games", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=max(1, (mp.cpu_count() or 2) - 1))
    parser.add_argument("--temperature", type=float, default=0.65)
    parser.add_argument("--gae-lambda", type=float, default=0.95)
    parser.add_argument("--seat-1-ratio", type=float, default=0.50, help="proportion of games hero plays as Seat 1 (Going 2nd)")
    parser.add_argument("--turn1-bench-reward", type=float, default=0.0, help="auxiliary reward bonus for establishing >=2 bench Pokemon on Turn 1")
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument("--output", required=True)
    parser.add_argument("--allow-local-smoke", action="store_true")
    args = parser.parse_args()
    enforce_azure_workload(allow_local_smoke=args.allow_local_smoke, workload_size=args.games)
    opponents = []
    if args.league:
        league = json.loads(Path(args.league).read_text())
        for entry in league["opponents"]:
            deck_path = Path(entry["deck"])
            model_value = entry.get("model", "")
            model_path = Path(model_value) if model_value else None
            opponents.append({
                "name": entry["name"],
                "archetype": entry.get("archetype", entry["name"]),
                "strength_tier": entry.get("strength_tier", "unspecified"),
                "deck": str((ROOT / deck_path).resolve()) if not deck_path.is_absolute() else str(deck_path),
                "model": str((ROOT / model_path).resolve()) if model_path is not None and not model_path.is_absolute() else (str(model_path) if model_path else ""),
                "submission": resolve_submission(entry.get("submission", "")),
                "env": {str(key): str(value) for key, value in entry.get("submission_env", {}).items()},
                "search_config": entry.get("search_teacher", {}),
                "weight": float(entry.get("train_weight", 1.0)),
            })
    opponents.extend(
        {
            "name": Path(path).stem,
            "archetype": Path(path).stem,
            "strength_tier": "unmodeled",
            "deck": str(Path(path).resolve()),
            "model": "",
            "submission": "",
            "env": {},
            "search_config": {},
            "weight": 1.0,
        }
        for path in args.opponent_deck
    )
    if not opponents:
        parser.error("provide --league or at least one --opponent-deck")
    total_weight = sum(entry["weight"] for entry in opponents)
    for entry in opponents:
        entry["behavior_probability"] = entry["weight"] / total_weight
        entry["target_probability"] = float(
            next(
                (
                    league_entry.get("target_probability")
                    for league_entry in (league.get("opponents", []) if args.league else [])
                    if league_entry.get("name") == entry["name"]
                    and league_entry.get("target_probability") is not None
                ),
                entry["behavior_probability"],
            )
        )
        entry["model_id"] = source_identifier(entry["model"], entry["submission"], entry["name"])
    scheduled = exact_weighted_schedule(opponents, args.games, args.seed)
    hero_seats = exact_binary_schedule(args.games, args.seat_1_ratio, args.seed + 10007)
    policy_version = hashlib.sha256(Path(args.model).read_bytes()).hexdigest()[:16]
    tasks = [
        (
            index,
            args.seed,
            hero_seats[index],
            str(Path(args.hero_deck).resolve()),
            scheduled[index]["name"],
            scheduled[index]["archetype"],
            scheduled[index]["model_id"],
            scheduled[index]["strength_tier"],
            scheduled[index]["behavior_probability"],
            scheduled[index]["target_probability"],
            scheduled[index]["deck"],
            scheduled[index]["model"],
            scheduled[index]["submission"],
            scheduled[index]["env"],
            scheduled[index]["search_config"],
            str(Path(args.model).resolve()),
            args.temperature,
            args.gae_lambda,
            args.turn1_bench_reward,
            policy_version,
        )
        for index in range(args.games)
    ]
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    wins = decisions = opponent_errors = 0
    context = mp.get_context("spawn")
    temporary = output.with_name(output.name + ".tmp")
    with gzip.open(temporary, "wt", encoding="utf-8", compresslevel=6) as handle:
        with context.Pool(args.workers) as pool:
            # One game per work item avoids a long straggler tail when authentic
            # submissions produce much longer matches than fast mirror games.
            for index, (trajectory, reward, game_opponent_errors) in enumerate(
                pool.imap_unordered(run_game, tasks, chunksize=1), 1
            ):
                wins += int(reward > 0)
                decisions += len(trajectory)
                opponent_errors += game_opponent_errors
                for row in trajectory:
                    handle.write(json.dumps(row, separators=(",", ":")) + "\n")
                if index % 100 == 0 or index == args.games:
                    print({
                        "games": index,
                        "win_rate": wins / index,
                        "decisions": decisions,
                        "opponent_policy_errors": opponent_errors,
                        "policy_version": policy_version,
                    })
    os.replace(temporary, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

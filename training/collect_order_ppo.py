#!/usr/bin/env python3
"""Collect forced-actual-order schema-2 rollouts with the training Torch actor."""

from __future__ import annotations

import argparse
import gzip
import json
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np
import torch

from cg.api import OptionType, SelectContext, to_observation_class
from cg.game import battle_finish, battle_select, battle_start
from ptcg_ai.external import ExternalSubmissionAgent
from ptcg_ai.features import encode_observation
from ptcg_ai.safety import sanitize_selection
from training.azure_guard import enforce_azure_workload
from training.order_ppo import complete_action_logprob, sha256
from training.train_bc import PolicyNet, collate, load_npz_weights


def _forced_order_action(select, hero_seat: int, requested_order: str) -> list[int]:
    seat_zero_should_go_first = (requested_order == "first") == (hero_seat == 0)
    desired = OptionType.YES if seat_zero_should_go_first else OptionType.NO
    matches = [index for index, option in enumerate(select.option) if option.type == desired]
    if len(matches) != 1:
        raise RuntimeError(f"forced-order chooser could not find unique {desired}")
    return sanitize_selection(select, matches, 1)


def _sample_complete_action(
    model: PolicyNet,
    features: dict[str, Any],
    select,
    generator: torch.Generator,
    temperature: float,
) -> tuple[list[int], float, bool]:
    row = {"features": features, "action": [], "reward": 0.0, "sample_weight": 1.0}
    batch = collate([row])
    with torch.no_grad():
        logits, counts, _ = model(batch)
        minimum, maximum = int(select.minCount), int(select.maxCount)
        if minimum == maximum:
            count = minimum
        else:
            probability = torch.softmax(counts[0, minimum:maximum + 1] / temperature, dim=0)
            count = minimum + int(torch.multinomial(probability, 1, generator=generator).item())
        available = torch.ones(len(logits), dtype=torch.bool)
        sampled: list[int] = []
        for _ in range(count):
            probability = torch.softmax((logits / temperature).masked_fill(~available, -torch.inf), dim=0)
            selected = int(torch.multinomial(probability, 1, generator=generator).item())
            sampled.append(selected)
            available[selected] = False
        sanitized = sanitize_selection(select, sampled, count)
        postprocessed = sanitized != sampled
        logprob = complete_action_logprob(logits, counts, batch, 0, sampled, temperature)
    return sanitized, float(logprob), postprocessed


class TorchSchema2Chooser:
    def __init__(self, model_path: Path, seed: int, temperature: float) -> None:
        self.model_path = model_path
        self.policy_hash = sha256(model_path)
        self.model = PolicyNet(feature_version=2)
        load_npz_weights(self.model, model_path)
        self.model.eval()
        self.generator = torch.Generator(device="cpu")
        self.generator.manual_seed(seed)
        self.temperature = temperature

    def choose(self, obs) -> tuple[list[int], float, bool, dict[str, Any]]:
        features = encode_observation(obs, feature_version=2).to_json()
        action, logprob, postprocessed = _sample_complete_action(
            self.model, features, obs.select, self.generator, self.temperature
        )
        return action, logprob, postprocessed, features


def collect_game(
    chooser: TorchSchema2Chooser,
    hero_deck: list[int],
    opponent_path: Path,
    opponent_id: str,
    physical_seat: int,
    actual_order: str,
    episode_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    opponent_deck = [int(line) for line in (opponent_path / "deck.csv").read_text().splitlines() if line.strip()]
    if len(opponent_deck) != 60:
        raise ValueError(f"opponent {opponent_id} does not have a 60-card deck")
    decks = [hero_deck, opponent_deck] if physical_seat == 0 else [opponent_deck, hero_deck]
    opponent = ExternalSubmissionAgent(opponent_path, {})
    records: list[dict[str, Any]] = []
    raw, started = battle_start(decks[0], decks[1])
    if started.errorType:
        opponent.close()
        raise RuntimeError(f"engine rejected deck: {started.errorType}")
    latched_first_player: int | None = None
    decisions = 0
    try:
        while True:
            obs = to_observation_class(raw)
            if obs.current is not None and int(obs.current.firstPlayer) in (0, 1):
                observed = int(obs.current.firstPlayer)
                if latched_first_player is None:
                    latched_first_player = observed
                elif observed != latched_first_player:
                    raise RuntimeError("firstPlayer changed after actual-order latch")
            if obs.current is not None and int(obs.current.result) >= 0:
                if latched_first_player is None:
                    raise RuntimeError("game completed without a valid firstPlayer latch")
                observed_order = "first" if latched_first_player == physical_seat else "second"
                if observed_order != actual_order:
                    raise RuntimeError(f"forced-order mismatch: requested {actual_order}, observed {observed_order}")
                result = int(obs.current.result)
                reward = 0.0 if result == 2 else (1.0 if result == physical_seat else -1.0)
                for row in records:
                    row["terminal_reward"] = reward
                opponent_errors = int(getattr(opponent, "errors", 0) or 0)
                inner = getattr(opponent.module, "_AGENT", None)
                opponent_errors += int(getattr(inner, "errors", 0) or 0)
                if opponent_errors:
                    raise RuntimeError(f"opponent policy reported {opponent_errors} errors")
                return records, {"reward": reward, "decisions": decisions, "actual_order": observed_order}

            if obs.select.context == SelectContext.IS_FIRST:
                action = _forced_order_action(obs.select, physical_seat, actual_order)
            elif int(obs.current.yourIndex) == physical_seat:
                if latched_first_player is None:
                    raise RuntimeError("hero decision arrived before firstPlayer was latched")
                observed_order = "first" if latched_first_player == physical_seat else "second"
                if observed_order != actual_order:
                    raise RuntimeError("hero decision has wrong actual order")
                action, old_logprob, postprocessed, features = chooser.choose(obs)
                records.append({
                    "episode_id": episode_id,
                    "opponent_id": opponent_id,
                    "features": features,
                    "action": action,
                    "choice": action,
                    "chooser": "torch_schema2_policy",
                    "old_logprob": old_logprob,
                    "behavior_temperature": chooser.temperature,
                    "policy_hash": chooser.policy_hash,
                    "physical_seat": physical_seat,
                    "actual_order": actual_order,
                    "terminal_reward": 0.0,
                    "forced_order_decision": False,
                    "shield_modified": False,
                    "postprocessed": postprocessed,
                    "trainable": not postprocessed,
                    "step": decisions,
                })
            else:
                action = opponent(raw)
            raw = battle_select(action)
            decisions += 1
            if decisions >= 2_000:
                raise RuntimeError("forced-order rollout exceeded decision cap")
    finally:
        battle_finish()
        opponent.close()


def weighted_schedule(specs: list[dict[str, Any]], games: int, seed: int) -> list[dict[str, Any]]:
    weights = [float(spec["weight"]) for spec in specs]
    if any(weight <= 0 for weight in weights) or abs(sum(weights) - 1.0) > 1e-9:
        raise ValueError("opponent weights must be positive and sum to 1.0")
    raw = [games * weight for weight in weights]
    counts = [int(value) for value in raw]
    for index in sorted(range(len(specs)), key=lambda i: (-(raw[i] - counts[i]), i))[:games - sum(counts)]:
        counts[index] += 1
    schedule = [spec for spec, count in zip(specs, counts) for _ in range(count)]
    random.Random(seed).shuffle(schedule)
    return schedule


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actor", type=Path, required=True)
    parser.add_argument("--deck", type=Path, required=True)
    parser.add_argument("--opponent-spec", type=Path, required=True)
    parser.add_argument("--actual-order", choices=("first", "second"), required=True)
    parser.add_argument("--games", type=int, default=5_000)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--temperature", type=float, default=0.70)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-local-smoke", action="store_true")
    args = parser.parse_args()
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        raise ValueError("shard-index must be in [0, shard-count)")
    enforce_azure_workload(allow_local_smoke=args.allow_local_smoke, workload_size=args.games)
    if abs(args.temperature - 0.70) > 1e-12:
        raise ValueError("this program is locked to behavior temperature 0.70")
    hero_deck = [int(line) for line in args.deck.read_text().splitlines() if line.strip()]
    if len(hero_deck) != 60:
        raise ValueError("hero deck must contain exactly 60 cards")
    specs = json.loads(args.opponent_spec.read_text(encoding="utf-8"))["opponents"]
    full_schedule = weighted_schedule(specs, args.games, args.seed)
    schedule = [
        (global_index, spec) for global_index, spec in enumerate(full_schedule)
        if global_index % args.shard_count == args.shard_index
    ]
    chooser = TorchSchema2Chooser(args.actor, args.seed, args.temperature)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    games = wins = decisions = excluded = 0
    seat_games = {"0": 0, "1": 0}
    opponent_games: dict[str, int] = {}
    with gzip.open(args.output, "wt", encoding="utf-8") as handle:
        for global_index, spec in schedule:
            opponent_id = str(spec["id"])
            episode_id = f"order-ppo-{args.seed}-{global_index}"
            rows, result = collect_game(
                chooser=chooser,
                hero_deck=hero_deck,
                opponent_path=Path(spec["path"]).resolve(),
                opponent_id=opponent_id,
                physical_seat=global_index % 2,
                actual_order=args.actual_order,
                episode_id=episode_id,
            )
            for row in rows:
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")
                excluded += int(not row["trainable"])
            games += 1
            seat_games[str(global_index % 2)] += 1
            wins += int(result["reward"] > 0)
            decisions += len(rows)
            opponent_games[opponent_id] = opponent_games.get(opponent_id, 0) + 1
            if games % 100 == 0:
                print(json.dumps({"games": games, "win_rate": wins / games, "decisions": decisions}), flush=True)
    manifest = {
        "status": "complete",
        "games": games,
        "wins": wins,
        "decisions": decisions,
        "excluded_decisions": excluded,
        "actual_order": args.actual_order,
        "physical_seat_games": seat_games,
        "opponent_games": opponent_games,
        "behavior_temperature": args.temperature,
        "policy_hash": chooser.policy_hash,
        "terminal_reward_only": True,
        "seed": args.seed,
        "generation_games": args.games,
        "shard_count": args.shard_count,
        "shard_index": args.shard_index,
    }
    args.output.with_suffix(args.output.suffix + ".json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

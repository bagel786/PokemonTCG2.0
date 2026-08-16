#!/usr/bin/env python3
"""P1 causal PLAY label generation on the seeded engine with true state forks.

For eligible hero MAIN prompts (>=2 distinct playable PLAY cards) harvested
from live seeded games, this script:

1. opens engine search forks via SearchBegin on the exact live snapshot,
2. determinizes hidden information via determinize_known_matchup,
3. forces ONE PLAY card per branch, then returns control to the exact R0
   package policy (hero) and the opponent package policy,
4. rolls each fork to a terminal outcome,
5. repeats across determinizations.

RNG honesty: forks clone the live battle snapshot; hidden card orders are
determinized by a seeded Python RNG; downstream engine randomness continues
from the fork snapshot and may diverge between branches that consume random
numbers differently.  Two identical forks are re-run per session to prove
branch determinism.
"""

from __future__ import annotations

import argparse
import ctypes
import dataclasses
import json
import os
import random
import sys
import time
from enum import Enum
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

from cg.api import OptionType, SelectContext, SelectType, to_observation_class  # noqa: E402
from training.search_teacher import DeterminizationError, determinize_known_matchup  # noqa: E402

SEEDED_ENGINE = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/deterministic_engine/bin/libcg_seeded.dylib")
R0_PACKAGE = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/grim_damage_conversion/winner/extracted")
B0_PACKAGE = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/grim_variance_floor/candidates/B0")
MASTER_V1 = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/grim_damage_conversion/opponents/master_v1")
REPLAY_REFRESH = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/grim_damage_conversion/opponents/replay_refresh")

MAX_STEPS = 500
DETS_PER_STATE = 3
ALTERNATIVES = 2
HARVEST_CAP = 2


def _primitive(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return int(value.value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return str(value)


def obs_to_dict(obs) -> dict:
    """JSON-safe observation dict for training-time feature replay."""

    def convert(value):
        if dataclasses.is_dataclass(value):
            return {field.name: convert(getattr(value, field.name)) for field in dataclasses.fields(value)}
        if isinstance(value, list):
            return [convert(item) for item in value]
        if isinstance(value, tuple):
            return [convert(item) for item in value]
        if isinstance(value, dict):
            return {key: convert(item) for key, item in value.items()}
        return _primitive(value)

    result = convert(obs)
    result.pop("search_begin_input", None)
    return result


class StartData(ctypes.Structure):
    _fields_ = [
        ("battlePtr", ctypes.c_void_p),
        ("errorPlayer", ctypes.c_int),
        ("errorType", ctypes.c_int),
    ]


class SerialData(ctypes.Structure):
    _fields_ = [
        ("json", ctypes.c_char_p),
        ("data", ctypes.POINTER(ctypes.c_ubyte)),
        ("count", ctypes.c_int),
        ("selectPlayer", ctypes.c_int),
    ]


class SeededSearchEngine:
    """ctypes adapter for the seeded engine including fork/search exports."""

    def __init__(self, dll_path: Path):
        self.lib = ctypes.CDLL(str(dll_path))
        self.lib.GameInitialize.argtypes = []
        self.lib.GameInitialize.restype = None
        self.lib.GameInitialize()
        self.lib.BattleStartSeeded.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_uint32]
        self.lib.BattleStartSeeded.restype = StartData
        self.lib.BattleFinish.argtypes = [ctypes.c_void_p]
        self.lib.BattleFinish.restype = None
        self.lib.GetBattleData.argtypes = [ctypes.c_void_p]
        self.lib.GetBattleData.restype = SerialData
        self.lib.Select.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.c_int]
        self.lib.Select.restype = ctypes.c_int
        self.lib.AgentStart.argtypes = []
        self.lib.AgentStart.restype = ctypes.c_void_p
        self.agent_ptr = self.lib.AgentStart()
        self.lib.SearchBegin.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int,
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
            ctypes.c_int,
        ]
        self.lib.SearchBegin.restype = ctypes.c_char_p
        self.lib.SearchStep.argtypes = [ctypes.c_void_p, ctypes.c_int64, ctypes.POINTER(ctypes.c_int), ctypes.c_int]
        self.lib.SearchStep.restype = ctypes.c_char_p
        self.lib.SearchEnd.argtypes = [ctypes.c_void_p]
        self.lib.SearchRelease.argtypes = [ctypes.c_void_p, ctypes.c_int64]
        self.lib.SearchSetSeed.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self.lib.SearchSetSeed.restype = None

    def search_set_seed(self, seed: int) -> None:
        self.lib.SearchSetSeed(self.agent_ptr, ctypes.c_uint32(seed).value)

    def _observation(self, battle_ptr: int) -> dict:
        serial = self.lib.GetBattleData(battle_ptr)
        observation = json.loads(serial.json.decode("utf-8"))
        if serial.count > 0:
            observation["search_begin_input"] = ctypes.string_at(serial.data, serial.count).decode("ascii")
        return observation

    def start(self, deck0: list[int], deck1: list[int], seed: int) -> tuple[int, dict]:
        cards = (ctypes.c_int * 120)(*(deck0 + deck1))
        started = self.lib.BattleStartSeeded(cards, ctypes.c_uint32(seed).value)
        if not started.battlePtr:
            raise RuntimeError(f"seeded engine rejected battle start for player {started.errorPlayer}: {started.errorType}")
        return int(started.battlePtr), self._observation(started.battlePtr)

    def select(self, battle_ptr: int, selection: list[int]) -> dict:
        values = (ctypes.c_int * len(selection))(*selection)
        error = self.lib.Select(battle_ptr, values, len(selection))
        if error:
            raise RuntimeError(f"seeded engine rejected selection with error {error}")
        return self._observation(battle_ptr)

    def finish(self, battle_ptr: int) -> None:
        self.lib.BattleFinish(battle_ptr)

    def search_begin(self, obs_dict: dict, **kwargs) -> dict:
        snapshot = obs_dict.get("search_begin_input") or ""
        payload = snapshot.encode("utf-8")

        def arr(name):
            values = [int(card) for card in kwargs.get(name, [])]
            return (ctypes.c_int * max(1, len(values)))(*values) if values else ctypes.POINTER(ctypes.c_int)()

        raw = self.lib.SearchBegin(
            self.agent_ptr,
            ctypes.c_char_p(payload),
            len(payload),
            arr("your_deck"), arr("your_prize"),
            arr("opponent_deck"), arr("opponent_prize"),
            arr("opponent_hand"), arr("opponent_active"),
            int(bool(kwargs.get("manual_coin", False))),
        )
        result = json.loads(raw.decode("utf-8"))
        if int(result.get("error", 0)) != 0:
            raise RuntimeError(f"SearchBegin error {result.get('error')}")
        return result["state"]

    def search_step(self, search_id: int, selection: list[int]) -> dict:
        values = (ctypes.c_int * len(selection))(*selection)
        raw = self.lib.SearchStep(self.agent_ptr, ctypes.c_int64(search_id), values, len(selection))
        result = json.loads(raw.decode("utf-8"))
        if int(result.get("error", 0)) != 0:
            raise RuntimeError(f"SearchStep error {result.get('error')} for selection {selection}")
        return result["state"]

    def search_release(self, search_id: int) -> None:
        self.lib.SearchRelease(self.agent_ptr, ctypes.c_int64(search_id))

    def search_end(self) -> None:
        self.lib.SearchEnd(self.agent_ptr)


_POLICY_CACHE: dict[tuple[str, str], object] = {}


def load_package_policy(package_dir: Path, npz_name: str, cache_tag: str = ""):
    """Isolated-load a packaged policy under unique module names, kept alive."""
    import importlib.util
    from uuid import uuid4

    cache_key = (str(package_dir), npz_name, cache_tag)
    if cache_key in _POLICY_CACHE:
        return _POLICY_CACHE[cache_key]

    token = uuid4().hex
    package_name = f"_p1pkg_{token}"
    package_spec = importlib.util.spec_from_file_location(
        package_name, package_dir / "ptcg_ai" / "__init__.py", submodule_search_locations=[str(package_dir / "ptcg_ai")]
    )
    package = importlib.util.module_from_spec(package_spec)
    sys.modules[package_name] = package
    package_spec.loader.exec_module(package)
    model_module = importlib.import_module(package_name + ".model")
    policy = model_module.NeuralPolicy(str(package_dir / npz_name), None)
    _POLICY_CACHE[cache_key] = policy
    return policy


def _play_cards(obs) -> dict[int, int]:
    me = obs.current.players[obs.current.yourIndex]
    hand = me.hand or []
    cards: dict[int, int] = {}
    for index, option in enumerate(obs.select.option):
        if option.type == OptionType.PLAY:
            position = getattr(option, "index", None)
            cards[index] = int(hand[position].id) if position is not None and 0 <= position < len(hand) else -1
    return cards


def play_logits(policy, obs) -> dict[int, float]:
    """PLAY option index -> R0 logit, using the package's own encoder."""
    from importlib import import_module

    package_name = policy.__class__.__module__.split(".")[0]
    features_mod = import_module(f"{package_name}.features")
    features = features_mod.encode_observation(obs, policy.model.feature_version)
    logits, _, _ = policy.model.predict(features)
    return {index: float(logits[index]) for index in range(len(obs.select.option))}


def rollout_to_terminal(engine, state: dict, hero_policy, opponent_policy, hero_seat: int) -> tuple[int, int]:
    """Roll a fork to terminal with package policies. Returns (hero_win, steps).

    Interior search states are released as soon as the next state exists so a
    long rollout cannot exhaust the search memory pool (which the engine may
    recycle in unspecified ways).  The caller releases the terminal state.
    """
    steps = 0
    current_state = state
    root_id = int(state["searchId"])
    while steps < MAX_STEPS:
        obs_dict = current_state["observation"]
        current = obs_dict.get("current") or {}
        if current.get("result", -1) is not None and int(current["result"]) >= 0:
            return int(current["result"]) == hero_seat, steps
        select = obs_dict.get("select")
        if not select:
            return -1, steps
        acting = int(current["yourIndex"])
        obs = to_observation_class(obs_dict)
        policy = hero_policy if acting == hero_seat else opponent_policy
        action = policy.choose(obs)
        next_state = engine.search_step(int(current_state["searchId"]), [int(index) for index in action])
        if int(current_state["searchId"]) != root_id:
            engine.search_release(int(current_state["searchId"]))
        current_state = next_state
        steps += 1
    return -1, steps


_ENGINE: SeededSearchEngine | None = None


def get_engine() -> SeededSearchEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = SeededSearchEngine(SEEDED_ENGINE)
    return _ENGINE


def run_label_game(task: dict) -> dict:
    import numpy as np

    seed = int(task["seed"])
    order = str(task["order"])
    opponent_name = str(task["opponent"])
    random.seed(seed)
    np.random.seed(seed & 0xFFFFFFFF)

    opponent_dir = {"d842": B0_PACKAGE, "master_v1": MASTER_V1, "replay_refresh": REPLAY_REFRESH}[opponent_name]
    hero_deck = [int(line) for line in (R0_PACKAGE / "deck.csv").read_text().splitlines() if line.strip()]
    opponent_deck = [int(line) for line in (opponent_dir / "deck.csv").read_text().splitlines() if line.strip()]
    hero_seat = seed % 2
    decks = [hero_deck, opponent_deck] if hero_seat == 0 else [opponent_deck, hero_deck]

    engine = get_engine()
    os.environ["PTCG_GRIM_DAMAGE_SOLVER"] = "v0"
    hero_policy = load_package_policy(R0_PACKAGE, "policy_first.npz")
    fork_policy = load_package_policy(R0_PACKAGE, "policy_first.npz", cache_tag="fork")
    opponent_policy = load_package_policy(opponent_dir, "policy_weights.npz")
    if hasattr(hero_policy, "reset"):
        hero_policy.reset()
    if hasattr(fork_policy, "reset"):
        fork_policy.reset()

    states = []
    errors = []
    decisions = 0
    battle_ptr = 0
    try:
        battle_ptr, raw = engine.start(decks[0], decks[1], seed)
        while True:
            obs_dict = raw
            current = obs_dict.get("current") or {}
            if current.get("result", -1) is not None and int(current["result"]) >= 0:
                break
            select = obs_dict.get("select")
            if not select:
                raise RuntimeError("live game reached nonterminal state without selection")
            context = int(select.get("context", -1))
            select_type = int(select.get("type", -1))
            obs = to_observation_class(obs_dict)
            acting = int(current["yourIndex"])
            if context == int(SelectContext.IS_FIRST):
                options = [i for i, option in enumerate(obs.select.option) if option.type in (OptionType.YES, OptionType.NO)]
                want_yes = (order == "first") == (hero_seat == 0)
                chosen = [i for i in options if (obs.select.option[i].type == OptionType.YES) == want_yes]
                if len(chosen) != 1:
                    raise RuntimeError("invalid IS_FIRST choice set")
                action = chosen
                raw = engine.select(battle_ptr, action)
                decisions += 1
                continue
            if acting != hero_seat:
                action = [int(index) for index in opponent_policy.choose(obs)]
                raw = engine.select(battle_ptr, action)
                decisions += 1
                continue
            action = [int(index) for index in hero_policy.choose(obs)]
            if (
                select_type == int(SelectType.MAIN)
                and context == int(SelectContext.MAIN)
                and len([r for r in states if r["game_seed"] == seed]) < HARVEST_CAP
            ):
                play = _play_cards(obs)
                active = [index for index in play if play[index] >= 0]
                distinct = sorted({play[index] for index in active})
                if len(distinct) >= 2:
                    chosen_card = None
                    for index in action:
                        if index in play and play[index] >= 0:
                            chosen_card = play[index]
                            break
                    logits = play_logits(hero_policy, obs)
                    card_logits = {
                        str(card): round(max((logits[i] for i in active if play[i] == card), default=-9e9), 4)
                        for card in distinct
                    }
                    alternatives = [card for card in sorted(distinct, key=lambda c: -max((logits[i] for i in active if play[i] == c), default=-1e9)) if card != chosen_card][:ALTERNATIVES]
                    cards_to_test = [card for card in ([chosen_card] if chosen_card is not None else []) + alternatives]
                    state_record = {
                        "game_seed": seed,
                        "order": order,
                        "opponent": opponent_name,
                        "hero_seat": hero_seat,
                        "turn": int(current["turn"]),
                        "your_index": int(current["yourIndex"]),
                        "first_player": int(current["firstPlayer"]),
                        "hand_size": len(current["players"][int(current["yourIndex"])]["hand"] or []),
                        "opponent_hand_size": int(current["players"][1 - int(current["yourIndex"])]["handCount"]),
                        "my_prizes": len(current["players"][int(current["yourIndex"])]["prize"] or []),
                        "opponent_prizes": len(current["players"][1 - int(current["yourIndex"])]["prize"] or []),
                        "playable": distinct,
                        "chosen_card": chosen_card,
                        "alternatives": alternatives,
                        "card_logits": card_logits,
                        "obs": obs_to_dict(obs),
                        "per_card": {str(card): {"wins": 0, "runs": 0} for card in cards_to_test},
                    }
                    try:
                        determinism_probe = None
                        for det_index in range(DETS_PER_STATE):
                            det_seed = seed * 31 + det_index
                            kwargs = dict(determinize_known_matchup(obs, list(hero_deck), list(opponent_deck), random.Random(det_seed)))
                            for card in cards_to_test:
                                option_index = next(i for i in active if play[i] == card)
                                if hasattr(fork_policy, "reset"):
                                    fork_policy.reset()
                                engine.search_set_seed(det_seed)
                                root = engine.search_begin(obs_dict, **kwargs)
                                root_id = int(root["searchId"])
                                state = engine.search_step(root_id, [option_index])
                                hero_win, steps = rollout_to_terminal(engine, state, fork_policy, opponent_policy, hero_seat)
                                engine.search_release(root_id)
                                engine.search_end()
                                if det_index == 0 and determinism_probe is None:
                                    determinism_probe = (card, hero_win, steps)
                                if hero_win >= 0:
                                    state_record["per_card"][str(card)]["runs"] += 1
                                    state_record["per_card"][str(card)]["wins"] += int(hero_win)
                            if det_index == 0 and determinism_probe:
                                card, win, steps = determinism_probe
                                option_index = next(i for i in active if play[i] == card)
                                if hasattr(fork_policy, "reset"):
                                    fork_policy.reset()
                                engine.search_set_seed(det_seed)
                                probe_root = engine.search_begin(obs_dict, **kwargs)
                                probe_state = engine.search_step(int(probe_root["searchId"]), [option_index])
                                probe_win, probe_steps = rollout_to_terminal(engine, probe_state, fork_policy, opponent_policy, hero_seat)
                                if probe_win != win:
                                    raise RuntimeError(f"fork determinism probe failed: {win} vs {probe_win}")
                                engine.search_release(int(probe_root["searchId"]))
                                engine.search_end()
                        states.append(state_record)
                    except (DeterminizationError, RuntimeError, ValueError, KeyError, IndexError) as exc:
                        errors.append({"game_seed": seed, "turn": int(current["turn"]), "error": repr(exc)})
                    try:
                        engine.search_end()
                    except Exception:
                        pass
            raw = engine.select(battle_ptr, action)
            decisions += 1
    finally:
        if battle_ptr:
            engine.finish(battle_ptr)
    return {"task": task, "states": states, "errors": errors, "decisions": decisions}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mining-games", type=int, default=300)
    parser.add_argument("--base-seed", type=int, default=202608160101)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/p1_causal_labels.jsonl")
    parser.add_argument("--errors-output", type=Path, default=ROOT / "artifacts/p1_causal_errors.jsonl")
    args = parser.parse_args()

    opponents = ["d842", "master_v1", "replay_refresh"]
    tasks = []
    for index in range(args.mining_games):
        tasks.append(
            {
                "seed": args.base_seed + index,
                "order": "first" if index % 2 == 0 else "second",
                "opponent": opponents[(index // 2) % len(opponents)],
            }
        )
    started = time.time()
    if args.workers > 1:
        import multiprocessing as mp

        context = mp.get_context("spawn")
        results = []
        with context.Pool(args.workers) as pool:
            for result in pool.imap_unordered(run_label_game, tasks, chunksize=1):
                results.append(result)
                if len(results) % 20 == 0:
                    total = sum(len(r["states"]) for r in results)
                    print({"games": len(results), "states": total, "elapsed": round(time.time() - started)}, flush=True)
    else:
        results = [run_label_game(task) for task in tasks]

    states = [state for result in results for state in result["states"]]
    errors = [error for result in results for error in result["errors"]]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w") as handle:
        for state in states:
            handle.write(json.dumps(state) + "\n")
    with args.errors_output.open("w") as handle:
        for error in errors:
            handle.write(json.dumps(error) + "\n")
    print(json.dumps({"games": len(results), "states": len(states), "errors": len(errors), "elapsed": round(time.time() - started)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

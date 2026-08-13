#!/usr/bin/env python3
"""C0 — Alakazam Petrel->Unfair Stamp opportunity audit.

Plays exact R0 against the authentic Alakazam 2.7 package on the seeded
engine and, at every hero MAIN prompt where the opponent Knocked Out one of
our Pokémon during their previous turn, mechanically checks the line:

    Petrel playable -> Petrel -> search results contain Unfair Stamp
    -> retrieve Stamp -> Stamp playable

through actual engine forks.  Never assumes hidden deck knowledge.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor"), str(ROOT / "scripts")]

from cg.api import AreaType, OptionType, SelectContext, SelectType, to_observation_class  # noqa: E402
from ptcg_ai.external import ExternalSubmissionAgent  # noqa: E402
from training.search_teacher import DeterminizationError, determinize_known_matchup  # noqa: E402
from generate_p1_causal_labels import (  # noqa: E402
    SeededSearchEngine,
    SEEDED_ENGINE,
    R0_PACKAGE,
    load_package_policy,
    rollout_to_terminal,
)

ALAKAZAM_27 = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0/freshstart/elite_submissions/alakazam_2_7")
STAMP_ID = 1080
PETREL_ID = 1219

_ENGINE: SeededSearchEngine | None = None


def get_engine() -> SeededSearchEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = SeededSearchEngine(SEEDED_ENGINE)
    return _ENGINE


def playable_cards(obs) -> dict[int, int]:
    me = obs.current.players[obs.current.yourIndex]
    hand = me.hand or []
    cards: dict[int, int] = {}
    for index, option in enumerate(obs.select.option):
        if option.type == OptionType.PLAY:
            position = getattr(option, "index", None)
            cards[index] = int(hand[position].id) if position is not None and 0 <= position < len(hand) else -1
    return cards


def board_serials(obs) -> set[int]:
    me = obs.current.players[obs.current.yourIndex]
    serials = set()
    for pokemon in (me.active or []) + (me.bench or []):
        if pokemon is not None:
            serials.add(int(pokemon.serial))
    return serials


def ko_since(obs, previous_serials: set[int]) -> bool:
    """True if a hero Pokémon vanished from play and is neither promoted to a
    preEvolution slot nor returned to the bench."""
    me = obs.current.players[obs.current.yourIndex]
    current = board_serials(obs)
    gone = previous_serials - current
    if not gone:
        return False
    in_discard = {int(card.serial) for card in (me.discard or [])}
    for pokemon in (me.active or []) + (me.bench or []):
        if pokemon is None:
            continue
        for prior in pokemon.preEvolution or []:
            gone.discard(int(prior.serial))
    return bool(gone & in_discard)


def search_stamp_option(obs) -> int | None:
    deck = obs.select.deck or []
    for index, option in enumerate(obs.select.option):
        if getattr(option, "area", None) == AreaType.DECK:
            position = getattr(option, "index", None)
            if position is not None and 0 <= position < len(deck) and int(deck[position].id) == STAMP_ID:
                return index
    return None


def run_game(task: dict) -> dict:
    seed = int(task["seed"])
    hero_seat = seed % 2
    order = "first" if seed % 3 == 0 else "second"
    random.seed(seed)
    np.random.seed(seed & 0xFFFFFFFF)
    engine = get_engine()
    os.environ["PTCG_GRIM_DAMAGE_SOLVER"] = "v0"
    hero_policy = load_package_policy(R0_PACKAGE, "policy_first.npz")
    fork_policy = load_package_policy(R0_PACKAGE, "policy_first.npz", cache_tag="fork")
    if hasattr(hero_policy, "reset"):
        hero_policy.reset()

    opponent = ExternalSubmissionAgent(ALAKAZAM_27, {"NO_SEARCH": "1"})
    hero_deck = [int(line) for line in (R0_PACKAGE / "deck.csv").read_text().splitlines() if line.strip()]
    decks = [hero_deck, opponent.deck] if hero_seat == 0 else [opponent.deck, hero_deck]

    opportunities = []
    errors = []
    previous_serials: set[int] = set()
    battle_ptr = 0
    try:
        battle_ptr, raw = engine.start(decks[0], decks[1], seed)
        while True:
            obs_dict = raw
            current = obs_dict.get("current") or {}
            if current.get("result", -1) is not None and int(current["result"]) >= 0:
                terminal = int(current["result"]) == hero_seat
                break
            select = obs_dict.get("select")
            obs = to_observation_class(obs_dict)
            acting = int(current["yourIndex"])
            context = int(select["context"])
            if context == int(SelectContext.IS_FIRST):
                want_yes = (order == "first") == (hero_seat == 0)
                chosen = [j for j, o in enumerate(obs.select.option) if (o.type == OptionType.YES) == want_yes]
                if len(chosen) != 1:
                    raise RuntimeError("invalid IS_FIRST choice set")
                raw = engine.select(battle_ptr, chosen)
                continue
            if acting != hero_seat:
                action = [int(index) for index in opponent(obs_dict)]
                raw = engine.select(battle_ptr, action)
                continue
            action = [int(index) for index in hero_policy.choose(obs)]
            if int(select["type"]) == int(SelectType.MAIN) and context == int(SelectContext.MAIN):
                koed = previous_serials and ko_since(obs, previous_serials)
                previous_serials = board_serials(obs)
                play = playable_cards(obs)
                hand_ids = {int(card.id) for card in (obs.current.players[acting].hand or [])}
                petrel_options = [index for index in play if play[index] == PETREL_ID]
                stamp_in_hand = STAMP_ID in hand_ids
                eligible = koed and bool(petrel_options) and not stamp_in_hand
                if eligible:
                    opp_hand = int(current["players"][1 - acting]["handCount"])
                    record = {
                        "game_seed": seed,
                        "order": order,
                        "turn": int(current["turn"]),
                        "opponent_hand_size": opp_hand,
                        "stamp_in_hand": stamp_in_hand,
                        "r0_choice_is_petrel": bool(play and any(i in petrel_options for i in action)),
                        "stamp_in_search": None,
                        "stamp_playable_after_retrieval": None,
                    }
                    record["game_win"] = None
                    try:
                        det_seed = seed * 31 + 7
                        kwargs = dict(determinize_known_matchup(obs, list(hero_deck), list(opponent.deck), random.Random(det_seed)))
                        engine.search_set_seed(det_seed)
                        root = engine.search_begin(obs_dict, **kwargs)
                        root_id = int(root["searchId"])
                        if hasattr(fork_policy, "reset"):
                            fork_policy.reset()
                        fork_opponent = ExternalSubmissionAgent(ALAKAZAM_27, {"NO_SEARCH": "1"})
                        state = engine.search_step(root_id, [petrel_options[0]])
                        stamp_found = False
                        steps = 0
                        while steps < 40:
                            fork_obsd = state["observation"]
                            fork_cur = fork_obsd.get("current") or {}
                            fork_sel = fork_obsd.get("select")
                            if fork_cur.get("result", -1) is not None and int(fork_cur["result"]) >= 0:
                                break
                            fork_obs = to_observation_class(fork_obsd)
                            fork_acting = int(fork_cur["yourIndex"])
                            fork_ctx = int(fork_sel["context"]) if fork_sel else -1
                            if fork_acting != hero_seat:
                                state = engine.search_step(int(state["searchId"]), [int(x) for x in fork_opponent(fork_obsd)])
                                steps += 1
                                continue
                            if fork_sel.get("deck") is not None:
                                option_index = search_stamp_option(fork_obs)
                                if option_index is not None:
                                    state = engine.search_step(int(state["searchId"]), [option_index])
                                    stamp_found = True
                                    steps += 1
                                    continue
                                state = engine.search_step(int(state["searchId"]), [0])
                                steps += 1
                                continue
                            if stamp_found and fork_ctx == int(SelectContext.MAIN):
                                fork_play = playable_cards(fork_obs)
                                record["stamp_playable_after_retrieval"] = STAMP_ID in fork_play.values()
                                break
                            fork_action = [int(x) for x in fork_policy.choose(fork_obs)]
                            state = engine.search_step(int(state["searchId"]), fork_action)
                            steps += 1
                        record["stamp_in_search"] = stamp_found
                        engine.search_release(root_id)
                        engine.search_end()
                        fork_opponent.close()
                    except (DeterminizationError, RuntimeError, ValueError, KeyError, IndexError) as exc:
                        errors.append({"game_seed": seed, "error": repr(exc)})
                    opportunities.append(record)
            raw = engine.select(battle_ptr, action)
        game_win = terminal
        for row in opportunities:
            row["game_win"] = game_win
    finally:
        if battle_ptr:
            engine.finish(battle_ptr)
        opponent.close()
    return {"seed": seed, "order": order, "win": game_win, "opportunities": opportunities, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=80)
    parser.add_argument("--base-seed", type=int, default=202608190101)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/c0_petrel_stamp_audit.json")
    parser.add_argument("--rows", type=Path, default=ROOT / "artifacts/c0_petrel_stamp_rows.jsonl")
    args = parser.parse_args()

    started = time.time()
    games = []
    for index in range(args.games):
        result = run_game({"seed": args.base_seed + index})
        games.append(result)
        if len(games) % 10 == 0:
            print({"games": len(games), "opps": sum(len(g["opportunities"]) for g in games), "elapsed": round(time.time() - started)}, flush=True)

    opportunities = [row for game in games for row in game["opportunities"]]
    loss_games = [game for game in games if not game["win"]]
    eligible_loss_games = [game for game in loss_games if game["opportunities"]]
    stamp_found = [row for row in opportunities if row["stamp_in_search"]]
    stamp_playable = [row for row in stamp_found if row["stamp_playable_after_retrieval"]]
    report = {
        "games": len(games),
        "wins": sum(game["win"] for game in games),
        "losses": len(loss_games),
        "opportunities": len(opportunities),
        "games_with_opportunity": len([game for game in games if game["opportunities"]]),
        "loss_games_with_opportunity": len(eligible_loss_games),
        "theoretical_max_uplift_pp": 100.0 * len(eligible_loss_games) / len(games),
        "stamp_in_search": len(stamp_found),
        "stamp_playable_after_retrieval": len(stamp_playable),
        "r0_played_petrel_at_opportunity": sum(row["r0_choice_is_petrel"] for row in opportunities),
        "opponent_hand_size_distribution": Counter(row["opponent_hand_size"] for row in opportunities),
        "errors": [error for game in games for error in game["errors"]][:10],
        "elapsed_seconds": round(time.time() - started),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    with args.rows.open("w") as handle:
        for row in opportunities:
            handle.write(json.dumps(row) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

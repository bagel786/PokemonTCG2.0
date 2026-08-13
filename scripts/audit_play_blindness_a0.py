#!/usr/bin/env python3
"""A0 — PLAY opportunity + blindness audit on authentic exact-Grim replays.

Descriptive only.  Never advances the engine and never changes a gameplay
policy.  For every hero MAIN/PLAY prompt it records:

- actual order and own-turn ordinal (first two own turns flagged separately)
- playable PLAY card identities (resolved as hand[option.index])
- whether the prompt offers >=2 distinct playable card identities
- A2 (R0) semantic PLAY choice versus the recorded action
- card-level agreement (duplicate-tolerant Counter of card ids)
- game outcome and opponent family

A0.2 additionally runs a hand-permutation diagnostic: the hand list order is
cyclically rotated and every PLAY/HAND-area option index is remapped so all
legal semantic choices stay identical.  A2's chosen SEMANTIC CARD is compared
before/after.  Evidence of positional reliance only, not promotion evidence.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor"), str(ROOT / "scripts")]

from cg.api import AreaType, OptionType, SelectContext, SelectType, to_observation_class  # noqa: E402
from ptcg_ai.model import NumpyPolicyModel  # noqa: E402
from ptcg_ai.view import card_table, resolve_area_card  # noqa: E402
from audit_grim_damage_conversion import (  # noqa: E402
    _a2_action,
    _episode_archetype,
    _valid_action,
)

R0_MODEL_SHA256 = "B19871A9F1499C2460AE266E58194ACAB1D8C90B390FA5CF24ED94B9A2B6BDA8"

TRAINERS_OF_INTEREST = (
    "Team Rocket's Petrel",
    "Rare Candy",
    "Unfair Stamp",
    "Dawn",
    "Hilda",
    "Boss's Orders",
    "Night Stretcher",
    "Poké Pad",
    "Pokégear 3.0",
    "Buddy-Buddy Poffin",
    "Lillie's Determination",
    "Tool Scrapper",
    "Spikemuth Gym",
)


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _own_turn_ordinal(turn: int, seat: int, first_player: int) -> int:
    if first_player not in (0, 1) or turn <= 0:
        return 0
    return (turn + 1) // 2 if seat == first_player else turn // 2


def _play_cards(obs) -> dict[int, int]:
    """Map PLAY option index -> hand card id it represents (hand[option.index])."""
    me = obs.current.players[obs.current.yourIndex]
    hand = me.hand or []
    cards: dict[int, int] = {}
    for index, option in enumerate(obs.select.option):
        if option.type == OptionType.PLAY:
            position = getattr(option, "index", None)
            if position is None or not 0 <= position < len(hand):
                cards[index] = -1
                continue
            cards[index] = int(hand[position].id)
    return cards


def _card_names(counter: Counter) -> list[str]:
    table = card_table()
    names = []
    for card_id, count in sorted(counter.items()):
        meta = table.get(int(card_id))
        name = meta.name if meta else str(card_id)
        names.extend([name] * count)
    return names


def _chosen_play_counter(obs, action: list[int]) -> Counter:
    play = _play_cards(obs)
    chosen = Counter()
    for index in action:
        if index in play:
            chosen[play[index]] += 1
    return chosen


def _permuted_obs(obs, rotation: int):
    """Rotate the hero hand by `rotation` and remap PLAY/HAND option indices.

    Returns an observation whose hand multiset and legal semantic choices are
    identical to `obs`, with only hand-list order and the option.index values
    that refer into the hand changed.
    """
    state = obs.current
    me = state.players[state.yourIndex]
    hand = list(me.hand or [])
    n = len(hand)
    if n < 2:
        return None
    rotation %= n
    if rotation == 0:
        return None
    new_hand = hand[rotation:] + hand[:rotation]
    position = {old: new for new, old in enumerate(range(rotation, n + rotation))}
    position = {old % n: new for old, new in position.items()}

    new_options = []
    for option in obs.select.option:
        index = getattr(option, "index", None)
        refers_hand = (
            option.type == OptionType.PLAY
            or (getattr(option, "area", None) == AreaType.HAND and index is not None)
        )
        if refers_hand and index in position:
            option = replace(option, index=position[index])
        new_options.append(option)

    new_me = replace(me, hand=new_hand)
    new_players = list(state.players)
    new_players[state.yourIndex] = new_me
    new_state = replace(state, players=new_players)
    new_select = replace(obs.select, option=new_options)
    return replace(obs, select=new_select, current=new_state)


def audit(replay_root: Path, submission_id: int, model_path: Path) -> dict:
    metadata = json.loads((replay_root / "episodes_metadata.json").read_text())
    episode_meta = {int(row["id"]): row for row in metadata}
    model = NumpyPolicyModel(model_path)
    model_digest = _sha256(model_path)

    rows: list[dict] = []
    game_rows: list[dict] = []
    counts = Counter()
    trainer_stats: dict[str, Counter] = defaultdict(Counter)
    parse_failures: dict[str, str] = {}

    for path in sorted(replay_root.glob("episode-*-replay.json")):
        try:
            episode_id = int(path.stem.split("-")[1])
            meta = episode_meta[episode_id]
            hero = next(
                i for i, agent in enumerate(meta["agents"]) if int(agent.get("submissionId", -1)) == submission_id
            )
            hero_won = int(meta["agents"][hero].get("reward", 0) or 0) == 1
            replay = json.loads(path.read_text())
            archetype = _episode_archetype(replay, hero)
            steps = replay.get("steps", [])
            game = {
                "episode": episode_id,
                "hero_won": hero_won,
                "opponent_archetype": archetype,
                "main_prompts": 0,
                "play_prompts": 0,
                "multi_prompts": 0,
                "multi_prompts_early": 0,
                "second_multi_early": 0,
                "second": False,
                "multi_game": False,
            }
            for step_index, step in enumerate(steps[:-1]):
                following = steps[step_index + 1]
                if hero >= len(step) or hero >= len(following):
                    continue
                raw = step[hero]
                if str(raw.get("status", "")).upper() != "ACTIVE":
                    continue
                obs_dict = raw.get("observation") or {}
                if not obs_dict.get("select") or not obs_dict.get("current"):
                    continue
                obs = to_observation_class(obs_dict)
                counts["decisions"] += 1
                if not (
                    int(obs.select.type) == int(SelectType.MAIN)
                    and int(obs.select.context) == int(SelectContext.MAIN)
                ):
                    continue
                counts["main_prompts"] += 1
                game["main_prompts"] += 1
                turn = int(obs.current.turn)
                seat = int(obs.current.yourIndex)
                first_player = int(obs.current.firstPlayer)
                order = "first" if first_player == seat else "second"
                if order == "second":
                    game["second"] = True
                ordinal = _own_turn_ordinal(turn, seat, first_player)
                early = ordinal in (1, 2)
                play_cards = _play_cards(obs)
                active_play = [i for i in play_cards if play_cards[i] >= 0]
                distinct = len({play_cards[i] for i in active_play})
                captured = _valid_action(obs, following[hero].get("action"))
                a2 = _a2_action(model, obs)
                captured_counter = _chosen_play_counter(obs, captured) if captured is not None else Counter()
                a2_counter = _chosen_play_counter(obs, a2)
                card_agree = captured_counter == a2_counter
                strict_agree = (
                    captured is not None
                    and len(captured) == len(a2)
                    and tuple(sorted(captured)) == tuple(sorted(a2))
                )
                multi = distinct >= 2
                counts["play_prompts"] += 1
                game["play_prompts"] += 1
                if multi:
                    counts["multi_prompts"] += 1
                    game["multi_prompts"] += 1
                    game["multi_game"] = True
                    if early:
                        counts["multi_prompts_early"] += 1
                        game["multi_prompts_early"] += 1
                        if order == "second":
                            game["second_multi_early"] += 1
                playable_names = Counter()
                table = card_table()
                for card_id in {play_cards[i] for i in active_play}:
                    meta = table.get(int(card_id))
                    playable_names[meta.name if meta else str(card_id)] += 1

                recorded_names = _card_names(captured_counter)
                a2_names = _card_names(a2_counter)
                for name in recorded_names:
                    trainer_stats[name]["recorded_played"] += 1
                    trainer_stats[name]["recorded_agree"] += int(card_agree)
                    trainer_stats[name]["recorded_strict_agree"] += int(strict_agree)
                for name in a2_names:
                    trainer_stats[name]["a2_played"] += 1
                    trainer_stats[name]["a2_agree"] += int(card_agree)
                for name in playable_names:
                    trainer_stats[name]["playable"] += 1
                    trainer_stats[name]["playable_multi"] += int(multi)

                perm_changes = []
                if multi:
                    n_hand = len(obs.current.players[seat].hand or [])
                    for rotation in range(1, n_hand):
                        permuted = _permuted_obs(obs, rotation)
                        if permuted is None:
                            continue
                        perm_a2 = _a2_action(model, permuted)
                        perm_counter = _chosen_play_counter(permuted, perm_a2)
                        changed = perm_counter != a2_counter
                        counts["permutations"] += 1
                        if changed:
                            counts["perm_changed"] += 1
                            perm_changes.append(rotation)

                rows.append(
                    {
                        "episode": episode_id,
                        "step": step_index,
                        "turn": turn,
                        "ordinal": ordinal,
                        "early": early,
                        "order": order,
                        "archetype": archetype,
                        "hero_won": hero_won,
                        "n_play_options": len(active_play),
                        "distinct_playable": distinct,
                        "multi": multi,
                        "hand_size": len(obs.current.players[seat].hand or []),
                        "recorded_semantic": recorded_names,
                        "a2_semantic": a2_names,
                        "card_agree": card_agree,
                        "strict_agree": strict_agree,
                        "playable": sorted(playable_names),
                        "perm_changed_rotations": perm_changes,
                    }
                )
            game_rows.append(game)
        except Exception as exc:  # pragma: no cover - defensive audit boundary
            parse_failures[path.name] = repr(exc)

    multi_games = [g for g in game_rows if g["multi_game"]]
    loss_games = [g for g in game_rows if not g["hero_won"]]
    eligible_loss_games = [g for g in loss_games if g["multi_game"]]
    second_games = [g for g in game_rows if g["second"]]
    second_loss_games = [g for g in loss_games if g["second"]]
    eligible_second_loss = [g for g in second_loss_games if g["multi_game"]]
    early_second_multi = [g for g in game_rows if g["second_multi_early"] > 0]
    early_second_multi_loss = [g for g in early_second_multi if not g["hero_won"]]

    play_rows = rows
    multi_rows = [r for r in rows if r["multi"]]
    multi_early_second_rows = [r for r in multi_rows if r["early"] and r["order"] == "second"]
    disagree_rows = [r for r in play_rows if not r["card_agree"]]
    perm_sensitive_rows = [r for r in rows if r["perm_changed_rotations"]]

    total = len(game_rows)
    result = {
        "label": "A0 PLAY OPPORTUNITY + BLINDNESS AUDIT — DESCRIPTIVE, NOT GAMEPLAY CAUSAL",
        "source": {
            "replays": str(replay_root),
            "submission_id": submission_id,
            "games": total,
            "model": str(model_path),
            "model_sha256": model_digest,
            "model_is_r0": model_digest == R0_MODEL_SHA256,
        },
        "counts": dict(counts),
        "opportunity": {
            "games_total": total,
            "games_with_multi": len(multi_games),
            "loss_games_with_multi": len(eligible_loss_games),
            "second_games": len(second_games),
            "second_loss_games_with_multi": len(eligible_second_loss),
            "early_second_multi_games": len(early_second_multi),
            "early_second_multi_loss_games": len(early_second_multi_loss),
            "prompts_total": len(play_rows),
            "prompts_multi": len(multi_rows),
            "prompts_multi_early_second": len(multi_early_second_rows),
            "theoretical_max_uplift_pp": 100.0 * len(eligible_loss_games) / total if total else 0.0,
            "theoretical_max_uplift_second_pp": 100.0 * len(eligible_second_loss) / len(second_games) if second_games else 0.0,
            "theoretical_max_uplift_early_second_pp": 100.0 * len(early_second_multi_loss) / len(second_games) if second_games else 0.0,
        },
        "agreement": {
            "play_prompts": len(play_rows),
            "card_level_agreement": sum(r["card_agree"] for r in play_rows),
            "card_level_agreement_rate": sum(r["card_agree"] for r in play_rows) / len(play_rows) if play_rows else 0.0,
            "strict_option_agreement": sum(r["strict_agree"] for r in play_rows),
            "strict_option_agreement_rate": sum(r["strict_agree"] for r in play_rows) / len(play_rows) if play_rows else 0.0,
            "disagree_prompts": len(disagree_rows),
        },
        "trainer_stats": {name: dict(stats) for name, stats in sorted(trainer_stats.items())},
        "permutation_diagnostic": {
            "eligible_prompts": len(multi_rows),
            "rotations_tested": counts["permutations"],
            "rotations_changed": counts["perm_changed"],
            "rotation_change_rate": counts["perm_changed"] / counts["permutations"] if counts["permutations"] else 0.0,
            "prompts_with_any_change": len(perm_sensitive_rows),
            "prompt_change_rate": len(perm_sensitive_rows) / len(multi_rows) if multi_rows else 0.0,
            "changes_by_archetype": Counter(r["archetype"] for r in perm_sensitive_rows),
        },
        "by_archetype": Counter(r["archetype"] for r in play_rows),
        "by_order": Counter(r["order"] for r in play_rows),
        "multi_by_order": Counter(r["order"] for r in multi_rows),
        "multi_early_second_by_archetype": Counter(r["archetype"] for r in multi_early_second_rows),
        "disagreement_examples": [
            {
                "episode": r["episode"],
                "step": r["step"],
                "turn": r["turn"],
                "ordinal": r["ordinal"],
                "order": r["order"],
                "archetype": r["archetype"],
                "hero_won": r["hero_won"],
                "playable": r["playable"],
                "recorded_semantic": r["recorded_semantic"],
                "a2_semantic": r["a2_semantic"],
                "hand_size": r["hand_size"],
            }
            for r in disagree_rows[:40]
        ],
        "permutation_examples": [
            {
                "episode": r["episode"],
                "step": r["step"],
                "order": r["order"],
                "archetype": r["archetype"],
                "a2_semantic": r["a2_semantic"],
                "changed_rotations": r["perm_changed_rotations"],
                "playable": r["playable"],
                "hand_size": r["hand_size"],
            }
            for r in perm_sensitive_rows[:40]
        ],
        "parse_failures": parse_failures,
    }
    return result, rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replays", type=Path, default="/Users/safiullahbaig/Projects/pokemonTCG2.0/data/replays/55399728")
    parser.add_argument("--submission-id", type=int, default=55399728)
    parser.add_argument(
        "--model",
        type=Path,
        default="/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/grim_damage_conversion/winner/extracted/policy_weights.npz",
    )
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/play_blindness_a0.json")
    parser.add_argument("--rows", type=Path, default=ROOT / "artifacts/play_blindness_a0_rows.jsonl")
    args = parser.parse_args()
    report, rows = audit(args.replays, args.submission_id, args.model)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    with args.rows.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    printable = dict(report)
    printable.pop("disagreement_examples", None)
    printable.pop("permutation_examples", None)
    print(json.dumps(printable, indent=2))


if __name__ == "__main__":
    main()

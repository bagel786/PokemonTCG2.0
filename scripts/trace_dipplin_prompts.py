#!/usr/bin/env python3
"""Collect public, engine-authentic prompt fixtures for the rank-34 Dipplin deck.

This is an audit harness, not the competition policy.  It runs the pinned native
engine, records only observations visible to the acting player, and writes the
first representative instance of every relevant prompt contract.  The small
audit driver deliberately exercises cards and effects that a generic policy may
never choose.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))

from cg.api import (  # noqa: E402
    AreaType,
    CardType,
    LogType,
    Observation,
    OptionType,
    SelectContext,
    SelectType,
    to_observation_class,
)
from cg.game import battle_finish, battle_select, battle_start  # noqa: E402
from ptcg_ai.heuristic import GrimmsnarlHeuristic  # noqa: E402
from ptcg_ai.safety import sanitize_selection  # noqa: E402
from ptcg_ai.view import (  # noqa: E402
    card_table,
    option_source_card,
    option_target_pokemon,
    prize_value,
    resolve_area_card,
)


GRASS_ENERGY = 1
APPLIN_DRAGON = 42
VOLBEAT = 88
GROOKEY = 89
THWACKEY = 90
APPLIN_GRASS = 92
DIPPLIN = 93
SHAYMIN = 343

UNFAIR_STAMP = 1080
POFFIN = 1086
BUG_SET = 1094
NIGHT_STRETCHER = 1097
SACRED_ASH = 1129
POKE_PAD = 1152
BRAVE_BANGLE = 1175
BOSS = 1182
BROCK = 1210
BLACK_BELT = 1211
HILDA = 1225
LILLIE = 1227
FESTIVAL = 1245

QUICK_SIGN = 107
DO_THE_WAVE = 115


EXACT_DECK: tuple[int, ...] = tuple(
    [GRASS_ENERGY] * 8
    + [APPLIN_DRAGON] * 3
    + [VOLBEAT] * 3
    + [GROOKEY] * 4
    + [THWACKEY] * 4
    + [APPLIN_GRASS]
    + [DIPPLIN] * 4
    + [SHAYMIN]
    + [UNFAIR_STAMP]
    + [POFFIN] * 4
    + [BUG_SET] * 4
    + [NIGHT_STRETCHER] * 2
    + [SACRED_ASH]
    + [POKE_PAD] * 4
    + [BRAVE_BANGLE]
    + [BOSS]
    + [BROCK]
    + [BLACK_BELT]
    + [HILDA] * 4
    + [LILLIE] * 4
    + [FESTIVAL] * 4
)

EFFECT_NAMES = {
    VOLBEAT: "quick_sign",
    POFFIN: "buddy_buddy_poffin",
    BUG_SET: "bug_catching_set",
    NIGHT_STRETCHER: "night_stretcher",
    SACRED_ASH: "sacred_ash",
    POKE_PAD: "poke_pad",
    BOSS: "boss_orders",
    BROCK: "brocks_scouting",
    HILDA: "hilda",
    THWACKEY: "boom_boom_groove",
}

TARGET_FIXTURES = frozenset(
    {
        "is_first_yes",
        "is_first_no",
        "setup_active",
        "setup_active_volbeat",
        "setup_bench",
        "quick_sign",
        "quick_sign_turn1_first",
        "quick_sign_two_targets",
        "buddy_buddy_poffin",
        "bug_catching_set",
        "night_stretcher",
        "sacred_ash",
        "sacred_ash_multi",
        "poke_pad",
        "boss_orders",
        "brocks_scouting",
        "brock_first_choice",
        "brock_second_basic",
        "hilda_evolution",
        "hilda_energy",
        "boom_boom_groove",
        "promotion_after_ko",
        "festival_second_attack",
        "festival_second_attack_after_ko",
        "main_play_festival",
        "main_attach_brave_bangle",
        "main_play_black_belt",
        "main_play_lillie",
        "main_play_unfair_stamp",
        "main_evolve_dipplin",
        "main_evolve_thwackey",
        "main_manual_energy",
        "main_retreat",
        "main_do_the_wave",
        "main_quick_sign_turn1",
        "main_two_thwackey_abilities",
        "main_second_thwackey_available",
        "hero_actual_first",
        "hero_actual_second",
    }
)


def load_deck(path: Path) -> list[int]:
    cards = [int(value) for value in path.read_text(encoding="utf-8").splitlines() if value.strip()]
    if len(cards) != 60:
        raise ValueError(f"expected a 60-card opponent deck, got {len(cards)} from {path}")
    return cards


def _effect_id(obs: Observation) -> int | None:
    effect = getattr(obs.select, "effect", None)
    return int(effect.id) if effect is not None else None


def _source(obs: Observation, index: int):
    return option_source_card(obs, obs.select.option[index])


def _ability_source(obs: Observation, index: int):
    option = obs.select.option[index]
    if option.type != OptionType.ABILITY:
        return None
    return resolve_area_card(obs, option.area, option.index, obs.current.yourIndex)


def _in_play(player) -> list[Any]:
    return [card for card in list(player.active or []) + list(player.bench or []) if card is not None]


class AuditPolicy:
    """A deterministic driver biased toward prompt coverage, never used for play."""

    def __init__(self, *, go_first: bool) -> None:
        self.go_first = bool(go_first)
        self.turn = -1
        self.do_the_wave_attacks = 0
        self.last_effect: int | None = None
        self.effect_prompt_ordinal = 0
        self.thwackey_abilities_chosen = 0
        self.first_attack_target_serial: int | None = None

    def _observe_logs(self, obs: Observation) -> None:
        turn = int(obs.current.turn)
        if turn != self.turn:
            self.turn = turn
            self.do_the_wave_attacks = 0
            self.thwackey_abilities_chosen = 0
            self.first_attack_target_serial = None
        for log in obs.logs or []:
            if (
                int(getattr(log, "type", -1)) == int(LogType.ATTACK)
                and int(getattr(log, "playerIndex", -1)) == int(obs.current.yourIndex)
                and int(getattr(log, "attackId", -1)) == DO_THE_WAVE
            ):
                self.do_the_wave_attacks += 1

    def choose(self, obs: Observation) -> list[int]:
        self._observe_logs(obs)
        select = obs.select
        effect = _effect_id(obs)
        if effect is not None and effect == self.last_effect:
            self.effect_prompt_ordinal += 1
        elif effect is not None:
            self.effect_prompt_ordinal = 1
        else:
            self.effect_prompt_ordinal = 0
        self.last_effect = effect
        if select.context == SelectContext.IS_FIRST:
            wanted = OptionType.YES if self.go_first else OptionType.NO
            index = next(i for i, option in enumerate(select.option) if option.type == wanted)
            return sanitize_selection(select, [index], 1)
        if select.context == SelectContext.SETUP_ACTIVE_POKEMON:
            return self._rank_cards(obs, [VOLBEAT, APPLIN_GRASS, APPLIN_DRAGON, GROOKEY, SHAYMIN], 1)
        if select.context == SelectContext.SETUP_BENCH_POKEMON:
            return self._rank_cards(
                obs,
                [APPLIN_GRASS, APPLIN_DRAGON, GROOKEY, APPLIN_DRAGON, GROOKEY, SHAYMIN, VOLBEAT],
                select.maxCount,
            )
        if select.type == SelectType.MAIN:
            return self._main(obs)
        if select.type == SelectType.ATTACK or select.context == SelectContext.ATTACK:
            attacks = [i for i, option in enumerate(select.option) if option.type == OptionType.ATTACK]
            attacks.sort(key=lambda i: (int(select.option[i].attackId or 0) == DO_THE_WAVE, -i), reverse=True)
            return sanitize_selection(select, attacks, 1 if attacks else select.minCount)
        if select.context in {SelectContext.SWITCH, SelectContext.TO_ACTIVE}:
            return self._switch(obs)
        if select.type == SelectType.COUNT:
            ranked = sorted(
                range(len(select.option)),
                key=lambda i: (int(select.option[i].number or 0), -i),
                reverse=True,
            )
            return sanitize_selection(select, ranked, 1)
        if select.type == SelectType.YES_NO:
            yes = [i for i, option in enumerate(select.option) if option.type == OptionType.YES]
            no = [i for i, option in enumerate(select.option) if option.type == OptionType.NO]
            return sanitize_selection(select, yes + no, 1)
        if select.type == SelectType.CARD:
            return self._card_prompt(obs)
        return sanitize_selection(select, list(range(len(select.option))), select.maxCount)

    def _rank_cards(self, obs: Observation, priorities: list[int], desired: int) -> list[int]:
        rank = {card_id: len(priorities) - priorities.index(card_id) for card_id in set(priorities)}
        indices = list(range(len(obs.select.option)))
        indices.sort(
            key=lambda i: (
                rank.get(int(getattr(_source(obs, i), "id", -1)), 0),
                -i,
            ),
            reverse=True,
        )
        return sanitize_selection(obs.select, indices, desired)

    def _main(self, obs: Observation) -> list[int]:
        me = obs.current.players[obs.current.yourIndex]
        active = (me.active or [None])[0]
        active_id = int(getattr(active, "id", -1))
        bench_dipplin = any(int(card.id) == DIPPLIN for card in me.bench or [])
        discard_pokemon = sum(
            1
            for card in me.discard or []
            if (metadata := card_table().get(int(card.id))) is not None
            and int(metadata.cardType) == int(CardType.POKEMON)
        )

        def score(index: int) -> tuple[int, int]:
            option = obs.select.option[index]
            source = _source(obs, index)
            source_id = int(getattr(source, "id", -1))
            target = option_target_pokemon(obs, option)
            target_id = int(getattr(target, "id", -1))
            if option.type == OptionType.EVOLVE:
                return ({DIPPLIN: 980, THWACKEY: 960}.get(source_id, 700), -index)
            if option.type == OptionType.ATTACH:
                if source_id == BRAVE_BANGLE:
                    return (940 if target_id == DIPPLIN else 720, -index)
                if source_id == GRASS_ENERGY:
                    if target_id == DIPPLIN:
                        return (920, -index)
                    if target_id == VOLBEAT and int(obs.current.turn) == 1:
                        return (995, -index)
                    if target_id in {APPLIN_GRASS, APPLIN_DRAGON}:
                        return (760, -index)
                    return (500, -index)
            if option.type == OptionType.PLAY:
                play_priority = {
                    POFFIN: 900,
                    BUG_SET: 890,
                    POKE_PAD: 880,
                    NIGHT_STRETCHER: 875,
                    SACRED_ASH: 870 if discard_pokemon >= 2 else -500,
                    FESTIVAL: 865,
                    HILDA: 850,
                    BROCK: 845,
                    BLACK_BELT: 840,
                    BOSS: 835,
                    UNFAIR_STAMP: 830,
                    LILLIE: 810,
                }
                return (play_priority.get(source_id, 600), -index)
            if option.type == OptionType.ABILITY:
                ability = _ability_source(obs, index)
                return (855 if int(getattr(ability, "id", -1)) == THWACKEY else 650, -index)
            if option.type == OptionType.RETREAT:
                return (825 if active_id != DIPPLIN and bench_dipplin else 300, -index)
            if option.type == OptionType.ATTACK:
                if int(option.attackId or 0) == DO_THE_WAVE:
                    return (800, -index)
                if int(option.attackId or 0) == QUICK_SIGN:
                    return (990 if int(obs.current.turn) == 1 else 790, -index)
                return (420, -index)
            if option.type == OptionType.END:
                return (-1000, -index)
            return (0, -index)

        ranked = sorted(range(len(obs.select.option)), key=score, reverse=True)
        result = sanitize_selection(obs.select, ranked, 1)
        if result:
            option = obs.select.option[result[0]]
            if option.type == OptionType.ABILITY:
                ability = _ability_source(obs, result[0])
                if int(getattr(ability, "id", -1)) == THWACKEY:
                    self.thwackey_abilities_chosen += 1
            elif option.type == OptionType.ATTACK and int(option.attackId or 0) == DO_THE_WAVE:
                opponent = obs.current.players[1 - obs.current.yourIndex]
                target = (opponent.active or [None])[0]
                self.first_attack_target_serial = int(getattr(target, "serial", -1))
        return result

    def _card_prompt(self, obs: Observation) -> list[int]:
        effect = _effect_id(obs)
        desired = obs.select.maxCount
        me = obs.current.players[obs.current.yourIndex]
        counts = Counter(int(card.id) for card in _in_play(me))

        def priority(index: int) -> tuple[int, int]:
            card = _source(obs, index)
            card_id = int(getattr(card, "id", -1))
            metadata = card_table().get(card_id)
            if effect in {VOLBEAT, POFFIN}:
                values = {
                    APPLIN_GRASS: 100 if counts[APPLIN_GRASS] + counts[APPLIN_DRAGON] == 0 else 75,
                    APPLIN_DRAGON: 95 if counts[APPLIN_GRASS] + counts[APPLIN_DRAGON] == 0 else 70,
                    GROOKEY: 90 if counts[GROOKEY] + counts[THWACKEY] == 0 else 65,
                    SHAYMIN: 45,
                    VOLBEAT: 20,
                }
                return (values.get(card_id, 0), -index)
            if effect == HILDA:
                if metadata is not None and int(metadata.cardType) in {
                    int(CardType.BASIC_ENERGY),
                    int(CardType.SPECIAL_ENERGY),
                }:
                    return (100 if card_id == GRASS_ENERGY else 10, -index)
                return ({DIPPLIN: 100, THWACKEY: 80}.get(card_id, 20), -index)
            if effect == BROCK:
                return (
                    {
                        APPLIN_GRASS: 100,
                        APPLIN_DRAGON: 95,
                        GROOKEY: 90,
                        DIPPLIN: 85,
                        THWACKEY: 80,
                        SHAYMIN: 40,
                        VOLBEAT: 20,
                    }.get(card_id, 0),
                    -index,
                )
            if effect == THWACKEY:
                return (
                    {
                        DIPPLIN: 120,
                        FESTIVAL: 115,
                        GRASS_ENERGY: 110,
                        APPLIN_GRASS: 100,
                        APPLIN_DRAGON: 95,
                        THWACKEY: 90,
                        HILDA: 80,
                        LILLIE: 75,
                    }.get(card_id, 20),
                    -index,
                )
            if effect in {BUG_SET, POKE_PAD, NIGHT_STRETCHER}:
                return (
                    {
                        DIPPLIN: 120,
                        GRASS_ENERGY: 115,
                        APPLIN_GRASS: 110,
                        GROOKEY: 105,
                        THWACKEY: 100,
                        APPLIN_DRAGON: 95,
                        SHAYMIN: 60,
                        VOLBEAT: 30,
                    }.get(card_id, 0),
                    -index,
                )
            if effect == SACRED_ASH:
                return ({DIPPLIN: 120, APPLIN_GRASS: 115, APPLIN_DRAGON: 110, THWACKEY: 105, GROOKEY: 100}.get(card_id, 20), -index)
            if obs.select.context == SelectContext.SETUP_BENCH_POKEMON:
                return ({APPLIN_GRASS: 100, APPLIN_DRAGON: 95, GROOKEY: 90, SHAYMIN: 50, VOLBEAT: 20}.get(card_id, 0), -index)
            return (prize_value(card) * 10 if card is not None else 0, -index)

        ranked = sorted(range(len(obs.select.option)), key=priority, reverse=True)
        return sanitize_selection(obs.select, ranked, desired)

    def _switch(self, obs: Observation) -> list[int]:
        me = int(obs.current.yourIndex)
        effect = _effect_id(obs)

        def score(index: int) -> tuple[int, int]:
            card = _source(obs, index)
            if card is None:
                return (0, -index)
            if effect == BOSS or int(getattr(card, "playerIndex", me)) != me:
                return (1000 * prize_value(card) - int(getattr(card, "hp", 0)), -index)
            return (
                {
                    DIPPLIN: 1000,
                    APPLIN_GRASS: 800,
                    APPLIN_DRAGON: 750,
                    VOLBEAT: 400,
                    GROOKEY: 300,
                    THWACKEY: 100,
                    SHAYMIN: 50,
                }.get(int(card.id), 0),
                -index,
            )

        ranked = sorted(range(len(obs.select.option)), key=score, reverse=True)
        return sanitize_selection(obs.select, ranked, 1)


def fixture_names(obs: Observation, action: Iterable[int], *, go_first: bool, policy: AuditPolicy) -> set[str]:
    names: set[str] = set()
    select = obs.select
    context = int(select.context)
    effect = _effect_id(obs)
    if context == int(SelectContext.IS_FIRST):
        names.add("is_first_yes" if go_first else "is_first_no")
    elif context == int(SelectContext.SETUP_ACTIVE_POKEMON):
        names.add("setup_active")
        if any(int(getattr(_source(obs, i), "id", -1)) == VOLBEAT for i in range(len(select.option))):
            names.add("setup_active_volbeat")
    elif context == int(SelectContext.SETUP_BENCH_POKEMON):
        names.add("setup_bench")
    elif effect in EFFECT_NAMES:
        base = EFFECT_NAMES[effect]
        if effect == HILDA:
            ids = [int(getattr(_source(obs, i), "id", -1)) for i in range(len(select.option))]
            metadata = [card_table().get(card_id) for card_id in ids]
            energy_only = bool(metadata) and all(
                item is not None
                and int(item.cardType) in {int(CardType.BASIC_ENERGY), int(CardType.SPECIAL_ENERGY)}
                for item in metadata
            )
            names.add("hilda_energy" if energy_only else "hilda_evolution")
        else:
            names.add(base)
        if effect == VOLBEAT:
            if select.maxCount >= 2:
                names.add("quick_sign_two_targets")
            if (
                int(obs.current.turn) == 1
                and int(obs.current.yourIndex) == int(obs.current.firstPlayer)
            ):
                names.add("quick_sign_turn1_first")
        elif effect == BROCK:
            names.add(
                "brock_first_choice"
                if policy.effect_prompt_ordinal <= 1
                else "brock_second_basic"
            )
        elif effect == SACRED_ASH and select.maxCount >= 2:
            names.add("sacred_ash_multi")
    if context == int(SelectContext.TO_ACTIVE) and effect is None:
        names.add("promotion_after_ko")
    if (
        int(select.type) == int(SelectType.ATTACK)
        and context == int(SelectContext.ATTACK)
        and policy.do_the_wave_attacks >= 1
        and any(int(option.attackId or 0) == DO_THE_WAVE for option in select.option)
    ):
        names.add("festival_second_attack")
        opponent = obs.current.players[1 - obs.current.yourIndex]
        active = (opponent.active or [None])[0]
        if (
            policy.first_attack_target_serial is not None
            and int(getattr(active, "serial", -1)) != policy.first_attack_target_serial
        ):
            names.add("festival_second_attack_after_ko")
    if int(select.type) == int(SelectType.MAIN):
        thwackey_abilities = [
            i
            for i, option in enumerate(select.option)
            if option.type == OptionType.ABILITY
            and int(getattr(_ability_source(obs, i), "id", -1)) == THWACKEY
        ]
        if len(thwackey_abilities) >= 2:
            names.add("main_two_thwackey_abilities")
        if thwackey_abilities and policy.thwackey_abilities_chosen >= 2:
            names.add("main_second_thwackey_available")
        for index in action:
            option = select.option[int(index)]
            source = _source(obs, int(index))
            source_id = int(getattr(source, "id", -1))
            if option.type == OptionType.PLAY:
                names.add(
                    {
                        FESTIVAL: "main_play_festival",
                        BLACK_BELT: "main_play_black_belt",
                        LILLIE: "main_play_lillie",
                        UNFAIR_STAMP: "main_play_unfair_stamp",
                    }.get(source_id, f"main_play_{source_id}")
                )
            elif option.type == OptionType.ATTACH:
                names.add("main_attach_brave_bangle" if source_id == BRAVE_BANGLE else "main_manual_energy")
            elif option.type == OptionType.EVOLVE:
                if source_id == DIPPLIN:
                    names.add("main_evolve_dipplin")
                elif source_id == THWACKEY:
                    names.add("main_evolve_thwackey")
            elif option.type == OptionType.RETREAT:
                names.add("main_retreat")
            elif option.type == OptionType.ATTACK and int(option.attackId or 0) == DO_THE_WAVE:
                names.add("main_do_the_wave")
            elif (
                option.type == OptionType.ATTACK
                and int(option.attackId or 0) == QUICK_SIGN
                and int(obs.current.turn) == 1
                and int(obs.current.yourIndex) == int(obs.current.firstPlayer)
            ):
                names.add("main_quick_sign_turn1")
        if obs.current.yourIndex == obs.current.firstPlayer:
            names.add("hero_actual_first")
        else:
            names.add("hero_actual_second")
    return names


def _public_fixture(raw: dict[str, Any], action: list[int], name: str) -> dict[str, Any]:
    observation = copy.deepcopy(raw)
    observation["search_begin_input"] = None
    return {
        "fixture": name,
        "observation": observation,
        "expected_audit_action": list(map(int, action)),
        "source": "pinned_native_engine_public_observation",
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    if len(EXACT_DECK) != 60:
        raise AssertionError(f"exact Dipplin deck expanded to {len(EXACT_DECK)}, not 60")
    opponent_deck = load_deck(args.opponent_deck)
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    fixtures: dict[str, dict[str, Any]] = {}
    occurrences: Counter[str] = Counter()
    games_complete = decisions = policy_errors = illegal_actions = 0

    modes = (True, False)
    for game_index in range(args.games):
        go_first = modes[game_index % len(modes)]
        raw, start = battle_start(list(EXACT_DECK), opponent_deck)
        if start.errorType != 0:
            raise RuntimeError(f"engine rejected deck: errorType={start.errorType}")
        hero = AuditPolicy(go_first=go_first)
        opponent = GrimmsnarlHeuristic()
        try:
            for _step in range(args.max_decisions):
                obs = to_observation_class(raw)
                if obs.current is not None and obs.current.result != -1:
                    games_complete += 1
                    break
                actor = int(obs.current.yourIndex)
                try:
                    action = hero.choose(obs) if actor == 0 else opponent.choose(obs)
                except Exception:
                    policy_errors += 1
                    action = sanitize_selection(
                        obs.select,
                        list(range(len(obs.select.option))),
                        obs.select.minCount,
                    )
                if actor == 0:
                    for name in fixture_names(obs, action, go_first=go_first, policy=hero):
                        occurrences[name] += 1
                        fixtures.setdefault(name, _public_fixture(raw, action, name))
                try:
                    raw = battle_select(list(map(int, action)))
                except Exception:
                    illegal_actions += 1
                    raise
                decisions += 1
            else:
                raise RuntimeError(f"game {game_index} exceeded {args.max_decisions} decisions")
        finally:
            battle_finish()
        if TARGET_FIXTURES <= set(fixtures) and games_complete >= args.minimum_complete_games:
            break

    for name, payload in sorted(fixtures.items()):
        (output / f"{name}.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    missing = sorted(TARGET_FIXTURES - set(fixtures))
    summary = {
        "deck": list(EXACT_DECK),
        "deck_count": len(EXACT_DECK),
        "deck_counts": {str(key): value for key, value in sorted(Counter(EXACT_DECK).items())},
        "games_complete": games_complete,
        "decisions": decisions,
        "policy_errors": policy_errors,
        "illegal_actions": illegal_actions,
        "fixtures": sorted(fixtures),
        "fixture_occurrences": dict(sorted(occurrences.items())),
        "target_fixtures": sorted(TARGET_FIXTURES),
        "missing_target_fixtures": missing,
        "complete": not missing and policy_errors == 0 and illegal_actions == 0,
        "opponent_deck": str(args.opponent_deck.resolve()),
        "note": "Opponent identity is used only by this offline prompt-audit harness.",
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=200)
    parser.add_argument("--minimum-complete-games", type=int, default=20)
    parser.add_argument("--max-decisions", type=int, default=800)
    parser.add_argument("--opponent-deck", type=Path, default=ROOT / "decks" / "grimmsnarl.csv")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts" / "dipplin_prompt_audit",
    )
    args = parser.parse_args()
    if args.games <= 0 or args.minimum_complete_games <= 0 or args.max_decisions <= 0:
        parser.error("games, minimum-complete-games, and max-decisions must be positive")
    return args


if __name__ == "__main__":
    run(parse_args())

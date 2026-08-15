"""Narrow, replay-derived Wave-1 rails layered on the frozen A2 policy.

The rails only reorder legal options.  Every unmatched or incompletely described
prompt falls through to A2 unchanged, and the ordinary safety sanitizer remains
the final boundary before an action is returned to the engine.
"""

from __future__ import annotations

from collections import Counter
from functools import lru_cache

from cg.api import AreaType, EnergyType, OptionType, SelectContext

from .card_ids import (
    BUDDY_BUDDY_POFFIN,
    HANDHELD_FAN,
    LILLIES_DETERMINATION,
    MARNIES_GRIMMSNARL_EX,
    MARNIES_IMPIDIMP,
    MARNIES_MORGREM,
    MUNKIDORI,
    POKE_PAD,
    RARE_CANDY,
    SHADOW_BULLET,
    SNORUNT,
    SPIKEMUTH_GYM,
    TEAM_ROCKETS_PETREL,
)
from .view import attack_table, card_table, option_source_card, option_target_pokemon


FROSLASS_IDS = frozenset({104, 861})
GRIM_LINE = frozenset({MARNIES_IMPIDIMP, MARNIES_MORGREM, MARNIES_GRIMMSNARL_EX})

ALAKAZAM_SINK_TIERS = (
    frozenset({65, 305, 996}),                 # Dunsparce
    frozenset({66, 306, 997}),                 # Dudunsparce
    frozenset({174}),                          # Fan Rotom
    frozenset({758, 759, 848, 849}),           # Buneary / Lopunny
    frozenset({109, 245, 741, 742, 743}),      # Abra line
)
LUCARIO_SINK_TIERS = (
    frozenset({675}),                          # Lunatone
    frozenset({676}),                          # Solrock
    frozenset({673}),                          # Makuhita
    frozenset({333, 677, 974}),                # Riolu
    frozenset({674}),                          # Hariyama
    frozenset({678}),                          # Mega Lucario ex
)
GRIM_SINK_TIERS = (
    frozenset({MARNIES_IMPIDIMP}),
    frozenset({MUNKIDORI}),
    frozenset({MARNIES_MORGREM}),
    frozenset({MARNIES_GRIMMSNARL_EX}),
    frozenset({SNORUNT}) | FROSLASS_IDS,
)
OGERPON_IDS = frozenset({95, 96, 349})


def _context_is(select, numeric: int, name: str) -> bool:
    context = getattr(select, "context", None)
    return context == numeric or str(context).replace("_", "").lower().endswith(name.replace("_", "").lower())


def _effect_id(obs) -> int:
    effect = getattr(obs.select, "effect", None)
    context = getattr(obs.select, "contextCard", None)
    return int(getattr(effect or context, "id", 0) or 0)


def _own_turn_ordinal(state) -> int:
    if state is None or state.firstPlayer not in (0, 1) or state.turn <= 0:
        return 0
    return (state.turn + 1) // 2 if state.yourIndex == state.firstPlayer else state.turn // 2


def _cards(player, zone: str) -> list:
    return [card for card in (getattr(player, zone, None) or []) if card is not None]


def _board(player) -> list[tuple[int, object]]:
    result = [(0, card) for card in _cards(player, "active")]
    result.extend((index + 1, card) for index, card in enumerate(_cards(player, "bench")))
    return result


def _hand_ids(player) -> set[int]:
    return {int(card.id) for card in _cards(player, "hand")}


def _play_option(obs, card_id: int) -> int | None:
    for index, option in enumerate(obs.select.option):
        if int(option.type) != int(OptionType.PLAY):
            continue
        card = option_source_card(obs, option)
        if card is not None and int(card.id) == card_id:
            return index
    return None


def _ability_option(obs, card_id: int) -> int | None:
    for index, option in enumerate(obs.select.option):
        if int(option.type) != int(OptionType.ABILITY):
            continue
        card = option_source_card(obs, option)
        if card is not None and int(card.id) == card_id:
            return index
    return None


def _ranked_with(ranked: list[int], preferred: list[int]) -> list[int]:
    head = []
    for index in preferred:
        if index in ranked and index not in head:
            head.append(index)
    return head + [index for index in ranked if index not in head]


def _target_option(obs, index: int):
    option = obs.select.option[index]
    return option_target_pokemon(obs, option) or option_source_card(obs, option)


def _option_active(option) -> bool:
    return option.inPlayArea == AreaType.ACTIVE or (
        option.inPlayArea is None and option.area == AreaType.ACTIVE
    )


def _option_slot(option) -> int:
    value = option.inPlayIndex if option.inPlayIndex is not None else option.index
    return int(value or 0)


def _option_card_id(obs, index: int) -> int:
    card = option_source_card(obs, obs.select.option[index])
    return int(getattr(card, "id", 0) or 0)


def _old_imp(player) -> list[tuple[int, object]]:
    return [
        (slot, card) for slot, card in _board(player)
        if int(card.id) == MARNIES_IMPIDIMP and not bool(getattr(card, "appearThisTurn", False))
    ]


def _damage(card) -> int:
    return max(0, int(getattr(card, "maxHp", 0) or 0) - int(getattr(card, "hp", 0) or 0))


def _energy_count(card) -> int:
    return len(getattr(card, "energies", None) or [])


def _minimum_attack_deficit(card, extra_energy: int | None = None) -> int:
    metadata = card_table().get(int(getattr(card, "id", 0) or 0))
    if metadata is None or not metadata.attacks:
        return 99
    energies = [int(value) for value in (getattr(card, "energies", None) or [])]
    if extra_energy is not None:
        energies.append(int(extra_energy))
    return min(_attack_deficit(energies, attack_table()[attack_id].energies)
               for attack_id in metadata.attacks if attack_id in attack_table())


def _energy_matches(energy: int, required: int) -> bool:
    return (
        required == int(EnergyType.COLORLESS)
        or energy == required
        or energy == int(EnergyType.RAINBOW)
        or (energy == int(EnergyType.TEAM_ROCKET) and required in {
            int(EnergyType.PSYCHIC), int(EnergyType.DARKNESS)
        })
    )


def _attack_deficit(energies, requirements) -> int:
    remaining = [int(value) for value in energies]
    typed = [int(value) for value in requirements if int(value) != int(EnergyType.COLORLESS)]
    colorless = sum(int(value) == int(EnergyType.COLORLESS) for value in requirements)
    missing = 0
    for required in typed:
        match = next((i for i, energy in enumerate(remaining) if _energy_matches(energy, required)), None)
        if match is None:
            missing += 1
        else:
            remaining.pop(match)
    return missing + max(0, colorless - len(remaining))


@lru_cache(maxsize=1)
def _evolves_from_names() -> frozenset[str]:
    return frozenset(data.evolvesFrom for data in card_table().values() if data.evolvesFrom)


def _public_opponent_ids(obs) -> set[int]:
    state = obs.current
    opponent = state.players[1 - state.yourIndex]
    ids = {int(card.id) for _, card in _board(opponent)}
    ids.update(int(card.id) for card in _cards(opponent, "discard"))
    return ids


def _punk_capacity(player) -> int:
    return sum(max(0, 2 - _energy_count(card)) for _, card in _board(player) if int(card.id) in GRIM_LINE)


def _punk_target_key(obs, option_index: int):
    option = obs.select.option[option_index]
    target = _target_option(obs, option_index)
    if target is None or int(target.id) not in GRIM_LINE or _energy_count(target) >= 2:
        return None
    active = _option_active(option)
    target_id = int(target.id)
    if active and target_id == MARNIES_GRIMMSNARL_EX:
        tier = 0
    elif target_id == MARNIES_GRIMMSNARL_EX and _bench_grim_promotable(obs, target):
        tier = 1
    elif target_id == MARNIES_MORGREM:
        tier = 2
    elif target_id == MARNIES_IMPIDIMP:
        tier = 3
    else:
        tier = 4
    return (tier, -_energy_count(target), _option_slot(option), option_index)


def _bench_grim_promotable(obs, target) -> bool:
    state = obs.current
    if state.retreated:
        return False
    me = state.players[state.yourIndex]
    active = _cards(me, "active")
    if not active:
        return True
    metadata = card_table().get(int(active[0].id))
    return metadata is not None and _energy_count(active[0]) >= int(metadata.retreatCost)


def _apply_punk_up(obs, ranked: list[int], desired: int):
    select = obs.select
    if _effect_id(obs) != MARNIES_GRIMMSNARL_EX:
        return None
    me = obs.current.players[obs.current.yourIndex]
    capacity = _punk_capacity(me)
    if _context_is(select, int(SelectContext.ACTIVATE), "ACTIVATE"):
        wanted = OptionType.YES if capacity > 0 and me.deckCount > 0 else OptionType.NO
        choices = [i for i, option in enumerate(select.option) if int(option.type) == int(wanted)]
        if choices:
            return _ranked_with(ranked, choices), desired, "punk_up_activate"
    if _context_is(select, int(SelectContext.ATTACH_TO), "ATTACH_TO"):
        count = max(int(select.minCount), min(int(select.maxCount), capacity))
        return ranked, count, "punk_up_energy_count"
    if _context_is(select, int(SelectContext.ATTACH_FROM), "ATTACH_FROM"):
        choices = []
        for index in range(len(select.option)):
            key = _punk_target_key(obs, index)
            if key is not None:
                choices.append(key)
        if choices:
            preferred = min(choices)[-1]
            return _ranked_with(ranked, [preferred]), desired, "punk_up_target"
    return None


def _apply_munk_source(obs, ranked: list[int], desired: int):
    select = obs.select
    if _effect_id(obs) != MUNKIDORI:
        return None
    me = obs.current.players[obs.current.yourIndex]
    if _context_is(select, int(SelectContext.REMOVE_DAMAGE_COUNTER), "REMOVE_DAMAGE_COUNTER"):
        candidates = []
        checkup = (10 if bool(me.poisoned) else 0) + (20 if bool(me.burned) else 0)
        for index in range(len(select.option)):
            option = select.option[index]
            if option.playerIndex != obs.current.yourIndex:
                continue
            card = _target_option(obs, index)
            damage = _damage(card)
            if card is None or damage <= 0:
                continue
            active = option.area == AreaType.ACTIVE
            lethal = active and checkup > 0 and int(card.hp) <= checkup
            card_id = int(card.id)
            if active and card_id == MARNIES_GRIMMSNARL_EX:
                tier = 0
            elif card_id == MARNIES_GRIMMSNARL_EX:
                tier = 1
            elif card_id == MUNKIDORI:
                tier = 2
            elif card_id == MARNIES_IMPIDIMP:
                tier = 3
            elif card_id == MARNIES_MORGREM:
                tier = 4
            else:
                tier = 5
            candidates.append((not lethal, damage < 30, tier, -damage, index))
        if candidates:
            preferred = min(candidates)[-1]
            return _ranked_with(ranked, [preferred]), desired, "munk_damage_source"
    if _context_is(select, int(SelectContext.REMOVE_DAMAGE_COUNTER_COUNT), "REMOVE_DAMAGE_COUNTER_COUNT"):
        source = getattr(select, "contextCard", None)
        source_serial = int(getattr(source, "serial", 0) or 0)
        source_board = next(
            (card for _, card in _board(me) if int(getattr(card, "serial", 0) or 0) == source_serial),
            source,
        )
        counters = _damage(source_board) // 10 if source_board is not None else 0
        wanted = min(3, counters)
        choices = [
            i for i, option in enumerate(select.option)
            if int(getattr(option, "number", 0) or 0) == wanted
        ]
        if wanted > 0 and choices:
            return _ranked_with(ranked, choices), desired, "munk_damage_count"
    return None


def _apply_setup(obs, ranked: list[int], desired: int):
    select = obs.select
    if _context_is(select, int(SelectContext.SETUP_ACTIVE_POKEMON), "SETUP_ACTIVE_POKEMON"):
        priorities = (MARNIES_IMPIDIMP, MUNKIDORI, SNORUNT)
        for card_id in priorities:
            choices = [i for i in ranked if _option_card_id(obs, i) == card_id]
            if choices:
                return _ranked_with(ranked, choices), 1, "tempo_setup_active"
    if _context_is(select, int(SelectContext.SETUP_BENCH_POKEMON), "SETUP_BENCH_POKEMON"):
        me = obs.current.players[obs.current.yourIndex]
        active_id = int(_cards(me, "active")[0].id) if _cards(me, "active") else 0
        if active_id != MARNIES_IMPIDIMP:
            choices = [i for i in ranked if _option_card_id(obs, i) == MARNIES_IMPIDIMP]
            if choices:
                return _ranked_with(ranked, choices), max(1, desired), "tempo_setup_bench_imp"
    return None


def _apply_early_search(obs, ranked: list[int], desired: int, max_ordinal: int = 2):
    state = obs.current
    ordinal = _own_turn_ordinal(state)
    if ordinal < 1 or ordinal > max_ordinal:
        return None
    select = obs.select
    me = state.players[state.yourIndex]
    hand = _hand_ids(me)
    board_ids = [int(card.id) for _, card in _board(me)]
    old_imps = _old_imp(me)

    if _effect_id(obs) == BUDDY_BUDDY_POFFIN and ordinal == 1 and _context_is(
        select, int(SelectContext.TO_BENCH), "TO_BENCH"
    ):
        by_id = {}
        for index in ranked:
            by_id.setdefault(_option_card_id(obs, index), []).append(index)
        wanted = []
        if MARNIES_IMPIDIMP not in board_ids and by_id.get(MARNIES_IMPIDIMP):
            wanted.append(by_id[MARNIES_IMPIDIMP].pop(0))
        if SNORUNT not in board_ids and by_id.get(SNORUNT):
            wanted.append(by_id[SNORUNT].pop(0))
        if by_id.get(MARNIES_IMPIDIMP):
            wanted.append(by_id[MARNIES_IMPIDIMP].pop(0))
        room = max(0, int(me.benchMax) - len(_cards(me, "bench")))
        count = min(int(select.maxCount), room, len(wanted))
        if count:
            return _ranked_with(ranked, wanted[:count]), max(int(select.minCount), count), "tempo_poffin_targets"

    if _effect_id(obs) == SPIKEMUTH_GYM and _context_is(select, int(SelectContext.TO_HAND), "TO_HAND"):
        target = None
        if ordinal >= 2 and old_imps and RARE_CANDY in hand and MARNIES_GRIMMSNARL_EX not in hand:
            target = MARNIES_GRIMMSNARL_EX
        elif ordinal == 1:
            if MARNIES_IMPIDIMP not in board_ids and len(_cards(me, "bench")) < int(me.benchMax):
                target = MARNIES_IMPIDIMP
            elif RARE_CANDY in hand and MARNIES_GRIMMSNARL_EX not in hand:
                target = MARNIES_GRIMMSNARL_EX
            elif MARNIES_MORGREM not in hand:
                target = MARNIES_MORGREM
            else:
                target = MARNIES_IMPIDIMP
        choices = [i for i in ranked if _option_card_id(obs, i) == target]
        if choices:
            return _ranked_with(ranked, choices), max(1, int(select.minCount)), "tempo_gym_search"

    if _effect_id(obs) == TEAM_ROCKETS_PETREL and ordinal >= 2 and _context_is(
        select, int(SelectContext.TO_HAND), "TO_HAND"
    ):
        target = None
        if old_imps and MARNIES_GRIMMSNARL_EX in hand and RARE_CANDY not in hand:
            target = RARE_CANDY
        elif old_imps and RARE_CANDY in hand and MARNIES_GRIMMSNARL_EX not in hand:
            target = SPIKEMUTH_GYM
        choices = [i for i in ranked if _option_card_id(obs, i) == target]
        if choices:
            return _ranked_with(ranked, choices), max(1, int(select.minCount)), "tempo_petrel_search"

    if _effect_id(obs) == RARE_CANDY and ordinal >= 2 and _context_is(
        select, int(SelectContext.EVOLVE), "EVOLVE"
    ):
        choices = []
        for index in ranked:
            option = select.option[index]
            target = option_target_pokemon(obs, option)
            source = option_source_card(obs, option)
            if (
                target is not None and source is not None
                and int(target.id) == MARNIES_IMPIDIMP
                and not bool(getattr(target, "appearThisTurn", False))
                and int(source.id) == MARNIES_GRIMMSNARL_EX
            ):
                choices.append((option.inPlayArea != AreaType.ACTIVE, int(option.inPlayIndex or 0), index))
        if choices:
            return _ranked_with(ranked, [min(choices)[-1]]), desired, "tempo_candy_target"

    if not _context_is(select, int(SelectContext.MAIN), "MAIN"):
        return None

    if ordinal >= 2 and old_imps:
        candy = RARE_CANDY in hand
        grim = MARNIES_GRIMMSNARL_EX in hand
        candy_play = _play_option(obs, RARE_CANDY)
        if candy and grim and candy_play is not None:
            return _ranked_with(ranked, [candy_play]), desired, "tempo_play_candy"
        if candy and not grim:
            gym_ability = _ability_option(obs, SPIKEMUTH_GYM)
            if gym_ability is not None:
                return _ranked_with(ranked, [gym_ability]), desired, "tempo_use_gym_for_grim"
            gym_play = _play_option(obs, SPIKEMUTH_GYM)
            if gym_play is not None and not bool(state.stadiumPlayed):
                return _ranked_with(ranked, [gym_play]), desired, "tempo_play_gym_for_grim"
            petrel = _play_option(obs, TEAM_ROCKETS_PETREL)
            if petrel is not None and not bool(state.supporterPlayed):
                return _ranked_with(ranked, [petrel]), desired, "tempo_petrel_for_gym"
        if grim and not candy:
            petrel = _play_option(obs, TEAM_ROCKETS_PETREL)
            if petrel is not None and not bool(state.supporterPlayed):
                return _ranked_with(ranked, [petrel]), desired, "tempo_petrel_for_candy"

    if ordinal >= 2 and not old_imps:
        morgrem = []
        for index in ranked:
            option = select.option[index]
            if int(option.type) != int(OptionType.EVOLVE):
                continue
            source = option_source_card(obs, option)
            target = option_target_pokemon(obs, option)
            if source is not None and target is not None and int(source.id) == MARNIES_MORGREM and int(target.id) == MARNIES_IMPIDIMP:
                morgrem.append(index)
        if morgrem:
            return _ranked_with(ranked, morgrem), desired, "tempo_take_morgrem"

    if ordinal == 1:
        needs_poffin = (
            len(_cards(me, "bench")) < int(me.benchMax)
            and (MARNIES_IMPIDIMP not in board_ids or SNORUNT not in board_ids or board_ids.count(MARNIES_IMPIDIMP) < 2)
        )
        poffin = _play_option(obs, BUDDY_BUDDY_POFFIN)
        if needs_poffin and poffin is not None:
            return _ranked_with(ranked, [poffin]), desired, "tempo_play_poffin"
        pad = _play_option(obs, POKE_PAD)
        if pad is not None:
            return _ranked_with(ranked, [pad]), desired, "tempo_play_pad_before_draw"
        gym_play = _play_option(obs, SPIKEMUTH_GYM)
        if gym_play is not None and not bool(state.stadiumPlayed):
            return _ranked_with(ranked, [gym_play]), desired, "tempo_play_gym"
        gym_ability = _ability_option(obs, SPIKEMUTH_GYM)
        if gym_ability is not None:
            return _ranked_with(ranked, [gym_ability]), desired, "tempo_use_gym"
        basics = []
        for card_id in (MARNIES_IMPIDIMP, SNORUNT, MUNKIDORI):
            if card_id in board_ids:
                continue
            option = _play_option(obs, card_id)
            if option is not None:
                basics.append(option)
        if basics:
            return _ranked_with(ranked, basics), desired, "tempo_bench_basic_before_draw"
        complete = (
            bool(_old_imp(me) or MARNIES_IMPIDIMP in board_ids)
            and RARE_CANDY in hand
            and MARNIES_GRIMMSNARL_EX in hand
        )
        lillie = _play_option(obs, LILLIES_DETERMINATION)
        if complete and lillie is not None and ranked and ranked[0] == lillie:
            alternatives = [i for i in ranked if i != lillie]
            if alternatives:
                return alternatives + [lillie], desired, "tempo_preserve_candy_package"
    return None


def _apply_attack_floor(obs, ranked: list[int], desired: int):
    """Prevent the observed repeated pass with a ready Shadow Bullet.

    This is intentionally narrower than an "always attack" rule: it only
    overrides END when the active Pokemon is Grimmsnarl ex and Shadow Bullet is
    explicitly legal.  It therefore covers the live Crustle and historical
    Bellibolt pass loops without changing ordinary development choices.
    """
    if not _context_is(obs.select, int(SelectContext.MAIN), "MAIN") or not ranked:
        return None
    me = obs.current.players[obs.current.yourIndex]
    active = _cards(me, "active")
    if not active or int(active[0].id) != MARNIES_GRIMMSNARL_EX:
        return None
    first = obs.select.option[ranked[0]]
    if int(first.type) != int(OptionType.END):
        return None
    attacks = [
        index for index in ranked
        if int(obs.select.option[index].type) == int(OptionType.ATTACK)
        and int(getattr(obs.select.option[index], "attackId", 0) or 0) == SHADOW_BULLET
    ]
    if not attacks:
        return None
    return _ranked_with(ranked, [attacks[0]]), 1, "floor_shadow_over_end"


def _fan_attach_key(obs, index: int):
    option = obs.select.option[index]
    target = option_target_pokemon(obs, option)
    if target is None:
        return None
    active = _option_active(option)
    card_id = int(target.id)
    energy = _energy_count(target)
    if active and card_id in GRIM_LINE:
        return (0, -energy, _option_slot(option), index)
    if not active and card_id == MARNIES_GRIMMSNARL_EX and _minimum_attack_deficit(target) == 0:
        return (1, -energy, _option_slot(option), index)
    if not active and card_id == MARNIES_MORGREM:
        return (2, -energy, _option_slot(option), index)
    if not active and card_id == MARNIES_IMPIDIMP:
        return (3, -energy, _option_slot(option), index)
    if not active and card_id == MARNIES_GRIMMSNARL_EX:
        return (4, -energy, _option_slot(option), index)
    if active and card_id == SNORUNT:
        return (5, -energy, _option_slot(option), index)
    if not active and card_id == SNORUNT:
        return (6, -energy, _option_slot(option), index)
    return None


def _energy_card_for_option(obs, index: int):
    option = obs.select.option[index]
    state = obs.current
    owner = int(option.playerIndex) if option.playerIndex is not None else 1 - state.yourIndex
    player = state.players[owner]
    area = player.active if option.area == AreaType.ACTIVE else player.bench if option.area == AreaType.BENCH else []
    if option.index is None or not 0 <= int(option.index) < len(area):
        return None
    pokemon = area[int(option.index)]
    cards = getattr(pokemon, "energyCards", None) or []
    if option.energyIndex is None or not 0 <= int(option.energyIndex) < len(cards):
        return None
    return cards[int(option.energyIndex)]


def _fan_energy_key(obs, index: int):
    card = _energy_card_for_option(obs, index)
    if card is None:
        return None
    card_id = int(card.id)
    data = card_table().get(card_id)
    energy_type = int(getattr(data, "energyType", EnergyType.COLORLESS))
    option = obs.select.option[index]
    opponent = obs.current.players[1 - obs.current.yourIndex]
    active = _cards(opponent, "active")
    disabled_damage = 0
    deficit_gain = 0
    if active:
        pokemon = active[0]
        metadata = card_table().get(int(pokemon.id))
        before = [int(value) for value in (pokemon.energies or [])]
        after = list(before)
        removals = max(1, int(getattr(option, "count", 1) or 1))
        for _ in range(removals):
            pos = next((i for i, value in enumerate(after) if value == energy_type), None)
            if pos is None:
                break
            after.pop(pos)
        if metadata is not None:
            before_ready = []
            after_ready = []
            gains = []
            for attack_id in metadata.attacks:
                attack = attack_table().get(attack_id)
                if attack is None:
                    continue
                left = _attack_deficit(before, attack.energies)
                right = _attack_deficit(after, attack.energies)
                if left == 0:
                    before_ready.append(int(attack.damage))
                if right == 0:
                    after_ready.append(int(attack.damage))
                gains.append(right - left)
            disabled_damage = max(before_ready or [0]) - max(after_ready or [0])
            deficit_gain = max(gains or [0])
    hard = 100 if card_id == 18 else 10 if card_id == 20 else 9 if card_id == 14 else 8 if card_id == 13 else 7 if card_id == 11 else 0
    return (-hard, -disabled_damage, -deficit_gain, card_id, index)


def _sink_tiers(public_ids: set[int]):
    if public_ids & set().union(*ALAKAZAM_SINK_TIERS):
        return ALAKAZAM_SINK_TIERS
    if public_ids & set().union(*LUCARIO_SINK_TIERS):
        return LUCARIO_SINK_TIERS
    if public_ids & set().union(*GRIM_SINK_TIERS):
        return GRIM_SINK_TIERS
    if public_ids & OGERPON_IDS:
        return (OGERPON_IDS,)
    return None


def _unknown_sink_key(obs, index: int, added_energy: int):
    target = _target_option(obs, index)
    if target is None:
        return None
    data = card_table().get(int(target.id))
    if data is None:
        return None
    prize = 3 if data.megaEx else 2 if data.ex else 1
    evolves = data.name in _evolves_from_names()
    before = _minimum_attack_deficit(target)
    after = _minimum_attack_deficit(target, added_energy)
    readiness_gain = max(0, before - after)
    max_damage = max((int(attack_table()[a].damage) for a in data.attacks if a in attack_table()), default=0)
    option = obs.select.option[index]
    return (prize, evolves, readiness_gain, max_damage, _option_slot(option), index)


def _apply_fan(obs, ranked: list[int], desired: int):
    select = obs.select
    if _context_is(select, int(SelectContext.MAIN), "MAIN"):
        fan_options = []
        for index, option in enumerate(select.option):
            if int(option.type) != int(OptionType.ATTACH):
                continue
            card = option_source_card(obs, option)
            if card is not None and int(card.id) == HANDHELD_FAN:
                fan_options.append(index)
        if fan_options:
            supported = [key for index in fan_options if (key := _fan_attach_key(obs, index)) is not None]
            if supported:
                preferred = min(supported)[-1]
                return _ranked_with(ranked, [preferred]), desired, "fan_attach"
            non_fan = [index for index in ranked if index not in fan_options]
            if non_fan:
                return non_fan + [index for index in ranked if index in fan_options], desired, "fan_retain_no_target"

    if _effect_id(obs) != HANDHELD_FAN:
        return None
    if _context_is(select, int(SelectContext.SWITCH_ENERGY), "SWITCH_ENERGY"):
        choices = [key for index in ranked if (key := _fan_energy_key(obs, index)) is not None]
        if choices:
            return _ranked_with(ranked, [min(choices)[-1]]), desired, "fan_energy"
    if _context_is(select, int(SelectContext.ATTACH_FROM), "ATTACH_FROM"):
        context_card = getattr(select, "contextCard", None)
        energy_data = card_table().get(int(getattr(context_card, "id", 0) or 0))
        if energy_data is None:
            return None
        public_ids = _public_opponent_ids(obs)
        tiers = _sink_tiers(public_ids)
        if tiers is not None:
            for tier in tiers:
                choices = [index for index in ranked if int(getattr(_target_option(obs, index), "id", 0) or 0) in tier]
                if choices:
                    return _ranked_with(ranked, choices), desired, "fan_sink_known"
        choices = [
            key for index in ranked
            if (key := _unknown_sink_key(obs, index, int(energy_data.energyType))) is not None
        ]
        if choices:
            return _ranked_with(ranked, [min(choices)[-1]]), desired, "fan_sink_unknown"
    return None


class Wave1Rail:
    """Mode-gated deterministic overlay with auditable intervention counts."""

    def __init__(self, mode: str = "off") -> None:
        mode = str(mode or "off").strip().lower()
        if mode not in {"off", "punk_only", "tempo", "fan", "floor"}:
            raise ValueError(f"unknown Wave-1 rail mode: {mode}")
        self.mode = mode
        self.counts: Counter[str] = Counter()
        self.last_intervention: str | None = None

    def apply(self, obs, ranked: list[int], desired: int):
        result = None
        if self.mode == "punk_only":
            result = _apply_punk_up(obs, ranked, desired)
        elif self.mode == "tempo":
            result = (
                _apply_setup(obs, ranked, desired)
                or _apply_punk_up(obs, ranked, desired)
                or _apply_munk_source(obs, ranked, desired)
                or _apply_early_search(obs, ranked, desired)
            )
        elif self.mode == "floor":
            result = (
                _apply_setup(obs, ranked, desired)
                or _apply_punk_up(obs, ranked, desired)
                or _apply_munk_source(obs, ranked, desired)
                or _apply_early_search(obs, ranked, desired, max_ordinal=3)
                or _apply_attack_floor(obs, ranked, desired)
            )
        elif self.mode == "fan":
            result = _apply_fan(obs, ranked, desired)
        if result is None:
            self.last_intervention = None
            return list(ranked), desired, None
        new_ranked, new_desired, reason = result
        self.last_intervention = reason
        self.counts[reason] += 1
        return new_ranked, new_desired, reason

    def apply_post_shield(self, obs, ranked: list[int], desired: int):
        """Apply invariants which must remain final after tactical shielding."""
        result = _apply_attack_floor(obs, ranked, desired) if self.mode == "floor" else None
        if result is None:
            return list(ranked), desired, None
        new_ranked, new_desired, reason = result
        self.last_intervention = reason
        self.counts[reason] += 1
        return new_ranked, new_desired, reason

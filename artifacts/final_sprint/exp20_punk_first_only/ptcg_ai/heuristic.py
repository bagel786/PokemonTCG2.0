"""Deck-aware deterministic baseline and neural-policy fallback."""

from __future__ import annotations

from collections import Counter

from cg.api import AreaType, CardType, OptionType, SelectContext

from . import card_ids as C
from .safety import sanitize_selection
from .view import (
    attached_energy_count,
    card_table,
    cards_in_play,
    damage_on,
    id_counts,
    option_source_card,
    option_target_pokemon,
    prize_value,
    resolve_area_card,
)


class GrimmsnarlHeuristic:
    """A safe first policy for the supplied Marnie's Grimmsnarl ex list."""

    def choose(self, obs) -> list[int]:
        select = obs.select
        scored = [(self.score(obs, option, i), i) for i, option in enumerate(select.option)]
        scored.sort(key=lambda pair: (pair[0], -pair[1]), reverse=True)
        ranked = [index for _, index in scored]

        # Optional selections should include only strategically positive choices. Required
        # selections are filled by sanitize_selection even when every score is negative.
        if select.minCount < select.maxCount:
            positive = [index for score, index in scored if score > 0]
            desired = max(select.minCount, min(select.maxCount, len(positive)))
        else:
            desired = select.maxCount
        return sanitize_selection(select, ranked, desired)

    def score(self, obs, option, option_index: int) -> float:
        context = obs.select.context
        if option.type == OptionType.NUMBER:
            return float(option.number or 0)
        if option.type == OptionType.YES:
            return self._yes_no_score(context, True)
        if option.type == OptionType.NO:
            return self._yes_no_score(context, False)
        if option.type == OptionType.CARD:
            return self._score_card(obs, option)
        if option.type in {OptionType.TOOL_CARD, OptionType.ENERGY_CARD, OptionType.ENERGY}:
            return self._score_attached_card(obs, option)
        if option.type == OptionType.PLAY:
            return self._score_play(obs, option)
        if option.type == OptionType.ATTACH:
            return self._score_attach(obs, option)
        if option.type == OptionType.EVOLVE:
            return self._score_evolve(obs, option)
        if option.type == OptionType.ABILITY:
            return self._score_ability(obs, option)
        if option.type == OptionType.DISCARD:
            return 50.0
        if option.type == OptionType.RETREAT:
            return self._score_retreat(obs)
        if option.type == OptionType.ATTACK:
            return self._score_attack(obs, option)
        if option.type == OptionType.END:
            return -10_000.0
        if option.type == OptionType.SKILL:
            return 100.0 + prize_value(self._pokemon_by_serial(obs, option.serial))
        if option.type == OptionType.SPECIAL_CONDITION:
            return -float(option.specialConditionType or 0)
        return -float(option_index)

    def _players(self, obs):
        state = obs.current
        me = state.players[state.yourIndex]
        opponent = state.players[1 - state.yourIndex]
        return me, opponent

    def _field_counts(self, player) -> Counter:
        return id_counts(cards_in_play(player))

    def _hand_counts(self, player) -> Counter:
        return id_counts(player.hand or [])

    def _yes_no_score(self, context, yes: bool) -> float:
        if context == SelectContext.IS_FIRST:
            return 100.0 if yes else 0.0
        if context == SelectContext.COIN_HEAD:
            return 100.0 if yes else 0.0
        if context in {SelectContext.ACTIVATE, SelectContext.FIRST_EFFECT}:
            return 50.0 if yes else 0.0
        if context == SelectContext.MULLIGAN:
            return 50.0 if yes else 0.0
        return 1.0 if yes else 0.0

    def _score_card(self, obs, option) -> float:
        card = option_source_card(obs, option)
        if card is None:
            return -1_000.0
        context = obs.select.context
        me, opponent = self._players(obs)
        mine = option.playerIndex == obs.current.yourIndex
        if context == SelectContext.SETUP_ACTIVE_POKEMON:
            return {
                C.MARNIES_IMPIDIMP: 500,
                C.MUNKIDORI: 350,
                C.SNORUNT: 200,
            }.get(card.id, 0)
        if context in {SelectContext.SETUP_BENCH_POKEMON, SelectContext.TO_BENCH, SelectContext.TO_FIELD}:
            counts = self._field_counts(me)
            return self._bench_priority(card.id, counts)
        if context in {SelectContext.SWITCH, SelectContext.TO_ACTIVE}:
            if mine:
                return self._active_priority(card)
            return self._target_priority(card)
        if context == SelectContext.TO_HAND:
            return self._take_to_hand_priority(card.id, me)
        if context in {SelectContext.DISCARD, SelectContext.TO_DECK, SelectContext.TO_DECK_BOTTOM}:
            return self._discard_priority(card.id, me)
        if context in {SelectContext.ATTACH_FROM, SelectContext.EVOLVES_FROM, SelectContext.EVOLVES_TO}:
            return self._active_priority(card)
        if context in {SelectContext.DAMAGE_COUNTER, SelectContext.DAMAGE_COUNTER_ANY, SelectContext.DAMAGE}:
            return self._target_priority(card) if not mine else -damage_on(card)
        if context in {SelectContext.REMOVE_DAMAGE_COUNTER, SelectContext.HEAL}:
            return damage_on(card) + 300 * prize_value(card)
        if context in {SelectContext.EFFECT_TARGET, SelectContext.TO_PRIZE}:
            return self._target_priority(card)
        return 10.0 + (5.0 if not mine else 0.0)

    def _bench_priority(self, card_id: int, counts: Counter) -> float:
        if card_id == C.MARNIES_IMPIDIMP:
            return 1_000 - 250 * counts[card_id]
        if card_id == C.MUNKIDORI:
            return 800 - 180 * counts[card_id]
        if card_id == C.SNORUNT:
            return 650 - 300 * counts[card_id]
        return 10.0

    def _active_priority(self, pokemon) -> float:
        energy = attached_energy_count(pokemon)
        hp = getattr(pokemon, "hp", 0)
        if pokemon.id == C.MARNIES_GRIMMSNARL_EX:
            return 4_000 + 500 * energy + hp
        if pokemon.id == C.MARNIES_MORGREM:
            return 1_500 + 250 * energy + hp
        if pokemon.id == C.MARNIES_IMPIDIMP:
            return 1_000 + 100 * energy + hp
        if pokemon.id == C.MUNKIDORI:
            return 400 + 100 * energy + hp
        return hp

    def _target_priority(self, pokemon) -> float:
        if pokemon is None:
            return -1_000.0
        damage = damage_on(pokemon)
        return 5_000 * prize_value(pokemon) + 15 * damage - pokemon.hp + 100 * len(pokemon.energies)

    def _take_to_hand_priority(self, card_id: int, me) -> float:
        hand = self._hand_counts(me)
        field = self._field_counts(me)
        base = {
            C.MARNIES_GRIMMSNARL_EX: 1_400 if field[C.MARNIES_MORGREM] or field[C.MARNIES_IMPIDIMP] else 200,
            C.MARNIES_MORGREM: 1_250 if field[C.MARNIES_IMPIDIMP] else 150,
            C.MARNIES_IMPIDIMP: 1_100 if not field[C.MARNIES_IMPIDIMP] else 450,
            C.RARE_CANDY: 1_200 if field[C.MARNIES_IMPIDIMP] else 200,
            C.DARK_ENERGY: 900,
            C.BOSS_ORDERS: 800,
            C.BUDDY_BUDDY_POFFIN: 750,
            C.POKE_PAD: 700,
            C.LILLIES_DETERMINATION: 650,
            C.TEAM_ROCKETS_PETREL: 600,
            C.SNORUNT: 500 if not field[C.SNORUNT] else 100,
            C.FROSLASS: 550 if field[C.SNORUNT] else 100,
            C.MUNKIDORI: 500 if field[C.MUNKIDORI] < 2 else 100,
        }.get(card_id, 250)
        return base - 180 * hand[card_id]

    def _discard_priority(self, card_id: int, me) -> float:
        hand = self._hand_counts(me)
        protected = {
            C.MARNIES_GRIMMSNARL_EX,
            C.MARNIES_MORGREM,
            C.RARE_CANDY,
            C.DARK_ENERGY,
        }
        score = 500 + 120 * max(0, hand[card_id] - 1)
        if card_id in protected:
            score -= 450
        if card_id in {C.TOOL_SCRAPPER, C.POKEGEAR_30, C.NIGHT_STRETCHER}:
            score += 150
        return score

    def _score_play(self, obs, option) -> float:
        card = option_source_card(obs, option)
        if card is None:
            return -2_000.0
        me, opponent = self._players(obs)
        counts = self._field_counts(me)
        data = card_table().get(card.id)
        if data is not None and data.cardType == CardType.POKEMON:
            return 80_000 + self._bench_priority(card.id, counts)
        priorities = {
            C.SPIKEMUTH_GYM: 70_000,
            C.BUDDY_BUDDY_POFFIN: 69_000 if len(me.bench) < me.benchMax else -1_000,
            C.POKE_PAD: 68_000,
            C.RARE_CANDY: 67_500 if counts[C.MARNIES_IMPIDIMP] else -500,
            C.NIGHT_STRETCHER: 66_000 if me.discard else -500,
            C.UNFAIR_STAMP: 65_500,
            C.TOOL_SCRAPPER: 65_000 if any(p.tools for p in cards_in_play(opponent)) else -500,
            C.POKEGEAR_30: 64_500,
            C.DAWN: 63_500,
            C.TEAM_ROCKETS_PETREL: 63_000,
            C.LILLIES_DETERMINATION: 62_000 if me.handCount <= 4 else 50_000,
            C.BOSS_ORDERS: 61_000 if opponent.bench else -500,
        }
        return priorities.get(card.id, 40_000)

    def _score_attach(self, obs, option) -> float:
        card = option_source_card(obs, option)
        target = option_target_pokemon(obs, option)
        if card is None or target is None:
            return -2_000.0
        energy = attached_energy_count(target)
        if card.id == C.DARK_ENERGY:
            if target.id == C.MARNIES_GRIMMSNARL_EX:
                return 95_000 + (2 - energy) * 1_000
            if target.id == C.MARNIES_MORGREM:
                return 94_000 + (2 - energy) * 1_000
            if target.id == C.MARNIES_IMPIDIMP:
                return 93_000 + (2 - energy) * 1_000
            if target.id == C.MUNKIDORI:
                return 91_000 if energy == 0 else 60_000
        return 50_000 - 500 * energy

    def _score_evolve(self, obs, option) -> float:
        card = option_source_card(obs, option)
        target = option_target_pokemon(obs, option)
        if card is None:
            return -2_000.0
        base = {
            C.MARNIES_GRIMMSNARL_EX: 120_000,
            C.MARNIES_MORGREM: 115_000,
            C.FROSLASS: 100_000,
        }.get(card.id, 90_000)
        return base + 100 * attached_energy_count(target)

    def _score_ability(self, obs, option) -> float:
        pokemon = option_source_card(obs, option)
        me, opponent = self._players(obs)
        if pokemon is None:
            return 105_000
        if pokemon.id == C.MUNKIDORI:
            movable = max((damage_on(p) for p in cards_in_play(me)), default=0)
            targetable = bool(cards_in_play(opponent))
            return 110_000 if movable and targetable else -1_000
        return 108_000

    def _score_retreat(self, obs) -> float:
        me, _ = self._players(obs)
        active = me.active[0] if me.active else None
        ready_grim = any(
            p.id == C.MARNIES_GRIMMSNARL_EX and attached_energy_count(p) >= 2 for p in me.bench
        )
        if ready_grim and (active is None or active.id != C.MARNIES_GRIMMSNARL_EX):
            return 90_000
        return -2_000

    def _score_attack(self, obs, option) -> float:
        me, opponent = self._players(obs)
        active = opponent.active[0] if opponent.active else None
        if option.attackId == C.SHADOW_BULLET:
            knockout = active is not None and active.hp <= 180
            return 20_000 + (30_000 if knockout else 0) + 5_000 * prize_value(active)
        if option.attackId == C.FILCH:
            return 3_000 if me.handCount <= 5 else 500
        if option.attackId in {C.MIND_BEND, C.MORGREM_CORKSCREW_PUNCH, C.FROST_SMASH}:
            return 8_000
        return 1_000

    def _score_attached_card(self, obs, option) -> float:
        card = option_source_card(obs, option)
        owner_is_opponent = option.playerIndex != obs.current.yourIndex
        if owner_is_opponent:
            return 1_000 + (200 if card is not None else 0)
        if card is not None and card.id == C.DARK_ENERGY:
            return -100
        return 100

    def _pokemon_by_serial(self, obs, serial):
        for player in obs.current.players:
            for pokemon in cards_in_play(player):
                if pokemon.serial == serial:
                    return pokemon
        return None


class GarchompHeuristic(GrimmsnarlHeuristic):
    """Deterministic fallback for the supplied Cynthia's Garchomp ex list."""

    def _score_card(self, obs, option) -> float:
        card = option_source_card(obs, option)
        if card is None:
            return -1_000.0
        context = obs.select.context
        me, _ = self._players(obs)
        mine = option.playerIndex == obs.current.yourIndex
        counts = self._field_counts(me)
        if context == SelectContext.SETUP_ACTIVE_POKEMON:
            return {
                C.CYNTHIAS_GIBLE: 500,
                C.CYNTHIAS_ROSELIA: 350,
                C.CYNTHIAS_SPIRITOMB: 250,
            }.get(card.id, 0)
        if context in {SelectContext.SETUP_BENCH_POKEMON, SelectContext.TO_BENCH, SelectContext.TO_FIELD}:
            return self._garchomp_bench_priority(card.id, counts)
        if context in {SelectContext.SWITCH, SelectContext.TO_ACTIVE, SelectContext.ATTACH_FROM}:
            return self._garchomp_active_priority(card) if mine else self._target_priority(card)
        if context == SelectContext.TO_HAND:
            return self._garchomp_take_priority(card.id, me)
        if context in {SelectContext.DISCARD, SelectContext.TO_DECK, SelectContext.TO_DECK_BOTTOM}:
            return self._garchomp_discard_priority(card.id, me)
        if context in {SelectContext.DAMAGE_COUNTER, SelectContext.DAMAGE_COUNTER_ANY, SelectContext.DAMAGE}:
            return self._target_priority(card) if not mine else -damage_on(card)
        if context in {SelectContext.REMOVE_DAMAGE_COUNTER, SelectContext.HEAL}:
            return damage_on(card) + 300 * prize_value(card)
        if context in {SelectContext.EFFECT_TARGET, SelectContext.TO_PRIZE}:
            return self._target_priority(card)
        return 10.0

    def _garchomp_bench_priority(self, card_id: int, counts: Counter) -> float:
        if card_id == C.CYNTHIAS_GIBLE:
            return 1_100 - 260 * counts[card_id]
        if card_id == C.CYNTHIAS_ROSELIA:
            return 850 - 240 * counts[card_id]
        if card_id == C.CYNTHIAS_SPIRITOMB:
            return 500 - 250 * counts[card_id]
        return 10

    def _garchomp_active_priority(self, pokemon) -> float:
        energy = attached_energy_count(pokemon)
        hp = getattr(pokemon, "hp", 0)
        if pokemon.id == C.CYNTHIAS_GARCHOMP_EX:
            return 5_000 + 700 * energy + hp
        if pokemon.id == C.CYNTHIAS_GABITE:
            return 1_800 + 250 * energy + hp
        if pokemon.id == C.CYNTHIAS_GIBLE:
            return 1_200 + 150 * energy + hp
        if pokemon.id == C.CYNTHIAS_SPIRITOMB:
            return 700 + hp
        return hp

    def _garchomp_take_priority(self, card_id: int, me) -> float:
        hand = self._hand_counts(me)
        field = self._field_counts(me)
        base = {
            C.CYNTHIAS_GARCHOMP_EX: 1_500 if field[C.CYNTHIAS_GABITE] else 300,
            C.CYNTHIAS_GABITE: 1_350 if field[C.CYNTHIAS_GIBLE] else 250,
            C.CYNTHIAS_GIBLE: 1_200 if field[C.CYNTHIAS_GIBLE] < 2 else 450,
            C.CYNTHIAS_ROSERADE: 1_050 if field[C.CYNTHIAS_ROSELIA] else 200,
            C.CYNTHIAS_ROSELIA: 900 if not field[C.CYNTHIAS_ROSELIA] else 350,
            C.FIGHTING_ENERGY: 1_000,
            C.ROCK_FIGHTING_ENERGY: 950,
            C.CYNTHIAS_POWER_WEIGHT: 850,
            C.BOSS_ORDERS: 800,
            C.FIGHTING_GONG: 780,
            C.BUDDY_BUDDY_POFFIN: 750,
            C.POKE_PAD: 700,
            C.HILDA: 680,
            C.LILLIES_DETERMINATION: 650,
        }.get(card_id, 250)
        return base - 180 * hand[card_id]

    def _garchomp_discard_priority(self, card_id: int, me) -> float:
        hand = self._hand_counts(me)
        protected = C.GARCHOMP_LINE | {C.FIGHTING_ENERGY, C.ROCK_FIGHTING_ENERGY, C.CYNTHIAS_POWER_WEIGHT}
        score = 500 + 120 * max(0, hand[card_id] - 1)
        if card_id in protected:
            score -= 450
        if card_id in {C.XEROSICS_MACHINATIONS, C.SURFER, C.NIGHT_STRETCHER}:
            score += 100
        return score

    def _score_play(self, obs, option) -> float:
        card = option_source_card(obs, option)
        if card is None:
            return -2_000.0
        me, opponent = self._players(obs)
        counts = self._field_counts(me)
        data = card_table().get(card.id)
        if data is not None and data.cardType == CardType.POKEMON:
            return 80_000 + self._garchomp_bench_priority(card.id, counts)
        priorities = {
            C.FOREST_OF_VITALITY: 71_000,
            C.BUDDY_BUDDY_POFFIN: 70_000 if len(me.bench) < me.benchMax else -1_000,
            C.FIGHTING_GONG: 69_000,
            C.POKE_PAD: 68_500,
            C.NIGHT_STRETCHER: 67_000 if me.discard else -500,
            C.UNFAIR_STAMP: 66_000,
            C.CYNTHIAS_POWER_WEIGHT: 65_000,
            C.HILDA: 64_000,
            C.LILLIES_DETERMINATION: 63_000 if me.handCount <= 4 else 51_000,
            C.SURFER: 62_500 if me.bench else -500,
            C.XEROSICS_MACHINATIONS: 62_000 if opponent.handCount > 3 else -500,
            C.BOSS_ORDERS: 61_000 if opponent.bench else -500,
        }
        return priorities.get(card.id, 40_000)

    def _score_attach(self, obs, option) -> float:
        card = option_source_card(obs, option)
        target = option_target_pokemon(obs, option)
        if card is None or target is None:
            return -2_000.0
        energy = attached_energy_count(target)
        if card.id in {C.FIGHTING_ENERGY, C.ROCK_FIGHTING_ENERGY}:
            if target.id == C.CYNTHIAS_GARCHOMP_EX:
                return 96_000 + (2 - energy) * 1_200
            if target.id == C.CYNTHIAS_GABITE:
                return 95_000 + (2 - energy) * 1_100
            if target.id == C.CYNTHIAS_GIBLE:
                return 94_000 + (2 - energy) * 1_000
            if target.id == C.CYNTHIAS_SPIRITOMB:
                return 80_000 if energy == 0 else 40_000
        if card.id == C.CYNTHIAS_POWER_WEIGHT:
            return 97_000 if target.id == C.CYNTHIAS_GARCHOMP_EX else 85_000
        return 50_000 - 500 * energy

    def _score_evolve(self, obs, option) -> float:
        card = option_source_card(obs, option)
        target = option_target_pokemon(obs, option)
        if card is None:
            return -2_000.0
        base = {
            C.CYNTHIAS_GARCHOMP_EX: 120_000,
            C.CYNTHIAS_GABITE: 116_000,
            C.CYNTHIAS_ROSERADE: 112_000,
        }.get(card.id, 90_000)
        return base + 100 * attached_energy_count(target)

    def _score_ability(self, obs, option) -> float:
        pokemon = option_source_card(obs, option)
        if pokemon is not None and pokemon.id == C.CYNTHIAS_GABITE:
            return 112_000
        return 108_000

    def _score_retreat(self, obs) -> float:
        me, _ = self._players(obs)
        active = me.active[0] if me.active else None
        ready = any(p.id == C.CYNTHIAS_GARCHOMP_EX and attached_energy_count(p) >= 1 for p in me.bench)
        if ready and (active is None or active.id != C.CYNTHIAS_GARCHOMP_EX):
            return 90_000
        return -2_000

    def _score_attack(self, obs, option) -> float:
        _, opponent = self._players(obs)
        active = opponent.active[0] if opponent.active else None
        roserade_count = sum(p.id == C.CYNTHIAS_ROSERADE for p in cards_in_play(self._players(obs)[0]))
        if option.attackId == C.DRACONIC_BUSTER:
            damage = 260 + 30 * roserade_count
            knockout = active is not None and active.hp <= damage
            final = active is not None and len(opponent.prize) <= prize_value(active)
            return 24_000 + (35_000 if knockout else 0) + (100_000 if final else 0)
        if option.attackId == C.CORKSCREW_DIVE:
            knockout = active is not None and active.hp <= 100 + 30 * roserade_count
            return 20_000 + (30_000 if knockout else 0)
        if option.attackId == C.RAGING_CURSE:
            return 12_000
        return 2_000

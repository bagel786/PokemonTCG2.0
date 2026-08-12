"""FESTIVAL-D0 deterministic stateful decision policy."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Iterable

from cg.api import AreaType, OptionType, SelectType, to_observation_class

from ptcg_ai.safety import emergency_selection, sanitize_selection

from .cards import (
    APPLIN_DRAGON,
    APPLIN_GRASS,
    BLACK_BELT,
    BOSS,
    BRAVE_BANGLE,
    BROCK,
    BUG_SET,
    DIPPLIN,
    DO_THE_WAVE,
    EXACT_DECK,
    FESTIVAL,
    GRASS_ENERGY,
    GROOKEY,
    HILDA,
    LILLIE,
    NIGHT_STRETCHER,
    POFFIN,
    POKE_PAD,
    QUICK_SIGN,
    SACRED_ASH,
    SHAYMIN,
    THWACKEY,
    UNFAIR_STAMP,
    VOLBEAT,
)
from .damage import DamageProjection, project_do_the_wave
from .plan import MacroPlan, Phase, build_macro_plan
from .resolvers import (
    PromptResolver,
    SelectionIntent,
    option_card_id,
    option_source,
    option_target,
)
from .snapshot import PlanMemory, PlanSnapshot, SemanticAction
from .telemetry import Telemetry


def _int(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return raw.strip().lower() not in {"", "0", "false", "no", "off"}


def _active(player: Any) -> Any | None:
    cards = list(getattr(player, "active", None) or []) if player is not None else []
    return cards[0] if cards and cards[0] is not None else None


def _players(obs: Any) -> tuple[Any | None, Any | None]:
    state = getattr(obs, "current", None)
    players = list(getattr(state, "players", None) or []) if state is not None else []
    hero_index = _int(getattr(state, "yourIndex", None), 0) if state is not None else 0
    hero = players[hero_index] if 0 <= hero_index < len(players) else None
    opponent_index = 1 - hero_index
    opponent = players[opponent_index] if 0 <= opponent_index < len(players) else None
    return hero, opponent


def _stadium_id(obs: Any) -> int | None:
    stadium = list(getattr(getattr(obs, "current", None), "stadium", None) or [])
    return _int(getattr(stadium[0], "id", None)) if stadium else None


def _energy_count(card: Any) -> int:
    return len(getattr(card, "energies", None) or []) if card is not None else 0


def _serial(card: Any) -> int:
    return _int(getattr(card, "serial", None))


def _card_id(card: Any) -> int:
    return _int(getattr(card, "id", None))


def _lineage(card: Any) -> int | None:
    if card is None:
        return None
    pre = list(getattr(card, "preEvolution", None) or [])
    value = _serial(pre[0]) if pre else _serial(card)
    return value if value >= 0 else None


_SUPPORTERS = frozenset({BOSS, BROCK, BLACK_BELT, HILDA, LILLIE})


def semantic_final_action(obs: Any, action: list[int], resolver: str, reason: str) -> SemanticAction:
    """Describe the final legal action without relying on its prompt index."""

    options = list(getattr(getattr(obs, "select", None), "option", None) or [])
    selected = [options[index] for index in action if 0 <= index < len(options)]
    if not selected:
        return SemanticAction(
            kind="SKIP",
            selected_indices=tuple(action),
            details=(("resolver", resolver), ("reason", reason)),
        )
    first = selected[0]
    option_type = _int(getattr(first, "type", None))
    source = option_source(obs, first)
    target = option_target(obs, first)
    hero, _ = _players(obs)
    active = _active(hero)
    attack_id = _int(getattr(first, "attackId", None))
    if option_type == int(OptionType.PLAY):
        kind = "PLAY_SUPPORTER" if _card_id(source) in _SUPPORTERS else "PLAY"
    elif option_type == int(OptionType.ATTACH):
        kind = "ENERGY_ATTACH" if _card_id(source) == GRASS_ENERGY else "ATTACH"
    elif option_type == int(OptionType.EVOLVE):
        kind = "EVOLVE"
    elif option_type == int(OptionType.ABILITY):
        kind = "THWACKEY_ABILITY" if _card_id(source) == THWACKEY else "ABILITY"
    elif option_type == int(OptionType.RETREAT):
        kind = "RETREAT"
    elif option_type == int(OptionType.ATTACK):
        kind = "SECOND_ATTACK" if resolver == "festival_second_attack" else "ATTACK"
        source = active
    elif option_type == int(OptionType.END):
        kind = "END"
    elif option_type == int(OptionType.CARD):
        kind = "SELECT_CARD"
    else:
        kind = f"OPTION_{option_type}"
    selected_ids = tuple(_card_id(option_source(obs, option)) for option in selected)
    return SemanticAction(
        kind=kind,
        card_id=_card_id(source) if source is not None else None,
        source_serial=_serial(source) if source is not None else None,
        source_lineage=_lineage(source),
        target_serial=_serial(target) if target is not None else None,
        target_lineage=_lineage(target),
        attack_id=attack_id if attack_id >= 0 else None,
        selected_indices=tuple(action),
        details=(
            ("resolver", resolver),
            ("reason", reason),
            ("selected_card_ids", ",".join(map(str, selected_ids))),
        ),
    )


@dataclass(frozen=True)
class PolicyProposal:
    intent: SelectionIntent
    plan: MacroPlan


class FestivalD0Planner:
    """Requirement-tier planner with no learned scalar or legacy policy prior."""

    def __init__(self, *, go_first: bool = True) -> None:
        self.go_first = bool(go_first)
        self.resolver = PromptResolver(go_first=self.go_first)

    def propose(self, obs: Any, snapshot: PlanSnapshot | None, memory: PlanMemory) -> PolicyProposal:
        plan = build_macro_plan(obs, memory)
        if _int(getattr(obs.select, "type", None)) == int(SelectType.MAIN):
            intent = self._main(obs, plan, memory)
        else:
            intent = self.resolver.resolve(obs, plan, memory)
        return PolicyProposal(intent=intent, plan=plan)

    @staticmethod
    def _option_indices(obs: Any, option_type: OptionType) -> list[int]:
        return [
            index
            for index, option in enumerate(obs.select.option)
            if _int(getattr(option, "type", None)) == int(option_type)
        ]

    @staticmethod
    def _first_intent(indices: Iterable[int], resolver: str, reason: str) -> SelectionIntent | None:
        ranked = tuple(indices)
        return SelectionIntent(ranked, 1, resolver, reason) if ranked else None

    def _play(self, obs: Any, card_id: int) -> list[int]:
        return [
            index
            for index in self._option_indices(obs, OptionType.PLAY)
            if option_card_id(obs, index) == card_id
        ]

    def _ability(self, obs: Any, card_id: int) -> list[int]:
        return [
            index
            for index in self._option_indices(obs, OptionType.ABILITY)
            if option_card_id(obs, index) == card_id
        ]

    def _attack(self, obs: Any, attack_id: int) -> list[int]:
        return [
            index
            for index in self._option_indices(obs, OptionType.ATTACK)
            if _int(getattr(obs.select.option[index], "attackId", None)) == attack_id
        ]

    def _evolutions(self, obs: Any, source_id: int, target_ids: set[int] | None = None) -> list[int]:
        result: list[int] = []
        for index in self._option_indices(obs, OptionType.EVOLVE):
            if option_card_id(obs, index) != source_id:
                continue
            target = option_target(obs, obs.select.option[index])
            if target_ids is None or _card_id(target) in target_ids:
                result.append(index)
        return result

    def _attachments(self, obs: Any, source_id: int, target_ids: set[int] | None = None) -> list[int]:
        result: list[int] = []
        for index in self._option_indices(obs, OptionType.ATTACH):
            if option_card_id(obs, index) != source_id:
                continue
            target = option_target(obs, obs.select.option[index])
            if target_ids is None or _card_id(target) in target_ids:
                result.append(index)
        return result

    def _useful_basic_plays(self, obs: Any, plan: MacroPlan) -> list[int]:
        hero, _ = _players(obs)
        in_play = [
            card
            for card in list(getattr(hero, "active", None) or []) + list(getattr(hero, "bench", None) or [])
            if card is not None
        ]
        applin_count = sum(_card_id(card) in {APPLIN_GRASS, APPLIN_DRAGON, DIPPLIN} for card in in_play)
        engine_count = sum(_card_id(card) in {GROOKEY, THWACKEY} for card in in_play)
        priorities: list[int] = []
        if applin_count < 2:
            priorities.extend((APPLIN_DRAGON, APPLIN_GRASS))
        if engine_count < 1:
            priorities.append(GROOKEY)
        if applin_count < 2:
            priorities.extend((APPLIN_DRAGON, APPLIN_GRASS))
        if engine_count < 2:
            priorities.append(GROOKEY)
        # Shaymin is the conditional fifth body once the attacker and engine
        # requirements above are satisfied; its Bench slot adds 20 to each
        # Festival hit.
        priorities.append(SHAYMIN)
        result: list[int] = []
        for card_id in priorities:
            for index in self._play(obs, card_id):
                if index not in result:
                    if card_id == GROOKEY and engine_count + sum(option_card_id(obs, i) == GROOKEY for i in result) >= 2:
                        continue
                    if card_id in {APPLIN_GRASS, APPLIN_DRAGON} and applin_count + sum(option_card_id(obs, i) in {APPLIN_GRASS, APPLIN_DRAGON} for i in result) >= 2:
                        continue
                    result.append(index)
                    break
        if 121 in set(plan.opponent_visible_ids) and plan.fragile_bench_count >= 2:
            result = [index for index in result if option_card_id(obs, index) not in {APPLIN_GRASS, APPLIN_DRAGON}]
        return result

    @staticmethod
    def _target_order(indices: Iterable[int], obs: Any, preferred_serials: Iterable[int]) -> list[int]:
        order = {int(serial): len(tuple(preferred_serials)) - index for index, serial in enumerate(tuple(preferred_serials))}
        return sorted(
            indices,
            key=lambda index: (order.get(_serial(option_target(obs, obs.select.option[index])), 0), -index),
            reverse=True,
        )

    def _projection(
        self,
        obs: Any,
        plan: MacroPlan,
        defender: Any | None = None,
        *,
        black_belt: bool | None = None,
        bench_delta: int = 0,
    ) -> DamageProjection:
        hero, opponent = _players(obs)
        attacker = _active(hero)
        target = defender if defender is not None else _active(opponent)
        used = bool(black_belt) if black_belt is not None else bool(plan.black_belt_used)
        return project_do_the_wave(
            attacker,
            target,
            bench_count=max(0, plan.bench_count + bench_delta),
            black_belt_used=used,
            stadium_id=_stadium_id(obs),
            festival_active=plan.festival_active,
        )

    @staticmethod
    def _outcome_key(projection: DamageProjection) -> tuple[int, int, int, int, int]:
        return (
            int(projection.ko) * projection.prize_value,
            int(projection.turn_ko) * projection.prize_value,
            projection.prize_value if projection.productive else 0,
            -int(projection.attacks_to_ko or 99),
            projection.final,
        )

    def _boss_improves(self, obs: Any, plan: MacroPlan) -> bool:
        if not self._play(obs, BOSS):
            return False
        _, opponent = _players(obs)
        current = _active(opponent)
        baseline = self._outcome_key(self._projection(obs, plan, current))
        return any(
            self._outcome_key(self._projection(obs, plan, card)) > baseline
            for card in (getattr(opponent, "bench", None) or [])
            if card is not None
        )

    def _modifier_crosses_threshold(self, obs: Any, plan: MacroPlan, card_id: int) -> bool:
        hero, opponent = _players(obs)
        attacker = _active(hero)
        target = _active(opponent)
        before = self._projection(obs, plan, target, black_belt=plan.black_belt_used)
        if card_id == BLACK_BELT:
            after = self._projection(obs, plan, target, black_belt=True)
        elif card_id == BRAVE_BANGLE:
            # Project a synthetic attached copy without mutating the observation.
            class AttackerView:
                pass

            synthetic = AttackerView()
            for name in ("id", "serial", "hp", "maxHp", "energies", "energyCards", "preEvolution"):
                setattr(synthetic, name, getattr(attacker, name, None))
            synthetic.tools = list(getattr(attacker, "tools", None) or []) + [type("Card", (), {"id": BRAVE_BANGLE})()]
            after = project_do_the_wave(
                synthetic,
                target,
                bench_count=plan.bench_count,
                black_belt_used=plan.black_belt_used,
                stadium_id=_stadium_id(obs),
                festival_active=plan.festival_active,
            )
        else:
            return False
        return (after.ko and not before.ko) or (after.turn_ko and not before.turn_ko)

    def _damage_expansion_needed(self, obs: Any, plan: MacroPlan) -> bool:
        if plan.bench_count >= 5:
            return False
        before = self._projection(obs, plan)
        after = self._projection(obs, plan, bench_delta=min(2, 5 - plan.bench_count))
        return (
            # Four is the audited expert attack floor: it reaches 80 per hit
            # while retaining one slot when search supplies only a single
            # useful body.  Three-benched attacks were the remaining broad
            # damage defect against both single- and multi-Prize decks.
            plan.bench_count < 4
            or (after.ko and not before.ko)
            or (after.turn_ko and not before.turn_ko)
        )

    @staticmethod
    def _actionable_prerequisites(plan: MacroPlan, hero: Any) -> tuple[str, ...]:
        missing = list(plan.missing_prerequisites)
        bench_full = len(getattr(hero, "bench", None) or []) >= int(getattr(hero, "benchMax", 5) or 5)
        if bench_full:
            missing = [item for item in missing if item != "replacement_applin"]
        return tuple(missing)

    def _main(self, obs: Any, plan: MacroPlan, memory: PlanMemory) -> SelectionIntent:
        hero, opponent = _players(obs)
        active = _active(hero)
        active_id = _card_id(active)
        ready_bench = [
            card
            for card in (getattr(hero, "bench", None) or [])
            if _card_id(card) == DIPPLIN and _energy_count(card) >= 1
        ]
        retreat = self._option_indices(obs, OptionType.RETREAT)
        if active_id not in {DIPPLIN, APPLIN_GRASS, APPLIN_DRAGON} and ready_bench and retreat:
            return SelectionIntent(tuple(retreat), 1, "retreat_to_attacker", "restore the Festival attack loop")
        do_wave_now = self._attack(obs, DO_THE_WAVE)
        if do_wave_now and not plan.festival_active:
            festival_now = self._play(obs, FESTIVAL)
            if festival_now:
                return SelectionIntent(tuple(festival_now), 1, "festival_for_attack", "unlock the second Festival strike")

        # Quick Sign is an opening search attack, but it ends the turn.  The
        # rank-34 replay corpus consistently takes every permanent setup action
        # first (Poffin/Pad/Bug Set, Basics, legal Evolutions) and attacks only
        # after the board is developed.  Merely having Quick Sign legal must not
        # suppress those actions.
        quick_sign = self._attack(obs, QUICK_SIGN)
        if active_id == VOLBEAT and plan.own_turn_ordinal == 1 and not quick_sign:
            energy = self._attachments(obs, GRASS_ENERGY, {VOLBEAT})
            if energy:
                return SelectionIntent(tuple(energy), 1, "quick_sign_energy", "enable turn-one Quick Sign")
            bug_set = self._play(obs, BUG_SET)
            if bug_set:
                return SelectionIntent(tuple(bug_set), 1, "quick_sign_bug_set", "look for the missing Grass Energy")

        # When moving second, Quick Sign is the first-turn development action:
        # it supplies up to two attacker Basics and ends the turn. Continuing
        # to fill the Bench with Poffin first could make Quick Sign illegal and
        # produced a dead turn in both represented archetypes. The starting
        # player retains the longer permanent-setup sequence below.
        if quick_sign and plan.own_turn_ordinal == 1 and plan.actual_order == "second":
            return SelectionIntent(tuple(quick_sign), 1, "quick_sign_attack", "preserve two Bench slots for the opening search attack")

        # Broad replay pattern 1: on the first hero turn, thin permanent setup
        # before attaching, then enable the Active Basic's legal attack.  The
        # previous tiers frequently ended with Energy still in hand whenever
        # the Active was an Applin rather than Volbeat.
        if plan.own_turn_ordinal == 1:
            basics = self._useful_basic_plays(obs, plan)
            if basics and len(getattr(hero, "bench", None) or []) < 5:
                return SelectionIntent(tuple(basics), 1, "opening_basic", "place attacker and engine lines before search")
            poffin = self._play(obs, POFFIN)
            if poffin and any(missing in plan.missing_prerequisites for missing in ("replacement_applin", "thwackey")):
                return SelectionIntent(tuple(poffin), 1, "opening_poffin", "fill the minimum attacker and engine board")
            poke_pad = self._play(obs, POKE_PAD)
            if poke_pad and any(missing in plan.missing_prerequisites for missing in ("active_dipplin", "replacement_applin", "replacement_dipplin", "thwackey")):
                return SelectionIntent(tuple(poke_pad), 1, "opening_poke_pad", "secure the missing evolution line")
            bug_set = self._play(obs, BUG_SET)
            if bug_set:
                return SelectionIntent(tuple(bug_set), 1, "opening_bug_set", "convert the free top-seven search before attachment")
            opening_energy = [
                index
                for index in self._attachments(
                    obs,
                    GRASS_ENERGY,
                    {VOLBEAT, APPLIN_DRAGON, APPLIN_GRASS, GROOKEY, SHAYMIN},
                )
                if _serial(option_target(obs, obs.select.option[index])) == _serial(active)
            ]
            if opening_energy:
                return SelectionIntent(tuple(opening_energy), 1, "opening_energy", "enable the Active Basic's opening attack")
            hand_count = _int(getattr(hero, "handCount", None), len(getattr(hero, "hand", None) or []))
            hilda = self._play(obs, HILDA)
            if hilda and plan.has_applin_line and DIPPLIN not in set(plan.known_hand_ids):
                return SelectionIntent(tuple(hilda), 1, "opening_hilda", "guarantee the first evolution and Energy pair")
            lillie = self._play(obs, LILLIE)
            if lillie and hand_count <= 4:
                return SelectionIntent(tuple(lillie), 1, "opening_lillie", "refresh a depleted opening hand after thinning")
            if hilda and plan.has_applin_line:
                return SelectionIntent(tuple(hilda), 1, "opening_hilda", "bank the first evolution and Energy pair")

        # Tier 1: escape a support Active when an attack-ready Dipplin waits.
        if active_id not in {DIPPLIN, APPLIN_GRASS, APPLIN_DRAGON} and ready_bench and retreat:
            return SelectionIntent(tuple(retreat), 1, "retreat_to_attacker", "restore the Festival attack loop")
        if active_id not in {DIPPLIN, APPLIN_GRASS, APPLIN_DRAGON} and ready_bench:
            retreat_cost = {VOLBEAT: 1, GROOKEY: 1, THWACKEY: 2, SHAYMIN: 1}.get(active_id, 99)
            trapped_energy = [
                index
                for index in self._attachments(obs, GRASS_ENERGY, {active_id})
                if _serial(option_target(obs, obs.select.option[index])) == _serial(active)
            ]
            if trapped_energy and _energy_count(active) + 1 >= retreat_cost:
                return SelectionIntent(
                    tuple(trapped_energy),
                    1,
                    "energy_for_complete_retreat",
                    "attach-retreat-attack line is complete this turn",
                )

        do_wave = self._attack(obs, DO_THE_WAVE)
        projection = self._projection(obs, plan) if do_wave else None
        productive_do_wave = bool(projection and projection.productive)

        if do_wave:
            # Tier 2: prerequisites and exact prize-route modifiers before a
            # legal attack.  These conditions are boolean requirements, not
            # additive bonuses.
            if not plan.festival_active:
                festival = self._play(obs, FESTIVAL)
                if festival:
                    return SelectionIntent(tuple(festival), 1, "festival_for_attack", "unlock the second Festival strike")

            # Boom Boom Groove is a once-per-turn deterministic card.  The old
            # policy attacked with a legal Do the Wave before establishing or
            # using the engine; in the audited pilot replays this is the single
            # largest attack-timing disagreement.  Establish a Bench Thwackey,
            # then exhaust the ability before committing to damage.
            thwackey_count = sum(
                _card_id(card) == THWACKEY
                for card in list(getattr(hero, "active", None) or []) + list(getattr(hero, "bench", None) or [])
                if card is not None
            )
            bench_thwackey = [
                index
                for index in self._evolutions(obs, THWACKEY, {GROOKEY})
                if _serial(option_target(obs, obs.select.option[index])) != _serial(active)
            ] if thwackey_count < 2 else []
            if bench_thwackey:
                return SelectionIntent(tuple(bench_thwackey), 1, "evolve_thwackey_before_attack", "establish tutor before ending the turn")
            if self._boss_improves(obs, plan):
                return SelectionIntent(tuple(self._play(obs, BOSS)), 1, "boss_prize_line", "strictly better completed-turn prizes")
            belt = self._play(obs, BLACK_BELT)
            if belt and self._modifier_crosses_threshold(obs, plan, BLACK_BELT):
                return SelectionIntent(tuple(belt), 1, "black_belt_threshold", "cross exact KO threshold")
            bangle = self._attachments(obs, BRAVE_BANGLE, {DIPPLIN})
            bangle = self._target_order(bangle, obs, (plan.current_attacker_serial or -1,))
            if bangle and self._modifier_crosses_threshold(obs, plan, BRAVE_BANGLE):
                return SelectionIntent(tuple(bangle), 1, "bangle_threshold", "cross exact KO threshold")
            # Bench development is itself damage for Do the Wave.  Only expand
            # when it establishes the minimum board or changes the prize route.
            if self._damage_expansion_needed(obs, plan):
                poffin = self._play(obs, POFFIN)
                if poffin:
                    return SelectionIntent(tuple(poffin), 1, "poffin_damage", "board width changes damage or replacement floor")
                basics = self._useful_basic_plays(obs, plan)
                if basics and len(getattr(hero, "bench", None) or []) < 5:
                    return SelectionIntent(tuple(basics), 1, "bench_for_damage", "one body adds 20 damage")

            # Secure the replacement using known pieces before any shuffle draw.
            replacement_evolve = self._evolutions(obs, DIPPLIN, {APPLIN_GRASS, APPLIN_DRAGON})
            replacement_evolve = self._target_order(
                replacement_evolve,
                obs,
                (plan.replacement_attacker_serial or -1,),
            )
            if replacement_evolve:
                return SelectionIntent(tuple(replacement_evolve), 1, "evolve_replacement", "attack loop survives the return KO")

            replacement_energy = [
                index
                for index in self._attachments(obs, GRASS_ENERGY, {DIPPLIN})
                if _serial(option_target(obs, obs.select.option[index])) != _serial(active)
                and _energy_count(option_target(obs, obs.select.option[index])) == 0
            ]
            replacement_energy = self._target_order(
                replacement_energy,
                obs,
                (plan.replacement_attacker_serial or -1,),
            )
            if replacement_energy:
                return SelectionIntent(tuple(replacement_energy), 1, "energy_replacement", "current attacker already complete")

            replacement_applin_energy = [
                index
                for index in self._attachments(obs, GRASS_ENERGY, {APPLIN_DRAGON, APPLIN_GRASS})
                if _serial(option_target(obs, obs.select.option[index])) != _serial(active)
                and _energy_count(option_target(obs, obs.select.option[index])) == 0
            ]
            replacement_applin_energy = self._target_order(
                replacement_applin_energy,
                obs,
                (plan.replacement_attacker_serial or -1,),
            )
            if replacement_applin_energy:
                return SelectionIntent(
                    tuple(replacement_applin_energy),
                    1,
                    "energy_replacement_applin",
                    "pre-load the replacement before evolution",
                )

            # Free Pokemon search and the two-card Hilda line are development,
            # not post-attack recovery.  The original D0 deferred them until no
            # attack existed, while the audited pilot used them before damage to
            # turn a brittle single attacker into a sustained prize chain.
            if not plan.replacement_attacker_ready or not plan.thwackey_serials:
                poke_pad = self._play(obs, POKE_PAD)
                if poke_pad:
                    return SelectionIntent(tuple(poke_pad), 1, "poke_pad_before_attack", "complete replacement or engine before attacking")
                bug_set = self._play(obs, BUG_SET)
                if bug_set:
                    return SelectionIntent(tuple(bug_set), 1, "bug_set_before_attack", "convert free search before attacking")
                hilda = self._play(obs, HILDA)
                if hilda and any(
                    missing in plan.missing_prerequisites
                    for missing in ("replacement_dipplin", "replacement_energy", "current_energy")
                ):
                    return SelectionIntent(tuple(hilda), 1, "hilda_before_attack", "secure evolution plus Energy replacement")

            # Shuffle/draw precedes Boom Boom Groove unless a known permanent
            # above was available.  This avoids tutoring a card then shuffling it.
            stamp = self._play(obs, UNFAIR_STAMP)
            if stamp:
                return SelectionIntent(tuple(stamp), 1, "unfair_stamp", "post-KO disruption before deterministic tutor")
            lillie = self._play(obs, LILLIE)
            hand_count = _int(getattr(hero, "handCount", None), len(getattr(hero, "hand", None) or []))
            if lillie and hand_count <= 4:
                return SelectionIntent(tuple(lillie), 1, "lillie_before_tutor", "refresh depleted hand before tutor")

            thwackey = self._ability(obs, THWACKEY)
            if thwackey:
                return SelectionIntent(tuple(thwackey), 1, "thwackey_before_attack", "exhaust deterministic tutor before attacking")

            if productive_do_wave:
                return SelectionIntent(tuple(do_wave), 1, "productive_do_the_wave", "attack outranks END")
            # A legal but nullified Do the Wave is not fired merely because it
            # exists.  Continue through recovery lines below.

        # Broad replay pattern 2: evolve all immediately usable attacker and
        # engine lines before spending the once-per-turn attachment.  This
        # preserves the choice of which newly evolved Dipplin should receive
        # Energy and creates the deterministic tutor before an attack ends the
        # turn.
        active_evolution = [
            index
            for index in self._evolutions(obs, DIPPLIN, {APPLIN_GRASS, APPLIN_DRAGON})
            if _serial(option_target(obs, obs.select.option[index])) == _serial(active)
        ]
        if active_evolution:
            return SelectionIntent(tuple(active_evolution), 1, "evolve_current_attacker", "first missing attack prerequisite")

        early_bench_evolution = self._evolutions(obs, DIPPLIN, {APPLIN_GRASS, APPLIN_DRAGON})
        early_bench_evolution = self._target_order(
            early_bench_evolution,
            obs,
            (plan.replacement_attacker_serial or -1,),
        )
        if early_bench_evolution:
            return SelectionIntent(tuple(early_bench_evolution), 1, "evolve_promotable_attacker", "establish every available prize-trading line")

        early_thwackey_count = sum(
            _card_id(card) == THWACKEY
            for card in list(getattr(hero, "active", None) or []) + list(getattr(hero, "bench", None) or [])
            if card is not None
        )
        early_thwackey = self._evolutions(obs, THWACKEY, {GROOKEY}) if early_thwackey_count < 2 else []
        if early_thwackey:
            return SelectionIntent(tuple(early_thwackey), 1, "evolve_thwackey", "establish deterministic engine before attachment")

        # Broad replay pattern 3: known Basics precede deck search, and free
        # search precedes Energy.  The predicates keep the board to attacker
        # and engine requirements instead of indiscriminately filling it.
        early_basics = self._useful_basic_plays(obs, plan)
        if early_basics and len(getattr(hero, "bench", None) or []) < 5:
            return SelectionIntent(tuple(early_basics), 1, "play_basic", "complete the minimum attacker and engine board")
        early_poffin = self._play(obs, POFFIN)
        if early_poffin and any(missing in plan.missing_prerequisites for missing in ("replacement_applin", "thwackey")):
            return SelectionIntent(tuple(early_poffin), 1, "poffin_setup", "fill a missing Basic attacker or engine line")
        early_pad = self._play(obs, POKE_PAD)
        if early_pad and any(missing in plan.missing_prerequisites for missing in ("active_dipplin", "replacement_applin", "replacement_dipplin", "thwackey")):
            return SelectionIntent(tuple(early_pad), 1, "poke_pad_setup", "fetch the exact missing non-rule Pokemon")
        early_bug_set = self._play(obs, BUG_SET)
        if early_bug_set:
            return SelectionIntent(tuple(early_bug_set), 1, "bug_set_setup", "use visible Grass resource search before attachment")

        festival_window = self._play(obs, FESTIVAL)
        if festival_window and not plan.festival_active and any(
            _card_id(card) == DIPPLIN
            for card in list(getattr(hero, "active", None) or []) + list(getattr(hero, "bench", None) or [])
            if card is not None
        ):
            return SelectionIntent(tuple(festival_window), 1, "festival_before_energy", "open the durable attack window before attachment")

        active_energy = [
            index
            for index in self._attachments(obs, GRASS_ENERGY, {DIPPLIN})
            if _serial(option_target(obs, obs.select.option[index])) == _serial(active)
            and _energy_count(active) == 0
        ]
        if active_energy:
            return SelectionIntent(tuple(active_energy), 1, "energy_current_attacker", "enable current-turn attack")

        # Pre-load an unevolved Active Applin when the evolution is not yet
        # available. The Energy survives evolution, enables Find a Friend or
        # Tumbling now, and leaves the following turn's attachment free for the
        # replacement. The prior Dipplin-only filter caused repeated dead turns
        # after promotion.
        active_applin_energy = [
            index
            for index in self._attachments(obs, GRASS_ENERGY, {APPLIN_DRAGON, APPLIN_GRASS})
            if _serial(option_target(obs, obs.select.option[index])) == _serial(active)
            and _energy_count(active) == 0
        ]
        if active_applin_energy:
            return SelectionIntent(tuple(active_applin_energy), 1, "energy_active_applin", "pre-load the current attacker before evolution")

        if active_id == DIPPLIN and _energy_count(active) >= 1 and not plan.festival_active:
            festival = self._play(obs, FESTIVAL)
            if festival:
                return SelectionIntent(tuple(festival), 1, "festival_near_attack", "durable attack window")

        # If the attacker is on the Bench but not ready, finish it before broad
        # setup.  Retreat is selected only after its complete line exists.
        bench_evolution = self._evolutions(obs, DIPPLIN, {APPLIN_GRASS, APPLIN_DRAGON})
        bench_evolution = self._target_order(
            bench_evolution,
            obs,
            (plan.replacement_attacker_serial or -1,),
        )
        if bench_evolution:
            return SelectionIntent(tuple(bench_evolution), 1, "evolve_promotable_attacker", "prepare escape from trapped Active")

        bench_energy = [
            index
            for index in self._attachments(obs, GRASS_ENERGY, {DIPPLIN})
            if _energy_count(option_target(obs, obs.select.option[index])) == 0
        ]
        bench_energy = self._target_order(
            bench_energy,
            obs,
            (plan.replacement_attacker_serial or -1,),
        )
        if bench_energy:
            return SelectionIntent(tuple(bench_energy), 1, "energy_promotable_attacker", "one-Energy Dipplin is complete")

        # Energy can be attached to Applin before it evolves. This is the
        # highest-impact replacement-development pattern in the expert audit:
        # after evolution the line is immediately attack-ready, instead of
        # consuming the next turn's attachment and losing a prize-race tempo.
        bench_applin_energy = [
            index
            for index in self._attachments(obs, GRASS_ENERGY, {APPLIN_DRAGON, APPLIN_GRASS})
            if _energy_count(option_target(obs, obs.select.option[index])) == 0
        ]
        bench_applin_energy = self._target_order(
            bench_applin_energy,
            obs,
            (plan.replacement_attacker_serial or -1,),
        )
        if bench_applin_energy:
            return SelectionIntent(tuple(bench_applin_energy), 1, "energy_replacement_applin", "pre-load the replacement before evolution")

        if ready_bench and retreat:
            return SelectionIntent(tuple(retreat), 1, "retreat_completed_line", "attach-retreat-attack line completed")

        # Tier 4: deterministic search/recovery by explicit missing component.
        hilda = self._play(obs, HILDA)
        has_applin_line = any(
            _card_id(card) in {APPLIN_GRASS, APPLIN_DRAGON, DIPPLIN}
            for card in list(getattr(hero, "active", None) or []) + list(getattr(hero, "bench", None) or [])
            if card is not None
        )
        if hilda and has_applin_line and any(
            missing in plan.missing_prerequisites
            for missing in ("active_dipplin", "current_energy", "replacement_dipplin", "replacement_energy")
        ):
            return SelectionIntent(tuple(hilda), 1, "hilda_prerequisites", "Evolution plus Energy line")

        poffin = self._play(obs, POFFIN)
        if poffin and any(missing in plan.missing_prerequisites for missing in ("replacement_applin", "thwackey")):
            return SelectionIntent(tuple(poffin), 1, "poffin_setup", "missing Basic attacker and engine lines")

        poke_pad = self._play(obs, POKE_PAD)
        if poke_pad and any(missing in plan.missing_prerequisites for missing in ("active_dipplin", "replacement_applin", "replacement_dipplin", "thwackey")):
            return SelectionIntent(tuple(poke_pad), 1, "poke_pad_setup", "exact missing non-rule Pokemon")

        bug_set = self._play(obs, BUG_SET)
        if bug_set:
            return SelectionIntent(tuple(bug_set), 1, "bug_set_setup", "visible Grass resource search")

        basics = self._useful_basic_plays(obs, plan)
        if basics and len(getattr(hero, "bench", None) or []) < 5:
            if basics:
                return SelectionIntent(tuple(basics), 1, "play_basic", "minimum functional board")

        thwackey_count = sum(
            _card_id(card) == THWACKEY
            for card in list(getattr(hero, "active", None) or []) + list(getattr(hero, "bench", None) or [])
            if card is not None
        )
        first_thwackey = self._evolutions(obs, THWACKEY, {GROOKEY}) if thwackey_count < 2 else []
        if first_thwackey:
            return SelectionIntent(tuple(first_thwackey), 1, "evolve_thwackey", "establish deterministic engine")

        stretcher = self._play(obs, NIGHT_STRETCHER)
        if stretcher and any(card_id in {DIPPLIN, APPLIN_GRASS, APPLIN_DRAGON, GRASS_ENERGY} for card_id in plan.known_discard_ids):
            return SelectionIntent(tuple(stretcher), 1, "night_stretcher", "recover immediate attack component")

        ash = self._play(obs, SACRED_ASH)
        discarded_core = sum(
            card_id in {DIPPLIN, APPLIN_GRASS, APPLIN_DRAGON, THWACKEY, GROOKEY}
            for card_id in plan.known_discard_ids
        )
        if ash and discarded_core >= 2:
            return SelectionIntent(tuple(ash), 1, "sacred_ash", "restore multiple searchable lines")

        brock = self._play(obs, BROCK)
        if brock and plan.phase in {Phase.OPENING_SETUP, Phase.RECOVER}:
            return SelectionIntent(tuple(brock), 1, "brock_setup", "two missing Basics or one critical Evolution")

        # Known permanent actions were exhausted.  Draw before Thwackey.
        stamp = self._play(obs, UNFAIR_STAMP)
        if stamp:
            return SelectionIntent(tuple(stamp), 1, "unfair_stamp_rebuild", "legal disruption and hand reset")
        lillie = self._play(obs, LILLIE)
        if lillie:
            return SelectionIntent(tuple(lillie), 1, "lillie_rebuild", "find missing attack pieces")

        thwackey = self._ability(obs, THWACKEY)
        if thwackey and self._actionable_prerequisites(plan, hero):
            return SelectionIntent(tuple(thwackey), 1, "thwackey_prerequisite", "fetch exact macro prerequisite")

        # Tier 5: any genuinely productive attack, then deterministic END.
        if productive_do_wave:
            return SelectionIntent(tuple(do_wave), 1, "productive_do_the_wave", "productive attack is mandatory")
        for attack_id in (QUICK_SIGN, 114, 37):
            attack = self._attack(obs, attack_id)
            if attack:
                return SelectionIntent(tuple(attack), 1, "fallback_attack", f"legal exact-deck attack {attack_id}")
        end = self._option_indices(obs, OptionType.END)
        if end:
            return SelectionIntent(tuple(end), 1, "end", "no productive legal line remains")
        return SelectionIntent(tuple(range(len(obs.select.option))), int(obs.select.minCount), "main_unknown", "mandatory fail-closed main option", False)


class DipplinCompetitionAgent:
    """Direct competition entrypoint shared by D0 and the optional D1 overlay."""

    def __init__(self, *, search_enabled: bool | None = None, go_first: bool | None = None) -> None:
        self.deck = tuple(EXACT_DECK)
        self.go_first = _bool_env("PTCG_DIPPLIN_GO_FIRST", True) if go_first is None else bool(go_first)
        self.search_enabled = _bool_env("PTCG_DIPPLIN_SEARCH", False) if search_enabled is None else bool(search_enabled)
        self.planner = FestivalD0Planner(go_first=self.go_first)
        self.memory = PlanMemory()
        self.telemetry = Telemetry()
        self.errors = 0
        self.route_telemetry: dict[str, float] = {}
        self._search = None
        self._first_productive_turn_recorded = False
        self._refresh_telemetry()

    def reset(self) -> None:
        self.memory.reset_game()
        self.telemetry.reset()
        self.errors = 0
        self._first_productive_turn_recorded = False
        if self._search is not None and hasattr(self._search, "reset"):
            self._search.reset()
        self._refresh_telemetry()

    def _refresh_telemetry(self) -> None:
        values = self.telemetry.snapshot()
        values["policy_errors"] = float(self.errors)
        values["search_enabled"] = float(self.search_enabled)
        self.route_telemetry = {
            str(key): float(value)
            for key, value in values.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }

    def _search_controller(self):
        if not self.search_enabled:
            return None
        if self._search is None:
            from .search import FestivalD1Search

            self._search = FestivalD1Search(self.planner, self.telemetry)
        return self._search

    def _record_decision(
        self,
        obs: Any,
        proposal: PolicyProposal,
        final: list[int],
    ) -> None:
        telemetry = self.telemetry
        resolver = proposal.intent.resolver
        selected_options = [obs.select.option[index] for index in final if 0 <= index < len(obs.select.option)]
        selected_card_ids = [option_card_id(obs, index) for index in final if 0 <= index < len(obs.select.option)]
        selected_attack_ids = [_int(getattr(option, "attackId", None)) for option in selected_options]
        took_do_wave = DO_THE_WAVE in selected_attack_ids
        telemetry.increment("decisions")
        telemetry.record_phase(proposal.plan.phase)
        if not proposal.intent.known_context:
            telemetry.increment("unknown_contexts")
            telemetry.increment("legal_fallbacks")
            select = obs.select
            effect = getattr(select, "effect", None)
            context_card = getattr(select, "contextCard", None)
            option_types = "_".join(
                str(value)
                for value in sorted(
                    {
                        _int(getattr(option, "type", None))
                        for option in (getattr(select, "option", None) or [])
                    }
                )
            ) or "none"
            telemetry.increment(
                "unknown_prompt_"
                f"t{_int(getattr(select, 'type', None))}_"
                f"c{_int(getattr(select, 'context', None))}_"
                f"e{_int(getattr(effect, 'id', None))}_"
                f"cc{_int(getattr(context_card, 'id', None))}_"
                f"o{option_types}"
            )
        if resolver == "is_first":
            selected = obs.select.option[final[0]] if final else None
            telemetry.record_go_first(
                selected is not None and _int(getattr(selected, "type", None)) == int(OptionType.YES)
            )
        if resolver == "setup_active" and final:
            telemetry.record_setup_active(option_card_id(obs, final[0]))
        if any(
            _int(getattr(option, "attackId", None)) == QUICK_SIGN
            for option in obs.select.option
        ):
            telemetry.increment("quick_sign_offered")
        if resolver == "quick_sign":
            telemetry.record_quick_sign([option_card_id(obs, index) for index in final])
        if resolver == "festival_for_attack" or resolver == "festival_near_attack" or FESTIVAL in selected_card_ids:
            telemetry.increment("festival_plays")
        if resolver == "lillie_before_tutor":
            telemetry.increment("lillie_before_tutor")
        if resolver == "thwackey" and final:
            telemetry.record_thwackey_tutor(option_card_id(obs, final[0]))
        if (resolver.startswith("energy_") or any(_int(getattr(option, "type", None)) == int(OptionType.ATTACH) and option_card_id(obs, index) == GRASS_ENERGY for index, option in zip(final, selected_options))) and final:
            target = option_target(obs, obs.select.option[final[0]])
            telemetry.record_energy_attachment(
                _card_id(target),
                current_attacker=_serial(target) == proposal.plan.current_attacker_serial,
                replacement_attacker=_serial(target) == proposal.plan.replacement_attacker_serial,
            )
        if resolver == "bangle_threshold" and final:
            target = option_target(obs, obs.select.option[final[0]])
            telemetry.record_bangle_target(_card_id(target))
        if resolver == "black_belt_threshold":
            telemetry.increment("black_belt_uses")
            telemetry.increment("black_belt_threshold_crossing_uses")
        if resolver == "boss_prize_line" or BOSS in selected_card_ids:
            telemetry.increment("boss_uses")
        if proposal.plan.productive_attack_legal:
            telemetry.increment("productive_attacks_offered")
        if resolver == "productive_do_the_wave" or took_do_wave:
            telemetry.increment("productive_attacks_taken")
            telemetry.increment("first_festival_attacks")
            telemetry.increment("festival_attack_windows")
            if proposal.plan.festival_active:
                telemetry.increment("festival_active_attack_windows")
            if proposal.plan.replacement_attacker_ready:
                telemetry.increment("replacement_attacker_ready_attack_windows")
            if not self._first_productive_turn_recorded:
                telemetry.increment("first_productive_attack_turn_count")
                telemetry.increment("first_productive_attack_turn_sum", proposal.plan.own_turn_ordinal)
                telemetry.increment("first_productive_attack_turn_max", proposal.plan.own_turn_ordinal)
                self._first_productive_turn_recorded = True
        if resolver == "prize" and self.memory.festival_attack_count == 1:
            telemetry.increment("first_attack_kos")
        if resolver == "end" and proposal.plan.own_turn_ordinal >= 3 and self.memory.festival_attack_count == 0:
            telemetry.increment("late_turns_no_productive_attack")
            if proposal.plan.replacement_attacker_ready:
                telemetry.increment("replacement_attacker_ready_end_turn")
        if proposal.plan.second_attack_offered:
            telemetry.increment("second_attacks_offered")
            if resolver == "festival_second_attack" and final:
                telemetry.increment("second_attacks_taken")
            else:
                telemetry.increment("second_attacks_missed")

    def __call__(self, raw: dict[str, Any]) -> list[int]:
        if not raw or raw.get("select") is None:
            self.reset()
            return list(self.deck)

        started = time.perf_counter()
        obs = None
        try:
            obs = to_observation_class(raw)
            working_memory = self.memory.clone()
            snapshot = PlanSnapshot.from_observation(obs, working_memory)
            proposal = self.planner.propose(obs, snapshot, working_memory)
            baseline = sanitize_selection(
                obs.select,
                list(proposal.intent.ranked_indices),
                proposal.intent.desired_count,
            )
            final = list(baseline)
            controller = self._search_controller()
            if controller is not None:
                final = controller.choose(raw, obs, snapshot, working_memory, proposal, baseline)
            # A D1 abstention must return the exact D0 list; sanitation only
            # occurs again when the override is genuinely different.
            if final != baseline:
                final = sanitize_selection(obs.select, list(final), len(final))
            # Promote the reconciled pre-action clone, then commit exactly the
            # one final D0/D1 action.  A rejected search proposal never pollutes
            # persistent history.
            self.memory = working_memory
            semantic = semantic_final_action(
                obs,
                final,
                proposal.intent.resolver,
                proposal.intent.reason,
            )
            decision_key = (
                int(snapshot.global_turn),
                int(snapshot.turn_action_count),
                int(snapshot.select.type),
                int(snapshot.select.context),
                snapshot.parent_serial,
            )
            self.memory.commit(semantic, decision_key=decision_key)
            self._record_decision(obs, proposal, final)
            return final
        except Exception:
            self.errors += 1
            self.telemetry.increment("policy_errors")
            if obs is not None and getattr(obs, "select", None) is not None:
                action = emergency_selection(obs.select)
                try:
                    reconciled = self.memory.clone()
                    snapshot = PlanSnapshot.from_observation(obs, reconciled)
                    self.memory = reconciled
                    self.memory.commit(
                        semantic_final_action(obs, action, "exception", "emergency"),
                        decision_key=(
                            snapshot.global_turn,
                            snapshot.turn_action_count,
                            snapshot.select.type,
                            snapshot.select.context,
                            snapshot.parent_serial,
                        ),
                    )
                except Exception:
                    pass
                return action
            return []
        finally:
            self.telemetry.record_latency((time.perf_counter() - started) * 1000.0)
            self._refresh_telemetry()


__all__ = ["DipplinCompetitionAgent", "FestivalD0Planner", "PolicyProposal"]

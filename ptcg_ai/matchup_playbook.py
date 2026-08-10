"""Public-information matchup router and conservative A2 semantic overlay.

The runtime keeps one broad A2 policy.  It never reads an opponent hand or deck;
classification is accumulated only from public Active, Bench, pre-evolution, and
discard identities.  All bonuses rerank currently legal options and the ordinary
sanitizer remains the final legality boundary.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from cg.api import AreaType, EnergyType, OptionType, SelectContext, to_observation_class

from .agent import CompetitionAgent
from .features import encode_observation
from .model import NumpyPolicyModel
from .safety import sanitize_selection
from .tactical_shield import ShieldTelemetry, apply_tactical_shield
from .view import attack_table, card_table


# Our deck and effects.
DARK_ENERGY = 7
FROSLASS = 104
MUNKIDORI = 112
IMPIDIMP = 646
MORGREM = 647
GRIMMSNARL = 648
SNORUNT = 860
RARE_CANDY = 1079
BUDDY_POFFIN = 1086
BOSS_ORDERS = 1182
SPIKEMUTH = 1259
SHADOW_BULLET = 937
GRIM_LINE = frozenset({IMPIDIMP, MORGREM, GRIMMSNARL})
SUPPORT = frozenset({MUNKIDORI, FROSLASS, SNORUNT})

# Opposing Stadiums whose removal has verified public mechanical value.
FESTIVAL_GROUNDS = 1245
JAMMING_TOWER = 1246
AREA_ZERO = 1250
BATTLE_CAGE = 1264


def _find(filename: str) -> Path:
    for candidate in (Path(filename), Path("/kaggle_simulations/agent") / filename):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(filename)


def _cards(player, zone: str) -> list:
    return [card for card in (getattr(player, zone, None) or []) if card is not None]


def _board(player) -> list:
    return _cards(player, "active") + _cards(player, "bench")


def _own_turn_ordinal(state) -> int:
    if state.firstPlayer not in (0, 1) or int(state.turn or 0) <= 0:
        return 0
    return ((int(state.turn) + 1) // 2 if state.yourIndex == state.firstPlayer
            else int(state.turn) // 2)


def _effect_id(obs) -> int:
    effect = getattr(obs.select, "effect", None)
    context = getattr(obs.select, "contextCard", None)
    return int(getattr(effect or context, "id", 0) or 0)


def _zone(obs, owner: int, area):
    state = obs.current
    if area == AreaType.LOOKING:
        return state.looking or []
    if area == AreaType.STADIUM:
        return state.stadium or []
    if area == AreaType.DECK:
        return obs.select.deck or []
    player = state.players[owner]
    return {
        AreaType.HAND: player.hand or [],
        AreaType.DISCARD: player.discard or [],
        AreaType.ACTIVE: player.active or [],
        AreaType.BENCH: player.bench or [],
        AreaType.PRIZE: player.prize or [],
    }.get(area, [])


def _at(zone, index):
    return zone[int(index)] if index is not None and 0 <= int(index) < len(zone) else None


def _option_source(obs, option):
    owner = obs.current.yourIndex if option.playerIndex is None else int(option.playerIndex)
    area = option.area
    if int(option.type) == int(OptionType.PLAY) and area is None:
        area = AreaType.HAND
        owner = obs.current.yourIndex
    return _at(_zone(obs, owner, area), option.index)


def _option_target(obs, option):
    if option.inPlayArea is None:
        return None
    owner = obs.current.yourIndex if option.playerIndex is None else int(option.playerIndex)
    return _at(_zone(obs, owner, option.inPlayArea), option.inPlayIndex)


def _selected_card(obs, option):
    return _option_target(obs, option) or _option_source(obs, option)


def _option_owner(obs, option) -> int:
    if option.playerIndex is not None:
        return int(option.playerIndex)
    return obs.current.yourIndex


def _energy_matches(attached: int, required: int) -> bool:
    return (
        required == int(EnergyType.COLORLESS)
        or attached == required
        or attached == int(EnergyType.RAINBOW)
        or (attached == int(EnergyType.TEAM_ROCKET) and required in {
            int(EnergyType.PSYCHIC), int(EnergyType.DARKNESS)
        })
    )


def _attack_deficit(pokemon) -> int:
    metadata = card_table().get(int(getattr(pokemon, "id", 0) or 0))
    if metadata is None or not metadata.attacks:
        return 99
    result = []
    for attack_id in metadata.attacks:
        attack = attack_table().get(attack_id)
        if attack is None:
            continue
        remaining = [int(value) for value in (getattr(pokemon, "energies", None) or [])]
        missing = 0
        for required in [int(value) for value in attack.energies]:
            match = next((i for i, energy in enumerate(remaining)
                          if _energy_matches(energy, required)), None)
            if match is None:
                missing += 1
            else:
                remaining.pop(match)
        result.append(missing)
    return min(result or [99])


def _ready(pokemon) -> bool:
    return pokemon is not None and _attack_deficit(pokemon) == 0


def _energy_count(pokemon) -> int:
    return len(getattr(pokemon, "energies", None) or []) if pokemon is not None else 0


def _prize_value(pokemon) -> int:
    data = card_table().get(int(getattr(pokemon, "id", 0) or 0))
    return 3 if data is not None and data.megaEx else 2 if data is not None and data.ex else 1


def _damage(pokemon) -> int:
    return max(0, int(getattr(pokemon, "maxHp", 0) or 0) - int(getattr(pokemon, "hp", 0) or 0))


def _public_ids(player) -> set[int]:
    result: set[int] = set()
    for pokemon in _board(player):
        result.add(int(pokemon.id))
        result.update(int(card.id) for card in (getattr(pokemon, "preEvolution", None) or []))
    result.update(int(card.id) for card in _cards(player, "discard"))
    return result


@dataclass(frozen=True)
class RouteSignature:
    main: frozenset[int]
    family: frozenset[int]
    weak: frozenset[int] = frozenset()


SIGNATURES: dict[str, RouteSignature] = {
    "grim": RouteSignature(frozenset({647, 648}), frozenset({646}), frozenset({104, 112, 860})),
    "alakazam": RouteSignature(frozenset({742, 743}), frozenset({741}), frozenset({66, 305})),
    "lopunny": RouteSignature(frozenset({849}), frozenset({848}), frozenset({66, 174, 305})),
    "dragapult": RouteSignature(frozenset({120, 121}), frozenset({119}), frozenset({112, 235})),
    "crustle": RouteSignature(frozenset({345}), frozenset({344}), frozenset({117, 756})),
    "ogerpon": RouteSignature(frozenset({96, 108, 184, 272}), frozenset({63, 978}), frozenset({756})),
    "lucario": RouteSignature(frozenset({678}), frozenset({673, 674, 675, 676, 677})),
    "dipplin": RouteSignature(frozenset({90, 93}), frozenset({89, 92})),
    "garchomp": RouteSignature(frozenset({342, 380, 381}), frozenset({341, 379, 387})),
    "mewtwo": RouteSignature(frozenset({401, 431}), frozenset({400, 434}), frozenset({414})),
    "bellibolt": RouteSignature(frozenset({269}), frozenset({265, 268, 270, 271})),
    "starmie": RouteSignature(frozenset({861, 1031}), frozenset({1030}), frozenset({117, 414, 666, 860})),
}


class PublicArchetypeRouter:
    """Sticky classifier over accumulated public Pokemon identities only."""

    def __init__(self, minimum: float = 0.55):
        self.minimum = float(minimum)
        self.reset()

    def reset(self) -> None:
        self.seen: set[int] = set()
        self.locked: str | None = None
        self.last_route = "unknown"
        self.last_confidence = 0.0
        self.last_scores: dict[str, float] = {}

    @staticmethod
    def _score(ids: set[int], signature: RouteSignature) -> float:
        main = len(ids & signature.main)
        family = len(ids & signature.family)
        weak = len(ids & signature.weak)
        if main:
            return min(1.0, 0.92 + 0.04 * (main - 1) + 0.02 * family)
        if family >= 2:
            return 0.84
        if family == 1 and weak:
            return 0.76
        if family == 1:
            return 0.68
        if weak >= 2:
            return 0.52
        if weak == 1:
            return 0.18
        return 0.0

    def update(self, obs) -> tuple[str, float]:
        opponent = obs.current.players[1 - obs.current.yourIndex]
        self.seen.update(_public_ids(opponent))
        scores = {name: self._score(self.seen, signature) for name, signature in SIGNATURES.items()}
        self.last_scores = scores
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        name, top = ranked[0]
        second = ranked[1][1]
        conflicting_main = [route for route, signature in SIGNATURES.items()
                            if route != self.locked and self.seen & signature.main]
        if self.locked is not None:
            if conflicting_main and scores[self.locked] < top:
                self.last_route, self.last_confidence = "unknown", 0.25
                return self.last_route, self.last_confidence
            self.last_route = self.locked
            self.last_confidence = max(0.85, scores.get(self.locked, 0.0))
            return self.last_route, self.last_confidence
        confidence = max(0.0, min(1.0, top - 0.5 * second))
        if top < self.minimum or confidence < self.minimum:
            self.last_route, self.last_confidence = "unknown", 0.0
            return self.last_route, self.last_confidence
        self.last_route, self.last_confidence = name, confidence
        if confidence >= 0.85:
            self.locked = name
        return self.last_route, self.last_confidence


@dataclass(frozen=True)
class MatchupPlan:
    route_name: str
    target_weights: dict[int, float]
    deny_stadiums: frozenset[int] = frozenset()
    support_bench_cap: int = 1
    narrow_bench: bool = False
    froslass_priority: float = 0.0
    munkidori_priority: float = 0.0
    preserve_morgrem: bool = False


PLANS: dict[str, MatchupPlan] = {
    "grim": MatchupPlan("grim", {648: 1.0, 647: .75, 646: .65, 112: .35, 104: .25}, support_bench_cap=2),
    "alakazam": MatchupPlan("alakazam", {743: 1.0, 742: .9, 741: .85, 66: .55, 305: .35}, support_bench_cap=1, narrow_bench=True),
    "lopunny": MatchupPlan("lopunny", {849: 1.0, 848: .75, 66: .5, 305: .35}, support_bench_cap=1, narrow_bench=True),
    "dragapult": MatchupPlan("dragapult", {121: 1.0, 120: .9, 119: .85, 235: .6, 112: .4}, frozenset({JAMMING_TOWER}), 1, True, .1, .1),
    "crustle": MatchupPlan("crustle", {345: 1.0, 344: .95, 756: .8, 117: .75}, frozenset({BATTLE_CAGE}), 2, False, .25, .1, False),
    "ogerpon": MatchupPlan("ogerpon", {96: 1.0, 272: .95, 63: .9, 756: .85, 108: .85, 184: .8, 978: .45}, frozenset({AREA_ZERO}), 2, False, .2, .25),
    "lucario": MatchupPlan("lucario", {678: 1.0, 677: .85, 674: .65, 673: .55, 675: .3, 676: .2}, support_bench_cap=1, narrow_bench=True),
    "dipplin": MatchupPlan("dipplin", {93: 1.0, 90: .95, 92: .85, 89: .75}, frozenset({FESTIVAL_GROUNDS}), 1, True, .1, .05, False),
    "garchomp": MatchupPlan("garchomp", {381: 1.0, 380: .9, 379: .85, 342: .75, 341: .55}, support_bench_cap=1),
    "mewtwo": MatchupPlan("mewtwo", {431: 1.0, 401: .75, 414: .7, 400: .55, 434: .45}, support_bench_cap=1),
    "bellibolt": MatchupPlan("bellibolt", {269: 1.0, 268: .8, 271: .65, 265: .45, 270: .4}, support_bench_cap=1, froslass_priority=.2),
    "starmie": MatchupPlan("starmie", {861: 1.0, 1031: .95, 860: .8, 1030: .75, 666: .5}, support_bench_cap=1, narrow_bench=True),
}


@dataclass
class PublicSummary:
    actual_second: bool
    own_turn: int
    route: str
    confidence: float
    stadium: int
    own_ids: list[int]
    opponent_ids: list[int]
    marnie_bodies: int
    support_bodies: int
    ready_attackers: int
    replacement_ready: bool
    active_ready: bool
    bench_width: int
    own_prizes: int
    opponent_prizes: int


def _summary(obs, router: PublicArchetypeRouter) -> PublicSummary:
    state = obs.current
    me = state.players[state.yourIndex]
    opponent = state.players[1 - state.yourIndex]
    route, confidence = router.update(obs)
    own = _board(me)
    opp = _board(opponent)
    active = _cards(me, "active")
    bench = _cards(me, "bench")
    ready = [pokemon for pokemon in own if int(pokemon.id) in GRIM_LINE and _ready(pokemon)]
    return PublicSummary(
        actual_second=state.firstPlayer in (0, 1) and state.yourIndex != state.firstPlayer,
        own_turn=_own_turn_ordinal(state), route=route, confidence=confidence,
        stadium=int(state.stadium[0].id) if state.stadium else 0,
        own_ids=[int(card.id) for card in own], opponent_ids=[int(card.id) for card in opp],
        marnie_bodies=sum(int(card.id) in GRIM_LINE for card in own),
        support_bodies=sum(int(card.id) in SUPPORT for card in own),
        ready_attackers=len(ready), replacement_ready=any(int(card.id) in GRIM_LINE and _ready(card) for card in bench),
        active_ready=bool(active and int(active[0].id) in GRIM_LINE and _ready(active[0])),
        bench_width=len(bench), own_prizes=len(me.prize or []), opponent_prizes=len(opponent.prize or []),
    )


def _add(bonuses: np.ndarray, reasons: list[list[str]], index: int, value: float, reason: str) -> None:
    if value:
        bonuses[index] += float(value)
        reasons[index].append(reason)


class MatchupPolicy:
    def __init__(self, config: dict):
        self.config = config
        self.model = NumpyPolicyModel(_find("policy_a2.npz"))
        self.router = PublicArchetypeRouter(float(config.get("router_minimum", .55)))
        self.shield_telemetry = ShieldTelemetry()
        self.telemetry: Counter[str] = Counter()
        self.last = {}

    def reset(self) -> None:
        self.router.reset()
        self.shield_telemetry = ShieldTelemetry()
        self.telemetry.clear()
        self.last = {}

    def _second_bonuses(self, obs, state: PublicSummary, bonuses, count_bonuses, reasons) -> None:
        if not state.actual_second:
            return
        scale = float(self.config.get("actual_second_scale", .5))
        surgical = bool(self.config.get("surgical", False))
        if scale <= 0:
            return
        me = obs.current.players[obs.current.yourIndex]
        old_imp = any(int(card.id) == IMPIDIMP and not bool(getattr(card, "appearThisTurn", False)) for card in _board(me))
        advancing = False
        for index, option in enumerate(obs.select.option):
            option_type = int(option.type)
            source = _option_source(obs, option)
            target = _option_target(obs, option)
            source_id = int(getattr(source, "id", 0) or 0)
            target_id = int(getattr(target, "id", 0) or 0)
            value = 0.0; reason = ""
            if option_type == int(OptionType.PLAY):
                if not surgical and source_id == BUDDY_POFFIN and state.own_turn <= 2 and state.marnie_bodies < 3:
                    value, reason, advancing = .55, "second:poffin", True
                elif not surgical and source_id == SPIKEMUTH and state.own_turn <= 3:
                    value, reason, advancing = .25, "second:spikemuth", True
                elif not surgical and source_id == IMPIDIMP:
                    value = .45 if state.marnie_bodies < 3 else -.55
                    reason = "second:impidimp_width"; advancing = advancing or value > 0
                elif source_id == RARE_CANDY and old_imp:
                    value, reason, advancing = .65, "second:rare_candy", True
                elif not surgical and source_id in SUPPORT and state.ready_attackers < 2:
                    value, reason = -.35, "second:delay_support"
            elif option_type == int(OptionType.EVOLVE):
                if source_id == GRIMMSNARL:
                    value, reason, advancing = .75, "second:first_grim", True
                elif not surgical and source_id == MORGREM:
                    value, reason, advancing = .4, "second:morgrem", True
            elif option_type == int(OptionType.ATTACH):
                if target_id in GRIM_LINE:
                    deficit = _attack_deficit(target)
                    value = .55 if deficit > 0 else .1
                    if target is not None and target not in _cards(me, "active") and state.active_ready:
                        value += .25
                    reason, advancing = "second:energy_to_attacker", True
                elif target_id in SUPPORT:
                    value, reason = -.7, "second:no_stranded_energy"
            if value:
                _add(bonuses, reasons, index, scale * value, reason)

        if not surgical and int(obs.select.context) == int(SelectContext.SETUP_BENCH_POKEMON):
            wanted = min(int(obs.select.maxCount), max(int(obs.select.minCount), 2))
            if 0 <= wanted < len(count_bonuses):
                count_bonuses[wanted] += scale * .3
            for index, option in enumerate(obs.select.option):
                card_id = int(getattr(_selected_card(obs, option), "id", 0) or 0)
                if card_id == IMPIDIMP:
                    _add(bonuses, reasons, index, scale * .5, "second:setup_impidimp")
                elif card_id in SUPPORT:
                    _add(bonuses, reasons, index, scale * -.15, "second:setup_support_delay")

        effect = _effect_id(obs)
        if effect in {SPIKEMUTH, BUDDY_POFFIN} and int(obs.select.context) in {
            int(SelectContext.TO_HAND), int(SelectContext.TO_BENCH), int(SelectContext.EVOLVE)
        }:
            for index, option in enumerate(obs.select.option):
                card_id = int(getattr(_selected_card(obs, option), "id", 0) or 0)
                if card_id in {IMPIDIMP, MORGREM, GRIMMSNARL, RARE_CANDY}:
                    _add(bonuses, reasons, index, scale * .35, "second:search_attacker_line")

        if effect == GRIMMSNARL:
            if int(obs.select.context) == int(SelectContext.ATTACH_TO):
                capacity = sum(max(0, 2 - _energy_count(card)) for card in _board(me) if int(card.id) in GRIM_LINE)
                wanted = min(5, int(obs.select.maxCount), capacity)
                if 0 <= wanted < len(count_bonuses):
                    count_bonuses[wanted] += scale * .45
            elif int(obs.select.context) == int(SelectContext.ATTACH_FROM):
                for index, option in enumerate(obs.select.option):
                    target = _selected_card(obs, option)
                    card_id = int(getattr(target, "id", 0) or 0)
                    if card_id in GRIM_LINE and _attack_deficit(target) > 0:
                        value = .55 + (.2 if target not in _cards(me, "active") else 0)
                        _add(bonuses, reasons, index, scale * value, "second:punk_up_continuity")

        if int(obs.select.context) in {int(SelectContext.SWITCH), int(SelectContext.TO_ACTIVE)}:
            for index, option in enumerate(obs.select.option):
                target = _selected_card(obs, option)
                card_id = int(getattr(target, "id", 0) or 0)
                if _option_owner(obs, option) == obs.current.yourIndex:
                    value = .7 if card_id in GRIM_LINE and _ready(target) else -.55 if card_id in SUPPORT else 0
                    _add(bonuses, reasons, index, scale * value, "second:promote_ready_attacker")

        if not surgical and int(obs.select.context) == int(SelectContext.MAIN) and state.own_turn <= 4 and advancing:
            for index, option in enumerate(obs.select.option):
                if int(option.type) == int(OptionType.END):
                    _add(bonuses, reasons, index, scale * -.5, "second:no_empty_development_turn")

    def _matchup_bonuses(self, obs, state: PublicSummary, bonuses, reasons) -> None:
        if state.route == "unknown" or state.route not in PLANS:
            return
        if state.route not in set(self.config.get("enabled_routes", PLANS)):
            return
        plan = PLANS[state.route]
        surgical = bool(self.config.get("surgical", False))
        order_multiplier = (float(self.config.get("matchup_second_multiplier", 1.0))
                            if state.actual_second else 1.0)
        scale = float(self.config.get("matchup_scale", .5)) * state.confidence * order_multiplier
        if scale <= 0:
            return
        me = obs.current.players[obs.current.yourIndex]
        opponent = obs.current.players[1 - obs.current.yourIndex]
        central_present = any(int(card.id) in plan.target_weights and plan.target_weights[int(card.id)] >= .8
                              for card in _board(opponent))

        for index, option in enumerate(obs.select.option):
            option_type = int(option.type)
            source = _option_source(obs, option)
            target = _selected_card(obs, option)
            source_id = int(getattr(source, "id", 0) or 0)
            target_id = int(getattr(target, "id", 0) or 0)

            if int(obs.select.context) == int(SelectContext.MAIN):
                if option_type == int(OptionType.PLAY) and source_id == SPIKEMUTH and state.stadium in plan.deny_stadiums:
                    _add(bonuses, reasons, index, scale * 1.2, f"{plan.route_name}:deny_stadium")
                if not surgical and option_type == int(OptionType.PLAY) and source_id == IMPIDIMP and state.marnie_bodies >= 3:
                    _add(bonuses, reasons, index, scale * -.55, f"{plan.route_name}:cap_marnie_width")
                if not surgical and option_type == int(OptionType.PLAY) and source_id in SUPPORT:
                    penalty = -.5 if state.support_bodies >= plan.support_bench_cap else 0.0
                    if plan.narrow_bench and state.bench_width >= 3:
                        penalty -= .35
                    if source_id == SNORUNT and plan.froslass_priority > 0 and state.ready_attackers >= 1 and state.stadium != BATTLE_CAGE:
                        penalty += plan.froslass_priority
                    if source_id == MUNKIDORI and plan.munkidori_priority > 0 and state.ready_attackers >= 1:
                        penalty += plan.munkidori_priority
                    _add(bonuses, reasons, index, scale * penalty, f"{plan.route_name}:support_discipline")
                if not surgical and option_type == int(OptionType.EVOLVE) and source_id == FROSLASS:
                    value = plan.froslass_priority if state.ready_attackers >= 1 and state.stadium != BATTLE_CAGE else -.2
                    _add(bonuses, reasons, index, scale * value, f"{plan.route_name}:froslass_timing")
                if not surgical and option_type == int(OptionType.PLAY) and source_id == BOSS_ORDERS and central_present:
                    _add(bonuses, reasons, index, scale * .18, f"{plan.route_name}:boss_access")

            owner = _option_owner(obs, option)
            if owner != 1 - obs.current.yourIndex or target is None:
                continue
            weight = plan.target_weights.get(target_id, 0.0)
            effect = _effect_id(obs)
            target_context = int(obs.select.context) in {
                int(SelectContext.SWITCH), int(SelectContext.EFFECT_TARGET),
                int(SelectContext.DAMAGE), int(SelectContext.DAMAGE_COUNTER),
                int(SelectContext.DAMAGE_COUNTER_ANY),
            }
            if not target_context:
                continue
            value = .65 * weight
            if central_present and _prize_value(target) == 1 and weight < .5:
                value -= .25
            if _energy_count(target) > 0:
                value += .08 * min(3, _energy_count(target))
            if _damage(target) > 0:
                value += .08
            metadata = card_table().get(target_id)
            target_benched = option.area == AreaType.BENCH or option.inPlayArea == AreaType.BENCH
            if effect == GRIMMSNARL and target_benched and metadata is not None and metadata.tera:
                value = -1.5
            if effect == MUNKIDORI and target_benched and state.stadium == BATTLE_CAGE:
                value = -1.5
            if effect == BOSS_ORDERS:
                value += .12 * (_prize_value(target) - 1)
            _add(bonuses, reasons, index, scale * value, f"{plan.route_name}:target_pressure")

    def choose(self, obs) -> list[int]:
        features = encode_observation(obs, self.model.feature_version)
        logits, count_logits, _ = self.model.predict(features)
        if len(logits) == 0:
            return []
        public = _summary(obs, self.router)
        bonuses = np.zeros_like(logits, dtype=np.float32)
        count_bonuses = np.zeros_like(count_logits, dtype=np.float32)
        reasons: list[list[str]] = [[] for _ in range(len(logits))]
        self._second_bonuses(obs, public, bonuses, count_bonuses, reasons)
        self._matchup_bonuses(obs, public, bonuses, reasons)
        base_ranked = np.argsort(-logits).astype(int).tolist()
        ranked = np.argsort(-(logits + bonuses)).astype(int).tolist()
        if obs.select.minCount == obs.select.maxCount:
            desired = int(obs.select.maxCount)
        else:
            minimum = int(obs.select.minCount)
            maximum = min(int(obs.select.maxCount), len(count_logits) - 1)
            desired = minimum + int(np.argmax((count_logits + count_bonuses)[minimum:maximum + 1]))
        before_shield = ranked[0] if ranked else -1
        ranked, desired, shield_reason = apply_tactical_shield(obs, ranked, desired)
        self.shield_telemetry.record(shield_reason)
        result = sanitize_selection(obs.select, ranked, desired)
        changed = bool(result and base_ranked and result[0] != base_ranked[0])
        self.telemetry["decisions"] += 1
        self.telemetry[f"route:{public.route}"] += 1
        self.telemetry["actual_second" if public.actual_second else "actual_first"] += 1
        if changed:
            self.telemetry["changed_top"] += 1
            self.telemetry[f"changed_route:{public.route}"] += 1
        if shield_reason:
            self.telemetry[f"shield:{shield_reason}"] += 1
        selected_reason = reasons[before_shield] if 0 <= before_shield < len(reasons) else []
        for reason in selected_reason:
            self.telemetry[f"selected:{reason}"] += 1
        self.last = {
            "route": public.route, "confidence": public.confidence,
            "actual_second": public.actual_second, "changed_top": changed,
            "selected_reasons": selected_reason, "shield": shield_reason,
        }
        return result


class MatchupPlaybookAgent:
    """Competition wrapper with exact-d842 fail-closed behavior."""

    def __init__(self):
        self.deck_path = _find("deck.csv")
        self.deck = [int(line) for line in self.deck_path.read_text().splitlines() if line.strip()]
        if len(self.deck) != 60:
            raise ValueError("deck must contain exactly 60 cards")
        self.config = json.loads(_find("matchup_config.json").read_text(encoding="utf-8"))
        self.policy = MatchupPolicy(self.config)
        self.exact = CompetitionAgent(self.deck_path, _find("policy_d842.npz"))
        self.errors = 0

    def __call__(self, obs_dict: dict) -> list[int]:
        if not obs_dict or obs_dict.get("select") is None:
            self.errors = 0
            self.exact.errors = 0
            self.policy.reset()
            return list(self.deck)
        obs = to_observation_class(obs_dict)
        if int(obs.select.context) == int(SelectContext.IS_FIRST):
            yes = [i for i, option in enumerate(obs.select.option) if int(option.type) == int(OptionType.YES)]
            if len(yes) == 1:
                return sanitize_selection(obs.select, yes, 1)
        try:
            return self.policy.choose(obs)
        except Exception:
            self.errors += 1
            return self.exact(obs_dict)

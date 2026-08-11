"""Persistent public-information strategic controller for Grimmsnarl.

The controller selects a phase and temporally extended objective at the start
of an own turn.  Full A2 ranks actions *inside* the objective-consistent set;
the tactical shield and ordinary sanitizer remain the final safety boundary.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum

import numpy as np
from cg.api import AreaType, OptionType, SelectContext, SelectType, to_observation_class

from .agent import CompetitionAgent
from .features import encode_observation
from .matchup_playbook import (
    AREA_ZERO,
    BATTLE_CAGE,
    BOSS_ORDERS,
    BUDDY_POFFIN,
    DARK_ENERGY,
    FESTIVAL_GROUNDS,
    FROSLASS,
    GRIMMSNARL,
    GRIM_LINE,
    IMPIDIMP,
    JAMMING_TOWER,
    MORGREM,
    MUNKIDORI,
    RARE_CANDY,
    SHADOW_BULLET,
    SNORUNT,
    SPIKEMUTH,
    SUPPORT,
    RouteSignature,
    SIGNATURES as V1_SIGNATURES,
    _attack_deficit,
    _board,
    _cards,
    _damage,
    _effect_id,
    _energy_count,
    _find,
    _option_owner,
    _option_source,
    _option_target,
    _own_turn_ordinal,
    _prize_value,
    _public_ids,
    _ready,
    _selected_card,
)
from .model import NumpyPolicyModel
from .prevention import attack_nullified
from .safety import sanitize_selection
from .tactical_shield import ShieldTelemetry, apply_tactical_shield
from .view import attack_table, card_table


class Phase(Enum):
    SETUP = "setup"
    STABILIZE = "stabilize"
    PRESSURE = "pressure"
    RECOVERY = "recovery"
    CLOSEOUT = "closeout"


class Objective(Enum):
    DEFAULT_A2 = "default_a2"
    CLOSEOUT_PRIZE_ROUTE = "closeout_prize_route"
    ESCAPE_DEAD_ACTIVE = "escape_dead_active"
    BUILD_FIRST_ATTACKER = "build_first_attacker"
    BUILD_REPLACEMENT_ATTACKER = "build_replacement_attacker"
    DENY_STADIUM_ENGINE = "deny_stadium_engine"
    DENY_EVOLUTION_ENGINE = "deny_evolution_engine"
    DENY_SUPPORT_ENGINE = "deny_support_engine"
    PRESSURE_PRIMARY_ATTACKER = "pressure_primary_attacker"
    CONVERT_DAMAGE_BREAKPOINT = "convert_damage_breakpoint"
    PRESERVE_ONE_PRIZE_ATTACKER = "preserve_one_prize_attacker"
    MANAGE_SPREAD_LIABILITY = "manage_spread_liability"
    MANAGE_HAND_SIZE = "manage_hand_size"


class Enforcement(Enum):
    HARD = "hard"
    COMMIT = "commit"
    PREFERENCE = "preference"


class RouteStatus(Enum):
    UNKNOWN = "unknown"
    PROVISIONAL = "provisional"
    HIGH_CONFIDENCE = "high_confidence"
    LOCKED = "locked"
    CONTRADICTED = "contradicted"


@dataclass
class TargetRef:
    serial: int | None
    card_id: int | None
    family_ids: tuple[int, ...]
    role: str
    last_zone: int | None
    last_damage: int
    last_energy: int


@dataclass
class GamePlanState:
    route: str
    route_confidence: float
    actual_second: bool
    phase: Phase
    objective: Objective
    enforcement: Enforcement
    selected_on_turn: int
    expires_after_turn: int
    target_serial: int | None = None
    target_card_id: int | None = None
    target_family: tuple[int, ...] = ()
    target_role: str | None = None
    objective_reason: str = ""
    subgoals: dict[str, bool] = field(default_factory=dict)
    last_action_semantic: dict | None = None
    objective_changes_this_turn: int = 0
    fallback_prompts_this_turn: int = 0
    target: TargetRef | None = None


@dataclass(frozen=True)
class PublicPokemon:
    card_id: int
    serial: int | None
    zone: int
    hp: int
    max_hp: int
    damage: int
    energy: int
    attack_deficit: int
    ready: bool
    prizes: int
    tera: bool
    support: bool


@dataclass
class PublicSummary:
    actual_order: str
    actual_second: bool
    own_turn_ordinal: int
    public_turn: int
    route: str
    route_confidence: float
    route_status: str
    own_active: PublicPokemon | None
    own_bench: list[PublicPokemon]
    opponent_active: PublicPokemon | None
    opponent_bench: list[PublicPokemon]
    ready_attacker_count: int
    ready_replacement_count: int
    minimum_attack_deficit: int
    first_grim_established: bool
    replacement_grim_established: bool
    marnie_line_body_count: int
    support_count: int
    morgrem_count: int
    grim_count: int
    own_hand_count: int
    opponent_hand_count: int
    own_deck_count: int
    opponent_deck_count: int
    own_prize_count: int
    opponent_prize_count: int
    current_stadium: int
    public_prevention_effects: tuple[int, ...]
    public_mobility_effects: tuple[int, ...]
    public_attack_restrictions: tuple[int, ...]
    publicly_ready_opponent_attackers: int
    public_max_known_current_attack_damage: int
    target_prize_values: dict[int, int]
    target_damage_breakpoints: dict[int, int]

    @property
    def own_ids(self) -> list[int]:
        return [p.card_id for p in ([self.own_active] if self.own_active else []) + self.own_bench]

    @property
    def opponent_ids(self) -> list[int]:
        return [p.card_id for p in ([self.opponent_active] if self.opponent_active else []) + self.opponent_bench]


@dataclass(frozen=True)
class StrategicRoute:
    primary: tuple[int, ...]
    evolution: tuple[int, ...] = ()
    support: tuple[int, ...] = ()
    deny_stadiums: tuple[int, ...] = ()
    useful_width: int = 3
    spread: bool = False
    hand_size: bool = False


# IDs are verified against freshstart/data/EN_Card_Data.csv.  In particular,
# Duraludon/Archaludon variants are 169/170, 190, 839/840, and 992.
ROUTES: dict[str, StrategicRoute] = {
    "grim": StrategicRoute((648,), (646, 647), (104, 112, 860), useful_width=3),
    "alakazam": StrategicRoute((743, 742), (741,), (66, 305), useful_width=2),
    "lopunny": StrategicRoute((849,), (848,), (66, 174, 305), useful_width=2),
    "dragapult": StrategicRoute((121, 120), (119,), (235, 112), (JAMMING_TOWER,), 2, True),
    "archaludon": StrategicRoute((190, 840, 170), (169, 839, 992), (57,), useful_width=3),
    "crustle": StrategicRoute((345,), (344,), (117, 756), (BATTLE_CAGE,), 2),
    "ogerpon": StrategicRoute((96, 272, 108, 184, 756), (), (63, 978), (AREA_ZERO,), 3),
    "kangaskhan_generic": StrategicRoute((756,), (), (), (), 3),
    "lucario": StrategicRoute((678,), (673, 674, 677), (675, 676), useful_width=3),
    "dipplin": StrategicRoute((93, 90), (89, 92), (), (FESTIVAL_GROUNDS,), 2),
    "garchomp": StrategicRoute((381, 380, 342), (341, 379), (387,), useful_width=3),
    "mewtwo": StrategicRoute((431, 401), (400, 434), (414,), useful_width=2),
    "bellibolt": StrategicRoute((269,), (265, 268, 270, 271), (), useful_width=3),
    "starmie": StrategicRoute((861, 1031), (860, 1030), (117, 414, 666), useful_width=2, spread=True, hand_size=True),
}


SIGNATURES = dict(V1_SIGNATURES)
SIGNATURES["archaludon"] = RouteSignature(
    frozenset({170, 190, 840}), frozenset({169, 839, 992}), frozenset({57})
)


class PublicStrategicRouter:
    """Public-only sticky router with provisional Kangaskhan refinement."""

    def __init__(self, minimum: float = .55):
        self.minimum = float(minimum)
        self.reset()

    def reset(self) -> None:
        self.seen: set[int] = set()
        self.locked: str | None = None
        self.last_route = "unknown"
        self.last_confidence = 0.0
        self.last_status = RouteStatus.UNKNOWN
        self.last_scores: dict[str, float] = {}

    @staticmethod
    def _score(ids: set[int], signature: RouteSignature) -> float:
        main, family, weak = (len(ids & values) for values in (signature.main, signature.family, signature.weak))
        if main:
            return min(1.0, .92 + .04 * (main - 1) + .02 * family)
        if family >= 2:
            return .84
        if family == 1 and weak:
            return .76
        if family == 1:
            return .68
        if weak >= 2:
            return .52
        if weak == 1:
            return .18
        return 0.0

    def update(self, obs) -> tuple[str, float, str]:
        opponent = obs.current.players[1 - obs.current.yourIndex]
        self.seen.update(_public_ids(opponent))
        scores = {name: self._score(self.seen, sig) for name, sig in SIGNATURES.items()}
        self.last_scores = scores

        # A specific route always refines the one-card provisional route.
        specific = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        name, top = specific[0]
        second = specific[1][1]
        if self.locked:
            contradictory = [route for route, sig in SIGNATURES.items()
                             if route != self.locked and self.seen & sig.main and scores[route] > scores[self.locked]]
            if contradictory:
                self.last_route, self.last_confidence = "unknown", .25
                self.last_status = RouteStatus.CONTRADICTED
                return self.last_route, self.last_confidence, self.last_status.value
            self.last_route = self.locked
            self.last_confidence = max(.85, scores.get(self.locked, 0.0))
            self.last_status = RouteStatus.LOCKED
            return self.last_route, self.last_confidence, self.last_status.value

        confidence = max(0.0, min(1.0, top - .5 * second))
        if top >= self.minimum and confidence >= self.minimum:
            self.last_route, self.last_confidence = name, confidence
            self.last_status = RouteStatus.HIGH_CONFIDENCE
            if confidence >= .85:
                self.locked = name
                self.last_status = RouteStatus.LOCKED
            return name, confidence, self.last_status.value

        if 756 in self.seen:
            self.last_route, self.last_confidence = "kangaskhan_generic", .62
            self.last_status = RouteStatus.PROVISIONAL
            return self.last_route, self.last_confidence, self.last_status.value

        self.last_route, self.last_confidence = "unknown", 0.0
        self.last_status = RouteStatus.UNKNOWN
        return self.last_route, self.last_confidence, self.last_status.value


def _serial(card) -> int | None:
    value = int(getattr(card, "serial", 0) or 0) if card is not None else 0
    return value or None


def _public_pokemon(card, zone: AreaType) -> PublicPokemon:
    metadata = card_table().get(int(card.id))
    hp = int(getattr(card, "hp", 0) or 0)
    maximum = int(getattr(card, "maxHp", 0) or (metadata.hp if metadata else hp) or 0)
    return PublicPokemon(
        card_id=int(card.id), serial=_serial(card), zone=int(zone), hp=hp, max_hp=maximum,
        damage=max(0, maximum - hp), energy=_energy_count(card), attack_deficit=_attack_deficit(card),
        ready=_ready(card), prizes=_prize_value(card), tera=bool(metadata and metadata.tera),
        support=int(card.id) in SUPPORT,
    )


def _max_known_damage(pokemon) -> int:
    if pokemon is None or not _ready(pokemon):
        return 0
    metadata = card_table().get(int(pokemon.id))
    return max((int(attack_table()[aid].damage or 0) for aid in (metadata.attacks if metadata else [])
                if aid in attack_table()), default=0)


def build_public_summary(obs, router: PublicStrategicRouter) -> PublicSummary:
    state = obs.current
    me, opponent = state.players[state.yourIndex], state.players[1 - state.yourIndex]
    route, confidence, status = router.update(obs)
    own_active_cards, opp_active_cards = _cards(me, "active"), _cards(opponent, "active")
    own_active = _public_pokemon(own_active_cards[0], AreaType.ACTIVE) if own_active_cards else None
    opponent_active = _public_pokemon(opp_active_cards[0], AreaType.ACTIVE) if opp_active_cards else None
    own_bench = [_public_pokemon(card, AreaType.BENCH) for card in _cards(me, "bench")]
    opp_bench = [_public_pokemon(card, AreaType.BENCH) for card in _cards(opponent, "bench")]
    own_all = ([own_active] if own_active else []) + own_bench
    opp_all = ([opponent_active] if opponent_active else []) + opp_bench
    ready_grim = [p for p in own_all if p.card_id == GRIMMSNARL and p.ready]
    ready_bench = [p for p in own_bench if p.card_id in GRIM_LINE and p.ready]
    actual_second = state.firstPlayer in (0, 1) and state.yourIndex != state.firstPlayer
    opp_raw = _board(opponent)
    prevention = tuple(sorted({p.card_id for p in opp_all if p.card_id in {345, 533, 840}} |
                              ({int(state.stadium[0].id)} if state.stadium and int(state.stadium[0].id) == BATTLE_CAGE else set())))
    mobility = tuple(sorted(p.card_id for p in opp_all if p.card_id in {63, 57}))
    restrictions = tuple(sorted(p.card_id for p in opp_all if p.card_id in {170, 269, 678, 849}))
    return PublicSummary(
        actual_order="second" if actual_second else "first", actual_second=actual_second,
        own_turn_ordinal=_own_turn_ordinal(state), public_turn=int(state.turn or 0),
        route=route, route_confidence=confidence, route_status=status,
        own_active=own_active, own_bench=own_bench, opponent_active=opponent_active, opponent_bench=opp_bench,
        ready_attacker_count=len(ready_grim), ready_replacement_count=len(ready_bench),
        minimum_attack_deficit=min((p.attack_deficit for p in own_all if p.card_id in GRIM_LINE), default=99),
        first_grim_established=any(p.card_id == GRIMMSNARL for p in own_all),
        replacement_grim_established=any(p.card_id in {MORGREM, GRIMMSNARL} for p in own_bench),
        marnie_line_body_count=sum(p.card_id in GRIM_LINE for p in own_all),
        support_count=sum(p.support for p in own_all), morgrem_count=sum(p.card_id == MORGREM for p in own_all),
        grim_count=sum(p.card_id == GRIMMSNARL for p in own_all), own_hand_count=len(me.hand or []),
        opponent_hand_count=len(opponent.hand or []), own_deck_count=int(getattr(me, "deckCount", 0) or 0),
        opponent_deck_count=int(getattr(opponent, "deckCount", 0) or 0), own_prize_count=len(me.prize or []),
        opponent_prize_count=len(opponent.prize or []), current_stadium=int(state.stadium[0].id) if state.stadium else 0,
        public_prevention_effects=prevention, public_mobility_effects=mobility,
        public_attack_restrictions=restrictions,
        publicly_ready_opponent_attackers=sum(_ready(p) for p in opp_raw),
        public_max_known_current_attack_damage=max((_max_known_damage(p) for p in opp_raw), default=0),
        target_prize_values={p.serial or -(i + 1): p.prizes for i, p in enumerate(opp_all)},
        target_damage_breakpoints={p.serial or -(i + 1): p.hp for i, p in enumerate(opp_all)},
    )


def _option_type(option) -> int:
    return int(getattr(option, "type", -1))


def _is_main(obs) -> bool:
    select_type = getattr(obs.select, "type", SelectType.MAIN)
    return int(obs.select.context) == int(SelectContext.MAIN) and int(select_type) == int(SelectType.MAIN)


def _has_option(obs, option_type: OptionType, source_id: int | None = None) -> bool:
    for option in obs.select.option:
        if _option_type(option) != int(option_type):
            continue
        if source_id is None or int(getattr(_option_source(obs, option), "id", 0) or 0) == source_id:
            return True
    return False


def _target_ref(pokemon: PublicPokemon, role: str, family: tuple[int, ...]) -> TargetRef:
    return TargetRef(pokemon.serial, pokemon.card_id, family, role, pokemon.zone, pokemon.damage, pokemon.energy)


class StrategicPolicy:
    """A2-backed option controller with persistent phase/objective state."""

    def __init__(self, config: dict, model=None):
        self.config = config
        self.model = model or NumpyPolicyModel(_find("policy_a2.npz"))
        self.router = PublicStrategicRouter(float(config.get("router_minimum", .55)))
        self.shield_telemetry = ShieldTelemetry()
        self.reset()

    def reset(self) -> None:
        self.router.reset()
        self.shield_telemetry = ShieldTelemetry()
        self.plan: GamePlanState | None = None
        self.telemetry: Counter[str] = Counter()
        self.objective_events: list[dict] = []
        self.turn_traces: list[dict] = []
        self.last: dict = {}

    def _phase(self, summary: PublicSummary) -> Phase:
        if summary.own_prize_count <= 2 and summary.ready_attacker_count:
            return Phase.CLOSEOUT
        if (summary.own_active is None or not summary.own_active.ready or summary.own_active.support) and summary.ready_replacement_count:
            return Phase.RECOVERY
        if not summary.first_grim_established or (summary.own_turn_ordinal <= 2 and summary.ready_attacker_count == 0):
            return Phase.SETUP
        if summary.ready_attacker_count == 0 or summary.ready_replacement_count == 0:
            return Phase.STABILIZE
        return Phase.PRESSURE

    def _opponent(self, summary: PublicSummary) -> list[PublicPokemon]:
        return ([summary.opponent_active] if summary.opponent_active else []) + summary.opponent_bench

    def _resolve_target(self, summary: PublicSummary, ref: TargetRef | None) -> PublicPokemon | None:
        if ref is None:
            return None
        public = self._opponent(summary)
        exact = next((p for p in public if ref.serial and p.serial == ref.serial), None)
        if exact:
            return exact
        family = [p for p in public if p.card_id in ref.family_ids]
        if family:
            return max(family, key=lambda p: (p.damage, p.energy, p.prizes))
        route = ROUTES.get(summary.route)
        role_ids = route.primary if route and ref.role in {"primary", "closeout"} else route.evolution if route else ()
        role = [p for p in public if p.card_id in role_ids]
        return max(role, key=lambda p: (p.damage, p.energy, p.prizes), default=None)

    def _attack_damage(self, obs, option, target: PublicPokemon | None) -> int:
        attack = attack_table().get(int(getattr(option, "attackId", 0) or 0))
        damage = int(getattr(attack, "damage", 0) or 0)
        if target and obs.current.players[obs.current.yourIndex].active:
            actor = obs.current.players[obs.current.yourIndex].active[0]
            actor_data, target_data = card_table().get(int(actor.id)), card_table().get(target.card_id)
            if actor_data and target_data and target_data.weakness == actor_data.energyType:
                damage *= 2
            if actor_data and target_data and target_data.resistance == actor_data.energyType:
                damage = max(0, damage - 30)
        return damage

    def _winning_attack(self, obs, summary: PublicSummary) -> int | None:
        target = summary.opponent_active
        if target is None or summary.own_prize_count > target.prizes:
            return None
        for index, option in enumerate(obs.select.option):
            if _option_type(option) == int(OptionType.ATTACK) and not attack_nullified(obs, option):
                if self._attack_damage(obs, option, target) >= target.hp:
                    return index
        return None

    def _pick_target(self, summary: PublicSummary, role: str) -> TargetRef | None:
        route = ROUTES.get(summary.route)
        if not route:
            return None
        candidates = self._opponent(summary)
        ids = route.primary if role in {"primary", "closeout"} else route.evolution if role == "evolution" else route.support
        eligible = [p for p in candidates if p.card_id in ids]
        if not eligible:
            return None
        target = max(eligible, key=lambda p: (p.damage * 3 + p.energy * 18 + p.prizes * 20 +
                                              (18 if summary.opponent_active and p.serial == summary.opponent_active.serial else 0)))
        family = tuple(dict.fromkeys(route.primary + route.evolution))
        return _target_ref(target, role, family)

    def _escape_verified(self, obs, summary: PublicSummary) -> bool:
        if not summary.ready_replacement_count or summary.own_active is None:
            return False
        if _has_option(obs, OptionType.RETREAT):
            return True
        return summary.own_active.attack_deficit == 1 and any(
            _option_type(option) == int(OptionType.ATTACH)
            and getattr(option, "inPlayArea", None) == AreaType.ACTIVE
            for option in obs.select.option
        )

    def _breakpoint_available(self, summary: PublicSummary) -> bool:
        return bool(
            summary.route == "ogerpon" and summary.opponent_active and summary.opponent_active.card_id == 96
            and 180 < summary.opponent_active.hp <= 210 and MUNKIDORI in summary.own_ids
            and summary.ready_attacker_count and any(p.damage >= 30 for p in ([summary.own_active] if summary.own_active else []) + summary.own_bench)
        )

    def _select_objective(self, obs, summary: PublicSummary) -> tuple[Objective, Enforcement, str, TargetRef | None, int]:
        phase = self._phase(summary)
        if self._winning_attack(obs, summary) is not None:
            target = _target_ref(summary.opponent_active, "closeout", (summary.opponent_active.card_id,))
            return Objective.CLOSEOUT_PRIZE_ROUTE, Enforcement.HARD, "public immediate winning attack", target, summary.own_turn_ordinal
        if phase == Phase.RECOVERY and self._escape_verified(obs, summary):
            return Objective.ESCAPE_DEAD_ACTIVE, Enforcement.HARD, "verified dead-Active escape sequence", None, summary.own_turn_ordinal
        route = ROUTES.get(summary.route)
        if route and summary.current_stadium in route.deny_stadiums and _has_option(obs, OptionType.PLAY, SPIKEMUTH):
            return Objective.DENY_STADIUM_ENGINE, Enforcement.COMMIT, "replace route-critical opposing Stadium", None, summary.own_turn_ordinal
        if summary.ready_attacker_count == 0:
            return Objective.BUILD_FIRST_ATTACKER, Enforcement.COMMIT, "no ready Grimmsnarl attacker", None, summary.own_turn_ordinal
        credible_threat = summary.publicly_ready_opponent_attackers > 0 or bool(summary.own_active and summary.own_active.damage)
        if summary.ready_replacement_count == 0 and credible_threat:
            return Objective.BUILD_REPLACEMENT_ATTACKER, Enforcement.COMMIT, "no ready replacement into public threat", None, summary.own_turn_ordinal
        if self._breakpoint_available(summary):
            target = _target_ref(summary.opponent_active, "primary", (96,))
            return Objective.CONVERT_DAMAGE_BREAKPOINT, Enforcement.COMMIT, "Munkidori 30 plus Shadow Bullet 180 reaches 210", target, summary.own_turn_ordinal
        evolution = self._pick_target(summary, "evolution")
        if evolution and (summary.opponent_active and evolution.serial == summary.opponent_active.serial or _has_option(obs, OptionType.PLAY, BOSS_ORDERS)):
            return Objective.DENY_EVOLUTION_ENGINE, Enforcement.COMMIT, "reachable route-critical pre-evolution", evolution, summary.own_turn_ordinal
        if route and route.hand_size and 861 in summary.opponent_ids and summary.own_active and summary.own_hand_count * 50 >= summary.own_active.hp:
            return Objective.MANAGE_HAND_SIZE, Enforcement.PREFERENCE, "public Mega Froslass hand-size lethal", None, summary.own_turn_ordinal
        primary = self._pick_target(summary, "primary")
        if primary:
            return Objective.PRESSURE_PRIMARY_ATTACKER, Enforcement.COMMIT, "damaged, Energy-loaded, or central primary attacker", primary, summary.own_turn_ordinal + 1
        support = self._pick_target(summary, "support")
        if support and summary.publicly_ready_opponent_attackers:
            return Objective.DENY_SUPPORT_ENGINE, Enforcement.PREFERENCE, "public support is enabling a ready attacker", support, summary.own_turn_ordinal
        if route and route.spread and any(p.hp <= 60 for p in summary.own_bench):
            return Objective.MANAGE_SPREAD_LIABILITY, Enforcement.PREFERENCE, "low-HP Bench liability in public spread route", None, summary.own_turn_ordinal
        # The one-Prize Morgrem hypotheses remain disabled unless explicitly certified.
        if bool(self.config.get("enable_one_prize_hypotheses", False)) and summary.route in {"crustle", "dipplin"} and summary.morgrem_count:
            return Objective.PRESERVE_ONE_PRIZE_ATTACKER, Enforcement.PREFERENCE, "certified route-specific one-Prize mapping", None, summary.own_turn_ordinal
        return Objective.DEFAULT_A2, Enforcement.PREFERENCE, "no visible strategic precondition", None, summary.own_turn_ordinal

    def _start_plan(self, obs, summary: PublicSummary, *, reason: str | None = None) -> None:
        objective, enforcement, why, target, expires = self._select_objective(obs, summary)
        if reason:
            why = f"{reason}; {why}"
        old = self.plan.objective.value if self.plan else None
        self.plan = GamePlanState(
            route=summary.route, route_confidence=summary.route_confidence, actual_second=summary.actual_second,
            phase=self._phase(summary), objective=objective, enforcement=enforcement,
            selected_on_turn=summary.own_turn_ordinal, expires_after_turn=expires,
            target_serial=target.serial if target else None, target_card_id=target.card_id if target else None,
            target_family=target.family_ids if target else (), target_role=target.role if target else None,
            objective_reason=why, target=target,
        )
        self.telemetry[f"objective:{objective.value}"] += 1
        self.telemetry[f"phase:{self.plan.phase.value}"] += 1
        self.telemetry[f"route_objective:{summary.route}:{objective.value}"] += 1
        self.objective_events.append({"turn": summary.own_turn_ordinal, "from": old, "to": objective.value,
                                      "reason": why, "target_serial": self.plan.target_serial})

    def _ensure_plan(self, obs, summary: PublicSummary) -> None:
        if self.plan is None:
            self._start_plan(obs, summary)
            self.turn_traces.append({"turn": summary.own_turn_ordinal, "route": summary.route, "decisions": []})
            return
        new_turn = summary.own_turn_ordinal != self.plan.selected_on_turn
        if new_turn:
            previous_turn = self.plan.selected_on_turn
            resolved = self._resolve_target(summary, self.plan.target)
            persistent = self.plan.objective in {Objective.PRESSURE_PRIMARY_ATTACKER, Objective.CLOSEOUT_PRIZE_ROUTE}
            if persistent and resolved and summary.own_turn_ordinal <= self.plan.expires_after_turn:
                self.plan.selected_on_turn = summary.own_turn_ordinal
                self.plan.phase = self._phase(summary)
                self.plan.route = summary.route
                self.plan.target = _target_ref(resolved, self.plan.target.role, self.plan.target.family_ids)
                self.plan.target_serial = resolved.serial
                self.plan.objective_changes_this_turn = 0
                self.plan.fallback_prompts_this_turn = 0
                self.telemetry["cross_turn_commitments"] += 1
            else:
                self._start_plan(obs, summary, reason=f"turn {previous_turn} objective expired or completed")
            self.turn_traces.append({"turn": summary.own_turn_ordinal, "route": summary.route, "decisions": []})
            return

        self.plan.route = summary.route
        self.plan.route_confidence = summary.route_confidence
        self.plan.phase = self._phase(summary)
        if _is_main(obs) and self._winning_attack(obs, summary) is not None and self.plan.objective != Objective.CLOSEOUT_PRIZE_ROUTE:
            self._start_plan(obs, summary, reason="immediate win interrupted prior objective")
            return
        if self.plan.target and self._resolve_target(summary, self.plan.target) is None:
            self.telemetry["termination:target_disappeared"] += 1
            self._start_plan(obs, summary, reason="target disappeared")
            return
        if self.plan.target:
            resolved = self._resolve_target(summary, self.plan.target)
            if resolved is not None:
                self.plan.target = _target_ref(resolved, self.plan.target.role, self.plan.target.family_ids)
                self.plan.target_serial = resolved.serial
                self.plan.target_card_id = resolved.card_id
        if not _is_main(obs):
            return
        completed = (
            self.plan.objective == Objective.BUILD_FIRST_ATTACKER and summary.ready_attacker_count > 0
            or self.plan.objective == Objective.BUILD_REPLACEMENT_ATTACKER and summary.ready_replacement_count > 0
            or self.plan.objective == Objective.DENY_STADIUM_ENGINE and summary.current_stadium == SPIKEMUTH
            or self.plan.objective == Objective.ESCAPE_DEAD_ACTIVE and bool(summary.own_active and summary.own_active.ready)
            or self.plan.objective == Objective.MANAGE_HAND_SIZE and summary.own_active is not None and summary.own_hand_count * 50 < summary.own_active.hp
        )
        if completed:
            self.telemetry["termination:milestone"] += 1
            self._start_plan(obs, summary, reason="objective milestone achieved")

    def _matches_target(self, card, plan: GamePlanState) -> bool:
        if card is None:
            return False
        serial = _serial(card)
        card_id = int(getattr(card, "id", 0) or 0)
        if plan.target_serial:
            return serial == plan.target_serial
        return card_id in plan.target_family

    def _mechanically_forbidden(self, obs, summary: PublicSummary, index: int) -> str | None:
        option = obs.select.option[index]
        option_type = _option_type(option)
        target = _selected_card(obs, option)
        target_id = int(getattr(target, "id", 0) or 0)
        if option_type == int(OptionType.ATTACK) and attack_nullified(obs, option):
            return "nullified_attack"
        target_benched = getattr(option, "area", None) == AreaType.BENCH or getattr(option, "inPlayArea", None) == AreaType.BENCH
        metadata = card_table().get(target_id)
        if _effect_id(obs) == GRIMMSNARL and target_benched and metadata and metadata.tera:
            return "protected_tera_bench"
        if _effect_id(obs) == MUNKIDORI and target_benched and summary.current_stadium == BATTLE_CAGE:
            return "battle_cage_counter_prevention"
        target_own_support = (_option_owner(obs, option) == obs.current.yourIndex and target_id in SUPPORT)
        if self.plan and self.plan.objective != Objective.ESCAPE_DEAD_ACTIVE and target_own_support:
            if option_type == int(OptionType.ATTACH) or int(obs.select.context) == int(SelectContext.ATTACH_FROM):
                own = ([summary.own_active] if summary.own_active else []) + summary.own_bench
                munkidori_enabled = target_id == MUNKIDORI and summary.ready_attacker_count > 0 and any(p.damage >= 10 for p in own)
                if not munkidori_enabled:
                    return "stranded_energy_on_support"
        return None

    def _development_action(self, obs, summary: PublicSummary, index: int, replacement: bool) -> bool:
        option = obs.select.option[index]
        kind = _option_type(option)
        source, target = _option_source(obs, option), _option_target(obs, option)
        source_id, target_id = int(getattr(source, "id", 0) or 0), int(getattr(target, "id", 0) or 0)
        if kind == int(OptionType.PLAY):
            if source_id == RARE_CANDY:
                return True
            route = ROUTES.get(summary.route)
            width = route.useful_width if route else (3 if summary.actual_second else 2)
            if source_id == IMPIDIMP:
                return summary.own_turn_ordinal <= 3 and summary.marnie_line_body_count < width
            if source_id == BUDDY_POFFIN:
                return summary.own_turn_ordinal <= 2 and summary.marnie_line_body_count < min(2, width)
            return False
        if kind == int(OptionType.EVOLVE):
            if source_id not in {MORGREM, GRIMMSNARL}:
                return False
            return not replacement or getattr(option, "inPlayArea", None) == AreaType.BENCH
        if kind == int(OptionType.ATTACH) and target_id in GRIM_LINE and target is not None:
            return _attack_deficit(target) > 0 and (not replacement or getattr(option, "inPlayArea", None) == AreaType.BENCH)
        if kind == int(OptionType.ABILITY) and source_id == GRIMMSNARL:
            return True
        return False

    def _classify(self, obs, summary: PublicSummary, index: int, development_available: bool) -> tuple[str, str]:
        plan = self.plan
        assert plan is not None
        option = obs.select.option[index]
        kind = _option_type(option)
        context = int(obs.select.context)
        source, target, selected = _option_source(obs, option), _option_target(obs, option), _selected_card(obs, option)
        source_id = int(getattr(source, "id", 0) or 0)
        target_id = int(getattr(target, "id", 0) or 0)
        selected_id = int(getattr(selected, "id", 0) or 0)

        if self._mechanically_forbidden(obs, summary, index):
            return "forbidden", self._mechanically_forbidden(obs, summary, index) or "forbidden"

        objective = plan.objective
        if objective == Objective.DEFAULT_A2:
            return "neutral", "a2"
        if objective == Objective.CLOSEOUT_PRIZE_ROUTE:
            if index == self._winning_attack(obs, summary):
                return "advancing", "immediate_win"
            if kind == int(OptionType.PLAY) and source_id == BOSS_ORDERS:
                return "advancing", "boss_closeout_target"
        if objective == Objective.ESCAPE_DEAD_ACTIVE:
            if kind == int(OptionType.RETREAT):
                return "advancing", "escape_retreat"
            if kind == int(OptionType.ATTACH) and getattr(option, "inPlayArea", None) == AreaType.ACTIVE:
                return "advancing", "escape_attach_active"
            if context in {int(SelectContext.TO_ACTIVE), int(SelectContext.SWITCH)} and selected_id in GRIM_LINE and _ready(selected):
                return "advancing", "escape_promote_ready"
            if kind == int(OptionType.ATTACK) and summary.own_active and summary.own_active.ready:
                return "advancing", "escape_attack"
            if kind in {int(OptionType.END), int(OptionType.ATTACK)}:
                return "contradicting", "escape_incomplete"
        if objective in {Objective.BUILD_FIRST_ATTACKER, Objective.BUILD_REPLACEMENT_ATTACKER}:
            replacement = objective == Objective.BUILD_REPLACEMENT_ATTACKER
            if self._development_action(obs, summary, index, replacement):
                return "advancing", "build_replacement" if replacement else "build_first"
            if context in {int(SelectContext.TO_HAND), int(SelectContext.TO_BENCH), int(SelectContext.EVOLVE), int(SelectContext.EVOLVES_TO)}:
                if selected_id in {IMPIDIMP, MORGREM, GRIMMSNARL, RARE_CANDY, DARK_ENERGY}:
                    return "advancing", "search_attacker_line"
                if selected_id in SUPPORT:
                    return "contradicting", "delay_optional_support"
            if context == int(SelectContext.ATTACH_TO) and selected_id == DARK_ENERGY:
                return "advancing", "select_useful_energy"
            if context == int(SelectContext.ATTACH_FROM) and selected_id in GRIM_LINE and _attack_deficit(selected) > 0:
                own_bench_target = getattr(option, "area", None) == AreaType.BENCH
                if not replacement or own_bench_target:
                    return "advancing", "punk_up_attacker"
            if context in {int(SelectContext.TO_ACTIVE), int(SelectContext.SWITCH)} and selected_id in GRIM_LINE and _ready(selected):
                return "advancing", "promote_ready_attacker"
            if _is_main(obs) and kind in {int(OptionType.ATTACK), int(OptionType.END)} and development_available:
                return "contradicting", "required_development_before_attack"
            if _is_main(obs) and kind == int(OptionType.PLAY) and source_id in SUPPORT:
                return "contradicting", "delay_optional_support"
        if objective == Objective.DENY_STADIUM_ENGINE:
            if kind == int(OptionType.PLAY) and source_id == SPIKEMUTH:
                return "advancing", "replace_opposing_stadium"
            if _is_main(obs) and kind in {int(OptionType.ATTACK), int(OptionType.END)} and _has_option(obs, OptionType.PLAY, SPIKEMUTH):
                return "contradicting", "stadium_denial_before_attack"
        if objective in {Objective.DENY_EVOLUTION_ENGINE, Objective.DENY_SUPPORT_ENGINE,
                         Objective.PRESSURE_PRIMARY_ATTACKER, Objective.CLOSEOUT_PRIZE_ROUTE}:
            target_is_benched = bool(plan.target and plan.target.last_zone == int(AreaType.BENCH))
            resolved = self._resolve_target(summary, plan.target)
            boss_converts_to_ko = bool(
                resolved and summary.own_active and summary.own_active.ready
                and any(
                    _option_type(candidate) == int(OptionType.ATTACK)
                    and not attack_nullified(obs, candidate)
                    and self._attack_damage(obs, candidate, resolved) >= resolved.hp
                    for candidate in obs.select.option
                )
            )
            if kind == int(OptionType.PLAY) and source_id == BOSS_ORDERS and target_is_benched and boss_converts_to_ko:
                return "advancing", "boss_committed_target"
            if context in {int(SelectContext.SWITCH), int(SelectContext.EFFECT_TARGET), int(SelectContext.DAMAGE),
                           int(SelectContext.DAMAGE_COUNTER), int(SelectContext.DAMAGE_COUNTER_ANY)}:
                if _option_owner(obs, option) != obs.current.yourIndex:
                    return ("advancing", "committed_target") if self._matches_target(selected, plan) else ("contradicting", "abandon_committed_target")
            # The attack itself ends the turn and is not target-specific.  A2
            # decides when development is complete; the commitment governs
            # Boss/target/damage prompts and survives until the attack occurs.
        if objective == Objective.CONVERT_DAMAGE_BREAKPOINT:
            if kind == int(OptionType.ABILITY) and source_id == MUNKIDORI:
                return "advancing", "activate_damage_conversion"
            if kind == int(OptionType.ATTACK) and int(getattr(option, "attackId", 0) or 0) == SHADOW_BULLET:
                if _has_option(obs, OptionType.ABILITY, MUNKIDORI):
                    return "contradicting", "convert_before_attack"
                return "advancing", "complete_180_plus_30"
            if context in {int(SelectContext.REMOVE_DAMAGE_COUNTER), int(SelectContext.DAMAGE_COUNTER),
                           int(SelectContext.DAMAGE_COUNTER_ANY), int(SelectContext.DAMAGE)}:
                if _option_owner(obs, option) == obs.current.yourIndex and _damage(selected) >= 30:
                    return "advancing", "source_damage_counters"
                if _option_owner(obs, option) != obs.current.yourIndex and self._matches_target(selected, plan):
                    return "advancing", "place_conversion_damage"
        if objective == Objective.PRESERVE_ONE_PRIZE_ATTACKER:
            if (kind == int(OptionType.ATTACH) and target_id == MORGREM) or (context == int(SelectContext.TO_ACTIVE) and selected_id == MORGREM):
                return "advancing", "preserve_morgrem_route"
            if kind == int(OptionType.EVOLVE) and target_id == MORGREM and summary.morgrem_count <= 1:
                return "contradicting", "keep_last_morgrem"
        if objective == Objective.MANAGE_SPREAD_LIABILITY:
            if kind == int(OptionType.EVOLVE) and target is not None and int(getattr(target, "hp", 999) or 999) <= 60:
                return "advancing", "evolve_spread_liability"
            if kind == int(OptionType.ABILITY) and source_id == MUNKIDORI:
                return "advancing", "clear_critical_counters"
            if kind == int(OptionType.PLAY) and source_id in SUPPORT:
                return "contradicting", "avoid_extra_spread_liability"
        if objective == Objective.MANAGE_HAND_SIZE:
            if kind in {int(OptionType.PLAY), int(OptionType.ATTACH), int(OptionType.EVOLVE)} and source_id not in {BUDDY_POFFIN}:
                return "advancing", "safe_hand_reduction"
            if kind == int(OptionType.ABILITY) and source_id in {FROSLASS, MUNKIDORI}:
                return "contradicting", "avoid_optional_draw"
        return "neutral", "neutral"

    def _desired_count(self, obs, summary: PublicSummary, count_logits: np.ndarray) -> int:
        minimum, maximum = int(obs.select.minCount), int(obs.select.maxCount)
        if minimum == maximum:
            return maximum
        maximum = min(maximum, len(count_logits) - 1)
        desired = minimum + int(np.argmax(count_logits[minimum:maximum + 1]))
        route = ROUTES.get(summary.route)
        if int(obs.select.context) == int(SelectContext.SETUP_BENCH_POKEMON):
            width = route.useful_width if route else (3 if summary.actual_second else 2)
            return min(maximum, max(minimum, width))
        if _effect_id(obs) == GRIMMSNARL and int(obs.select.context) == int(SelectContext.ATTACH_TO):
            own = ([summary.own_active] if summary.own_active else []) + summary.own_bench
            deficits = [min(2, p.attack_deficit) for p in own if p.card_id in GRIM_LINE and p.attack_deficit < 99]
            useful = sum(deficits)
            return min(maximum, max(minimum, useful))
        if self.plan and self.plan.objective == Objective.CONVERT_DAMAGE_BREAKPOINT and int(obs.select.context) in {
            int(SelectContext.DAMAGE_COUNTER_COUNT), int(SelectContext.REMOVE_DAMAGE_COUNTER_COUNT)
        }:
            return min(maximum, max(minimum, 3))
        return desired

    def _action_semantic(self, obs, index: int, category: str, reason: str) -> dict:
        option = obs.select.option[index]
        source, selected = _option_source(obs, option), _selected_card(obs, option)
        return {
            "context": int(obs.select.context), "type": _option_type(option),
            "source_id": int(getattr(source, "id", 0) or 0),
            "target_id": int(getattr(selected, "id", 0) or 0),
            "target_serial": _serial(selected), "attack_id": int(getattr(option, "attackId", 0) or 0),
            "category": category, "reason": reason,
        }

    def choose(self, obs) -> list[int]:
        features = encode_observation(obs, self.model.feature_version)
        logits, count_logits, _ = self.model.predict(features)
        if len(logits) == 0:
            return []
        summary = build_public_summary(obs, self.router)
        self._ensure_plan(obs, summary)
        assert self.plan is not None
        base_ranked = np.argsort(-logits).astype(int).tolist()
        development_available = any(
            self._development_action(obs, summary, i, self.plan.objective == Objective.BUILD_REPLACEMENT_ATTACKER)
            for i in range(len(obs.select.option))
        )
        classified = {i: self._classify(obs, summary, i, development_available) for i in range(len(logits))}
        advancing = [i for i in base_ranked if classified[i][0] == "advancing"]
        neutral = [i for i in base_ranked if classified[i][0] == "neutral"]
        contradicting = [i for i in base_ranked if classified[i][0] == "contradicting"]
        forbidden = [i for i in base_ranked if classified[i][0] == "forbidden"]
        commit_allowed = False
        if advancing and self.plan.enforcement == Enforcement.COMMIT:
            best_advance = max(float(logits[i]) for i in advancing)
            gap = float(logits[base_ranked[0]]) - best_advance
            target_context = int(obs.select.context) in {
                int(SelectContext.SWITCH), int(SelectContext.EFFECT_TARGET), int(SelectContext.DAMAGE),
                int(SelectContext.DAMAGE_COUNTER), int(SelectContext.DAMAGE_COUNTER_ANY),
            }
            if self.plan.objective == Objective.DENY_STADIUM_ENGINE or target_context:
                margin = float(self.config.get("target_commit_logit_margin", 3.0))
            elif self.plan.objective in {Objective.BUILD_FIRST_ATTACKER, Objective.BUILD_REPLACEMENT_ATTACKER}:
                margin = float(self.config.get(
                    "actual_second_build_logit_margin" if summary.actual_second else "build_logit_margin",
                    1.25 if summary.actual_second else .65,
                ))
            else:
                margin = float(self.config.get("commit_logit_margin", 1.0))
            commit_allowed = gap <= margin
        if self.plan.enforcement == Enforcement.HARD and advancing:
            ranked = advancing + neutral + contradicting + forbidden
        elif self.plan.enforcement == Enforcement.COMMIT and advancing and commit_allowed:
            ranked = advancing + neutral + contradicting + forbidden
        elif self.plan.enforcement == Enforcement.PREFERENCE:
            margin = float(self.config.get("preference_logit_margin", .75))
            scores = np.asarray(logits, dtype=np.float32).copy()
            for i in advancing:
                scores[i] += margin
            for i in contradicting:
                scores[i] -= margin
            for i in forbidden:
                scores[i] -= 1e6
            ranked = np.argsort(-scores).astype(int).tolist()
        else:
            # A persistent objective with no executable advancing action is a
            # state commitment, not permission to suppress A2's best legal
            # fallback.  Only verified mechanical impossibilities stay last.
            ranked = [i for i in base_ranked if i not in forbidden] + forbidden
            self.plan.fallback_prompts_this_turn += 1
            self.telemetry["fallback_prompts"] += 1
        desired = self._desired_count(obs, summary, count_logits)
        before_shield = ranked[0] if ranked else -1
        ranked, desired, shield_reason = apply_tactical_shield(obs, ranked, desired)
        self.shield_telemetry.record(shield_reason)
        result = sanitize_selection(obs.select, ranked, desired)
        selected = result[0] if result else -1
        category, reason = classified.get(selected, ("none", "none"))
        semantic = self._action_semantic(obs, selected, category, reason) if selected >= 0 else {}
        changed = bool(result and base_ranked and selected != base_ranked[0])
        self.telemetry["decisions"] += 1
        self.telemetry[f"route:{summary.route}"] += 1
        self.telemetry[f"objective_decision:{self.plan.objective.value}"] += 1
        self.telemetry[f"phase_decision:{self.plan.phase.value}"] += 1
        self.telemetry[f"order:{summary.actual_order}"] += 1
        if changed:
            self.telemetry["changed_top"] += 1
            self.telemetry[f"changed_route:{summary.route}"] += 1
            self.telemetry[f"changed_order:{summary.actual_order}"] += 1
            self.telemetry[f"changed_objective:{self.plan.objective.value}"] += 1
        if shield_reason:
            self.telemetry[f"hard_mechanics:{shield_reason}"] += 1
        for i in forbidden:
            self.telemetry[f"mechanically_forbidden:{classified[i][1]}"] += 1
        self.plan.last_action_semantic = semantic
        if self.turn_traces:
            self.turn_traces[-1]["decisions"].append({
                "objective": self.plan.objective.value, "phase": self.plan.phase.value,
                "a2_top": base_ranked[0] if base_ranked else None, "controller": selected,
                "overrode_a2": changed, "semantic": semantic, "shield": shield_reason,
            })
        self.last = {
            "route": summary.route, "confidence": summary.route_confidence, "route_status": summary.route_status,
            "phase": self.plan.phase.value, "objective": self.plan.objective.value,
            "enforcement": self.plan.enforcement.value, "target_serial": self.plan.target_serial,
            "objective_reason": self.plan.objective_reason, "actual_second": summary.actual_second,
            "changed_top": changed, "a2_top": base_ranked[0] if base_ranked else None,
            "controller_top": before_shield, "selected": selected, "semantic": semantic, "shield": shield_reason,
        }
        return result


class StrategicPlaybookAgent:
    """Competition wrapper retaining exact d842 as fail-closed fallback."""

    def __init__(self):
        self.deck_path = _find("deck.csv")
        self.deck = [int(line) for line in self.deck_path.read_text().splitlines() if line.strip()]
        if len(self.deck) != 60:
            raise ValueError("deck must contain exactly 60 cards")
        self.config = json.loads(_find("strategic_config.json").read_text(encoding="utf-8"))
        self.policy = StrategicPolicy(self.config)
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
            yes = [i for i, option in enumerate(obs.select.option) if _option_type(option) == int(OptionType.YES)]
            if len(yes) == 1:
                return sanitize_selection(obs.select, yes, 1)
        try:
            return self.policy.choose(obs)
        except Exception:
            self.errors += 1
            return self.exact(obs_dict)

"""Fail-closed, complete-turn counterfactual correction certification.

This module is intentionally training-only.  It compares one proposed root
selection with the frozen policy selection on common hidden-state
determinizations, completes the *current* turn for both branches, and evaluates
only public board outcomes.  It never turns a truncated rollout into a neutral
score and it never admits a comparison with partial or unequal coverage.

The engine's option indices are prompt-local.  Persisted boundaries therefore
use card serials and intrinsic option fields, and can be resolved again after
the engine reorders otherwise identical legal options.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import time
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Sequence

from cg.api import AreaType, OptionType, search_begin, search_end, search_release, search_step, to_observation_class

from ptcg_ai.view import attached_energy_count, cards_in_play, damage_on, prize_value
from training.search_teacher import DeterminizationError, determinize_known_matchup


class CorrectionOracleError(RuntimeError):
    """Base class for a comparison that cannot be certified."""


class SemanticBoundaryError(CorrectionOracleError):
    """A prompt-local option could not be represented without its index."""


class IncompleteTurnError(CorrectionOracleError):
    """A branch failed to reach a terminal or next-turn boundary."""


class EngineCleanupError(CorrectionOracleError):
    """A native search resource could not be released cleanly."""


def _primitive(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return int(value.value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return str(value)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _card_identity(card: Any) -> dict[str, int] | None:
    if card is None or getattr(card, "id", None) is None or getattr(card, "serial", None) is None:
        return None
    payload = {"id": int(card.id), "serial": int(card.serial)}
    if getattr(card, "playerIndex", None) is not None:
        payload["player_index"] = int(card.playerIndex)
    return payload


def _sorted_identities(cards: Any) -> list[dict[str, int]]:
    result = [_card_identity(card) for card in cards or []]
    return sorted((item for item in result if item is not None), key=_canonical)


def _zone_card(obs: Any, area: Any, index: Any, player_index: Any = None) -> Any:
    if obs.current is None or area is None or index is None:
        return None
    area_value = int(area)
    position = int(index)
    owner = int(obs.current.yourIndex if player_index is None else player_index)
    if area_value == int(AreaType.LOOKING):
        zone = obs.current.looking or []
    elif area_value == int(AreaType.STADIUM):
        zone = obs.current.stadium or []
    elif area_value == int(AreaType.DECK):
        zone = obs.select.deck or []
    else:
        player = obs.current.players[owner]
        zones = {
            int(AreaType.HAND): player.hand or [],
            int(AreaType.DISCARD): player.discard or [],
            int(AreaType.ACTIVE): player.active or [],
            int(AreaType.BENCH): player.bench or [],
            int(AreaType.PRIZE): player.prize or [],
        }
        zone = zones.get(area_value, [])
    return zone[position] if 0 <= position < len(zone) else None


@dataclass(frozen=True)
class SemanticOption:
    """One legal option represented without any prompt-local array index."""

    option_type: int
    payload_json: str

    @property
    def payload(self) -> dict[str, Any]:
        return json.loads(self.payload_json)

    def to_dict(self) -> dict[str, Any]:
        return {"option_type": self.option_type, "payload": self.payload}


@dataclass(frozen=True)
class SemanticAction:
    """A stable action boundary suitable for a correction artifact."""

    select_type: int
    context: int
    minimum: int
    maximum: int
    context_card: str | None
    effect: str | None
    options: tuple[SemanticOption, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "select_type": self.select_type,
            "context": self.context,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "context_card": json.loads(self.context_card) if self.context_card else None,
            "effect": json.loads(self.effect) if self.effect else None,
            "options": [option.to_dict() for option in self.options],
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict()).encode("utf-8")).hexdigest().upper()


_SOURCE_TYPES = frozenset(
    {
        int(OptionType.CARD),
        int(OptionType.PLAY),
        int(OptionType.ATTACH),
        int(OptionType.EVOLVE),
        int(OptionType.ABILITY),
        int(OptionType.DISCARD),
        int(OptionType.TOOL_CARD),
        int(OptionType.ENERGY_CARD),
        int(OptionType.ENERGY),
    }
)
_ATTACHED_TYPES = frozenset(
    {int(OptionType.TOOL_CARD), int(OptionType.ENERGY_CARD), int(OptionType.ENERGY)}
)
_TARGET_TYPES = frozenset({int(OptionType.ATTACH), int(OptionType.EVOLVE)})


def semantic_option(obs: Any, option: Any) -> SemanticOption:
    """Convert an option to stable visible identities, or fail closed."""

    option_type = int(option.type)
    payload: dict[str, Any] = {}
    for source_name, destination_name in (
        ("number", "number"),
        ("count", "count"),
        ("attackId", "attack_id"),
        ("cardId", "card_id"),
        ("serial", "serial"),
        ("specialConditionType", "special_condition_type"),
    ):
        value = getattr(option, source_name, None)
        if value is not None:
            payload[destination_name] = _primitive(value)

    raw_area = getattr(option, "area", None)
    raw_owner = getattr(option, "playerIndex", None)
    raw_index = getattr(option, "index", None)
    if option_type == int(OptionType.PLAY):
        raw_area = AreaType.HAND
        raw_owner = obs.current.yourIndex if obs.current is not None else None

    if option_type in _SOURCE_TYPES:
        if raw_area is not None:
            payload["area"] = int(raw_area)
        if raw_owner is not None:
            payload["player_index"] = int(raw_owner)
        if raw_area is not None and int(raw_area) == int(AreaType.PLAYER):
            payload["selected_player"] = int(raw_owner if raw_owner is not None else raw_index)
        else:
            source = _zone_card(obs, raw_area, raw_index, raw_owner)
            identity = _card_identity(source)
            if identity is None:
                raise SemanticBoundaryError(
                    f"cannot resolve source for option type={option_type} area={raw_area}"
                )
            payload["source"] = identity

            if option_type in _ATTACHED_TYPES:
                attached_name = "tools" if option_type == int(OptionType.TOOL_CARD) else "energyCards"
                sub_name = "toolIndex" if option_type == int(OptionType.TOOL_CARD) else "energyIndex"
                sub_index = getattr(option, sub_name, None)
                attached = getattr(source, attached_name, None) or []
                if sub_index is None or not 0 <= int(sub_index) < len(attached):
                    raise SemanticBoundaryError(
                        f"cannot resolve attached card for option type={option_type}"
                    )
                payload["attached"] = _card_identity(attached[int(sub_index)])

    elif raw_index is not None:
        # Future engine option types must be deliberately modeled.  Falling
        # back to ``index`` would make a persisted correction unstable.
        raise SemanticBoundaryError(f"unsupported positional option type={option_type}")

    if option_type in _TARGET_TYPES:
        target_area = getattr(option, "inPlayArea", None)
        target_index = getattr(option, "inPlayIndex", None)
        target = _zone_card(obs, target_area, target_index, obs.current.yourIndex)
        identity = _card_identity(target)
        if target_area is None or identity is None:
            raise SemanticBoundaryError(f"cannot resolve target for option type={option_type}")
        payload["target_area"] = int(target_area)
        payload["target"] = identity

    return SemanticOption(option_type=option_type, payload_json=_canonical(payload))


def semantic_action(obs: Any, action: Sequence[int]) -> SemanticAction:
    """Capture a complete selection without retaining option indices."""

    if obs.current is None or obs.select is None:
        raise SemanticBoundaryError("semantic action requires a live selection")
    indices = tuple(int(index) for index in action)
    if len(indices) != len(set(indices)):
        raise SemanticBoundaryError("selection contains duplicate option indices")
    if not int(obs.select.minCount) <= len(indices) <= int(obs.select.maxCount):
        raise SemanticBoundaryError("selection count is outside the legal bounds")
    if any(index < 0 or index >= len(obs.select.option) for index in indices):
        raise SemanticBoundaryError("selection contains an out-of-range option index")

    context_card = _card_identity(getattr(obs.select, "contextCard", None))
    effect = _card_identity(getattr(obs.select, "effect", None))
    return SemanticAction(
        select_type=int(obs.select.type),
        context=int(obs.select.context),
        minimum=int(obs.select.minCount),
        maximum=int(obs.select.maxCount),
        context_card=_canonical(context_card) if context_card else None,
        effect=_canonical(effect) if effect else None,
        options=tuple(semantic_option(obs, obs.select.option[index]) for index in indices),
    )


def resolve_semantic_action(obs: Any, action: SemanticAction) -> list[int] | None:
    """Resolve a stable action against the current prompt's option ordering."""

    if obs.current is None or obs.select is None:
        return None
    if (
        int(obs.select.type) != action.select_type
        or int(obs.select.context) != action.context
        or int(obs.select.minCount) != action.minimum
        or int(obs.select.maxCount) != action.maximum
    ):
        return None
    context_card = _card_identity(getattr(obs.select, "contextCard", None))
    effect = _card_identity(getattr(obs.select, "effect", None))
    if (_canonical(context_card) if context_card else None) != action.context_card:
        return None
    if (_canonical(effect) if effect else None) != action.effect:
        return None

    available: dict[SemanticOption, list[int]] = {}
    for index, option in enumerate(obs.select.option):
        try:
            key = semantic_option(obs, option)
        except SemanticBoundaryError:
            continue
        available.setdefault(key, []).append(index)
    resolved: list[int] = []
    for key in action.options:
        matches = available.get(key, [])
        if not matches:
            return None
        resolved.append(matches.pop(0))
    return resolved


def _pokemon_payload(pokemon: Any) -> dict[str, Any] | None:
    identity = _card_identity(pokemon)
    if identity is None:
        return None
    return {
        **identity,
        "hp": int(getattr(pokemon, "hp", 0)),
        "max_hp": int(getattr(pokemon, "maxHp", 0)),
        "appeared": bool(getattr(pokemon, "appearThisTurn", False)),
        "energies": sorted(int(value) for value in (getattr(pokemon, "energies", None) or [])),
        "energy_cards": _sorted_identities(getattr(pokemon, "energyCards", None)),
        "tools": _sorted_identities(getattr(pokemon, "tools", None)),
        "pre_evolution": _sorted_identities(getattr(pokemon, "preEvolution", None)),
    }


def _sorted_pokemon(cards: Any) -> list[dict[str, Any]]:
    result = [_pokemon_payload(card) for card in cards or []]
    return sorted((item for item in result if item is not None), key=_canonical)


def _player_boundary(player: Any, reveal_hand: bool) -> dict[str, Any]:
    prize = [_card_identity(card) for card in (player.prize or [])]
    return {
        "active": _sorted_pokemon(player.active),
        "bench": _sorted_pokemon(player.bench),
        "deck_count": int(player.deckCount),
        "discard": _sorted_identities(player.discard),
        "prize_count": len(player.prize or []),
        "known_prizes": sorted((item for item in prize if item is not None), key=_canonical),
        "hand_count": int(player.handCount),
        "hand": _sorted_identities(player.hand) if reveal_hand else None,
        "conditions": {
            name: bool(getattr(player, name, False))
            for name in ("poisoned", "burned", "asleep", "paralyzed", "confused")
        },
    }


def _log_payload(log: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    fields = getattr(log, "__dataclass_fields__", None)
    names = list(fields) if fields else list(vars(log))
    for name in names:
        value = getattr(log, name, None)
        if value is not None:
            payload[name] = _primitive(value)
    return payload


def public_boundary_hash(obs_or_dict: Any) -> str:
    """Hash the actor-visible semantic decision boundary, not option ordering."""

    obs = to_observation_class(obs_or_dict) if isinstance(obs_or_dict, dict) else obs_or_dict
    if obs.current is None or obs.select is None:
        raise SemanticBoundaryError("boundary requires a live selection")
    viewer = int(obs.current.yourIndex)
    choices = sorted((semantic_option(obs, option).to_dict() for option in obs.select.option), key=_canonical)
    payload = {
        "state": {
            "turn": int(obs.current.turn),
            "turn_action_count": int(obs.current.turnActionCount),
            "your_index": viewer,
            "first_player": int(obs.current.firstPlayer),
            "supporter_played": bool(obs.current.supporterPlayed),
            "stadium_played": bool(obs.current.stadiumPlayed),
            "energy_attached": bool(obs.current.energyAttached),
            "retreated": bool(obs.current.retreated),
            "result": int(obs.current.result),
            "players": [
                _player_boundary(player, index == viewer)
                for index, player in enumerate(obs.current.players)
            ],
            "stadium": _sorted_identities(obs.current.stadium),
            "looking": _sorted_identities(obs.current.looking),
        },
        "select": {
            "type": int(obs.select.type),
            "context": int(obs.select.context),
            "minimum": int(obs.select.minCount),
            "maximum": int(obs.select.maxCount),
            "remain_damage_counter": int(getattr(obs.select, "remainDamageCounter", 0)),
            "remain_energy_cost": int(getattr(obs.select, "remainEnergyCost", 0)),
            "context_card": _card_identity(getattr(obs.select, "contextCard", None)),
            "effect": _card_identity(getattr(obs.select, "effect", None)),
            "choices": choices,
        },
        "logs": [_log_payload(log) for log in (obs.logs or [])],
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest().upper()


def crn_seed(base_seed: int, boundary_hash: str, world_index: int) -> int:
    """Derive a call-order-independent hidden-world seed."""

    if world_index < 0:
        raise ValueError("world_index must be non-negative")
    material = f"complete-turn-correction-v1\0{int(base_seed)}\0{boundary_hash.upper()}\0{world_index}"
    return int.from_bytes(hashlib.sha256(material.encode("ascii")).digest()[:8], "big")


@dataclass(frozen=True)
class PublicMetricConfig:
    """Deck-specific constants for public, auditable board evaluation."""

    ready_energy_requirements: tuple[tuple[int, int], ...] = ((648, 2),)
    route_weights: tuple[tuple[int, float], ...] = (
        (646, 0.5),
        (647, 1.0),
        (648, 2.0),
        (112, 0.75),
        (860, 0.4),
        (104, 0.9),
    )
    critical_resource_ids: tuple[int, ...] = (7, 647, 648, 1079, 1097, 1137, 1152, 1182, 1219, 1259)


@dataclass(frozen=True)
class PublicMetricVector:
    """Higher-is-better components in their strict lexicographic order."""

    terminal_result: float
    prizes: float
    ko_value: float
    ready_attackers: float
    route_progress: float
    exposed_prizes: float
    retained_critical_resources: float

    def values(self) -> tuple[float, ...]:
        return (
            self.terminal_result,
            self.prizes,
            self.ko_value,
            self.ready_attackers,
            self.route_progress,
            self.exposed_prizes,
            self.retained_critical_resources,
        )

    def is_finite(self) -> bool:
        return all(math.isfinite(float(value)) for value in self.values())


def compare_public_metrics(left: PublicMetricVector, right: PublicMetricVector) -> int:
    """Return the lexicographic ordering of two validated public vectors."""

    if not left.is_finite() or not right.is_finite():
        raise ValueError("public metric components must be finite")
    return (left.values() > right.values()) - (left.values() < right.values())


def _damage_pressure(player: Any) -> float:
    total = 0.0
    for pokemon in cards_in_play(player):
        maximum = max(1, int(getattr(pokemon, "maxHp", 0)))
        total += float(prize_value(pokemon)) * float(damage_on(pokemon)) / maximum
    return total


def public_metric_vector(
    initial_state: Any,
    final_state: Any,
    root_player: int,
    config: PublicMetricConfig | None = None,
) -> PublicMetricVector:
    """Evaluate a complete branch using board, discard, and prize counts only."""

    config = config or PublicMetricConfig()
    if final_state is None:
        raise IncompleteTurnError("complete branch has no public final state")
    root_player = int(root_player)
    initial_me = initial_state.players[root_player]
    final_me = final_state.players[root_player]
    initial_opponent = initial_state.players[1 - root_player]
    final_opponent = final_state.players[1 - root_player]

    result = int(final_state.result)
    terminal = 0.0
    if result >= 0 and result != 2:
        terminal = 1.0 if result == root_player else -1.0
    prizes = float(len(initial_me.prize or []) - len(final_me.prize or []))
    initial_pressure = _damage_pressure(initial_opponent) - _damage_pressure(initial_me)
    final_pressure = _damage_pressure(final_opponent) - _damage_pressure(final_me)

    requirements = dict(config.ready_energy_requirements)
    ready = sum(
        1.0
        for pokemon in cards_in_play(final_me)
        if int(pokemon.id) in requirements
        and int(getattr(pokemon, "hp", 0)) > 0
        and attached_energy_count(pokemon) >= int(requirements[int(pokemon.id)])
    )
    weights = dict(config.route_weights)
    route = sum(float(weights.get(int(pokemon.id), 0.0)) for pokemon in cards_in_play(final_me))
    exposed = -sum(
        float(prize_value(pokemon))
        * float(damage_on(pokemon))
        / max(1, int(getattr(pokemon, "maxHp", 0)))
        for pokemon in cards_in_play(final_me)
    )
    critical = set(map(int, config.critical_resource_ids))
    retained = -sum(1.0 for card in (final_me.discard or []) if int(card.id) in critical)
    vector = PublicMetricVector(
        terminal_result=terminal,
        prizes=prizes,
        ko_value=float(final_pressure - initial_pressure),
        ready_attackers=float(ready),
        route_progress=float(route),
        exposed_prizes=float(exposed),
        retained_critical_resources=float(retained),
    )
    if not vector.is_finite():
        raise CorrectionOracleError("non-finite public metric")
    return vector


@dataclass(frozen=True)
class AdmissionDecision:
    admitted: bool
    reason: str
    expected_worlds: int
    covered_worlds: int
    noninferior_worlds: int
    strict_better_worlds: int
    required_strict_worlds: int


def assess_admission(
    baseline: Mapping[int, PublicMetricVector],
    candidate: Mapping[int, PublicMetricVector],
    expected_worlds: int,
) -> AdmissionDecision:
    """Apply noninferior-all and strict-better-in-at-least-half admission."""

    if expected_worlds <= 0:
        raise ValueError("expected_worlds must be positive")
    required = int(math.ceil(expected_worlds / 2))
    expected = set(range(expected_worlds))
    baseline_keys, candidate_keys = set(baseline), set(candidate)
    paired = baseline_keys & candidate_keys
    if baseline_keys != expected or candidate_keys != expected:
        return AdmissionDecision(
            False,
            "incomplete_or_unequal_coverage",
            expected_worlds,
            len(paired),
            0,
            0,
            required,
        )
    if any(not baseline[index].is_finite() or not candidate[index].is_finite() for index in expected):
        return AdmissionDecision(False, "invalid_metric", expected_worlds, expected_worlds, 0, 0, required)

    noninferior = 0
    strict = 0
    for world_index in range(expected_worlds):
        comparison = compare_public_metrics(candidate[world_index], baseline[world_index])
        if comparison < 0:
            return AdmissionDecision(
                False,
                f"regression_in_world:{world_index}",
                expected_worlds,
                expected_worlds,
                noninferior,
                strict,
                required,
            )
        noninferior += 1
        strict += int(comparison > 0)
    if strict < required:
        return AdmissionDecision(
            False,
            "strict_improvement_below_half",
            expected_worlds,
            expected_worlds,
            noninferior,
            strict,
            required,
        )
    return AdmissionDecision(
        True,
        "admitted",
        expected_worlds,
        expected_worlds,
        noninferior,
        strict,
        required,
    )


@dataclass(frozen=True)
class CorrectionConfig:
    worlds: int = 8
    max_turn_steps: int = 64
    timeout_seconds: float = 120.0
    seed: int = 20260809
    manual_coin: bool = True

    def __post_init__(self) -> None:
        if self.worlds <= 0:
            raise ValueError("worlds must be positive")
        if self.max_turn_steps <= 0:
            raise ValueError("max_turn_steps must be positive")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")


@dataclass(frozen=True)
class WorldComparison:
    world_index: int
    seed: int
    baseline: PublicMetricVector
    candidate: PublicMetricVector
    baseline_steps: int
    candidate_steps: int


@dataclass(frozen=True)
class CorrectionEvaluation:
    boundary_hash: str
    baseline_action: SemanticAction | None
    candidate_action: SemanticAction | None
    worlds: tuple[WorldComparison, ...]
    coverage: dict[str, int]
    decision: AdmissionDecision
    errors: tuple[str, ...]

    @property
    def admitted(self) -> bool:
        return self.decision.admitted

    @property
    def reason(self) -> str:
        return self.decision.reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "boundary_hash": self.boundary_hash,
            "baseline_action": self.baseline_action.to_dict() if self.baseline_action else None,
            "candidate_action": self.candidate_action.to_dict() if self.candidate_action else None,
            "worlds": [asdict(world) for world in self.worlds],
            "coverage": dict(self.coverage),
            "decision": asdict(self.decision),
            "errors": list(self.errors),
        }


Selector = Callable[[Any], Sequence[int]]
SelectorFactory = Callable[[], Selector]
Clock = Callable[[], float]


def _check_deadline(clock: Clock, deadline: float) -> None:
    if clock() >= deadline:
        raise TimeoutError("complete-turn correction deadline exceeded")


def _turn_complete(state: Any, root_player: int, root_turn: int) -> bool:
    current = state.observation.current
    return (
        current is not None
        and (
            int(current.result) >= 0
            or int(current.yourIndex) != root_player
            or int(current.turn) != root_turn
        )
    )


def _release_state(state: Any, cleanup_errors: list[str], label: str) -> None:
    if state is None:
        return
    try:
        search_release(int(state.searchId))
    except Exception as exc:  # cleanup failures make certification unusable
        cleanup_errors.append(f"{label}:{type(exc).__name__}:{exc}")


def _run_branch(
    root: Any,
    root_action: SemanticAction,
    root_player: int,
    root_turn: int,
    initial_state: Any,
    selector: Selector,
    config: CorrectionConfig,
    metric_config: PublicMetricConfig,
    clock: Clock,
    deadline: float,
) -> tuple[PublicMetricVector, int]:
    state = None
    cleanup_errors: list[str] = []
    primary_error: Exception | None = None
    result: tuple[PublicMetricVector, int] | None = None
    try:
        _check_deadline(clock, deadline)
        resolved = resolve_semantic_action(root.observation, root_action)
        if resolved is None:
            raise SemanticBoundaryError("semantic root action is unavailable in determinized world")
        state = search_step(int(root.searchId), resolved)
        steps = 1
        _check_deadline(clock, deadline)
        while not _turn_complete(state, root_player, root_turn):
            current = state.observation.current
            if current is None or state.observation.select is None:
                raise IncompleteTurnError("nonterminal branch has no legal selection")
            if steps >= config.max_turn_steps:
                raise IncompleteTurnError(
                    f"turn did not complete within {config.max_turn_steps} engine steps"
                )
            action = [int(index) for index in selector(state.observation)]
            _check_deadline(clock, deadline)
            next_state = search_step(int(state.searchId), action)
            _release_state(state, cleanup_errors, "interior_release")
            state = next_state
            steps += 1
            _check_deadline(clock, deadline)
        result = (
            public_metric_vector(initial_state, state.observation.current, root_player, metric_config),
            steps,
        )
    except Exception as exc:
        primary_error = exc
    finally:
        _release_state(state, cleanup_errors, "branch_release")
    if primary_error is not None:
        if cleanup_errors:
            primary_error.add_note(";".join(cleanup_errors))
        raise primary_error
    if cleanup_errors:
        raise EngineCleanupError(";".join(cleanup_errors))
    if result is None:
        raise IncompleteTurnError("branch produced no complete public metric")
    return result


def _evaluate_world(
    obs: Any,
    baseline: SemanticAction,
    candidate: SemanticAction,
    hero_deck: Sequence[int],
    opponent_deck: Sequence[int],
    selector_factory: SelectorFactory,
    config: CorrectionConfig,
    metric_config: PublicMetricConfig,
    seed: int,
    determinizer: Callable[[Any, list[int], list[int], random.Random], dict[str, Any]],
    clock: Clock,
    deadline: float,
) -> tuple[PublicMetricVector, int, PublicMetricVector, int]:
    root = None
    cleanup_errors: list[str] = []
    primary_error: Exception | None = None
    result: tuple[PublicMetricVector, int, PublicMetricVector, int] | None = None
    try:
        _check_deadline(clock, deadline)
        kwargs = dict(determinizer(obs, list(hero_deck), list(opponent_deck), random.Random(seed)))
        kwargs["manual_coin"] = bool(config.manual_coin)
        root = search_begin(obs, **kwargs)
        _check_deadline(clock, deadline)
        root_player = int(obs.current.yourIndex)
        root_turn = int(obs.current.turn)
        initial_state = root.observation.current
        baseline_metric, baseline_steps = _run_branch(
            root,
            baseline,
            root_player,
            root_turn,
            initial_state,
            selector_factory(),
            config,
            metric_config,
            clock,
            deadline,
        )
        candidate_metric, candidate_steps = _run_branch(
            root,
            candidate,
            root_player,
            root_turn,
            initial_state,
            selector_factory(),
            config,
            metric_config,
            clock,
            deadline,
        )
        result = baseline_metric, baseline_steps, candidate_metric, candidate_steps
    except Exception as exc:
        primary_error = exc
    finally:
        _release_state(root, cleanup_errors, "root_release")
        try:
            search_end()
        except Exception as exc:
            cleanup_errors.append(f"search_end:{type(exc).__name__}:{exc}")
    if primary_error is not None:
        if cleanup_errors:
            primary_error.add_note(";".join(cleanup_errors))
        raise primary_error
    if cleanup_errors:
        raise EngineCleanupError(";".join(cleanup_errors))
    if result is None:
        raise IncompleteTurnError("world produced no paired result")
    return result


def _failure_decision(reason: str, expected_worlds: int, covered_worlds: int) -> AdmissionDecision:
    return AdmissionDecision(
        admitted=False,
        reason=reason,
        expected_worlds=expected_worlds,
        covered_worlds=covered_worlds,
        noninferior_worlds=0,
        strict_better_worlds=0,
        required_strict_worlds=int(math.ceil(expected_worlds / 2)),
    )


def _error_reason(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, IncompleteTurnError):
        return "incomplete_turn"
    if isinstance(exc, SemanticBoundaryError):
        return "semantic_boundary_error"
    if isinstance(exc, DeterminizationError):
        return "determinization_error"
    if isinstance(exc, EngineCleanupError):
        return "engine_cleanup_error"
    return "engine_error"


def evaluate_complete_turn_correction(
    observation: Any,
    baseline_action: Sequence[int],
    candidate_action: Sequence[int],
    hero_deck: Sequence[int],
    opponent_deck: Sequence[int],
    selector_factory: SelectorFactory,
    *,
    config: CorrectionConfig | None = None,
    metric_config: PublicMetricConfig | None = None,
    determinizer: Callable[[Any, list[int], list[int], random.Random], dict[str, Any]] | None = None,
    clock: Clock | None = None,
) -> CorrectionEvaluation:
    """Certify one correction, rejecting every partial or errored comparison.

    ``selector_factory`` is called separately for the baseline and candidate
    branch in every world.  It should return a fresh deterministic continuation
    policy; this prevents state accumulated in one branch from affecting the
    other branch.
    """

    config = config or CorrectionConfig()
    metric_config = metric_config or PublicMetricConfig()
    determinizer = determinizer or determinize_known_matchup
    clock = clock or time.monotonic
    obs = to_observation_class(observation) if isinstance(observation, dict) else observation
    baseline_semantic: SemanticAction | None = None
    candidate_semantic: SemanticAction | None = None
    boundary_hash = ""
    try:
        boundary_hash = public_boundary_hash(obs)
        baseline_semantic = semantic_action(obs, baseline_action)
        candidate_semantic = semantic_action(obs, candidate_action)
    except Exception as exc:
        reason = _error_reason(exc) if isinstance(exc, Exception) else "semantic_boundary_error"
        return CorrectionEvaluation(
            boundary_hash,
            baseline_semantic,
            candidate_semantic,
            (),
            {"baseline": 0, "candidate": 0},
            _failure_decision(reason, config.worlds, 0),
            (f"boundary:{type(exc).__name__}:{exc}",),
        )
    if baseline_semantic == candidate_semantic:
        return CorrectionEvaluation(
            boundary_hash,
            baseline_semantic,
            candidate_semantic,
            (),
            {"baseline": 0, "candidate": 0},
            _failure_decision("same_semantic_action", config.worlds, 0),
            (),
        )

    started = clock()
    deadline = started + config.timeout_seconds
    comparisons: list[WorldComparison] = []
    baseline_scores: dict[int, PublicMetricVector] = {}
    candidate_scores: dict[int, PublicMetricVector] = {}
    errors: list[str] = []
    for world_index in range(config.worlds):
        seed = crn_seed(config.seed, boundary_hash, world_index)
        try:
            baseline_metric, baseline_steps, candidate_metric, candidate_steps = _evaluate_world(
                obs,
                baseline_semantic,
                candidate_semantic,
                hero_deck,
                opponent_deck,
                selector_factory,
                config,
                metric_config,
                seed,
                determinizer,
                clock,
                deadline,
            )
        except Exception as exc:
            reason = _error_reason(exc)
            errors.append(f"world={world_index}:{type(exc).__name__}:{exc}")
            covered = len(comparisons)
            return CorrectionEvaluation(
                boundary_hash,
                baseline_semantic,
                candidate_semantic,
                tuple(comparisons),
                {"baseline": covered, "candidate": covered},
                _failure_decision(reason, config.worlds, covered),
                tuple(errors),
            )
        baseline_scores[world_index] = baseline_metric
        candidate_scores[world_index] = candidate_metric
        comparisons.append(
            WorldComparison(
                world_index,
                seed,
                baseline_metric,
                candidate_metric,
                baseline_steps,
                candidate_steps,
            )
        )

    decision = assess_admission(baseline_scores, candidate_scores, config.worlds)
    covered = len(comparisons)
    return CorrectionEvaluation(
        boundary_hash,
        baseline_semantic,
        candidate_semantic,
        tuple(comparisons),
        {"baseline": covered, "candidate": covered},
        decision,
        tuple(errors),
    )


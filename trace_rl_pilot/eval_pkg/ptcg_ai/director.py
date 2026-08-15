"""Deterministic, abstaining complete-turn planning for Marnie-Grim matchups.

The Director is deliberately independent of the retired scalar value head.  It
uses only public observations, legal engine continuations, terminal outcomes,
and an auditable lexicographic board evaluator.  Any incomplete comparison
returns the already-computed baseline action.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import random
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from cg.api import OptionType, SelectType, search_begin, search_end, search_release, search_step, to_observation_class

from .heuristic import GrimmsnarlHeuristic
from .safety import emergency_selection, sanitize_selection
from .search import determinize_state
from .tactical_shield import apply_tactical_shield
from .view import attached_energy_count, cards_in_play, damage_on, prize_value


MARNIE_LINE_IDS = frozenset({646, 647, 648})
STRATIFIED_IDS = frozenset({7, 648, 112, 1137, 1182, 1231})


class RouteStatus(str, Enum):
    INACTIVE = "inactive"
    COMPATIBLE = "compatible"
    DISQUALIFIED = "disqualified"


@dataclass(frozen=True)
class DeckHypothesis:
    name: str
    deck_sha256: str
    cards: tuple[int, ...]

    @classmethod
    def from_cards(cls, name: str, cards: Iterable[int]) -> "DeckHypothesis":
        normalized = tuple(sorted(map(int, cards)))
        if len(normalized) != 60:
            raise ValueError(f"deck hypothesis {name!r} has {len(normalized)} cards, expected 60")
        digest = hashlib.sha256(",".join(map(str, normalized)).encode("ascii")).hexdigest().upper()
        return cls(name=name, deck_sha256=digest, cards=normalized)


def _public_cards_with_serials(obs) -> tuple[tuple[int, int], ...]:
    """Opponent cards visible to the actor, never hand/deck/prize identities."""
    if obs.current is None:
        return ()
    opponent_index = 1 - int(obs.current.yourIndex)
    opponent = obs.current.players[opponent_index]
    result: set[tuple[int, int]] = set()

    def add_card(card) -> None:
        if card is not None and getattr(card, "id", None) is not None:
            result.add((int(card.id), int(getattr(card, "serial", -1))))

    def add_pokemon(card) -> None:
        if card is None:
            return
        add_card(card)
        for attr in ("energyCards", "tools", "preEvolution"):
            for attached in getattr(card, attr, None) or []:
                add_card(attached)

    for pokemon in (opponent.active or []) + (opponent.bench or []):
        add_pokemon(pokemon)
    for card in opponent.discard or []:
        add_card(card)
    for card in getattr(obs.current, "stadium", None) or []:
        if card is not None and int(card.playerIndex) == opponent_index:
            add_card(card)
    for log in obs.logs or []:
        if getattr(log, "playerIndex", None) == opponent_index and getattr(log, "cardId", None) is not None:
            result.add((int(log.cardId), int(getattr(log, "serial", -1) or -1)))
    return tuple(sorted(result))


@dataclass
class MirrorEvidenceState:
    status: RouteStatus = RouteStatus.INACTIVE
    visible_cards: dict[int, int] = field(default_factory=dict)
    visible_serials: set[tuple[int, int]] = field(default_factory=set)
    compatible_deck_hashes: set[str] = field(default_factory=set)
    activation_step: int | None = None
    disqualification_step: int | None = None

    def reset(self, hypotheses: Iterable[DeckHypothesis]) -> None:
        self.status = RouteStatus.INACTIVE
        self.visible_cards.clear()
        self.visible_serials.clear()
        self.compatible_deck_hashes = {item.deck_sha256 for item in hypotheses}
        self.activation_step = None
        self.disqualification_step = None

    def observe(self, obs, hypotheses: Iterable[DeckHypothesis], step: int) -> RouteStatus:
        if self.status == RouteStatus.DISQUALIFIED:
            return self.status
        by_hash = {item.deck_sha256: item for item in hypotheses}
        if not self.compatible_deck_hashes:
            self.compatible_deck_hashes = set(by_hash)
        for card_id, serial in _public_cards_with_serials(obs):
            self.visible_serials.add((card_id, serial))
        # Serial is the physical-instance key; multiplicity is therefore stable
        # when the same public card occurs in several successive observations.
        counts = Counter(card_id for card_id, _serial in self.visible_serials)
        self.visible_cards = dict(counts)
        compatible: set[str] = set()
        for digest in self.compatible_deck_hashes:
            hypothesis = by_hash.get(digest)
            if hypothesis is None:
                continue
            supply = Counter(hypothesis.cards)
            if all(count <= supply[card_id] for card_id, count in counts.items()):
                compatible.add(digest)
        self.compatible_deck_hashes = compatible
        if not compatible:
            self.status = RouteStatus.DISQUALIFIED
            self.disqualification_step = int(step)
        elif counts.keys() & MARNIE_LINE_IDS:
            if self.status == RouteStatus.INACTIVE:
                self.activation_step = int(step)
            self.status = RouteStatus.COMPATIBLE
        return self.status

    def telemetry(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["visible_serials"] = sorted([list(item) for item in self.visible_serials])
        payload["compatible_deck_hashes"] = sorted(self.compatible_deck_hashes)
        return payload


@dataclass(frozen=True)
class DirectorConfig:
    enabled: bool = True
    trigger: str = "first_high_impact"
    horizon: str = "turn_reply"
    max_root_actions: int = 12
    max_interior_actions: int = 6
    beam_width: int = 6
    max_nodes_per_world: int = 300
    max_native_steps: int = 3600
    min_complete_worlds: int = 8
    target_worlds: int = 12
    cvar_alpha: float = 0.25
    stop_expand_seconds: float = 260.0
    stop_engine_seconds: float = 280.0
    cleanup_seconds: float = 295.0
    hard_timeout_seconds: float = 300.0
    minimum_overage_reserve_seconds: float = 120.0
    seed_salt: str = "grim-director-v1"

    def __post_init__(self) -> None:
        if self.trigger not in {"first_high_impact", "first_robust_disagreement", "third_turn"}:
            raise ValueError(f"invalid Director trigger: {self.trigger}")
        if self.horizon not in {"turn", "turn_reply"}:
            raise ValueError(f"invalid Director horizon: {self.horizon}")
        if not (8 <= self.min_complete_worlds <= self.target_worlds):
            raise ValueError("Director requires at least eight complete worlds")
        if not (0 < self.cvar_alpha <= 1):
            raise ValueError("CVaR alpha must be in (0, 1]")
        if not (self.stop_expand_seconds < self.stop_engine_seconds < self.cleanup_seconds < self.hard_timeout_seconds):
            raise ValueError("Director deadlines must be strictly increasing")


@dataclass(frozen=True)
class TurnPlanRequest:
    observation: dict
    state_hash: str
    fallback_action: tuple[int, ...]
    proposal_actions: tuple[tuple[int, ...], ...]
    hero_deck: tuple[int, ...]
    hypotheses: tuple[DeckHypothesis, ...]
    config: DirectorConfig
    artifact_hashes: dict[str, str]


@dataclass
class TurnPlanResult:
    status: str
    action: list[int]
    semantic_plan: list[dict[str, Any]]
    world_coverage: dict[str, int]
    cvar_vector: list[float]
    trigger: str
    latency_seconds: float
    fallback_reason: str | None = None
    errors: list[str] = field(default_factory=list)
    state_hash: str = ""
    safety_intervention: str | None = None


def load_hypotheses(path: str | os.PathLike[str] | None, exact_deck: Iterable[int]) -> tuple[DeckHypothesis, ...]:
    exact = DeckHypothesis.from_cards("current_exact", exact_deck)
    if path is None or not Path(path).is_file():
        return (exact,)
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    hypotheses = [exact]
    for item in raw.get("hypotheses", []):
        candidate = DeckHypothesis.from_cards(str(item["name"]), item["cards"])
        if candidate.deck_sha256 not in {entry.deck_sha256 for entry in hypotheses}:
            hypotheses.append(candidate)
    return tuple(hypotheses)


def _primitive(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return int(value.value)
    if isinstance(value, (list, tuple)):
        return [_primitive(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _primitive(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    fields = getattr(value, "__dataclass_fields__", None)
    if fields:
        return {name: _primitive(getattr(value, name)) for name in fields if name != "search_begin_input"}
    return repr(value)


def public_state_hash(obs_or_dict: Any) -> str:
    obs = to_observation_class(obs_or_dict) if isinstance(obs_or_dict, dict) else obs_or_dict
    payload = {"select": _primitive(obs.select), "logs": _primitive(obs.logs), "current": _primitive(obs.current)}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def option_signature(option: Any) -> dict[str, Any]:
    names = ("type", "number", "area", "index", "playerIndex", "toolIndex", "energyIndex", "count", "inPlayArea", "inPlayIndex", "attackId", "cardId", "serial", "specialConditionType")
    return {name: _primitive(getattr(option, name, None)) for name in names}


def semantic_action(obs, action: Iterable[int]) -> dict[str, Any]:
    return {
        "select_type": _primitive(obs.select.type),
        "context": _primitive(obs.select.context),
        "options": [option_signature(obs.select.option[int(index)]) for index in action],
    }


def resolve_semantic_action(obs, semantic: dict[str, Any]) -> list[int] | None:
    if _primitive(obs.select.type) != semantic.get("select_type") or _primitive(obs.select.context) != semantic.get("context"):
        return None
    available: dict[str, list[int]] = {}
    for index, option in enumerate(obs.select.option):
        key = json.dumps(option_signature(option), sort_keys=True, separators=(",", ":"))
        available.setdefault(key, []).append(index)
    resolved: list[int] = []
    for signature in semantic.get("options", []):
        key = json.dumps(signature, sort_keys=True, separators=(",", ":"))
        choices = available.get(key, [])
        if not choices:
            return None
        resolved.append(choices.pop(0))
    if len(resolved) < int(obs.select.minCount) or len(resolved) > int(obs.select.maxCount):
        return None
    return resolved


def _action_priority(obs, action: list[int]) -> tuple[int, str]:
    types = [int(obs.select.option[index].type) for index in action]
    priority = {
        int(OptionType.ATTACK): 100,
        int(OptionType.ABILITY): 95,
        int(OptionType.EVOLVE): 90,
        int(OptionType.ATTACH): 85,
        int(OptionType.PLAY): 80,
        int(OptionType.RETREAT): 75,
        int(OptionType.END): 0,
    }
    return max((priority.get(item, 50) for item in types), default=40), json.dumps(semantic_action(obs, action), sort_keys=True)


def enumerate_complete_actions(obs, limit: int, proposals: Iterable[Iterable[int]] = ()) -> list[list[int]]:
    """Enumerate legal complete selections; sequential effects are expanded later."""
    select = obs.select
    if select is None:
        return []
    option_count = len(select.option)
    if option_count == 0:
        return [[]] if int(select.minCount) == 0 else []
    results: list[list[int]] = []
    seen: set[tuple[int, ...]] = set()
    preferred: list[list[int]] = []

    def add(action: Iterable[int]) -> None:
        raw = list(map(int, action))
        clean = tuple(sanitize_selection(select, raw, len(raw)))
        if int(select.minCount) <= len(clean) <= int(select.maxCount) and clean not in seen:
            seen.add(clean)
            results.append(list(clean))

    for proposal in proposals:
        proposal = list(proposal)
        if all(isinstance(item, int) and 0 <= item < option_count for item in proposal):
            add(proposal)
            if results:
                preferred.append(list(results[-1]))
    for count in range(int(select.minCount), int(select.maxCount) + 1):
        if count == 0:
            add([])
        else:
            for combination in itertools.combinations(range(option_count), count):
                add(combination)
                if len(results) >= max(limit * 8, 64):
                    break
        if len(results) >= max(limit * 8, 64):
            break
    results.sort(key=lambda action: _action_priority(obs, action), reverse=True)
    # END remains represented even when its lexical priority places it last.
    end = [action for action in results if any(obs.select.option[index].type == OptionType.END for index in action)]
    required: list[list[int]] = []
    for action in [*preferred, *(end[:1])]:
        if action not in required:
            required.append(action)
    trimmed = required[:limit]
    for action in results:
        if len(trimmed) >= limit:
            break
        if action not in trimmed:
            trimmed.append(action)
    return trimmed


def _terminal_value(state, root_player: int) -> tuple[float, float]:
    result = int(state.result)
    if result < 0:
        return 0.0, 0.0
    if result == 2:
        return 0.0, 0.0
    return (1.0, 0.0) if result == root_player else (0.0, 1.0)


def _board_vector(state, root_player: int, initial_prizes: int) -> tuple[float, ...]:
    me = state.players[root_player]
    opponent = state.players[1 - root_player]
    win, loss = _terminal_value(state, root_player)
    prizes_taken = float(initial_prizes - len(me.prize))
    prize_margin = float(len(opponent.prize) - len(me.prize))

    def ko_pressure(player) -> float:
        return sum(max(0.0, damage_on(card) / max(1.0, float(card.maxHp))) * prize_value(card) for card in cards_in_play(player))

    own = cards_in_play(me)
    active = me.active[0] if me.active else None
    ready_active = float(active is not None and active.id == 648 and attached_energy_count(active) >= 2)
    ready_backup = float(any(card.id == 648 and attached_energy_count(card) >= 2 for card in me.bench or []))
    munk_capacity = float(sum(1 for card in own if card.id == 112 and attached_energy_count(card) >= 1))
    development = sum({646: 0.5, 647: 1.0, 648: 2.0, 112: 0.75, 860: 0.4, 104: 0.9}.get(card.id, 0.0) for card in own)
    exposed = -sum(prize_value(card) * max(0.0, 1.0 - float(card.hp) / max(1.0, float(card.maxHp))) for card in own)
    froslass_risk = -sum(1.0 for card in own if card.id == 860 and card.hp <= 30)
    bench_roles = float(len({card.id for card in me.bench or []}) + 0.25 * max(0, int(me.benchMax) - len(me.bench or [])))
    scarce_ids = {1079, 1080, 1137, 1182, 1231}
    scarce = float(me.deckCount) - sum(1.0 for card in me.discard or [] if card.id in scarce_ids)
    return (win, -loss, prizes_taken, prize_margin, ko_pressure(opponent) - ko_pressure(me), ready_active + ready_backup + munk_capacity + development, exposed + froslass_risk, bench_roles, scarce)


def _cvar(values: list[float], alpha: float) -> float:
    if not values:
        return -math.inf
    take = max(1, int(math.ceil(len(values) * alpha)))
    return sum(sorted(values)[:take]) / take


@dataclass
class _Leaf:
    state: Any
    plan: list[dict[str, Any]]
    root_action: tuple[int, ...]
    depth: int


def _release(state, released: set[int]) -> None:
    search_id = int(state.searchId)
    if search_id not in released:
        search_release(search_id)
        released.add(search_id)


def _turn_complete(state, root_player: int, root_turn: int) -> bool:
    current = state.observation.current
    return current is None or int(current.result) >= 0 or int(current.yourIndex) != root_player or int(current.turn) != root_turn


def _adversarial_reply_vector(state, root_player: int, initial_prizes: int, config: DirectorConfig, deadline: float, released: set[int]) -> tuple[float, ...]:
    """Bound one opponent turn and return its worst completed public outcome."""
    current = state.observation.current
    if current is None or int(current.result) >= 0 or int(current.yourIndex) == root_player:
        vector = _board_vector(current, root_player, initial_prizes)
        _release(state, released)
        return vector
    reply_player = int(current.yourIndex)
    reply_turn = int(current.turn)
    frontier = [(state, 0)]
    completed: list[Any] = []
    nodes = 1
    heuristic = GrimmsnarlHeuristic()
    while frontier and nodes < 40:
        next_frontier: list[tuple[Any, int]] = []
        for parent, depth in frontier:
            observation = parent.observation
            finished = (
                observation.current is None
                or int(observation.current.result) >= 0
                or int(observation.current.yourIndex) != reply_player
                or int(observation.current.turn) != reply_turn
                or depth >= 12
            )
            if finished or observation.select is None:
                completed.append(parent)
                continue
            proposal = emergency_selection(observation.select)
            try:
                proposal = heuristic.choose(observation)
            except Exception:
                pass
            actions = enumerate_complete_actions(observation, config.max_interior_actions, [proposal])
            for action in actions:
                if time.monotonic() >= deadline:
                    raise TimeoutError("reply expansion deadline")
                child = search_step(parent.searchId, action)
                next_frontier.append((child, depth + 1))
                nodes += 1
                if nodes >= 40:
                    break
            _release(parent, released)
            if nodes >= 40:
                break
        # The adversary keeps the branches with the lowest root-player vector.
        next_frontier.sort(key=lambda pair: _board_vector(pair[0].observation.current, root_player, initial_prizes))
        frontier = next_frontier[:config.beam_width]
        for dropped, _depth in next_frontier[config.beam_width:]:
            _release(dropped, released)
    completed.extend(parent for parent, _depth in frontier)
    if not completed:
        raise RuntimeError("adversarial reply produced no complete branch")
    worst = min((_board_vector(item.observation.current, root_player, initial_prizes) for item in completed))
    for item in completed:
        _release(item, released)
    return worst


def _expand_one_world(obs, hero_deck: list[int], opponent_deck: list[int], seed: int, config: DirectorConfig, fallback_action: list[int], proposal_actions: list[list[int]], deadline: float) -> dict[tuple[int, ...], tuple[tuple[float, ...], list[dict[str, Any]]]]:
    rng = random.Random(seed)
    kwargs = determinize_state(obs, hero_deck, opponent_deck, rng)
    root = None
    released: set[int] = set()
    native_steps = 0
    try:
        root = search_begin(obs, manual_coin=True, **kwargs)
        root_player = int(obs.current.yourIndex)
        root_turn = int(obs.current.turn)
        initial_prizes = len(obs.current.players[root_player].prize)
        root_actions = enumerate_complete_actions(obs, config.max_root_actions, [fallback_action, *proposal_actions])
        if not root_actions:
            raise RuntimeError("no legal root actions")
        roots: dict[tuple[int, ...], _Leaf] = {}
        for action in root_actions:
            if time.monotonic() >= deadline:
                raise TimeoutError("world expansion deadline")
            child = search_step(root.searchId, action)
            native_steps += 1
            roots[tuple(action)] = _Leaf(child, [semantic_action(obs, action)], tuple(action), 1)
        _release(root, released)
        root = None
        heuristic = GrimmsnarlHeuristic()
        completed: dict[tuple[int, ...], list[_Leaf]] = {action: [] for action in roots}
        # Every root receives the same node allowance.  A missing completed leaf
        # therefore abstains instead of rewarding candidates visited earlier.
        allowance = max(2, config.max_nodes_per_world // max(1, len(roots)))
        for root_action in sorted(roots):
            frontier = [roots[root_action]]
            used = 1
            while frontier and used < allowance and native_steps < config.max_native_steps:
                next_frontier: list[_Leaf] = []
                # Expand the strongest current leaves first, but reserve enough
                # budget for a deterministic greedy path to reach turn end.
                frontier.sort(key=lambda leaf: _board_vector(leaf.state.observation.current, root_player, initial_prizes), reverse=True)
                for leaf in frontier:
                    current = leaf.state.observation
                    if _turn_complete(leaf.state, root_player, root_turn) or leaf.depth >= 40 or current.select is None:
                        completed[root_action].append(leaf)
                        continue
                    proposal = emergency_selection(current.select)
                    try:
                        proposal = heuristic.choose(current)
                    except Exception:
                        pass
                    remaining = allowance - used
                    # Near the cap, continue only the deterministic proposal;
                    # otherwise explore bounded semantic alternatives.
                    width = 1 if remaining <= max(3, leaf.depth) else min(config.max_interior_actions, remaining)
                    actions = enumerate_complete_actions(current, width, [proposal])
                    for action in actions:
                        if time.monotonic() >= deadline:
                            raise TimeoutError("world expansion deadline")
                        child = search_step(leaf.state.searchId, action)
                        native_steps += 1
                        used += 1
                        next_frontier.append(_Leaf(child, leaf.plan + [semantic_action(current, action)], root_action, leaf.depth + 1))
                        if used >= allowance or native_steps >= config.max_native_steps:
                            break
                    _release(leaf.state, released)
                    if used >= allowance or native_steps >= config.max_native_steps:
                        break
                next_frontier.sort(key=lambda leaf: _board_vector(leaf.state.observation.current, root_player, initial_prizes), reverse=True)
                frontier = next_frontier[:config.beam_width]
                for dropped in next_frontier[config.beam_width:]:
                    _release(dropped.state, released)
            for leaf in frontier:
                if _turn_complete(leaf.state, root_player, root_turn):
                    completed[root_action].append(leaf)
                else:
                    _release(leaf.state, released)
        output: dict[tuple[int, ...], tuple[tuple[float, ...], list[dict[str, Any]]]] = {}
        for root_action, leaves in completed.items():
            if not leaves:
                continue
            if config.horizon == "turn_reply":
                evaluated = [
                    (_adversarial_reply_vector(leaf.state, root_player, initial_prizes, config, deadline, released), leaf)
                    for leaf in leaves
                ]
            else:
                evaluated = [(_board_vector(leaf.state.observation.current, root_player, initial_prizes), leaf) for leaf in leaves]
            best_vector, best = max(evaluated, key=lambda pair: pair[0])
            output[root_action] = (best_vector, best.plan)
            for leaf in leaves:
                _release(leaf.state, released)
        return output
    finally:
        if root is not None:
            try:
                _release(root, released)
            except Exception:
                pass
        try:
            search_end()
        except Exception:
            pass


def plan_turn(request: TurnPlanRequest) -> TurnPlanResult:
    started = time.monotonic()
    obs = to_observation_class(request.observation)
    fallback = list(request.fallback_action)
    result = TurnPlanResult("abstained", fallback, [], {}, [], request.config.trigger, 0.0, state_hash=request.state_hash)
    if public_state_hash(obs) != request.state_hash:
        result.fallback_reason = "state_hash_mismatch"
        return result
    if obs.current is None or obs.select is None:
        result.fallback_reason = "inactive_observation"
        return result
    exact_hash = request.hypotheses[0].deck_sha256
    worlds: list[DeckHypothesis] = []
    variants = [item for item in request.hypotheses if item.deck_sha256 != exact_hash]
    for index in range(request.config.target_worlds):
        if index % 2 == 0 or not variants:
            worlds.append(request.hypotheses[0])
        else:
            worlds.append(variants[(index // 2) % len(variants)])
    scores: dict[tuple[int, ...], list[tuple[float, ...]]] = {}
    plans: dict[tuple[int, ...], list[list[dict[str, Any]]]] = {}
    errors: list[str] = []
    deadline = started + request.config.stop_expand_seconds
    expected_actions = {
        tuple(action)
        for action in enumerate_complete_actions(obs, request.config.max_root_actions, [fallback, *[list(action) for action in request.proposal_actions]])
    }
    for world_index, hypothesis in enumerate(worlds):
        digest = hashlib.sha256(f"{request.config.seed_salt}:{request.state_hash}:{hypothesis.deck_sha256}:{world_index}".encode()).digest()
        seed = int.from_bytes(digest[:8], "big")
        try:
            world = _expand_one_world(obs, list(request.hero_deck), list(hypothesis.cards), seed, request.config, fallback, [list(action) for action in request.proposal_actions], deadline)
            for action, (vector, plan) in world.items():
                scores.setdefault(action, []).append(vector)
                plans.setdefault(action, []).append(plan)
        except Exception as exc:
            errors.append(f"world={world_index}:{type(exc).__name__}:{exc}")
    coverage = {json.dumps(list(action)): len(scores.get(action, [])) for action in sorted(expected_actions)}
    result.world_coverage = coverage
    result.errors = errors
    eligible = {action: scores.get(action, []) for action in expected_actions if len(scores.get(action, [])) >= request.config.min_complete_worlds}
    if not eligible or any(len(scores.get(action, [])) < request.config.min_complete_worlds for action in expected_actions):
        result.fallback_reason = "incomplete_world_coverage"
        result.latency_seconds = time.monotonic() - started
        return result

    def aggregate(action: tuple[int, ...]) -> tuple[float, ...]:
        vectors = eligible[action]
        return tuple(_cvar([vector[index] for vector in vectors], request.config.cvar_alpha) for index in range(len(vectors[0])))

    selected = max(eligible, key=lambda action: (aggregate(action), action == tuple(fallback)))
    selected_plans = plans[selected]
    # Cache only a semantic prefix shared across every covered world.  Divergent
    # continuations are unsafe and correctly fall back during live execution.
    common: list[dict[str, Any]] = []
    for items in zip(*selected_plans):
        if all(item == items[0] for item in items):
            common.append(items[0])
        else:
            break
    result.status = "planned"
    result.action = list(selected)
    result.semantic_plan = common
    result.cvar_vector = list(aggregate(selected))
    result.latency_seconds = time.monotonic() - started
    return result


def _worker(request: TurnPlanRequest, output) -> None:
    try:
        output.put(asdict(plan_turn(request)))
    except BaseException as exc:  # worker boundary must never take down Kaggle agent
        output.put({"status": "abstained", "action": list(request.fallback_action), "semantic_plan": [], "world_coverage": {}, "cvar_vector": [], "trigger": request.config.trigger, "latency_seconds": 0.0, "fallback_reason": f"worker_exception:{type(exc).__name__}:{exc}", "errors": [], "state_hash": request.state_hash})


def _request_payload(request: TurnPlanRequest) -> dict[str, Any]:
    return asdict(request)


def _request_from_payload(payload: dict[str, Any]) -> TurnPlanRequest:
    return TurnPlanRequest(
        observation=payload["observation"],
        state_hash=str(payload["state_hash"]),
        fallback_action=tuple(map(int, payload["fallback_action"])),
        proposal_actions=tuple(tuple(map(int, action)) for action in payload["proposal_actions"]),
        hero_deck=tuple(map(int, payload["hero_deck"])),
        hypotheses=tuple(
            DeckHypothesis(str(item["name"]), str(item["deck_sha256"]), tuple(map(int, item["cards"])))
            for item in payload["hypotheses"]
        ),
        config=DirectorConfig(**payload["config"]),
        artifact_hashes={str(key): str(value) for key, value in payload.get("artifact_hashes", {}).items()},
    )


def worker_main() -> int:
    try:
        request = _request_from_payload(json.load(sys.stdin))
        print(json.dumps(asdict(plan_turn(request)), sort_keys=True))
        return 0
    except BaseException as exc:
        print(json.dumps({"worker_error": f"{type(exc).__name__}:{exc}"}, sort_keys=True))
        return 1


class TurnDirector:
    """Per-game parent controller enforcing the one-attempt/one-turn contract."""

    def __init__(self, hero_deck: Iterable[int], hypotheses: Iterable[DeckHypothesis], config: DirectorConfig, artifact_hashes: dict[str, str] | None = None):
        self.hero_deck = tuple(map(int, hero_deck))
        self.hypotheses = tuple(hypotheses)
        self.config = config
        self.artifact_hashes = dict(artifact_hashes or {})
        self.reset()

    def reset(self) -> None:
        self.consumed = False
        self.disabled = False
        self.planned_turn: int | None = None
        self.cache: list[dict[str, Any]] = []
        self.last_result: TurnPlanResult | None = None

    def _high_impact(self, obs) -> bool:
        if obs.select is None:
            return False
        if obs.select.type != SelectType.MAIN:
            context = int(obs.select.context)
            return context in {13, 14, 16, 25, 39, 40}
        types = {option.type for option in obs.select.option}
        return bool(types & {OptionType.ATTACK, OptionType.ABILITY}) or sum(option.type == OptionType.ATTACH for option in obs.select.option) >= 2

    def should_attempt(self, obs, own_turn_ordinal: int, proposals: Iterable[Iterable[int]]) -> bool:
        if not self.config.enabled or self.consumed or self.disabled or obs.current is None or obs.select is None:
            return False
        if self.config.trigger == "third_turn":
            return own_turn_ordinal >= 3
        if self.config.trigger == "first_robust_disagreement":
            normalized = {tuple(action) for action in proposals}
            return len(normalized) >= 2 and self._high_impact(obs)
        return self._high_impact(obs) or own_turn_ordinal >= 3

    def cached_action(self, obs) -> list[int] | None:
        if not self.cache or self.planned_turn != int(obs.current.turn):
            self.cache.clear()
            return None
        action = resolve_semantic_action(obs, self.cache[0])
        if action is None:
            self.cache.clear()
            return None
        self.cache.pop(0)
        return action

    def choose(self, obs_dict: dict, fallback_action: list[int], proposals: Iterable[Iterable[int]], own_turn_ordinal: int) -> list[int]:
        obs = to_observation_class(obs_dict)
        cached = self.cached_action(obs)
        if cached is not None:
            return cached
        raw_remaining = obs_dict.get("remainingOverageTime", math.inf)
        remaining = math.inf if raw_remaining is None else float(raw_remaining)
        if remaining < self.config.minimum_overage_reserve_seconds:
            self.disabled = True
            return fallback_action
        if not self.should_attempt(obs, own_turn_ordinal, proposals):
            return fallback_action
        self.consumed = True  # mark before worker start; failures never retry next turn
        state_hash = public_state_hash(obs)
        proposal_actions = tuple(tuple(map(int, action)) for action in proposals)
        request = TurnPlanRequest(obs_dict, state_hash, tuple(fallback_action), proposal_actions, self.hero_deck, self.hypotheses, self.config, self.artifact_hashes)
        environment = os.environ.copy()
        package_root = str(Path(__file__).resolve().parent.parent)
        environment["PYTHONPATH"] = package_root + os.pathsep + environment.get("PYTHONPATH", "")
        try:
            complete = subprocess.run(
                [sys.executable, "-m", "ptcg_ai.director", "--worker"],
                input=json.dumps(_request_payload(request), separators=(",", ":")),
                text=True,
                capture_output=True,
                timeout=self.config.hard_timeout_seconds,
                cwd=package_root,
                env=environment,
            )
        except subprocess.TimeoutExpired:
            self.disabled = True
            self.last_result = TurnPlanResult("abstained", fallback_action, [], {}, [], self.config.trigger, self.config.hard_timeout_seconds, "parent_timeout", state_hash=state_hash)
            return fallback_action
        try:
            if complete.returncode != 0:
                raise ValueError(complete.stdout.strip() or complete.stderr.strip() or "worker failed")
            payload = json.loads(complete.stdout.strip().splitlines()[-1])
            self.last_result = TurnPlanResult(**payload)
        except (IndexError, json.JSONDecodeError, TypeError, ValueError):
            self.disabled = True
            self.last_result = TurnPlanResult("abstained", fallback_action, [], {}, [], self.config.trigger, 0.0, "worker_no_result", state_hash=state_hash)
            return fallback_action
        if self.last_result.status != "planned":
            self.disabled = True
            return fallback_action
        self.planned_turn = int(obs.current.turn)
        # First semantic action is being returned now, cache only its suffix.
        self.cache = list(self.last_result.semantic_plan[1:])
        ranked = list(self.last_result.action) + [index for index in range(len(obs.select.option)) if index not in self.last_result.action]
        ranked, desired, intervention = apply_tactical_shield(obs, ranked, len(self.last_result.action))
        selected = sanitize_selection(obs.select, ranked, desired)
        self.last_result.safety_intervention = intervention
        if selected != self.last_result.action:
            self.cache.clear()
        return selected

    def telemetry(self) -> dict[str, Any]:
        return {
            "consumed": self.consumed,
            "disabled": self.disabled,
            "planned_turn": self.planned_turn,
            "cached_actions": len(self.cache),
            "last_result": asdict(self.last_result) if self.last_result is not None else None,
        }


if __name__ == "__main__":
    if "--worker" not in sys.argv:
        raise SystemExit("ptcg_ai.director is an internal worker module")
    raise SystemExit(worker_main())

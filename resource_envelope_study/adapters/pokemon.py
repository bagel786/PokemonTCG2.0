"""Three study-owned, budget-responsive search algorithms for one matchup.

All configurations use the same public observation, decks, proposal/value
models, and evaluation-only seeded engine.  They differ in search algorithm:

* ``one_ply_value`` averages neural values after one native transition;
* ``flat_rollout`` averages bounded policy rollouts;
* ``puct_tree`` performs incremental adversarial PUCT simulations.

One call to ``perform_unit`` is the declared work boundary.  No function in
this module reads a clock.
"""

from __future__ import annotations

import math
import random
import itertools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ..canonical import derive_u32, hash_json
from ..telemetry import WorkCounters
from .native_backend import SeededSearchBackend


def _semantic_public_state(value: Any) -> Any:
    """Drop opaque engine serialization and non-semantic presentation fields."""

    excluded = {
        "search_begin_input",
        "searchBeginInput",
        "log",
        "logs",
        "timestamp",
        "wall_time",
    }
    if isinstance(value, dict):
        return {
            str(key): _semantic_public_state(item)
            for key, item in value.items()
            if str(key) not in excluded
        }
    if isinstance(value, (list, tuple)):
        return [_semantic_public_state(item) for item in value]
    if hasattr(value, "__dict__"):
        return _semantic_public_state(vars(value))
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _terminal_value(state, root_player: int) -> float | None:
    current = state.observation.current
    if current is None:
        return 0.0
    result = int(current.result)
    if result < 0:
        return None
    if result == 2:
        return 0.0
    return 1.0 if result == root_player else -1.0


def _neural_value(model, observation, root_player: int) -> float:
    from ptcg_ai.features import encode_observation

    features = encode_observation(observation, model.feature_version)
    _logits, _counts, raw = model.predict(features)
    probability = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, float(raw)))))
    value = 2.0 * probability - 1.0
    return value if int(observation.current.yourIndex) == root_player else -value


def _determinize_study_matchup(
    observation,
    hero_deck: list[int],
    opponent_deck: list[int],
    rng: random.Random,
) -> dict[str, list[int]]:
    """Reconcile engine transient cards without assuming they left a zone.

    The engine sometimes exposes ``select.contextCard`` as a semantic effect
    object whose serial is absent from public zones but whose card remains in a
    counted hidden zone.  Other contexts expose a genuinely transient physical
    card.  We enumerate the at-most-two unique transient candidates and accept
    exactly one resulting hidden-zone partition.  Ambiguity is an error.
    """

    from training.search_teacher import (
        _card_ids,
        _card_serials,
        _partition_hidden,
        visible_zone_serials,
    )

    state = observation.current
    me = int(state.yourIndex)
    opponent = 1 - me
    looking = list(getattr(state, "looking", None) or [])
    known_serials = visible_zone_serials(state, me) | _card_serials(looking)
    transient_by_serial: dict[int, int] = {}
    for card in (
        getattr(observation.select, "contextCard", None),
        getattr(observation.select, "effect", None),
    ):
        if card is None or int(card.playerIndex) != me:
            continue
        serial = int(card.serial)
        if serial not in known_serials:
            transient_by_serial[serial] = int(card.id)
    transient = [
        card_id
        for _serial, card_id in sorted(transient_by_serial.items())
    ]
    successful: dict[
        tuple[tuple[int, ...], tuple[int, ...]],
        tuple[list[int], list[int], object],
    ] = {}
    for count in range(len(transient) + 1):
        for subset in itertools.combinations(transient, count):
            # Clone RNG state so failed hypotheses cannot perturb the accepted
            # determinization stream.
            trial_rng = random.Random()
            trial_rng.setstate(rng.getstate())
            try:
                your_deck, your_prize, _hand, _active = _partition_hidden(
                    hero_deck,
                    state,
                    me,
                    reveal_hand=True,
                    rng=trial_rng,
                    extra_known=_card_ids(looking) + list(subset),
                )
            except Exception:
                continue
            key = (tuple(your_deck), tuple(your_prize))
            successful[key] = (your_deck, your_prize, trial_rng.getstate())
    if len(successful) != 1:
        raise ValueError(
            "acting-player transient-card reconciliation yielded "
            f"{len(successful)} distinct partitions"
        )
    your_deck, your_prize, accepted_rng_state = next(iter(successful.values()))
    rng.setstate(accepted_rng_state)
    opponent_hidden_deck, opponent_prize, opponent_hand, opponent_active = _partition_hidden(
        opponent_deck,
        state,
        opponent,
        reveal_hand=False,
        rng=rng,
    )
    if observation.select.deck is not None:
        your_deck = []
    return {
        "your_deck": your_deck,
        "your_prize": your_prize,
        "opponent_deck": opponent_hidden_deck,
        "opponent_prize": opponent_prize,
        "opponent_hand": opponent_hand,
        "opponent_active": opponent_active,
    }


@dataclass(frozen=True)
class PokemonAdapterConfig:
    agent_id: str
    algorithm: str
    hero_deck_path: str
    hero_model_path: str
    opponent_deck_path: str
    opponent_model_path: str
    seeded_engine_path: str
    max_candidates: int = 8
    candidate_width: int = 8
    rollout_depth: int = 96
    tree_depth: int = 32
    puct_c: float = 1.5
    initialize_engine: bool = True

    def validate(self) -> None:
        if self.algorithm not in {"one_ply_value", "flat_rollout", "puct_tree"}:
            raise ValueError(f"unsupported search algorithm: {self.algorithm}")
        if self.max_candidates < 2:
            raise ValueError("at least two root candidates are required")
        if self.candidate_width <= 0 or self.rollout_depth <= 0 or self.tree_depth <= 0:
            raise ValueError("search bounds must be positive")


@dataclass
class _Edge:
    action: tuple[int, ...]
    prior: float
    visits: int = 0
    value_sum: float = 0.0
    child: "_Node | None" = None

    @property
    def mean(self) -> float:
        return self.value_sum / self.visits if self.visits else 0.0


@dataclass
class _Node:
    state: Any
    depth: int
    visits: int = 0
    value_sum: float = 0.0
    expanded: bool = False
    edges: dict[tuple[int, ...], _Edge] = field(default_factory=dict)


class PokemonSearchAdapter:
    def __init__(self, config: PokemonAdapterConfig):
        config.validate()
        from ptcg_ai.model import NumpyPolicyModel
        from training.search_teacher import load_deck

        self.config = config
        self.agent_id = config.agent_id
        self.hero_deck = load_deck(config.hero_deck_path)
        self.opponent_deck = load_deck(config.opponent_deck_path)
        self.hero_model = NumpyPolicyModel(config.hero_model_path)
        self.opponent_model = NumpyPolicyModel(config.opponent_model_path)
        self.backend = SeededSearchBackend(
            config.seeded_engine_path,
            initialize=config.initialize_engine,
        )
        self._instrumentation_enabled = True

    def configure_instrumentation(self, enabled: bool) -> None:
        self._instrumentation_enabled = bool(enabled)
        self.backend.configure_instrumentation(enabled)

    def reset_case(self, state: Any, agent_seed: int) -> None:
        from cg.api import to_observation_class

        self._raw_state = state
        self.observation = to_observation_class(state) if isinstance(state, dict) else state
        if self.observation.current is None or self.observation.select is None:
            raise ValueError("search adapter requires an active selection observation")
        self.agent_seed = int(agent_seed)
        self.root_player = int(self.observation.current.yourIndex)
        self.unit_index = 0
        self.scores: list[float] = []
        self.counts: list[int] = []
        self.root: _Node | None = None
        self._search_open = False
        self._semantic_hash = hash_json(_semantic_public_state(state))

    def _candidate_actions(self, observation, *, root: bool) -> list[tuple[list[int], float]]:
        from training.search_teacher import SearchConfig, candidate_actions

        model = self._model_for_observation(observation)
        return candidate_actions(
            model,
            observation,
            SearchConfig(
                max_candidates=self.config.max_candidates,
                candidate_width=self.config.candidate_width,
                candidate_mode="exhaustive" if root else "prior",
                seed=self.agent_seed,
            ),
        )

    def _model_for_observation(self, observation):
        return (
            self.hero_model
            if int(observation.current.yourIndex) == self.root_player
            else self.opponent_model
        )

    def _world(self, unit_index: int):
        determinization_seed = derive_u32(self.agent_seed, "determinization", unit_index)
        search_seed = derive_u32(self.agent_seed, "native_search", unit_index)
        kwargs = _determinize_study_matchup(
            self.observation,
            self.hero_deck,
            self.opponent_deck,
            random.Random(determinization_seed),
        )
        self.backend.reset_seed(search_seed)
        return kwargs

    def prepare(self) -> None:
        from training.search_teacher import SearchConfig, candidate_actions

        self.candidates = candidate_actions(
            self.hero_model,
            self.observation,
            SearchConfig(
                max_candidates=self.config.max_candidates,
                candidate_width=self.config.candidate_width,
                candidate_mode="exhaustive",
                seed=self.agent_seed,
            ),
        )
        if len(self.candidates) < 2:
            raise ValueError("decision is not search-eligible: fewer than two candidates")
        self.scores = [0.0] * len(self.candidates)
        self.counts = [0] * len(self.candidates)
        # PUCT root construction is deliberately lazy.  It belongs to the
        # first atomic simulation, so both a deadline and fixed-work N=1 cover
        # the same declared work boundary.

    def _flat_one_ply(self) -> WorkCounters | None:
        candidate_index = self.unit_index % len(self.candidates)
        kwargs = self._world(self.unit_index)
        root = None
        calls_before = self.backend.forward_model_calls if self._instrumentation_enabled else 0
        try:
            root = self.backend.begin(self.observation, kwargs)
            child = self.backend.step(root.searchId, self.candidates[candidate_index][0])
            terminal = _terminal_value(child, self.root_player)
            score = (
                terminal
                if terminal is not None
                else _neural_value(self._model_for_observation(child.observation), child.observation, self.root_player)
            )
            self.scores[candidate_index] += float(score)
            self.counts[candidate_index] += 1
        finally:
            if root is not None:
                try:
                    self.backend.release(root.searchId)
                finally:
                    self.backend.end()
            else:
                self.backend.end()
        if not self._instrumentation_enabled:
            return None
        calls = self.backend.forward_model_calls - calls_before
        return WorkCounters(work_units=1, simulations=1, nodes=1, forward_model_calls=calls)

    def _rollout_action(self, observation) -> list[int]:
        from training.search_teacher import deterministic_model_action

        return deterministic_model_action(self._model_for_observation(observation), observation)

    def _flat_rollout(self) -> WorkCounters | None:
        candidate_index = self.unit_index % len(self.candidates)
        kwargs = self._world(self.unit_index)
        root = None
        calls_before = self.backend.forward_model_calls if self._instrumentation_enabled else 0
        steps = 0
        try:
            root = self.backend.begin(self.observation, kwargs)
            current = self.backend.step(root.searchId, self.candidates[candidate_index][0])
            steps += 1
            score: float | None = _terminal_value(current, self.root_player)
            while score is None and steps < self.config.rollout_depth:
                if current.observation.select is None:
                    score = 0.0
                    break
                current = self.backend.step(
                    current.searchId,
                    self._rollout_action(current.observation),
                )
                steps += 1
                score = _terminal_value(current, self.root_player)
            if score is None:
                score = _neural_value(
                    self._model_for_observation(current.observation),
                    current.observation,
                    self.root_player,
                )
            self.scores[candidate_index] += float(score)
            self.counts[candidate_index] += 1
        finally:
            if root is not None:
                try:
                    self.backend.release(root.searchId)
                finally:
                    self.backend.end()
            else:
                self.backend.end()
        if not self._instrumentation_enabled:
            return None
        calls = self.backend.forward_model_calls - calls_before
        return WorkCounters(work_units=1, simulations=1, nodes=steps, forward_model_calls=calls)

    @staticmethod
    def _normalized_priors(candidates: list[tuple[list[int], float]]) -> list[float]:
        values = np.asarray([prior for _action, prior in candidates], dtype=np.float64)
        values -= float(np.max(values))
        weights = np.exp(values)
        weights /= float(np.sum(weights))
        return weights.tolist()

    def _expand(self, node: _Node, *, root: bool = False) -> int:
        terminal = _terminal_value(node.state, self.root_player)
        if terminal is not None or node.state.observation.select is None:
            node.expanded = True
            return 0
        candidates = self._candidate_actions(node.state.observation, root=root)
        priors = self._normalized_priors(candidates)
        node.edges = {
            tuple(action): _Edge(tuple(action), prior)
            for (action, _log_prior), prior in zip(candidates, priors)
        }
        node.expanded = True
        return 1

    def _select_edge(self, node: _Node) -> _Edge:
        root_to_move = int(node.state.observation.current.yourIndex) == self.root_player
        return max(
            node.edges.values(),
            key=lambda edge: (
                (edge.mean if root_to_move else -edge.mean)
                + self.config.puct_c
                * edge.prior
                * math.sqrt(max(1, node.visits))
                / (1 + edge.visits),
                edge.prior,
                tuple(-value for value in edge.action),
            ),
        )

    def _puct_simulation(self) -> WorkCounters | None:
        calls_before = self.backend.forward_model_calls if self._instrumentation_enabled else 0
        created_nodes = 0
        if self.root is None:
            kwargs = self._world(0)
            root_state = self.backend.begin(self.observation, kwargs)
            self._search_open = True
            self.root = _Node(root_state, 0)
            root_nodes = self._expand(self.root, root=True)
            if self._instrumentation_enabled:
                created_nodes += root_nodes
        node = self.root
        path: list[tuple[_Node, _Edge]] = []
        while True:
            terminal = _terminal_value(node.state, self.root_player)
            if terminal is not None:
                value = terminal
                break
            if node.depth >= self.config.tree_depth:
                value = _neural_value(
                    self._model_for_observation(node.state.observation),
                    node.state.observation,
                    self.root_player,
                )
                break
            if not node.expanded:
                expanded_nodes = self._expand(node)
                if self._instrumentation_enabled:
                    created_nodes += expanded_nodes
                value = _neural_value(
                    self._model_for_observation(node.state.observation),
                    node.state.observation,
                    self.root_player,
                )
                break
            if not node.edges:
                value = 0.0
                break
            edge = self._select_edge(node)
            if edge.child is None:
                child_state = self.backend.step(node.state.searchId, edge.action)
                edge.child = _Node(child_state, node.depth + 1)
            path.append((node, edge))
            node = edge.child
        node.visits += 1
        node.value_sum += value
        for parent, edge in reversed(path):
            edge.visits += 1
            edge.value_sum += value
            parent.visits += 1
            parent.value_sum += value
        if not self._instrumentation_enabled:
            return None
        calls = self.backend.forward_model_calls - calls_before
        return WorkCounters(
            work_units=1,
            simulations=1,
            nodes=created_nodes,
            forward_model_calls=calls,
        )

    def perform_unit(self) -> WorkCounters | None:
        if self.config.algorithm == "one_ply_value":
            result = self._flat_one_ply()
        elif self.config.algorithm == "flat_rollout":
            result = self._flat_rollout()
        else:
            result = self._puct_simulation()
        self.unit_index += 1
        return result

    def select_action(self) -> tuple[list[int], list[float | None], str]:
        if self.config.algorithm == "puct_tree":
            if self.root is None or not self.root.edges:
                return list(self.candidates[0][0]), [], "no_completed_tree_edge"
            root_edges = [self.root.edges.get(tuple(action)) for action, _prior in self.candidates]
            values: list[float | None] = [
                edge.mean if edge is not None and edge.visits > 0 else None
                for edge in root_edges
            ]
            visited = [
                index
                for index, edge in enumerate(root_edges)
                if edge is not None and edge.visits > 0
            ]
            if not visited:
                return list(self.candidates[0][0]), values, "no_completed_tree_edge"
            best = max(
                visited,
                key=lambda index: (
                    float(values[index]),
                    root_edges[index].visits if root_edges[index] is not None else 0,
                    self.candidates[index][1],
                    -index,
                ),
            )
            return list(self.candidates[best][0]), values, ""
        values: list[float | None] = [
            self.scores[index] / self.counts[index] if self.counts[index] else None
            for index in range(len(self.candidates))
        ]
        completed = [index for index, count in enumerate(self.counts) if count]
        if not completed:
            return list(self.candidates[0][0]), values, "no_completed_flat_evaluation"
        best = max(
            completed,
            key=lambda index: (
                float(values[index]) if values[index] is not None else -math.inf,
                self.candidates[index][1],
                -index,
            ),
        )
        return list(self.candidates[best][0]), values, ""  # type: ignore[return-value]

    def _release_tree(self) -> None:
        if self.root is None:
            return
        stack = [self.root]
        seen: set[int] = set()
        order: list[int] = []
        while stack:
            node = stack.pop()
            search_id = int(node.state.searchId)
            if search_id in seen:
                continue
            seen.add(search_id)
            order.append(search_id)
            stack.extend(edge.child for edge in node.edges.values() if edge.child is not None)
        failures: list[tuple[int, str, str]] = []
        for search_id in reversed(order):
            try:
                self.backend.release(search_id)
            except Exception as exc:
                failures.append((search_id, type(exc).__name__, str(exc)))
        if failures:
            raise RuntimeError(f"failed to release PUCT search IDs: {failures}")

    def cleanup(self) -> None:
        if self.config.algorithm == "puct_tree" and self._search_open:
            try:
                self._release_tree()
            finally:
                try:
                    self.backend.end()
                finally:
                    self._search_open = False

    def state_hash(self) -> str:
        return self._semantic_hash

    def action_identity(self, action: list[int]) -> dict[str, Any]:
        options = list(self.observation.select.option or [])
        selected: list[Any] = []
        for index in action:
            if 0 <= index < len(options):
                selected.append(_semantic_public_state(options[index]))
            else:
                selected.append({"invalid_option_index": index})
        return {
            "selected_options": selected,
            "selected_count": len(action),
        }


def default_agent_configs(
    *,
    hero_deck_path: str,
    hero_model_path: str,
    opponent_deck_path: str,
    opponent_model_path: str,
    seeded_engine_path: str,
    initialize_engine: bool = True,
) -> list[PokemonAdapterConfig]:
    common = {
        "hero_deck_path": hero_deck_path,
        "hero_model_path": hero_model_path,
        "opponent_deck_path": opponent_deck_path,
        "opponent_model_path": opponent_model_path,
        "seeded_engine_path": seeded_engine_path,
        "initialize_engine": initialize_engine,
    }
    return [
        PokemonAdapterConfig(
            agent_id="one_ply_value_v1",
            algorithm="one_ply_value",
            max_candidates=8,
            **common,
        ),
        PokemonAdapterConfig(
            agent_id="flat_rollout_v1",
            algorithm="flat_rollout",
            max_candidates=6,
            # The latency-only local smoke found that a 96-step atomic unit
            # could overshoot a 5 ms deadline by roughly 44 ms.  Sixteen steps
            # retain a genuinely multi-ply rollout while making the common
            # work boundary auditable at candidate final deadlines.
            rollout_depth=16,
            **common,
        ),
        PokemonAdapterConfig(
            agent_id="puct_tree_v1",
            algorithm="puct_tree",
            max_candidates=8,
            tree_depth=32,
            puct_c=1.5,
            **common,
        ),
    ]

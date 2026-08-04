"""Generic information-set PUCT teacher for training-only opponents.

The agent contains no deck/card tactics.  It samples hidden worlds consistent
with registered deck lists, covers every bounded legal root action, and then
uses adversarial PUCT over the engine forward model.  Neural checkpoints are
priors/value estimators and optional rollout policies, never the final policy.
"""

from __future__ import annotations

import math
import random
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

from cg.api import search_begin, search_end, search_release, search_step, to_observation_class
from ptcg_ai.features import encode_observation
from ptcg_ai.model import NumpyPolicyModel
from ptcg_ai.safety import emergency_selection
from training.search_teacher import (
    SearchConfig,
    candidate_actions,
    determinize_known_matchup,
    load_deck,
    rollout_to_outcome,
)


@dataclass(frozen=True)
class MCTSConfig:
    determinizations: int = 2
    simulations: int = 48
    max_depth: int = 64
    puct_c: float = 1.5
    root_max_candidates: int = 512
    tree_max_candidates: int = 8
    tree_candidate_width: int = 8
    leaf_rollout_steps: int = 0
    rollout_weight: float = 0.0
    seed: int = 20260803


@dataclass
class Edge:
    action: tuple[int, ...]
    prior: float
    visits: int = 0
    value_sum: float = 0.0
    child: "Node | None" = None

    @property
    def mean_value(self) -> float:
        return self.value_sum / self.visits if self.visits else 0.0


@dataclass
class Node:
    state: object
    depth: int
    visits: int = 0
    value_sum: float = 0.0
    expanded: bool = False
    edges: dict[tuple[int, ...], Edge] = field(default_factory=dict)


def puct_score(edge: Edge, parent_visits: int, root_to_move: bool, exploration: float) -> float:
    exploitation = edge.mean_value if root_to_move else -edge.mean_value
    bonus = exploration * edge.prior * math.sqrt(max(1, parent_visits)) / (1 + edge.visits)
    return exploitation + bonus


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


def neural_leaf_value(model: NumpyPolicyModel, obs, root_player: int) -> float:
    features = encode_observation(obs, model.feature_version)
    _logits, _counts, logit = model.predict(features)
    probability = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, float(logit)))))
    value = 2.0 * probability - 1.0
    return value if int(obs.current.yourIndex) == root_player else -value


def normalized_priors(candidates: list[tuple[list[int], float]]) -> list[float]:
    logs = np.asarray([prior for _action, prior in candidates], dtype=np.float64)
    logs -= float(np.max(logs))
    values = np.exp(logs)
    total = float(values.sum())
    return (values / total).tolist() if total > 0 else [1.0 / len(candidates)] * len(candidates)


class InformationSetMCTSAgent:
    def __init__(
        self,
        deck_path: str | Path,
        model_path: str | Path,
        opponent_deck_path: str | Path,
        opponent_model_path: str | Path,
        config: MCTSConfig | None = None,
    ):
        self.deck = load_deck(deck_path)
        self.opponent_deck = load_deck(opponent_deck_path)
        self.model = NumpyPolicyModel(model_path)
        self.opponent_model = NumpyPolicyModel(opponent_model_path)
        self.config = config or MCTSConfig()
        if self.config.determinizations <= 0 or self.config.simulations <= 0:
            raise ValueError("determinizations and simulations must be positive")
        if not 0.0 <= self.config.rollout_weight <= 1.0:
            raise ValueError("rollout_weight must be in [0, 1]")
        self.calls = 0
        self.search_errors = 0
        self.simulations = 0
        self.rollouts = 0
        self.nodes = 0
        self.error_counts: Counter[str] = Counter()
        self.last_error = ""

    def _model_for(self, state, root_player: int) -> NumpyPolicyModel:
        return self.model if int(state.observation.current.yourIndex) == root_player else self.opponent_model

    def _expand(self, node: Node, root_player: int, *, root: bool = False) -> None:
        terminal = _terminal_value(node.state, root_player)
        if terminal is not None or node.state.observation.select is None:
            node.expanded = True
            return
        model = self._model_for(node.state, root_player)
        candidate_config = SearchConfig(
            max_candidates=(self.config.root_max_candidates if root else self.config.tree_max_candidates),
            candidate_width=self.config.tree_candidate_width,
            candidate_mode=("exhaustive" if root else "prior"),
            seed=self.config.seed,
        )
        candidates = candidate_actions(model, node.state.observation, candidate_config)
        priors = normalized_priors(candidates)
        node.edges = {
            tuple(action): Edge(tuple(action), prior)
            for (action, _log_prior), prior in zip(candidates, priors)
        }
        node.expanded = True
        self.nodes += 1

    def _leaf_value(self, node: Node, root_player: int) -> float:
        terminal = _terminal_value(node.state, root_player)
        if terminal is not None:
            return terminal
        model = self._model_for(node.state, root_player)
        neural = neural_leaf_value(model, node.state.observation, root_player)
        if self.config.leaf_rollout_steps <= 0 or self.config.rollout_weight <= 0:
            return neural
        outcome = rollout_to_outcome(
            node.state,
            root_player,
            self.model,
            self.opponent_model,
            self.config.leaf_rollout_steps,
        )
        self.rollouts += 1
        weight = self.config.rollout_weight
        return (1.0 - weight) * neural + weight * outcome

    def _select_edge(self, node: Node, root_player: int) -> Edge:
        root_to_move = int(node.state.observation.current.yourIndex) == root_player
        return max(
            node.edges.values(),
            key=lambda edge: (
                puct_score(edge, node.visits, root_to_move, self.config.puct_c),
                edge.prior,
                tuple(-index for index in edge.action),
            ),
        )

    def _simulate(self, root: Node, root_player: int, forced_root_edge: Edge | None = None) -> None:
        node = root
        path: list[tuple[Node, Edge]] = []
        first = True
        try:
            while True:
                terminal = _terminal_value(node.state, root_player)
                if terminal is not None:
                    value = terminal
                    break
                if node.depth >= self.config.max_depth:
                    value = self._leaf_value(node, root_player)
                    break
                if not node.expanded:
                    self._expand(node, root_player, root=(node is root))
                    value = self._leaf_value(node, root_player)
                    break
                if not node.edges:
                    value = self._leaf_value(node, root_player)
                    break
                edge = forced_root_edge if first and forced_root_edge is not None else self._select_edge(node, root_player)
                first = False
                if edge.child is None:
                    child_state = search_step(node.state.searchId, list(edge.action))
                    edge.child = Node(child_state, node.depth + 1)
                path.append((node, edge))
                node = edge.child
        except Exception:
            raise
        node.visits += 1
        node.value_sum += value
        for parent, edge in reversed(path):
            edge.visits += 1
            edge.value_sum += value
            parent.visits += 1
            parent.value_sum += value
        self.simulations += 1

    @staticmethod
    def _release_tree(root: Node) -> None:
        stack = [root]
        seen = set()
        release_order = []
        while stack:
            node = stack.pop()
            search_id = int(node.state.searchId)
            if search_id in seen:
                continue
            seen.add(search_id)
            release_order.append(search_id)
            stack.extend(edge.child for edge in node.edges.values() if edge.child is not None)
        # Releasing the root after descendants lets the engine discard each branch safely.
        for search_id in reversed(release_order):
            try:
                search_release(search_id)
            except Exception:
                pass

    def __call__(self, obs_dict: dict) -> list[int]:
        if obs_dict.get("select") is None:
            return list(self.deck)
        obs = to_observation_class(obs_dict)
        fallback = candidate_actions(
            self.model,
            obs,
            SearchConfig(max_candidates=1, candidate_width=8, candidate_mode="prior"),
        )[0][0]
        self.calls += 1
        root_player = int(obs.current.yourIndex)
        aggregate: dict[tuple[int, ...], list[float]] = {}
        for world_index in range(self.config.determinizations):
            root = None
            try:
                rng = random.Random(self.config.seed + self.calls * 1_000_003 + world_index * 10_007)
                kwargs = determinize_known_matchup(obs, self.deck, self.opponent_deck, rng)
                root_state = search_begin(obs, **kwargs)
                root = Node(root_state, 0)
                self._expand(root, root_player, root=True)
                if not root.edges:
                    continue
                # Every root action receives evidence even if its neural prior is tiny.
                for edge in root.edges.values():
                    self._simulate(root, root_player, forced_root_edge=edge)
                remaining = max(0, self.config.simulations - len(root.edges))
                for _ in range(remaining):
                    self._simulate(root, root_player)
                for action, edge in root.edges.items():
                    totals = aggregate.setdefault(action, [0.0, 0.0])
                    totals[0] += edge.visits
                    totals[1] += edge.value_sum
            except Exception as exc:
                self.search_errors += 1
                key = f"{type(exc).__name__}: {exc}"
                self.error_counts[key] += 1
                self.last_error = key
            finally:
                if root is not None:
                    self._release_tree(root)
                try:
                    search_end()
                except Exception:
                    pass
        if not aggregate:
            return fallback
        best = max(
            aggregate,
            key=lambda action: (
                aggregate[action][1] / max(1.0, aggregate[action][0]),
                aggregate[action][0],
            ),
        )
        return list(best)

    def telemetry(self) -> dict:
        return {
            "search_calls": self.calls,
            "search_errors": self.search_errors,
            "search_rollouts": self.rollouts,
            "search_simulations": self.simulations,
            "search_nodes": self.nodes,
            "search_error_counts": dict(self.error_counts),
            "last_search_error": self.last_error,
        }

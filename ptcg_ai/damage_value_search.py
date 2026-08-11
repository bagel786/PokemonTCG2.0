"""Narrow value search for deterministic damage/healing target prompts in Grim mirrors."""

from __future__ import annotations

from collections import Counter
import math
import time

import numpy as np

from cg.api import SelectContext, search_begin, search_end, search_release, search_step

from .features import encode_observation
from .model import NeuralPolicy
from .search import OnePlySearchPolicy, determinize_state


GRIM_LINE = frozenset({646, 647, 648})
SAFE_TARGET_CONTEXTS = frozenset(
    {
        int(SelectContext.DAMAGE_COUNTER),
        int(SelectContext.DAMAGE_COUNTER_ANY),
        int(SelectContext.DAMAGE),
        int(SelectContext.REMOVE_DAMAGE_COUNTER),
        int(SelectContext.HEAL),
    }
)


def _card_ids(cards) -> set[int]:
    return {
        int(card.id)
        for card in cards or []
        if card is not None and getattr(card, "id", None) is not None
    }


def opponent_grim_line_visible(obs) -> bool:
    state = obs.current
    if state is None:
        return False
    opponent = state.players[1 - int(state.yourIndex)]
    visible = _card_ids(opponent.discard)
    for pokemon in list(opponent.active or []) + list(opponent.bench or []):
        if pokemon is None:
            continue
        visible.add(int(pokemon.id))
        visible.update(_card_ids(getattr(pokemon, "preEvolution", None)))
    for event in obs.logs or []:
        if event.playerIndex != state.yourIndex and event.cardId is not None:
            visible.add(int(event.cardId))
    return bool(visible & GRIM_LINE)


def damage_search_eligible(obs, *, min_turn: int) -> bool:
    if obs.current is None or obs.select is None:
        return False
    if int(obs.current.turn or 0) < min_turn:
        return False
    if int(obs.select.context) not in SAFE_TARGET_CONTEXTS:
        return False
    if int(obs.select.minCount) != 1 or int(obs.select.maxCount) != 1:
        return False
    if len(obs.select.option) < 2:
        return False
    return opponent_grim_line_visible(obs)


class IndependentRootOnePlySearch(OnePlySearchPolicy):
    """Evaluate each candidate from a fresh root and one frozen determinization."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.telemetry: Counter[str] = Counter()

    def evaluate_candidates(
        self,
        obs,
        candidates: list[list[int]],
        opponent_deck: list[int],
        *,
        priorities: dict[tuple[int, ...], int] | None = None,
    ) -> list[int] | None:
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        try:
            kwargs = determinize_state(obs, self.hero_deck, opponent_deck, self._rng)
        except Exception:
            self.telemetry["determinization_errors"] += 1
            return None

        priority = priorities or {
            tuple(action): index for index, action in enumerate(sorted(candidates))
        }
        started = time.perf_counter()
        scores: dict[tuple[int, ...], float] = {}
        your_idx = int(obs.current.yourIndex)
        for action in candidates[: self.max_candidates]:
            if (time.perf_counter() - started) * 1000.0 >= self.timeout_ms:
                self.telemetry["timeouts"] += 1
                return None
            root = child = None
            try:
                root = search_begin(obs, **kwargs)
                child = search_step(root.searchId, action)
                child_obs = child.observation
                child_curr = child_obs.current
                if child_curr is not None and int(child_curr.result) >= 0:
                    self.telemetry["terminal_children"] += 1
                    if int(child_curr.result) == 2:
                        score = 0.0
                    else:
                        score = 10.0 if int(child_curr.result) == your_idx else -10.0
                elif child_obs.select is not None and child_curr is not None:
                    if int(child_curr.yourIndex) != your_idx:
                        # This head was trained only on the hero's decision
                        # states. Negating an opponent-facing prediction would
                        # assume an unvalidated symmetry between different
                        # decks/policies, so reject the whole search attempt.
                        self.telemetry["opponent_to_act_rejections"] += 1
                        return None
                    self.telemetry["hero_to_act_children"] += 1
                    child_feat = encode_observation(child_obs, self.model.feature_version)
                    _, _, value = self.model.predict(child_feat)
                    score = value
                else:
                    self.telemetry["unscored_children"] += 1
                    return None
                scores[tuple(action)] = float(score)
                self.telemetry["completed_candidates"] += 1
            except Exception:
                self.telemetry["candidate_errors"] += 1
                return None
            finally:
                for state in (child, root):
                    if state is not None:
                        try:
                            search_release(state.searchId)
                        except Exception:
                            self.telemetry["release_errors"] += 1
                try:
                    search_end()
                except Exception:
                    self.telemetry["end_errors"] += 1

        if len(scores) != min(len(candidates), self.max_candidates):
            self.telemetry["incomplete"] += 1
            return None
        return list(
            min(
                scores,
                key=lambda action: (-scores[action], priority.get(action, math.inf), action),
            )
        )


class DamageValueSearchPolicy:
    """Preserve shielded A2 except at deterministic, fixed-count target prompts."""

    def __init__(
        self,
        path,
        fallback,
        hero_deck: list[int],
        *,
        min_turn: int = 6,
        ambiguity_margin: float = 0.35,
        timeout_ms: float = 50.0,
    ):
        self.base = NeuralPolicy(path, fallback)
        self.model = self.base.model
        self.search = IndependentRootOnePlySearch(
            self.model,
            list(hero_deck),
            ambiguity_margin=ambiguity_margin,
            timeout_ms=timeout_ms,
            max_candidates=3,
        )
        self.hero_deck = list(hero_deck)
        self.min_turn = int(min_turn)
        self.telemetry: Counter[str] = Counter()

    @property
    def shield_telemetry(self):
        return self.base.shield_telemetry

    def choose(self, obs) -> list[int]:
        greedy = self.base.choose(obs)
        if not damage_search_eligible(obs, min_turn=self.min_turn):
            return greedy
        self.telemetry["eligible"] += 1
        try:
            features = encode_observation(obs, self.model.feature_version)
            logits, count_logits, _value = self.model.predict(features)
            if not self.search.should_search(logits, count_logits, obs.select):
                self.telemetry["clear_margin"] += 1
                return greedy
            candidates = [greedy]
            for index in np.argsort(-logits).astype(int).tolist():
                candidate = [index]
                if candidate not in candidates:
                    candidates.append(candidate)
                if len(candidates) >= self.search.max_candidates:
                    break
            priorities = {tuple(action): index for index, action in enumerate(candidates)}
            self.telemetry["attempts"] += 1
            before_search = self.search.telemetry.copy()
            started = time.perf_counter()
            selected = self.search.evaluate_candidates(
                obs, candidates, self.hero_deck, priorities=priorities
            )
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            self.telemetry["search_ms_total"] += elapsed_ms
            self.telemetry["search_ms_max"] = max(
                self.telemetry["search_ms_max"], elapsed_ms
            )
            for name, value in self.search.telemetry.items():
                delta = value - before_search.get(name, 0)
                if delta:
                    self.telemetry[f"engine_{name}"] += delta
            if selected is None:
                self.telemetry["no_result"] += 1
                return greedy
            if selected != greedy:
                self.telemetry["overrides"] += 1
            return selected
        except Exception:
            self.telemetry["errors"] += 1
            return greedy

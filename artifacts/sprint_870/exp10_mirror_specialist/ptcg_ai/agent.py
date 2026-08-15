"""Competition-facing agent with fail-closed behavior."""

from __future__ import annotations

import os
from pathlib import Path

from cg.api import to_observation_class

from .card_ids import CYNTHIAS_GARCHOMP_EX
from .heuristic import GarchompHeuristic, GrimmsnarlHeuristic
from .safety import emergency_selection


GRIMMSNARL_MIRROR_PUBLIC_CARD_IDS = frozenset({646, 647, 648})


def _public_card_ids(obs) -> set[int]:
    state = obs.current
    opponent = state.players[1 - state.yourIndex]
    result: set[int] = set()

    def add_cards(cards) -> None:
        for card in cards or []:
            if card is not None and getattr(card, "id", None) is not None:
                result.add(int(card.id))

    def add_pokemon(pokemon) -> None:
        for card in pokemon or []:
            if card is None:
                continue
            result.add(int(card.id))
            add_cards(getattr(card, "energyCards", None))
            add_cards(getattr(card, "tools", None))
            add_cards(getattr(card, "preEvolution", None))

    add_pokemon(opponent.active)
    add_pokemon(opponent.bench)
    add_cards(opponent.discard)
    for log in obs.logs or []:
        if log.playerIndex != state.yourIndex and log.cardId is not None:
            result.add(int(log.cardId))
    return result


def grimmsnarl_mirror_publicly_detected(obs) -> bool:
    return bool(_public_card_ids(obs) & GRIMMSNARL_MIRROR_PUBLIC_CARD_IDS)


class CompetitionAgent:
    def __init__(
        self,
        deck_path: str | os.PathLike[str] | None = None,
        model_path: str | os.PathLike[str] | None = None,
    ):
        self.deck_path = Path(deck_path) if deck_path else self._find("deck.csv")
        self.deck = [int(line) for line in self.deck_path.read_text().splitlines() if line.strip()]
        if len(self.deck) != 60:
            raise ValueError(f"deck must contain exactly 60 cards, got {len(self.deck)}")
        fallback = GarchompHeuristic() if CYNTHIAS_GARCHOMP_EX in self.deck else GrimmsnarlHeuristic()
        prior_path = self._optional_find("elite_prior.json")
        if prior_path is not None:
            from .elite_prior import ElitePriorHeuristic

            fallback = ElitePriorHeuristic(prior_path, fallback)
        self.fallback = fallback
        model_path = Path(model_path) if model_path else self._optional_find("policy_weights.npz")
        policy_mode = os.environ.get("PTCG_POLICY", "auto").lower()
        if model_path is not None and policy_mode != "heuristic":
            from .model import NeuralPolicy

            self.policy = NeuralPolicy(model_path, fallback)
        else:
            self.policy = fallback
        mirror_model_path = self._optional_find("mirror_specialist.npz")
        self.mirror_specialist = (
            NeuralPolicy(mirror_model_path, fallback)
            if mirror_model_path is not None
            else None
        )
        self.mirror_routed = False
        self.errors = 0

    @staticmethod
    def _find(filename: str) -> Path:
        candidates = [Path(filename), Path("/kaggle_simulations/agent") / filename]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        raise FileNotFoundError(filename)

    @staticmethod
    def _optional_find(filename: str) -> Path | None:
        for candidate in [Path(filename), Path("/kaggle_simulations/agent") / filename]:
            if candidate.exists():
                return candidate
        return None

    def __call__(self, obs_dict: dict) -> list[int]:
        obs = to_observation_class(obs_dict)
        if obs.select is None:
            self.errors = 0
            self.mirror_routed = False
            if self.mirror_specialist is not None and hasattr(self.mirror_specialist, "reset"):
                self.mirror_specialist.reset()
            return list(self.deck)
        try:
            if (
                not self.mirror_routed
                and self.mirror_specialist is not None
                and grimmsnarl_mirror_publicly_detected(obs)
            ):
                self.mirror_routed = True
            if self.mirror_routed and self.mirror_specialist is not None:
                return self.mirror_specialist.choose(obs)
            return self.policy.choose(obs)
        except Exception:
            self.errors += 1
            try:
                return self.fallback.choose(obs)
            except Exception:
                return emergency_selection(obs.select)

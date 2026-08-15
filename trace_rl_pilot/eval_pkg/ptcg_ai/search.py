"""Selective 1-Ply Forward Search Policy for Live Competition Agent."""

from __future__ import annotations

import itertools
import math
import os
import random
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from cg.api import (
    all_card_data,
    search_begin,
    search_end,
    search_release,
    search_step,
    to_observation_class,
)

from .card_ids import CYNTHIAS_GARCHOMP_EX
from .features import encode_observation
from .model import NumpyPolicyModel
from .safety import emergency_selection, sanitize_selection


def _card_ids(cards) -> list[int]:
    return [int(card.id) for card in cards or [] if card is not None and getattr(card, "id", None) is not None]


def _pokemon_card_ids(pokemon) -> list[int]:
    result: list[int] = []
    for card in pokemon or []:
        if card is None:
            continue
        if getattr(card, "id", None) is not None:
            result.append(int(card.id))
        result.extend(_card_ids(getattr(card, "energyCards", None)))
        result.extend(_card_ids(getattr(card, "tools", None)))
        result.extend(_card_ids(getattr(card, "preEvolution", None)))
    return result


def _card_serials(cards) -> set[int]:
    return {int(card.serial) for card in cards or [] if card is not None and getattr(card, "serial", None) is not None}


def visible_zone_serials(state, player_index: int) -> set[int]:
    player = state.players[player_index]
    result = _card_serials(player.hand) | _card_serials(player.discard) | _card_serials(player.prize)
    result |= {
        int(card.serial)
        for card in state.stadium or []
        if card is not None and int(card.playerIndex) == player_index and getattr(card, "serial", None) is not None
    }
    for pokemon_zone in (player.active, player.bench):
        for pokemon_card in pokemon_zone or []:
            if pokemon_card is None:
                continue
            if getattr(pokemon_card, "serial", None) is not None:
                result.add(int(pokemon_card.serial))
            result |= _card_serials(getattr(pokemon_card, "energyCards", None))
            result |= _card_serials(getattr(pokemon_card, "tools", None))
            result |= _card_serials(getattr(pokemon_card, "preEvolution", None))
    return result


def visible_zone_cards(state, player_index: int, include_hand: bool) -> list[int]:
    player = state.players[player_index]
    result = _pokemon_card_ids(player.active) + _pokemon_card_ids(player.bench)
    result.extend(_card_ids(player.discard))
    result.extend(
        int(card.id)
        for card in state.stadium or []
        if card is not None and int(card.playerIndex) == player_index and getattr(card, "id", None) is not None
    )
    if include_hand:
        result.extend(_card_ids(player.hand))
    return result


_BASIC_CARD_IDS_CACHE: frozenset[int] | None = None


def get_basic_card_ids() -> frozenset[int]:
    global _BASIC_CARD_IDS_CACHE
    if _BASIC_CARD_IDS_CACHE is None:
        try:
            _BASIC_CARD_IDS_CACHE = frozenset(int(card.cardId) for card in all_card_data() if bool(card.basic))
        except Exception:
            _BASIC_CARD_IDS_CACHE = frozenset()
    return _BASIC_CARD_IDS_CACHE


def _subtract_known(full_deck: list[int], known: list[int], label: str) -> list[int]:
    pool = Counter(map(int, full_deck))
    for card_id in known:
        if pool[card_id] <= 0:
            raise ValueError(f"{label}: visible card {card_id} exceeds deck multiplicity")
        pool[card_id] -= 1
    return list(pool.elements())


def _partition_hidden(
    full_deck: list[int],
    state,
    player_index: int,
    *,
    reveal_hand: bool,
    rng: random.Random,
    extra_known: list[int] | None = None,
) -> tuple[list[int], list[int], list[int], list[int]]:
    player = state.players[player_index]
    known_prizes = _card_ids(player.prize)
    known = (
        visible_zone_cards(state, player_index, include_hand=reveal_hand)
        + known_prizes
        + list(extra_known or [])
    )
    pool = _subtract_known(full_deck, known, f"player {player_index}")
    rng.shuffle(pool)

    hidden_active: list[int] = []
    active = player.active or []
    if active and active[0] is None:
        basics = get_basic_card_ids()
        basic_index = next((index for index, card_id in enumerate(pool) if card_id in basics), None)
        if basic_index is None:
            raise ValueError(f"player {player_index}: face-down active has no Basic candidate")
        hidden_active = [pool.pop(basic_index)]

    hand_count = 0 if reveal_hand else int(player.handCount)
    hidden_prize_count = len(player.prize) - len(known_prizes)
    expected = int(player.deckCount) + hand_count + hidden_prize_count
    if len(pool) != expected:
        raise ValueError(
            f"player {player_index}: hidden pool has {len(pool)} cards, expected {expected} "
            f"(deck={player.deckCount}, hand={hand_count}, prize={hidden_prize_count})"
        )
    deck_end = int(player.deckCount)
    prize_end = deck_end + hidden_prize_count
    deck = pool[:deck_end]
    prizes = known_prizes + pool[deck_end:prize_end]
    hand = pool[prize_end:]
    return deck, prizes, hand, hidden_active


def determinize_state(
    obs,
    acting_deck: list[int],
    opponent_deck: list[int],
    rng: random.Random,
) -> dict:
    state = obs.current
    if state is None or obs.select is None:
        raise ValueError("search requires a live selection observation")
    me = int(state.yourIndex)
    opponent = 1 - me
    looking = getattr(state, "looking", None)
    known_serials = visible_zone_serials(state, me) | _card_serials(looking)
    transient: list[int] = []
    for card in (getattr(obs.select, "contextCard", None), getattr(obs.select, "effect", None)):
        if (
            card is not None
            and int(card.playerIndex) == me
            and int(card.serial) not in known_serials
            and getattr(card, "id", None) is not None
        ):
            transient.append(int(card.id))
            known_serials.add(int(card.serial))
    your_deck, your_prize, _, _your_hidden_active = _partition_hidden(
        acting_deck,
        state,
        me,
        reveal_hand=True,
        rng=rng,
        extra_known=_card_ids(looking) + transient,
    )
    opponent_hidden_deck, opponent_prize, opponent_hand, opponent_active = _partition_hidden(
        opponent_deck, state, opponent, reveal_hand=False, rng=rng
    )

    if obs.select.deck is not None:
        your_deck = []

    return {
        "your_deck": your_deck,
        "your_prize": your_prize,
        "opponent_deck": opponent_hidden_deck,
        "opponent_prize": opponent_prize,
        "opponent_hand": opponent_hand,
        "opponent_active": opponent_active,
    }


def load_deck_file(path: str | Path) -> list[int] | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        cards = [int(line) for line in p.read_text().splitlines() if line.strip()]
        if len(cards) == 60:
            return cards
    except Exception:
        pass
    return None


from .archetypes import COMPETITIVE_ARCHETYPES


class ArchetypeRegistry:
    """Maintains known competitive decklists and identifies opponent archetypes."""

    def __init__(self, root_dir: Path | None = None):
        self.root = root_dir or Path(__file__).resolve().parents[1]
        self.archetypes: dict[str, list[int]] = {
            name: list(deck) for name, deck in COMPETITIVE_ARCHETYPES.items()
        }
        self.archetype_sets: dict[str, frozenset[int]] = {
            name: frozenset(deck) for name, deck in COMPETITIVE_ARCHETYPES.items()
        }
        self._load_known_decks()

    def _load_known_decks(self) -> None:
        candidates = [
            ("grimmsnarl", self.root / "decks" / "grimmsnarl.csv"),
            ("grimmsnarl", self.root / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv"),
            ("alakazam", self.root / "freshstart" / "decklists" / "alakazam_dudunsparce.deck.csv"),
            ("crustle", self.root / "freshstart" / "decklists" / "kangaskhan_crustle.deck.csv"),
            ("lucario", self.root / "freshstart" / "decklists" / "mega_lucario_ex.deck.csv"),
            ("mewtwo", self.root / "freshstart" / "decklists" / "team_rockets_mewtwo_ex.deck.csv"),
            ("garchomp", self.root / "freshstart" / "decklists" / "cynthias_garchomp_ex.deck.csv"),
            ("dragapult", self.root / "freshstart" / "decklists" / "dragapult_ex.deck.csv"),
            ("bellibolt", self.root / "freshstart" / "decklists" / "iono_bellibolt_ex.deck.csv"),
        ]
        for name, path in candidates:
            if name not in self.archetypes:
                deck = load_deck_file(path)
                if deck is not None:
                    self.archetypes[name] = deck
                    self.archetype_sets[name] = frozenset(deck)

    def match(self, opponent_visible_ids: set[int]) -> tuple[str | None, list[int] | None, float]:
        """Compute Jaccard similarity against known archetypes."""
        if not opponent_visible_ids or not self.archetype_sets:
            # Default to Grimmsnarl mirror if no cards revealed yet (high-stakes default)
            grim = self.archetypes.get("grimmsnarl")
            return ("grimmsnarl", grim, 1.0) if grim is not None else (None, None, 0.0)

        best_name: str | None = None
        best_deck: list[int] | None = None
        best_jaccard = 0.0

        for name, card_set in self.archetype_sets.items():
            intersection = len(opponent_visible_ids & card_set)
            union = len(opponent_visible_ids | card_set)
            jaccard = intersection / max(1, union)
            coverage = intersection / max(1, len(opponent_visible_ids))
            score = max(jaccard, coverage * 0.8)

            if score > best_jaccard:
                best_jaccard = score
                best_name = name
                best_deck = self.archetypes[name]

        return best_name, best_deck, best_jaccard


class OnePlySearchPolicy:
    """Selective 1-ply forward search evaluator using native engine and Value Head."""

    def __init__(
        self,
        model: NumpyPolicyModel,
        hero_deck: list[int],
        registry: ArchetypeRegistry | None = None,
        ambiguity_margin: float = 0.35,
        jaccard_threshold: float = 0.35,
        timeout_ms: float = 50.0,
        max_candidates: int = 3,
    ):
        self.model = model
        self.hero_deck = hero_deck
        self.registry = registry or ArchetypeRegistry()
        self.ambiguity_margin = ambiguity_margin
        self.jaccard_threshold = jaccard_threshold
        self.timeout_ms = timeout_ms
        self.max_candidates = max_candidates
        self._rng = random.Random(20260805)

    def should_search(self, logits: np.ndarray, count_logits: np.ndarray, select) -> bool:
        """Determine if decision is ambiguous enough to warrant forward search."""
        if len(logits) <= 1:
            return False
        sorted_logits = np.sort(logits)[::-1]
        top1, top2 = float(sorted_logits[0]), float(sorted_logits[1])
        if (top1 - top2) >= self.ambiguity_margin:
            return False
        return True

    def evaluate_candidates(
        self,
        obs,
        candidates: list[list[int]],
        opponent_deck: list[int],
    ) -> list[int] | None:
        """Simulate top candidate moves 1-ply with guaranteed C++ memory release."""
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        start_time = time.perf_counter()
        best_action: list[int] | None = None
        best_score = -math.inf

        root = None
        try:
            kwargs = determinize_state(obs, self.hero_deck, opponent_deck, self._rng)
            root = search_begin(obs, **kwargs)
            your_idx = int(obs.current.yourIndex)

            for action in candidates[: self.max_candidates]:
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                if elapsed_ms >= self.timeout_ms:
                    break

                child = None
                try:
                    child = search_step(root.searchId, action)
                    child_obs = child.observation
                    child_curr = child_obs.current

                    if child_curr is not None and int(child_curr.result) >= 0:
                        if int(child_curr.result) == 2:
                            score = 0.0
                        else:
                            score = 10.0 if int(child_curr.result) == your_idx else -10.0
                    elif child_obs.select is not None:
                        child_feat = encode_observation(child_obs, self.model.feature_version)
                        _, _, val = self.model.predict(child_feat)
                        if int(child_curr.yourIndex) == your_idx:
                            score = val
                        else:
                            score = -val
                    else:
                        score = 0.0

                    if score > best_score:
                        best_score = score
                        best_action = action
                except Exception:
                    continue
                finally:
                    if child is not None:
                        try:
                            search_release(child.searchId)
                        except Exception:
                            pass
        except Exception:
            return None
        finally:
            if root is not None:
                try:
                    search_release(root.searchId)
                except Exception:
                    pass
            try:
                search_end()
            except Exception:
                pass

        return best_action

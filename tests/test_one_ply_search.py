"""Unit tests and latency benchmarks for OnePlySearchPolicy."""

from __future__ import annotations

import os
import random
import sys
import time
from collections import Counter
from types import SimpleNamespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np

from ptcg_ai.search import (
    ArchetypeRegistry,
    OnePlySearchPolicy,
    determinize_state,
)


def card(card_id, player=0, serial=None):
    return SimpleNamespace(id=card_id, playerIndex=player, serial=card_id if serial is None else serial)


def pokemon(card_id, player=0):
    return SimpleNamespace(
        id=card_id,
        playerIndex=player,
        serial=card_id,
        energyCards=[],
        tools=[],
        preEvolution=[],
    )


def test_archetype_registry_matching():
    registry = ArchetypeRegistry()
    assert len(registry.archetypes) > 0

    # Test Grimmsnarl matching
    grim_deck = registry.archetypes.get("grimmsnarl")
    if grim_deck:
        visible_grim = set(grim_deck[:10])
        name, matched_deck, score = registry.match(visible_grim)
        assert name == "grimmsnarl"
        assert score >= 0.35
        assert matched_deck is not None

    # Test off-meta / rogue deck triggering low Jaccard
    rogue_cards = {99901, 99902, 99903, 99904}
    name, matched_deck, score = registry.match(rogue_cards)
    assert score < 0.35


def test_ambiguity_trigger():
    policy = OnePlySearchPolicy(
        model=None,
        hero_deck=[1] * 60,
        ambiguity_margin=0.35,
    )
    select = SimpleNamespace(minCount=1, maxCount=1, option=[0, 1])

    # Case 1: Clear best action (gap = 1.0 >= 0.35) -> No search
    clear_logits = np.array([2.5, 1.0], dtype=np.float32)
    assert not policy.should_search(clear_logits, np.array([0.0]), select)

    # Case 2: Ambiguous action (gap = 0.15 < 0.35) -> Should search
    ambiguous_logits = np.array([2.15, 2.0], dtype=np.float32)
    assert policy.should_search(ambiguous_logits, np.array([0.0]), select)

    # Case 3: Single option -> No search
    single_logit = np.array([1.5], dtype=np.float32)
    assert not policy.should_search(single_logit, np.array([0.0]), select)


def test_determinize_state_preserves_card_counts():
    own_deck = [1, 2, 3, 4]
    opponent_deck = [5, 6, 7, 8, 9]
    own = SimpleNamespace(
        active=[pokemon(2, 0)],
        bench=[],
        discard=[],
        prize=[None],
        hand=[card(1, 0)],
        handCount=1,
        deckCount=1,
    )
    opponent = SimpleNamespace(
        active=[pokemon(5, 1)],
        bench=[],
        discard=[card(6, 1)],
        prize=[None],
        hand=None,
        handCount=1,
        deckCount=1,
    )
    state = SimpleNamespace(yourIndex=0, players=[own, opponent], stadium=[])
    obs = SimpleNamespace(current=state, select=SimpleNamespace(deck=None, contextCard=None, effect=None))
    
    result = determinize_state(obs, own_deck, opponent_deck, random.Random(42))
    assert Counter(result["your_deck"] + result["your_prize"] + [1, 2]) == Counter(own_deck)
    assert Counter(result["opponent_deck"] + result["opponent_prize"] + result["opponent_hand"] + [5, 6]) == Counter(opponent_deck)


if __name__ == "__main__":
    print("Running test_archetype_registry_matching...")
    test_archetype_registry_matching()
    print("Running test_ambiguity_trigger...")
    test_ambiguity_trigger()
    print("Running test_determinize_state_preserves_card_counts...")
    test_determinize_state_preserves_card_counts()
    print("All unit tests passed successfully!")


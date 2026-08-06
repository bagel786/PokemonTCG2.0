"""Acceptance tests for the Grimmsnarl-mirror public-information router.

Covers the plan's router requirements: detection per identifier (646/647/648),
permanent latch, game reset, no private-information access, search-disabled
greedy specialist wiring, and non-mirror parity (dormant when no specialist is
bundled -> behavior is exactly the v2.2 base policy).
"""

from pathlib import Path

import pytest

import ptcg_ai.agent as agent_module
from ptcg_ai.agent import (
    CompetitionAgent,
    grimmsnarl_mirror_publicly_detected,
    lucario_publicly_detected,
)

from tests.test_grim_lucario_router import observation

ROOT = Path(__file__).resolve().parents[1]
REAL_WEIGHTS = ROOT / "artifacts" / "v2_model" / "policy_weights.npz"
DECK = ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv"


@pytest.mark.parametrize("mirror_id", [646, 647, 648])
def test_detects_each_mirror_identifier(mirror_id):
    assert grimmsnarl_mirror_publicly_detected(observation(opponent_cards=[mirror_id]))
    assert grimmsnarl_mirror_publicly_detected(observation(opponent_bench=[mirror_id]))
    assert grimmsnarl_mirror_publicly_detected(observation(opponent_discard=[mirror_id]))


def test_no_detection_on_neutral_or_own_cards():
    assert not grimmsnarl_mirror_publicly_detected(observation(opponent_cards=[100, 200]))
    # Our own Grimmsnarl line must not trip mirror detection.
    assert not grimmsnarl_mirror_publicly_detected(observation(own_cards=[646, 647, 648]))


def test_never_inspects_private_zones():
    """Mirror identifiers hidden in the opponent's hand/deck must NOT be detected."""
    assert not grimmsnarl_mirror_publicly_detected(
        observation(opponent_hand=[648], opponent_deck=[646, 647])
    )
    # Same identifiers, but now publicly visible -> detected.
    assert grimmsnarl_mirror_publicly_detected(observation(opponent_cards=[648]))


def test_mirror_and_lucario_detectors_are_disjoint():
    assert not lucario_publicly_detected(observation(opponent_cards=[646, 647, 648]))
    assert not grimmsnarl_mirror_publicly_detected(observation(opponent_cards=[677, 678]))


def _fake_agent(monkeypatch, *, has_mirror=True):
    monkeypatch.setattr(agent_module, "to_observation_class", lambda value: value)
    calls = []

    class Policy:
        def __init__(self, name):
            self.name = name

        def choose(self, obs):
            calls.append(self.name)
            return [0]

    agent = CompetitionAgent.__new__(CompetitionAgent)
    agent.deck = [1] * 60
    agent.policy = Policy("base")
    agent.specialist = Policy("lucario")
    agent.mirror_specialist = Policy("mirror") if has_mirror else None
    agent.fallback = Policy("fallback")
    agent.lucario_routed = False
    agent.mirror_routed = False
    agent.errors = 0
    return agent, calls


def test_mirror_router_latches_for_rest_of_game(monkeypatch):
    agent, calls = _fake_agent(monkeypatch)

    assert agent(observation(opponent_cards=[100])) == [0]      # pre-reveal -> base
    assert agent(observation(opponent_cards=[646])) == [0]      # reveal -> mirror
    assert agent(observation(opponent_cards=[100])) == [0]      # latched -> mirror
    assert agent(observation(opponent_bench=[999])) == [0]      # still latched
    assert calls == ["base", "mirror", "mirror", "mirror"]


def test_mirror_latch_resets_on_deck_handshake(monkeypatch):
    agent, calls = _fake_agent(monkeypatch)

    assert agent(observation(opponent_cards=[647])) == [0]
    assert agent.mirror_routed
    # Deck-handshake observation (select is None) resets latches for the next game.
    assert agent(observation(select=False)) == [1] * 60
    assert not agent.mirror_routed
    assert agent(observation(opponent_cards=[100])) == [0]
    assert calls == ["mirror", "base"]


def test_mirror_takes_precedence_over_lucario(monkeypatch):
    """If somehow both are present, the mirror specialist wins the route."""
    agent, calls = _fake_agent(monkeypatch)
    assert agent(observation(opponent_cards=[648, 677])) == [0]
    assert calls == ["mirror"]


def test_dormant_when_no_specialist_is_base_policy(monkeypatch):
    """No mirror_specialist bundled -> mirror reveal still routes to base (v2.2 parity)."""
    agent, calls = _fake_agent(monkeypatch, has_mirror=False)
    assert agent(observation(opponent_cards=[648])) == [0]
    assert agent(observation(opponent_cards=[646])) == [0]
    assert calls == ["base", "base"]
    assert not agent.mirror_routed


@pytest.mark.skipif(
    not REAL_WEIGHTS.exists() or not DECK.exists(),
    reason="requires bundled v2 weights + deck",
)
def test_specialist_is_greedy_search_disabled():
    """Real construction: the mirror specialist must have live search disabled."""
    agent = CompetitionAgent(
        deck_path=DECK,
        model_path=REAL_WEIGHTS,
        mirror_model_path=REAL_WEIGHTS,  # any real weights prove the wiring
    )
    assert agent.mirror_specialist is not None
    # Search DISABLED for the specialist (no OnePlySearchPolicy attached)...
    assert agent.mirror_specialist.search_policy is None
    # ...while the base policy keeps v2.2 selective search.
    assert agent.policy.search_policy is not None
    # Greedy lock (temperature 0) as pinned by submission/main.py.
    assert agent.mirror_specialist.temp == 0.0

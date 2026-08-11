import hashlib
from pathlib import Path

import pytest

from training.evaluate_deterministic_crn import (
    DEFAULT_CONTROL,
    DEFAULT_ENGINE,
    _public_observation_sha256,
    get_engine,
    paired_summary,
)


def row(pair, *, win, seed=None, order="first", seat=0):
    return {
        "pair_index": pair,
        "win": win,
        "draw": 0,
        "seed": pair + 10 if seed is None else seed,
        "actual_order": order,
        "physical_seat": seat,
        "hero_policy_errors": 0,
        "opponent_policy_errors": 0,
        "decisions": 20,
    }


def test_paired_summary_uses_within_seed_differences():
    candidate = [row(0, win=1), row(1, win=0)]
    control = [row(0, win=0), row(1, win=1)]
    summary = paired_summary(candidate, control)
    assert summary["pairs"] == 2
    assert summary["paired_difference"] == 0
    assert summary["discordant_candidate_wins"] == 1
    assert summary["discordant_control_wins"] == 1
    assert summary["concordant"] == 0


def test_paired_summary_rejects_seed_or_schedule_mismatch():
    candidate = [row(0, win=1), row(1, win=0)]
    control = [row(0, win=0, seed=999), row(1, win=1)]
    with pytest.raises(ValueError, match="paired schedules differ"):
        paired_summary(candidate, control)


@pytest.mark.skipif(not DEFAULT_ENGINE.exists(), reason="isolated deterministic DLL has not been built")
def test_seeded_engine_repeats_public_state_and_treats_zero_as_literal_seed():
    engine = get_engine(DEFAULT_ENGINE)
    deck = [int(line) for line in (DEFAULT_CONTROL / "deck.csv").read_text().splitlines() if line.strip()]

    def state_after_order(seed):
        pointer, _ = engine.start(deck, deck, seed)
        try:
            return _public_observation_sha256(engine.select(pointer, [0]))
        finally:
            engine.finish(pointer)

    assert state_after_order(123) == state_after_order(123)
    assert state_after_order(0) == state_after_order(0)
    assert state_after_order(123) != state_after_order(124)


@pytest.mark.skipif(not DEFAULT_ENGINE.exists(), reason="isolated deterministic DLL has not been built")
def test_local_source_engine_matches_production_card_metadata():
    from cg.sim import lib as production

    engine = get_engine(DEFAULT_ENGINE)
    local_cards = engine.lib.AllCard()
    local_attacks = engine.lib.AllAttack()
    assert hashlib.sha256(local_cards).digest() == hashlib.sha256(production.AllCard()).digest()
    assert hashlib.sha256(local_attacks).digest() == hashlib.sha256(production.AllAttack()).digest()

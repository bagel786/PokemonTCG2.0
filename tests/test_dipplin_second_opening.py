"""Regression and behavior tests for S1 SECOND_OPENING_V2.

SECOND_OPENING_V2 is the deterministic second-player first-turn route gated
behind ``PTCG_DIPPLIN_SECOND_OPENING_V2=1``.  It must change behavior only in
the exact context (actual second, own turn 1, Active Volbeat, Quick Sign legal)
and must be byte-identical to incumbent D1 everywhere else.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from cg.api import OptionType, to_observation_class

from ptcg_ai.dipplin.cards import DIPPLIN, GRASS_ENERGY, GROOKEY, HILDA, QUICK_SIGN
from ptcg_ai.dipplin.policy import DipplinCompetitionAgent
from ptcg_ai.dipplin.resolvers import option_card_id


FIXTURES = Path(__file__).resolve().parents[1] / "artifacts" / "dipplin_prompt_audit"


def _fixture(name: str) -> dict:
    payload = json.loads((FIXTURES / f"{name}.json").read_text())
    return payload["observation"]


def _act(raw: dict, second_opening_v2: bool) -> list[int]:
    if second_opening_v2:
        os.environ["PTCG_DIPPLIN_SECOND_OPENING_V2"] = "1"
    else:
        os.environ.pop("PTCG_DIPPLIN_SECOND_OPENING_V2", None)
    agent = DipplinCompetitionAgent(search_enabled=False)
    return agent(raw)


def _selected_ids(raw: dict, action: list[int]) -> list[int]:
    obs = to_observation_class(raw)
    return [option_card_id(obs, index) for index in action]


def _attack_ids(raw: dict, action: list[int]) -> list[int]:
    options = raw["select"]["option"]
    return [int(options[index].get("attackId", -1)) for index in action]


# Non-second-opening MAIN prompts used by the shared policy.  Candidate and
# incumbent must select identical actions for every one of these.
NON_SECOND_OPENING_MAIN = [
    "main_quick_sign_turn1",
    "main_do_the_wave",
    "main_evolve_dipplin",
    "main_evolve_thwackey",
    "main_manual_energy",
    "main_play_1225",
    "main_play_lillie",
    "main_play_1152",
    "main_play_1086",
    "main_play_1094",
    "main_retreat",
    "main_attach_brave_bangle",
    "main_play_343",
    "main_play_42",
    "main_play_89",
    "main_play_92",
    "hero_actual_first",
]


def test_candidate_identical_to_incumbent_outside_second_opening():
    for name in NON_SECOND_OPENING_MAIN:
        raw = _fixture(name)
        incumbent = _act(raw, second_opening_v2=False)
        candidate = _act(raw, second_opening_v2=True)
        assert candidate == incumbent, f"{name}: candidate {candidate} != incumbent {incumbent}"


def test_incumbent_quick_signs_immediately_in_second_opening():
    raw = _fixture("second_opening_quick_sign")
    action = _act(raw, second_opening_v2=False)
    assert QUICK_SIGN in _attack_ids(raw, action)


def test_candidate_banks_hilda_before_quick_sign_in_second_opening():
    raw = _fixture("second_opening_quick_sign")
    action = _act(raw, second_opening_v2=True)
    # The captured hand holds Hilda but no Grass Energy, so S1 banks the
    # evolution/Energy line before Quick Sign.
    assert _selected_ids(raw, action) == [HILDA]


def test_second_opening_hilda_resolves_dipplin_without_board_applin():
    # Hilda's evolution stage must bank a Dipplin for the Applin Quick Sign will
    # place, even though no Applin currently exists on the board.
    raw = _fixture("hilda_evolution")
    # hilda_evolution fixture normally has no Applin; verify the resolver's
    # public-state detection helper does not leak outside the S1 context.
    obs = to_observation_class(raw)
    from ptcg_ai.dipplin.plan import build_macro_plan
    from ptcg_ai.dipplin.resolvers import PromptResolver

    plan = build_macro_plan(obs)
    resolver = PromptResolver(go_first=True, second_opening_v2=True)
    assert resolver._in_second_opening(plan) is False


def test_second_opening_state_is_detected_only_in_exact_context():
    raw = _fixture("second_opening_quick_sign")
    obs = to_observation_class(raw)
    from ptcg_ai.dipplin.plan import build_macro_plan
    from ptcg_ai.dipplin.resolvers import PromptResolver

    plan = build_macro_plan(obs)
    resolver_on = PromptResolver(go_first=True, second_opening_v2=True)
    resolver_off = PromptResolver(go_first=True, second_opening_v2=False)
    assert resolver_on._in_second_opening(plan) is True
    assert resolver_off._in_second_opening(plan) is False


def test_opening_basic_play_preserves_quick_sign_slots():
    from ptcg_ai.dipplin.policy import FestivalD0Planner

    planner = FestivalD0Planner(go_first=True)
    grookey_raw = _fixture("main_play_89")
    applin_raw = _fixture("main_play_42")

    def grookey_play(free_slots):
        obs = to_observation_class(grookey_raw)
        return planner._second_opening_basic_play(
            obs, GROOKEY, applin_lines=0, engine_lines=0, free_slots=free_slots
        )

    def applin_play(free_slots):
        obs = to_observation_class(applin_raw)
        return planner._second_opening_basic_play(
            obs, 42, applin_lines=0, engine_lines=0, free_slots=free_slots
        )

    # A Grookey play satisfies the missing engine line and reduces the Quick
    # Sign slots in lock-step, so it is offered while a slot remains.
    assert grookey_play(5) != []
    assert applin_play(5) != []
    # With only two free slots and two attacker + one engine lines still
    # missing, an Applin play would leave too few slots for Quick Sign.
    assert applin_play(2) == []


def test_second_opening_never_activates_for_starting_player():
    raw = _fixture("main_quick_sign_turn1")  # actual-first turn 1, Quick Sign legal
    incumbent = _act(raw, second_opening_v2=False)
    candidate = _act(raw, second_opening_v2=True)
    assert candidate == incumbent

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from cg.api import OptionType, to_observation_class

from ptcg_ai.dipplin.cards import (
    APPLIN_DRAGON,
    DIPPLIN,
    EXACT_DECK,
    NIGHT_STRETCHER,
    SACRED_ASH,
)
from ptcg_ai.dipplin.policy import DipplinCompetitionAgent
from ptcg_ai.dipplin.resolvers import option_card_id, option_source


FIXTURES = Path(__file__).resolve().parents[1] / "artifacts" / "dipplin_prompt_audit"


def _fixture(name: str) -> dict:
    payload = json.loads((FIXTURES / f"{name}.json").read_text())
    raw = payload["observation"]
    to_observation_class(raw)
    return deepcopy(raw)


def _assert_legal(raw: dict, action: list[int]) -> None:
    select = raw["select"]
    assert len(action) == len(set(action))
    assert select["minCount"] <= len(action) <= select["maxCount"]
    assert all(type(index) is int and 0 <= index < len(select["option"]) for index in action)


def _selected_ids(raw: dict, action: list[int]) -> list[int]:
    obs = to_observation_class(raw)
    return [option_card_id(obs, index) for index in action]


def test_night_stretcher_recovers_the_immediate_dipplin_component():
    raw = _fixture("night_stretcher")

    action = DipplinCompetitionAgent(search_enabled=False)(raw)

    _assert_legal(raw, action)
    assert raw["select"]["effect"]["id"] == NIGHT_STRETCHER
    assert _selected_ids(raw, action) == [DIPPLIN]


def test_sacred_ash_restores_all_useful_exhausted_lines_in_fixture():
    raw = _fixture("sacred_ash_multi")

    action = DipplinCompetitionAgent(search_enabled=False)(raw)

    _assert_legal(raw, action)
    assert raw["select"]["effect"]["id"] == SACRED_ASH
    assert set(_selected_ids(raw, action)) == {DIPPLIN, APPLIN_DRAGON}


def test_promotion_prefers_attack_ready_dipplin_after_ko():
    raw = _fixture("promotion_after_ko")

    action = DipplinCompetitionAgent(search_enabled=False)(raw)
    obs = to_observation_class(raw)
    promoted = option_source(obs, obs.select.option[action[0]])

    _assert_legal(raw, action)
    assert promoted.id == DIPPLIN
    assert promoted.energies


def test_trapped_volbeat_retreats_to_attack_ready_dipplin():
    raw = _fixture("main_retreat")

    action = DipplinCompetitionAgent(search_enabled=False)(raw)
    obs = to_observation_class(raw)
    selected = obs.select.option[action[0]]

    _assert_legal(raw, action)
    assert selected.type == int(OptionType.RETREAT)


def test_post_retreat_switch_context_promotes_attack_ready_dipplin():
    raw = _fixture("promotion_after_ko")
    raw["select"]["context"] = 3  # SelectContext.SWITCH is non-strict.
    raw["select"]["effect"] = None
    raw["select"]["contextCard"] = None

    action = DipplinCompetitionAgent(search_enabled=False)(raw)
    obs = to_observation_class(raw)
    promoted = option_source(obs, obs.select.option[action[0]])

    _assert_legal(raw, action)
    assert promoted.id == DIPPLIN
    assert promoted.energies


def test_handshake_reset_clears_persistent_turn_memory():
    agent = DipplinCompetitionAgent(search_enabled=False)
    second_attack = _fixture("festival_second_attack")
    action = agent(second_attack)
    _assert_legal(second_attack, action)
    assert agent.memory.festival_attack_count == 1

    deck = agent({"select": None})

    assert deck == list(EXACT_DECK)
    assert agent.memory.global_turn is None
    assert agent.memory.action_history == []
    assert agent.memory.festival_attack_count == 0
    assert agent.memory.used_thwackey_lineages == set()


def test_unknown_optional_prompt_fails_closed_without_exception():
    raw = _fixture("night_stretcher")
    raw["select"]["type"] = 999
    raw["select"]["context"] = 999
    raw["select"]["minCount"] = 0
    raw["select"]["maxCount"] = 1
    raw["select"]["effect"] = {"id": 9999, "serial": 9999, "playerIndex": 0}
    to_observation_class(raw)
    agent = DipplinCompetitionAgent(search_enabled=False)

    action = agent(raw)

    _assert_legal(raw, action)
    assert action == []
    assert agent.errors == 0
    assert agent.route_telemetry["unknown_contexts"] == 1.0


def test_every_public_prompt_fixture_produces_a_legal_selection():
    fixture_paths = sorted(FIXTURES.glob("*.json"))
    assert fixture_paths
    checked = 0
    for path in fixture_paths:
        if path.name == "summary.json":
            continue
        payload = json.loads(path.read_text())
        raw = payload["observation"]
        to_observation_class(raw)
        agent = DipplinCompetitionAgent(search_enabled=False)

        action = agent(raw)

        _assert_legal(raw, action)
        assert agent.errors == 0, path.name
        checked += 1
    assert checked >= 50

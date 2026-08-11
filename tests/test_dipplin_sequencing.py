from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from cg.api import OptionType, to_observation_class

from ptcg_ai.dipplin.cards import (
    BRAVE_BANGLE,
    DIPPLIN,
    DO_THE_WAVE,
    FESTIVAL,
    GRASS_ENERGY,
    LILLIE,
    THWACKEY,
)
from ptcg_ai.dipplin.policy import DipplinCompetitionAgent
from ptcg_ai.dipplin.resolvers import option_card_id, option_source, option_target


FIXTURES = Path(__file__).resolve().parents[1] / "artifacts" / "dipplin_prompt_audit"


def _fixture(name: str) -> dict:
    payload = json.loads((FIXTURES / f"{name}.json").read_text())
    raw = payload["observation"]
    to_observation_class(raw)
    return deepcopy(raw)


def _card(card_id: int, serial: int, player: int = 0) -> dict:
    return {"id": card_id, "serial": serial, "playerIndex": player}


def _assert_legal(raw: dict, action: list[int]) -> None:
    select = raw["select"]
    assert len(action) == len(set(action))
    assert select["minCount"] <= len(action) <= select["maxCount"]
    assert all(type(index) is int and 0 <= index < len(select["option"]) for index in action)


def _chosen_option(raw: dict, action: list[int]):
    obs = to_observation_class(raw)
    assert len(action) == 1
    return obs, obs.select.option[action[0]]


def test_festival_is_played_before_an_available_do_the_wave():
    raw = _fixture("main_do_the_wave")
    hero_index = raw["current"]["yourIndex"]
    hero = raw["current"]["players"][hero_index]
    hero["hand"].append(_card(FESTIVAL, 990, hero_index))
    hero["handCount"] = len(hero["hand"])
    raw["select"]["option"].insert(
        0, {"type": int(OptionType.PLAY), "index": len(hero["hand"]) - 1}
    )

    action = DipplinCompetitionAgent(search_enabled=False)(raw)
    obs, _ = _chosen_option(raw, action)

    _assert_legal(raw, action)
    assert option_card_id(obs, action[0]) == FESTIVAL


def test_own_festival_is_not_replaced_pointlessly_before_attacking():
    raw = _fixture("main_do_the_wave")
    hero_index = raw["current"]["yourIndex"]
    hero = raw["current"]["players"][hero_index]
    raw["current"]["stadium"] = [_card(FESTIVAL, 991, hero_index)]
    hero["hand"].append(_card(FESTIVAL, 992, hero_index))
    hero["handCount"] = len(hero["hand"])
    raw["select"]["option"].insert(
        0, {"type": int(OptionType.PLAY), "index": len(hero["hand"]) - 1}
    )

    action = DipplinCompetitionAgent(search_enabled=False)(raw)
    _, selected = _chosen_option(raw, action)

    _assert_legal(raw, action)
    assert option_card_id(to_observation_class(raw), action[0]) != FESTIVAL


def test_lillie_precedes_thwackey_but_tutor_is_used_after_the_draw():
    before = _fixture("main_two_thwackey_abilities")
    hero_index = before["current"]["yourIndex"]
    hero = before["current"]["players"][hero_index]
    hero["hand"] = [_card(LILLIE, 993, hero_index)]
    hero["handCount"] = 1
    before["current"]["stadium"] = [_card(FESTIVAL, 994, hero_index)]
    original = before["select"]["option"]
    ability = deepcopy(original[10])
    attack = deepcopy(original[13])
    end = deepcopy(original[14])
    before["select"]["option"] = [
        {"type": int(OptionType.PLAY), "index": 0},
        ability,
        attack,
        end,
    ]
    agent = DipplinCompetitionAgent(search_enabled=False)

    before_action = agent(before)
    before_obs, _ = _chosen_option(before, before_action)

    after = deepcopy(before)
    after["current"]["turnActionCount"] += 1
    after["current"]["supporterPlayed"] = True
    after_hero = after["current"]["players"][hero_index]
    after_hero["hand"] = []
    after_hero["handCount"] = 0
    after["select"]["option"] = [ability, attack, end]
    after_action = agent(after)
    after_obs, after_selected = _chosen_option(after, after_action)

    _assert_legal(before, before_action)
    _assert_legal(after, after_action)
    assert option_card_id(before_obs, before_action[0]) == LILLIE
    assert after_selected.type == int(OptionType.ABILITY)
    assert option_card_id(after_obs, after_action[0]) == THWACKEY


def test_manual_energy_targets_the_current_dipplin_when_it_enables_attack():
    raw = _fixture("main_attach_brave_bangle")
    action = DipplinCompetitionAgent(search_enabled=False)(raw)
    obs, selected = _chosen_option(raw, action)
    source = option_source(obs, selected)
    target = option_target(obs, selected)

    _assert_legal(raw, action)
    assert source.id == GRASS_ENERGY
    assert target.id == DIPPLIN
    assert target.serial == obs.current.players[obs.current.yourIndex].active[0].serial


def test_manual_energy_moves_to_replacement_once_current_attacker_is_ready():
    raw = _fixture("main_attach_brave_bangle")
    hero_index = raw["current"]["yourIndex"]
    hero = raw["current"]["players"][hero_index]
    hero["active"][0]["energies"] = [GRASS_ENERGY]
    hero["active"][0]["energyCards"] = [_card(GRASS_ENERGY, 995, hero_index)]
    replacement = deepcopy(
        _fixture("promotion_after_ko")["current"]["players"][hero_index]["bench"][1]
    )
    replacement["energies"] = []
    replacement["energyCards"] = []
    hero["bench"][3] = replacement

    action = DipplinCompetitionAgent(search_enabled=False)(raw)
    obs, selected = _chosen_option(raw, action)
    source = option_source(obs, selected)
    target = option_target(obs, selected)

    _assert_legal(raw, action)
    assert source.id == GRASS_ENERGY
    assert target.id == DIPPLIN
    assert target.serial == replacement["serial"]
    assert target.serial != obs.current.players[hero_index].active[0].serial


def test_bangle_attaches_to_the_intended_dipplin_when_it_changes_ko_route():
    raw = _fixture("main_attach_brave_bangle")
    hero_index = raw["current"]["yourIndex"]
    hero = raw["current"]["players"][hero_index]
    hero["active"][0]["energies"] = [GRASS_ENERGY]
    hero["active"][0]["energyCards"] = [_card(GRASS_ENERGY, 996, hero_index)]
    opponent = raw["current"]["players"][1 - hero_index]
    # Use a real, non-Grass-weak Basic ex identity so 80 damage is short and
    # Bangle's 110 crosses the one-hit threshold without weakness doing it.
    opponent["active"][0]["id"] = 24
    opponent["active"][0]["hp"] = 100
    opponent["active"][0]["maxHp"] = 230
    opponent["active"][0]["preEvolution"] = []
    original = raw["select"]["option"]
    do_wave = deepcopy(_fixture("main_do_the_wave")["select"]["option"][2])
    raw["select"]["option"] = [
        deepcopy(original[6]),
        deepcopy(original[8]),
        do_wave,
        deepcopy(original[12]),
    ]

    action = DipplinCompetitionAgent(search_enabled=False)(raw)
    obs, selected = _chosen_option(raw, action)
    source = option_source(obs, selected)
    target = option_target(obs, selected)

    _assert_legal(raw, action)
    assert source.id == BRAVE_BANGLE
    assert target.id == DIPPLIN
    assert target.serial == obs.current.players[hero_index].active[0].serial


def test_productive_do_the_wave_state_never_selects_end_while_development_remains():
    raw = _fixture("main_do_the_wave")

    action = DipplinCompetitionAgent(search_enabled=False)(raw)
    _, selected = _chosen_option(raw, action)

    _assert_legal(raw, action)
    assert selected.type != int(OptionType.END)


@pytest.mark.parametrize(
    "fixture_name", ["festival_second_attack", "festival_second_attack_after_ko"]
)
def test_festival_second_attack_is_always_selected_even_when_optional(fixture_name: str):
    raw = _fixture(fixture_name)

    action = DipplinCompetitionAgent(search_enabled=False)(raw)
    _, selected = _chosen_option(raw, action)

    _assert_legal(raw, action)
    assert raw["select"]["minCount"] == 0
    assert selected.type == int(OptionType.ATTACK)
    assert selected.attackId == DO_THE_WAVE

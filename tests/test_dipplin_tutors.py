from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from cg.api import AreaType, OptionType, to_observation_class

from ptcg_ai.dipplin.cards import (
    APPLIN_DRAGON,
    APPLIN_GRASS,
    DIPPLIN,
    GRASS_ENERGY,
    GROOKEY,
    THWACKEY,
)
from ptcg_ai.dipplin.policy import DipplinCompetitionAgent
from ptcg_ai.dipplin.resolvers import option_card_id, option_source


FIXTURES = Path(__file__).resolve().parents[1] / "artifacts" / "dipplin_prompt_audit"


def _fixture(name: str) -> dict:
    payload = json.loads((FIXTURES / f"{name}.json").read_text())
    raw = payload["observation"]
    to_observation_class(raw)
    return deepcopy(raw)


def _card(card_id: int, serial: int, player: int = 0) -> dict:
    return {"id": card_id, "serial": serial, "playerIndex": player}


def _pokemon(card_id: int, serial: int, *, player: int = 0, hp: int = 40) -> dict:
    return {
        "id": card_id,
        "serial": serial,
        "playerIndex": player,
        "hp": hp,
        "maxHp": hp,
        "appearThisTurn": False,
        "energies": [],
        "energyCards": [],
        "tools": [],
        "preEvolution": [],
    }


def _assert_legal(raw: dict, action: list[int]) -> None:
    select = raw["select"]
    assert len(action) == len(set(action))
    assert select["minCount"] <= len(action) <= select["maxCount"]
    assert all(type(index) is int and 0 <= index < len(select["option"]) for index in action)


def _selected_ids(raw: dict, action: list[int]) -> list[int]:
    obs = to_observation_class(raw)
    return [option_card_id(obs, index) for index in action]


def test_bug_set_rejects_dragon_applin_even_if_a_malformed_option_exposes_it():
    raw = _fixture("bug_catching_set")
    # The real fixture proves card 42 is absent from the engine's legal pool.
    # Add it as an adversarial option so the resolver's own type guard is also
    # exercised rather than merely trusting option ordering.
    raw["select"]["option"].append(
        {
            "type": int(OptionType.CARD),
            "area": int(AreaType.LOOKING),
            "index": 6,
            "playerIndex": raw["current"]["yourIndex"],
        }
    )
    raw["select"]["maxCount"] = 2

    action = DipplinCompetitionAgent(search_enabled=False)(raw)

    _assert_legal(raw, action)
    assert _selected_ids(raw, action) == [THWACKEY]
    assert APPLIN_DRAGON not in _selected_ids(raw, action)


def test_hilda_selects_the_attack_enabling_dipplin_then_energy():
    evolution = _fixture("hilda_evolution")
    hero_index = evolution["current"]["yourIndex"]
    hero = evolution["current"]["players"][hero_index]
    hero["active"] = [_pokemon(APPLIN_DRAGON, 901, player=hero_index)]
    evolution["select"]["deck"] = [
        _card(THWACKEY, 902, hero_index),
        _card(DIPPLIN, 903, hero_index),
    ]
    evolution["select"]["option"] = [
        {
            "type": int(OptionType.CARD),
            "area": int(AreaType.DECK),
            "index": index,
            "playerIndex": hero_index,
        }
        for index in range(2)
    ]

    evolution_action = DipplinCompetitionAgent(search_enabled=False)(evolution)

    _assert_legal(evolution, evolution_action)
    assert _selected_ids(evolution, evolution_action) == [DIPPLIN]

    energy = _fixture("hilda_energy")
    energy_hero = energy["current"]["players"][energy["current"]["yourIndex"]]
    energy_hero["active"][0]["energies"] = []
    energy_hero["active"][0]["energyCards"] = []
    energy_action = DipplinCompetitionAgent(search_enabled=False)(energy)

    _assert_legal(energy, energy_action)
    assert _selected_ids(energy, energy_action) == [GRASS_ENERGY]


def test_brock_takes_two_basics_when_board_setup_is_incomplete():
    first = _fixture("brock_first_choice")
    second = _fixture("brock_second_basic")

    first_action = DipplinCompetitionAgent(search_enabled=False)(first)
    second_action = DipplinCompetitionAgent(search_enabled=False)(second)

    _assert_legal(first, first_action)
    _assert_legal(second, second_action)
    assert _selected_ids(first, first_action)[0] in {APPLIN_GRASS, APPLIN_DRAGON, GROOKEY}
    assert _selected_ids(second, second_action)[0] in {APPLIN_GRASS, APPLIN_DRAGON, GROOKEY}
    assert _selected_ids(first, first_action)[0] != THWACKEY
    assert _selected_ids(second, second_action)[0] != THWACKEY


def test_brock_chooses_one_critical_evolution_instead_of_basic_branch():
    raw = _fixture("brock_first_choice")
    hero_index = raw["current"]["yourIndex"]
    hero = raw["current"]["players"][hero_index]
    hero["active"] = [_pokemon(APPLIN_GRASS, 910, player=hero_index)]
    raw["select"]["deck"].append(_card(DIPPLIN, 911, hero_index))
    raw["select"]["option"].append(
        {
            "type": int(OptionType.CARD),
            "area": int(AreaType.DECK),
            "index": len(raw["select"]["deck"]) - 1,
            "playerIndex": hero_index,
        }
    )

    action = DipplinCompetitionAgent(search_enabled=False)(raw)

    _assert_legal(raw, action)
    assert _selected_ids(raw, action) == [DIPPLIN]


def test_first_thwackey_tutor_fetches_the_exact_missing_attack_energy():
    raw = _fixture("boom_boom_groove")

    action = DipplinCompetitionAgent(search_enabled=False)(raw)

    _assert_legal(raw, action)
    assert _selected_ids(raw, action) == [GRASS_ENERGY]


def test_dragon_applin_find_a_friend_fetches_next_turn_dipplin():
    raw = _fixture("boom_boom_groove")
    hero_index = raw["current"]["yourIndex"]
    raw["current"]["players"][hero_index]["active"] = [
        _pokemon(APPLIN_DRAGON, 979, player=hero_index)
    ]
    raw["select"]["effect"] = _card(APPLIN_DRAGON, 980, hero_index)
    raw["select"]["deck"] = [
        _card(THWACKEY, 981, hero_index),
        _card(DIPPLIN, 982, hero_index),
        _card(GROOKEY, 983, hero_index),
    ]
    raw["select"]["option"] = [
        {
            "type": int(OptionType.CARD),
            "area": int(AreaType.DECK),
            "index": index,
            "playerIndex": hero_index,
        }
        for index in range(3)
    ]
    raw["select"]["minCount"] = 1
    raw["select"]["maxCount"] = 1

    agent = DipplinCompetitionAgent(search_enabled=False)
    action = agent(raw)

    _assert_legal(raw, action)
    assert _selected_ids(raw, action) == [DIPPLIN]
    assert agent.route_telemetry.get("unknown_contexts", 0.0) == 0.0


def test_two_thwackey_activations_are_committed_by_distinct_lineage_serials():
    first = _fixture("main_two_thwackey_abilities")
    first_options = first["select"]["option"]
    # Isolate the two independently legal Boom Boom Groove options and END.
    first["select"]["option"] = [
        deepcopy(first_options[10]),
        deepcopy(first_options[11]),
        deepcopy(first_options[14]),
    ]
    agent = DipplinCompetitionAgent(search_enabled=False)

    first_action = agent(first)
    first_obs = to_observation_class(first)
    first_source = option_source(first_obs, first_obs.select.option[first_action[0]])
    first_lineage = first_source.preEvolution[0].serial

    second = _fixture("main_second_thwackey_available")
    # That independently captured fixture came from turn 11.  Replay its
    # remaining-option shape in the same turn as the first activation so the
    # test measures per-turn serial tracking rather than the required reset.
    second["current"]["turn"] = first["current"]["turn"]
    second_action = agent(second)
    second_obs = to_observation_class(second)
    second_source = option_source(second_obs, second_obs.select.option[second_action[0]])
    second_lineage = second_source.preEvolution[0].serial

    _assert_legal(first, first_action)
    _assert_legal(second, second_action)
    assert first_lineage != second_lineage
    assert agent.memory.used_thwackey_lineages == {first_lineage, second_lineage}

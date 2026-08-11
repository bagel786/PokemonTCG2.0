from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from cg.api import AreaType, OptionType, to_observation_class

from ptcg_ai.dipplin.cards import (
    APPLIN_DRAGON,
    APPLIN_GRASS,
    GRASS_ENERGY,
    GROOKEY,
    SHAYMIN,
    VOLBEAT,
)
from ptcg_ai.dipplin.policy import DipplinCompetitionAgent
from ptcg_ai.dipplin.resolvers import option_card_id


FIXTURES = Path(__file__).resolve().parents[1] / "artifacts" / "dipplin_prompt_audit"


def _fixture(name: str) -> dict:
    payload = json.loads((FIXTURES / f"{name}.json").read_text())
    raw = payload["observation"]
    # Every focused test goes through the same public conversion used by the
    # competition runtime; this also catches stale or malformed audit data.
    to_observation_class(raw)
    return deepcopy(raw)


def _card(card_id: int, serial: int, player: int = 0) -> dict:
    return {"id": card_id, "serial": serial, "playerIndex": player}


def _set_setup_hand(raw: dict, ids: list[int]) -> None:
    hero_index = raw["current"]["yourIndex"]
    hero = raw["current"]["players"][hero_index]
    hero["hand"] = [_card(card_id, 700 + index, hero_index) for index, card_id in enumerate(ids)]
    hero["handCount"] = len(hero["hand"])
    raw["select"]["option"] = [
        {
            "type": int(OptionType.CARD),
            "area": int(AreaType.HAND),
            "index": index,
            "playerIndex": hero_index,
        }
        for index, card_id in enumerate(ids)
        if card_id in {VOLBEAT, APPLIN_GRASS, APPLIN_DRAGON, GROOKEY, SHAYMIN}
    ]


def _assert_legal(raw: dict, action: list[int]) -> None:
    select = raw["select"]
    assert len(action) == len(set(action))
    assert select["minCount"] <= len(action) <= select["maxCount"]
    assert all(type(index) is int and 0 <= index < len(select["option"]) for index in action)


def _selected_ids(raw: dict, action: list[int]) -> list[int]:
    obs = to_observation_class(raw)
    return [option_card_id(obs, index) for index in action]


def test_setup_active_chooses_volbeat_when_grass_energy_enables_quick_sign():
    raw = _fixture("setup_active")
    _set_setup_hand(
        raw,
        [VOLBEAT, APPLIN_GRASS, APPLIN_DRAGON, GROOKEY, SHAYMIN, GRASS_ENERGY],
    )

    action = DipplinCompetitionAgent(search_enabled=False)(raw)

    _assert_legal(raw, action)
    assert _selected_ids(raw, action) == [VOLBEAT]


def test_setup_active_avoids_stranded_volbeat_without_energy_or_search_path():
    raw = _fixture("setup_active")
    _set_setup_hand(raw, [VOLBEAT, APPLIN_GRASS, APPLIN_DRAGON, GROOKEY, SHAYMIN])

    action = DipplinCompetitionAgent(search_enabled=False)(raw)

    _assert_legal(raw, action)
    assert _selected_ids(raw, action) == [APPLIN_GRASS]


def test_setup_bench_builds_attacker_and_engine_without_redundant_volbeat():
    raw = _fixture("setup_bench")
    quick_sign = _fixture("quick_sign")
    hero_index = raw["current"]["yourIndex"]
    hero = raw["current"]["players"][hero_index]
    # The Active selected in the preceding setup prompt is public by the time
    # board composition matters.  Reuse the engine-derived Volbeat shape.
    hero["active"] = deepcopy(
        quick_sign["current"]["players"][quick_sign["current"]["yourIndex"]]["active"]
    )
    _set_setup_hand(raw, [APPLIN_GRASS, APPLIN_DRAGON, GROOKEY, SHAYMIN, VOLBEAT])
    raw["select"]["maxCount"] = 4

    action = DipplinCompetitionAgent(search_enabled=False)(raw)
    chosen = _selected_ids(raw, action)

    _assert_legal(raw, action)
    assert APPLIN_GRASS in chosen
    assert APPLIN_DRAGON in chosen
    assert GROOKEY in chosen
    assert VOLBEAT not in chosen


def test_quick_sign_chooses_one_applin_and_one_grookey():
    raw = _fixture("quick_sign_two_targets")

    action = DipplinCompetitionAgent(search_enabled=False)(raw)
    chosen = _selected_ids(raw, action)

    _assert_legal(raw, action)
    assert len(chosen) == 2
    assert GROOKEY in chosen
    assert len({APPLIN_GRASS, APPLIN_DRAGON}.intersection(chosen)) == 1
    assert SHAYMIN not in chosen
    assert VOLBEAT not in chosen


def test_poffin_fills_the_two_missing_grookey_lines():
    raw = _fixture("buddy_buddy_poffin")

    action = DipplinCompetitionAgent(search_enabled=False)(raw)

    _assert_legal(raw, action)
    assert _selected_ids(raw, action) == [GROOKEY, GROOKEY]

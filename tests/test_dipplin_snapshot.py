from __future__ import annotations

from collections import Counter
from dataclasses import FrozenInstanceError

import pytest

from ptcg_ai.dipplin.cards import (
    APPLIN_DRAGON,
    APPLIN_GRASS,
    DECK_CSV_SHA256,
    DECK_ID,
    DECK_MULTISET_SHA256,
    DIPPLIN,
    DO_THE_WAVE,
    EXACT_COUNTS,
    EXACT_DECK,
    GRASS_ENERGY,
    THWACKEY,
    deck_csv_sha256,
    deck_multiset_sha256,
)
from ptcg_ai.dipplin.snapshot import PlanMemory, PlanSnapshot, SemanticAction
from ptcg_ai.dipplin.telemetry import DipplinTelemetry


def _card(card_id: int, serial: int, player: int = 0) -> dict:
    return {"id": card_id, "serial": serial, "playerIndex": player}


def _pokemon(
    card_id: int,
    serial: int,
    *,
    player: int = 0,
    pre: tuple[dict, ...] = (),
    energies: tuple[int, ...] = (),
    hp: int = 80,
) -> dict:
    return {
        "id": card_id,
        "serial": serial,
        "playerIndex": player,
        "hp": hp,
        "maxHp": hp,
        "appearThisTurn": False,
        "energies": list(energies),
        "energyCards": [
            _card(GRASS_ENERGY, 1000 + offset, player) for offset, _ in enumerate(energies)
        ],
        "tools": [],
        "preEvolution": list(pre),
    }


def _player(
    player: int,
    *,
    active: dict | None = None,
    bench: tuple[dict, ...] = (),
    hand: tuple[dict, ...] = (),
    discard: tuple[dict, ...] = (),
) -> dict:
    return {
        "active": [active] if active is not None else [],
        "bench": list(bench),
        "benchMax": 5,
        "deckCount": 40,
        "discard": list(discard),
        "prize": [None] * 6,
        "handCount": len(hand),
        "hand": list(hand),
        "poisoned": False,
        "burned": False,
        "asleep": False,
        "paralyzed": False,
        "confused": False,
    }


def _observation(
    *,
    turn: int = 1,
    your_index: int = 0,
    first_player: int = 0,
    hero_active: dict | None = None,
    hero_bench: tuple[dict, ...] = (),
    hero_hand: tuple[dict, ...] = (),
    hero_discard: tuple[dict, ...] = (),
    opponent_active: dict | None = None,
    opponent_hand: tuple[dict, ...] = (),
    select: dict | None = None,
    logs: tuple[dict, ...] = (),
) -> dict:
    hero = _player(
        your_index,
        active=hero_active,
        bench=hero_bench,
        hand=hero_hand,
        discard=hero_discard,
    )
    opponent_index = 1 - your_index
    opponent = _player(
        opponent_index,
        active=opponent_active,
        hand=opponent_hand,
    )
    players = [None, None]
    players[your_index] = hero
    players[opponent_index] = opponent
    return {
        "current": {
            "turn": turn,
            "turnActionCount": 3,
            "yourIndex": your_index,
            "firstPlayer": first_player,
            "supporterPlayed": False,
            "stadiumPlayed": False,
            "energyAttached": False,
            "retreated": False,
            "result": -1,
            "stadium": [],
            "looking": None,
            "players": players,
        },
        "select": select
        or {
            "type": 0,
            "context": 0,
            "minCount": 1,
            "maxCount": 1,
            "option": [],
            "deck": None,
            "contextCard": None,
            "effect": None,
        },
        "logs": list(logs),
    }


def test_exact_deck_identity_and_applin_printings_remain_distinct():
    assert DECK_ID == "291b0afd6ead"
    assert len(EXACT_DECK) == 60
    assert Counter(EXACT_DECK) == EXACT_COUNTS
    assert APPLIN_DRAGON != APPLIN_GRASS
    assert Counter(EXACT_DECK)[APPLIN_DRAGON] == 3
    assert Counter(EXACT_DECK)[APPLIN_GRASS] == 1
    assert deck_csv_sha256() == DECK_CSV_SHA256
    assert deck_multiset_sha256() == DECK_MULTISET_SHA256


def test_physical_serial_changes_on_evolution_but_lineage_is_stable():
    base = _pokemon(APPLIN_DRAGON, 11, hp=40)
    before = PlanSnapshot.from_observation(_observation(turn=2, hero_active=base))
    evolved = _pokemon(DIPPLIN, 29, pre=(_card(APPLIN_DRAGON, 11),), energies=(1,))
    memory = PlanMemory(
        primary_attacker_serial=11,
        primary_attacker_lineage=11,
    )
    after = PlanSnapshot.from_observation(
        _observation(turn=2, hero_active=evolved), memory
    )

    assert before.active is not None and after.active is not None
    assert before.active.serial == 11
    assert after.active.serial == 29
    assert before.active.lineage_serial == after.active.lineage_serial == 11
    assert before.active.lineage_key == after.active.lineage_key == (0, 11)
    assert after.active.attack_ready
    assert after.primary_attacker_serial == 29


@pytest.mark.parametrize(
    ("turn", "your_index", "first_player", "order", "ordinal", "our_turn"),
    [
        (3, 0, 0, "FIRST", 2, True),
        (4, 0, 1, "SECOND", 2, True),
        (3, 0, 1, "SECOND", 1, False),
        (0, 1, -1, "UNKNOWN", 0, False),
    ],
)
def test_actual_order_and_own_turn_ordinal(
    turn: int,
    your_index: int,
    first_player: int,
    order: str,
    ordinal: int,
    our_turn: bool,
):
    snapshot = PlanSnapshot.from_observation(
        _observation(turn=turn, your_index=your_index, first_player=first_player)
    )
    assert snapshot.actual_order == order
    assert snapshot.own_turn_ordinal == ordinal
    assert snapshot.current_turn_is_ours is our_turn


def test_parent_and_public_zones_are_captured_without_opponent_hand_leakage():
    select = {
        "type": 1,
        "context": 7,
        "minCount": 1,
        "maxCount": 1,
        "option": [{"type": 3, "area": 1, "index": 0, "playerIndex": 0}],
        "deck": [_card(DIPPLIN, 29)],
        "contextCard": _card(999, 998),
        "effect": _card(THWACKEY, 24),
    }
    snapshot = PlanSnapshot.from_observation(
        _observation(
            hero_hand=(_card(APPLIN_GRASS, 25),),
            hero_discard=(_card(APPLIN_DRAGON, 11),),
            opponent_hand=(_card(1234, 77, 1),),
            select=select,
        )
    )

    assert snapshot.parent_card_id == THWACKEY
    assert snapshot.parent_serial == 24
    assert snapshot.select.parent_source == "effect"
    assert snapshot.select.deck[0].card_id == DIPPLIN
    assert snapshot.hand_count(APPLIN_GRASS) == 1
    assert snapshot.discard_count(APPLIN_DRAGON) == 1
    assert snapshot.opponent.hand == ()
    assert snapshot.opponent.hand_count == 1
    assert not snapshot.opponent.hand_known


def test_turn_and_handshake_resets_clear_supplemental_memory():
    memory = PlanMemory()
    turn_one = _observation(turn=1, hero_active=_pokemon(DIPPLIN, 29, energies=(1,)))
    PlanSnapshot.from_observation(turn_one, memory)
    memory.commit(
        SemanticAction(kind="ATTACK", attack_id=DO_THE_WAVE, source_serial=29),
        decision_key=(1, 3),
    )
    memory.commit(
        SemanticAction(
            kind="THWACKEY_ABILITY",
            card_id=THWACKEY,
            source_serial=24,
            source_lineage=18,
        )
    )
    assert memory.first_festival_attack_made
    assert memory.used_thwackey_lineages == {18}
    assert len(memory.action_history) == 2

    # Re-reading the same decision key is idempotent.
    assert not memory.commit(
        SemanticAction(kind="ATTACK", attack_id=DO_THE_WAVE, source_serial=29),
        decision_key=(1, 3),
    )
    PlanSnapshot.from_observation(_observation(turn=2), memory)
    assert memory.global_turn == 2
    assert not memory.first_festival_attack_made
    assert memory.used_thwackey_lineages == set()
    assert memory.action_history == []

    epoch = memory.game_epoch
    handshake = PlanSnapshot.from_observation({"select": None, "logs": [], "current": None}, memory)
    assert not handshake.valid
    assert memory.game_epoch == epoch + 1
    assert memory.global_turn is None
    assert memory.action_history == []


def test_memory_clone_and_snapshot_are_purely_independent():
    memory = PlanMemory()
    PlanSnapshot.from_observation(_observation(turn=3), memory)
    memory.commit(SemanticAction(kind="RETREAT", source_serial=88))
    clone = memory.clone()
    clone.commit(
        SemanticAction(
            kind="THWACKEY_ABILITY",
            card_id=THWACKEY,
            source_serial=24,
            source_lineage=18,
        )
    )
    clone.primary_attacker_lineage = 11

    assert memory.used_thwackey_lineages == set()
    assert memory.primary_attacker_lineage is None
    assert len(memory.action_history) == 1
    assert len(clone.action_history) == 2

    snapshot = PlanSnapshot.from_observation(_observation(turn=3), memory)
    with pytest.raises(FrozenInstanceError):
        snapshot.global_turn = 99  # type: ignore[misc]


def test_telemetry_export_is_flat_numeric_and_clone_is_independent():
    telemetry = DipplinTelemetry()
    telemetry.increment("decisions")
    telemetry.record_phase("ENABLE_FIRST_ATTACK")
    telemetry.record_setup_active(APPLIN_GRASS)
    telemetry.record_quick_sign([APPLIN_GRASS, THWACKEY])
    telemetry.record_latency(2.5)
    clone = telemetry.clone()
    clone.increment("policy_errors")

    flat = telemetry.flat()
    assert flat["decisions"] == 1
    assert flat["policy_errors"] == 0
    assert flat["phase_enable_first_attack"] == 1
    assert flat[f"setup_active_{APPLIN_GRASS}"] == 1
    assert flat["search_independent_latency_ms_total"] == 2.5
    assert all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in flat.values())
    assert clone.flat()["policy_errors"] == 1


def test_malformed_observation_builds_invalid_fail_closed_snapshot():
    snapshot = PlanSnapshot.from_observation({"current": {"turn": "bad"}, "select": {}})
    assert not snapshot.valid
    assert snapshot.active is None
    assert snapshot.hand == ()
    assert snapshot.parent_card_id is None


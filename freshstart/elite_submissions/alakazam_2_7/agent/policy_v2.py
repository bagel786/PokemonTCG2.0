"""Structured legal-action policy used by the v26 MAIN controller.

The engine supplies the legal action mask.  This module scores those actions;
the caller applies narrow tactical vetoes before taking the argmax.  Card and
action embeddings are augmented with normalized live-state features so the
controller can distinguish materially different prize, damage, energy, board,
and turn situations instead of treating them as the same bag of cards.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np

MODEL_PATHS = (
    Path(__file__).with_name("policy_v2.npz"),
    Path("/kaggle_simulations/agent/agent/policy_v2.npz"),
)
_MODEL = None
_LOAD_ATTEMPTED = False

ZONE = {"hand": 0, "active": 1, "bench": 2, "discard": 3, "stadium": 4,
        "energy": 5, "tool": 6, "pre_evolution": 7}
STATE_FEATURE_DIM = 28


def _top(slot):
    if not slot:
        return None
    if isinstance(slot, list):
        return slot[-1] if slot else None
    return slot


def _card_id(card) -> int:
    return int(card.get("id", 0)) if isinstance(card, dict) else int(card or 0)


def state_tokens(state: dict) -> list[tuple[int, int, int, int, int, int]]:
    """(card, zone, owner-relative, visible, evolved, attached) tokens."""
    yi = state.get("yourIndex", 0)
    tokens = []
    for player_index, player in enumerate(state.get("players") or []):
        owner = 0 if player_index == yi else 1
        for card in player.get("hand") or []:
            cid = _card_id(card)
            if cid:
                tokens.append((cid, ZONE["hand"], owner, int(owner == 0), 0, 0))
        for zone_name, slots in (("active", player.get("active") or []),
                                 ("bench", player.get("bench") or [])):
            for slot in slots:
                mon = _top(slot)
                if not mon:
                    continue
                evolved = int(bool(mon.get("preEvolution")))
                tokens.append((_card_id(mon), ZONE[zone_name], owner, 1, evolved, 0))
                for attached_zone, key in (("energy", "energyCards"), ("tool", "tools"),
                                           ("pre_evolution", "preEvolution")):
                    for card in mon.get(key) or []:
                        tokens.append((_card_id(card), ZONE[attached_zone], owner, 1,
                                       int(attached_zone == "pre_evolution"), 1))
        for card in player.get("discard") or []:
            tokens.append((_card_id(card), ZONE["discard"], owner, 1, 0, 0))
    for card in state.get("stadium") or []:
        tokens.append((_card_id(card), ZONE["stadium"], 2, 1, 0, 0))
    return [token for token in tokens if token[0] > 0]


def _target(state: dict, option: dict) -> int:
    players = state.get("players") or []
    pi = option.get("playerIndex", state.get("yourIndex", 0))
    if not isinstance(pi, int) or pi >= len(players):
        return 0
    player = players[pi]
    area = option.get("inPlayArea", option.get("area"))
    index = option.get("inPlayIndex", option.get("index", 0))
    if area == 4:
        return _card_id(_top(player.get("active")))
    if area == 5 and isinstance(index, int) and index < len(player.get("bench") or []):
        return _card_id(_top(player["bench"][index]))
    return 0


def action_struct(state: dict, option: dict) -> dict:
    yi = state.get("yourIndex", 0)
    players = state.get("players") or []
    hand = players[yi].get("hand") or [] if yi < len(players) else []
    index = option.get("index")
    source = (_card_id(hand[index]) if isinstance(index, int) and index < len(hand)
              and option.get("type") in (7, 8, 9) else _card_id(option.get("cardId")))
    return {
        "action_type": int(option.get("type") or 0),
        "source_card": source,
        "target_card": _target(state, option),
        "attack": int(option.get("attackId") or 0),
        "target_area": int(option.get("inPlayArea", option.get("area", 0)) or 0),
        "target_owner": int(option.get("playerIndex", yi) != yi),
    }


def matchup_features(state: dict) -> np.ndarray:
    yi = state.get("yourIndex", 0)
    players = state.get("players") or [{}, {}]
    me, opp = players[yi], players[1 - yi]
    opp_ids = {_card_id(_top(slot)) for slot in (opp.get("active") or []) + (opp.get("bench") or [])}
    return np.asarray([
        int(bool(opp_ids & {345, 344, 533, 532})),
        int(bool(opp_ids & {646, 647, 648, 112, 139})),
        int(bool(opp_ids & {741, 742, 743})),
        len(me.get("prize") or []) / 6.0,
        len(opp.get("prize") or []) / 6.0,
        (me.get("deckCount") or 0) / 60.0,
        (opp.get("deckCount") or 0) / 60.0,
    ], dtype=np.float32)


def _count(player: dict, visible_key: str, hidden_key: str | None = None) -> int:
    value = player.get(visible_key)
    if isinstance(value, list):
        return len(value)
    if hidden_key is not None:
        return int(player.get(hidden_key) or 0)
    return int(value or 0)


def _player_features(player: dict) -> list[float]:
    active = _top(player.get("active")) or {}
    board = [active] + [(_top(mon) or {}) for mon in (player.get("bench") or [])]
    energy = sum(len(mon.get("energyCards") or []) for mon in board if mon)
    return [
        min(_count(player, "hand", "handCount") / 20.0, 1.5),
        min(float(player.get("deckCount") or 0) / 60.0, 1.0),
        min(_count(player, "prize") / 6.0, 1.0),
        min(_count(player, "bench") / 5.0, 1.0),
        min(float(active.get("hp") or 0) / 400.0, 1.5),
        min(float(active.get("damage") or 0) / 400.0, 1.5),
        min(len(active.get("energyCards") or []) / 5.0, 1.0),
        min(energy / 12.0, 1.0),
        float(bool(player.get("asleep"))),
        float(bool(player.get("burned"))),
        float(bool(player.get("confused"))),
        float(bool(player.get("poisoned"))),
    ]


def state_features(state: dict) -> np.ndarray:
    """Fixed-width numeric context in relative-player order."""
    yi = int(state.get("yourIndex", 0) or 0)
    players = state.get("players") or [{}, {}]
    me = players[yi] if yi < len(players) else {}
    opp_index = 1 - yi
    opp = players[opp_index] if opp_index < len(players) else {}
    first = state.get("firstPlayer", -1)
    values = [
        min(float(state.get("turn") or 0) / 30.0, 2.0),
        min(float(state.get("turnActionCount") or 0) / 20.0, 2.0),
        float(bool(state.get("energyAttached"))),
        1.0 if first == yi else (-1.0 if first == opp_index else 0.0),
        *_player_features(me),
        *_player_features(opp),
    ]
    assert len(values) == STATE_FEATURE_DIM
    return np.asarray(values, dtype=np.float32)


def load_model():
    global _MODEL, _LOAD_ATTEMPTED
    if _LOAD_ATTEMPTED:
        return _MODEL
    _LOAD_ATTEMPTED = True
    for path in MODEL_PATHS:
        if path.exists():
            data = np.load(path)
            _MODEL = {key: data[key] for key in data.files}
            break
    return _MODEL


def available() -> bool:
    return load_model() is not None


def scores(state: dict, options: list[dict]) -> list[float]:
    model = load_model()
    if model is None:
        raise RuntimeError("policy_v2.npz is not installed")
    card = model["card_embeddings"]
    tokens = state_tokens(state)
    vectors = []
    for cid, zone, owner, visible, evolved, attached in tokens:
        if cid < len(card):
            vectors.append(card[cid] + model["zone_embeddings"][zone]
                           + model["owner_embeddings"][owner]
                           + model["context_projection"] @ np.asarray(
                               [visible, evolved, attached], dtype=np.float32))
    state_vec = np.mean(vectors, axis=0) if vectors else np.zeros(card.shape[1], dtype=np.float32)
    state_vec = state_vec + matchup_features(state) @ model["matchup_projection"]
    if "state_projection" in model:
        state_vec = state_vec + state_features(state) @ model["state_projection"]
    output = []
    for option in options:
        action = action_struct(state, option)
        source = card[action["source_card"]] if action["source_card"] < len(card) else 0.0
        target = card[action["target_card"]] if action["target_card"] < len(card) else 0.0
        attack = model["attack_embeddings"][action["attack"] % len(model["attack_embeddings"])]
        action_vec = (source + target + attack
                      + model["type_embeddings"][action["action_type"]]
                      + model["area_embeddings"][action["target_area"]]
                      + model["target_owner_embeddings"][action["target_owner"]])
        output.append(float(state_vec @ action_vec + model["action_bias"][action["action_type"]]))
    return output

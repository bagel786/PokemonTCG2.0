"""State -> fixed feature vector for the value net.

ONE feature function serves both state representations: plain-dict observations
(replay training data) and engine dataclass State (live search rollout leaves).
They are parsed from the same JSON so field names match; `_g` bridges access.
Never fork this into a train copy and a live copy -- that is the shadow_replay
bug (train path != ship path) all over again.

Deck-agnostic by design (no card-id one-hots): only card_db-derived scalars
(prize value, energy-ness) so the net transfers across the crawl meta.
"""
from __future__ import annotations

from . import card_db

FEAT_VERSION = 1


def _g(o, k, default=None):
    if o is None:
        return default
    if isinstance(o, dict):
        v = o.get(k, default)
    else:
        v = getattr(o, k, default)
    return default if v is None else v


def _prize_value(cid: int) -> int:
    c = card_db.card(cid) or {}
    rule = (c.get("rule") or "").lower()
    if "ex" in rule:
        return 3 if "mega" in rule else 2
    return 1


def _side(p) -> list[float]:
    """Per-player features. p is a PlayerState (dict or dataclass)."""
    prize_left = len(_g(p, "prize", []))
    hand = _g(p, "hand")
    hand_n = len(hand) if hand is not None else _g(p, "handCount", 0)
    deck_n = _g(p, "deckCount", 0)
    bench = [b for b in _g(p, "bench", []) if b]
    act = next((a for a in _g(p, "active", []) if a), None)

    a_hpf = a_maxhp = a_energy = a_prize = a_tools = 0.0
    if act is not None:
        mx = _g(act, "maxHp", 0)
        a_hpf = _g(act, "hp", 0) / mx if mx else 0.0
        a_maxhp = mx / 340.0
        a_energy = len(_g(act, "energyCards", [])) / 4.0
        a_prize = _prize_value(_g(act, "id", 0)) / 3.0
        a_tools = float(len(_g(act, "tools", [])) > 0)

    b_energy = b_hpf = b_damaged = b_armed = 0.0
    b_prize_max = 0
    for b in bench:
        mx = _g(b, "maxHp", 0)
        e = len(_g(b, "energyCards", []))
        b_energy += e
        b_armed += float(e > 0)
        if mx:
            hpf = _g(b, "hp", 0) / mx
            b_hpf += hpf
            b_damaged += float(hpf < 1.0)
        b_prize_max = max(b_prize_max, _prize_value(_g(b, "id", 0)))

    disc = _g(p, "discard", [])
    disc_energy = sum(1 for c in disc if card_db.is_energy(_g(c, "id", 0)))
    # asleep/paralyzed skip the mon's action; poison/burn only chip
    stuck = float(_g(p, "asleep", False)) + float(_g(p, "paralyzed", False)) \
        + 0.5 * float(_g(p, "confused", False))
    chip = float(_g(p, "poisoned", False)) + float(_g(p, "burned", False))

    return [
        prize_left / 6.0,
        hand_n / 10.0,
        deck_n / 40.0,
        len(bench) / 5.0,
        float(act is not None),
        a_hpf, a_maxhp, a_energy, a_prize, a_tools,
        b_energy / 8.0,
        b_hpf / 5.0,
        b_damaged / 5.0,
        b_armed / 5.0,
        b_prize_max / 3.0,
        len(disc) / 30.0,
        disc_energy / 10.0,
        stuck / 2.0,
        chip / 2.0,
    ]


_SIDE_NAMES = ["prize_left", "hand_n", "deck_n", "bench_n", "has_active",
               "act_hpf", "act_maxhp", "act_energy", "act_prize", "act_tools",
               "bench_energy", "bench_hpf", "bench_damaged", "bench_armed",
               "bench_prize_max", "discard_n", "discard_energy", "stuck", "chip"]
FEATURE_NAMES = (["turn"]
                 + [f"my_{n}" for n in _SIDE_NAMES]
                 + [f"opp_{n}" for n in _SIDE_NAMES]
                 + ["d_prize", "d_deck", "d_hand", "d_bench", "d_act_hpf", "d_energy"])


def encode(state, me: int) -> list[float]:
    """state: engine State (dict or dataclass), me: player index. ~45 dims."""
    players = _g(state, "players", [{}, {}])
    mine, opp = _side(players[me]), _side(players[1 - me])
    turn = [_g(state, "turn", 0) / 40.0]
    # explicit PBRS-style diffs (prize race, deck race, hand economy, board, hp, energy)
    diffs = [opp[0] - mine[0], mine[2] - opp[2], mine[1] - opp[1],
             mine[3] - opp[3], mine[5] - opp[5],
             (mine[7] + mine[10]) - (opp[7] + opp[10])]
    return turn + mine + opp + diffs


N_FEATURES = len(FEATURE_NAMES)


if __name__ == "__main__":
    # self-check: dict state and attribute-access state must encode identically
    from types import SimpleNamespace as NS
    import json
    import copy

    mon = {"id": 596, "serial": 1, "hp": 60, "maxHp": 140, "appearThisTurn": False,
           "energies": [5], "energyCards": [{"id": 5, "serial": 9, "playerIndex": 0}],
           "tools": [], "preEvolution": []}
    player = {"active": [mon], "bench": [dict(mon, hp=140)], "benchMax": 5,
              "deckCount": 22, "discard": [{"id": 5, "serial": 3, "playerIndex": 0}],
              "prize": [None] * 4, "handCount": 7, "hand": None,
              "poisoned": False, "burned": True, "asleep": False,
              "paralyzed": False, "confused": False}
    state = {"turn": 9, "yourIndex": 0, "result": -1,
             "players": [copy.deepcopy(player), copy.deepcopy(player)]}

    def to_ns(o):
        if isinstance(o, dict):
            return NS(**{k: to_ns(v) for k, v in o.items()})
        if isinstance(o, list):
            return [to_ns(v) for v in o]
        return o

    v_dict = encode(state, 0)
    v_ns = encode(to_ns(state), 0)
    assert len(v_dict) == N_FEATURES == len(v_ns), (len(v_dict), N_FEATURES)
    assert v_dict == v_ns, "dict vs dataclass encoding diverged"
    assert all(isinstance(x, float) or isinstance(x, int) for x in v_dict)
    print(f"OK: {N_FEATURES} features, dict==dataclass")
    print(json.dumps(dict(zip(FEATURE_NAMES, [round(x, 3) for x in v_dict]))))

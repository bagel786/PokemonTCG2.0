"""Card-aware action scorer (v3) -- shared encoder + numpy inference.

Replaces policy_v2's bilinear `state_vec @ action_vec` (82k params, no hidden
layer) with a deep-sets state encoder and an MLP scorer over
[state, action, state*action].  The interaction term is the point: a dot product
cannot express "play Rare Candy IF a stage-2 is in hand", which is most of what
piloting this deck actually is.

The SAME slim/encode functions are used by scripts/build_corpus_v3.py at
extraction time and by the live agent at inference, so train/serve skew is
structurally impossible.  Inference is pure numpy -- the Kaggle image is not
guaranteed to ship torch, and a 2-layer MLP does not need it.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np

MODEL_PATHS = (
    Path(__file__).with_name("policy_v3.npz"),
    Path("/kaggle_simulations/agent/agent/policy_v3.npz"),
)

MAX_CARD = 1400
MAX_ATTACK = 2100
N_ZONE = 8
N_OWNER = 2
N_TYPE = 20
N_AREA = 16
MAX_TOKENS = 160
N_STATE_FEAT = 24
N_OPT_FEAT = 8
# Which Pokemon a token hangs off: 0 = unattached (hand/discard/stadium),
# 1 = active, 2..6 = bench slot 0..4. Without this an Alakazam's Psychic Energy
# and a benched Abra's are the SAME token, so no amount of pooling can answer
# "is the mon this option targets actually armed?".
N_SLOT = 7

ZONE = {"hand": 0, "active": 1, "bench": 2, "discard": 3, "stadium": 4,
        "energy": 5, "tool": 6, "pre": 7}


# --------------------------------------------------------------- slim encoding
# NOTE: byte-identical to scripts/build_corpus_v3.py. If you change one, change
# both, or every trained model silently mismatches what the agent feeds it.

def slim_mon(slot) -> dict | None:
    mon = slot[-1] if isinstance(slot, list) and slot else slot
    if not isinstance(mon, dict):
        return None
    return {
        "id": mon.get("id"),
        "hp": mon.get("hp"),
        "dmg": mon.get("damage"),
        "e": [c.get("id") for c in (mon.get("energyCards") or [])],
        "t": [c.get("id") for c in (mon.get("tools") or [])],
        "pre": [c.get("id") for c in (mon.get("preEvolution") or [])],
    }


def slim_state(state: dict) -> dict:
    yi = state.get("yourIndex", 0)
    players = []
    for i, p in enumerate(state.get("players") or []):
        players.append({
            "me": int(i == yi),
            "hand": [c.get("id") for c in (p.get("hand") or [])],
            "active": [slim_mon(s) for s in (p.get("active") or [])],
            "bench": [slim_mon(s) for s in (p.get("bench") or [])],
            "discard": [c.get("id") for c in (p.get("discard") or [])],
            "deck": p.get("deckCount"),
            "prize": len(p.get("prize") or []),
        })
    return {
        "turn": state.get("turn"),
        "yi": yi,
        "players": players,
        "stadium": [(c or {}).get("id") for c in (state.get("stadium") or [])],
        "supporterPlayed": state.get("supporterPlayed"),
        "energyAttached": state.get("energyAttached"),
    }


def slim_option(o: dict) -> dict:
    return {k: o.get(k) for k in
            ("type", "index", "cardId", "attackId", "area", "inPlayArea",
             "inPlayIndex", "playerIndex", "serial", "number")
            if o.get(k) is not None}


# ------------------------------------------------------------------- tokenizer

def _cid(x) -> int:
    try:
        v = int(x)
    except (TypeError, ValueError):
        return 0
    return v if 0 < v < MAX_CARD else 0


def state_tokens(s: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(card, zone, owner, slot) for every visible card. Owner 0 = us.

    `slot` binds an energy/tool/pre token to the Pokemon carrying it, so an
    option that names inPlayIndex can attend to that Pokemon's attachments.
    """
    cards, zones, owners, slots = [], [], [], []

    def add(cid, zone, owner, slot=0):
        cid = _cid(cid)
        if cid and len(cards) < MAX_TOKENS:
            cards.append(cid)
            zones.append(zone)
            owners.append(owner)
            slots.append(slot)

    for p in s.get("players") or []:
        owner = 0 if p.get("me") else 1
        for cid in p.get("hand") or []:
            add(cid, ZONE["hand"], owner)
        for zname, mons in (("active", p.get("active") or []),
                            ("bench", p.get("bench") or [])):
            for si, mon in enumerate(mons):
                if not mon:
                    continue
                slot = 1 if zname == "active" else min(si + 2, N_SLOT - 1)
                add(mon.get("id"), ZONE[zname], owner, slot)
                for cid in mon.get("e") or []:
                    add(cid, ZONE["energy"], owner, slot)
                for cid in mon.get("t") or []:
                    add(cid, ZONE["tool"], owner, slot)
                for cid in mon.get("pre") or []:
                    add(cid, ZONE["pre"], owner, slot)
        # discard is long and low-signal per-card: keep the tail only
        for cid in (p.get("discard") or [])[-12:]:
            add(cid, ZONE["discard"], owner)
    for cid in s.get("stadium") or []:
        add(cid, ZONE["stadium"], 0)

    n = len(cards)
    pad = MAX_TOKENS - n
    return (np.array(cards + [0] * pad, dtype=np.int32),
            np.array(zones + [0] * pad, dtype=np.int32),
            np.array(owners + [0] * pad, dtype=np.int32),
            np.array(slots + [0] * pad, dtype=np.int32))


def _side(s: dict, me: bool) -> dict:
    for p in s.get("players") or []:
        if bool(p.get("me")) == me:
            return p
    return {}


def state_feats(s: dict) -> np.ndarray:
    """Normalized scalars the token bag cannot express (counts, damage, tempo)."""
    us, them = _side(s, True), _side(s, False)
    f = []
    for p in (us, them):
        actives = [m for m in (p.get("active") or []) if m]
        bench = [m for m in (p.get("bench") or []) if m]
        a = actives[0] if actives else {}
        hp = a.get("hp") or 0
        dmg = a.get("dmg") or 0
        f += [
            len(p.get("hand") or []) / 10.0,
            (p.get("deck") or 0) / 60.0,
            (p.get("prize") or 0) / 6.0,
            len(bench) / 5.0,
            hp / 400.0,
            dmg / 400.0,
            (hp - dmg) / 400.0,
            len(a.get("e") or []) / 4.0,
            sum(len(m.get("e") or []) for m in bench) / 8.0,
            len(p.get("discard") or []) / 60.0,
        ]
    f += [
        (s.get("turn") or 0) / 30.0,
        1.0 if s.get("supporterPlayed") else 0.0,
        1.0 if s.get("energyAttached") else 0.0,
        1.0 if (s.get("stadium") or []) else 0.0,
    ]
    return np.asarray(f[:N_STATE_FEAT] + [0.0] * max(0, N_STATE_FEAT - len(f)),
                      dtype=np.float32)


def option_arrays(options: list[dict], s: dict) -> tuple[np.ndarray, ...]:
    """Per-option categorical ids + numeric features."""
    n = len(options)
    typ = np.zeros(n, dtype=np.int32)
    card = np.zeros(n, dtype=np.int32)
    atk = np.zeros(n, dtype=np.int32)
    area = np.zeros(n, dtype=np.int32)
    feats = np.zeros((n, N_OPT_FEAT), dtype=np.float32)
    hand = (_side(s, True).get("hand") or [])
    for i, o in enumerate(options):
        typ[i] = min(int(o.get("type") or 0), N_TYPE - 1)
        idx = o.get("index")
        cid = o.get("cardId")
        if cid is None and isinstance(idx, int) and 0 <= idx < len(hand):
            cid = hand[idx]
        card[i] = _cid(cid)
        a = o.get("attackId") or 0
        atk[i] = int(a) if 0 < int(a) < MAX_ATTACK else 0
        area[i] = min(int(o.get("area") or o.get("inPlayArea") or 0), N_AREA - 1)
        feats[i] = [
            1.0 if o.get("playerIndex") == s.get("yi") else 0.0,
            (o.get("inPlayIndex") or 0) / 5.0,
            (o.get("number") or 0) / 10.0,
            1.0 if o.get("attackId") else 0.0,
            1.0 if o.get("cardId") else 0.0,
            (idx or 0) / 10.0 if isinstance(idx, int) else 0.0,
            i / max(1.0, n),
            n / 20.0,
        ]
    return typ, card, atk, area, feats


def encode(s: dict, options: list[dict]) -> dict:
    tc, tz, to, ts = state_tokens(s)
    typ, card, atk, area, feats = option_arrays(options, s)
    return {"tok_card": tc, "tok_zone": tz, "tok_owner": to, "tok_slot": ts,
            "sfeat": state_feats(s), "o_type": typ, "o_card": card,
            "o_atk": atk, "o_area": area, "o_feat": feats}


# ------------------------------------------------------------ numpy inference

_MODEL = None
_TRIED = False


def load_model():
    global _MODEL, _TRIED
    if _MODEL is not None or _TRIED:
        return _MODEL
    _TRIED = True
    for path in MODEL_PATHS:
        try:
            if path.exists():
                g = {k: v for k, v in np.load(path).items()}
                # A pre-attention artifact has no slot_emb/q_w and would KeyError
                # mid-game. Reject it so available() is False and search falls
                # back to policy_v2 instead of crashing on a packaging slip.
                if "slot_emb" not in g or "q_w" not in g:
                    continue
                _MODEL = g
                return _MODEL
        except Exception:
            continue
    return None


def available() -> bool:
    return load_model() is not None


def _relu(x):
    return np.maximum(x, 0.0)


def scores(state: dict, options: list[dict]) -> list[float] | None:
    """Score each legal option. `state` is a RAW obs['current'] dict."""
    if not options:
        return None
    return scores_slim(slim_state(state), options)


def scores_slim(s: dict, options: list[dict]) -> list[float] | None:
    """Same, for an already-slimmed state (what the training corpus stores)."""
    m = load_model()
    if m is None or not options:
        return None
    e = encode(s, options)

    mask = (e["tok_card"] > 0).astype(np.float32)[:, None]
    tok = (m["card_emb"][e["tok_card"]] + m["zone_emb"][e["tok_zone"]]
           + m["owner_emb"][e["tok_owner"]] + m["slot_emb"][e["tok_slot"]]) * mask
    tok = _relu(tok @ m["tok_w"] + m["tok_b"]) * mask
    pooled = np.concatenate([
        tok.sum(0) / max(mask.sum(), 1.0),
        np.where(mask > 0, tok, -1e4).max(0) if mask.sum() else np.zeros(tok.shape[1], np.float32),
    ])
    h = np.concatenate([pooled, e["sfeat"]])
    h = _relu(h @ m["s_w1"] + m["s_b1"])
    h = _relu(h @ m["s_w2"] + m["s_b2"])

    a = np.concatenate([
        m["type_emb"][e["o_type"]], m["ocard_emb"][e["o_card"]],
        m["atk_emb"][e["o_atk"]], m["area_emb"][e["o_area"]], e["o_feat"],
    ], axis=1)
    a = _relu(a @ m["a_w1"] + m["a_b1"])

    # Cross-attention: each option queries the token set directly, so scoring an
    # option that names a slot can read that slot's attachments instead of the
    # single pooled vector shared by every option.
    q = a @ m["q_w"] + m["q_b"]
    att = q @ tok.T / np.sqrt(tok.shape[1])
    att = np.where(mask.reshape(1, -1) > 0, att, -1e9)
    att = np.exp(att - att.max(1, keepdims=True))
    ctx = (att / att.sum(1, keepdims=True)) @ tok

    hh = np.repeat(h[None, :], len(options), axis=0)
    x = np.concatenate([hh, a, hh * a, ctx], axis=1)
    x = _relu(x @ m["j_w1"] + m["j_b1"])
    out = (x @ m["j_w2"] + m["j_b2"]).reshape(-1)
    return [float(v) for v in out]

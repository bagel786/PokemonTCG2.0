"""Yushin decision clone: shared feature extraction + linear scoring.

One code path for training (scripts/train_clone.py, on replay records) and live
play (policy.py select handlers) — replay `obs.current`/`obs.select` are the
live format, so features computed here are identical in both worlds.

A decision is (state, select) with options; each option gets features
phi = state-base + option + option x state-flag interactions, and
score = w . phi. Weights per FAMILY live in yushin_model.json (trained on the
#1 ladder player's replays; held-out agreement table in each family's meta).
Families:
  keep    ctx8 own-hand discard (score = pitch-worthiness; pick k HIGHEST)
  fetch   ctx7 deck search (area 1) and reveal-take (area 12)
  recover ctx7/ctx9 own-discard recovery (Night Stretcher / Lana's / Sacred Ash)
  bench   ctx5 Poffin (area 1) and ctx2 setup bench (from hand)
  lead    ctx1 opening active pick
  promote ctx4 our switch-in after a KO
  rotate  ctx3 own-side switch (Trading Places / Teleportation)
  boss    ctx3 opponent-side drag (Boss's Orders)
  candy   ctx37 evolve target (trained for reference; NOT wired — code beats it)

scores() is called inside search rollouts, so the state is scanned once per
decision and the dot product never materializes the full feature dict.
"""
from __future__ import annotations

import json
import os

from . import card_db

ABRA, KADABRA, ALAKAZAM = 741, 742, 743
DUNSPARCE, DUDUNSPARCE = 305, 66
_LINE = {ABRA, KADABRA, ALAKAZAM, DUNSPARCE, DUDUNSPARCE}

# Opponent archetype fingerprints (clone v2, 2026-07-19): matchup flags cross
# with every option feature (option_features' flag loop), so the model can
# learn matchup-conditional ordering — the current features can't distinguish
# "digging vs a mill wall" from "digging vs aggro". Unretrained models ignore
# the new crossed names (weight 0), so adding these is inert until retrain.
_ARCH_WALL = {345, 533, 344, 532}            # Crustle / Dwebble (wall-mill)
_ARCH_GRIMM = {646, 647, 648, 112, 139}      # Marnie's Grimmsnarl line + Munkidori
_ARCH_MIRROR = {ABRA, KADABRA, ALAKAZAM}     # Alakazam mirror

_MODEL_PATHS = (
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "yushin_model.json"),
    "/kaggle_simulations/agent/agent/yushin_model.json",
)
_model_cache: dict | None = None


# --- obs resolvers (mirror policy.py; kept here so training needs no policy import) --
# Callers pass the plain-dict obs (live play / replays already are; search.py
# converts its dataclass State via dataclasses.asdict before calling in).

def _top_mon(slot) -> dict:
    if not slot:
        return {}
    mons = slot if isinstance(slot, list) else [slot]
    return mons[-1] or {}


def _in_play(p: dict) -> list[dict]:
    out = []
    for slot in [p.get("active")] + list(p.get("bench") or []):
        m = _top_mon(slot)
        if m:
            out.append(m)
    return out


def _hand_ids(p: dict) -> list[int]:
    return [c.get("id") for c in ((p or {}).get("hand") or []) if isinstance(c, dict)]


def _energy_n(mon: dict) -> int:
    return len((mon or {}).get("energyCards") or [])


def _card_id(opt: dict, state: dict, sel: dict | None) -> int:
    """Resolve a Card option to its card id (deck / hand / discard / looking / board)."""
    area, idx = opt.get("area"), opt.get("index")
    pi = opt.get("playerIndex", (state or {}).get("yourIndex", 0))
    players = (state or {}).get("players") or []
    p = players[pi] if pi < len(players) else {}
    if area == 1:
        deck = (sel or {}).get("deck") or []
        if idx is not None and idx < len(deck):
            c = deck[idx]
            return (c.get("id") if isinstance(c, dict) else c) or 0
        return 0
    src = {2: p.get("hand"), 3: p.get("discard"), 6: p.get("prize"),
           12: (state or {}).get("looking")}.get(area)
    if src is not None and idx is not None and idx < len(src):
        c = src[idx]
        return (c.get("id") if isinstance(c, dict) else c) or 0
    if area in (4, 5):
        return _target_mon(opt, state).get("id") or 0
    return 0


def _target_mon(opt: dict, state: dict) -> dict:
    """Resolve an in-play option (area 4 active / 5 bench) to its top mon."""
    pi = opt.get("playerIndex", (state or {}).get("yourIndex", 0))
    players = (state or {}).get("players") or []
    p = players[pi] if pi < len(players) else {}
    area = opt.get("inPlayArea", opt.get("area"))
    idx = opt.get("inPlayIndex", opt.get("index"))
    if area == 4:
        return _top_mon(p.get("active"))
    if area == 5:
        b = p.get("bench") or []
        if idx is not None and idx < len(b):
            return _top_mon(b[idx])
    return {}


def _prize_value(cid: int) -> int:
    c = card_db.card(cid) or {}
    rule = (c.get("rule") or "").lower()
    if "ex" in rule:
        return 3 if "mega" in rule else 2
    return 1


# --- family routing ------------------------------------------------------------------

def family_of(ctx: int, options: list[dict], state: dict) -> str | None:
    if not options:
        return None
    my_idx = (state or {}).get("yourIndex", 0)
    area = options[0].get("area")
    pi = options[0].get("playerIndex")
    if ctx == 8 and area == 2 and pi == my_idx:
        return "keep"
    if ctx == 7:
        if all(op.get("area") == 1 for op in options):
            return "fetch"
        if all(op.get("area") == 12 for op in options):
            return "fetch"
        if all(op.get("area") == 3 and op.get("playerIndex") == my_idx for op in options):
            return "recover"
    if ctx == 9 and all(op.get("area") == 3 and op.get("playerIndex") == my_idx
                        for op in options):
        return "recover"
    if ctx == 5 and all(op.get("area") == 1 for op in options):
        return "bench"
    if ctx == 2 and all(op.get("area") == 2 for op in options):
        return "bench"
    if ctx == 1 and all(op.get("area") == 2 for op in options):
        return "lead"  # opening active pick (yushin: Abra 76% / Dunsparce 20%)
    if ctx == 4:
        return "promote"
    if ctx == 3 and pi is not None:
        return "boss" if pi != my_idx else "rotate"
    if ctx == 37:
        return "candy"
    if ctx == 0:
        return "main"
    return None


# MAIN option types (cg/api.py OptionType)
_PLAY, _ATTACH, _EVOLVE, _ABILITY, _RETREAT, _ATTACK, _END = 7, 8, 9, 10, 12, 13, 14


def _main_target(opt: dict, state: dict, sel: dict | None) -> tuple[int, dict]:
    """Best-effort (card id, in-play mon) a MAIN option acts on, for scoring."""
    t = opt.get("type")
    if t == _PLAY:
        yi = (state or {}).get("yourIndex", 0)
        players = (state or {}).get("players") or []
        hand = _hand_ids(players[yi]) if yi < len(players) else []
        idx = opt.get("index")
        return (hand[idx] if idx is not None and idx < len(hand) else 0), {}
    if t in (_ATTACH, _EVOLVE):
        # MAIN-select ATTACH/EVOLVE options carry the hand card in "index" and
        # the target in inPlayArea/inPlayIndex -- they never set "area", so
        # _card_id (built for CARD-select options, which DO carry "area")
        # always fell through to its area==None default and returned 0. That
        # silently zeroed out every src_* feature (is_energy, fills_gap,
        # dup_hand, ...) for every ATTACH/EVOLVE decision in the game, leaving
        # the "main" clone model -- which feeds clone_bonus (+-30) and
        # _main_clone_top's candidate inclusion -- blind to WHICH card was
        # being played on the two most decision-critical MAIN option types.
        # Found 2026-07-15 auditing search.py/policy.py for siblings of the
        # _bad_attach stranded-active bug. Same hand-index resolution as the
        # _PLAY branch above, since ATTACH/EVOLVE options use the same "index
        # into hand" convention.
        yi = (state or {}).get("yourIndex", 0)
        players = (state or {}).get("players") or []
        hand = _hand_ids(players[yi]) if yi < len(players) else []
        idx = opt.get("index")
        cid = hand[idx] if idx is not None and idx < len(hand) else 0
        return cid, _target_mon(opt, state)
    if t == _ABILITY:
        mon = _target_mon(opt, state)
        return mon.get("id") or 0, mon
    if t == _ATTACK:
        yi = (state or {}).get("yourIndex", 0)
        players = (state or {}).get("players") or []
        mon = _top_mon(players[yi].get("active")) if yi < len(players) else {}
        return opt.get("attackId") or 0, mon
    return 0, {}


# --- per-decision environment --------------------------------------------------------

def _fills_gap(cid: int, ids: list[int], hand: list[int]) -> bool:
    """Is this card the missing next piece of an evolution line we're building?"""
    if cid == ALAKAZAM:
        return (KADABRA in ids or ABRA in ids) and ALAKAZAM not in ids and ALAKAZAM not in hand
    if cid == KADABRA:
        return ABRA in ids and KADABRA not in hand
    if cid == DUDUNSPARCE:
        return DUNSPARCE in ids and DUDUNSPARCE not in ids and DUDUNSPARCE not in hand
    if cid in (ABRA, DUNSPARCE):
        return cid not in ids
    return False


def _env(state: dict, sel: dict | None, hand_override: list[int] | None = None) -> dict:
    """Everything option scoring needs, computed ONCE per decision.

    hand_override replaces the state-derived hand for dup_hand/fills_gap-style
    features -- used by scores_sequential to make a multi-pick family (keep) see
    the SHRINKING hand as it picks, so set effects (pitch the 2nd copy of a card
    less eagerly once the 1st is already going) become expressible."""
    yi = (state or {}).get("yourIndex", 0)
    players = (state or {}).get("players") or [{}, {}]
    me, opp = players[yi], players[1 - yi]
    hand = hand_override if hand_override is not None else _hand_ids(me)
    mine = _in_play(me)
    ids = [m.get("id") for m in mine]
    disc = [c.get("id") for c in (me.get("discard") or []) if isinstance(c, dict)]
    bench_n = len([b for b in (me.get("bench") or []) if b])
    tb = ((state or {}).get("turn", 0) + 1) // 2
    my_act = _top_mon(me.get("active"))
    opp_act = _top_mon(opp.get("active"))
    my_left, opp_left = len(me.get("prize") or []), len(opp.get("prize") or [])
    energy_hand = sum(1 for h in hand if card_db.is_energy(h))
    zam_play = ids.count(ALAKAZAM)
    line_armed = sum(1 for m in mine if m.get("id") in (ABRA, KADABRA, ALAKAZAM)
                     and _energy_n(m) > 0)
    reach = 20 * len(hand) if my_act.get("id") == ALAKAZAM else 0

    base = {
        "tb": min(tb, 8) / 8.0,
        "hand_n": len(hand) / 10.0,
        "deck_n": (me.get("deckCount") or 0) / 40.0,
        "bench_n": bench_n / 5.0,
        "my_left": my_left / 6.0,
        "opp_left": opp_left / 6.0,
        "line_armed": line_armed / 3.0,
        "my_hpf": (my_act.get("hp", 0) / my_act["maxHp"]) if my_act.get("maxHp") else 0.0,
        "opp_hpf": (opp_act.get("hp", 0) / opp_act["maxHp"]) if opp_act.get("maxHp") else 0.0,
        "opp_prize_val": _prize_value(opp_act.get("id") or 0) / 3.0 if opp_act else 0.0,
    }
    flags = {
        "early": tb <= 2,
        "zam_built": zam_play > 0,
        "zam_secured": zam_play > 0 or ALAKAZAM in hand,
        "zam_armed": any(m.get("id") == ALAKAZAM and _energy_n(m) > 0 for m in mine),
        "abra_waiting": ABRA in ids,
        "dud_built": DUDUNSPARCE in ids,
        "bench0": bench_n == 0,
        "bench_thin": bench_n < 2,
        "no_energy_hand": energy_hand == 0,
        "hand_big": len(hand) >= 6,
        "behind": my_left > opp_left,
        "ph_ko": reach and opp_act.get("hp") is not None
                 and reach >= (opp_act.get("hp") or 9999),
    }
    opp_ids = {m.get("id") for m in _in_play(opp)}
    flags.update({
        "vs_wall": bool(opp_ids & _ARCH_WALL),
        "vs_grimm": bool(opp_ids & _ARCH_GRIMM),
        "vs_mirror": bool(opp_ids & _ARCH_MIRROR),
    })
    flags = [k for k, v in flags.items() if v]
    eff = (sel or {}).get("effect") or {}
    if eff.get("id"):
        flags.append(f"via{eff['id']}")  # trigger card (Dawn/Poke Pad/Poffin/...)
    opp_bench_prizes = [_prize_value(m.get("id") or 0) for m in _in_play(opp)[1:]]
    return {"base": base, "flags": flags, "hand": hand, "ids": ids, "disc": disc,
            "reach": reach,
            "opp_max_bench_prize": max(opp_bench_prizes, default=0)}


_CARD_FAMS = frozenset({"keep", "fetch", "recover", "bench", "lead"})


def _card_option(cid: int, env: dict) -> dict:
    c = card_db.card(cid) or {}
    st = c.get("stage_or_type") or ""
    f = {
        f"c{cid}": 1.0,
        "is_basic_mon": st == "Basic Pokémon",
        "is_evo_mon": st.startswith("Stage"),
        "is_supporter": st == "Supporter",
        "is_item": st == "Item",
        "is_tool": st == "Pokémon Tool",
        "is_stadium": st == "Stadium",
        "is_energy": st.endswith("Energy"),
        "is_line": cid in _LINE,
        "fills_gap": _fills_gap(cid, env["ids"], env["hand"]),
        "hp": card_db.hp(cid) / 340.0,
        "dup_hand": min(env["hand"].count(cid), 3) / 3.0,
        "dup_play": min(env["ids"].count(cid), 3) / 3.0,
        "dup_discard": min(env["disc"].count(cid), 3) / 3.0,
    }
    return {k: float(v) for k, v in f.items() if v}


def _board_option(mon: dict, env: dict, own: bool) -> dict:
    mid = mon.get("id") or 0
    max_hp = mon.get("maxHp") or 0
    retreat = (card_db.card(mid) or {}).get("retreat")
    f = {
        "prize_val": _prize_value(mid) / 3.0,
        "hpf": (mon.get("hp", 0) / max_hp) if max_hp else 0.0,
        "hp": (mon.get("hp") or 0) / 340.0,
        "energy_n": min(_energy_n(mon), 4) / 4.0,
        "dmg_taken": ((max_hp - mon.get("hp", 0)) / 340.0) if max_hp else 0.0,
        "fresh": bool(mon.get("appearThisTurn")),
        "has_tool": bool(mon.get("tools")),
        "retreat_cost": min(retreat, 4) / 4.0 if retreat else 0.0,
    }
    if own:
        f[f"m{mid}"] = 1.0
        f["is_attacker"] = mid in (ALAKAZAM, KADABRA, ABRA)
    else:
        # opponent mons: role features only, so the model generalizes across the meta
        f["koable"] = 0 < (mon.get("hp") or 9999) <= env["reach"]
        f["evolved"] = bool(mon.get("preEvolution"))
        # is this the biggest threat on their bench, or is a bigger one left behind?
        f["is_top_threat"] = _prize_value(mid) >= env.get("opp_max_bench_prize", 0)
    return {k: float(v) for k, v in f.items() if v}


def _main_option(opt: dict, env: dict, state: dict, sel: dict | None) -> dict:
    t = opt.get("type")
    f = {f"type{t}": 1.0}
    cid, mon = _main_target(opt, state, sel)
    if cid and t != _ATTACK:
        f.update({f"src_{k}": v for k, v in _card_option(cid, env).items()})
    elif t == _ATTACK:
        f["atk_reach"] = min(env["reach"], 4) / 4.0 if env["reach"] else 0.0
    if mon:
        f.update({f"tgt_{k}": v for k, v in _board_option(mon, env, own=True).items()})
    return f


def _opt_feats(fam: str, env: dict, state: dict, opt: dict, sel: dict | None) -> dict:
    if fam == "main":
        return _main_option(opt, env, state, sel)
    if fam in _CARD_FAMS:
        return _card_option(_card_id(opt, state, sel), env)
    return _board_option(_target_mon(opt, state), env,
                         own=fam in ("promote", "rotate", "candy"))


def option_features(fam: str, state: dict, opt: dict, sel: dict | None,
                    hand_override: list[int] | None = None) -> dict:
    """Full phi(state, option) dict — the TRAINING representation. scores() below
    computes the identical dot product without materializing this dict."""
    env = _env(state, sel, hand_override)
    of = _opt_feats(fam, env, state, opt, sel)
    out = {"bias": 1.0}
    out.update(env["base"])
    out.update(of)
    for k, v in of.items():
        for s in env["flags"]:
            out[f"{k}|{s}"] = v
    return out


# --- scoring -------------------------------------------------------------------------

def _model() -> dict:
    global _model_cache
    if _model_cache is None:
        _model_cache = {}
        for p in _MODEL_PATHS:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as fh:
                    _model_cache = json.load(fh)
                break
        # pooled all-elite retrain (policy_model.json) overrides per-family;
        # POLICY_MODEL=0 kill switch reverts to yushin-only weights exactly.
        if os.environ.get("POLICY_MODEL", "1") != "0":
            for p in _MODEL_PATHS:
                q = os.path.join(os.path.dirname(p), "policy_model.json")
                if os.path.exists(q):
                    with open(q, "r", encoding="utf-8") as fh:
                        _model_cache.update(json.load(fh))
                    break
    return _model_cache


def has_model(fam: str) -> bool:
    return bool(_model().get(fam, {}).get("w"))


_SEQUENTIAL_FAMS = frozenset({"keep"})


def pick_sequential(fam: str, state: dict, options: list[dict], sel: dict | None,
                    k: int) -> list[int]:
    """Greedy sequential pick for a multi-select family: score, take the best,
    shrink the hand it came from, rescore the rest. Captures set effects a
    single independent-per-option ranking can't: e.g. `keep` pitching the
    SECOND copy of a card less eagerly once the first is already going, since
    dup_hand/fills_gap see the shrunk hand on each later pick."""
    yi = (state or {}).get("yourIndex", 0)
    players = (state or {}).get("players") or [{}, {}]
    hand = list(_hand_ids(players[yi] if yi < len(players) else {}))
    remaining = list(range(len(options)))
    picked: list[int] = []
    for _ in range(min(k, len(options))):
        sc = scores(fam, state, [options[i] for i in remaining], sel, hand_override=hand)
        best_pos = max(range(len(remaining)), key=lambda p: sc[p])
        i = remaining.pop(best_pos)
        picked.append(i)
        cid = _card_id(options[i], state, sel)
        if cid in hand:
            hand.remove(cid)
    return sorted(picked)


def scores(fam: str, state: dict, options: list[dict], sel: dict | None,
          hand_override: list[int] | None = None) -> list[float]:
    """Clone score per option (higher = yushin more likely picks it; for `keep`
    higher = more likely PITCHED). Must equal w . option_features(...) exactly."""
    w = _model().get(fam, {}).get("w", {})
    env = _env(state, sel, hand_override)
    common = w.get("bias", 0.0) + sum(w.get(k, 0.0) * v for k, v in env["base"].items())
    flags = env["flags"]
    out = []
    for opt in options:
        s = common
        for k, v in _opt_feats(fam, env, state, opt, sel).items():
            s += w.get(k, 0.0) * v
            for fl in flags:
                wk = w.get(f"{k}|{fl}")
                if wk:
                    s += wk * v
        out.append(s)
    return out

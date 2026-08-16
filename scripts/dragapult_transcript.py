#!/usr/bin/env python3
"""Compact semantic turn transcript for a replay. One line per hero decision."""
import json, sys, csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
from cg.api import to_observation_class, AreaType  # noqa: E402

CARD_NAMES = {}
with open(ROOT / "freshstart/data/EN_Card_Data.csv") as f:
    for row in csv.DictReader(f):
        CARD_NAMES[row["Card ID"]] = row["Card Name"]

ATTACKS = {}
sys.path.insert(0, str(ROOT / "vendor"))
from cg.api import all_card_data  # noqa: E402
for c in all_card_data():
    for a in (c.attacks or []):
        if isinstance(a, int):
            pass
ATTACK_NAMES = {
    937: "ShadowBullet", 141: "MindBend", 934: "Corkscrew", 935: "Filch",
    153: "JetHeadbutt", 154: "PhantomDive", 323: "ItchyPollen", 324: "?",
}

AREA = {1: "DECK", 2: "HAND", 3: "DISC", 4: "ACT", 5: "BENCH", 6: "PRIZE", 7: "STAD", 8: "EN", 9: "TOOL", 10: "PRE", 12: "LOOK"}


def zone_cards(cur, seat, zone):
    players = cur.get("players") or []
    if seat >= len(players):
        return []
    return players[seat].get(zone) or []


def card_str(c):
    if not c:
        return "?"
    cid = c.get("id")
    hp = c.get("hp") or 0
    maxhp = c.get("maxHp") or hp
    en = sum(1 for e in (c.get("attachedEnergy") or []) if e.get("id") != 0)
    name = CARD_NAMES.get(str(cid), str(cid))
    return f"{name}[{hp}/{maxhp}]{en}E"


def resolve(cur, seat, area, index):
    m = {4: "active", 5: "bench", 2: "hand", 3: "discard", 6: "prize", 1: "deck"}
    zone = m.get(area)
    if zone is None:
        return None
    cards = zone_cards(cur, seat, zone)
    if 0 <= index < len(cards):
        return cards[index]
    return None


def decode(cur, seat, sel, action):
    out = []
    opts = sel.get("option") or []
    for idx in action:
        if idx >= len(opts):
            out.append("?IDX")
            continue
        o = opts[idx]
        t = o.get("type")
        pseat = o.get("playerIndex", seat)
        if t == 14:
            out.append("END")
        elif t == 7:
            c = resolve(cur, pseat, 2, o.get("index", 0))
            out.append(f"PLAY:{card_str(c)}")
        elif t == 8:
            src = resolve(cur, pseat, 2, o.get("index", 0))
            tgt = resolve(cur, pseat, o.get("inPlayArea", 4), o.get("inPlayIndex", 0))
            out.append(f"ATTACH:{card_str(src)}->{card_str(tgt)}")
        elif t == 9:
            src = resolve(cur, pseat, 2, o.get("index", 0))
            tgt = resolve(cur, pseat, o.get("inPlayArea", 4), o.get("inPlayIndex", 0))
            out.append(f"EVOLVE:{card_str(src)}->{card_str(tgt)}")
        elif t == 10:
            c = resolve(cur, pseat, o.get("area", 4), o.get("index", 0))
            out.append(f"ABILITY:{card_str(c)}")
        elif t == 12:
            out.append("RETREAT")
        elif t == 13:
            aid = o.get("attackId")
            out.append(f"ATK:{ATTACK_NAMES.get(aid, aid)}")
        elif t == 0:
            out.append(f"NUM:{o.get('number')}")
        elif t == 6:
            out.append("ENERGY?")
        elif t == 3:
            c = resolve(cur, pseat, o.get("area", 2), o.get("index", 0))
            out.append(f"CARD:{card_str(c)}@{AREA.get(o.get('area'))}")
        else:
            out.append(f"T{t}")
    return out


def board_line(cur, seat):
    act = zone_cards(cur, seat, "active")
    bench = zone_cards(cur, seat, "bench")
    prize = zone_cards(cur, seat, "prize")
    a = card_str(act[0]) if act else "NONE"
    b = " ".join(card_str(c) for c in bench) or "-"
    return f"  me: act={a} bench=[{b}] prizes={len(prize)}"


def main():
    ep_path, sub, seat = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    ep = json.load(open(ep_path))
    last_turn = None
    for step_list in ep["steps"]:
        if seat >= len(step_list):
            continue
        s = step_list[seat]
        obs = s.get("observation") or {}
        cur = obs.get("current") or {}
        sel = obs.get("select") or {}
        action = s.get("action") or []
        turn = cur.get("turn", 0)
        if not sel.get("option"):
            continue
        if turn != last_turn:
            print(f"--- TURN {turn} {board_line(cur, seat)}")
            opp = board_line(cur, 1 - seat)
            print(opp.replace("me:", "OP:"))
            last_turn = turn
        ctx = sel.get("context")
        sem = decode(cur, seat, sel, action)
        if sem:
            print(f"  ctx{ctx}: {' + '.join(sem)}")


if __name__ == "__main__":
    main()

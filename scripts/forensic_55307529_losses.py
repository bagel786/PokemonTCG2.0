#!/usr/bin/env python3
"""Forensic loss-bucket analysis for submission 55307529 (master v2, 23 public games, 8 losses).

Pulls per-loss:
  - opponent archetype (signature-card + Jaccard + card names)
  - prize-race progression (turns-to-first-prize, final prizes taken)
  - early bench / setup health
  - loss mechanism classification
"""

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / "vendor").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.search import ArchetypeRegistry

SUB_ID = 55307529
rd = ROOT / "data" / "replays" / str(SUB_ID)

# ---------- card map ----------
def load_card_map() -> dict[int, str]:
    for p in [ROOT / "freshstart" / "data" / "EN_Card_Data.csv", ROOT / "data" / "EN_Card_Data.csv"]:
        if p.exists():
            m = {}
            with open(p, encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    try:
                        cid = int(row["Card ID"])
                        m[cid] = row["Card Name"].strip()
                    except (ValueError, KeyError):
                        pass
            return m
    return {}

CARD = load_card_map()

def cname(cid) -> str:
    return CARD.get(cid, str(cid))

# ---------- archetype signatures ----------
SIG = {
    "grimmsnarl": {646, 647, 648, 649},
    "ogerpon": {96, 18, 1094},
    "lucario": {677, 678, 741, 742, 743},
    "dragapult": {652, 653, 654},
    "mewtwo": {655, 656, 657},
    "alakazam": {140, 305},
    "crustle": {345, 658, 659, 660, 756},
    "bellibolt": {661, 662, 663},
    "dipplin": {664, 665, 666},
    "lopunny": {667, 668, 669},
    "starmie": {670, 671, 672},
    "garchomp": {2, 649, 650, 651, 113, 861},
}

def sig_archetype(opp_ids: set[int]) -> str:
    best, best_c = None, 0
    for name, cards in SIG.items():
        hits = len(opp_ids & cards)
        if hits > best_c:
            best, best_c = name, hits
    return best if best_c >= 1 else "Rogue/Other"

def opp_key_mons(opp_ids: set[int]) -> list[str]:
    mons = []
    for cid in sorted(opp_ids):
        n = cname(cid)
        if "Energy" in n or "Trainer" in n or n.startswith("Card_"):
            continue
        if any(k in n for k in ["Ball", "Poffin", "Pokegear", "Pokegear", "Switch", "Boss", "Professor", "Iono", "Arven", "Rod", "Candy", "Cape", "Nest", "Energy", "Trimmer", "Research", "Determination", "Hilda", "Night", "Earthen", "Buddy", "Hand Trimmer", "Hero's", "Cage", "Lillie"]):
            continue
        mons.append(n)
    return mons[:5]

# ---------- game forensics ----------
def trace_game(data, h_idx):
    steps = data.get("steps", [])
    o_idx = 1 - h_idx
    opp_deck = steps[0][0]["visualize"][0]["action"][o_idx]
    opp_ids = set(opp_deck)

    # turn-by-turn snapshots
    turn_snap = {}
    for s in steps:
        cur = s[0].get("observation", {}).get("current")
        if not cur:
            continue
        pl = cur.get("players")
        if not pl or len(pl) < 2:
            continue
        turn = cur.get("turn")
        p0, p1 = pl[0], pl[1]
        snap = {
            0: (len(p0.get("prize") or []), p0.get("deckCount"), len(p0.get("bench") or []),
                [x.get("id") for x in (p0.get("active") or []) if x]),
            1: (len(p1.get("prize") or []), p1.get("deckCount"), len(p1.get("bench") or []),
                [x.get("id") for x in (p1.get("active") or []) if x]),
        }
        prev = turn_snap.get(turn)
        if prev is None:
            turn_snap[turn] = snap
        else:
            # keep the most-advanced (min prize) snapshot per turn per seat
            merged = {}
            for seat in (0, 1):
                p = snap[seat]
                q = prev[seat]
                merged[seat] = (min(p[0], q[0]), p[1], max(p[2], q[2]), q[3] if q[3] else p[3])
            turn_snap[turn] = merged

    max_turn = max(turn_snap, default=0)
    first_prize_turn = {0: None, 1: None}
    prev_prize = {0: 6, 1: 6}
    final_prizes_taken = {0: 0, 1: 0}
    for t in sorted(turn_snap):
        if t < 1:
            continue
        for seat in (0, 1):
            pr = turn_snap[t][seat][0]
            if pr < prev_prize[seat]:
                if first_prize_turn[seat] is None:
                    first_prize_turn[seat] = t
                prev_prize[seat] = pr
    # final prizes taken: use lowest prize count observed across turns >= 1
    for seat in (0, 1):
        final_prizes_taken[seat] = 6 - min(turn_snap[t][seat][0] for t in turn_snap if t >= 1)

    # early bench: did hero have a bench by end of turn 2 / turn 3?
    hero_bench_by_turn = {}
    for t in (1, 2, 3):
        if t in turn_snap:
            hero_bench_by_turn[t] = turn_snap[t][h_idx][2]

    # opp active line evolution
    opp_active_ids = []
    for t in sorted(turn_snap):
        act = turn_snap[t][o_idx][3]
        if act:
            cid = act[0]
            if not opp_active_ids or opp_active_ids[-1] != cid:
                opp_active_ids.append(cid)

    return {
        "opp_deck": opp_ids,
        "max_turn": max_turn,
        "final_prizes_taken": final_prizes_taken,
        "first_prize_turn": first_prize_turn,
        "hero_bench_by_turn": hero_bench_by_turn,
        "opp_active_line": opp_active_ids,
    }

def main():
    meta = json.loads((rd / "episodes_metadata.json").read_text(encoding="utf-8"))
    games = []
    for m in meta:
        if m["type"] == "EPISODE_TYPE_VALIDATION":
            continue
        rp = rd / f"episode-{m['id']}-replay.json"
        data = json.loads(rp.read_text(encoding="utf-8"))
        games.append({"meta": m, "data": data})

    wins = sum(1 for g in games if g["meta"]["hero_reward"] == 1)
    print("=" * 90)
    print(f"SUBMISSION {SUB_ID}  master v2  |  {len(games)} public games | {wins}W-{len(games)-wins}L "
          f"({wins/len(games)*100:.1f}%)")
    print("=" * 90)

    # signature-based matchup table over all games
    print("\n--- PERFORMANCE BY OPPONENT ARCHETYPE (signature) ---")
    arch_rec = defaultdict(lambda: {"W": 0, "L": 0})
    for g in games:
        h = g["meta"]["hero_seat"]
        tr = trace_game(g["data"], h)
        arch = sig_archetype(tr["opp_deck"])
        arch_rec[arch]["W" if g["meta"]["hero_reward"] == 1 else "L"] += 1
    for k, rec in sorted(arch_rec.items(), key=lambda x: -(x[1]["W"] + x[1]["L"])):
        tot = rec["W"] + rec["L"]
        print(f"  {k:12s}: {rec['W']:2d}W - {rec['L']:2d}L  ({rec['W']/max(1,tot)*100:5.1f}%) [{tot}]")

    print("\n--- PERFORMANCE BY OPPONENT ELO TIER ---")
    tier_rec = defaultdict(lambda: {"W": 0, "L": 0})
    for g in games:
        o = g["meta"]["opp_initialScore"]
        tier = "Elite(850+)" if o >= 850 else "High(750-849)" if o >= 750 else "Mid(650-749)" if o >= 650 else "Low(<650)"
        tier_rec[tier]["W" if g["meta"]["hero_reward"] == 1 else "L"] += 1
    for k, rec in sorted(tier_rec.items()):
        tot = rec["W"] + rec["L"]
        print(f"  {k:13s}: {rec['W']:2d}W - {rec['L']:2d}L  ({rec['W']/max(1,tot)*100:5.1f}%) [{tot}]")

    print("\n--- LOSS FORENSICS ---")
    for g in sorted([x for x in games if x["meta"]["hero_reward"] == -1], key=lambda x: x["meta"]["id"]):
        m = g["meta"]
        h = m["hero_seat"]
        tr = trace_game(g["data"], h)
        o_ids = tr["opp_deck"]
        arch = sig_archetype(o_ids)
        reg = ArchetypeRegistry(ROOT)
        _, _, j = reg.match(o_ids)
        ft = tr["first_prize_turn"]
        fp = tr["final_prizes_taken"]
        bench = tr["hero_bench_by_turn"]
        mons = opp_key_mons(o_ids)
        opp_act = [cname(c) for c in tr["opp_active_line"]]

        print(f"\n  {m['id']}  seat{h}  vs opp{sub_id_str(m['opp_submissionId'])} ({m['opp_initialScore']:6.1f})  turns={tr['max_turn']}")
        print(f"    archetype={arch:10s} jaccard={j:.2f} | opp mons: {', '.join(mons)}")
        print(f"    prizes taken: hero {fp[h]}-{fp[o_idx(m)]}  | first-prize turn hero={ft[h]} opp={ft[1-h]}")
        print(f"    hero bench by T1/T2/T3: {bench.get(1, '-')}/{bench.get(2, '-')}/{bench.get(3, '-')}")
        print(f"    opp active line: {' -> '.join(opp_act[:8])}")

def o_idx(m):
    return 1 - m["hero_seat"]

def sub_id_str(sid):
    return str(sid)

if __name__ == "__main__":
    main()

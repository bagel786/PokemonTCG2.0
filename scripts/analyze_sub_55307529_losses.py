#!/usr/bin/env python3
"""Deep loss-bucket analysis for submission 55307529 (master v2, 24 games, 8 losses)."""

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
meta = json.loads((rd / "episodes_metadata.json").read_text(encoding="utf-8"))
registry = ArchetypeRegistry(ROOT)

games = []
for m in meta:
    if m["type"] == "EPISODE_TYPE_VALIDATION":
        continue
    ep_id = m["id"]
    rp = rd / f"episode-{ep_id}-replay.json"
    data = json.loads(rp.read_text(encoding="utf-8"))
    steps = data.get("steps", [])
    h_idx = m["hero_seat"]
    o_idx = 1 - h_idx
    opp_deck = steps[0][0]["visualize"][0]["action"][o_idx]
    opp_ids = set(opp_deck)
    arch_name, arch_deck, arch_j = registry.match(opp_ids)
    games.append({**m, "steps": len(steps), "steps_data": steps, "opp_deck": opp_deck,
                  "opp_ids": opp_ids, "archetype": arch_name, "arch_j": arch_j})

print("=" * 78)
print(f"SUBMISSION {SUB_ID}  |  {len(games)} public games")
wins = sum(1 for g in games if g["hero_reward"] == 1)
losses = sum(1 for g in games if g["hero_reward"] == -1)
print(f"Record: {wins}W - {losses}L  (WR {wins / len(games) * 100:.1f}%)")
print("=" * 78)

print("\n--- PERFORMANCE BY OPPONENT ARCHETYPE ---")
arch_rec = defaultdict(lambda: {"W": 0, "L": 0})
for g in games:
    k = g["archetype"] or "Rogue/Other"
    arch_rec[k]["W" if g["hero_reward"] == 1 else "L"] += 1
for k, rec in sorted(arch_rec.items(), key=lambda x: -(x[1]["W"] + x[1]["L"])):
    tot = rec["W"] + rec["L"]
    print(f"  {k:16s}: {rec['W']:2d}W - {rec['L']:2d}L  ({rec['W'] / max(1, tot) * 100:5.1f}%) [{tot}]")

print("\n--- PERFORMANCE BY OPPONENT ELO TIER ---")
tier_rec = defaultdict(lambda: {"W": 0, "L": 0})
for g in games:
    o = g["opp_initialScore"]
    tier = "Elite(850+)" if o >= 850 else "High(750-849)" if o >= 750 else "Mid(650-749)" if o >= 650 else "Low(<650)"
    tier_rec[tier]["W" if g["hero_reward"] == 1 else "L"] += 1
for k, rec in sorted(tier_rec.items()):
    tot = rec["W"] + rec["L"]
    print(f"  {k:13s}: {rec['W']:2d}W - {rec['L']:2d}L  ({rec['W'] / max(1, tot) * 100:5.1f}%) [{tot}]")

print("\n--- PERFORMANCE BY SEAT ---")
seat_rec = defaultdict(lambda: {"W": 0, "L": 0})
for g in games:
    seat_rec[g["hero_seat"]]["W" if g["hero_reward"] == 1 else "L"] += 1
for k, rec in sorted(seat_rec.items()):
    tot = rec["W"] + rec["L"]
    print(f"  Seat {k}: {rec['W']:2d}W - {rec['L']:2d}L  ({rec['W'] / max(1, tot) * 100:5.1f}%) [{tot}]")

print("\n--- LOSS DETAILS (opp archetype / elo / steps / seat) ---")
for g in sorted([x for x in games if x["hero_reward"] == -1], key=lambda x: -x["opp_initialScore"]):
    print(f"  {g['id']}  seat{g['hero_seat']}  opp={g['opp_submissionId']}({g['opp_initialScore']:6.1f})  "
          f"arch={g['archetype'] or 'Rogue'}(j={g['arch_j']:.2f})  steps={g['steps']}")

def terminal_state(steps, idx):
    obs = steps[-2][idx].get("observation", {})
    cur = obs.get("current") or {}
    players = cur.get("players") or []
    if len(players) > idx:
        p = players[idx]
        return {
            "prizes": len(p.get("prizes") or []),
            "deck": len(p.get("deck") or []),
            "bench": len(p.get("bench") or []),
            "active": bool(p.get("active")),
        }
    return {}

def knockout_count(steps, idx):
    kos = 0
    for s in steps:
        for a in s:
            for log in a.get("observation", {}).get("logs", []):
                if log.get("type") == 16 and log.get("value", 0) < 0 and log.get("playerIndex") != idx:
                    kos += 1
    return kos

def setup_blunder(steps, idx):
    for s in steps[:16]:
        sel = s[idx].get("observation", {}).get("select")
        if sel and sel.get("context") == 2 and sel.get("maxCount", 0) > 0 and s[idx].get("action") == []:
            return True
    return False

def first_bench_turn(steps, idx):
    for t, s in enumerate(steps[:30]):
        cur = s[idx].get("observation", {}).get("current") or {}
        players = cur.get("players") or []
        if len(players) > idx and len(players[idx].get("bench") or []) > 0:
            return t
    return None

buckets = Counter()

# Signature cards per archetype (core evolution lines / signature attackers)
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

for g in [x for x in games if x["hero_reward"] == -1]:
    h, o = g["hero_seat"], 1 - g["hero_seat"]
    n = g["steps"]
    opp_arch = sig_archetype(g["opp_ids"])
    sb = setup_blunder(g["steps_data"] if "steps_data" in g else [], h)

    # classify
    if n <= 24:
        bucket = "T1-2 Donk / Fast KO"
    elif sb:
        bucket = "Setup Bench Blunder"
    elif opp_arch == "grimmsnarl":
        bucket = "Grimmsnarl Mirror"
    elif opp_arch == "ogerpon":
        bucket = "Ogerpon/Grass Weakness"
    elif opp_arch == "lucario":
        bucket = "Lucario Aggro Race"
    elif opp_arch == "crustle":
        bucket = "Kangaskhan/Crustle Tank"
    elif n >= 150:
        bucket = "Deep Endgame War"
    else:
        bucket = "Midgame Tactical Attrition"
    buckets[bucket] += 1
    g["bucket"] = bucket
    g["sig_arch"] = opp_arch

for b, c in buckets.most_common():
    print(f"  {c:2d} loss(es): {b}")

print("\n--- PER-LOSS MECHANICS ---")
for g in sorted([x for x in games if x["hero_reward"] == -1], key=lambda x: x["id"]):
    h, o = g["hero_seat"], 1 - g["hero_seat"]
    steps = g["steps_data"]
    ts = terminal_state(steps, h)
    hero_kos = knockout_count(steps, h)
    opp_kos = knockout_count(steps, o)
    fbt = first_bench_turn(steps, h)
    print(f"  {g['id']}  [{g['bucket']:26s}] sig={g['sig_arch']:10s} steps={g['steps']:3d} "
          f"hero_KOs={hero_kos} opp_KOs={opp_kos} first_bench_turn={fbt} "
          f"term(prizes={ts['prizes']} deck={ts['deck']} bench={ts['bench']} active={ts['active']})")

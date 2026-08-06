#!/usr/bin/env python3
"""Inspect game details and card moves of recent top-tier losses."""

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KAGGLE_EXE = shutil.which("kaggle") or "kaggle"
OUT_DIR = ROOT / "data" / "replays" / "top_losses"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Common card IDs
CARD_NAMES = {
    646: "Impidimp",
    647: "Morgrem",
    648: "Grimmsnarl",
    860: "Snorunt",
    861: "Froslass",
    112: "Buddy-Buddy Poffin",
    113: "Ultra Ball",
    114: "Rare Candy",
    115: "Night Stretcher",
    116: "Iono",
    117: "Professor's Research",
    118: "Arven",
    119: "Boss's Orders",
    120: "Super Rod",
    305: "Miraidon ex",
    741: "Tadbulb / Bellibolt",
    400: "Lucario / Riolu",
    434: "Mega Lucario ex",
    201: "Alakazam",
    202: "Abra",
    203: "Kadabra",
    204: "Dudunsparce / Dunsparce",
    501: "Kangaskhan",
    502: "Crustle / Dwebble",
    601: "Dragapult ex / Dreepy",
}

episodes = [90265576, 90266298, 90267012, 90266294, 90267005]

for ep_id in episodes:
    cmd = [KAGGLE_EXE, "competitions", "replay", str(ep_id), "-p", str(OUT_DIR)]
    subprocess.run(cmd, capture_output=True)
    p = OUT_DIR / f"episode-{ep_id}-replay.json"
    alt = OUT_DIR / f"{ep_id}.json"
    if alt.exists() and not p.exists():
        alt.rename(p)
    if p.exists():
        d = json.loads(p.read_text())
        steps = d.get("steps", [])
        print(f"\n=======================================================")
        print(f"=== Episode {ep_id}: {len(steps)} steps ===")
        print(f"=======================================================")
        
        # Check initial setup
        for s_idx, s in enumerate(steps[5:35]):
            curr = s[0].get("observation", {}).get("current")
            if curr and "players" in curr:
                p0 = curr["players"][0]
                p1 = curr['players'][1]
                p0_act = [CARD_NAMES.get(c["id"], str(c["id"])) for c in p0.get("active", []) if c]
                p0_bnc = [CARD_NAMES.get(c["id"], str(c["id"])) for c in p0.get("bench", []) if c]
                p1_act = [CARD_NAMES.get(c["id"], str(c["id"])) for c in p1.get("active", []) if c]
                p1_bnc = [CARD_NAMES.get(c["id"], str(c["id"])) for c in p1.get("bench", []) if c]
                print(f"Step {s_idx+5}:")
                print(f"  P0 (Seat 0): Active={p0_act}, Bench={p0_bnc}")
                print(f"  P1 (Seat 1): Active={p1_act}, Bench={p1_bnc}")
                break
        
        # Final rewards
        if steps:
            r0 = steps[-1][0].get("reward")
            r1 = steps[-1][1].get("reward")
            print(f"Final Rewards: P0={r0}, P1={r1}")

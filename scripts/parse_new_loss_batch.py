#!/usr/bin/env python3
"""Download and inspect newest loss batch from both submissions."""

import csv
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KAGGLE_EXE = shutil.which("kaggle") or "kaggle"
OUT_DIR = ROOT / "data" / "replays" / "new_loss_batch"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TARGET_EPISODES = [
    # 5k Baseline losses
    (90276389, 55280578, "5k Control", 55258362, 750.1),
    (90275662, 55280578, "5k Control", 55226777, 836.1),
    (90274209, 55280578, "5k Control", 54898359, 753.0),
    (90273504, 55280578, "5k Control", 55272743, 821.4),
    (90272795, 55280578, "5k Control", 55234823, 804.4),
    (90272074, 55280578, "5k Control", 55276208, 864.2),
    # Distilled losses
    (90276387, 55280582, "Distilled", 55276897, 809.6),
    (90275659, 55280582, "Distilled", 55170551, 769.2),
    (90273505, 55280582, "Distilled", 54800437, 742.0),
    (90270643, 55280582, "Distilled", 53895624, 759.1),
]

card_map = {}
csv_path = ROOT / "freshstart" / "data" / "EN_Card_Data.csv"
if csv_path.exists():
    with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
        reader = csv.reader(f)
        for row in reader:
            if row and row[0].isdigit():
                cid = int(row[0])
                cname = row[1] if len(row) > 1 else f"Card_{cid}"
                card_map[cid] = cname

def get_card_name(cid: int) -> str:
    return card_map.get(cid, f"Card_{cid}")

def download_ep(ep_id: int) -> Path | None:
    p = OUT_DIR / f"{ep_id}.json"
    if p.exists():
        return p
    cmd = [KAGGLE_EXE, "competitions", "replay", str(ep_id), "-p", str(OUT_DIR)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if not p.exists():
        # Check if saved with prefix
        alt = OUT_DIR / f"episode-{ep_id}-replay.json"
        if alt.exists():
            return alt
    return p if p.exists() else None

def main():
    print(f"=== DOWNLOADING AND PARSING {len(TARGET_EPISODES)} RECENT LOSS REPLAYS ===")
    for ep_id, hero_sub, model_name, opp_sub, opp_rating in TARGET_EPISODES:
        path = download_ep(ep_id)
        if not path or not path.exists():
            print(f"Ep {ep_id}: Could not download replay.")
            continue

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Ep {ep_id}: JSON error: {e}")
            continue

        steps = data.get("steps") or []
        if len(steps) < 2 or len(steps[1]) < 2:
            continue

        # Find hero seat
        info = data.get("info") or {}
        # In steps[0], check submission IDs or actions
        # Check action in step 1 (canonical deck)
        seat0_deck = [c for c in steps[1][0].get("action", [])]
        seat1_deck = [c for c in steps[1][1].get("action", [])]
        
        # Grimmsnarl has card 648 (Marnie's Grimmsnarl ex)
        hero_seat = 0 if 648 in seat0_deck else (1 if 648 in seat1_deck else 0)
        opp_seat = 1 - hero_seat

        total_steps = len(steps)
        last_step = steps[-1] if steps else []
        hero_reward = last_step[hero_seat].get("reward", 0) if last_step else 0

        # Collect cards in play
        opp_cards = set(seat1_deck if hero_seat == 0 else seat0_deck)
        opp_names = [get_card_name(cid) for cid in opp_cards]

        opp_arch = "Unknown Meta Deck"
        if any("Ogerpon" in n for n in opp_names):
            opp_arch = "Teal Mask Ogerpon ex (Grass Weakness)"
        elif any("Grimmsnarl" in n or "Marnie" in n for n in opp_names):
            opp_arch = "Grimmsnarl Mirror Match"
        elif any("Kangaskhan" in n for n in opp_names):
            opp_arch = "Mega Kangaskhan ex Tank"
        elif any("Lucario" in n or "Riolu" in n for n in opp_names or "Makuhita" in n or "Solrock" in n):
            opp_arch = "Lucario / Solrock / Makuhita Aggro"
        elif any("Bellibolt" in n or "Tadbulb" in n or "Wattrel" in n for n in opp_names):
            opp_arch = "Iono / Bellibolt ex Stall"
        elif any("Alakazam" in n or "Abra" in n for n in opp_names):
            opp_arch = "Alakazam / Dudunsparce"
        elif any("Charizard" in n for n in opp_names):
            opp_arch = "Charizard ex"
        elif any("Dragapult" in n or "Dreepy" in n for n in opp_names):
            opp_arch = "Dragapult ex"

        # Check hero opening setup
        hero_start_active = []
        hero_start_bench = []
        opp_start_active = []
        opp_start_bench = []
        for s_idx in range(5, min(15, total_steps)):
            curr = steps[s_idx][0].get("observation", {}).get("current")
            if curr and "players" in curr and len(curr["players"]) > 1:
                hp = curr["players"][hero_seat]
                op = curr["players"][opp_seat]
                h_act = hp.get("active") or []
                h_bnc = hp.get("bench") or []
                if h_act and not hero_start_active:
                    hero_start_active = [get_card_name(c["id"]) for c in h_act if c and "id" in c]
                    hero_start_bench = [get_card_name(c["id"]) for c in h_bnc if c and "id" in c]
                    opp_start_active = [get_card_name(c["id"]) for c in (op.get("active") or []) if c and "id" in c]
                    opp_start_bench = [get_card_name(c["id"]) for c in (op.get("bench") or []) if c and "id" in c]
                    break

        print(f"\n------------------------------------------------------------------")
        print(f"[Episode {ep_id}] Model: {model_name} (#{hero_sub}) | Opponent #{opp_sub} (Rating: {opp_rating:.1f})")
        print(f"  * Matchup Archetype   : {opp_arch}")
        print(f"  * Turn Order / Seat   : {'Seat 0 (Going 1st)' if hero_seat == 0 else 'Seat 1 (Going 2nd)'} | Game Length: {total_steps} steps")
        print(f"  * Hero Opening State  : Active={hero_start_active} | Bench={hero_start_bench}")
        print(f"  * Opponent Opening    : Active={opp_start_active} | Bench={opp_start_bench}")
        print(f"  * Key Cards in Opponent Deck: {list(opp_names)[:8]}")

if __name__ == "__main__":
    main()

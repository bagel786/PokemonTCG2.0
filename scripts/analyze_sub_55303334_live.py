#!/usr/bin/env python3
"""Fetch and analyze submission 55303334 games with exact turn-by-turn breakdown."""

import json
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUB_ID = 55303334
KAGGLE_EXE = sys.executable.replace("python.exe", "kaggle.exe")

EPISODE_SERVICE = "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes"

def fetch_episodes(sub_id: int):
    payload = json.dumps({"submissionId": sub_id}).encode()
    req = urllib.request.Request(
        EPISODE_SERVICE,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "PTCG-Live/1.0"}
    )
    ctx = ssl._create_unverified_context()
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        return json.loads(resp.read().decode()).get("episodes", [])

def download_replay(ep_id: int, out_dir: Path) -> Path | None:
    rp_path = out_dir / f"episode-{ep_id}-replay.json"
    alt_path = out_dir / f"{ep_id}.json"
    if rp_path.exists() and rp_path.stat().st_size > 0:
        return rp_path
    if alt_path.exists() and alt_path.stat().st_size > 0:
        return alt_path
    
    cmd = [KAGGLE_EXE, "competitions", "replay", str(ep_id), "-p", str(out_dir)]
    for attempt in range(3):
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if alt_path.exists() and alt_path.stat().st_size > 0:
            alt_path.rename(rp_path)
            return rp_path
        if rp_path.exists() and rp_path.stat().st_size > 0:
            return rp_path
        time.sleep(1.0)
    return None

print(f"Fetching matches for submission {SUB_ID}...")
episodes = fetch_episodes(SUB_ID)
print(f"Total matches found: {len(episodes)}")

replays_dir = ROOT / "data" / "replays" / str(SUB_ID)
replays_dir.mkdir(parents=True, exist_ok=True)

for ep in episodes:
    ep_id = ep["id"]
    ag = ep.get("agents", [])
    if len(ag) < 2:
        continue
    h_idx = 0 if ag[0].get("submissionId") == SUB_ID else 1
    h, o = ag[h_idx], ag[1 - h_idx]
    rew = h.get("reward")
    res = "WIN" if rew == 1 else ("LOSS" if rew == -1 else "TIE")
    h_init = h.get("initialScore", 0) or 0
    h_upd = h.get("updatedScore", 0) or 0
    o_init = o.get("initialScore", 0) or 0
    o_sub = o.get("submissionId")
    print(f"\n=======================================================")
    print(f"Episode {ep_id}: {res} | Rating: {h_init:.1f} -> {h_upd:.1f} (delta: {h_upd - h_init:+.1f}) vs Sub {o_sub} (Elo {o_init:.1f})")
    print(f"=======================================================")
    
    rp_file = download_replay(ep_id, replays_dir)
    if rp_file and rp_file.exists():
        rp_data = json.loads(rp_file.read_text(encoding="utf-8"))
        steps = rp_data.get("steps", [])
        print(f"  Total Replay Steps: {len(steps)}")
        
        if len(steps) >= 2:
            p0_deck = steps[1][0].get("action", [])
            hero_idx = 0 if p0_deck[:5] == [7, 7, 7, 7, 7] else 1
            opp_deck = steps[1][1 - hero_idx].get("action", [])
            print(f"  Hero index: {hero_idx}")
            print(f"  Opponent deck length: {len(opp_deck)} cards")
            
            # Print turn by turn logs & actions
            for s_idx, s in enumerate(steps):
                hero_step = s[hero_idx]
                opp_step = s[1 - hero_idx]
                act = hero_step.get("action")
                obs = hero_step.get("observation", {})
                sel = obs.get("select")
                logs = obs.get("logs", [])
                
                # Check setup benching
                if sel and sel.get("context") == 2:
                    print(f"  [STEP {s_idx:3d}] SETUP BENCH -> Hand Basics: {len(sel.get('option', []))} | Action Taken: {act}")
                    
                if sel and sel.get("context") != 2 and act != [] and act is not None:
                    # Print significant actions
                    print(f"  [STEP {s_idx:3d}] Context {sel.get('context')} | Options: {len(sel.get('option', []))} | Action: {act}")
                
                # Print game over / prize states
                if s_idx == len(steps) - 1:
                    cur = obs.get("current", {})
                    players = cur.get("players", [])
                    if len(players) >= 2:
                        h_p = players[cur.get("yourIndex", 0)]
                        o_p = players[1 - cur.get("yourIndex", 0)]
                        print(f"\n  FINAL BOARD STATE:")
                        print(f"    Hero Prizes Left: {len(h_p.get('prizes', []))} | Active: {h_p.get('active')} | Bench: {len(h_p.get('bench', []))}")
                        print(f"    Opp Prizes Left:  {len(o_p.get('prizes', []))} | Active: {o_p.get('active')} | Bench: {len(o_p.get('bench', []))}")
                        print(f"    Hero Discard: {len(h_p.get('discard', []))} | Opp Discard: {len(o_p.get('discard', []))}")

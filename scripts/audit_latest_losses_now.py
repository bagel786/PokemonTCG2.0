#!/usr/bin/env python3
"""Audit the latest fresh losses for both active submissions."""

import base64
import csv
import json
import os
import shutil
import ssl
import subprocess
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EPISODE_SERVICE = "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes"
KAGGLE_EXE = shutil.which("kaggle") or "kaggle"
OUT_DIR = ROOT / "data" / "replays" / "latest_losses_audit"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SUB_5K = 55280578
SUB_DISTILLED = 55280582

def auth_header() -> str:
    kaggle_json = Path.home() / ".kaggle" / "kaggle.json"
    if not kaggle_json.exists():
        return ""
    blob = json.loads(kaggle_json.read_text())
    if "access_token" in blob:
        return "Bearer " + blob["access_token"]
    pair = f"{blob['username']}:{blob['key']}".encode()
    return "Basic " + base64.b64encode(pair).decode()

def fetch_episode_metadata(sub_id: int) -> list[dict]:
    payload = json.dumps({"submissionId": sub_id}).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "PTCG-Live/1.0", "Authorization": auth_header()}
    req = urllib.request.Request(EPISODE_SERVICE, data=payload, headers=headers)
    ctx = ssl._create_unverified_context()
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    return data.get("episodes", [])

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

def download_replay(ep_id: int) -> Path | None:
    p = OUT_DIR / f"episode-{ep_id}-replay.json"
    alt = OUT_DIR / f"{ep_id}.json"
    if p.exists():
        return p
    if alt.exists():
        return alt
    cmd = [KAGGLE_EXE, "competitions", "replay", str(ep_id), "-p", str(OUT_DIR)]
    subprocess.run(cmd, capture_output=True)
    if alt.exists() and not p.exists():
        alt.rename(p)
    return p if p.exists() else None

def audit_submission(sub_id: int, sub_name: str):
    print(f"\n{'='*75}")
    print(f"  AUDITING LATEST MATCHES FOR SUBMISSION #{sub_id} ({sub_name})")
    print(f"{'='*75}")

    eps = fetch_episode_metadata(sub_id)
    print(f"Total episodes played so far: {len(eps)}")

    # List recent 8 episodes
    recent_eps = eps[:10]
    print(f"\nRecent Match Sequence (Newest First):")
    for idx, ep in enumerate(recent_eps):
        ep_id = ep.get("id")
        agents = ep.get("agents", [])
        if len(agents) < 2:
            continue
        hero_idx = 0 if agents[0].get("submissionId") == sub_id else 1
        opp_idx = 1 - hero_idx
        h_agent = agents[hero_idx]
        o_agent = agents[opp_idx]

        h_reward = h_agent.get("reward")
        h_score_before = h_agent.get("initialScore")
        h_score_after = h_agent.get("updatedScore")
        o_score_before = o_agent.get("initialScore")
        o_score_after = o_agent.get("updatedScore")
        o_sub = o_agent.get("submissionId")

        status = "WIN" if h_reward == 1 else ("LOSS" if h_reward in (-1, 0) else "UNKNOWN")
        delta = (h_score_after - h_score_before) if (h_score_after and h_score_before) else 0.0
        print(f"  Game #{len(eps)-idx:2d} [Ep {ep_id}] | {status:4s} ({delta:+5.1f}) | Score: {h_score_after:.1f} | Opponent #{o_sub} (Rating: {o_score_before:.1f})")

    # Detailed dive into the newest losses
    print(f"\n--- Detailed Forensic Breakdown of Newest Losses ---")
    for ep in recent_eps:
        agents = ep.get("agents", [])
        if len(agents) < 2:
            continue
        hero_idx = 0 if agents[0].get("submissionId") == sub_id else 1
        opp_idx = 1 - hero_idx
        h_agent = agents[hero_idx]
        o_agent = agents[opp_idx]
        if h_agent.get("reward") not in (-1, 0):
            continue

        ep_id = ep.get("id")
        replay_path = download_replay(ep_id)
        if not replay_path:
            continue

        try:
            r_data = json.loads(replay_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        steps = r_data.get("steps", [])
        total_steps = len(steps)

        opp_cards = set()
        hero_start_active = []
        hero_start_bench = []
        opp_start_active = []
        opp_start_bench = []
        
        # Track energy attachments and key trainer cards played by hero
        hero_trainers_played = []
        hero_prize_count = 6
        opp_prize_count = 6

        for s_idx, s in enumerate(steps):
            if len(s) < 2:
                continue
            curr = s[0].get("observation", {}).get("current")
            if not curr or "players" not in curr or len(curr["players"]) < 2:
                continue
            
            hp = curr["players"][hero_idx]
            op = curr["players"][opp_idx]

            h_act = hp.get("active") or []
            h_bnc = hp.get("bench") or []
            o_act = op.get("active") or []
            o_bnc = op.get("bench") or []

            if s_idx in (5, 6, 7, 8, 9, 10) and not hero_start_active and h_act:
                hero_start_active = [get_card_name(c["id"]) for c in h_act if c and "id" in c]
                hero_start_bench = [get_card_name(c["id"]) for c in h_bnc if c and "id" in c]
                opp_start_active = [get_card_name(c["id"]) for c in o_act if c and "id" in c]
                opp_start_bench = [get_card_name(c["id"]) for c in o_bnc if c and "id" in c]

            for c in o_act + o_bnc + (op.get("hand") or []):
                if c and "id" in c:
                    opp_cards.add(c["id"])

        opp_names = [get_card_name(cid) for cid in opp_cards]
        opp_arch = "Unknown"
        if any("Ogerpon" in n for n in opp_names):
            opp_arch = "Teal Mask Ogerpon ex (Grass Weakness)"
        elif any("Grimmsnarl" in n or "Marnie" in n for n in opp_names):
            opp_arch = "Grimmsnarl Mirror Match"
        elif any("Kangaskhan" in n for n in opp_names):
            opp_arch = "Mega Kangaskhan ex Tank"
        elif any("Lucario" in n or "Riolu" in n for n in opp_names):
            opp_arch = "Lucario Aggro"
        elif any("Bellibolt" in n or "Tadbulb" in n or "Wattrel" in n for n in opp_names):
            opp_arch = "Iono / Bellibolt ex"
        elif any("Alakazam" in n or "Abra" in n for n in opp_names):
            opp_arch = "Alakazam / Dudunsparce"
        elif any("Dragapult" in n or "Dreepy" in n for n in opp_names):
            opp_arch = "Dragapult ex"

        print(f"\n[Episode {ep_id}]")
        print(f"  - Opponent #{o_agent.get('submissionId')} | Rating: {o_agent.get('initialScore', 0):.1f} | Archetype: {opp_arch}")
        print(f"  - Hero Seat: {'Seat 0 (Going 1st)' if hero_idx == 0 else 'Seat 1 (Going 2nd)'} | Game Length: {total_steps} steps")
        print(f"  - Hero Opening: Active={hero_start_active} | Bench={hero_start_bench}")
        print(f"  - Opponent Opening: Active={opp_start_active} | Bench={opp_start_bench}")

def main():
    audit_submission(SUB_5K, "5k Control Baseline")
    audit_submission(SUB_DISTILLED, "Distilled Model")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

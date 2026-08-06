#!/usr/bin/env python3
"""Comprehensive forensic audit of recent loss streaks on Kaggle ladder."""

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
OUT_DIR = ROOT / "data" / "replays" / "loss_streak_audit"
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
    print(f"\n{'='*70}")
    print(f"  AUDITING SUBMISSION #{sub_id}: {sub_name}")
    print(f"{'='*70}")

    eps = fetch_episode_metadata(sub_id)
    print(f"Total episodes fetched: {len(eps)}")

    losses = []
    for idx, ep in enumerate(eps):
        ep_id = ep.get("id")
        agents = ep.get("agents", [])
        if len(agents) < 2:
            continue
        
        hero_idx = 0 if agents[0].get("submissionId") == sub_id else 1
        opp_idx = 1 - hero_idx

        hero_agent = agents[hero_idx]
        opp_agent = agents[opp_idx]

        hero_reward = hero_agent.get("reward")
        hero_score_after = hero_agent.get("updatedScore")
        opp_score_before = opp_agent.get("initialScore")
        opp_sub = opp_agent.get("submissionId")

        status = "WIN" if hero_reward == 1 else ("LOSS" if hero_reward in (-1, 0) else "UNKNOWN")
        if hero_reward is None:
            if hero_score_after and hero_agent.get("initialScore"):
                status = "WIN" if hero_score_after > hero_agent.get("initialScore") else "LOSS"

        if status == "LOSS":
            losses.append({
                "ep_id": ep_id,
                "seat": hero_idx,
                "opp_score_before": opp_score_before,
                "opp_sub": opp_sub,
                "agents": agents,
            })

    print(f"Total Losses Found: {len(losses)}")
    print(f"\n--- Detailed Analysis of Losses (Chronological) ---")

    loss_reasons = defaultdict(int)
    opp_archetypes = defaultdict(int)

    for loss in reversed(losses):
        ep_id = loss["ep_id"]
        seat = loss["seat"]
        opp_rating = loss["opp_score_before"]
        
        replay_path = download_replay(ep_id)
        if not replay_path:
            print(f"Episode {ep_id}: Failed to download replay.")
            continue

        try:
            r_data = json.loads(replay_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Episode {ep_id}: Error reading JSON: {e}")
            continue

        steps = r_data.get("steps", [])
        total_steps = len(steps)

        opp_cards_seen = set()
        hero_cards_seen = set()
        hero_start_active = []
        hero_start_bench = []
        opp_start_active = []
        opp_start_bench = []

        for s_idx, s in enumerate(steps):
            if len(s) < 2:
                continue
            curr = s[0].get("observation", {}).get("current")
            if not curr or "players" not in curr or len(curr["players"]) < 2:
                continue
            
            hero_p = curr["players"][seat]
            opp_p = curr["players"][1 - seat]

            h_act = hero_p.get("active") or []
            h_bnc = hero_p.get("bench") or []
            o_act = opp_p.get("active") or []
            o_bnc = opp_p.get("bench") or []
            h_hnd = hero_p.get("hand") or []
            o_hnd = opp_p.get("hand") or []

            if s_idx in (5, 6, 7, 8, 9, 10) and not hero_start_active and h_act:
                hero_start_active = [get_card_name(c["id"]) for c in h_act if c and "id" in c]
                hero_start_bench = [get_card_name(c["id"]) for c in h_bnc if c and "id" in c]
                opp_start_active = [get_card_name(c["id"]) for c in o_act if c and "id" in c]
                opp_start_bench = [get_card_name(c["id"]) for c in o_bnc if c and "id" in c]

            for c in h_act + h_bnc + h_hnd:
                if c and "id" in c:
                    hero_cards_seen.add(c["id"])
            for c in o_act + o_bnc + o_hnd:
                if c and "id" in c:
                    opp_cards_seen.add(c["id"])

        opp_names = [get_card_name(cid) for cid in opp_cards_seen]
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

        opp_archetypes[opp_arch] += 1

        loss_type = "Standard KO / Prize Trade Defeat"
        if total_steps <= 50:
            loss_type = "Turn-1/2 Donk / Lone-Basic Extinction"
        elif total_steps >= 220:
            loss_type = "Deckout / Stall Defeat"

        loss_reasons[loss_type] += 1

        print(f"\n[Episode {ep_id}]")
        print(f"  - Opponent: {loss.get('opp_sub')} | Rating: {opp_rating:.1f} | Archetype: {opp_arch}")
        print(f"  - Hero Seat: {'Going 1st (Seat 0)' if seat == 0 else 'Going 2nd (Seat 1)'} | Steps: {total_steps}")
        print(f"  - Loss Classification: {loss_type}")
        print(f"  - Hero Opening Active: {hero_start_active} | Bench: {hero_start_bench}")
        print(f"  - Opponent Opening Active: {opp_start_active} | Bench: {opp_start_bench}")

    print(f"\n{'='*70}")
    print(f"SUMMARY FOR #{sub_id} ({sub_name})")
    print(f"{'='*70}")
    print("Opponent Archetype Breakdown:")
    for arch, count in sorted(opp_archetypes.items(), key=lambda x: -x[1]):
        print(f"  * {arch:55s}: {count} losses")
    print("\nLoss Mode Breakdown:")
    for reason, count in sorted(loss_reasons.items(), key=lambda x: -x[1]):
        print(f"  * {reason:55s}: {count} losses")

def main():
    audit_submission(SUB_5K, "5k Control Baseline (grimmsnarl_5k_reference)")
    audit_submission(SUB_DISTILLED, "New Distilled Agent (submission.tar.gz)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

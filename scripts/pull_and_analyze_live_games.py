#!/usr/bin/env python3
"""Fetch all live matches from Kaggle for active submissions and perform in-depth loss analysis."""

import base64
import concurrent.futures
import json
import os
import shutil
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EPISODE_SERVICE = "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes"
KAGGLE_EXE = shutil.which("kaggle") or "kaggle"

SUB_NEW = 55278944
SUB_5K = 55278940

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
    headers = {"Content-Type": "application/json", "User-Agent": "PTCG-Live/1.0"}
    auth = auth_header()
    if auth:
        headers["Authorization"] = auth
    req = urllib.request.Request(EPISODE_SERVICE, data=payload, headers=headers)
    ctx = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        return data.get("episodes", [])
    except Exception as e:
        print(f"Error fetching metadata for sub {sub_id}: {e}")
        return []

def download_replay(ep_id: int, out_dir: Path) -> Path | None:
    rp_path = out_dir / f"episode-{ep_id}-replay.json"
    alt_path = out_dir / f"{ep_id}.json"
    if rp_path.exists() and rp_path.stat().st_size > 0:
        return rp_path
    if alt_path.exists() and alt_path.stat().st_size > 0:
        return alt_path
    
    cmd = [KAGGLE_EXE, "competitions", "replay", str(ep_id), "-p", str(out_dir)]
    for attempt in range(3):
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if alt_path.exists() and alt_path.stat().st_size > 0:
            alt_path.rename(rp_path)
            return rp_path
        if rp_path.exists() and rp_path.stat().st_size > 0:
            return rp_path
        time.sleep(1.0)
    return None

def analyze_match(ep_meta: dict, replay_file: Path | None, sub_id: int) -> dict:
    ep_id = ep_meta.get("id")
    agents = ep_meta.get("agents", [])
    hero_index = None
    opp_index = None
    hero_reward = None
    opp_reward = None
    hero_rating = None
    opp_rating = None
    opp_name = "Unknown Opponent"
    
    for idx, ag in enumerate(agents):
        if ag.get("submissionId") == sub_id:
            hero_index = idx
            hero_reward = ag.get("reward")
            hero_rating = ag.get("updatedScore")
        else:
            opp_index = idx
            opp_reward = ag.get("reward")
            opp_rating = ag.get("updatedScore")
            sub_info = ag.get("submission", {})
            opp_name = sub_info.get("teamName") or sub_info.get("name") or "Opponent"

    outcome = "UNKNOWN"
    if hero_reward is not None and opp_reward is not None:
        if hero_reward > opp_reward:
            outcome = "WIN"
        elif hero_reward < opp_reward:
            outcome = "LOSS"
        else:
            outcome = "TIE"

    analysis = {
        "episode_id": ep_id,
        "sub_id": sub_id,
        "hero_index": hero_index,
        "outcome": outcome,
        "hero_reward": hero_reward,
        "opp_reward": opp_reward,
        "opp_name": opp_name,
        "opp_rating": opp_rating,
        "hero_rating": hero_rating,
        "game_length_steps": 0,
        "loss_reason": None,
    }

    if not replay_file or not replay_file.exists():
        return analysis

    try:
        replay_data = json.loads(replay_file.read_text())
        steps = replay_data.get("steps", [])
        analysis["game_length_steps"] = len(steps)
        
        if steps:
            last_step = steps[-1]
            for idx, ag_step in enumerate(last_step):
                status = ag_step.get("status")
                if status != "DONE" and status != "ACTIVE":
                    if idx == hero_index:
                        analysis["loss_reason"] = f"HERO_ERROR_{status}"
                    else:
                        analysis["loss_reason"] = f"OPP_ERROR_{status}"
        
        if outcome == "LOSS" and not analysis["loss_reason"]:
            if len(steps) <= 15:
                analysis["loss_reason"] = "EARLY_OPENING_BRICK_OR_DONK"
            elif len(steps) <= 35:
                analysis["loss_reason"] = "MIDGAME_TEMPO_DEFICIT"
            else:
                analysis["loss_reason"] = "LATEGAME_PRIZE_TRADE"
                
    except Exception as e:
        analysis["detail_error"] = str(e)

    return analysis

def process_sub(sub_id: int, label: str):
    print(f"\n=======================================================")
    print(f"Fetching live matches for {label} (Sub #{sub_id})...")
    print(f"=======================================================")
    out_dir = ROOT / "data" / "replays" / str(sub_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    episodes = fetch_episode_metadata(sub_id)
    print(f"Total live episodes found on Kaggle: {len(episodes)}")
    if not episodes:
        return

    # Download replays in parallel
    print(f"Downloading replay logs...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(download_replay, ep["id"], out_dir): ep for ep in episodes if "id" in ep}
        for f in concurrent.futures.as_completed(futures):
            pass

    results = []
    wins = 0
    losses = 0
    ties = 0
    seat_0_wins = 0
    seat_0_total = 0
    seat_1_wins = 0
    seat_1_total = 0

    for ep in episodes:
        ep_id = ep.get("id")
        rp_file = out_dir / f"episode-{ep_id}-replay.json"
        if not rp_file.exists():
            rp_file = out_dir / f"{ep_id}.json"
        an = analyze_match(ep, rp_file if rp_file.exists() else None, sub_id)
        results.append(an)
        if an["outcome"] == "WIN":
            wins += 1
            if an["hero_index"] == 0:
                seat_0_wins += 1
            elif an["hero_index"] == 1:
                seat_1_wins += 1
        elif an["outcome"] == "LOSS":
            losses += 1
        else:
            ties += 1

        if an["hero_index"] == 0:
            seat_0_total += 1
        elif an["hero_index"] == 1:
            seat_1_total += 1

    total = wins + losses + ties
    win_pct = (wins / total * 100) if total > 0 else 0
    s0_pct = (seat_0_wins / seat_0_total * 100) if seat_0_total > 0 else 0
    s1_pct = (seat_1_wins / seat_1_total * 100) if seat_1_total > 0 else 0

    print(f"\n--- Match Record for {label} ---")
    print(f"Total Games Played: {total} | Wins: {wins} | Losses: {losses} | Ties: {ties}")
    print(f"Overall Win Rate: {win_pct:.1f}%")
    print(f"Seat 0 (Going 1st): {seat_0_wins}/{seat_0_total} ({s0_pct:.1f}%)")
    print(f"Seat 1 (Going 2nd): {seat_1_wins}/{seat_1_total} ({s1_pct:.1f}%)")

    loss_list = [r for r in results if r["outcome"] == "LOSS"]
    print(f"\n--- In-Depth Loss Breakdown ({len(loss_list)} losses) ---")
    for idx, l in enumerate(loss_list, 1):
        print(f"Loss #{idx}: Episode {l['episode_id']} | Seat: {l['hero_index']} | Opponent: {l['opp_name']} (Rating: {l['opp_rating']}) | Steps: {l['game_length_steps']} | Cause: {l['loss_reason']}")

    (out_dir / "live_analysis_report.json").write_text(json.dumps(results, indent=2))

def main():
    process_sub(SUB_NEW, "New Distilled Agent (submission.tar.gz)")
    process_sub(SUB_5K, "5k Control Baseline (grimmsnarl_5k_reference)")

if __name__ == "__main__":
    main()

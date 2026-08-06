#!/usr/bin/env python3
"""Detailed live match analytics and loss inspector for active Kaggle submissions."""

import base64
import json
import os
import shutil
import ssl
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EPISODE_SERVICE = "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes"
KAGGLE_EXE = shutil.which("kaggle") or "kaggle"

SUB_NEW = 55280582
SUB_5K = 55280578

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

def analyze_submission(sub_id: int, label: str):
    eps = fetch_episode_metadata(sub_id)
    out_dir = ROOT / "data" / "replays" / str(sub_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"\n=======================================================")
    print(f"  LIVE LADDER ANALYTICS: {label} (#{sub_id})")
    print(f"=======================================================")
    print(f"Total Matches Played So Far: {len(eps)}")
    
    wins = 0
    losses = 0
    ties = 0
    s0_wins, s0_total = 0, 0
    s1_wins, s1_total = 0, 0
    match_records = []

    for ep in eps:
        ep_id = ep.get("id")
        agents = ep.get("agents", [])
        create_time = ep.get("createTime", "")
        hero_idx = None
        hero_reward = None
        opp_reward = None
        hero_score_before = None
        hero_score_after = None
        opp_score_before = None
        opp_score_after = None
        opp_team_id = None
        opp_sub_id = None

        for idx, ag in enumerate(agents):
            if ag.get("submissionId") == sub_id:
                hero_idx = idx
                hero_reward = ag.get("reward")
                hero_score_before = ag.get("initialScore")
                hero_score_after = ag.get("updatedScore")
            else:
                opp_reward = ag.get("reward")
                opp_score_before = ag.get("initialScore")
                opp_score_after = ag.get("updatedScore")
                opp_team_id = ag.get("teamId")
                opp_sub_id = ag.get("submissionId")

        if hero_reward is None or opp_reward is None:
            continue

        if hero_reward > opp_reward:
            outcome = "WIN"
            wins += 1
            if hero_idx == 0: s0_wins += 1
            elif hero_idx == 1: s1_wins += 1
        elif hero_reward < opp_reward:
            outcome = "LOSS"
            losses += 1
        else:
            outcome = "TIE"
            ties += 1

        if hero_idx == 0: s0_total += 1
        elif hero_idx == 1: s1_total += 1

        delta_score = (hero_score_after - hero_score_before) if (hero_score_after is not None and hero_score_before is not None) else 0.0

        rec = {
            "episode_id": ep_id,
            "time": create_time,
            "seat": hero_idx,
            "outcome": outcome,
            "delta_score": delta_score,
            "hero_score_after": hero_score_after,
            "opp_sub_id": opp_sub_id,
            "opp_score_before": opp_score_before,
            "opp_team_id": opp_team_id,
        }
        match_records.append(rec)

    total = wins + losses + ties
    win_rate = (wins / total * 100) if total > 0 else 0
    s0_rate = (s0_wins / s0_total * 100) if s0_total > 0 else 0
    s1_rate = (s1_wins / s1_total * 100) if s1_total > 0 else 0
    
    current_score = match_records[0]["hero_score_after"] if match_records else 0

    print(f"\n[+] Current Rating: {current_score:.1f}")
    print(f"[+] Overall Record: {wins} Wins - {losses} Losses - {ties} Ties ({win_rate:.1f}% Win Rate)")
    print(f"    - Going First  (Seat 0): {s0_wins}/{s0_total} ({s0_rate:.1f}%)")
    print(f"    - Going Second (Seat 1): {s1_wins}/{s1_total} ({s1_rate:.1f}%)")

    # Chronological match log (oldest to newest)
    print("\n[+] Chronological Match Trajectory:")
    for idx, r in enumerate(reversed(match_records), 1):
        seat_str = "1st (Seat 0)" if r["seat"] == 0 else "2nd (Seat 1)"
        print(f"  Game {idx:2d} [Ep {r['episode_id']}]: {r['outcome']:4s} | Seat: {seat_str:12s} | Opp Rating: {r['opp_score_before'] or 0:5.1f} | Delta: {r['delta_score']:+6.1f} -> Rating: {r['hero_score_after'] or 0:5.1f}")

    loss_records = [r for r in match_records if r["outcome"] == "LOSS"]
    print(f"\n[-] In-Depth Loss Audit ({len(loss_records)} total losses):")
    if not loss_records:
        print("  Zero losses found!")
    else:
        for idx, l in enumerate(loss_records, 1):
            seat_str = "Going 1st" if l["seat"] == 0 else "Going 2nd"
            print(f"  Loss #{idx}: Episode {l['episode_id']} | Seat: {seat_str} | Opponent Rating: {l['opp_score_before']:.1f} | ELO Impact: {l['delta_score']:.1f}")

    return match_records

def main():
    analyze_submission(SUB_NEW, "New Distilled Agent (submission.tar.gz)")
    analyze_submission(SUB_5K, "5k Control Baseline (grimmsnarl_5k_reference)")

if __name__ == "__main__":
    main()

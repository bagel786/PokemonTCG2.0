#!/usr/bin/env python3
"""Scan all historical submissions to detect any rare/unaddressed loss buckets."""

import base64
import json
import ssl
import sys
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EPISODE_SERVICE = "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes"

KNOWN_SUBMISSIONS = [
    (55280578, "5k Control Baseline (Current)"),
    (55280582, "Distilled Agent (Current)"),
    (55222011, "Gen5 Model (Peak 1004)"),
    (55189658, "Candidate 1 (Gen4)"),
    (55189662, "Candidate 2 (Gen4 Distilled)"),
    (55180261, "5k Reference (Early Aug)"),
    (55180215, "Gen4 Sparred"),
    (55171235, "5k Reference (July 30)"),
    (55171237, "Co-Evolution R2"),
]

def auth_header() -> str:
    kaggle_json = Path.home() / ".kaggle" / "kaggle.json"
    if not kaggle_json.exists():
        return ""
    blob = json.loads(kaggle_json.read_text())
    if "access_token" in blob:
        return "Bearer " + blob["access_token"]
    pair = f"{blob['username']}:{blob['key']}".encode()
    return "Basic " + base64.b64encode(pair).decode()

def fetch_episodes(sub_id: int) -> list[dict]:
    payload = json.dumps({"submissionId": sub_id}).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "PTCG-Live/1.0", "Authorization": auth_header()}
    req = urllib.request.Request(EPISODE_SERVICE, data=payload, headers=headers)
    ctx = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        return data.get("episodes", [])
    except Exception as e:
        print(f"Error fetching sub #{sub_id}: {e}")
        return []

def main():
    print("=== SCANNING ALL HISTORICAL SUBMISSION LOSSES ===")
    total_losses = 0
    total_wins = 0
    total_games = 0

    seat_losses = Counter()
    opp_rating_brackets = Counter()
    sub_records = {}

    for sub_id, label in KNOWN_SUBMISSIONS:
        eps = fetch_episodes(sub_id)
        if not eps:
            continue
        sub_wins = 0
        sub_losses = 0
        for ep in eps:
            agents = ep.get("agents", [])
            if len(agents) < 2:
                continue
            hero_idx = 0 if agents[0].get("submissionId") == sub_id else 1
            opp_idx = 1 - hero_idx
            h_agent = agents[hero_idx]
            o_agent = agents[opp_idx]

            reward = h_agent.get("reward")
            opp_score = o_agent.get("initialScore") or 0.0

            total_games += 1
            if reward == 1:
                sub_wins += 1
                total_wins += 1
            elif reward in (-1, 0):
                sub_losses += 1
                total_losses += 1
                seat_losses[f"Seat {hero_idx}"] += 1
                if opp_score >= 900:
                    opp_rating_brackets["Elite (>900)"] += 1
                elif opp_score >= 800:
                    opp_rating_brackets["High Tier (800-900)"] += 1
                elif opp_score >= 700:
                    opp_rating_brackets["Mid Tier (700-800)"] += 1
                else:
                    opp_rating_brackets["Low Tier (<700)"] += 1

        sub_records[label] = {"games": len(eps), "wins": sub_wins, "losses": sub_losses}

    print(f"\nTotal Games Analyzed Across {len(KNOWN_SUBMISSIONS)} Submissions: {total_games}")
    print(f"Total Wins: {total_wins} | Total Losses: {total_losses} (Overall Win Rate: {total_wins/max(1, total_games)*100:.1f}%)")
    print(f"\nLoss Distribution by Seat:")
    for seat, count in seat_losses.items():
        print(f"  - {seat}: {count} losses ({count/max(1, total_losses)*100:.1f}%)")

    print(f"\nLoss Distribution by Opponent Rating Tier:")
    for bracket, count in opp_rating_brackets.items():
        print(f"  - {bracket:<22}: {count:3d} losses ({count/max(1, total_losses)*100:.1f}%)")

    print(f"\nSubmission Performance Breakdown:")
    for label, rec in sub_records.items():
        wr = rec['wins'] / max(1, rec['games']) * 100
        print(f"  - {label:<35}: {rec['wins']:2d}W - {rec['losses']:2d}L ({wr:.1f}%) [{rec['games']} games]")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())

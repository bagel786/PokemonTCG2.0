#!/usr/bin/env python3
"""Deep forensic and statistical comparison between 5k Baseline and Distilled Agent."""

import base64
import json
import ssl
import subprocess
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SUB_5K = 55280578
SUB_DISTILLED = 55280582
EPISODE_SERVICE = "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes"

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
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    return data.get("episodes", [])

def analyze_sub_matches(sub_id: int, name: str) -> dict:
    eps = fetch_episodes(sub_id)
    total_games = len(eps)
    wins = 0
    losses = 0
    ties = 0

    seat0_games = 0
    seat0_wins = 0
    seat1_games = 0
    seat1_wins = 0

    opp_ratings = []
    points_gained = []
    points_lost = []

    sub_losses_vs_800plus = 0
    sub_losses_under_750 = 0

    latest_score = 0.0
    latest_sigma = 0.0

    for ep in eps:
        agents = ep.get("agents", [])
        if len(agents) < 2:
            continue
        hero_idx = 0 if agents[0].get("submissionId") == sub_id else 1
        opp_idx = 1 - hero_idx
        h_agent = agents[hero_idx]
        o_agent = agents[opp_idx]

        reward = h_agent.get("reward")
        initial_score = h_agent.get("initialScore") or 0.0
        updated_score = h_agent.get("updatedScore") or 0.0
        opp_score = o_agent.get("initialScore") or 0.0
        opp_ratings.append(opp_score)

        if not latest_score:
            latest_score = updated_score
            latest_sigma = h_agent.get("updatedConfidence") or 0.0

        delta = updated_score - initial_score
        if delta > 0:
            points_gained.append(delta)
        elif delta < 0:
            points_lost.append(delta)

        if hero_idx == 0:
            seat0_games += 1
            if reward == 1:
                seat0_wins += 1
        else:
            seat1_games += 1
            if reward == 1:
                seat1_wins += 1

        if reward == 1:
            wins += 1
        elif reward in (-1, 0):
            losses += 1
            if opp_score >= 800:
                sub_losses_vs_800plus += 1
            elif opp_score < 750:
                sub_losses_under_750 += 1
        else:
            ties += 1

    return {
        "name": name,
        "sub_id": sub_id,
        "total_games": total_games,
        "wins": wins,
        "losses": losses,
        "win_rate": (wins / max(1, total_games)) * 100,
        "latest_score": latest_score,
        "latest_sigma": latest_sigma,
        "avg_opp_rating": sum(opp_ratings) / max(1, len(opp_ratings)),
        "seat0_games": seat0_games,
        "seat0_wins": seat0_wins,
        "seat0_wr": (seat0_wins / max(1, seat0_games)) * 100 if seat0_games else 0.0,
        "seat1_games": seat1_games,
        "seat1_wins": seat1_wins,
        "seat1_wr": (seat1_wins / max(1, seat1_games)) * 100 if seat1_games else 0.0,
        "avg_pts_per_win": sum(points_gained) / max(1, len(points_gained)) if points_gained else 0.0,
        "avg_pts_per_loss": sum(points_lost) / max(1, len(points_lost)) if points_lost else 0.0,
        "losses_vs_800plus": sub_losses_vs_800plus,
        "losses_under_750": sub_losses_under_750,
    }

def main():
    print("=== PULLING LADDER MATCHMAKING METRICS ===")
    stats_5k = analyze_sub_matches(SUB_5K, "5k Control Baseline")
    stats_dist = analyze_sub_matches(SUB_DISTILLED, "Distilled Agent")

    print("\n" + "="*80)
    print(f"{'METRIC':<35} | {'5k BASELINE (#55280578)':<20} | {'DISTILLED (#55280582)':<20}")
    print("="*80)
    print(f"{'Current ELO Rating':<35} | {stats_5k['latest_score']:<20.1f} | {stats_dist['latest_score']:<20.1f}")
    print(f"{'TrueSkill Sigma (Uncertainty)':<35} | {stats_5k['latest_sigma']:<20.2f} | {stats_dist['latest_sigma']:<20.2f}")
    print(f"{'Total Games Played':<35} | {stats_5k['total_games']:<20d} | {stats_dist['total_games']:<20d}")
    print(f"{'Record (W - L)':<35} | {stats_5k['wins']}W - {stats_5k['losses']}L{'':<13} | {stats_dist['wins']}W - {stats_dist['losses']}L{'':<13}")
    print(f"{'Ladder Win Rate':<35} | {stats_5k['win_rate']:<19.1f}% | {stats_dist['win_rate']:<19.1f}%")
    print(f"{'Average Opponent Rating':<35} | {stats_5k['avg_opp_rating']:<20.1f} | {stats_dist['avg_opp_rating']:<20.1f}")
    print(f"{'Going 1st (Seat 0) Games / WinRate':<35} | {stats_5k['seat0_wins']}/{stats_5k['seat0_games']} ({stats_5k['seat0_wr']:.1f}%){'':<7} | {stats_dist['seat0_wins']}/{stats_dist['seat0_games']} ({stats_dist['seat0_wr']:.1f}%){'':<7}")
    print(f"{'Going 2nd (Seat 1) Games / WinRate':<35} | {stats_5k['seat1_wins']}/{stats_5k['seat1_games']} ({stats_5k['seat1_wr']:.1f}%){'':<7} | {stats_dist['seat1_wins']}/{stats_dist['seat1_games']} ({stats_dist['seat1_wr']:.1f}%){'':<7}")
    print(f"{'Average Points Gained on Win':<35} | {stats_5k['avg_pts_per_win']:<+20.1f} | {stats_dist['avg_pts_per_win']:<+20.1f}")
    print(f"{'Average Points Lost on Loss':<35} | {stats_5k['avg_pts_per_loss']:<+20.1f} | {stats_dist['avg_pts_per_loss']:<+20.1f}")
    print(f"{'Losses vs Elite (Rating >= 800)':<35} | {stats_5k['losses_vs_800plus']:<20d} | {stats_dist['losses_vs_800plus']:<20d}")
    print(f"{'Losses vs Low Tier (Rating < 750)':<35} | {stats_5k['losses_under_750']:<20d} | {stats_dist['losses_under_750']:<20d}")
    print("="*80)

    # Now run head-to-head local simulated match
    print("\nRunning Head-to-Head Simulation: Distilled Model vs 5k Control Baseline (100 Games)...")
    deck_path = ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv"
    dist_weights = ROOT / "artifacts" / "overnight_pipeline_output" / "candidate_checkpoints" / "candidate_2_heads_1e4.npz"
    ctrl_weights = ROOT / "artifacts" / "overnight_grim_20260730" / "grim_selected.npz"

    cmd = [
        sys.executable,
        "-m",
        "training.evaluate",
        "--deck-a", str(deck_path),
        "--model-a", str(dist_weights),
        "--deck-b", str(deck_path),
        "--model-b", str(ctrl_weights),
        "--games", "100",
        "--workers", "8",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    import ast
    for line in reversed(res.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{") and "win_rate_a" in line:
            r = ast.literal_eval(line)
            print(f"\n--- Direct Head-to-Head Mirror Simulation Results ---")
            print(f"Distilled Model Won: {r.get('wins_a')}/100 ({r.get('win_rate_a')*100:.1f}%)")
            s_res = r.get("seat_results_a", {})
            print(f"  - Distilled Going First (Seat 0): {s_res.get('0', {}).get('wins')}/50 ({s_res.get('0', {}).get('win_rate', 0)*100:.1f}%)")
            print(f"  - Distilled Going Second (Seat 1): {s_res.get('1', {}).get('wins')}/50 ({s_res.get('1', {}).get('win_rate', 0)*100:.1f}%)")
            break

    return 0

if __name__ == "__main__":
    raise SystemExit(main())

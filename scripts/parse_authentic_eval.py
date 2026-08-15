#!/usr/bin/env python3
import json
import glob
import math

def wilson_ci(wins, n, z=1.96):
    if n == 0: return 0.0, 0.0
    p = wins / n
    denominator = 1 + z**2/n
    centre_adjusted_probability = p + z**2 / (2*n)
    adjusted_standard_deviation = math.sqrt((p*(1 - p) + z**2 / (4*n)) / n)
    lower_bound = (centre_adjusted_probability - z*adjusted_standard_deviation) / denominator
    upper_bound = (centre_adjusted_probability + z*adjusted_standard_deviation) / denominator
    return lower_bound, upper_bound

for f in sorted(glob.glob("eval_authentic100_*.json")):
    model_name = f.replace("eval_authentic100_", "").replace(".json", "")
    with open(f) as fp:
        data = json.load(fp)
    
    win_rate = data.get("win_rate_a", 0.0)
    wins = data.get("wins_a", 0)
    games = data.get("games", 100)
    ci = data.get("wilson_95", wilson_ci(wins, games))
    
    first = data.get("first_player_results_a", {})
    second = data.get("opponent_results_a", {}) # wait, it's actually seat_results_a? Let's rely on games_detail.
    
    policy_errors = data.get("hero_policy_errors", 0)
    illegal_actions = data.get("overall", {}).get("illegal_actions", 0) # usually 0
    decisions = data.get("decisions", 0)
    
    telemetry = data.get("hero_telemetry", {})
    runtime_policy = telemetry.get("runtime_policy", {})
    
    fallback_total = runtime_policy.get("total", 0)
    fallback_unrepresented = runtime_policy.get("unrepresented", 0)
    fallback_inference = runtime_policy.get("inference", 0)
    fallback_nonfinite = runtime_policy.get("nonfinite", 0)
    fallback_low_advantage = runtime_policy.get("low_advantage", 0)
    
    # physical seat is equivalent to actual order in un-paired games (usually first=seat0, second=seat1, though evaluate.py maps them)
    # The JSON games_detail has exact info.
    seat0_games = 0; seat0_wins = 0
    seat1_games = 0; seat1_wins = 0
    
    for g in data.get("games_detail", []):
        if g.get("physical_seat") == 0:
            seat0_games += 1
            if g.get("win"): seat0_wins += 1
        elif g.get("physical_seat") == 1:
            seat1_games += 1
            if g.get("win"): seat1_wins += 1

    print(f"=== {model_name} ===")
    print(f"Wins/Games: {wins}/{games}")
    print(f"Win Rate: {win_rate:.3f} (95% CI: {ci[0]:.3f} - {ci[1]:.3f})")
    
    print("By Actual Order:")
    print(f"  First:  {first.get('wins', 0)}/{first.get('games', 0)} ({first.get('win_rate', 0.0):.3f})")
    print(f"  Second: {second.get('wins', 0)}/{second.get('games', 0)} ({second.get('win_rate', 0.0):.3f})")
    
    print("By Physical Seat:")
    print(f"  Seat 0: {seat0_wins}/{seat0_games} ({(seat0_wins/seat0_games if seat0_games else 0):.3f})")
    print(f"  Seat 1: {seat1_wins}/{seat1_games} ({(seat1_wins/seat1_games if seat1_games else 0):.3f})")
    
    print("Telemetry:")
    print(f"  Policy Errors: {policy_errors}")
    print(f"  Illegal Actions: {illegal_actions}")
    print(f"  Decisions/Game: {decisions / max(1, games):.1f}")
    print(f"  Fallback Total: {fallback_total}")
    print(f"  Fallback Unrepresented: {fallback_unrepresented}")
    print(f"  Fallback Inference: {fallback_inference}")
    print(f"  Fallback Nonfinite: {fallback_nonfinite}")
    print(f"  Fallback Low Advantage: {fallback_low_advantage}")
    print(f"  Shield Interventions: {telemetry.get('mirror_activations', 0)}")
    print()

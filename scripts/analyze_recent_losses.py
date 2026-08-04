#!/usr/bin/env python3
"""Detailed analysis of recent submissions (55180261, 55180215, 55171235, 55171237) and their losses."""

import base64
import concurrent.futures
import csv
import json
import os
import ssl
import subprocess
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KAGGLE = "/Users/safiullahbaig/Library/Python/3.11/bin/kaggle"
EPISODE_SERVICE = "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes"

def auth_header() -> str:
    blob = json.loads((Path(os.environ["HOME"]) / ".kaggle" / "kaggle.json").read_text())
    if "access_token" in blob:
        return "Bearer " + blob["access_token"]
    u = blob["username"]
    k = blob["key"]
    pair = f"{u}:{k}".encode()
    return "Basic " + base64.b64encode(pair).decode()

def fetch_episodes(submission_id: int) -> list[dict]:
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(
        EPISODE_SERVICE,
        data=json.dumps({"submissionId": submission_id}).encode(),
        headers={"Content-Type": "application/json", "Authorization": auth_header()},
    )
    with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
        return json.load(resp).get("episodes", [])

def download_one(ep_id: int, output_dir: Path) -> tuple[int, str]:
    target_file = output_dir / f"episode-{ep_id}-replay.json"
    alt_file = output_dir / f"{ep_id}.json"
    if (target_file.exists() and target_file.stat().st_size > 0) or (alt_file.exists() and alt_file.stat().st_size > 0):
        return ep_id, "cached"

    command = [KAGGLE, "competitions", "replay", str(ep_id), "-p", str(output_dir)]
    for attempt in range(3):
        res = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if (target_file.exists() and target_file.stat().st_size > 0) or (alt_file.exists() and alt_file.stat().st_size > 0):
            return ep_id, "downloaded"
        time.sleep(1.0 * (attempt + 1))
    return ep_id, "failed"

def get_replay_path(ep_id: int, sub_dir: Path) -> Path | None:
    p1 = sub_dir / f"episode-{ep_id}-replay.json"
    p2 = sub_dir / f"{ep_id}.json"
    if p1.exists() and p1.stat().st_size > 0:
        return p1
    if p2.exists() and p2.stat().st_size > 0:
        return p2
    return None

def parse_replay_details(rp_path: Path, sub_id: int, episode_meta: dict):
    try:
        data = json.loads(rp_path.read_text())
    except Exception as e:
        return {"error": f"Failed to load replay JSON: {e}"}
        
    steps = data.get("steps", [])
    info = data.get("info", {})
    team_names = info.get("TeamNames", ["Player 0", "Player 1"])
    
    # Determine our seat index (0 or 1)
    # Check agents list in episode_meta
    meta_agents = episode_meta.get("agents", [])
    our_agent_idx = None
    for idx, ag in enumerate(meta_agents):
        if ag.get("submissionId") == sub_id:
            our_agent_idx = idx
            break
            
    our_seat = our_agent_idx if our_agent_idx is not None else 0
    opp_seat = 1 - our_seat
    
    our_name = team_names[our_seat] if len(team_names) > our_seat else f"Seat {our_seat}"
    opp_name = team_names[opp_seat] if len(team_names) > opp_seat else f"Seat {opp_seat}"
    
    # Extract decklists from step 1 actions if available
    our_deck = []
    opp_deck = []
    if len(steps) > 1:
        if len(steps[1]) > our_seat:
            our_deck = steps[1][our_seat].get("action") or []
        if len(steps[1]) > opp_seat:
            opp_deck = steps[1][opp_seat].get("action") or []
            
    # Check last step for game result and reason
    last_step = steps[-1] if steps else []
    our_status = last_step[our_seat].get("status") if len(last_step) > our_seat else "UNKNOWN"
    opp_status = last_step[opp_seat].get("status") if len(last_step) > opp_seat else "UNKNOWN"
    
    our_reward = last_step[our_seat].get("reward") if len(last_step) > our_seat else 0
    opp_reward = last_step[opp_seat].get("reward") if len(last_step) > opp_seat else 0
    
    # Analyze raw observations from near the end
    last_raw_obs = None
    for s in reversed(steps):
        if len(s) > our_seat and s[our_seat].get("observation", {}).get("raw"):
            last_raw_obs = s[our_seat]["observation"]["raw"]
            break
        elif len(s) > opp_seat and s[opp_seat].get("observation", {}).get("raw"):
            last_raw_obs = s[opp_seat]["observation"]["raw"]
            break
            
    # Count actions / step details
    total_steps = len(steps)
    
    # Trace game events
    # Let's see what happened during the game
    game_summary = {
        "our_seat": our_seat,
        "opp_name": opp_name,
        "our_status": our_status,
        "opp_status": opp_status,
        "our_reward": our_reward,
        "opp_reward": opp_reward,
        "total_steps": total_steps,
        "our_deck_size": len(our_deck),
        "opp_deck_size": len(opp_deck),
        "last_raw_obs": last_raw_obs
    }
    return game_summary

def analyze_submission(sub_id: int, label: str):
    print(f"\n================================================================================")
    print(f"SUBMISSION {sub_id}: {label}")
    print(f"================================================================================")
    episodes = fetch_episodes(sub_id)
    print(f"Total Episodes: {len(episodes)}")
    if not episodes:
        print("No episodes found.")
        return

    out_dir = ROOT / "data" / "replays" / str(sub_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "episodes_metadata.json").write_text(json.dumps(episodes, indent=2))
    
    # Download replays
    ep_ids = [ep["id"] for ep in episodes if "id" in ep]
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        future_map = {pool.submit(download_one, ep_id, out_dir): ep_id for ep_id in ep_ids}
        for fut in concurrent.futures.as_completed(future_map):
            pass

    # Sort episodes chronologically (by episode id or index)
    # EpisodeService returns newest first, so reversed is chronological
    episodes_chronological = list(reversed(episodes))
    
    current_score = None
    wins = 0
    losses = 0
    ties = 0
    errors = 0
    
    print("\n--- CHRONOLOGICAL MATCH HISTORY ---")
    for idx, ep in enumerate(episodes_chronological, 1):
        ep_id = ep["id"]
        agents = ep.get("agents", [])
        us = next((a for a in agents if a.get("submissionId") == sub_id), {})
        them = next((a for a in agents if a.get("submissionId") != sub_id), {})
        
        status = us.get("status", "UNKNOWN")
        reward = us.get("reward")
        our_init = us.get("initialScore")
        our_upd = us.get("updatedScore")
        opp_init = them.get("initialScore")
        opp_upd = them.get("updatedScore")
        opp_sub = them.get("submissionId")
        opp_status = them.get("status", "UNKNOWN")
        
        delta = (our_upd - our_init) if (our_upd is not None and our_init is not None) else 0.0
        current_score = our_upd if our_upd is not None else current_score
        
        result_str = "TIE"
        if reward is not None:
            if reward > 0:
                result_str = "WIN "
                wins += 1
            elif reward < 0:
                result_str = "LOSS"
                losses += 1
            else:
                ties += 1
        elif status == "ERROR":
            result_str = "ERR "
            errors += 1
        else:
            result_str = "LOSS"
            losses += 1
            
        rp_path = get_replay_path(ep_id, out_dir)
        replay_summary = parse_replay_details(rp_path, sub_id, ep) if rp_path else {}
        opp_name = replay_summary.get("opp_name", f"Sub {opp_sub}")
        total_steps = replay_summary.get("total_steps", "?")
        
        our_init_s = f"{our_init:.1f}" if our_init is not None else "Init"
        our_upd_s = f"{our_upd:.1f}" if our_upd is not None else "N/A"
        opp_init_s = f"{opp_init:.1f}" if opp_init is not None else "N/A"
        
        print(f"[{idx:2d}] Ep {ep_id} | {result_str} (Reward: {reward}) | Delta: {delta:+6.1f} | ELO: {our_init_s} -> {our_upd_s} | Opp: {opp_name[:20]:20s} (ELO {opp_init_s}) | Steps: {total_steps}")
        
    print(f"\nSUMMARY: Total Games = {len(episodes)} | Record = {wins}W - {losses}L - {ties}T (Winrate: {wins/max(1, len(episodes)):.1%}) | Final ELO: {current_score}")

def main():
    analyze_submission(55180261, "Grimmsnarl 5k Reference (Recent)")
    analyze_submission(55180215, "Grimmsnarl Gen4 Sparred (Recent)")
    analyze_submission(55171235, "Grimmsnarl 5k Reference (Previous Day)")
    analyze_submission(55171237, "Grimmsnarl Co-Evolution R2 (Previous Day)")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Inspect live matches and episode replay logs for submission 55283588 (Master v1)."""

import json
import ssl
import sys
import urllib.request
from pathlib import Path

from kaggle.api.kaggle_api_extended import KaggleApi

SUB_ID = 55283588

def main():
    api = KaggleApi()
    api.authenticate()
    token = api.config_values.get("token", "")
    
    payload = json.dumps({"submissionId": SUB_ID}).encode()
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "PTCG-Live/1.0",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(
        "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes",
        data=payload,
        headers=headers,
    )
    ctx = ssl._create_unverified_context()

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"Error fetching episodes: {e}")
        return 1

    eps = data.get("episodes", [])
    print(f"=== LIVE MATCH REPORT FOR MASTER V1 (#{SUB_ID}) ===")
    print(f"Total episodes played: {len(eps)}")

    for ep in eps:
        ep_id = ep.get("id")
        agents = ep.get("agents", [])
        
        hero_idx = None
        opp_idx = None
        for idx, a in enumerate(agents):
            if a.get("submissionId") == SUB_ID:
                hero_idx = idx
            else:
                opp_idx = idx

        hero = agents[hero_idx] if hero_idx is not None else {}
        opp = agents[opp_idx] if opp_idx is not None else {}

        hero_reward = hero.get("reward", 0)
        opp_reward = opp.get("reward", 0)
        hero_score = hero.get("updatedScore", 0)
        opp_score = opp.get("updatedScore", 0)
        hero_init = hero.get("initialScore", 0)
        opp_init = opp.get("initialScore", 0)
        opp_sub = opp.get("submissionId", "N/A")

        outcome = "WIN" if hero_reward > opp_reward else ("LOSS" if hero_reward < opp_reward else "TIE")
        print(f"Episode {ep_id}: {outcome:<4} | Seat {hero_idx} (Init={hero_init:.1f} -> Updated={hero_score:.1f}) vs Opponent Sub={opp_sub} (Init={opp_init:.1f} -> Updated={opp_score:.1f}, Seat={opp_idx})")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Forensically inspect Episode 90342558: the loss vs 464.8 rated bot."""

import json
import ssl
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EP_ID = 90342558
OUT_PATH = ROOT / "data" / "replays" / "55287852" / f"episode-{EP_ID}-replay.json"
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

# Fetch replay directly from Kaggle Replay API or Kaggle CLI
import kaggle
kaggle.api.authenticate()
import subprocess

print(f"Downloading replay for Episode {EP_ID}...")
cmd = [sys.executable, "-m", "kaggle", "competitions", "replay", str(EP_ID), "-p", str(OUT_PATH.parent)]
res = subprocess.run(cmd, capture_output=True, text=True)
alt_path = OUT_PATH.parent / f"{EP_ID}.json"
if alt_path.exists():
    alt_path.rename(OUT_PATH)

if not OUT_PATH.exists() or OUT_PATH.stat().st_size == 0:
    print("Trying direct curl / API fetch...")
    # direct API
    url = f"https://www.kaggle.com/api/i/competitions.EpisodeService/ShowEpisode"
    # Or fetch from kaggle episode api
    # Let's check if file downloaded

if OUT_PATH.exists():
    print(f"Replay saved: {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")
    data = json.loads(OUT_PATH.read_text(encoding="utf-8"))
    
    # Parse replay steps
    steps = data.get("steps", [])
    print(f"Total steps: {len(steps)}")
    
    # Let's inspect agents, decks, outcome, and turn-by-turn logs
    agents = data.get("agents", [])
    print("Agents:", agents)
    
    for i, step in enumerate(steps[:15]):
        print(f"Step {i}:", json.dumps(step)[:200])
else:
    print("Failed to download replay.")

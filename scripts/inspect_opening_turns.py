#!/usr/bin/env python3
import json
from pathlib import Path

rp_path = Path('data/replays/55287852/episode-90342558-replay.json')
data = json.loads(rp_path.read_text(encoding='utf-8'))
for i in range(2, 18):
    s = data['steps'][i]
    print(f"\n--- STEP {i} ---")
    for p_i, p in enumerate(s):
        act = p.get('action')
        obs = p.get('observation', {})
        sel = obs.get('select')
        cur = obs.get('current') or {}
        hand_cids = [c.get('cardId') for c in cur.get('players', [{}, {}])[p_i].get('hand', []) if isinstance(c, dict)]
        print(f"P{p_i}: action={act}")
        if sel:
            print(f"     select={sel}")
        if hand_cids:
            print(f"     hand_card_ids={hand_cids}")

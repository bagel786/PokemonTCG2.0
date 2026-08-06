#!/usr/bin/env python3
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
out_dir = ROOT / "data" / "replays" / "55287852"

for ep_id in [90341059, 90343300]:
    rp = out_dir / f"episode-{ep_id}-replay.json"
    if not rp.exists():
        cmd = [sys.executable, "-m", "kaggle", "competitions", "replay", str(ep_id), "-p", str(out_dir)]
        subprocess.run(cmd, capture_output=True, text=True)
        alt = out_dir / f"{ep_id}.json"
        if alt.exists():
            alt.rename(rp)
    
    if rp.exists():
        data = json.loads(rp.read_text(encoding="utf-8"))
        steps = data.get("steps", [])
        print(f"\n================ Episode {ep_id} (Total steps: {len(steps)}) ================")
        last_step = steps[-1]
        print("Last step outcomes:", [p.get("status") for p in last_step], [p.get("reward") for p in last_step])
        # Find why game ended: bench count of hero
        for s in steps[-3:]:
            for p_i, p in enumerate(s):
                obs = p.get("observation", {})
                cur = obs.get("current") or {}
                if "players" in cur and len(cur["players"]) >= 2:
                    p0 = cur["players"][0]
                    p1 = cur["players"][1]
                    print(f"Step {obs.get('step')}: P0 Active len={len(p0.get('active') or [])} Bench len={len(p0.get('bench') or [])} Prizes={p0.get('prizes')} | P1 Active len={len(p1.get('active') or [])} Bench len={len(p1.get('bench') or [])} Prizes={p1.get('prizes')}")
                    break

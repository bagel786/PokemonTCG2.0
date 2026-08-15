#!/usr/bin/env python3
"""Persist episode metadata and download public-episode replays for the 4 live
grim-a2-damage submissions. Stops on any repeated CLI failure (incl. 429)."""

import json
import os
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPLAYS = ROOT / "data" / "replays"
URL = "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes"

SUBS = (55513649, 55513642, 55491471, 55491464)


def auth() -> str:
    blob = json.loads((Path.home() / ".kaggle" / "credentials.json").read_text())
    return "Bearer " + (blob.get("access_token") or blob.get("refresh_token"))


def pull_metadata(sub_id: int) -> list[dict]:
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(
        URL,
        data=json.dumps({"submissionId": sub_id}).encode(),
        headers={"Content-Type": "application/json",
                 "User-Agent": "PTCG-Live/1.0",
                 "Authorization": auth()},
    )
    with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
        return json.loads(resp.read().decode()).get("episodes", [])


def main() -> int:
    token = json.loads((Path.home() / ".kaggle" / "credentials.json").read_text())["access_token"]
    env = dict(os.environ, KAGGLE_API_TOKEN=token)
    for sub_id in SUBS:
        sub_dir = REPLAYS / str(sub_id)
        sub_dir.mkdir(parents=True, exist_ok=True)
        try:
            eps = pull_metadata(sub_id)
        except urllib.error.HTTPError as e:
            print(f"STOP: HTTP {e.code} listing episodes for {sub_id} "
                  f"(Retry-After: {e.headers.get('Retry-After', 'none')})")
            return 3
        meta_path = sub_dir / "episodes_metadata.json"
        meta_path.write_text(json.dumps(eps, indent=2), encoding="utf-8")
        public = [e for e in eps
                  if e.get("type") == "EPISODE_TYPE_PUBLIC" and e.get("state") == "COMPLETED"]
        print(f"sub {sub_id}: {len(public)} public episodes, metadata saved")
        failures = 0
        for i, ep in enumerate(public, 1):
            target = sub_dir / f"episode-{ep['id']}-replay.json"
            if target.exists():
                continue
            cmd = ["kaggle", "competitions", "replay", str(ep["id"]), "-p", str(sub_dir)]
            result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=env)
            if result.returncode != 0:
                failures += 1
                print(f"  FAIL episode {ep['id']} ({i}/{len(public)}): "
                      f"{result.stderr.strip()[-200:]}")
                if failures >= 3:
                    print("STOP: 3 consecutive download failures - likely rate limited.")
                    return 3
                time.sleep(5)
                continue
            failures = 0
            if i % 10 == 0:
                print(f"  {i}/{len(public)} replays for {sub_id}")
            time.sleep(0.7)
        print(f"sub {sub_id}: replay pass done ({len(public)} checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

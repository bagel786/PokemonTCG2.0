#!/usr/bin/env python3
"""Fetch ListEpisodes metadata for candidate teacher submissions and cache it.

Usage:
    python3 scripts/dragapult_emergency_episodes.py 55456110 55456208 ...
"""

from __future__ import annotations

import gzip
import json
import random
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIST_EPISODES = "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes"
OUT = ROOT / "data" / "dragapult_emergency" / "episodes"
SSL_CTX = ssl._create_unverified_context()

_LAST = [0.0]
_MIN = 1.2


def access_token() -> str:
    res = subprocess.run(["kaggle", "auth", "print-access-token"], capture_output=True, text=True)
    token = res.stdout.strip()
    if not token:
        raise SystemExit("no access token: " + res.stderr.strip()[:200])
    return token


AUTH = "Bearer " + access_token()


def throttle():
    wait = _MIN - (time.time() - _LAST[0])
    if wait > 0:
        time.sleep(wait)
    _LAST[0] = time.time()


def get(url: str, payload: dict, tries: int = 8):
    for attempt in range(tries):
        throttle()
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": AUTH,
                     "Accept-Encoding": "gzip"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120, context=SSL_CTX) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503) or attempt == tries - 1:
                raise
            delay = max(60.0, min(2 ** attempt * 15, 180)) + random.random() * 5
            print(f"    http {exc.code}, retry in {delay:.0f}s", flush=True)
            time.sleep(delay)
    return None


def summarize(episodes: list) -> None:
    completed = [e for e in episodes if e.get("status", "").upper() in ("COMPLETE", "COMPLETED")
                 or e.get("status") is None or (e.get("agents") and all(
                     a.get("reward") is not None for a in e["agents"]))]
    times = sorted(e.get("createTime", "") for e in completed)
    print(f"    total episodes: {len(episodes)}  completed: {len(completed)}")
    if times:
        print(f"    completed range: {times[0][:16]} .. {times[-1][:16]}")
        recent = [t for t in times if t >= "2026-08-11"]
        print(f"    completed since Aug 11: {len(recent)}")
    for e in completed[-3:]:
        print(f"    last: {e.get('createTime','')[:16]} ep {e.get('id')} agents "
              f"{[(a.get('teamId'), a.get('submissionId'), a.get('updatedScore')) for a in e.get('agents', [])]}")


def main() -> int:
    submission_ids = [int(a) for a in sys.argv[1:]]
    OUT.mkdir(parents=True, exist_ok=True)
    for sid in submission_ids:
        path = OUT / f"{sid}.json"
        if path.exists():
            blob = json.loads(path.read_text())
            episodes = blob.get("result", {}).get("episodes", blob.get("episodes", []))
            print(f"submission {sid}: cached")
        else:
            try:
                blob = get(LIST_EPISODES, {"submissionId": sid})
            except Exception as exc:
                print(f"submission {sid}: FAILED {str(exc)[:80]}", flush=True)
                continue
            path.write_text(json.dumps(blob))
            episodes = blob.get("result", {}).get("episodes", blob.get("episodes", []))
            print(f"submission {sid}: fetched", flush=True)
        summarize(episodes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

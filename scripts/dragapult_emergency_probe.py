#!/usr/bin/env python3
"""Probe team public-submissions for Dragapult teacher candidates.

Fetches /competitions/teams/{teamId}/public-submissions, caches the JSON per
team under data/dragapult_emergency/team_submissions/, and prints a compact
table of the most recent submissions.

Usage:
    python3 scripts/dragapult_emergency_probe.py 16380946 16422241 ...
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
API = "https://api.kaggle.com/v1"
OUT = ROOT / "data" / "dragapult_emergency" / "team_submissions"
SSL_CTX = ssl._create_unverified_context()

_LAST = [0.0]
_MIN = 0.9


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


def get(url: str, tries: int = 8):
    for attempt in range(tries):
        throttle()
        req = urllib.request.Request(url, headers={"Authorization": AUTH, "Accept-Encoding": "gzip"})
        try:
            with urllib.request.urlopen(req, timeout=45, context=SSL_CTX) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503) or attempt == tries - 1:
                raise
            delay = max(60.0, min(2 ** attempt * 10, 120)) + random.random() * 5
            print(f"    http {exc.code}, retry in {delay:.0f}s", flush=True)
            time.sleep(delay)
    return None


def main() -> int:
    team_ids = [int(a) for a in sys.argv[1:]]
    OUT.mkdir(parents=True, exist_ok=True)
    for tid in team_ids:
        path = OUT / f"{tid}.json"
        if path.exists():
            subs = json.loads(path.read_text())
            print(f"team {tid}: cached {len(subs)} subs")
        else:
            try:
                subs = get(f"{API}/competitions/teams/{tid}/public-submissions")
            except Exception as exc:
                print(f"team {tid}: FAILED {str(exc)[:80]}", flush=True)
                continue
            if not isinstance(subs, list):
                print(f"team {tid}: unexpected payload {str(subs)[:80]}", flush=True)
                continue
            path.write_text(json.dumps(subs, indent=1))
            print(f"team {tid}: {len(subs)} subs", flush=True)
        for s in sorted(subs, key=lambda s: s.get("date") or s.get("submissionDate") or "", reverse=True)[:6]:
            score = s.get("publicScore")
            print(f"    sub {s.get('id')}  {str(s.get('date') or s.get('submissionDate'))[:19]}  "
                  f"score={score if score is not None else '-'}  {str(s.get('description') or '')[:40]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

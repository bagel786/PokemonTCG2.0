#!/usr/bin/env python3
"""Download missing replays for submissions, honoring Retry-After on 429.

Usage:
    python scripts/fetch_replays_honor_retry.py 55491464 55491471
"""

from __future__ import annotations

import argparse
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
OUT = ROOT / "data" / "replays"
REPLAY_URL = "https://api.kaggle.com/v1/competitions.CompetitionApiService/GetEpisodeReplay"
_CTX = ssl._create_unverified_context()


def token() -> str:
    res = subprocess.run(
        [sys.executable, "-m", "kaggle", "auth", "print-access-token"],
        capture_output=True, text=True,
    )
    out = res.stdout.strip()
    if not out:
        raise SystemExit(f"token refresh failed: {res.stderr.strip()[:200]}")
    return out


def fetch_replay(ep: int, out_dir: Path, bearer: str) -> str:
    target = out_dir / f"episode-{ep}-replay.json"
    if target.exists() and target.stat().st_size > 0:
        return "skip"
    req = urllib.request.Request(
        REPLAY_URL,
        data=json.dumps({"id": ep}).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + bearer},
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60, context=_CTX) as resp:
                target.write_bytes(resp.read())
            return "ok"
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                wait = float(exc.headers.get("Retry-After") or 0) or 30.0
                print(f"  429 on {ep}: sleeping {wait:.0f}s", flush=True)
                time.sleep(min(wait, 1800.0))
                continue
            print(f"  HTTP {exc.code} on {ep}: {str(exc)[:120]}", flush=True)
            return "fail"
        except Exception as exc:
            print(f"  error on {ep}: {type(exc).__name__} {str(exc)[:120]}", flush=True)
            time.sleep(min(60, 5 * (2 ** attempt)))
    return "fail"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("subs", nargs="+", type=int)
    ap.add_argument("--pace", type=float, default=6.0,
                    help="seconds between replay requests")
    args = ap.parse_args()

    bearer = token()
    work = []
    for sid in args.subs:
        out_dir = OUT / str(sid)
        meta = json.loads((out_dir / "episodes_metadata.json").read_text())
        eps = [e["id"] for e in meta if "id" in e]
        work += [(sid, ep, out_dir) for ep in eps]
        print(f"  {sid}: {len(eps)} episodes", flush=True)

    counts = {"ok": 0, "skip": 0, "fail": 0}
    for i, (sid, ep, out_dir) in enumerate(work, 1):
        result = fetch_replay(ep, out_dir, bearer)
        counts[result] += 1
        if i % 10 == 0 or i == len(work) or result == "fail":
            print(f"  {i}/{len(work)} {counts}", flush=True)
        if result != "skip":
            time.sleep(args.pace)
    print(f"done {counts}", flush=True)
    return 1 if counts["fail"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

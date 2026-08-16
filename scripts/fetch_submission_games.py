#!/usr/bin/env python3
"""Download every ladder game for our Kaggle submissions.

Auth note: the cached OAuth blob in ~/.kaggle/credentials.json is NOT picked up by
the `kaggle competitions ...` subcommands (its scope is resources.admin:*). The
refreshed bearer token must be handed back to the CLI via KAGGLE_API_TOKEN, which
is what ``access_token()`` does.

Usage:
    python scripts/fetch_submission_games.py --list
    python scripts/fetch_submission_games.py --family d842
    python scripts/fetch_submission_games.py --submission 55358290 55358291
    python scripts/fetch_submission_games.py --all
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import io
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
PY = "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11"
COMPETITION = "pokemon-tcg-ai-battle"
LIST_EPISODES = "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes"
OUT_ROOT = ROOT / "data" / "replays"

# Submissions that ship the d842 Grimmsnarl-5k policy.
D842_FAMILY = ("grimmsnarl_5k_reference", "d842")

_CTX = ssl._create_unverified_context()
_TOKEN: str | None = None


def access_token() -> str:
    """Refresh and cache the OAuth bearer token via the kaggle CLI."""
    global _TOKEN
    if _TOKEN is None:
        res = subprocess.run(
            [PY, "-m", "kaggle", "auth", "print-access-token"],
            capture_output=True, text=True,
        )
        _TOKEN = res.stdout.strip()
        if not _TOKEN:
            raise SystemExit(f"could not obtain kaggle access token: {res.stderr.strip()}")
    return _TOKEN


def cli_env() -> dict:
    env = dict(os.environ)
    env["KAGGLE_API_TOKEN"] = access_token()
    return env


def list_submissions() -> list[dict]:
    res = subprocess.run(
        [PY, "-m", "kaggle", "competitions", "submissions", "-c", COMPETITION, "-v"],
        capture_output=True, text=True, env=cli_env(),
    )
    body = res.stdout.lstrip("﻿")
    if "ref," not in body:
        raise SystemExit(f"submission listing failed: {res.stderr.strip()[:400]}")
    body = body[body.index("ref,"):]
    rows = [r for r in csv.DictReader(io.StringIO(body)) if r.get("ref")]
    for r in rows:
        r["status"] = r.get("status", "").replace("SubmissionStatus.", "")
    return rows


def fetch_episodes(submission_id: int) -> list[dict]:
    """All episodes this submission played. Retries on transient failures."""
    req = urllib.request.Request(
        LIST_EPISODES,
        data=json.dumps({"submissionId": int(submission_id)}).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + access_token()},
    )
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=90, context=_CTX) as resp:
                data = json.load(resp)
            return data.get("result", {}).get("episodes", []) or data.get("episodes", [])
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == 5:
                raise
            # Kaggle throttles this endpoint hard; honour Retry-After when present.
            wait = float(exc.headers.get("Retry-After") or 0) or 15 * (2 ** attempt)
            print(f"    429 on {submission_id}, sleeping {wait:.0f}s", flush=True)
            time.sleep(wait)
        except Exception:
            if attempt == 5:
                raise
            time.sleep(5 * (attempt + 1))
    return []


def download_replay(ep_id: int, out_dir: Path, env: dict) -> str:
    target = out_dir / f"episode-{ep_id}-replay.json"
    if target.exists() and target.stat().st_size > 0:
        return "skipped"
    for attempt in range(5):
        subprocess.run(
            [PY, "-m", "kaggle", "competitions", "replay", str(ep_id), "-p", str(out_dir)],
            capture_output=True, text=True, env=env,
        )
        if target.exists() and target.stat().st_size > 0:
            return "downloaded"
        time.sleep(min(60, 4 * (2 ** attempt)))  # throttled endpoint; back off hard
    return "failed"


def sync(submission_id: int, workers: int) -> dict:
    out_dir = OUT_ROOT / str(submission_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    episodes = fetch_episodes(submission_id)
    (out_dir / "episodes_metadata.json").write_text(json.dumps(episodes, indent=2))
    ep_ids = [e["id"] for e in episodes if "id" in e]
    print(f"  {submission_id}: {len(ep_ids)} episodes", flush=True)

    env = cli_env()
    counts = {"downloaded": 0, "skipped": 0, "failed": 0}
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(download_replay, e, out_dir, env): e for e in ep_ids}
        for done, fut in enumerate(cf.as_completed(futures), 1):
            counts[fut.result()] += 1
            if done % 25 == 0 or done == len(ep_ids):
                print(f"    {done}/{len(ep_ids)} {counts}", flush=True)
    return {"submission_id": submission_id, "episodes": len(ep_ids), **counts}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="print submissions and exit")
    ap.add_argument("--all", action="store_true", help="every COMPLETE submission")
    ap.add_argument("--family", help="substring match on fileName/description, or 'd842'")
    ap.add_argument("--submission", nargs="+", type=int)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--pace", type=float, default=3.0,
                    help="seconds to wait between submissions (429 avoidance)")
    args = ap.parse_args()

    subs = list_submissions()

    if args.list:
        for r in subs:
            score = r.get("publicScore") or "-"
            print(f"{r['ref']:>9}  {score:>7}  {r['status']:<9}  "
                  f"{r['fileName'][:42]:<42}  {r.get('description', '')[:50]}")
        print(f"\n{len(subs)} submissions")
        return 0

    if args.submission:
        targets = [int(s) for s in args.submission]
    else:
        complete = [r for r in subs if r["status"] == "COMPLETE"]
        if args.all:
            targets = [int(r["ref"]) for r in complete]
        else:
            keys = D842_FAMILY if (args.family or "d842") == "d842" else (args.family,)
            targets = [
                int(r["ref"]) for r in complete
                if any(k in r["fileName"].lower() or k in r.get("description", "").lower()
                       for k in keys)
            ]

    if not targets:
        print("no matching submissions")
        return 1

    print(f"syncing {len(targets)} submissions -> {OUT_ROOT}")
    report = []
    for i, sid in enumerate(targets):
        if i:
            time.sleep(args.pace)
        try:
            report.append(sync(sid, args.workers))
        except Exception as exc:  # keep going; one bad submission shouldn't kill the run
            print(f"  {sid}: ERROR {exc!r}", flush=True)
            report.append({"submission_id": sid, "error": repr(exc)})

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    summary = OUT_ROOT / "fetch_summary.json"
    summary.write_text(json.dumps(report, indent=2))
    total = sum(r.get("episodes", 0) for r in report)
    got = sum(r.get("downloaded", 0) + r.get("skipped", 0) for r in report)
    print(f"\ndone: {got}/{total} replays across {len(report)} submissions -> {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

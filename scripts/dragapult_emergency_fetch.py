#!/usr/bin/env python3
"""Download replays for Dragapult teacher submissions with resume + deck audit.

Usage:
    python3 scripts/dragapult_emergency_fetch.py --submission 55456110 --limit 5
    python3 scripts/dragapult_emergency_fetch.py --submission 55456110 --all --workers 3
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EP_DIR = ROOT / "data" / "dragapult_emergency" / "episodes"
OUT_ROOT = ROOT / "data" / "dragapult_emergency" / "replays"
KAGGLE = subprocess.run(["which", "kaggle"], capture_output=True, text=True).stdout.strip() or "kaggle"

REFERENCE_DECK = ROOT / "freshstart" / "decklists" / "dragapult_ex.txt"
CARD_CSV = ROOT / "freshstart" / "data" / "EN_Card_Data.csv"

_name_cache: dict[int, str] = {}
if CARD_CSV.exists():
    import csv
    for row in csv.DictReader(CARD_CSV.read_text(encoding="utf-8-sig").splitlines()):
        _name_cache[int(row["Card ID"])] = row["Card Name"]


def access_token() -> str:
    res = subprocess.run([KAGGLE, "auth", "print-access-token"], capture_output=True, text=True)
    token = res.stdout.strip()
    if not token:
        raise SystemExit("no access token: " + res.stderr.strip()[:200])
    return token


def cli_env() -> dict:
    env = dict(os.environ)
    env["KAGGLE_API_TOKEN"] = access_token()
    return env


def deck_sig(deck: list[int]) -> str:
    return hashlib.sha256(json.dumps(sorted(deck)).encode()).hexdigest()[:16]


def deck_summary(deck: list[int]) -> str:
    return ", ".join(f"{n}x {_name_cache.get(c, c)}" for c, n in Counter(deck).most_common())


def completed_episodes(sid: int) -> list[dict]:
    blob = json.loads((EP_DIR / f"{sid}.json").read_text())
    episodes = blob.get("result", {}).get("episodes", blob.get("episodes", []))
    done = [e for e in episodes
            if e.get("agents") and all(a.get("reward") is not None for a in e.get("agents", []))]
    return sorted(done, key=lambda e: e.get("createTime", ""), reverse=True)


def download_replay(ep_id: int, out_dir: Path, env: dict) -> str:
    target = out_dir / f"episode-{ep_id}-replay.json"
    if target.exists() and target.stat().st_size > 0:
        return "skipped"
    for attempt in range(4):
        subprocess.run(
            [KAGGLE, "competitions", "replay", str(ep_id), "-p", str(out_dir), "-q"],
            capture_output=True, text=True, env=env,
        )
        if target.exists() and target.stat().st_size > 0:
            return "downloaded"
        time.sleep(min(90, 6 * (2 ** attempt)) + random.random() * 3)
    return "failed"


def hero_seats(episode: dict, tid: int) -> list[int]:
    seats = []
    for agent in episode.get("agents", []):
        if agent.get("teamId") == tid:
            seats.append(int(agent.get("index", 0)))
    return seats


def load_hero_deck(replay: dict, seats: list[int]) -> list[int] | None:
    steps = replay.get("steps") or []
    if len(steps) < 2:
        return None
    for seat in seats:
        if seat >= len(steps[1]):
            continue
        candidate = (steps[1][seat] or {}).get("action") or []
        if len(candidate) == 60:
            return [int(c) for c in candidate]
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", nargs="+", type=int, required=True)
    parser.add_argument("--team", nargs="+", type=int, default=[],
                        help="team ids paired with --submission order")
    parser.add_argument("--all", action="store_true", help="download every completed episode")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--since", default="2026-08-11T00:00:00")
    args = parser.parse_args()

    env = cli_env()
    for sid, tid in zip(args.submission, args.team or [None] * len(args.submission)):
        episodes = completed_episodes(sid)
        picked = [e for e in episodes if e.get("createTime", "") >= args.since]
        if not args.all:
            picked = picked[: args.limit]
        print(f"submission {sid}: {len(picked)} episodes to fetch "
              f"({len(episodes)} completed total)", flush=True)
        if not picked:
            continue
        out_dir = OUT_ROOT / str(sid)
        out_dir.mkdir(parents=True, exist_ok=True)
        results = Counter()
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(download_replay, e["id"], out_dir, env): e["id"]
                       for e in picked}
            for i, fut in enumerate(as_completed(futures), 1):
                results[fut.result()] += 1
                if i % 10 == 0:
                    print(f"    {i}/{len(picked)} {dict(results)}", flush=True)
        print(f"    done: {dict(results)}", flush=True)
        if tid:
            episodes_by_id = {e["id"]: e for e in episodes}
            decks: dict[str, list[int]] = {}
            counts: Counter[str] = Counter()
            for path in sorted(out_dir.glob("*.json")):
                try:
                    replay = json.loads(path.read_text())
                except Exception:
                    continue
                ep_id = replay.get("info", {}).get("EpisodeId")
                seats = hero_seats(episodes_by_id.get(ep_id, {}), tid)
                deck = load_hero_deck(replay, seats)
                if deck:
                    sig = deck_sig(deck)
                    counts[sig] += 1
                    decks.setdefault(sig, deck)
            for sig, n in counts.most_common(5):
                print(f"    deck {sig} x{n}: {deck_summary(decks[sig])}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

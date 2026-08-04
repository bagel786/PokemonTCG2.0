#!/usr/bin/env python3
"""Stream a bounded daily Kaggle sample and mine exact-deck Grim wins.

Raw episode JSON is downloaded into per-file temporary directories and removed
immediately after inspection.  Only model-ready decisions from winning seats
whose 60-card deck exactly matches the requested Grimmsnarl deck are retained.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.replay import episode_reward, iter_decisions, load_episode  # noqa: E402
from training.lucario_data import (  # noqa: E402
    canonical_deck,
    deterministic_gzip_text,
    load_deck,
    sha256_file,
)


KAGGLE = ["kaggle"] if shutil.which("kaggle") else [sys.executable, "-m", "kaggle"]
DEFAULT_DECK = ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv"


def command_page(command: list[str]) -> tuple[list[dict], str | None]:
    result = subprocess.run(command, check=True, text=True, capture_output=True)
    start = result.stdout.find("[")
    if start < 0:
        raise RuntimeError(f"Kaggle CLI did not return a JSON list: {result.stdout[:500]}")
    token_match = re.search(r"Next Page Token = (\S+)", result.stdout[:start])
    return json.loads(result.stdout[start:]), token_match.group(1) if token_match else None


def list_episode_files(dataset: str) -> list[dict]:
    listing = []
    page_token = None
    while True:
        command = [
            *KAGGLE,
            "datasets",
            "files",
            dataset,
            "--page-size",
            "200",
            "--format",
            "json",
        ]
        if page_token:
            command.extend(["--page-token", page_token])
        page, page_token = command_page(command)
        listing.extend(row for row in page if str(row.get("name", "")).endswith(".json"))
        if not page_token:
            return listing


def deck_hash(signature: tuple[int, ...]) -> str:
    payload = ",".join(map(str, signature)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def mine_episode(path: Path, grim_signature: tuple[int, ...], dataset: str, date: str) -> dict:
    """Inspect one replay and return exact-Grim unit statistics and win rows."""
    episode = load_episode(path)
    steps = episode.get("steps") or []
    if len(steps) < 2 or len(steps[1]) < 2:
        return {"status": "invalid", "rows": [], "units": []}
    decks = [canonical_deck(steps[1][seat].get("action", [])) for seat in (0, 1)]
    if any(len(deck) != 60 for deck in decks):
        return {"status": "invalid", "rows": [], "units": []}

    exact_seats = [seat for seat in (0, 1) if decks[seat] == grim_signature]
    if not exact_seats:
        return {"status": "non_grim", "rows": [], "units": []}

    info = episode.get("info") or {}
    episode_id = str(info.get("EpisodeId") or path.stem)
    team_names = info.get("TeamNames") or ["seat_0", "seat_1"]
    units = []
    winning_seats = set()
    for seat in exact_seats:
        reward = float(episode_reward(episode, seat))
        team = team_names[seat] if len(team_names) > seat else f"seat_{seat}"
        units.append(
            {
                "episode_id": episode_id,
                "seat": seat,
                "team": team,
                "reward": reward,
                "opponent_exact_grim": decks[1 - seat] == grim_signature,
                "opponent_deck_sha256": deck_hash(decks[1 - seat]),
            }
        )
        if reward > 0:
            winning_seats.add(seat)

    rows = []
    if winning_seats:
        for decision in iter_decisions(episode, None, feature_version=2):
            if decision.seat not in winning_seats:
                continue
            row = decision.to_json()
            opponent = decks[1 - decision.seat]
            row.update(
                {
                    "source": "daily_top_episode",
                    "source_dataset": dataset,
                    "source_date": date,
                    "source_episode_file": path.name,
                    "opponent_exact_grim": opponent == grim_signature,
                    "opponent_deck_sha256": deck_hash(opponent),
                }
            )
            rows.append(row)
    return {"status": "grim", "rows": rows, "units": units}


def download_and_mine(
    dataset: str,
    date: str,
    item: dict,
    temporary_root: Path,
    grim_signature: tuple[int, ...],
) -> dict:
    filename = str(item["name"])
    task_dir = temporary_root / Path(filename).stem
    task_dir.mkdir(parents=True, exist_ok=True)
    target = task_dir / filename
    error = ""
    try:
        for attempt in range(4):
            command = [
                *KAGGLE,
                "datasets",
                "download",
                dataset,
                "-f",
                filename,
                "-p",
                str(task_dir),
                "--unzip",
                "-q",
            ]
            result = subprocess.run(command, text=True, capture_output=True, timeout=180)
            if result.returncode == 0 and target.exists() and target.stat().st_size > 0:
                mined = mine_episode(target, grim_signature, dataset, date)
                mined.update({"filename": filename, "bytes": int(item.get("size", 0) or 0)})
                return mined
            error = result.stderr.strip()
            time.sleep(2**attempt)
        return {
            "status": "failed",
            "rows": [],
            "units": [],
            "filename": filename,
            "bytes": int(item.get("size", 0) or 0),
            "error": error[-500:],
        }
    except Exception as exc:  # Keep the pilot auditable instead of aborting mid-stream.
        return {
            "status": "failed",
            "rows": [],
            "units": [],
            "filename": filename,
            "bytes": int(item.get("size", 0) or 0),
            "error": f"{type(exc).__name__}: {exc}"[-500:],
        }
    finally:
        shutil.rmtree(task_dir, ignore_errors=True)


def write_outputs(args, dataset: str, listing: list[dict], selected: list[dict], results: list[dict]) -> dict:
    output = Path(args.output).resolve()
    manifest_path = Path(args.manifest).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    seen = set()
    rows = []
    units = {}
    statuses = Counter()
    failures = []
    for result in results:
        statuses[result["status"]] += 1
        if result["status"] == "failed":
            failures.append({"filename": result["filename"], "error": result.get("error", "")})
        for unit in result["units"]:
            units[(str(unit["episode_id"]), int(unit["seat"]))] = unit
        for row in result["rows"]:
            key = (str(row["episode_id"]), int(row["seat"]), int(row["step"]))
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    rows.sort(key=lambda row: (str(row["episode_id"]), int(row["seat"]), int(row["step"])))

    temporary = output.with_name(output.name + ".tmp")
    with deterministic_gzip_text(temporary) as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    temporary.replace(output)

    exact_units = list(units.values())
    winning_units = [unit for unit in exact_units if float(unit["reward"]) > 0]
    manifest = {
        "version": 1,
        "dataset": dataset,
        "date": args.date,
        "seed": args.seed,
        "requested_files": args.limit,
        "listed_files": len(listing),
        "listed_bytes": sum(int(item.get("size", 0) or 0) for item in listing),
        "sampled_files": len(selected),
        "sampled_bytes": sum(int(item.get("size", 0) or 0) for item in selected),
        "statuses": dict(sorted(statuses.items())),
        "failed_files": failures,
        "exact_grim_units": len(exact_units),
        "winning_exact_grim_units": len(winning_units),
        "winning_mirror_units": sum(bool(unit["opponent_exact_grim"]) for unit in winning_units),
        "winning_seat_counts": dict(sorted(Counter(str(unit["seat"]) for unit in winning_units).items())),
        "teams": len({str(unit["team"]) for unit in exact_units}),
        "decisions": len(rows),
        "deck": str(Path(args.deck).resolve()),
        "deck_sha256": sha256_file(args.deck),
        "output": str(output),
        "output_sha256": sha256_file(output),
        "raw_episodes_retained": 0,
        "sampled_filenames": [str(item["name"]) for item in selected],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="2026-08-03")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20260804)
    parser.add_argument("--deck", default=str(DEFAULT_DECK))
    parser.add_argument("--output", default="artifacts/daily_grim_20260803_pilot/winning_decisions.jsonl.gz")
    parser.add_argument("--manifest", default="artifacts/daily_grim_20260803_pilot/manifest.json")
    parser.add_argument(
        "--exclude-manifest",
        action="append",
        default=[],
        help="skip sampled_filenames recorded by an earlier mining manifest",
    )
    args = parser.parse_args()
    if args.limit <= 0:
        parser.error("--limit must be positive for bounded streaming")
    if args.workers <= 0:
        parser.error("--workers must be positive")

    dataset = f"kaggle/pokemon-tcg-ai-battle-episodes-{args.date}"
    listing = list_episode_files(dataset)
    excluded_files = set()
    for path in args.exclude_manifest:
        excluded_files.update(json.loads(Path(path).read_text()).get("sampled_filenames", []))
    listing = [item for item in listing if str(item.get("name", "")) not in excluded_files]
    rng = random.Random(args.seed)
    selected = list(listing)
    rng.shuffle(selected)
    selected = selected[: min(args.limit, len(selected))]
    grim_signature = load_deck(args.deck)

    results = []
    with tempfile.TemporaryDirectory(prefix="daily-grim-") as temporary:
        temporary_root = Path(temporary)
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [
                pool.submit(download_and_mine, dataset, args.date, item, temporary_root, grim_signature)
                for item in selected
            ]
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())
                done = len(results)
                if done % 25 == 0 or done == len(selected):
                    counts = Counter(result["status"] for result in results)
                    print({"complete": done, "total": len(selected), **dict(counts)}, flush=True)

    manifest = write_outputs(args, dataset, listing, selected, results)
    print(json.dumps({key: manifest[key] for key in (
        "sampled_files", "sampled_bytes", "statuses", "exact_grim_units",
        "winning_exact_grim_units", "winning_mirror_units", "decisions",
        "raw_episodes_retained", "output",
    )}, indent=2, sort_keys=True))
    return 1 if manifest["failed_files"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

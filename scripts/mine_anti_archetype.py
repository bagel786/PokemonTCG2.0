#!/usr/bin/env python3
"""Mine winner-side Grimmsnarl decisions from real games against ladder Lucario/Iono opponents.

Sources, in order:
1. Every replay already cached under --replay-root (no network).
2. Optionally (--fetch), episodes of the known Lucario ladder submissions and the
   audited Bellibolt episodes — games those opponents LOST to a Grimmsnarl deck
   are demonstrations of correct anti-archetype play by any team.

A row is kept when: seat deck == Grimmsnarl signature, that seat won, and the
opposing seat deck matches a target archetype signature.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
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
from scripts.fetch_active_subs import download_one, fetch_episodes  # noqa: E402
from training.lucario_data import canonical_deck, deterministic_gzip_text, load_deck, sha256_file  # noqa: E402

GRIM_DECK = ROOT / "freshstart/decklists/grimmsnarl_marnie.deck.csv"
TARGET_DECKS = {
    "mega_lucario_ex": ROOT / "freshstart/decklists/mega_lucario_ex.deck.csv",
    "mega_lucario_ex_variant_2": ROOT / "freshstart/decklists/mega_lucario_ex_variant_2.deck.csv",
    "iono_bellibolt_ex": ROOT / "freshstart/decklists/iono_bellibolt_ex.deck.csv",
}


def seat_decks(episode: dict) -> list[tuple[int, ...]]:
    steps = episode.get("steps", [])
    if len(steps) < 2:
        return []
    return [canonical_deck(steps[1][seat].get("action", []) if len(steps[1]) > seat else []) for seat in (0, 1)]


def mine_episode(path: Path, grim_signature: tuple[int, ...], targets: dict[tuple[int, ...], str]) -> tuple[list[dict], str | None]:
    """Return (rows, matched_archetype) for the Grim-winner seat, if any."""
    try:
        episode = load_episode(path)
    except Exception:
        return [], None
    decks = seat_decks(episode)
    if len(decks) != 2:
        return [], None
    names = episode.get("info", {}).get("TeamNames", ["seat_0", "seat_1"])
    for seat in (0, 1):
        opponent = decks[1 - seat]
        if decks[seat] != grim_signature or opponent not in targets:
            continue
        if episode_reward(episode, seat) != 1.0:
            continue
        team = names[seat] if len(names) > seat else f"seat_{seat}"
        rows = []
        for record in iter_decisions(episode, {team}, feature_version=2):
            row = record.to_json()
            if int(row.get("seat", -1)) != seat:
                continue
            row["opponent_archetype"] = targets[opponent]
            rows.append(row)
        return rows, targets[opponent]
    return [], None


def local_replays(root: Path):
    yield from sorted(root.rglob("episode-*-replay.json"))
    yield from sorted(root.rglob("[0-9]*.json"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-root", default="data/replays")
    parser.add_argument("--output", default="artifacts/anti_archetype_20260804/anti_lucario_iono.jsonl.gz")
    parser.add_argument("--manifest", default="artifacts/anti_archetype_20260804/manifest.json")
    parser.add_argument("--fetch", action="store_true", help="also fetch Lucario-submission and Bellibolt episodes")
    parser.add_argument("--lucario-acquisition", default="artifacts/lucario_gap_20260803/data/acquisition.json")
    parser.add_argument("--bellibolt-manifest", default="artifacts/bellibolt_bootstrap_20260803/data/manifest.json")
    parser.add_argument("--max-episodes-per-submission", type=int, default=8)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--request-delay", type=float, default=1.0)
    args = parser.parse_args()

    grim_signature = load_deck(GRIM_DECK)
    targets = {load_deck(path): name for name, path in TARGET_DECKS.items() if path.exists()}

    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    seen_units: set[tuple[str, int]] = set()
    seen_rows: set[tuple[str, int, int]] = set()
    games = Counter()
    decisions = Counter()
    all_rows: list[dict] = []

    def consume(rows: list[dict], archetype: str | None, source: str) -> None:
        if not rows or archetype is None:
            return
        unit = (str(rows[0]["episode_id"]), int(rows[0]["seat"]))
        if unit in seen_units:
            return
        seen_units.add(unit)
        kept = 0
        for row in rows:
            key = (str(row["episode_id"]), int(row["seat"]), int(row["step"]))
            if key in seen_rows:
                continue
            seen_rows.add(key)
            row["source"] = source
            all_rows.append(row)
            kept += 1
        games[archetype] += 1
        decisions[archetype] += kept

    # Pass 1: everything already on disk.
    for path in local_replays(ROOT / args.replay_root):
        rows, archetype = mine_episode(path, grim_signature, targets)
        consume(rows, archetype, "local_cache")

    # Pass 2: bounded fetch of opponent-submission episodes (their losses to Grim decks).
    fetch_failures = 0
    if args.fetch:
        episode_ids: set[int] = set()
        acquisition = ROOT / args.lucario_acquisition
        if acquisition.exists():
            for submission in json.loads(acquisition.read_text()).get("discovered_submissions", []):
                try:
                    listed = fetch_episodes(int(submission))
                except Exception:
                    fetch_failures += 1
                    continue
                ordered = sorted(listed, key=lambda row: str(row.get("createTime", "")))
                for row in ordered[-args.max_episodes_per_submission:]:
                    if "id" in row:
                        episode_ids.add(int(row["id"]))
        bellibolt = ROOT / args.bellibolt_manifest
        if bellibolt.exists():
            for unit in json.loads(bellibolt.read_text()).get("episode_assignments", {}):
                episode_ids.add(int(str(unit).split(":")[0]))

        with tempfile.TemporaryDirectory(prefix="anti-archetype-") as temporary:
            download_dir = Path(temporary)

            def paced(episode_id: int):
                result = download_one(episode_id, download_dir)
                time.sleep(max(0.0, args.request_delay))
                return result

            pending = sorted(episode_ids)
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
                for episode_id, status in pool.map(paced, pending):
                    if str(status).startswith("failed"):
                        fetch_failures += 1
                        continue
                    path = download_dir / f"episode-{episode_id}-replay.json"
                    if not path.exists():
                        path = download_dir / f"{episode_id}.json"
                    if not path.exists():
                        fetch_failures += 1
                        continue
                    rows, archetype = mine_episode(path, grim_signature, targets)
                    consume(rows, archetype, "fetched")
                    path.unlink(missing_ok=True)

    with deterministic_gzip_text(output.with_name(output.name + ".tmp")) as handle:
        for row in all_rows:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    (output.with_name(output.name + ".tmp")).replace(output)

    manifest = {
        "version": 1,
        "grim_deck": str(GRIM_DECK),
        "target_archetypes": sorted(TARGET_DECKS),
        "winner_side_games": dict(games),
        "decisions": dict(decisions),
        "total_games": sum(games.values()),
        "total_decisions": sum(decisions.values()),
        "fetch_enabled": bool(args.fetch),
        "fetch_failures": fetch_failures,
        "output": str(output),
        "output_sha256": sha256_file(output),
    }
    manifest_path = ROOT / args.manifest
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

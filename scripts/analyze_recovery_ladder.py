#!/usr/bin/env python3
"""Download and analyze every rated replay for recovery submissions."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.crawl_grim_daily import classify, load_archetype_catalog


def card_catalog() -> tuple[dict[int, str], set[int]]:
    path = ROOT / "freshstart" / "data" / "EN_Card_Data.csv"
    names, pokemon = {}, set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            card_id = int(row["Card ID"])
            names[card_id] = row["Card Name"]
            stage_key = next((key for key in row if key.startswith("Stage (Pok")), "")
            stage = row.get(stage_key, "")
            if "Pokémon" in stage:
                pokemon.add(card_id)
    return names, pokemon


def deck_hash(deck: list[int]) -> str:
    payload = json.dumps(sorted(int(card) for card in deck), separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest().upper()


def pokemon_signature(deck: list[int], names: dict[int, str], pokemon: set[int]) -> list[str]:
    counts = Counter(int(card) for card in deck if int(card) in pokemon)
    return [f"{names.get(card, str(card))} x{count}" for card, count in counts.most_common(8)]


def final_state(replay: dict, hero_seat: int) -> dict:
    first_player = None
    last = None
    for step in replay.get("steps", []):
        for agent in step:
            current = (agent.get("observation") or {}).get("current")
            if not isinstance(current, dict):
                continue
            if first_player in (None, -1) and current.get("firstPlayer") not in (None, -1):
                first_player = int(current["firstPlayer"])
            if len(current.get("players", [])) == 2:
                last = current
    if last is None:
        raise ValueError("replay contains no complete public game state")
    hero = last["players"][hero_seat]
    opponent = last["players"][1 - hero_seat]
    hero_prizes = len(hero.get("prize") or [])
    opponent_prizes = len(opponent.get("prize") or [])
    hero_board = len([card for card in (hero.get("active") or []) + (hero.get("bench") or []) if card])
    return {
        "turn": int(last.get("turn", 0)),
        "went_first": first_player == hero_seat,
        "hero_prizes_taken": 6 - hero_prizes,
        "opponent_prizes_taken": 6 - opponent_prizes,
        "hero_board_at_end": hero_board,
        "hero_deck_at_end": int(hero.get("deckCount", 0)),
    }


def loss_shape(row: dict) -> str:
    if row["outcome"] > 0:
        return "win"
    if row["hero_board_at_end"] == 0 and row["turn"] <= 3:
        return "early_bench_extinction"
    if row["hero_board_at_end"] == 0:
        return "bench_extinction"
    if row["hero_deck_at_end"] == 0:
        return "deck_out"
    if row["opponent_prizes_taken"] >= 6:
        return "prize_race"
    return "other_terminal_loss"


def bucket(rows: list[dict]) -> dict:
    games = len(rows)
    wins = sum(row["outcome"] > 0 for row in rows)
    seats = {}
    for seat in (0, 1):
        subset = [row for row in rows if row["seat"] == seat]
        seat_wins = sum(row["outcome"] > 0 for row in subset)
        seats[str(seat)] = {
            "games": len(subset),
            "wins": seat_wins,
            "win_rate": seat_wins / len(subset) if subset else None,
        }
    return {
        "games": games,
        "wins": wins,
        "losses": games - wins,
        "win_rate": wins / games if games else None,
        "seat_results": seats,
        "loss_shapes": dict(sorted(Counter(row["loss_shape"] for row in rows if row["outcome"] <= 0).items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", default="artifacts/recovery_probes/submission_ledger.json")
    parser.add_argument("--ladder-dir", default="artifacts/recovery_ladder")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    ledger = json.loads((ROOT / args.ledger).read_text())
    ladder = ROOT / args.ladder_dir
    replay_root = ladder / "replays"
    replay_root.mkdir(parents=True, exist_ok=True)

    from kaggle.api.kaggle_api_extended import KaggleApi

    api = KaggleApi()
    api.authenticate()
    jobs = []
    submission_games = {}
    for submission in ledger["submissions"]:
        sid = str(submission["submission_id"])
        games = json.loads((ladder / "games" / f"{sid}.json").read_text())
        submission_games[sid] = (submission, games)
        target = replay_root / sid
        target.mkdir(parents=True, exist_ok=True)
        for game in games:
            path = target / f"episode-{game['episode_id']}-replay.json"
            if not path.exists():
                jobs.append((int(game["episode_id"]), target, path))

    def download(job: tuple[int, Path, Path]) -> str:
        episode_id, target, expected = job
        for attempt in range(8):
            try:
                api.competition_episode_replay(episode_id, path=str(target), quiet=True)
                break
            except Exception as exc:
                if "429" not in str(exc) or attempt == 7:
                    raise
                time.sleep(min(60, 2 ** (attempt + 1)))
        if not expected.exists() or expected.stat().st_size == 0:
            raise RuntimeError(f"missing replay after download: {episode_id}")
        return str(expected)

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        list(pool.map(download, jobs))

    names, pokemon = card_catalog()
    archetypes = load_archetype_catalog(ROOT / "freshstart" / "decklists")
    reports = {}
    for sid, (submission, games) in submission_games.items():
        rows = []
        for game in games:
            replay_path = replay_root / sid / f"episode-{game['episode_id']}-replay.json"
            replay = json.loads(replay_path.read_text(encoding="utf-8"))
            seat = int(game["seat"])
            steps = replay.get("steps", [])
            if len(steps) < 2 or len(steps[1]) != 2:
                raise RuntimeError(f"replay has no setup deck action: {game['episode_id']}")
            opponent_deck = steps[1][1 - seat].get("action")
            if not isinstance(opponent_deck, list) or len(opponent_deck) != 60:
                raise RuntimeError(f"opponent deck is not a complete 60-card list: {game['episode_id']}")
            state = final_state(replay, seat)
            row = {
                **game,
                **state,
                "opponent_deck_hash": deck_hash(opponent_deck),
                "opponent_archetype": classify(tuple(sorted(opponent_deck)), archetypes),
                "opponent_pokemon": pokemon_signature(opponent_deck, names, pokemon),
            }
            row["loss_shape"] = loss_shape(row)
            rows.append(row)
        rows.sort(key=lambda row: (row["created_unix"], row["episode_id"]))
        by_archetype = {name: bucket(group) for name, group in sorted(
            ((name, [row for row in rows if row["opponent_archetype"] == name])
             for name in {row["opponent_archetype"] for row in rows}),
            key=lambda item: (-len(item[1]), item[0]),
        )}
        by_deck = {}
        for signature in sorted({row["opponent_deck_hash"] for row in rows}):
            group = [row for row in rows if row["opponent_deck_hash"] == signature]
            by_deck[signature] = {
                **bucket(group),
                "archetype": group[0]["opponent_archetype"],
                "pokemon": group[0]["opponent_pokemon"],
            }
        report = {
            "submission_id": int(sid),
            "name": submission["name"],
            "overall": bucket(rows),
            "first_loss_game": next((i + 1 for i, row in enumerate(rows) if row["outcome"] <= 0), None),
            "recent_10": bucket(rows[-10:]),
            "by_archetype": by_archetype,
            "by_exact_deck": by_deck,
            "games": rows,
        }
        output = ladder / f"analysis_{sid}.json"
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        reports[sid] = report
    summary = {
        sid: {
            "name": report["name"],
            "overall": report["overall"],
            "first_loss_game": report["first_loss_game"],
            "recent_10": report["recent_10"],
            "by_archetype": report["by_archetype"],
        }
        for sid, report in reports.items()
    }
    (ladder / "analysis_latest.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"downloaded": len(jobs), "submissions": {
        sid: {"games": report["overall"]["games"], "win_rate": report["overall"]["win_rate"],
              "archetypes": len(report["by_archetype"])} for sid, report in reports.items()
    }}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

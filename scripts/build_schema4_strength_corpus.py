#!/usr/bin/env python3
"""Assemble A2-anchor and elite schema-4 streams for R0/R1 training."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
import zlib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.replay import iter_decisions, load_episode
from training.lucario_data import deterministic_gzip_text, sha256_file

HOLDOUT_SUBMISSIONS = {55308008, 55312662}


def deck_hash(cards) -> str:
    canonical = tuple(sorted(int(card) for card in cards))
    return hashlib.sha256(",".join(map(str, canonical)).encode()).hexdigest()


def is_multi_play(row: dict) -> bool:
    options = row["features"]["options"]
    return bool(options) and int(options[0]["context"]) == 0 and sum(
        int(option["option_type"]) == 7 for option in options
    ) >= 2


def load_jsonl(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line)


def a2_rows(replay_root: Path, games_path: Path) -> list[dict]:
    games = {str(row["episode_id"]): row for row in json.loads(games_path.read_text(encoding="utf-8"))}
    rows = []
    for replay in sorted(replay_root.glob("episode-*-replay.json")):
        episode = load_episode(replay)
        episode_id = str((episode.get("info") or {}).get("EpisodeId"))
        game = games.get(episode_id)
        if game is None:
            raise RuntimeError(f"A2 replay has no game metadata: {episode_id}")
        seat = int(game["seat"])
        steps = episode.get("steps") or []
        if len(steps) < 2:
            raise RuntimeError(f"A2 replay has no deck handshake: {episode_id}")
        decks = [steps[1][index].get("action") or [] for index in range(2)]
        for decision in iter_decisions(episode, feature_version=4):
            if decision.seat != seat:
                continue
            row = decision.to_json()
            row.update({
                "source": "a2_live_anchor",
                "objective_source": "a2_anchor",
                "source_submission_id": 55323436,
                "opponent_submission_id": game.get("opponent_submission_id"),
                "opponent_team": game.get("opponent_team_name"),
                "opponent_score_snapshot": None,
                "hero_deck_sha256": deck_hash(decks[seat]),
                "opponent_deck_sha256": deck_hash(decks[1 - seat]),
            })
            rows.append(row)
    return rows


def weighted(rows: list[dict], source_share: float) -> list[dict]:
    if not rows:
        return rows
    scale = source_share / len(rows)
    for row in rows:
        row["sample_weight"] = scale
    return rows


def write_stream(path: Path, rows: list[dict]) -> dict:
    ordered = sorted(rows, key=lambda row: (
        str(row.get("episode_id")), int(row.get("seat", 0)), int(row.get("step", 0)),
        str(row.get("objective_source", "")),
    ))
    with deterministic_gzip_text(path) as handle:
        for row in ordered:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    return {"path": str(path.resolve()), "rows": len(ordered), "sha256": sha256_file(path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elite-root", default="artifacts/live_grim_corpus_v4")
    parser.add_argument("--a2-replays", default="artifacts/recovery_ladder/replays/55323436")
    parser.add_argument("--a2-games", default="artifacts/recovery_ladder/games/55323436.json")
    parser.add_argument("--output-root", default="data/grim_strength_v4")
    args = parser.parse_args()

    elite_root = ROOT / args.elite_root
    output = ROOT / args.output_root
    output.mkdir(parents=True, exist_ok=True)
    anchors = a2_rows(ROOT / args.a2_replays, ROOT / args.a2_games)
    elite_train = []
    elite_holdout = []
    for path in sorted(elite_root.glob("submission_*.jsonl.gz")):
        submission_id = int(path.stem.split("_")[1].split(".")[0])
        for row in load_jsonl(path):
            if float(row["reward"]) <= 0:
                continue
            row["objective_source"] = "elite_demo"
            if submission_id in HOLDOUT_SUBMISSIONS:
                elite_holdout.append(row)
            else:
                elite_train.append(row)

    anchor_train, anchor_validation = [], []
    for row in anchors:
        bucket = zlib.crc32(str(row["episode_id"]).encode()) % 10
        (anchor_validation if bucket == 0 else anchor_train).append(row)
    elite_validation = []
    remaining_elite = []
    for row in elite_train:
        bucket = zlib.crc32(str(row["episode_id"]).encode()) % 10
        (elite_validation if bucket == 0 else remaining_elite).append(row)
    elite_train = remaining_elite

    streams = {}
    for mode, predicate in (("r0", is_multi_play), ("r1", lambda _row: True)):
        train_anchor = weighted([dict(row) for row in anchor_train if predicate(row)], 0.60 if mode == "r0" else 0.50)
        train_elite = weighted([dict(row) for row in elite_train if predicate(row)], 0.40 if mode == "r0" else 0.25)
        validation = [dict(row) for row in anchor_validation + elite_validation if predicate(row)]
        holdout = [dict(row) for row in elite_holdout if predicate(row)]
        for row in validation:
            row["split"] = "validation"
            row["sample_weight"] = 1.0
        for row in holdout:
            row["split"] = "holdout"
            row["sample_weight"] = 1.0
        for row in train_anchor + train_elite:
            row["split"] = "train"
        streams[mode] = {
            "train": write_stream(output / f"{mode}_train.jsonl.gz", train_anchor + train_elite),
            "validation": write_stream(output / f"{mode}_validation.jsonl.gz", validation),
            "policy_holdout": write_stream(output / f"{mode}_policy_holdout.jsonl.gz", holdout),
            "source_counts": dict(Counter(row["objective_source"] for row in train_anchor + train_elite)),
        }
    manifest = {
        "status": "complete",
        "feature_version": 4,
        "a2_submission_id": 55323436,
        "heldout_submission_ids": sorted(HOLDOUT_SUBMISSIONS),
        "split_unit": "whole_episode_and_source_submission",
        "training_mix": {
            "r0": {"a2_anchor": 0.60, "elite_demo": 0.40},
            "r1_without_corrections": {"a2_anchor": 0.50, "elite_demo": 0.25, "reserved_corrections": 0.25},
        },
        "streams": streams,
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

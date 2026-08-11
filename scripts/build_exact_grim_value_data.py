#!/usr/bin/env python3
"""Build date-separated public-observation value rows from exact-Grim replays."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.replay import iter_decisions, load_episode


DEFAULT_MANIFEST = ROOT / "artifacts" / "grim_5k_history" / "manifest.partial.json"
DEFAULT_DECK = ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv"
DEFAULT_OUTPUT = ROOT / "artifacts" / "emergency_strength_sprint" / "exact_grim_public_value"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_deck(cards) -> tuple[int, ...]:
    return tuple(sorted(int(card) for card in cards))


def split_for_date(date: str, validation_date: str, holdout_date: str) -> str:
    if date == holdout_date:
        return "holdout"
    if date == validation_date:
        return "validation"
    if date < validation_date:
        return "train"
    raise ValueError(f"date {date} is after validation but is not holdout")


def _opponent_hand_is_hidden(episode: dict, seat: int) -> bool:
    for step in episode.get("steps") or []:
        if seat >= len(step):
            continue
        row = step[seat]
        if str(row.get("status", "")).upper() != "ACTIVE":
            continue
        observation = row.get("observation") or {}
        current = observation.get("current") or {}
        players = current.get("players") or []
        if len(players) != 2:
            continue
        opponent_hand = players[1 - seat].get("hand")
        if opponent_hand is not None:
            return False
    return True


def build(args: argparse.Namespace) -> dict:
    manifest_path = Path(args.manifest).resolve()
    deck_path = Path(args.deck).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    expected_deck = canonical_deck(
        int(line.strip()) for line in deck_path.read_text().splitlines() if line.strip()
    )
    if len(expected_deck) != 60:
        raise ValueError("expected exact Grim deck must contain 60 cards")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources = []
    for submission in manifest.get("submissions", []):
        if submission.get("deck_class") != "exact_original_grim":
            continue
        submission_id = int(submission["submission_id"])
        for episode_row in submission.get("episodes", []):
            date = str(episode_row.get("created_utc", ""))[:10]
            split = split_for_date(date, args.validation_date, args.holdout_date)
            sources.append((date, int(episode_row["episode_id"]), submission_id, split, episode_row))
    sources.sort(key=lambda item: (item[0], item[1], item[2]))
    if not sources:
        raise ValueError("manifest contains no exact-original-Grim episodes")

    paths = {name: output_dir / f"{name}.jsonl.gz" for name in ("train", "validation", "holdout")}
    handles = {
        name: gzip.open(path, "wt", encoding="utf-8", compresslevel=6)
        for name, path in paths.items()
    }
    counts = Counter()
    episodes_by_split = {name: set() for name in handles}
    trajectories: dict[tuple[str, int], float] = {}
    try:
        for date, declared_episode_id, submission_id, split, episode_row in sources:
            replay_path = Path(episode_row["replay"]).resolve()
            episode = load_episode(replay_path)
            info = episode.get("info") or {}
            episode_id = int(info.get("EpisodeId", declared_episode_id))
            if episode_id != declared_episode_id:
                raise ValueError(f"episode id mismatch for {replay_path}")
            seat = int(episode_row["seat"])
            expected_reward = float(float(episode_row["outcome"]) > 0.0)
            if not _opponent_hand_is_hidden(episode, seat):
                raise ValueError(f"hidden opponent hand exposed in episode {episode_id} seat {seat}")
            decisions = [
                decision
                for decision in iter_decisions(episode, feature_version=3, include_observation=False)
                if decision.seat == seat
            ]
            if not decisions:
                raise ValueError(f"no aligned hero decisions in episode {episode_id} seat {seat}")
            if canonical_deck(decisions[0].deck) != expected_deck:
                raise ValueError(f"exact deck mismatch in episode {episode_id} seat {seat}")
            replay_sha256 = sha256_file(replay_path)
            unit = (str(episode_id), seat)
            if unit in trajectories:
                raise ValueError(f"duplicate trajectory {unit}")
            trajectories[unit] = expected_reward
            episodes_by_split[split].add(str(episode_id))
            counts[f"{split}_trajectories"] += 1
            counts[f"{split}_{'wins' if expected_reward else 'losses'}"] += 1
            for decision in decisions:
                if float(decision.reward) != expected_reward:
                    raise ValueError(f"outcome mismatch in episode {episode_id} seat {seat}")
                features = decision.features
                row = {
                    "episode_id": str(episode_id),
                    "submission_id": submission_id,
                    "seat": seat,
                    "step": int(decision.step),
                    "turn": int(decision.turn),
                    "source_date": date,
                    "split": split,
                    "deck": list(decision.deck),
                    "reward": 1.0 if expected_reward else -1.0,
                    "features": {
                        "feature_version": 3,
                        "global": features["global"],
                        "tokens": features["tokens"],
                    },
                    "source_replay_sha256": replay_sha256,
                }
                handles[split].write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")
                counts[f"{split}_rows"] += 1
    finally:
        for handle in handles.values():
            handle.close()

    for left, right in (("train", "validation"), ("train", "holdout"), ("validation", "holdout")):
        overlap = episodes_by_split[left] & episodes_by_split[right]
        if overlap:
            raise AssertionError(f"episode split leakage: {left}/{right}")
    result = {
        "status": "complete",
        "source_manifest": str(manifest_path),
        "source_manifest_sha256": sha256_file(manifest_path),
        "deck": str(deck_path),
        "deck_sha256": sha256_file(deck_path),
        "feature_version": 3,
        "split_rule": {
            "train": f"source_date < {args.validation_date}",
            "validation": f"source_date == {args.validation_date}",
            "holdout": f"source_date == {args.holdout_date}",
            "unit": "whole episode (both seats co-located if both ever appear)",
        },
        "opponent_hidden_hand_audit": "passed_all_active_hero_observations",
        "counts": dict(sorted(counts.items())),
        "episode_overlap": {"train_validation": 0, "train_holdout": 0, "validation_holdout": 0},
        "outputs": {
            name: {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}
            for name, path in paths.items()
        },
    }
    (output_dir / "manifest.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--deck", default=str(DEFAULT_DECK))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--validation-date", default="2026-08-08")
    parser.add_argument("--holdout-date", default="2026-08-09")
    args = parser.parse_args()
    if args.validation_date >= args.holdout_date:
        raise ValueError("validation date must precede holdout date")
    result = build(args)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

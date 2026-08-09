#!/usr/bin/env python3
"""Build policy streams from strong live exact-Grim submissions."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.replay import iter_decisions, load_episode
from training.lucario_data import deterministic_gzip_text, sha256_file

DEFAULT_SUBMISSIONS = "55327371,55325981,55308008,55312662,55321109,55316998"


def exact_deck(path: Path) -> tuple[int, ...]:
    cards = tuple(sorted(int(line.strip()) for line in path.read_text().splitlines() if line.strip()))
    if len(cards) != 60:
        raise ValueError(f"expected an exact 60-card deck: {path}")
    return cards


def deck_sha256(cards) -> str:
    canonical = tuple(sorted(int(card) for card in cards))
    return hashlib.sha256(",".join(map(str, canonical)).encode()).hexdigest()


def leaderboard_scores(path: Path | None) -> dict[str, float]:
    if path is None or not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return {row["TeamName"]: float(row["Score"]) for row in csv.DictReader(handle)}


def with_backoff(call):
    last_error = None
    for attempt in range(8):
        try:
            return call()
        except Exception as exc:
            last_error = exc
            if attempt == 7:
                break
            time.sleep(min(60, 2 ** (attempt + 1)))
    raise last_error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submissions", default=DEFAULT_SUBMISSIONS)
    parser.add_argument("--opponent-report", default="artifacts/recovery_ladder/live_grim_opponents.json")
    parser.add_argument("--deck", default="freshstart/decklists/grimmsnarl_marnie.deck.csv")
    parser.add_argument("--output-dir", default="artifacts/live_grim_corpus_v5")
    parser.add_argument("--replay-source", default="artifacts/live_grim_corpus_v4/replays")
    parser.add_argument("--feature-version", type=int, choices=(4, 5), default=5)
    parser.add_argument("--leaderboard")
    parser.add_argument("--team-overrides", default="{}", help="JSON submission-id to public team name")
    parser.add_argument("--team-name", help="public team name when every selected submission belongs to one team")
    parser.add_argument("--allow-grim-variant", action="store_true")
    args = parser.parse_args()
    submission_ids = [int(value) for value in args.submissions.split(",") if value.strip()]
    if len(submission_ids) != len(set(submission_ids)) or not submission_ids:
        raise ValueError("submissions must be a nonempty unique list")
    opponent_rows = {
        int(row["sid"]): row for row in json.loads((ROOT / args.opponent_report).read_text(encoding="utf-8"))
    }
    overrides = {int(key): str(value) for key, value in json.loads(args.team_overrides).items()}
    if args.team_name:
        overrides.update({submission_id: args.team_name for submission_id in submission_ids})
    missing = sorted(set(submission_ids) - set(opponent_rows) - set(overrides))
    if missing:
        raise ValueError(f"selected submissions are absent from the live opponent report: {missing}")
    expected_deck = exact_deck(ROOT / args.deck)
    if args.leaderboard:
        leaderboard_path = Path(args.leaderboard)
    else:
        candidates = sorted((ROOT / ".codex_tmp" / "ladder_forensics" / "unzipped").glob("*publicleaderboard*.csv"))
        leaderboard_path = candidates[-1] if candidates else None
    scores = leaderboard_scores(leaderboard_path)
    score_snapshot = leaderboard_path.name if leaderboard_path is not None else None
    output = ROOT / args.output_dir
    replay_root = output / "replays"
    replay_root.mkdir(parents=True, exist_ok=True)

    from kaggle.api.kaggle_api_extended import KaggleApi

    api = KaggleApi()
    api.authenticate()
    existing_replays = {}
    for path in (ROOT / args.replay_source).glob("*/episode-*-replay.json"):
        existing_replays[path.name] = path
    for path in (ROOT / "artifacts" / "recovery_ladder" / "replays").glob("*/episode-*-replay.json"):
        existing_replays[path.name] = path

    stream_paths, manifest = [], {}
    seen_decisions = set()
    for submission_id in submission_ids:
        target = replay_root / str(submission_id)
        target.mkdir(parents=True, exist_ok=True)
        metadata = []
        episodes = with_backoff(lambda: api.competition_list_episodes(submission_id))
        for episode in sorted(episodes, key=lambda row: row.create_time):
            own = [agent for agent in episode.agents if int(agent.submission_id) == submission_id]
            if len(own) != 1:
                continue
            metadata.append((episode, int(own[0].index), float(own[0].reward)))

        stream = output / f"submission_{submission_id}.jsonl.gz"
        temporary = stream.with_name(stream.name + ".tmp")
        game_count = win_count = decision_count = winning_decisions = 0
        with deterministic_gzip_text(temporary) as handle:
            for episode, seat, reward in metadata:
                replay = target / f"episode-{episode.id}-replay.json"
                if not replay.exists() and replay.name in existing_replays:
                    shutil.copy2(existing_replays[replay.name], replay)
                if not replay.exists():
                    with_backoff(lambda: api.competition_episode_replay(int(episode.id), path=str(target), quiet=True))
                episode_data = load_episode(replay)
                steps = episode_data.get("steps") or []
                deck = tuple(sorted(int(card) for card in (steps[1][seat].get("action") or []))) if len(steps) > 1 else ()
                if deck != expected_deck and not (args.allow_grim_variant and 648 in deck):
                    raise RuntimeError(
                        f"submission {submission_id} replay {episode.id} did not use the exact current Grim deck"
                    )
                game_count += 1
                win_count += reward > 0
                info = episode_data.get("info") or {}
                teams = info.get("TeamNames") or [f"seat-{index}" for index in range(2)]
                opponent_agents = [agent for agent in episode.agents if int(agent.index) != seat]
                opponent_submission_id = int(opponent_agents[0].submission_id) if len(opponent_agents) == 1 else None
                opponent_deck = tuple(sorted(int(card) for card in (steps[1][1 - seat].get("action") or [])))
                for decision in iter_decisions(
                    episode_data,
                    feature_version=args.feature_version,
                    include_observation=False,
                ):
                    if decision.seat != seat:
                        continue
                    key = (str(decision.episode_id), decision.seat, decision.step)
                    if key in seen_decisions:
                        raise RuntimeError(f"duplicate live decision: {key}")
                    seen_decisions.add(key)
                    row = decision.to_json()
                    row.update({
                        "source": "kaggle_live_submission",
                        "source_submission_id": submission_id,
                        "source_team": overrides.get(submission_id, opponent_rows.get(submission_id, {}).get("team")),
                        "behavior_archetype": f"live_grim_{submission_id}",
                        "hero_deck_sha256": deck_sha256(deck),
                        "opponent_deck_sha256": deck_sha256(opponent_deck),
                        "opponent_submission_id": opponent_submission_id,
                        "opponent_team": teams[1 - seat],
                        "opponent_score_snapshot": scores.get(teams[1 - seat]),
                        "score_snapshot_source": score_snapshot,
                    })
                    handle.write(json.dumps(row, separators=(",", ":")) + "\n")
                    decision_count += 1
                    winning_decisions += float(row["reward"]) > 0
        temporary.replace(stream)
        stream_paths.append(stream)
        manifest[str(submission_id)] = {
            "team": overrides.get(submission_id, opponent_rows.get(submission_id, {}).get("team")),
            "public_games": game_count,
            "public_wins": win_count,
            "public_win_rate": win_count / game_count,
            "decisions": decision_count,
            "winning_decisions": winning_decisions,
            "stream": str(stream),
            "stream_sha256": sha256_file(stream),
        }

    for name, winning_only in (("combined_all", False), ("combined_winning", True)):
        path = output / f"{name}.jsonl.gz"
        row_count = 0
        with deterministic_gzip_text(path) as handle:
            for stream in stream_paths:
                with gzip.open(stream, "rt", encoding="utf-8") as source:
                    for line in source:
                        if winning_only and float(json.loads(line)["reward"]) <= 0:
                            continue
                        handle.write(line)
                        row_count += 1
        manifest[name] = {"rows": row_count, "path": str(path), "sha256": sha256_file(path)}
    manifest["exact_deck"] = {"path": args.deck, "cards": len(expected_deck)}
    manifest["allow_grim_variant"] = bool(args.allow_grim_variant)
    manifest["feature_version"] = args.feature_version
    manifest["score_snapshot_source"] = score_snapshot
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({
        "submissions": len(submission_ids),
        "games": sum(row["public_games"] for row in manifest.values() if isinstance(row, dict) and "public_games" in row),
        "decisions": manifest["combined_all"]["rows"],
        "winning_decisions": manifest["combined_winning"]["rows"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

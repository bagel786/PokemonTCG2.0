#!/usr/bin/env python3
"""Append Kaggle rating snapshots and apply the conservative ladder policy."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from training.ladder_policy import assess_ladder

COMPETITION = "pokemon-tcg-ai-battle"


def episode_games(api, submission_id: int) -> tuple[list[dict], int]:
    """Return chronological rated episodes and the excluded self-play count."""
    games = []
    excluded_self_play = 0
    for episode in api.competition_list_episodes(submission_id):
        matching = [agent for agent in episode.agents if int(agent.submission_id) == submission_id]
        if len(matching) != 1:
            if len(matching) == 2:
                excluded_self_play += 1
                continue
            raise RuntimeError(
                f"episode {episode.id} does not identify submission {submission_id} exactly once"
            )
        agent = matching[0]
        opponents = [other for other in episode.agents if int(other.submission_id) != submission_id]
        if len(opponents) != 1:
            raise RuntimeError(f"episode {episode.id} does not contain exactly one opponent")
        opponent = opponents[0]
        created = episode.create_time
        if created.tzinfo is None:
            created = created.replace(tzinfo=dt.timezone.utc)
        state = str(agent.state)
        games.append({
            "episode_id": int(episode.id),
            "created_unix": created.timestamp(),
            "created_utc": created.isoformat(),
            "seat": int(agent.index),
            "outcome": float(agent.reward),
            "agent_state": state,
            "crash": "ERROR" in state or "INVALID" in state,
            "opponent_submission_id": int(opponent.submission_id),
            "opponent_team_id": int(opponent.team_id),
            "opponent_team_name": str(opponent.team_name),
        })
    games.sort(key=lambda game: (game["created_unix"], game["episode_id"]))
    ids = [game["episode_id"] for game in games]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"duplicate episode IDs returned for submission {submission_id}")
    return games, excluded_self_play


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", default="artifacts/recovery_probes/submission_ledger.json")
    parser.add_argument("--games-dir", default="artifacts/recovery_ladder/games")
    parser.add_argument("--output-dir", default="artifacts/recovery_ladder")
    args = parser.parse_args()
    ledger = json.loads(Path(args.ledger).read_text())
    from kaggle.api.kaggle_api_extended import KaggleApi

    api = KaggleApi()
    api.authenticate()
    remote = {str(row.ref): row for row in api.competition_submissions(COMPETITION, page_size=100)}
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    reports = {}
    now = time.time()
    for submission in ledger["submissions"]:
        submission_id = str(submission["submission_id"])
        row = remote.get(submission_id)
        if row is None:
            raise RuntimeError(f"ledger submission missing from Kaggle: {submission_id}")
        state_path = output / f"{submission_id}.json"
        state = json.loads(state_path.read_text()) if state_path.exists() else {
            "submission_id": submission_id,
            "name": submission["name"],
            "archive_sha256": submission["archive_sha256"],
            "snapshots": [],
        }
        if row.public_score not in (None, ""):
            state["snapshots"].append({"timestamp": now, "rating": float(row.public_score)})
        games_path = Path(args.games_dir) / f"{submission_id}.json"
        games_path.parent.mkdir(parents=True, exist_ok=True)
        games, excluded_self_play = episode_games(api, int(submission_id))
        temporary_games = games_path.with_name(games_path.name + ".tmp")
        temporary_games.write_text(json.dumps(games, indent=2), encoding="utf-8")
        temporary_games.replace(games_path)
        state["kaggle_status"] = str(row.status)
        state["assessment"] = assess_ladder(games, state["snapshots"], now=now)
        state["game_evidence"] = str(games_path.resolve())
        state["excluded_self_play_episodes"] = excluded_self_play
        temporary = state_path.with_name(state_path.name + ".tmp")
        temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
        temporary.replace(state_path)
        reports[submission_id] = state["assessment"]
    manifest = {"observed_unix": now, "reports": reports}
    (output / "latest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

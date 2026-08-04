#!/usr/bin/env python3
"""Rank our real ladder matchups for one submission.

Kaggle's EpisodeService gives outcomes and opponent team ids but no replays, so
opponent archetypes come from decks mined out of the local public replay dump.
Teams we have never seen a replay for land in `unknown`.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EPISODE_SERVICE = "https://www.kaggle.com/api/i/competitions.EpisodeService/"
# ponytail: Jaccard against the known lists, no card-weighting. Sharpen only if
# two archetypes start colliding in the `matched` column.
MATCH_THRESHOLD = 0.35


def auth_header() -> str:
    blob = json.loads((Path(os.environ["HOME"]) / ".kaggle" / "kaggle.json").read_text())
    if "access_token" in blob:
        return "Bearer " + blob["access_token"]
    pair = f"{blob['username']}:{blob['key']}".encode()
    return "Basic " + base64.b64encode(pair).decode()


def list_episodes(submission_id: int) -> list[dict]:
    import ssl
    context = ssl._create_unverified_context()
    request = urllib.request.Request(
        EPISODE_SERVICE + "ListEpisodes",
        data=json.dumps({"submissionId": submission_id}).encode(),
        headers={"Content-Type": "application/json", "Authorization": auth_header()},
    )
    with urllib.request.urlopen(request, timeout=120, context=context) as response:
        return json.load(response).get("episodes", [])


def known_decks() -> dict[str, set[int]]:
    decks = {}
    for path in sorted((ROOT / "freshstart" / "decklists").glob("*.deck.csv")):
        cards = {int(line) for line in path.read_text().split() if line.strip()}
        decks[path.name.removesuffix(".deck.csv")] = cards
    return decks


def classify(deck: list[int], decks: dict[str, set[int]]) -> str:
    """Name the closest known archetype, or 'unknown'."""
    if not deck:
        return "unknown"
    observed = set(deck)
    best, score = "unknown", 0.0
    for name, cards in decks.items():
        overlap = len(observed & cards) / len(observed | cards)
        if overlap > score:
            best, score = name, overlap
    return best if score >= MATCH_THRESHOLD else "unknown"


def team_archetypes(replay_root: Path, decks: dict[str, set[int]]) -> dict[str, str]:
    """Map team name -> archetype using decks recorded at steps[1][seat]['action']."""
    mapping: dict[str, str] = {}
    for path in sorted(replay_root.rglob("*.json")):
        try:
            episode = json.loads(path.read_text())
        except (ValueError, OSError):
            continue
        if not isinstance(episode, dict):
            continue
        steps = episode.get("steps") or []
        teams = (episode.get("info") or {}).get("TeamNames") or []
        if len(steps) < 2:
            continue
        for seat, name in enumerate(teams[:2]):
            if name in mapping or seat >= len(steps[1]):
                continue
            action = steps[1][seat].get("action") or []
            if len(action) == 60:
                mapping[name] = classify([int(card) for card in action], decks)
    return mapping


def leaderboard_names(path: Path) -> dict[int, str]:
    rows = csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines())
    return {int(row["TeamId"]): row["TeamName"] for row in rows}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", type=int, required=True)
    parser.add_argument("--leaderboard", required=True, help="downloaded leaderboard CSV")
    parser.add_argument("--replays", default="data/replays")
    parser.add_argument("--output", default="artifacts/ladder")
    args = parser.parse_args()

    episodes = list_episodes(args.submission)
    decks = known_decks()
    names = leaderboard_names(Path(args.leaderboard))
    archetypes = team_archetypes(ROOT / args.replays, decks)

    tally: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    rows = []
    for episode in episodes:
        agents = episode.get("agents") or []
        us = next((a for a in agents if a.get("submissionId") == args.submission), None)
        them = next((a for a in agents if a.get("submissionId") != args.submission), None)
        if us is None or them is None or us.get("reward") is None:
            continue
        won = us["reward"] > 0
        opponent = names.get(them.get("teamId"), str(them.get("teamId")))
        archetype = archetypes.get(opponent, "unknown")
        tally[archetype][0] += int(won)
        tally[archetype][1] += 1
        rows.append(
            {
                "episode": episode.get("id"),
                "won": won,
                "opponent": opponent,
                "archetype": archetype,
                "opponent_score": them.get("initialScore"),
            }
        )

    total = sum(count for _, count in tally.values())
    ranked = sorted(
        tally.items(),
        key=lambda item: (1 - item[1][0] / item[1][1]) * item[1][1],
        reverse=True,
    )
    lines = [
        f"# Ladder matchups - submission {args.submission}",
        "",
        f"{total} completed games, {sum(r['won'] for r in rows)} won "
        f"({sum(r['won'] for r in rows) / max(1, total):.1%}).",
        "",
        "Ranked by cost = (1 - winrate) x games. Promote the top archetypes to learners.",
        "",
        "| archetype | games | won | winrate | cost |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for archetype, (won, count) in ranked:
        rate = won / count
        lines.append(
            f"| {archetype} | {count} | {won} | {rate:.1%} | {(1 - rate) * count:.1f} |"
        )

    out = ROOT / args.output
    out.mkdir(parents=True, exist_ok=True)
    (out / "matchups.md").write_text("\n".join(lines) + "\n")
    (out / "episodes.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(json.dumps({"games": total, "archetypes": len(tally), "output": str(out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run the local strategic-v2/A2/v1 matchup population comparison."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

ARMS = {
    "a2": ROOT / "artifacts" / "recovery_probes" / "extracted" / "a2",
    "v1": ROOT / "artifacts" / "matchup_playbook" / "extracted" / "grimmsnarl_matchup_playbook",
    "v2": ROOT / "artifacts" / "strategic_playbook" / "extracted",
}
OPPONENTS = (
    ("grim_d842", "artifacts/recovery_final/opponents/d842", "grim", .0505, {}),
    ("grim_a2", "artifacts/recovery_probes/extracted/a2", "grim", .0505, {}),
    ("grim_master", "artifacts/recovery_final/opponents/master_v1", "grim", .0404, {}),
    ("grim_v22", "artifacts/recovery_final/opponents/v2_2", "grim", .0303, {}),
    ("grim_refresh", "artifacts/recovery_final/opponents/replay_refresh", "grim", .0303, {}),
    ("alakazam_24a", "freshstart/elite_submissions/alakazam_2_4a", "alakazam", .125, {"NO_SEARCH": "1"}),
    ("alakazam_27", "freshstart/elite_submissions/alakazam_2_7", "alakazam", .125, {"NO_SEARCH": "1"}),
    ("lucario_proxy", "artifacts/recovery_final/opponents/lucario", "proxy", .131, {}),
    ("crustle_proxy", "artifacts/recovery_final/opponents/crustle", "proxy", .036, {}),
    ("bellibolt_proxy", "artifacts/recovery_final/opponents/bellibolt", "proxy", .020, {}),
    ("ogerpon_proxy", "artifacts/recovery_final/opponents/ogerpon", "proxy", .020, {}),
    ("starmie_proxy", "artifacts/recovery_final/opponents/starmie_froslass", "proxy", .020, {}),
)


def run_one(arm: str, opponent: tuple, games: int, workers: int, seed: int, output: Path) -> dict:
    name, relative, _group, _weight, env = opponent
    agent = ARMS[arm]
    rival = ROOT / relative
    target = output / "shards" / f"{arm}__vs__{name}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(PYTHON), "-m", "training.evaluate",
        "--deck-a", str(agent / "deck.csv"), "--submission-a", str(agent),
        "--deck-b", str(rival / "deck.csv"), "--submission-b", str(rival),
        "--submission-env-b", json.dumps(env), "--opponent-name", name,
        "--games", str(games), "--workers", str(workers), "--seed", str(seed),
        "--max-decisions", "2000", "--output", str(target),
    ]
    subprocess.run(command, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    return json.loads(target.read_text(encoding="utf-8"))


def aggregate(rows: dict[str, dict[str, dict]]) -> dict:
    result = {}
    weight_total = sum(value[3] for value in OPPONENTS)
    for arm, matchups in rows.items():
        games = wins = errors = decisions = 0
        first_games = first_wins = second_games = second_wins = 0
        weighted = 0.0
        groups: dict[str, list[int]] = {}
        opponent_rows = {}
        for opponent in OPPONENTS:
            name, _path, group, weight, _env = opponent
            row = matchups[name]
            g, w = int(row["games"]), int(row["wins_a"])
            games += g; wins += w; errors += int(row["hero_policy_errors"]); decisions += int(row["decisions"])
            first = row["first_player_results_a"]["first"]
            second = row["first_player_results_a"]["second"]
            first_games += int(first["games"]); first_wins += int(first["wins"])
            second_games += int(second["games"]); second_wins += int(second["wins"])
            weighted += weight * float(row["win_rate_a"])
            groups.setdefault(group, [0, 0]); groups[group][0] += w; groups[group][1] += g
            opponent_rows[name] = {"games": g, "wins": w, "win_rate": w / g, "weight": weight}
        result[arm] = {
            "games": games, "wins": wins, "raw_win_rate": wins / games,
            "meta_weighted_win_rate": weighted / weight_total,
            "actual_first": {"games": first_games, "wins": first_wins, "win_rate": first_wins / max(1, first_games)},
            "actual_second": {"games": second_games, "wins": second_wins, "win_rate": second_wins / max(1, second_games)},
            "groups": {group: {"wins": values[0], "games": values[1], "win_rate": values[0] / values[1]}
                       for group, values in groups.items()},
            "opponents": opponent_rows, "hero_policy_errors": errors, "decisions": decisions,
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arms", default="a2,v1,v2")
    parser.add_argument("--games", type=int, default=40, help="games per arm/opponent")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=2026081017)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    arms = [value.strip() for value in args.arms.split(",") if value.strip()]
    unknown = set(arms) - set(ARMS)
    if unknown:
        raise ValueError(f"unknown arms: {sorted(unknown)}")
    started = time.time()
    rows: dict[str, dict[str, dict]] = {arm: {} for arm in arms}
    for arm_index, arm in enumerate(arms):
        for opponent_index, opponent in enumerate(OPPONENTS):
            rows[arm][opponent[0]] = run_one(
                arm, opponent, args.games, args.workers,
                args.seed + arm_index * 100_000 + opponent_index * 1_000, args.output.parent,
            )
    result = {
        "config": {"arms": arms, "games_per_arm_opponent": args.games, "seed": args.seed,
                   "engine_rng": "unpaired_std_random_device", "proxy_caveat": True},
        "results": aggregate(rows), "elapsed_seconds": time.time() - started,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if any(value["hero_policy_errors"] for value in result["results"].values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())

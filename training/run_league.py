#!/usr/bin/env python3
"""Train N live policies in synchronized league rounds.

Every learner collects against generation N before any of them is updated, so the
generation N+1 challengers all faced the same opponent generation.  Frozen
checkpoints remain a bounded minority of the league to detect and prevent
forgetting; they are not substitutes for the continually updated live opponents.

Learners are declared in `training/learners.json`; a learner's `name` is the stem
of its decklist, which is also its entry name in the base league.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def resolved(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else (ROOT / value).resolve()


def build_round_league(
    base: dict,
    live_models: dict[str, Path],
    live_opponents: list[dict],
    snapshots: list[dict],
    live_weight: float,
    snapshot_total_weight: float,
) -> dict:
    """Return a league with the other live policies plus a bounded snapshot mixture."""
    league = deepcopy(base)
    # Snapshot entries are regenerated from the bounded local pool.
    entries = [entry for entry in league["opponents"] if "snapshot" not in entry["name"]]
    for entry in entries:
        if entry["name"] in live_models:
            entry["model"] = str(live_models[entry["name"]])

    per_live = live_weight / max(1, len(live_opponents))
    for opponent in live_opponents:
        entries.append(
            {
                "name": f"live_{opponent['name']}",
                "deck": opponent["deck"],
                "model": str(live_models[opponent["name"]]),
                "meta_weight": 0,
                "train_weight": per_live,
                "evaluate": False,
                "plan": "Continuously updated cross-play opponent from this generation.",
            }
        )
    per_snapshot = snapshot_total_weight / max(1, len(snapshots))
    for snapshot in snapshots:
        entries.append(
            {
                "name": snapshot["name"],
                "deck": snapshot["deck"],
                "model": str(snapshot["model"]),
                "meta_weight": 0,
                "train_weight": per_snapshot,
                "evaluate": False,
                "plan": "Historical checkpoint used only to expose regressions and strategy cycling.",
            }
        )
    league["opponents"] = entries
    return league


def run(command: list[str], dry_run: bool) -> None:
    print("RUN", " ".join(command), flush=True)
    if not dry_run:
        subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--learners", default="training/learners.json")
    parser.add_argument("--base-league", default="training/meta_league.json")
    parser.add_argument("--bc-shard", action="append", default=[])
    parser.add_argument("--output-dir", default="artifacts/coevo_run_04")
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--games-per-learner", type=int, default=10_000)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--temperature", type=float, default=0.65)
    parser.add_argument("--ppo-epochs", type=int, default=2)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--bc-weight", type=float, default=0.25)
    parser.add_argument("--penalty-weight", type=float, default=0.10)
    parser.add_argument("--live-weight", type=float, default=30.0)
    parser.add_argument("--snapshot-total-weight", type=float, default=15.0)
    parser.add_argument("--max-snapshots", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.iterations < 1 or args.games_per_learner < 1:
        parser.error("iterations and games-per-learner must be positive")
    if args.max_snapshots < 1:
        parser.error("max-snapshots must be positive")

    if not args.bc_shard:
        default_shard = ROOT / "data/processed/elite-2026-07-28-v2ctl.jsonl.gz"
        if default_shard.exists():
            args.bc_shard = [str(default_shard)]

    learners = json.loads(resolved(args.learners).read_text())["learners"]
    if len(learners) < 2:
        parser.error("need at least two learners for cross-play")
    names = [learner["name"] for learner in learners]
    if len(set(names)) != len(names):
        parser.error(f"duplicate learner names: {names}")

    output_dir = resolved(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    base = json.loads(resolved(args.base_league).read_text())
    live_models: dict[str, Path] = {
        learner["name"]: resolved(learner.get("model", f"artifacts/round_000/{learner['name']}.npz"))
        for learner in learners
    }
    snapshots: list[dict] = []

    state_path = output_dir / "state.json"
    start_iteration = 1
    if state_path.exists():
        state = json.loads(state_path.read_text())
        start_iteration = int(state.get("completed_round", 0)) + 1
        live_models = {key: resolved(value) for key, value in state["live_models"].items()}
        snapshots = [{**row, "model": resolved(row["model"])} for row in state.get("snapshots", [])]
        print(f"Resuming from completed round {start_iteration - 1}", flush=True)

    python = str(ROOT / ".venv/bin/python") if (ROOT / ".venv/bin/python").exists() else sys.executable
    for iteration in range(start_iteration, start_iteration + args.iterations):
        generation = iteration - 1
        round_dir = output_dir / f"round_{iteration:03d}"
        round_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n=== ROUND {iteration:03d} (generation {generation}) ===", flush=True)

        # Create every rollout league before training any challenger. A failed
        # collection drops that learner from this round rather than killing the
        # whole night's run for the other five.
        rollout_paths: dict[str, Path] = {}
        failed: set[str] = set()
        for index, learner in enumerate(learners):
            other_learners = [row for row in learners if row["name"] != learner["name"]]
            league = build_round_league(
                base,
                live_models,
                other_learners,
                snapshots,
                args.live_weight,
                args.snapshot_total_weight,
            )
            league_path = round_dir / f"{learner['name']}_league.json"
            league_path.write_text(json.dumps(league, indent=2) + "\n")
            rollout = round_dir / f"{learner['name']}_rollouts.jsonl.gz"
            learner_games = int(learner.get("games", args.games_per_learner))
            seat_1_ratio = float(learner.get("seat_1_ratio", 0.50))
            turn1_bench_reward = float(learner.get("turn1_bench_reward", 0.0))
            try:
                run(
                    [
                        python,
                        "training/collect_selfplay.py",
                        "--model", str(live_models[learner["name"]]),
                        "--hero-deck", str(resolved(learner["deck"])),
                        "--league", str(league_path),
                        "--games", str(learner_games),
                        "--workers", str(args.workers),
                        "--temperature", str(args.temperature),
                        "--seat-1-ratio", str(seat_1_ratio),
                        "--turn1-bench-reward", str(turn1_bench_reward),
                        "--seed", str(args.seed + generation * 100 + index),
                        "--output", str(rollout),
                    ],
                    args.dry_run,
                )
                rollout_paths[learner["name"]] = rollout
            except subprocess.CalledProcessError as error:
                print(f"COLLECTION FAILED for {learner['name']}: {error}", flush=True)
                failed.add(learner["name"])

        next_models: dict[str, Path] = {}
        for index, learner in enumerate(learners):
            name = learner["name"]
            if name in failed:
                next_models[name] = live_models[name]
                continue
            challenger = round_dir / f"{name}_challenger.npz"
            turn1_bench_reward = float(learner.get("turn1_bench_reward", 0.0))
            penalty_weight = float(learner.get("penalty_weight", args.penalty_weight))
            command = [
                python,
                "training/train_ppo.py",
                "--initial-model", str(live_models[name]),
                "--rollouts", str(rollout_paths[name]),
                "--output", str(challenger),
                "--epochs", str(args.ppo_epochs),
                "--learning-rate", str(args.learning_rate),
                "--bc-weight", str(learner.get("bc_weight", args.bc_weight)),
                "--penalty-weight", str(penalty_weight),
                "--turn1-bench-reward", str(turn1_bench_reward),
                "--require-card", str(learner["marker_card"]),
                "--seed", str(args.seed + generation * 100 + 50 + index),
            ]
            for shard in args.bc_shard:
                command.extend(("--bc-shard", str(resolved(shard))))
            try:
                run(command, args.dry_run)
                next_models[name] = challenger
            except subprocess.CalledProcessError as error:
                print(f"PPO TRAIN FAILED for {name}: {error}", flush=True)
                next_models[name] = live_models[name]

        # Live policies advance only after every generation-N rollout exists.
        old_models = live_models
        live_models = next_models
        snapshots.extend(
            {
                "name": f"{learner['name']}_snapshot_{generation:03d}",
                "deck": learner["deck"],
                "model": old_models[learner["name"]],
            }
            for learner in learners
        )
        # Deduplicate generation zero, retain only a bounded recent history.
        unique = {str(row["model"]): row for row in snapshots}
        snapshots = list(unique.values())[-args.max_snapshots :]
        state = {
            "completed_round": iteration,
            "live_models": {key: str(value) for key, value in live_models.items()},
            "snapshots": [{**row, "model": str(row["model"])} for row in snapshots],
            "games_collected_per_learner": iteration * args.games_per_learner,
        }
        (output_dir / "state.json").write_text(json.dumps(state, indent=2) + "\n")
        print(json.dumps(state, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

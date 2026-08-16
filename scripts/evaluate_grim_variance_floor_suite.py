#!/usr/bin/env python3
"""Run bounded broad and holdout screens with search explicitly disabled.

All opponents are already present in the repository.  The Alakazam entries are
classified as no-search proxies in this run because ``PTCG_SEARCH=0`` is used
to make the local screen finish; this is not an authentic ladder claim.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANDIDATES = ROOT / "artifacts" / "grim_variance_floor" / "candidates"
DEFAULT_OUTPUT = ROOT / "artifacts" / "grim_variance_floor" / "broad_holdout_results.json"


def opponent_suite() -> tuple[dict[str, dict], dict[str, dict]]:
    decks = ROOT / "freshstart" / "decklists"
    models = ROOT / "artifacts" / "coevo_run_02" / "round_001"
    elite = ROOT / "freshstart" / "elite_submissions"
    development = {
        "alakazam_2_4a_no_search": {
            "deck": elite / "alakazam_2_4a" / "deck.csv",
            "submission": elite / "alakazam_2_4a",
            "classification": "LOW_CONFIDENCE_PROXY_NO_SEARCH",
        },
        "kangaskhan_crustle_model": {
            "deck": decks / "kangaskhan_crustle.deck.csv",
            "model": models / "kangaskhan_crustle_challenger.npz",
            "classification": "LOW_CONFIDENCE_PROXY",
        },
        "cynthias_garchomp_model": {
            "deck": decks / "cynthias_garchomp_ex.deck.csv",
            "model": models / "cynthias_garchomp_ex_challenger.npz",
            "classification": "LOW_CONFIDENCE_PROXY",
        },
        "dragapult_model": {
            "deck": decks / "dragapult_ex.deck.csv",
            "model": models / "dragapult_ex_challenger.npz",
            "classification": "LOW_CONFIDENCE_PROXY",
        },
    }
    holdout = {
        "alakazam_2_7_no_search": {
            "deck": elite / "alakazam_2_7" / "deck.csv",
            "submission": elite / "alakazam_2_7",
            "classification": "LOW_CONFIDENCE_PROXY_NO_SEARCH",
        },
        "team_rockets_mewtwo_model": {
            "deck": decks / "team_rockets_mewtwo_ex.deck.csv",
            "model": models / "team_rockets_mewtwo_ex_challenger.npz",
            "classification": "LOW_CONFIDENCE_PROXY",
        },
    }
    return development, holdout


def _summarize_result(result: dict, opponent: dict, output: Path) -> dict:
    return {
        "games": result["games"],
        "wins": result["wins_a"],
        "win_rate": result["win_rate_a"],
        "wilson_95": result["wilson_95"],
        "first_second": result["first_player_results_a"],
        "errors": {
            "hero": result["hero_policy_errors"],
            "opponent": result["opponent_policy_errors"],
        },
        "floor_metrics": result.get("game_metrics", {}),
        "classification": opponent["classification"],
        "artifact": str(output),
    }


def _run_cell(candidate: Path, opponent: dict, name: str, games: int, output: Path, seed: int, workers: int) -> dict:
    command = [
        sys.executable,
        "training/evaluate.py",
        "--deck-a",
        str(candidate / "deck.csv"),
        "--submission-a",
        str(candidate),
        "--deck-b",
        str(opponent["deck"]),
        "--games",
        str(games),
        "--workers",
        str(workers),
        "--seed",
        str(seed),
        "--max-decisions",
        "2000",
        "--opponent-name",
        name,
        "--output",
        str(output),
    ]
    if "submission" in opponent:
        command.extend(
            [
                "--submission-b",
                str(opponent["submission"]),
                "--submission-env-b",
                '{"PTCG_SEARCH":"0","PTCG_TEMP":"0"}',
            ]
        )
    else:
        command.extend(["--model-b", str(opponent["model"])])
    environment = dict(os.environ)
    environment.update({"PTCG_SEARCH": "0", "PTCG_TEMP": "0", "PYTHONDONTWRITEBYTECODE": "1"})
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        check=False,
        timeout=max(600, games * 60),
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise RuntimeError(
            f"evaluation failed for {name}: "
            + (completed.stderr.strip() or completed.stdout.strip())
        )
    result = json.loads(output.read_text(encoding="utf-8"))
    return _summarize_result(result, opponent, output)


def run_suite(
    *, candidates: Path, development_games: int, holdout_games: int, finalist: str,
    workers: int, output: Path, skip_development: bool = False
) -> dict:
    development, holdout = opponent_suite()
    for opponent in (*development.values(), *holdout.values()):
        for key in ("deck", "model", "submission"):
            if key in opponent and not Path(opponent[key]).exists():
                raise FileNotFoundError(opponent[key])
    result = {
        "label": "LOCAL BROAD/HOLDOUT SCREEN - SEARCH-DISABLED PROXIES",
        "search_enabled": False,
        "engine_deals_paired": False,
        "development": {},
        "holdout": {},
        "finalist": finalist,
    }
    seed = 20260950
    for variant in ("B1", "B2", "B3"):
        result["development"][variant] = {}
        for name, opponent in development.items():
            cell_path = output.parent / f"{variant}_development_{name}.json"
            if skip_development:
                if not cell_path.exists():
                    raise FileNotFoundError(cell_path)
                result["development"][variant][name] = _summarize_result(
                    json.loads(cell_path.read_text(encoding="utf-8")), opponent, cell_path
                )
            else:
                seed += 1
                result["development"][variant][name] = _run_cell(
                    candidates / variant, opponent, name, development_games, cell_path, seed, workers
                )
    result["holdout"][finalist] = {}
    for name, opponent in holdout.items():
        seed += 1
        cell_path = output.parent / f"{finalist}_holdout_{name}.json"
        result["holdout"][finalist][name] = _run_cell(
            candidates / finalist, opponent, name, holdout_games, cell_path, seed, workers
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--development-games", type=int, default=30)
    parser.add_argument("--holdout-games", type=int, default=50)
    parser.add_argument("--finalist", choices=("B2", "B3"), default="B3")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--skip-development", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = run_suite(
        candidates=args.candidates,
        development_games=args.development_games,
        holdout_games=args.holdout_games,
        finalist=args.finalist,
        workers=args.workers,
        output=args.output,
        skip_development=args.skip_development,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

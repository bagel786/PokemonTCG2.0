#!/usr/bin/env python3
"""Run the structural 5k mirror and challenger seat/turn-order audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from training.replay_refresh import _verify_control, run_match
from training.seat_adjusted import structural_lift


def write_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def run_or_load(path: Path, resume: bool, **kwargs) -> dict:
    if resume and path.exists():
        result = json.loads(path.read_text())
        if result["games"] == kwargs["games"]:
            return result
    return run_match(output=path, **kwargs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control-archive", default="grimmsnarl_5k_reference.tar.gz")
    parser.add_argument("--control-model", default="artifacts/grimmsnarl_5k_reference.npz")
    parser.add_argument("--challenger-model", required=True)
    parser.add_argument("--deck", default="freshstart/decklists/grimmsnarl_marnie.deck.csv")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--initial-games", type=int, default=10_000)
    parser.add_argument("--expanded-games", type=int, default=50_000)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260802)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    control = Path(args.control_model).resolve()
    challenger = Path(args.challenger_model).resolve()
    deck = Path(args.deck).resolve()
    _verify_control(Path(args.control_archive).resolve(), control, deck)
    root = Path(args.output_dir).resolve()

    def round_(games: int, label: str):
        control_result = run_or_load(
            root / label / "control_mirror.json", args.resume,
            deck_a=deck, model_a=control, deck_b=deck, model_b=control,
            games=games, workers=args.workers, seed=args.seed,
        )
        challenger_result = run_or_load(
            root / label / "challenger_vs_control.json", args.resume,
            deck_a=deck, model_a=challenger, deck_b=deck, model_b=control,
            games=games, workers=args.workers, seed=args.seed + 1_000_000,
        )
        gate = structural_lift(control_result, challenger_result)
        report = {"games_per_matchup": games, "control": control_result, "challenger": challenger_result, "gate": gate}
        write_json(root / label / "report.json", report)
        return report

    initial = round_(args.initial_games, "initial")
    strata_positive = all(value["lift"] > 0 for value in initial["gate"]["strata"].values())
    directionally_positive = initial["challenger"]["win_rate_a"] > 0.50 and strata_positive
    expanded = round_(args.expanded_games, "expanded") if directionally_positive and not initial["gate"]["passed"] else None
    final = expanded or initial
    report = {
        "version": 1,
        "status": "passed" if final["gate"]["passed"] else "failed",
        "initial": initial,
        "expanded": expanded,
        "final_gate": final["gate"],
        "recommendation_only": True,
        "package_created": False,
        "submitted": False,
    }
    write_json(root / "final_report.json", report)
    print(json.dumps({"status": report["status"], "expanded": expanded is not None, "output": str(root / "final_report.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

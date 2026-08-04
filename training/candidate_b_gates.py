#!/usr/bin/env python3
"""Select and gate Candidate B checkpoints against the original d842 model.

The funnel is recommendation-only and has no packaging/submission capability.
It requires a mirror lift, fresh/temporal decision retention, authentic
Alakazam non-regression, and Lucario/Bellibolt non-regression.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from training.replay_refresh import _verify_control, run_match, sha256_file  # noqa: E402
from training.candidate_b_refresh import candidate_b_decision_gate  # noqa: E402
from training.seat_adjusted import newcombe_difference, structural_lift  # noqa: E402


GRIM_DECK = ROOT / "freshstart/decklists/grimmsnarl_marnie.deck.csv"
LUCARIO_DECK = ROOT / "freshstart/decklists/mega_lucario_ex.deck.csv"
LUCARIO_MODEL = ROOT / "artifacts/lucario_pilot/lucario_ppo2.npz"
BELLIBOLT_DECK = ROOT / "freshstart/decklists/iono_bellibolt_ex.deck.csv"
BELLIBOLT_MODEL = ROOT / "artifacts/bellibolt_bootstrap_20260803/bc/initialized_seed20260804/policy_weights.npz"


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def match_or_load(path: Path, resume: bool, **kwargs) -> dict:
    if resume and path.exists():
        report = json.loads(path.read_text())
        expected_a = str(Path(kwargs["model_a"]).resolve())
        actual_a = str(Path(report.get("model_a", "")).resolve())
        if int(report.get("games", -1)) == int(kwargs["games"]) and actual_a == expected_a:
            return report
    return run_match(output=path, **kwargs)


def rate_gate(baseline: dict, challenger: dict, tolerance: float) -> dict:
    lift = float(challenger["win_rate_a"]) - float(baseline["win_rate_a"])
    interval = newcombe_difference(
        int(challenger["wins_a"]), int(challenger["games"]),
        int(baseline["wins_a"]), int(baseline["games"]),
    )
    errors = int(challenger.get("hero_policy_errors", 0)) + int(challenger.get("opponent_policy_errors", 0))
    return {
        "baseline_win_rate": baseline["win_rate_a"],
        "candidate_win_rate": challenger["win_rate_a"],
        "point_lift": lift,
        "newcombe_95": list(interval),
        "tolerance": tolerance,
        "policy_errors": errors,
        "passed": lift >= -tolerance and errors == 0,
    }


def adversary_gate(root: Path, label: str, anchor: Path, candidate: Path,
                   deck: Path, model: Path, games: int, workers: int,
                   seed: int, resume: bool, tolerance: float) -> dict:
    baseline = match_or_load(
        root / label / "baseline.json", resume,
        deck_a=GRIM_DECK, model_a=anchor, deck_b=deck, model_b=model,
        games=games, workers=workers, seed=seed,
    )
    challenger = match_or_load(
        root / label / "candidate.json", resume,
        deck_a=GRIM_DECK, model_a=candidate, deck_b=deck, model_b=model,
        games=games, workers=workers, seed=seed + 100_000,
    )
    return rate_gate(baseline, challenger, tolerance)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", action="append", required=True, help="Candidate B candidate.json")
    parser.add_argument("--control-archive", default="grimmsnarl_5k_reference.tar.gz")
    parser.add_argument("--control-model", default="artifacts/grimmsnarl_5k_reference.npz")
    parser.add_argument("--deck", default=str(GRIM_DECK))
    parser.add_argument(
        "--structural-control",
        default="artifacts/5k_improvement_20260802/seat_audit/initial/control_mirror.json",
    )
    parser.add_argument("--authentic-league", default="training/external_alakazam_benchmark.json")
    parser.add_argument("--output-dir", default="artifacts/candidate_b_20260804/gates")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--screen-games", type=int, default=500)
    parser.add_argument("--semifinal-games", type=int, default=2_000)
    parser.add_argument("--final-games", type=int, default=10_000)
    parser.add_argument("--adversary-games", type=int, default=1_000)
    parser.add_argument("--authentic-games", type=int, default=200)
    parser.add_argument(
        "--skip-authentic",
        action="store_true",
        help="close an already-failed experiment without spending on mathematically irrelevant authentic gates",
    )
    parser.add_argument("--nonregression-tolerance", type=float, default=0.03)
    parser.add_argument("--seed", type=int, default=20260840)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    root = Path(args.output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    anchor = Path(args.control_model).resolve()
    deck = Path(args.deck).resolve()
    _verify_control(Path(args.control_archive).resolve(), anchor, deck)
    candidates = [json.loads(Path(path).read_text()) for path in args.candidate]
    decision_gates = {candidate["name"]: candidate_b_decision_gate(candidate["decision_reports"]) for candidate in candidates}
    eligible = [candidate for candidate in candidates if decision_gates[candidate["name"]]["passed"]]

    screen = []
    for index, candidate in enumerate(eligible):
        match = match_or_load(
            root / "screen" / f"{candidate['name']}.json", args.resume,
            deck_a=deck, model_a=candidate["training"]["output"],
            deck_b=deck, model_b=anchor,
            games=args.screen_games, workers=args.workers,
            seed=args.seed + index * 10_000,
        )
        screen.append({"candidate": candidate, "match": match})
    screen.sort(key=lambda item: (
        item["match"]["win_rate_a"],
        item["candidate"]["decision_reports"]["team_holdout"]["delta"]["exact_rate"],
        item["candidate"]["decision_reports"]["temporal"]["delta"]["exact_rate"],
    ), reverse=True)

    semifinal = []
    for index, item in enumerate(screen[:2]):
        candidate = item["candidate"]
        match = match_or_load(
            root / "semifinal" / f"{candidate['name']}.json", args.resume,
            deck_a=deck, model_a=candidate["training"]["output"],
            deck_b=deck, model_b=anchor,
            games=args.semifinal_games, workers=args.workers,
            seed=args.seed + 1_000_000 + index * 10_000,
        )
        advanced = match["win_rate_a"] >= 0.51 and match.get("hero_policy_errors", 0) == 0
        semifinal.append({"candidate": candidate, "match": match, "advanced": advanced})
    semifinal.sort(key=lambda item: (item["advanced"], item["match"]["win_rate_a"]), reverse=True)
    finalist = semifinal[0]["candidate"] if semifinal and semifinal[0]["advanced"] else None

    final_match = structural = None
    authentic = {}
    lucario = bellibolt = None
    if finalist:
        candidate_path = Path(finalist["training"]["output"]).resolve()
        final_match = match_or_load(
            root / "final" / "candidate_vs_d842.json", args.resume,
            deck_a=deck, model_a=candidate_path, deck_b=deck, model_b=anchor,
            games=args.final_games, workers=args.workers, seed=args.seed + 2_000_000,
        )
        structural = structural_lift(json.loads(Path(args.structural_control).read_text()), final_match)

        lucario = adversary_gate(
            root, "nonregression/lucario", anchor, candidate_path,
            LUCARIO_DECK, LUCARIO_MODEL, args.adversary_games, args.workers,
            args.seed + 3_000_000, args.resume, args.nonregression_tolerance,
        )
        bellibolt = adversary_gate(
            root, "nonregression/bellibolt", anchor, candidate_path,
            BELLIBOLT_DECK, BELLIBOLT_MODEL, args.adversary_games, args.workers,
            args.seed + 4_000_000, args.resume, args.nonregression_tolerance,
        )

        if not args.skip_authentic:
            league = json.loads(Path(args.authentic_league).read_text())
            for index, entry in enumerate(league["opponents"]):
                if not entry.get("evaluate", True):
                    continue
                baseline = match_or_load(
                    root / "nonregression/authentic" / f"{entry['name']}_baseline.json", args.resume,
                    deck_a=deck, model_a=anchor, deck_b=ROOT / entry["deck"], model_b="",
                    submission_b=ROOT / entry["submission"], games=args.authentic_games,
                    workers=args.workers, seed=args.seed + 5_000_000 + index * 10_000,
                )
                challenger = match_or_load(
                    root / "nonregression/authentic" / f"{entry['name']}_candidate.json", args.resume,
                    deck_a=deck, model_a=candidate_path, deck_b=ROOT / entry["deck"], model_b="",
                    submission_b=ROOT / entry["submission"], games=args.authentic_games,
                    workers=args.workers, seed=args.seed + 6_000_000 + index * 10_000,
                )
                authentic[entry["name"]] = rate_gate(baseline, challenger, args.nonregression_tolerance)

    success = bool(
        finalist
        and structural and structural["passed"]
        and lucario and lucario["passed"]
        and bellibolt and bellibolt["passed"]
        and authentic and all(result["passed"] for result in authentic.values())
        and decision_gates[finalist["name"]]["passed"]
    )
    report = {
        "version": 1,
        "status": "candidate_b_passed" if success else "candidate_b_not_shippable",
        "success": success,
        "experiment_only": True,
        "package_created": False,
        "submitted": False,
        "anchor": {"path": str(anchor), "sha256": sha256_file(anchor)},
        "screen": [{"name": item["candidate"]["name"], "match": item["match"]} for item in screen],
        "semifinal": [
            {"name": item["candidate"]["name"], "match": item["match"], "advanced": item["advanced"]}
            for item in semifinal
        ],
        "finalist": finalist["name"] if finalist else None,
        "final_match": final_match,
        "gates": {
            "decision_holdout": decision_gates[finalist["name"]] if finalist else None,
            "structural_mirror": structural,
            "lucario": lucario,
            "bellibolt": bellibolt,
            "authentic_alakazam": authentic,
            "authentic_status": (
                "skipped_after_structural_failure" if args.skip_authentic else "completed"
            ),
        },
        "candidate_decision_gates": decision_gates,
    }
    write_json(root / "final_report.json", report)
    print(json.dumps({
        "status": report["status"], "success": success, "finalist": report["finalist"],
        "output": str(root / "final_report.json"), "package_created": False, "submitted": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Azure selection funnel for targeted BC candidates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from training.replay_refresh import _verify_control, run_match
from training.seat_adjusted import structural_lift


ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def match_or_load(path: Path, resume: bool, **kwargs):
    if resume and path.exists():
        value = json.loads(path.read_text())
        if value["games"] == kwargs["games"]:
            return value
    return run_match(output=path, **kwargs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", action="append", required=True, help="candidate.json path")
    parser.add_argument("--control-archive", default="grimmsnarl_5k_reference.tar.gz")
    parser.add_argument("--control-model", default="artifacts/grimmsnarl_5k_reference.npz")
    parser.add_argument("--deck", default="freshstart/decklists/grimmsnarl_marnie.deck.csv")
    parser.add_argument("--structural-control", required=True, help="5k-vs-5k evaluator JSON")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--screen-games", type=int, default=500)
    parser.add_argument("--semifinal-games", type=int, default=2000)
    parser.add_argument("--final-games", type=int, default=10_000)
    parser.add_argument("--expanded-games", type=int, default=50_000)
    parser.add_argument("--authentic-games", type=int, default=500)
    parser.add_argument("--authentic-league", default="training/external_alakazam_benchmark.json")
    parser.add_argument(
        "--fallback-candidate",
        default="artifacts/5k_replay_refresh_20260802/full/candidates/lr1e-04_seed20260803/decision_evaluation.json",
        help="validated incumbent decision-evaluation JSON",
    )
    parser.add_argument(
        "--fallback-model",
        default="artifacts/5k_replay_refresh_20260802/full/candidates/lr1e-04_seed20260803/policy_weights.npz",
        help="validated incumbent model weights",
    )
    parser.add_argument(
        "--fallback-seat-audit",
        default="artifacts/5k_improvement_20260802/seat_audit/final_report.json",
        help="completed seat-adjusted audit for the incumbent",
    )
    parser.add_argument("--seed", type=int, default=20260820)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    root = Path(args.output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    control = Path(args.control_model).resolve()
    deck = Path(args.deck).resolve()
    _verify_control(Path(args.control_archive).resolve(), control, deck)
    candidates = [json.loads(Path(path).read_text()) for path in args.candidate]
    eligible = [candidate for candidate in candidates if candidate["heldout_gate"]["passed"]]

    screen = []
    for index, candidate in enumerate(eligible):
        match = match_or_load(
            root / "screen" / f"{candidate['name']}.json", args.resume,
            deck_a=deck, model_a=candidate["training"]["output"], deck_b=deck, model_b=control,
            games=args.screen_games, workers=args.workers, seed=args.seed + index * 100_000,
        )
        screen.append({"candidate": candidate, "match": match})
    screen.sort(key=lambda item: (
        item["match"]["win_rate_a"], item["match"]["wilson_95"][0],
        item["candidate"]["decision_reports"]["temporal"]["candidate"]["exact_rate"],
    ), reverse=True)

    semifinal = []
    for index, item in enumerate(screen[:3]):
        candidate = item["candidate"]
        match = match_or_load(
            root / "semifinal" / f"{candidate['name']}.json", args.resume,
            deck_a=deck, model_a=candidate["training"]["output"], deck_b=deck, model_b=control,
            games=args.semifinal_games, workers=args.workers, seed=args.seed + 1_000_000 + index * 100_000,
        )
        advanced = match["win_rate_a"] >= 0.51 and match["hero_policy_errors"] == 0
        semifinal.append({"candidate": candidate, "match": match, "advanced": advanced})
    semifinal.sort(key=lambda item: (item["advanced"], item["match"]["win_rate_a"]), reverse=True)
    finalist = semifinal[0]["candidate"] if semifinal and semifinal[0]["advanced"] else None

    final_match = gate = expanded = None
    used_validated_fallback = False
    if not finalist and args.fallback_candidate and args.fallback_model and args.fallback_seat_audit:
        fallback = json.loads(Path(args.fallback_candidate).read_text())
        audit = json.loads(Path(args.fallback_seat_audit).read_text())
        if fallback["heldout_gate"]["passed"] and audit["final_gate"]["passed"]:
            fallback["name"] = "replay_refresh_incumbent"
            fallback["training"]["output"] = str(Path(args.fallback_model).resolve())
            finalist = fallback
            used_validated_fallback = True
            selected_audit = audit["expanded"] or audit["initial"]
            final_match = selected_audit["challenger"]
            gate = audit["final_gate"]
            expanded = audit["expanded"]

    authentic = {}
    authentic_pass = False
    if finalist:
        if not used_validated_fallback:
            final_match = match_or_load(
                root / "final" / "challenger.json", args.resume,
                deck_a=deck, model_a=finalist["training"]["output"], deck_b=deck, model_b=control,
                games=args.final_games, workers=args.workers, seed=args.seed + 2_000_000,
            )
            structural_control = json.loads(Path(args.structural_control).read_text())
            gate = structural_lift(structural_control, final_match)
            directionally_positive = (
                final_match["win_rate_a"] > 0.50
                and all(value["lift"] > 0 for value in gate["strata"].values())
            )
            if directionally_positive and not gate["passed"]:
                expanded_control = match_or_load(
                    root / "expanded" / "control.json", args.resume,
                    deck_a=deck, model_a=control, deck_b=deck, model_b=control,
                    games=args.expanded_games, workers=args.workers, seed=args.seed + 3_000_000,
                )
                expanded_candidate = match_or_load(
                    root / "expanded" / "challenger.json", args.resume,
                    deck_a=deck, model_a=finalist["training"]["output"], deck_b=deck, model_b=control,
                    games=args.expanded_games, workers=args.workers, seed=args.seed + 4_000_000,
                )
                gate = structural_lift(expanded_control, expanded_candidate)
                expanded = {"control": expanded_control, "challenger": expanded_candidate, "gate": gate}

        authentic_pass = True
        for index, entry in enumerate(json.loads(Path(args.authentic_league).read_text())["opponents"]):
            if not entry.get("evaluate"):
                continue
            opponent_deck = ROOT / entry["deck"]
            submission = ROOT / entry["submission"]
            baseline = match_or_load(
                root / "authentic" / f"{entry['name']}_baseline.json", args.resume,
                deck_a=deck, model_a=control, deck_b=opponent_deck,
                games=args.authentic_games, workers=args.workers,
                seed=args.seed + 5_000_000 + index * 100_000, submission_b=submission,
            )
            challenger = match_or_load(
                root / "authentic" / f"{entry['name']}_challenger.json", args.resume,
                deck_a=deck, model_a=finalist["training"]["output"], deck_b=opponent_deck,
                games=args.authentic_games, workers=args.workers,
                seed=args.seed + 5_000_000 + index * 100_000, submission_b=submission,
            )
            passed = challenger["win_rate_a"] >= baseline["win_rate_a"] - 0.03 and challenger["hero_policy_errors"] == 0
            authentic_pass &= passed
            authentic[entry["name"]] = {"baseline": baseline, "challenger": challenger, "passed": passed}

    success = bool(finalist and gate and gate["passed"] and authentic_pass and finalist["heldout_gate"]["passed"])
    report = {
        "version": 1,
        "status": "bc_recommendation" if success else "rl_required",
        "success": success,
        "recommendation_only": True,
        "package_created": False,
        "submitted": False,
        "screen": [{"name": item["candidate"]["name"], "match": item["match"]} for item in screen],
        "semifinal": [{"name": item["candidate"]["name"], "match": item["match"], "advanced": item["advanced"]} for item in semifinal],
        "finalist": finalist["name"] if finalist else None,
        "used_validated_fallback": used_validated_fallback,
        "final_match": final_match,
        "structural_gate": gate,
        "expanded": expanded,
        "authentic": authentic,
    }
    write_json(root / "final_report.json", report)
    print(json.dumps({"status": report["status"], "finalist": report["finalist"], "output": str(root / "final_report.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

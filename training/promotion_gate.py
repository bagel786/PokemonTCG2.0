#!/usr/bin/env python3
"""Decide whether a co-evolution challenger may replace its incumbent.

Five questions, enforcing Rule 2 (Paired Ladder Benchmark & Promotion Invariant):

1. head-to-head       -- does it beat the incumbent it would replace?
2. regression         -- does it still beat every frozen snapshot? (prevents policy cycling)
3. 5k baseline parity -- does it maintain 48-52% mirror parity against the 975 Elo 5k GM model?
4. meta gauntlet      -- does it achieve >= 80% aggregate win rate against the diverse meta roster?
5. held-out anchor    -- how does it do against a frozen external submission?

Emits decision.json in the shape used by artifacts/grim_challenger_20260730/.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def resolved(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else (ROOT / value).resolve()


def head_to_head(deck, model_a, model_b, games, workers, out_path, submission_b="") -> dict:
    command = [
        sys.executable, "training/evaluate.py",
        "--deck-a", str(resolved(deck)), "--model-a", str(resolved(model_a)),
        "--deck-b", str(resolved(deck)),
        "--games", str(games), "--workers", str(workers),
        "--output", str(out_path),
    ]
    if submission_b:
        command += ["--submission-b", str(resolved(submission_b))]
    else:
        command += ["--model-b", str(resolved(model_b))]
    subprocess.run(command, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    return json.loads(Path(out_path).read_text())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--learner", required=True, help="learner name in learners.json")
    parser.add_argument("--challenger", required=True)
    parser.add_argument("--incumbent", required=True)
    parser.add_argument("--learners", default="training/learners.json")
    parser.add_argument("--snapshot", action="append", default=[], help="frozen checkpoint to regress against")
    parser.add_argument("--external-submission", default="", help="frozen held-out opponent directory")
    parser.add_argument("--baseline-5k", default="artifacts/overnight_grim_20260730/grim_selected.npz", help="frozen 5k GM reference baseline")
    parser.add_argument("--min-5k-win-rate", type=float, default=0.48, help="minimum mirror parity win rate against 5k baseline")
    parser.add_argument("--max-5k-win-rate", type=float, default=0.52, help="maximum mirror parity win rate against 5k baseline")
    parser.add_argument("--skip-5k-baseline", action="store_true", help="skip 5k baseline mirror parity gate")
    parser.add_argument("--meta-league", default="training/meta_league.json", help="meta league definition JSON")
    parser.add_argument("--min-meta-win-rate", type=float, default=0.80, help="minimum meta-weighted win rate across meta roster")
    parser.add_argument("--meta-games-per-opponent", type=int, default=100, help="games per meta opponent during gauntlet")
    parser.add_argument("--skip-meta-gauntlet", action="store_true", help="skip meta gauntlet gate")
    parser.add_argument("--games", type=int, default=500)
    parser.add_argument("--anchor-games", type=int, default=100)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--min-win-rate", type=float, default=0.52)
    parser.add_argument("--min-snapshot-win-rate", type=float, default=0.50)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    learners = json.loads(resolved(args.learners).read_text())["learners"]
    entry = next((row for row in learners if row["name"] == args.learner), None)
    if entry is None:
        parser.error(f"unknown learner {args.learner}; have {[r['name'] for r in learners]}")
    deck = entry["deck"]

    out_dir = resolved(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    gates: dict[str, dict] = {}

    versus = head_to_head(
        deck, args.challenger, args.incumbent, args.games, args.workers,
        out_dir / "vs_incumbent.json",
    )
    gates["head_to_head"] = {
        "win_rate": versus["win_rate_a"],
        "games": versus["games"],
        "required": args.min_win_rate,
        "passed": versus["win_rate_a"] >= args.min_win_rate,
        "policy_errors": versus["hero_policy_errors"] + versus["opponent_policy_errors"],
    }

    regressions = []
    for index, snapshot in enumerate(args.snapshot):
        result = head_to_head(
            deck, args.challenger, snapshot, args.games // 2, args.workers,
            out_dir / f"vs_snapshot_{index}.json",
        )
        regressions.append({
            "snapshot": str(snapshot),
            "win_rate": result["win_rate_a"],
            "games": result["games"],
            "passed": result["win_rate_a"] >= args.min_snapshot_win_rate,
        })
    gates["regression"] = {
        "required_each": args.min_snapshot_win_rate,
        "results": regressions,
        "passed": all(row["passed"] for row in regressions) if regressions else None,
    }

    if not args.skip_5k_baseline and resolved(args.baseline_5k).exists():
        parity = head_to_head(
            deck, args.challenger, args.baseline_5k, args.games, args.workers,
            out_dir / "vs_5k_baseline.json",
        )
        parity_passed = (parity["win_rate_a"] >= args.min_5k_win_rate) and (parity["win_rate_a"] <= args.max_5k_win_rate)
        gates["baseline_5k_parity"] = {
            "baseline": str(args.baseline_5k),
            "win_rate": parity["win_rate_a"],
            "games": parity["games"],
            "required_range": [args.min_5k_win_rate, args.max_5k_win_rate],
            "passed": parity_passed,
            "policy_errors": parity["hero_policy_errors"] + parity["opponent_policy_errors"],
        }

    if not args.skip_meta_gauntlet and resolved(args.meta_league).exists():
        meta_cmd = [
            sys.executable, "training/evaluate_league.py",
            "--hero-deck", str(resolved(deck)),
            "--hero-model", str(resolved(args.challenger)),
            "--league", str(resolved(args.meta_league)),
            "--games-per-opponent", str(args.meta_games_per_opponent),
            "--workers", str(args.workers),
            "--output", str(out_dir / "meta_gauntlet.json"),
        ]
        subprocess.run(meta_cmd, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
        meta_report = json.loads((out_dir / "meta_gauntlet.json").read_text())
        meta_passed = meta_report["meta_weighted_win_rate"] >= args.min_meta_win_rate
        gates["meta_gauntlet"] = {
            "meta_weighted_win_rate": meta_report["meta_weighted_win_rate"],
            "games_per_opponent": args.meta_games_per_opponent,
            "total_games": meta_report["total_games"],
            "required": args.min_meta_win_rate,
            "passed": meta_passed,
        }

    if args.external_submission:
        anchor = head_to_head(
            deck, args.challenger, "", args.anchor_games, args.workers,
            out_dir / "vs_external.json", submission_b=args.external_submission,
        )
        gates["held_out_anchor"] = {
            "win_rate": anchor["win_rate_a"],
            "games": anchor["games"],
            "note": "reported, not gated: frozen opponent that never trains",
        }

    blocking = [name for name, gate in gates.items() if gate.get("passed") is False]
    decision = {
        "learner": args.learner,
        "challenger": str(args.challenger),
        "incumbent": str(args.incumbent),
        "decision": "promote_challenger" if not blocking else "reject_challenger_keep_incumbent",
        "failed_gates": blocking,
        "gates": gates,
        "submitted": False,
    }
    (out_dir / "decision.json").write_text(json.dumps(decision, indent=2) + "\n")
    print(json.dumps(decision, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

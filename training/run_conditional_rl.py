#!/usr/bin/env python3
"""Azure-only conservative PPO fallback after targeted BC fails."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from training.azure_guard import enforce_azure_workload
from training.replay_refresh import evaluate_model_pair, heldout_gate, run_match, sha256_file
from training.seat_adjusted import structural_lift


ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def rollout_league(control: Path, snapshot: Path) -> dict:
    meta = json.loads((ROOT / "training" / "meta_league.json").read_text())["opponents"]
    diverse = [row for row in meta if row["name"] != "grimmsnarl_marnie" and not row.get("submission")][:10]
    entries = [
        {
            "name": "original_5k_mirror", "deck": "freshstart/decklists/grimmsnarl_marnie.deck.csv",
            "model": str(control), "train_weight": 40,
        },
        {
            "name": "strongest_bc_snapshot", "deck": "freshstart/decklists/grimmsnarl_marnie.deck.csv",
            "model": str(snapshot), "train_weight": 20,
        },
        {
            "name": "alakazam_2_7_authentic", "deck": "freshstart/elite_submissions/alakazam_2_7/deck.csv",
            "submission": "freshstart/elite_submissions/alakazam_2_7", "submission_env": {"NO_LETHAL": "1"},
            "train_weight": 10,
        },
        {
            "name": "alakazam_2_4a_authentic", "deck": "freshstart/elite_submissions/alakazam_2_4a/deck.csv",
            "submission": "freshstart/elite_submissions/alakazam_2_4a",
            "submission_env": {"DIRECT_POLICY": "1", "NO_LETHAL": "1"}, "train_weight": 10,
        },
    ]
    for row in diverse:
        entries.append({
            "name": f"meta_{row['name']}", "deck": row["deck"], "model": row.get("model", ""),
            "train_weight": 20 / len(diverse),
        })
    return {"version": 1, "purpose": "guarded_single-policy_ppo", "opponents": entries}


def run_round(args, root: Path, name: str, initial: Path, games: int, seed: int, manifest: dict) -> dict:
    round_dir = root / name
    round_dir.mkdir(parents=True, exist_ok=True)
    rollouts = round_dir / "rollouts" / "rollouts.jsonl.gz"
    subprocess.run([
        sys.executable, "training/collect_sharded.py",
        "--model", str(initial), "--hero-deck", args.deck, "--league", str(root / "league.json"),
        "--games", str(games), "--shard-size", "500", "--workers", str(args.workers),
        "--temperature", "0.70", "--gae-lambda", "0.95", "--seed", str(seed),
        "--output-dir", str(round_dir / "rollouts"),
    ], cwd=ROOT, check=True)
    challenger = round_dir / "policy_weights.npz"
    subprocess.run([
        sys.executable, "training/train_ppo.py",
        "--initial-model", str(initial), "--rollouts", str(rollouts),
        "--bc-shard", args.fresh, "--require-card", "648", "--output", str(challenger),
        "--epochs", "1", "--learning-rate", "1e-5", "--bc-weight", "0.50",
        "--target-kl", "0.01", "--hard-kl", "0.02", "--seed", str(seed + 50),
    ], cwd=ROOT, check=True)
    reports = {
        split: evaluate_model_pair(
            args.control_model, challenger, args.fresh, manifest, split, 256, "cpu", 0
        )
        for split in ("internal_validation", "team_holdout", "temporal")
    }
    heldout = heldout_gate(reports)
    screen = run_match(
        deck_a=args.deck, model_a=challenger, deck_b=args.deck, model_b=args.control_model,
        games=500, workers=args.workers, output=round_dir / "screen.json", seed=seed + 100,
    )
    passed = heldout["passed"] and screen["win_rate_a"] >= 0.51 and screen["hero_policy_errors"] == 0
    report = {
        "name": name, "games": games, "initial": str(initial), "output": str(challenger),
        "sha256": sha256_file(challenger), "decision_reports": reports, "heldout_gate": heldout,
        "screen": screen, "passed": passed,
    }
    write_json(round_dir / "report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initial-candidate", required=True, help="targeted candidate.json")
    parser.add_argument("--control-model", default="artifacts/grimmsnarl_5k_reference.npz")
    parser.add_argument("--deck", default="freshstart/decklists/grimmsnarl_marnie.deck.csv")
    parser.add_argument("--fresh", default="data/processed/elite-2026-07-30-31-v2ctl.jsonl.gz")
    parser.add_argument("--split-manifest", required=True)
    parser.add_argument("--structural-control", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260830)
    args = parser.parse_args()
    enforce_azure_workload(workload_size=5_000)
    root = Path(args.output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    candidate = json.loads(Path(args.initial_candidate).read_text())
    initial = Path(candidate["training"]["output"]).resolve()
    control = Path(args.control_model).resolve()
    write_json(root / "league.json", rollout_league(control, initial))
    manifest = json.loads(Path(args.split_manifest).read_text())
    pilot = run_round(args, root, "pilot_5k", initial, 5_000, args.seed, manifest)
    expanded = run_round(args, root, "round_20k", Path(pilot["output"]), 20_000, args.seed + 1_000_000, manifest) if pilot["passed"] else None
    selected = expanded or pilot
    final = run_match(
        deck_a=args.deck, model_a=selected["output"], deck_b=args.deck, model_b=control,
        games=10_000, workers=args.workers, output=root / "final_match.json", seed=args.seed + 2_000_000,
    )
    structural = structural_lift(json.loads(Path(args.structural_control).read_text()), final)
    authentic = {}
    authentic_pass = True
    for index, entry in enumerate(json.loads((ROOT / "training" / "external_alakazam_benchmark.json").read_text())["opponents"]):
        opponent_deck = ROOT / entry["deck"]
        submission = ROOT / entry["submission"]
        baseline = run_match(
            deck_a=args.deck, model_a=control, deck_b=opponent_deck, games=500, workers=args.workers,
            output=root / "authentic" / f"{entry['name']}_baseline.json", seed=args.seed + 3_000_000 + index,
            submission_b=submission,
        )
        challenger = run_match(
            deck_a=args.deck, model_a=selected["output"], deck_b=opponent_deck, games=500, workers=args.workers,
            output=root / "authentic" / f"{entry['name']}_challenger.json", seed=args.seed + 3_000_000 + index,
            submission_b=submission,
        )
        passed = challenger["win_rate_a"] >= baseline["win_rate_a"] - 0.03 and challenger["hero_policy_errors"] == 0
        authentic_pass &= passed
        authentic[entry["name"]] = {"baseline": baseline, "challenger": challenger, "passed": passed}
    success = selected["passed"] and structural["passed"] and authentic_pass
    report = {
        "version": 1, "status": "rl_recommendation" if success else "no_improvement",
        "success": success, "pilot": pilot, "expanded": expanded, "selected": selected["output"],
        "final": final, "structural_gate": structural, "authentic": authentic,
        "recommendation_only": True, "package_created": False, "submitted": False,
    }
    write_json(root / "final_report.json", report)
    print(json.dumps({"status": report["status"], "output": str(root / "final_report.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

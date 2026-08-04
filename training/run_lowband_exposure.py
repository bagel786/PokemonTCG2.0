#!/usr/bin/env python3
"""Azure-only single-candidate Grim exposure curriculum.

Trains ONE conservative PPO candidate from an anchor against the low-band
exposure league (adds Mega Lucario ex + Iono/Bellibolt ex, which no prior Grim
league contained) and runs regression + improvement gates. Contains no packaging
or submission step.

Bypasses the qualified-adversary gate that blocks run_grim_lucario_recovery.py:
here the Lucario/Iono opponents are deliberately weak, un-qualified adversaries
used only for exposure. Catastrophic forgetting is held off by conservative PPO
(low LR, BC anchoring, KL rollback) and confirmed by the structural + authentic
gates below.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from training.azure_guard import enforce_azure_workload
from training.replay_refresh import evaluate_model_pair, heldout_gate, run_match, sha256_file
from training.seat_adjusted import newcombe_difference, structural_lift

ROOT = Path(__file__).resolve().parents[1]
GRIM_DECK = ROOT / "freshstart/decklists/grimmsnarl_marnie.deck.csv"
LUCARIO_DECK = ROOT / "freshstart/decklists/mega_lucario_ex.deck.csv"
LUCARIO_MODEL = ROOT / "artifacts/lucario_pilot/lucario_ppo2.npz"
BELLIBOLT_DECK = ROOT / "freshstart/decklists/iono_bellibolt_ex.deck.csv"
BELLIBOLT_MODEL = ROOT / "artifacts/bellibolt_bootstrap_20260803/bc/initialized_seed20260804/policy_weights.npz"
GRIM_MARKER_CARD = 648  # Marnie's Grimmsnarl ex


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def match_or_load(path: Path, resume: bool, **kwargs) -> dict:
    if resume and path.exists():
        report = json.loads(path.read_text())
        if int(report.get("games", -1)) == int(kwargs["games"]):
            return report
    return run_match(output=path, **kwargs)


def adversary_gate(root: Path, label: str, anchor: Path, challenger: Path,
                   deck: Path, model: Path, games: int, workers: int, seed: int, resume: bool) -> dict:
    """Anchor-vs-adversary baseline compared to challenger-vs-adversary."""
    baseline = match_or_load(root / label / "baseline.json", resume,
                             deck_a=GRIM_DECK, model_a=anchor, deck_b=deck, model_b=model,
                             games=games, workers=workers, seed=seed)
    candidate = match_or_load(root / label / "candidate.json", resume,
                              deck_a=GRIM_DECK, model_a=challenger, deck_b=deck, model_b=model,
                              games=games, workers=workers, seed=seed + 500_000)
    interval = newcombe_difference(candidate["wins_a"], candidate["games"], baseline["wins_a"], baseline["games"])
    errors = candidate.get("hero_policy_errors", 0) + candidate.get("opponent_policy_errors", 0)
    point_lift = candidate["win_rate_a"] - baseline["win_rate_a"]
    return {
        "baseline_win_rate": baseline["win_rate_a"], "candidate_win_rate": candidate["win_rate_a"],
        "point_lift": point_lift, "newcombe_95": list(interval), "policy_errors": errors,
        "improved": point_lift > 0 and errors == 0,
        "significant": interval[0] > 0 and errors == 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor", default="artifacts/5k_replay_refresh_20260802/full/candidates/lr1e-04_seed20260803/policy_weights.npz")
    parser.add_argument("--league", default="training/lowband_grim_league.json")
    parser.add_argument("--fresh", default="data/processed/elite-2026-07-30-31-v2ctl.jsonl.gz")
    parser.add_argument("--split-manifest", default="artifacts/5k_replay_refresh_20260802/full/split_manifest.json")
    parser.add_argument("--output-dir", default="artifacts/lowband_exposure_20260803")
    parser.add_argument("--collect-games", type=int, default=5000)
    parser.add_argument("--shard-size", type=int, default=500)
    parser.add_argument("--mirror-games", type=int, default=2000)
    parser.add_argument("--adversary-games", type=int, default=1000)
    parser.add_argument("--authentic-games", type=int, default=500)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--temperature", type=float, default=0.70)
    parser.add_argument("--seat1-ratio", type=float, default=0.50)
    parser.add_argument("--turn1-bench-reward", type=float, default=0.0)
    parser.add_argument("--extra-bc-shard", action="append", default=[])
    parser.add_argument("--learning-rate", type=float, default=1e-5)
    parser.add_argument("--bc-weight", type=float, default=0.50)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--target-kl", type=float, default=0.01)
    parser.add_argument("--hard-kl", type=float, default=0.02)
    parser.add_argument("--seed", type=int, default=20260803)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--allow-local-smoke", action="store_true")
    args = parser.parse_args()
    enforce_azure_workload(allow_local_smoke=args.allow_local_smoke, workload_size=args.collect_games)

    root = Path(args.output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    anchor = Path(args.anchor).resolve()
    challenger = root / "policy_weights.npz"
    smoke = ["--allow-local-smoke"] if args.allow_local_smoke else []

    # 1. Collect rollouts against the exposure league.
    rollouts_dir = root / "rollouts"
    combined = rollouts_dir / "rollouts.jsonl.gz"
    if not (args.resume and combined.exists()):
        subprocess.run([
            sys.executable, "training/collect_sharded.py", "--model", str(anchor),
            "--hero-deck", str(GRIM_DECK), "--league", str(ROOT / args.league),
            "--games", str(args.collect_games), "--shard-size", str(args.shard_size),
            "--workers", str(args.workers), "--temperature", str(args.temperature),
            "--seat-1-ratio", str(args.seat1_ratio),
            "--turn1-bench-reward", str(args.turn1_bench_reward),
            "--seed", str(args.seed), "--output-dir", str(rollouts_dir), *smoke,
        ], cwd=ROOT, check=True)

    # 2. Conservative PPO update (KL guards + BC anchoring resist forgetting).
    if not (args.resume and challenger.exists()):
        train_command = [
            sys.executable, "training/train_ppo.py", "--initial-model", str(anchor),
            "--rollouts", str(combined), "--bc-shard", str(ROOT / args.fresh),
            "--require-card", str(GRIM_MARKER_CARD), "--output", str(challenger),
            "--epochs", str(args.epochs), "--learning-rate", str(args.learning_rate),
            "--bc-weight", str(args.bc_weight), "--target-kl", str(args.target_kl), "--hard-kl", str(args.hard_kl),
            "--turn1-bench-reward", str(args.turn1_bench_reward),
            "--seed", str(args.seed + 50), *smoke,
        ]
        for shard in args.extra_bc_shard:
            train_command.extend(("--bc-shard", str(ROOT / shard)))
        result = subprocess.run(train_command, cwd=ROOT, check=True, text=True, capture_output=True)
        (root / "train.log").write_text(result.stdout + result.stderr)
    kl_rollback = "rolled_back': True" in (root / "train.log").read_text() if (root / "train.log").exists() else False

    # 3. Gates.
    manifest = json.loads((ROOT / args.split_manifest).read_text())
    decisions = {
        split: evaluate_model_pair(anchor, challenger, str(ROOT / args.fresh), manifest, split, 256, "cpu", 0)
        for split in ("internal_validation", "team_holdout", "temporal")
    }
    heldout = heldout_gate(decisions)

    control = match_or_load(root / "gates/structural_control.json", args.resume,
                            deck_a=GRIM_DECK, model_a=anchor, deck_b=GRIM_DECK, model_b=anchor,
                            games=args.mirror_games, workers=args.workers, seed=args.seed + 1_000_000)
    mirror = match_or_load(root / "gates/challenger_vs_anchor.json", args.resume,
                           deck_a=GRIM_DECK, model_a=challenger, deck_b=GRIM_DECK, model_b=anchor,
                           games=args.mirror_games, workers=args.workers, seed=args.seed + 2_000_000)
    structural = structural_lift(control, mirror)

    lucario = adversary_gate(root, "gates/lucario", anchor, challenger, LUCARIO_DECK, LUCARIO_MODEL,
                             args.adversary_games, args.workers, args.seed + 3_000_000, args.resume)
    bellibolt = adversary_gate(root, "gates/bellibolt", anchor, challenger, BELLIBOLT_DECK, BELLIBOLT_MODEL,
                               args.adversary_games, args.workers, args.seed + 4_000_000, args.resume)

    authentic = {}
    authentic_pass = True
    for index, entry in enumerate(json.loads((ROOT / "training/external_alakazam_benchmark.json").read_text())["opponents"]):
        base = match_or_load(root / f"gates/authentic/{entry['name']}_baseline.json", args.resume,
                             deck_a=GRIM_DECK, model_a=anchor, deck_b=ROOT / entry["deck"], model_b="",
                             submission_b=ROOT / entry["submission"], games=args.authentic_games,
                             workers=args.workers, seed=args.seed + 5_000_000 + index)
        cand = match_or_load(root / f"gates/authentic/{entry['name']}_candidate.json", args.resume,
                             deck_a=GRIM_DECK, model_a=challenger, deck_b=ROOT / entry["deck"], model_b="",
                             submission_b=ROOT / entry["submission"], games=args.authentic_games,
                             workers=args.workers, seed=args.seed + 6_000_000 + index)
        passed = cand["win_rate_a"] >= base["win_rate_a"] - 0.03 and cand["hero_policy_errors"] == 0
        authentic_pass &= passed
        authentic[entry["name"]] = {"baseline_win_rate": base["win_rate_a"], "candidate_win_rate": cand["win_rate_a"], "passed": passed}

    # Success = no regression (structural + authentic + heldout) AND both new
    # matchups improved. Weak adversaries mean "improved" (point lift > 0) is the
    # bar, not statistical significance.
    no_regression = structural["passed"] and authentic_pass and heldout["passed"] and not kl_rollback
    improved = lucario["improved"] and bellibolt["improved"]
    success = no_regression and improved

    report = {
        "version": 1,
        "status": "recommend_grim_candidate" if success else "no_safe_improvement",
        "success": success, "no_regression": no_regression, "improved_new_matchups": improved,
        "kl_rollback": kl_rollback, "challenger": str(challenger), "sha256": sha256_file(challenger),
        "anchor": str(anchor),
        "gates": {
            "heldout": heldout, "structural_mirror": structural,
            "mirror_seat_results": mirror.get("seat_results_a"),
            "mirror_first_player_results": mirror.get("first_player_results_a"),
            "lucario": lucario, "bellibolt": bellibolt, "authentic_alakazam": authentic,
        },
        "recommendation_only": True, "package_created": False, "submitted": False,
    }
    write_json(root / "final_report.json", report)
    print(json.dumps({"status": report["status"], "success": success, "output": str(root / "final_report.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

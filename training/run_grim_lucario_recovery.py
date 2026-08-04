#!/usr/bin/env python3
"""Azure-only matched Grim PPO recovery after a Lucario sparring model qualifies."""

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
LUCARIO_DECKS = [
    ROOT / "freshstart/decklists/mega_lucario_ex.deck.csv",
    ROOT / "freshstart/decklists/mega_lucario_ex_variant_2.deck.csv",
]


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def grim_league(control: Path, refresh: Path, lucario: Path) -> dict:
    meta = json.loads((ROOT / "training/meta_league.json").read_text())["opponents"]
    diverse = [row for row in meta if row["name"] != "grimmsnarl_marnie" and not row.get("submission")][:10]
    entries = [
        {"name": "original_5k_mirror", "deck": str(GRIM_DECK), "model": str(control), "train_weight": 35},
        {"name": "replay_refresh", "deck": str(GRIM_DECK), "model": str(refresh), "train_weight": 20},
        {"name": "lucario_variant_1", "deck": str(LUCARIO_DECKS[0]), "model": str(lucario), "train_weight": 12.5},
        {"name": "lucario_variant_2", "deck": str(LUCARIO_DECKS[1]), "model": str(lucario), "train_weight": 12.5},
    ]
    for row in diverse:
        entries.append({
            "name": f"meta_{row['name']}", "deck": row["deck"], "model": row.get("model", ""),
            "train_weight": 20.0 / len(diverse),
        })
    return {"version": 1, "purpose": "lucario-gap Grim recovery; frozen opponents only", "opponents": entries}


def match_or_load(path: Path, resume: bool, **kwargs) -> dict:
    if resume and path.exists():
        report = json.loads(path.read_text())
        if int(report.get("games", -1)) == int(kwargs["games"]):
            return report
    return run_match(output=path, **kwargs)


def lucario_matches(root: Path, label: str, grim: Path, lucario: Path, games: int, workers: int, seed: int, resume: bool) -> dict:
    reports = []
    for index, deck in enumerate(LUCARIO_DECKS, 1):
        report = match_or_load(
            root / label / f"variant_{index}.json", resume,
            deck_a=GRIM_DECK, model_a=grim, deck_b=deck, model_b=lucario,
            games=games, workers=workers, seed=seed + index * 100_000,
        )
        reports.append(report)
    games_total = sum(row["games"] for row in reports)
    wins = sum(row["wins_a"] for row in reports)
    return {"games": games_total, "wins": wins, "win_rate": wins / games_total, "variants": reports}


def lucario_lift(baseline: dict, challenger: dict) -> dict:
    interval = newcombe_difference(challenger["wins"], challenger["games"], baseline["wins"], baseline["games"])
    variant_lifts = [
        current["win_rate_a"] - control["win_rate_a"]
        for control, current in zip(baseline["variants"], challenger["variants"])
    ]
    errors = sum(
        row.get("hero_policy_errors", 0) + row.get("opponent_policy_errors", 0)
        for row in challenger["variants"]
    )
    return {
        "lift": challenger["win_rate"] - baseline["win_rate"], "newcombe_95": list(interval),
        "variant_lifts": variant_lifts, "policy_errors": errors,
        "passed": all(value > 0 for value in variant_lifts) and interval[0] > 0 and errors == 0,
    }


def train_candidate(args, root: Path, name: str, anchor: Path, seed: int, manifest: dict) -> dict:
    candidate_dir = root / "candidates" / name
    report_path = candidate_dir / "candidate.json"
    if args.resume and report_path.exists():
        report = json.loads(report_path.read_text())
        output = Path(report["output"])
        if output.exists() and sha256_file(output) == report["sha256"]:
            return report
    rollouts_dir = candidate_dir / "rollouts"
    subprocess.run([
        sys.executable, "training/collect_sharded.py", "--model", str(anchor), "--hero-deck", str(GRIM_DECK),
        "--league", str(root / "grim_league.json"), "--games", "5000", "--shard-size", "500",
        "--workers", str(args.workers), "--temperature", "0.70", "--seed", str(seed),
        "--output-dir", str(rollouts_dir),
    ], cwd=ROOT, check=True)
    output = candidate_dir / "policy_weights.npz"
    result = subprocess.run([
        sys.executable, "training/train_ppo.py", "--initial-model", str(anchor),
        "--rollouts", str(rollouts_dir / "rollouts.jsonl.gz"), "--bc-shard", args.fresh,
        "--require-card", "648", "--output", str(output), "--epochs", "1", "--learning-rate", "1e-5",
        "--bc-weight", "0.50", "--target-kl", "0.01", "--hard-kl", "0.02", "--seed", str(seed + 50),
    ], cwd=ROOT, check=True, text=True, capture_output=True)
    (candidate_dir / "train.log").write_text(result.stdout + result.stderr)
    rollback = "rolled_back': True" in result.stdout
    decisions = {
        split: evaluate_model_pair(anchor, output, args.fresh, manifest, split, 256, "cpu", 0)
        for split in ("internal_validation", "team_holdout", "temporal")
    }
    gate = heldout_gate(decisions)
    report = {
        "name": name, "anchor": str(anchor), "seed": seed, "output": str(output), "sha256": sha256_file(output),
        "kl_rollback": rollback, "decision_reports": decisions, "heldout_gate": gate,
        "eligible": gate["passed"] and not rollback,
    }
    write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lucario-report", required=True)
    parser.add_argument("--control", default="artifacts/grimmsnarl_5k_reference.npz")
    parser.add_argument("--refresh", default="artifacts/5k_replay_refresh_20260802/full/candidates/lr1e-04_seed20260803/policy_weights.npz")
    parser.add_argument("--fresh", default="data/processed/elite-2026-07-30-31-v2ctl.jsonl.gz")
    parser.add_argument("--split-manifest", default="artifacts/5k_replay_refresh_20260802/full/split_manifest.json")
    parser.add_argument("--output-dir", default="artifacts/lucario_gap_20260803/grim")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260830)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    enforce_azure_workload(workload_size=5_000)
    root = Path(args.output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    lucario_report = json.loads(Path(args.lucario_report).read_text())
    if lucario_report.get("status") != "qualified":
        report = {
            "version": 1, "status": "skipped_unqualified_lucario", "success": False,
            "recommendation_only": True, "package_created": False, "submitted": False,
        }
        write_json(root / "final_report.json", report)
        return 0
    lucario = Path(lucario_report["selected_model"]).resolve()
    control, refresh = Path(args.control).resolve(), Path(args.refresh).resolve()
    write_json(root / "grim_league.json", grim_league(control, refresh, lucario))
    manifest = json.loads(Path(args.split_manifest).read_text())

    candidates = []
    for anchor_name, anchor in (("5k", control), ("refresh", refresh)):
        for offset in range(3):
            seed = args.seed + offset
            candidates.append(train_candidate(args, root, f"{anchor_name}_seed{seed}", anchor, seed, manifest))

    eligible = [row for row in candidates if row["eligible"]]
    screened = []
    baseline_cache = {}
    for index, candidate in enumerate(eligible):
        anchor = Path(candidate["anchor"])
        anchor_key = anchor.name + sha256_file(anchor)[:8]
        baseline = baseline_cache.setdefault(anchor_key, lucario_matches(
            root, f"screen/baseline_{anchor_key}", anchor, lucario, 500, args.workers,
            args.seed + 1_000_000 + index * 10_000, args.resume,
        ))
        challenger = lucario_matches(
            root, f"screen/{candidate['name']}", Path(candidate["output"]), lucario, 500, args.workers,
            args.seed + 2_000_000 + index * 10_000, args.resume,
        )
        mirror = match_or_load(
            root / "screen" / f"{candidate['name']}_mirror.json", args.resume,
            deck_a=GRIM_DECK, model_a=candidate["output"], deck_b=GRIM_DECK, model_b=anchor,
            games=500, workers=args.workers, seed=args.seed + 3_000_000 + index * 10_000,
        )
        screened.append({"candidate": candidate, "baseline": baseline, "challenger": challenger, "mirror": mirror})
    screened.sort(key=lambda row: (row["challenger"]["win_rate"] - row["baseline"]["win_rate"], row["mirror"]["win_rate_a"]), reverse=True)

    semifinals = []
    for index, row in enumerate(screened[:3]):
        candidate = row["candidate"]
        anchor = Path(candidate["anchor"])
        baseline = lucario_matches(root, f"semifinal/baseline_{candidate['name']}", anchor, lucario, 2_000, args.workers, args.seed + 4_000_000 + index * 10_000, args.resume)
        challenger = lucario_matches(root, f"semifinal/{candidate['name']}", Path(candidate["output"]), lucario, 2_000, args.workers, args.seed + 4_000_000 + index * 10_000, args.resume)
        semifinals.append({"candidate": candidate, "baseline": baseline, "challenger": challenger, "point_lift": challenger["win_rate"] - baseline["win_rate"]})
    semifinals.sort(key=lambda row: row["point_lift"], reverse=True)
    finalist = semifinals[0]["candidate"] if semifinals and semifinals[0]["point_lift"] > 0 else None

    final = None
    if finalist:
        anchor, challenger_model = Path(finalist["anchor"]), Path(finalist["output"])
        structural_control = match_or_load(root / "final/structural_control.json", args.resume, deck_a=GRIM_DECK, model_a=anchor, deck_b=GRIM_DECK, model_b=anchor, games=10_000, workers=args.workers, seed=args.seed + 5_000_000)
        mirror = match_or_load(root / "final/challenger_vs_anchor.json", args.resume, deck_a=GRIM_DECK, model_a=challenger_model, deck_b=GRIM_DECK, model_b=anchor, games=10_000, workers=args.workers, seed=args.seed + 6_000_000)
        structural = structural_lift(structural_control, mirror)
        lucario_base = lucario_matches(root, "final/lucario_baseline", anchor, lucario, 5_000, args.workers, args.seed + 7_000_000, args.resume)
        lucario_candidate = lucario_matches(root, "final/lucario_candidate", challenger_model, lucario, 5_000, args.workers, args.seed + 8_000_000, args.resume)
        lift = lucario_lift(lucario_base, lucario_candidate)
        authentic = {}
        authentic_pass = True
        for index, entry in enumerate(json.loads((ROOT / "training/external_alakazam_benchmark.json").read_text())["opponents"]):
            baseline = match_or_load(root / f"final/authentic/{entry['name']}_baseline.json", args.resume, deck_a=GRIM_DECK, model_a=anchor, deck_b=ROOT / entry["deck"], model_b="", submission_b=ROOT / entry["submission"], games=500, workers=args.workers, seed=args.seed + 9_000_000 + index)
            current = match_or_load(root / f"final/authentic/{entry['name']}_candidate.json", args.resume, deck_a=GRIM_DECK, model_a=challenger_model, deck_b=ROOT / entry["deck"], model_b="", submission_b=ROOT / entry["submission"], games=500, workers=args.workers, seed=args.seed + 9_000_000 + index)
            passed = current["win_rate_a"] >= baseline["win_rate_a"] - 0.03 and current["hero_policy_errors"] == 0
            authentic_pass &= passed
            authentic[entry["name"]] = {"baseline": baseline, "candidate": current, "passed": passed}
        success = structural["passed"] and lift["passed"] and authentic_pass and finalist["heldout_gate"]["passed"]
        final = {"candidate": finalist, "mirror": mirror, "structural_gate": structural, "lucario_baseline": lucario_base, "lucario_candidate": lucario_candidate, "lucario_lift": lift, "authentic": authentic, "success": success}

    success = bool(final and final["success"])
    report = {
        "version": 1, "status": "recommend_grim_candidate" if success else "no_safe_improvement",
        "success": success, "candidates": candidates,
        "screen": [{"name": row["candidate"]["name"], "baseline": row["baseline"], "challenger": row["challenger"], "mirror": row["mirror"]} for row in screened],
        "semifinals": [{"name": row["candidate"]["name"], "point_lift": row["point_lift"]} for row in semifinals],
        "final": final, "recommendation_only": True, "package_created": False, "submitted": False,
    }
    write_json(root / "final_report.json", report)
    print(json.dumps({"status": report["status"], "output": str(root / "final_report.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

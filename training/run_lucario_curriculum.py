#!/usr/bin/env python3
"""Resumable two-variant Lucario sparring curriculum and qualification gate."""

from __future__ import annotations

import argparse
import ast
import gzip
import json
import math
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from training.azure_guard import enforce_azure_workload
from training.evaluate import wilson
from training.lucario_data import build_replay_view, sha256_file
from training.replay_refresh import run_match


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DECKS = [
    "freshstart/decklists/mega_lucario_ex.deck.csv",
    "freshstart/decklists/mega_lucario_ex_variant_2.deck.csv",
]
DEFAULT_GRIM_MODELS = [
    "artifacts/grimmsnarl_5k_reference.npz",
    "artifacts/5k_replay_refresh_20260802/full/candidates/lr1e-04_seed20260803/policy_weights.npz",
    "artifacts/sparring_gen4/grimmsnarl_gen4_sparred.npz",
    "artifacts/coevo_run_04/round_001/grimmsnarl_marnie_challenger.npz",
]
GRIM_DECK = "freshstart/decklists/grimmsnarl_marnie.deck.csv"


def resolved(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else (ROOT / value).resolve()


def write_json(path: str | Path, value: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def run_logged(command: list[str], log_path: Path) -> str:
    result = subprocess.run(command, cwd=ROOT, check=True, text=True, capture_output=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(result.stdout + result.stderr)
    return result.stdout


def parse_best_validation_loss(stdout: str) -> float:
    losses = []
    for line in stdout.splitlines():
        try:
            value = ast.literal_eval(line)
        except (ValueError, SyntaxError):
            continue
        if isinstance(value, dict) and "validation_loss" in value:
            losses.append(float(value["validation_loss"]))
    if not losses:
        raise RuntimeError("BC training log contained no validation loss")
    return min(losses)


def variant_game_allocation(stage_games: int) -> dict[str, int]:
    if stage_games <= 0 or stage_games % 2:
        raise ValueError("stage games must be a positive even number")
    return {"variant_1": stage_games // 2, "variant_2": stage_games // 2}


def load_resumable_stage(report_path: Path) -> tuple[dict, Path] | None:
    if not report_path.exists():
        return None
    report = json.loads(report_path.read_text())
    candidate = resolved(report["candidate"]["path"])
    if not candidate.exists() or sha256_file(candidate) != report["candidate"]["sha256"]:
        raise RuntimeError(f"resume checkpoint verification failed for {candidate}")
    return report, candidate


def evaluate_imitation(model: Path, shard: Path, split: str, output: Path) -> dict:
    command = [
        sys.executable,
        str(ROOT / "training" / "evaluate_imitation.py"),
        str(shard),
        "--model", str(model),
        "--require-card", "678",
        "--split", split,
        "--output", str(output),
    ]
    subprocess.run(command, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    return json.loads(output.read_text())


def prepare_bc(args, root: Path, shard: Path) -> tuple[Path, dict]:
    selection_path = root / "bc" / "selection.json"
    if args.resume and selection_path.exists():
        selection = json.loads(selection_path.read_text())
        model = resolved(selection["selected_model"])
        if model.exists() and sha256_file(model) == selection["selected_sha256"]:
            return model, selection

    candidates = []
    specifications = [
        (f"{kind}_seed{seed}", initial, seed)
        for kind, initial in (("fresh", None), ("initialized", resolved(args.existing_bc)))
        for seed in (args.seed, args.seed + 1, args.seed + 2)
    ]
    for name, initial, seed in specifications:
        output = root / "bc" / name / "policy_weights.npz"
        command = [
            sys.executable,
            str(ROOT / "training" / "train_bc.py"),
            str(shard),
            "--output", str(output),
            "--epochs", str(args.bc_epochs),
            "--feature-version", "2",
            "--require-card", "678",
            "--seed", str(seed),
        ]
        if args.bc_max_records:
            command.extend(["--max-records", str(args.bc_max_records)])
        if initial is not None:
            command.extend(["--initial-model", str(initial)])
        stdout = run_logged(command, root / "bc" / name / "train.log")
        metrics = evaluate_imitation(output, shard, "validation", root / "bc" / name / "validation.json")
        unseen = evaluate_imitation(output, shard, "unseen_team", root / "bc" / name / "unseen_team.json")
        temporal = evaluate_imitation(output, shard, "temporal", root / "bc" / name / "temporal.json")
        candidates.append({
            "name": name,
            "model": str(output),
            "sha256": sha256_file(output),
            "validation_loss": parse_best_validation_loss(stdout),
            "validation": metrics["overall"],
            "unseen_team": unseen["overall"],
            "temporal": temporal["overall"],
            "initial_model": str(initial) if initial else None,
        })

    control = resolved(args.existing_bc)
    control_metrics = evaluate_imitation(control, shard, "validation", root / "bc" / "control_validation.json")
    selected = min(candidates, key=lambda row: (
        row["validation_loss"], -row["unseen_team"]["exact_rate"],
        -row["temporal"]["exact_rate"], -row["validation"]["count_accuracy"],
    ))
    selection = {
        "version": 1,
        "candidates": candidates,
        "control": {
            "model": str(control),
            "sha256": sha256_file(control),
            "validation": control_metrics["overall"],
        },
        "selected": selected["name"],
        "selected_model": selected["model"],
        "selected_sha256": selected["sha256"],
    }
    write_json(selection_path, selection)
    return Path(selected["model"]), selection


def frozen_league(models: list[Path]) -> dict:
    preferred = [60.0, 20.0, 10.0, 10.0]
    weights = preferred[: len(models)]
    if len(models) > len(weights):
        weights.extend([25.0] * (len(models) - len(weights)))
    total = sum(weights)
    return {
        "version": 1,
        "purpose": "Faithful Lucario curriculum against frozen Grimmsnarl checkpoints",
        "opponents": [
            {
                "name": f"grim_frozen_{index + 1}",
                "deck": str(resolved(GRIM_DECK)),
                "model": str(model),
                "model_sha256": sha256_file(model),
                "train_weight": 100.0 * weights[index] / total,
            }
            for index, model in enumerate(models)
        ],
    }


def merge_rollouts(inputs: list[Path], output: Path) -> dict:
    temporary = output.with_name(output.name + ".tmp")
    decisions = 0
    trajectories = set()
    per_variant = {}
    with gzip.open(temporary, "wt", encoding="utf-8", compresslevel=6) as destination:
        for index, source in enumerate(inputs, 1):
            variant = f"variant_{index}"
            local_decisions = 0
            with gzip.open(source, "rt", encoding="utf-8") as handle:
                for line in handle:
                    row = json.loads(line)
                    row["lucario_variant"] = variant
                    destination.write(json.dumps(row, separators=(",", ":")) + "\n")
                    trajectories.add(str(row.get("trajectory_id", row.get("episode_id"))))
                    decisions += 1
                    local_decisions += 1
            per_variant[variant] = {"source": str(source), "decisions": local_decisions}
    os.replace(temporary, output)
    return {
        "output": str(output),
        "sha256": sha256_file(output),
        "decisions": decisions,
        "trajectories_with_decisions": len(trajectories),
        "variants": per_variant,
    }


def aggregate_matchups(reports: list[dict]) -> dict:
    games = sum(int(row["games"]) for row in reports)
    wins = sum(int(row["wins_a"]) for row in reports)
    variants = {}
    policy_errors = 0
    for row in reports:
        bucket = variants.setdefault(row["variant"], {"games": 0, "wins": 0})
        bucket["games"] += int(row["games"])
        bucket["wins"] += int(row["wins_a"])
        policy_errors += int(row.get("hero_policy_errors", 0)) + int(row.get("opponent_policy_errors", 0))
    for bucket in variants.values():
        bucket["win_rate"] = bucket["wins"] / max(1, bucket["games"])
    lower, upper = wilson(wins, games)
    return {
        "games": games,
        "wins": wins,
        "win_rate": wins / max(1, games),
        "wilson_95": [lower, upper],
        "variants": variants,
        "policy_errors": policy_errors,
    }


def qualification(
    frozen: dict,
    fidelity_delta: float | dict,
    kl_rollback: bool,
    unseen: dict | None = None,
    minimum: float = 0.40,
    pooled_minimum: float = 0.40,
    variant_minimum: float = 0.35,
    fidelity_tolerance: float = 0.03,
) -> dict:
    checks = {
        "frozen_pooled_minimum": frozen["win_rate"] >= pooled_minimum,
        "frozen_variant_floor": all(row["win_rate"] >= variant_minimum for row in frozen["variants"].values()),
        "fidelity": all(value >= -fidelity_tolerance for value in fidelity_delta.values())
        if isinstance(fidelity_delta, dict) else fidelity_delta >= -fidelity_tolerance,
        "zero_policy_errors": frozen["policy_errors"] == 0 and (unseen is None or unseen["policy_errors"] == 0),
        "no_kl_rollback": not kl_rollback,
        "unseen_optional_check": unseen is None or unseen["policy_errors"] == 0,
        "unseen_pooled_minimum": unseen is None or unseen["win_rate"] >= minimum,
    }
    reasons = [name for name, passed in checks.items() if not passed]
    return {"passed": not reasons, "checks": checks, "failed_checks": reasons}


def recoverable_understrength(report: dict) -> bool:
    checks = report["qualification"]["checks"]
    return (
        min(float(row["win_rate"]) for row in report["frozen_evaluation"]["variants"].values()) >= 0.20
        and checks["fidelity"]
        and checks["no_kl_rollback"]
    )


def curriculum_status(report: dict, completed_games: int, maximum_games: int) -> str:
    if report["qualification"]["passed"]:
        return "qualified"
    if min(row["win_rate"] for row in report["frozen_evaluation"]["variants"].values()) < 0.20:
        return "failed_understrength"
    if completed_games >= maximum_games:
        return "failed_at_budget_cap"
    return "needs_more_training"


def evaluate_pool(args, stage_dir: Path, model: Path, decks: list[Path], grim_models: list[Path], label: str) -> dict:
    reports = []
    for variant_index, deck in enumerate(decks, 1):
        for grim_index, grim in enumerate(grim_models, 1):
            output = stage_dir / "evaluation" / label / f"variant_{variant_index}_grim_{grim_index}.json"
            report = run_match(
                deck_a=deck,
                model_a=model,
                deck_b=resolved(GRIM_DECK),
                model_b=grim,
                games=args.games_per_eval,
                workers=args.workers,
                output=output,
                seed=args.seed + variant_index * 10_000 + grim_index * 1_000 + int(stage_dir.name.split("_")[-1]),
            )
            reports.append({
                **report,
                "variant": f"variant_{variant_index}",
                "grim_model": str(grim),
                "grim_sha256": sha256_file(grim),
            })
    aggregate = aggregate_matchups(reports)
    aggregate["reports"] = reports
    return aggregate


def collect_variant(args, stage_dir: Path, model: Path, deck: Path, league_path: Path, variant_index: int, games: int) -> Path:
    output_dir = stage_dir / "rollouts" / f"variant_{variant_index}"
    shard_size = math.gcd(games, args.shard_size)
    command = [
        sys.executable,
        str(ROOT / "training" / "collect_sharded.py"),
        "--model", str(model),
        "--hero-deck", str(deck),
        "--league", str(league_path),
        "--games", str(games),
        "--shard-size", str(shard_size),
        "--workers", str(args.workers),
        "--temperature", str(args.temperature),
        "--seed", str(args.seed + int(stage_dir.name.split("_")[-1]) * 100_000 + variant_index * 10_000),
        "--output-dir", str(output_dir),
    ]
    if args.allow_local_smoke:
        command.append("--allow-local-smoke")
    subprocess.run(command, cwd=ROOT, check=True)
    return output_dir / "rollouts.jsonl.gz"


def build_grim_handoff(base_league: Path, lucario_model: Path, decks: list[Path], initial_grim: Path, output: Path) -> dict:
    league = deepcopy(json.loads(base_league.read_text()))
    entries = league["opponents"]
    existing_total = sum(float(row.get("train_weight", 0.0)) for row in entries)
    if existing_total <= 0:
        raise ValueError("base Grim league must have positive train weights")
    for row in entries:
        row["train_weight"] = float(row.get("train_weight", 0.0)) * 75.0 / existing_total
    for index, deck in enumerate(decks, 1):
        entries.append({
            "name": f"mega_lucario_qualified_variant_{index}",
            "deck": str(deck),
            "model": str(lucario_model),
            "meta_weight": 0,
            "train_weight": 12.5,
            "evaluate": False,
            "plan": "Qualified faithful Lucario matchup curriculum opponent.",
        })
    write_json(output, league)
    handoff = {
        "version": 1,
        "initial_grim_model": str(initial_grim),
        "lucario_model": str(lucario_model),
        "lucario_sha256": sha256_file(lucario_model),
        "league": str(output),
        "lucario_combined_train_weight": 25.0,
        "requirements": {
            "improve_lucario_matchup": True,
            "maximum_non_lucario_meta_regression": 0.03,
        },
    }
    write_json(output.with_name("grim_handoff.json"), handoff)
    return handoff


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bc-shard", default="artifacts/lucario_bc/lucario_raw.jsonl.gz")
    parser.add_argument("--deck", action="append", default=[])
    parser.add_argument("--grim-model", action="append", default=[])
    parser.add_argument("--unseen-grim", default="")
    parser.add_argument("--existing-bc", default="artifacts/lucario_bc/lucario_bc.npz")
    parser.add_argument("--base-grim-league", default="training/meta_league.json")
    parser.add_argument("--output-dir", default="artifacts/lucario_curriculum")
    parser.add_argument("--stage-games", type=int, default=5_000)
    parser.add_argument("--max-games", type=int, default=20_000)
    parser.add_argument("--games-per-eval", type=int, default=500)
    parser.add_argument("--shard-size", type=int, default=500)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--temperature", type=float, default=0.70)
    parser.add_argument("--bc-epochs", type=int, default=8)
    parser.add_argument("--bc-max-records", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20260803)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--allow-local-smoke", action="store_true")
    args = parser.parse_args()
    if args.stage_games <= 0 or args.stage_games % 2 or args.max_games < args.stage_games or args.max_games % args.stage_games:
        parser.error("stage-games must be positive/even and max-games must be a positive multiple of it")
    enforce_azure_workload(allow_local_smoke=args.allow_local_smoke, workload_size=args.stage_games)

    decks = [resolved(path) for path in (args.deck or DEFAULT_DECKS)]
    grim_models = [resolved(path) for path in (args.grim_model or DEFAULT_GRIM_MODELS)]
    if len(decks) != 2:
        parser.error("exactly two --deck values are required")
    missing = [str(path) for path in [*decks, *grim_models, resolved(args.bc_shard), resolved(args.existing_bc)] if not path.exists()]
    if missing:
        parser.error(f"missing required inputs: {missing}")
    unseen = resolved(args.unseen_grim) if args.unseen_grim else None
    if unseen is not None and not unseen.exists():
        parser.error(f"unseen Grim checkpoint does not exist: {unseen}")

    root = resolved(args.output_dir)
    root.mkdir(parents=True, exist_ok=True)
    filtered_shard = root / "data" / "lucario_top_two.jsonl.gz"
    data_manifest = root / "data" / "manifest.json"
    if not (args.resume and filtered_shard.exists() and data_manifest.exists()):
        build_replay_view(resolved(args.bc_shard), decks, filtered_shard, data_manifest, args.seed)
    selected_bc, bc_selection = prepare_bc(args, root, filtered_shard)
    selected_heldout = {
        split: evaluate_imitation(selected_bc, filtered_shard, split, root / "bc" / f"selected_{split}.json")
        for split in ("unseen_team", "temporal")
    }

    league_path = root / "frozen_grim_league.json"
    write_json(league_path, frozen_league(grim_models))
    baseline = evaluate_pool(args, root / "stage_000", selected_bc, decks, grim_models[:1], "baseline_5k")
    write_json(root / "bc" / "baseline_vs_5k.json", baseline)
    current_model = selected_bc
    completed_games = 0
    stage_reports = []
    final_status = "needs_more_training"
    while completed_games < args.max_games:
        stage_number = completed_games // args.stage_games + 1
        stage_dir = root / f"stage_{stage_number:03d}"
        stage_report_path = stage_dir / "report.json"
        resumed = load_resumable_stage(stage_report_path) if args.resume else None
        if resumed is not None:
            report, candidate = resumed
        else:
            allocation = variant_game_allocation(args.stage_games)
            streams = [
                collect_variant(args, stage_dir, current_model, deck, league_path, index, allocation[f"variant_{index}"])
                for index, deck in enumerate(decks, 1)
            ]
            merged = merge_rollouts(streams, stage_dir / "rollouts" / "combined.jsonl.gz")
            write_json(stage_dir / "rollouts" / "audit.json", merged)
            candidate = stage_dir / "policy_weights.npz"
            command = [
                sys.executable,
                str(ROOT / "training" / "train_ppo.py"),
                "--initial-model", str(current_model),
                "--rollouts", merged["output"],
                "--bc-shard", str(filtered_shard),
                "--require-card", "678",
                "--output", str(candidate),
                "--epochs", "1",
                "--learning-rate", "1e-5",
                "--bc-weight", "0.50",
                "--target-kl", "0.01",
                "--hard-kl", "0.02",
                "--seed", str(args.seed + stage_number * 1_000_000),
            ]
            if args.allow_local_smoke:
                command.append("--allow-local-smoke")
            ppo_stdout = run_logged(command, stage_dir / "train.log")
            kl_rollback = "hard_kl_stop" in ppo_stdout and "rolled_back': True" in ppo_stdout
            candidate_heldout = {
                split: evaluate_imitation(candidate, filtered_shard, split, stage_dir / "evaluation" / f"{split}.json")
                for split in ("unseen_team", "temporal")
            }
            fidelity_delta = {
                f"{split}_{metric}": candidate_heldout[split]["overall"][metric] - selected_heldout[split]["overall"][metric]
                for split in ("unseen_team", "temporal")
                for metric in ("exact_rate", "count_accuracy")
            }
            frozen = evaluate_pool(args, stage_dir, candidate, decks, grim_models[:1], "frozen_5k")
            unseen_result = evaluate_pool(args, stage_dir, candidate, decks, [unseen], "unseen") if unseen else None
            gate = qualification(frozen, fidelity_delta, kl_rollback, unseen_result)
            report = {
                "version": 1,
                "stage": stage_number,
                "stage_games": args.stage_games,
                "scheduled_games": allocation,
                "cumulative_games": completed_games + args.stage_games,
                "initial_model": {"path": str(current_model), "sha256": sha256_file(current_model)},
                "candidate": {"path": str(candidate), "sha256": sha256_file(candidate)},
                "rollouts": merged,
                "fidelity": {
                    "anchor": {key: value["overall"] for key, value in selected_heldout.items()},
                    "candidate": {key: value["overall"] for key, value in candidate_heldout.items()},
                    "deltas": fidelity_delta,
                },
                "kl_rollback": kl_rollback,
                "frozen_evaluation": frozen,
                "unseen_evaluation": unseen_result,
                "qualification": gate,
            }
            write_json(stage_report_path, report)
        completed_games = int(report["cumulative_games"])
        stage_reports.append(str(stage_report_path))
        current_model = candidate
        final_status = curriculum_status(report, completed_games, args.max_games)
        if final_status == "qualified":
            break
        if not recoverable_understrength(report):
            break

    handoff = None
    if final_status == "qualified":
        handoff = build_grim_handoff(
            resolved(args.base_grim_league), current_model, decks, unseen or grim_models[0],
            root / "next_grim_league.json",
        )
    final = {
        "version": 1,
        "status": final_status,
        "selected_bc": bc_selection,
        "selected_model": str(current_model),
        "selected_sha256": sha256_file(current_model),
        "cumulative_games": completed_games,
        "maximum_games": args.max_games,
        "baseline_vs_5k": baseline,
        "stages": stage_reports,
        "unseen_grim": str(unseen) if unseen else None,
        "grim_handoff": handoff,
        "recommendation_only": True,
        "package_created": False,
        "submitted": False,
    }
    write_json(root / "final_report.json", final)
    print(json.dumps({"status": final_status, "model": str(current_model), "report": str(root / "final_report.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

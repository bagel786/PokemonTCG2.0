#!/usr/bin/env python3
"""Build the canonical paired-game table and prospectively specified statistics.

The fresh-confirmation estimand is the equal-weight mean of candidate-minus-
control win indicators across the seven opponent by two actual-order strata.
All confidence intervals in the fresh tables use a paired, within-stratum
percentile bootstrap.  McNemar tests use the exact two-sided binomial test.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
from collections import defaultdict
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_CANDIDATE = "83489e0c80c631763c65375d2a7a34d28d6aa9fbb1d11e89d130c83b1e27f1c0"
EXPECTED_CONTROL = "13426288358d597ead809e45c364c7f7b9274a6eebf55ddd942142e3326535c3"
EXPECTED_ENGINE = "867e3f9bb87e0b48889a44b5d4b04f5d2d434b2a0788d1b2bcfe0caebcb5ab78"
EXPECTED_PRODUCTION_ENGINE = "7a157f045d333f99d1996d49c12bdbdd148072a619af246385c7295518776e30"
EXPECTED_RUNNER = "fa60021b0906401aeb2c7c33e0f65f586eff256d83d689d688a86a40480e1341"
EXPECTED_FRESH = {
    "grim_b0.json": ("B0", "Grim", "baseline", "0c15b56adf3b09c654505a152309fdc9f8401579a495da714347d98ae735003c", 202608230000, 8),
    "grim_d842_runtime.json": ("d842_runtime", "Grim", "internal_learned", "7db753d6610930d8bd9694b4b9bece5ac48733b825422a3e399c18077b55e64e", 202608231000, 8),
    "grim_master_v1.json": ("master_v1", "Grim", "internal_learned", "8a06ebab47cc60ed981dfada85972eb8a62e732e349f01c2a3085262079f06e8", 202608232000, 8),
    "grim_replay_refresh.json": ("replay_refresh", "Grim", "internal_learned", "30e45955b67893514c8ee077cac15d46fc207efe781cbce1b94242defda4cbdc", 202608233000, 8),
    "starmie_v2_boss_atk.json": ("starmie", "Other", "external", "1b73779da7dcc93c8f121090bb0f1ae2d9b10b798ca4c70447b0ce1d6d01c0db", 202608234000, 4),
    "dipplin_d1.json": ("dipplin", "Other", "external", "076ae8de12d2d6c4a170b47b2d2f9cf538c1d318a05bb2e81f13da9be2cd2026", 202608235000, 4),
    "alakazam_2_4a_no_search.json": ("alakazam_no_search", "Other", "external", "5d44338891094988ca15f0c26d5187316549facd64a7bfbac04aa0048424e8c7", 202608236000, 8),
}
DISPLAY_LABELS = {
    "B0": "Matched 1", "d842_runtime": "Matched 2",
    "master_v1": "Matched 3", "replay_refresh": "Matched 4",
    "starmie": "Broader 1", "dipplin": "Broader 2",
    "alakazam_no_search": "Broader 3",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def outcome(row: dict) -> str:
    if int(row.get("draw", 0)):
        return "draw"
    return "win" if int(row.get("win", 0)) else "loss"


def pair_rows(payload: dict, source: Path, experiment: str, opponent: str,
              family: str, role: str, expected_base_seed: int | None = None,
              require_zero_errors: bool = False) -> list[dict]:
    grouped: dict[tuple[str, int], dict[str, dict]] = defaultdict(dict)
    for row in payload["rows"]:
        key = (str(row["actual_order"]), int(row["pair_index"]))
        arm = str(row["arm"])
        if arm not in {"candidate", "control"}:
            raise ValueError(f"{source}: invalid arm {arm!r}")
        if arm in grouped[key]:
            raise ValueError(f"{source}: duplicate arm {arm} at {key}")
        grouped[key][arm] = row
    expected = int(payload["overall"]["pairs"])
    if len(payload["rows"]) != 2 * expected:
        raise ValueError(f"{source}: expected {2 * expected} rows, got {len(payload['rows'])}")
    if len(grouped) != expected:
        raise ValueError(f"{source}: {len(grouped)} paired keys, expected {expected}")
    source_rel = str(source.relative_to(ROOT))
    source_sha = sha256_file(source)
    records = []
    for (actual_order, pair_index), arms in sorted(grouped.items()):
        if set(arms) != {"candidate", "control"}:
            raise ValueError(f"{source}: incomplete pair {(actual_order, pair_index)}")
        candidate, control = arms["candidate"], arms["control"]
        for field in ("seed", "actual_order", "pair_index", "physical_seat"):
            if candidate.get(field) != control.get(field):
                raise ValueError(f"{source}: CRN mismatch in {field} at {(actual_order, pair_index)}")
        if expected_base_seed is not None:
            if actual_order not in {"first", "second"} or not 0 <= pair_index < 200:
                raise ValueError(f"{source}: out-of-schedule pair {(actual_order, pair_index)}")
            expected_seed = expected_base_seed + (1_000_000 if actual_order == "second" else 0) + pair_index
            if int(candidate["seed"]) != expected_seed:
                raise ValueError(f"{source}: seed mismatch at {(actual_order, pair_index)}")
            if int(candidate["physical_seat"]) != pair_index % 2:
                raise ValueError(f"{source}: physical-seat mismatch at {(actual_order, pair_index)}")
        for arm_name, row in (("candidate", candidate), ("control", control)):
            win = int(row.get("win", 0))
            draw = int(row.get("draw", 0))
            if win not in {0, 1} or draw not in {0, 1} or win + draw > 1:
                raise ValueError(f"{source}: invalid outcome for {arm_name} at {(actual_order, pair_index)}")
            if require_zero_errors and (
                int(row.get("hero_policy_errors", 0)) != 0
                or int(row.get("opponent_policy_errors", 0)) != 0
            ):
                raise ValueError(f"{source}: policy error for {arm_name} at {(actual_order, pair_index)}")
        records.append({
            "experiment": experiment,
            "candidate_hash": payload["candidate_sha256"],
            "control_hash": payload["control_sha256"],
            "opponent": opponent,
            "opponent_family": family,
            "opponent_role": role,
            "opponent_hash": payload["opponent_sha256"],
            "seed": int(candidate["seed"]),
            "pair_index": pair_index,
            "actual_order": actual_order,
            "physical_seat": int(candidate["physical_seat"]),
            "candidate_outcome": outcome(candidate),
            "control_outcome": outcome(control),
            "candidate_win": int(candidate.get("win", 0)),
            "control_win": int(control.get("win", 0)),
            "candidate_draw": int(candidate.get("draw", 0)),
            "control_draw": int(control.get("draw", 0)),
            "candidate_error": int(candidate.get("hero_policy_errors", 0)),
            "control_error": int(control.get("hero_policy_errors", 0)),
            "candidate_opponent_error": int(candidate.get("opponent_policy_errors", 0)),
            "control_opponent_error": int(control.get("opponent_policy_errors", 0)),
            "latency_candidate_ms": "",
            "latency_control_ms": "",
            "source_artifact": source_rel,
            "source_sha256": source_sha,
        })
    return records


def exact_mcnemar(candidate_only: int, control_only: int) -> float:
    n = candidate_only + control_only
    if n == 0:
        return 1.0
    lower = min(candidate_only, control_only)
    tail = sum(math.comb(n, index) for index in range(lower + 1)) / (2 ** n)
    return min(1.0, 2.0 * tail)


def holm(p_values: list[float]) -> list[float]:
    m = len(p_values)
    adjusted = [0.0] * m
    running = 0.0
    for rank, index in enumerate(sorted(range(m), key=p_values.__getitem__)):
        running = max(running, (m - rank) * p_values[index])
        adjusted[index] = min(1.0, running)
    return adjusted


def bootstrap_cells(cells: list[np.ndarray], iterations: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    samples = np.empty((len(cells), iterations), dtype=np.float32)
    batch = 1_000
    for cell_index, values in enumerate(cells):
        n = len(values)
        for start in range(0, iterations, batch):
            stop = min(iterations, start + batch)
            indices = rng.integers(0, n, size=(stop - start, n))
            samples[cell_index, start:stop] = values[indices].mean(axis=1)
    return samples


def summarize(group: list[dict], bootstrap: np.ndarray | None = None) -> dict:
    differences = np.asarray(
        [row["candidate_win"] - row["control_win"] for row in group], dtype=np.float64
    )
    candidate_only = int(sum(value == 1 for value in differences))
    control_only = int(sum(value == -1 for value in differences))
    result = {
        "pairs": len(group),
        "candidate_wins": int(sum(row["candidate_win"] for row in group)),
        "control_wins": int(sum(row["control_win"] for row in group)),
        "candidate_draws": int(sum(row["candidate_draw"] for row in group)),
        "control_draws": int(sum(row["control_draw"] for row in group)),
        "candidate_only_wins": candidate_only,
        "control_only_wins": control_only,
        "effect": float(differences.mean()),
        "mcnemar_exact_two_sided_p": exact_mcnemar(candidate_only, control_only),
        "candidate_errors": int(sum(row["candidate_error"] for row in group)),
        "control_errors": int(sum(row["control_error"] for row in group)),
        "opponent_errors": int(sum(
            row["candidate_opponent_error"] + row["control_opponent_error"] for row in group
        )),
    }
    if bootstrap is not None:
        result["paired_bootstrap_95_ci"] = [
            float(np.percentile(bootstrap, 2.5)),
            float(np.percentile(bootstrap, 97.5)),
        ]
    return result


def write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fieldnames or list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def escape_tex(value: str) -> str:
    return value.replace("_", r"\_")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fresh-dir", type=Path,
        default=ROOT / "paper/data/fresh_confirmation/raw",
    )
    parser.add_argument(
        "--canonical", type=Path, default=ROOT / "paper/data/canonical_results.csv",
    )
    parser.add_argument(
        "--summary", type=Path, default=ROOT / "paper/data/statistical_summary.json",
    )
    parser.add_argument("--iterations", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=20260823)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    canonical: list[dict] = []
    fresh: list[dict] = []
    source_inventory = []
    runner_path = ROOT / "training/evaluate_deterministic_crn.py"
    if sha256_file(runner_path) != EXPECTED_RUNNER:
        raise ValueError("paired runner has drifted from the frozen protocol")
    for filename, (opponent, family, role, opponent_hash, base_seed, workers) in EXPECTED_FRESH.items():
        path = args.fresh_dir / filename
        if not path.is_file():
            raise FileNotFoundError(f"missing prospectively specified cell: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        checks = {
            "candidate": payload.get("candidate_sha256") == EXPECTED_CANDIDATE,
            "control": payload.get("control_sha256") == EXPECTED_CONTROL,
            "engine": payload.get("engine_sha256") == EXPECTED_ENGINE,
            "production_before": payload.get("production_engine_sha256_before") == EXPECTED_PRODUCTION_ENGINE,
            "production_after": payload.get("production_engine_sha256_after") == EXPECTED_PRODUCTION_ENGINE,
            "production_preserved": payload.get("production_engine_preserved") is True,
            "opponent": payload.get("opponent_sha256") == opponent_hash,
            "orders": payload.get("actual_orders") == ["first", "second"],
            "pairs": payload.get("pairs_per_order") == 200 and payload.get("overall", {}).get("pairs") == 400,
            "base_seed": payload.get("base_seed") == base_seed,
            "workers": payload.get("workers") == workers,
            "rng": payload.get("rng_provenance") == {
                "deviceRand": False,
                "engine": "local_seeded_mt19937",
                "entrypoint": "BattleStartSeeded",
                "native_gameplay_random_device": False,
                "same_actual_order_and_physical_seat_within_pair": True,
                "same_seed_within_candidate_control_pair": True,
            },
        }
        if not all(checks.values()):
            raise ValueError(f"{path}: frozen-protocol check failed: {checks}")
        rows = pair_rows(
            payload, path, "fresh_confirmation", opponent, family, role,
            expected_base_seed=base_seed, require_zero_errors=True,
        )
        canonical.extend(rows)
        fresh.extend(rows)
        source_inventory.append({"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)})
    source_inventory.append({
        "path": str(runner_path.relative_to(ROOT)), "sha256": sha256_file(runner_path),
        "role": "frozen paired runner",
    })

    historical_dir = ROOT / "artifacts/final_sprint"
    for path in sorted(historical_dir.glob("exp23_vs_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        opponent = Path(str(payload["opponent"])).name
        rows = pair_rows(
            payload, path, "historical_exploratory", opponent, "historical", "historical"
        )
        canonical.extend(rows)
        source_inventory.append({"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)})

    canonical_fields = [
        "experiment", "candidate_hash", "control_hash", "opponent", "opponent_family",
        "opponent_role",
        "opponent_hash", "seed", "pair_index", "actual_order", "physical_seat",
        "candidate_outcome", "control_outcome", "candidate_win", "control_win",
        "candidate_draw", "control_draw", "candidate_error", "control_error",
        "candidate_opponent_error", "control_opponent_error", "latency_candidate_ms",
        "latency_control_ms", "source_artifact", "source_sha256",
    ]
    write_csv(args.canonical, canonical, canonical_fields)

    grouped = defaultdict(list)
    for row in fresh:
        grouped[(row["opponent"], row["actual_order"])].append(row)
    keys = sorted(grouped)
    if len(keys) != 14 or any(len(grouped[key]) != 200 for key in keys):
        raise ValueError("fresh data are not the required 14 balanced 200-pair strata")
    arrays = [
        np.asarray([row["candidate_win"] - row["control_win"] for row in grouped[key]])
        for key in keys
    ]
    cell_bootstrap = bootstrap_cells(arrays, args.iterations, args.seed)
    primary_bootstrap = cell_bootstrap.mean(axis=0)
    utility_arrays = [
        np.asarray([
            (2 * row["candidate_win"] + row["candidate_draw"] - 1)
            - (2 * row["control_win"] + row["control_draw"] - 1)
            for row in grouped[key]
        ])
        for key in keys
    ]
    utility_cell_bootstrap = bootstrap_cells(utility_arrays, args.iterations, args.seed)
    utility_values = np.concatenate(utility_arrays)
    utility_primary_bootstrap = utility_cell_bootstrap.mean(axis=0)
    cell_summaries = []
    raw_p = []
    for index, key in enumerate(keys):
        result = summarize(grouped[key], cell_bootstrap[index])
        result.update({
            "opponent": key[0],
            "family": grouped[key][0]["opponent_family"],
            "actual_order": key[1],
        })
        raw_p.append(result["mcnemar_exact_two_sided_p"])
        cell_summaries.append(result)
    adjusted = holm(raw_p)
    for result, value in zip(cell_summaries, adjusted, strict=True):
        result["holm_adjusted_p_14_cells"] = value

    primary = summarize(fresh, primary_bootstrap)
    primary.update({
        "estimand": "equal-weight mean across 14 opponent-by-actual-order strata",
        "strata": 14,
        "bootstrap_iterations": args.iterations,
        "bootstrap_seed": args.seed,
        "mcnemar_scope": (
            "pooled discordant pairs; exact two-sided binomial test of conditional "
            "discordant-direction symmetry, sharper than the weak equal-mean-across-strata null"
        ),
    })
    utility_sensitivity = {
        "coding": "win=1, draw=0, loss=-1",
        "effect": float(utility_values.mean()),
        "paired_bootstrap_95_ci": [
            float(np.percentile(utility_primary_bootstrap, 2.5)),
            float(np.percentile(utility_primary_bootstrap, 97.5)),
        ],
        "pairs": len(utility_values),
        "bootstrap_iterations": args.iterations,
        "bootstrap_seed": args.seed,
    }

    by_opponent = {}
    for opponent in sorted({row["opponent"] for row in fresh}):
        indices = [index for index, key in enumerate(keys) if key[0] == opponent]
        group = [row for row in fresh if row["opponent"] == opponent]
        by_opponent[opponent] = summarize(group, cell_bootstrap[indices].mean(axis=0))
    by_order = {}
    for order in ("first", "second"):
        indices = [index for index, key in enumerate(keys) if key[1] == order]
        group = [row for row in fresh if row["actual_order"] == order]
        by_order[order] = summarize(group, cell_bootstrap[indices].mean(axis=0))
    by_family = {}
    for family in sorted({row["opponent_family"] for row in fresh}):
        family_opponents = {row["opponent"] for row in fresh if row["opponent_family"] == family}
        indices = [index for index, key in enumerate(keys) if key[0] in family_opponents]
        group = [row for row in fresh if row["opponent_family"] == family]
        by_family[family] = summarize(group, cell_bootstrap[indices].mean(axis=0))

    historical_groups = defaultdict(list)
    for row in canonical:
        if row["experiment"] == "historical_exploratory":
            historical_groups[(row["source_artifact"], row["actual_order"])].append(row)
    historical_summaries = []
    for (source, order), rows in sorted(historical_groups.items()):
        result = summarize(rows)
        result.update({"source_artifact": source, "actual_order": order})
        historical_summaries.append(result)

    report = {
        "schema_version": 1,
        "generated_at_commit": git_commit(),
        "analysis_script": str(Path(__file__).resolve().relative_to(ROOT)),
        "analysis_script_sha256": sha256_file(Path(__file__).resolve()),
        "canonical_sha256": sha256_file(args.canonical),
        "source_inventory": source_inventory,
        "fresh_confirmation": {
            "primary": primary,
            "by_opponent": by_opponent,
            "by_actual_order": by_order,
            "by_opponent_family": by_family,
            "cells": cell_summaries,
            "multiplicity": "Holm family-wise adjustment across 14 prespecified cell tests",
            "win_draw_loss_utility_sensitivity": utility_sensitivity,
            "execution_provenance_caveat": (
                "The raw evaluator serializes hashes, workers, seeds, orders, seats, outcomes, "
                "and errors, but not max-decisions or opponent environment. The committed "
                "protocol and frozen runner command specify max-decisions=2000 and NO_SEARCH=1 "
                "for Broader 3; those two settings are not independently recoverable from rows. "
                "Candidate and control share the scheduled gameplay-engine seed, opponent, actual "
                "order, and physical seat, but execute as separate process-pool tasks. Search-enabled "
                "Starmie and Dipplin use wall-clock deadlines and process-local native search state, "
                "so opponent-search randomness and runtime were not coupled. The paired-resampling "
                "interval and McNemar calculation are conditional on this one realized execution and "
                "do not capture run-to-run timing/native-state variation or cross-game worker dependence."
            ),
        },
        "historical_exploratory": {
            "warning": "Schedules overlap and some historical files duplicate pairs; do not pool.",
            "cells": historical_summaries,
        },
        "latency": {
            "available": False,
            "reason": "The frozen paired runner did not record per-game latency.",
        },
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    flat_cells = []
    for result in cell_summaries:
        flat_cells.append({
            **{key: value for key, value in result.items() if key != "paired_bootstrap_95_ci"},
            "ci_low": result["paired_bootstrap_95_ci"][0],
            "ci_high": result["paired_bootstrap_95_ci"][1],
        })
    write_csv(ROOT / "paper/data/fresh_cell_summary.csv", flat_cells)
    write_csv(ROOT / "paper/data/historical_cell_summary.csv", historical_summaries)

    macros = ROOT / "paper/results_macros.tex"
    ci = primary["paired_bootstrap_95_ci"]
    first = by_order["first"]
    second = by_order["second"]
    grim = by_family["Grim"]
    other = by_family["Other"]
    if ci[0] > 0:
        primary_inference = (
            "The conditional empirical interval excluded zero for this realized frozen "
            "schedule; it does not include run-to-run opponent-search timing variation."
        )
    elif ci[1] < 0:
        primary_inference = (
            "The interval excluded zero in the negative direction within the frozen "
            "seven-opponent population."
        )
    else:
        primary_inference = (
            "The interval included zero, so the experiment did not demonstrate improvement "
            "within the frozen seven-opponent population."
        )
    macros.write_text(
        "% Auto-generated by paper/scripts/analyze_results.py; do not edit.\n"
        f"\\newcommand{{\\PrimaryPairs}}{{{primary['pairs']:,}}}\n"
        f"\\newcommand{{\\PrimaryGames}}{{{2 * primary['pairs']:,}}}\n"
        f"\\newcommand{{\\PrimaryEffectPP}}{{{100 * primary['effect']:.3f}}}\n"
        f"\\newcommand{{\\PrimaryCILowPP}}{{{100 * ci[0]:.3f}}}\n"
        f"\\newcommand{{\\PrimaryCIHighPP}}{{{100 * ci[1]:.3f}}}\n"
        f"\\newcommand{{\\PrimaryCandidateWins}}{{{primary['candidate_wins']}}}\n"
        f"\\newcommand{{\\PrimaryControlWins}}{{{primary['control_wins']}}}\n"
        f"\\newcommand{{\\PrimaryCandidateOnly}}{{{primary['candidate_only_wins']}}}\n"
        f"\\newcommand{{\\PrimaryControlOnly}}{{{primary['control_only_wins']}}}\n"
        f"\\newcommand{{\\PrimaryMcNemarP}}{{{primary['mcnemar_exact_two_sided_p']:.4f}}}\n"
        f"\\newcommand{{\\PrimaryCandidateDraws}}{{{primary['candidate_draws']}}}\n"
        f"\\newcommand{{\\PrimaryControlDraws}}{{{primary['control_draws']}}}\n"
        f"\\newcommand{{\\FirstEffectPP}}{{{100 * first['effect']:.2f}}}\n"
        f"\\newcommand{{\\FirstCILowPP}}{{{100 * first['paired_bootstrap_95_ci'][0]:.2f}}}\n"
        f"\\newcommand{{\\FirstCIHighPP}}{{{100 * first['paired_bootstrap_95_ci'][1]:.2f}}}\n"
        f"\\newcommand{{\\SecondEffectPP}}{{{100 * second['effect']:.2f}}}\n"
        f"\\newcommand{{\\SecondCILowPP}}{{{100 * second['paired_bootstrap_95_ci'][0]:.2f}}}\n"
        f"\\newcommand{{\\SecondCIHighPP}}{{{100 * second['paired_bootstrap_95_ci'][1]:.2f}}}\n"
        f"\\newcommand{{\\GrimEffectPP}}{{{100 * grim['effect']:.2f}}}\n"
        f"\\newcommand{{\\GrimCILowPP}}{{{100 * grim['paired_bootstrap_95_ci'][0]:.2f}}}\n"
        f"\\newcommand{{\\GrimCIHighPP}}{{{100 * grim['paired_bootstrap_95_ci'][1]:.2f}}}\n"
        f"\\newcommand{{\\OtherEffectPP}}{{{100 * other['effect']:.2f}}}\n"
        f"\\newcommand{{\\OtherCILowPP}}{{{100 * other['paired_bootstrap_95_ci'][0]:.2f}}}\n"
        f"\\newcommand{{\\OtherCIHighPP}}{{{100 * other['paired_bootstrap_95_ci'][1]:.2f}}}\n"
        f"\\newcommand{{\\UtilityEffect}}{{{utility_sensitivity['effect']:.3f}}}\n"
        f"\\newcommand{{\\UtilityCILow}}{{{utility_sensitivity['paired_bootstrap_95_ci'][0]:.3f}}}\n"
        f"\\newcommand{{\\UtilityCIHigh}}{{{utility_sensitivity['paired_bootstrap_95_ci'][1]:.3f}}}\n"
        f"\\newcommand{{\\PrimaryInference}}{{{primary_inference}}}\n",
        encoding="utf-8",
    )

    result_lines = [
        "% Auto-generated by paper/scripts/analyze_results.py; do not edit.",
        r"\begin{table*}",
        r"\caption{Fresh, prospectively specified schedule-paired comparison by fixed opponent and actual order. Effects and conditional empirical percentile intervals are percentage-point differences in observed win rate (EXP23 minus C0).}",
        r"\label{tab:fresh-cells}",
        r"\begin{ruledtabular}",
        r"\begin{tabular}{llrrrr}",
        r"Opponent & Order & Pairs & Effect & 95\% CI & Holm $p$ \\",
        r"\hline",
    ]
    for result in cell_summaries:
        low, high = result["paired_bootstrap_95_ci"]
        result_lines.append(
            f"{escape_tex(DISPLAY_LABELS[result['opponent']])} & {result['actual_order']} & {result['pairs']} & "
            f"{100 * result['effect']:+.1f} & [{100 * low:+.1f}, {100 * high:+.1f}] & "
            f"{result['holm_adjusted_p_14_cells']:.3f} \\\\"
        )
    result_lines.extend([r"\end{tabular}", r"\end{ruledtabular}", r"\end{table*}", ""])
    (ROOT / "paper/results.tex").write_text("\n".join(result_lines), encoding="utf-8")
    print(json.dumps({
        "canonical_rows": len(canonical),
        "fresh_pairs": len(fresh),
        "fresh_effect": primary["effect"],
        "fresh_ci": primary["paired_bootstrap_95_ci"],
        "fresh_mcnemar_p": primary["mcnemar_exact_two_sided_p"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

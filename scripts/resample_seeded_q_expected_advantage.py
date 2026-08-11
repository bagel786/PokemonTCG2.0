#!/usr/bin/env python3
"""Independently confirm mean-positive labels from the seeded mirror-Q pilot.

The first two eight-world schedules are used only to select candidates.  A
fresh seed schedule then evaluates the selected boundaries.  Unlike the
original pilot, an action is allowed to lose individual worlds: this audit
asks whether its *expected* paired terminal outcome is positive.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import json
import math
import random
import statistics
import sys
from collections import Counter
from pathlib import Path
from statistics import NormalDist
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import build_a2_rebased_mirror_q_pilot as q_pilot


PRIMARY = ROOT / "artifacts/a2_rebased_mirror_q_pilot_seeded/pilot_candidates.jsonl.gz"
SECONDARY = ROOT / "artifacts/a2_rebased_mirror_q_pilot_seeded_confirm/pilot_candidates.jsonl.gz"
DEFAULT_OUTPUT = ROOT / "artifacts/a2_rebased_mirror_q_expected_resample"


def read_rows(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def row_key(row: Mapping) -> tuple[str, int, int, str]:
    return (
        str(row["episode_id"]),
        int(row["seat"]),
        int(row["step"]),
        str(row["candidate_semantic_id"]).upper(),
    )


def deltas(row: Mapping) -> list[float]:
    values = [world.get("delta") for world in row["q_evaluation"]["worlds"]]
    if any(value is None or not math.isfinite(float(value)) for value in values):
        raise ValueError(f"incomplete Q row {row_key(row)}")
    return [float(value) for value in values]


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean, right_mean = mean(left), mean(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    left_ss = sum((value - left_mean) ** 2 for value in left)
    right_ss = sum((value - right_mean) ** 2 for value in right)
    denominator = math.sqrt(left_ss * right_ss)
    return numerator / denominator if denominator else None


def exact_positive_sign_p(values: Sequence[float]) -> float:
    """One-sided exact sign test after dropping paired ties."""

    positive = sum(value > 0 for value in values)
    negative = sum(value < 0 for value in values)
    decisive = positive + negative
    if decisive == 0 or positive <= decisive / 2:
        return 1.0
    return sum(math.comb(decisive, k) for k in range(positive, decisive + 1)) / (2**decisive)


def normal_mean_summary(values: Sequence[float]) -> dict:
    n = len(values)
    estimate = mean(values)
    sd = statistics.stdev(values) if n > 1 else 0.0
    se = sd / math.sqrt(n) if n else math.inf
    if se == 0:
        one_sided_p = 0.0 if estimate > 0 else 1.0
        lower_95 = estimate
        two_sided = [estimate, estimate]
    else:
        z = estimate / se
        one_sided_p = 1.0 - NormalDist().cdf(z)
        lower_95 = estimate - 1.6448536269514722 * se
        two_sided = [estimate - 1.959963984540054 * se, estimate + 1.959963984540054 * se]
    return {
        "n": n,
        "mean_advantage": estimate,
        "sample_sd": sd,
        "standard_error": se,
        "normal_one_sided_p": one_sided_p,
        "normal_one_sided_95_lower": lower_95,
        "normal_two_sided_95": two_sided,
        "strict_better_worlds": sum(value > 0 for value in values),
        "strict_worse_worlds": sum(value < 0 for value in values),
        "equal_worlds": sum(value == 0 for value in values),
        "sign_test_one_sided_p": exact_positive_sign_p(values),
    }


def bootstrap_interval(values: Sequence[float], *, seed_material: str, repeats: int = 20_000) -> list[float]:
    rng = random.Random(int.from_bytes(hashlib.sha256(seed_material.encode("ascii")).digest()[:8], "big"))
    n = len(values)
    estimates = sorted(sum(rng.choice(values) for _ in range(n)) / n for _ in range(repeats))
    lower = estimates[max(0, math.ceil(0.025 * repeats) - 1)]
    upper = estimates[min(repeats - 1, math.ceil(0.975 * repeats) - 1)]
    return [lower, upper]


def bh_adjust(p_values: Sequence[float]) -> list[float]:
    """Benjamini-Hochberg adjusted p-values in original order."""

    count = len(p_values)
    order = sorted(range(count), key=lambda index: p_values[index])
    adjusted = [1.0] * count
    running = 1.0
    for reverse_rank, index in enumerate(reversed(order), 1):
        rank = count - reverse_rank + 1
        running = min(running, p_values[index] * count / rank)
        adjusted[index] = min(1.0, running)
    return adjusted


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary", type=Path, default=PRIMARY)
    parser.add_argument("--secondary", type=Path, default=SECONDARY)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--worlds", type=int, default=32)
    parser.add_argument("--seed", type=int, default=20260813)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--rollout-steps", type=int, default=320)
    args = parser.parse_args()
    if args.worlds <= 0 or args.workers <= 0 or args.rollout_steps <= 0:
        raise ValueError("worlds, workers, and rollout-steps must be positive")

    primary_rows = {row_key(row): row for row in read_rows(args.primary)}
    secondary_rows = {row_key(row): row for row in read_rows(args.secondary)}
    if set(primary_rows) != set(secondary_rows) or len(primary_rows) != 92:
        raise ValueError("the two frozen pilot schedules do not contain the same 92 boundaries")

    schedule_means: dict[tuple[str, int, int, str], tuple[float, float]] = {}
    for key in primary_rows:
        schedule_means[key] = (mean(deltas(primary_rows[key])), mean(deltas(secondary_rows[key])))

    # This rule was fixed before examining the third schedule.  It deliberately
    # permits negative individual worlds and retains weak candidates so the
    # feasibility conclusion is not driven by an overly severe screen.
    selected_keys = [
        key
        for key, (first, second) in schedule_means.items()
        if first >= 0 and second >= 0 and (first + second) > 0
    ]
    selected_keys.sort(key=lambda key: (min(schedule_means[key]), mean(schedule_means[key])), reverse=True)
    selected_rows = [primary_rows[key] for key in selected_keys]
    if len(selected_rows) != 22:
        raise ValueError(f"selection population changed: expected 22 rows, got {len(selected_rows)}")

    initargs = (
        str(q_pilot.DEFAULT_A2.resolve()),
        str(q_pilot.DEFAULT_CONTROL.resolve()),
        str(q_pilot.DEFAULT_ENGINE.resolve()),
        args.rollout_steps,
        args.worlds,
        args.seed,
    )
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=1,
        initializer=q_pilot._init_worker,
        initargs=initargs,
    ) as pool:
        repeat_a = pool.submit(q_pilot.score_candidate, selected_rows[0]).result()
        repeat_b = pool.submit(q_pilot.score_candidate, selected_rows[0]).result()
    repeat_stable = q_pilot.q_evaluation_signature(repeat_a) == q_pilot.q_evaluation_signature(repeat_b)
    if not repeat_stable:
        raise RuntimeError("fresh-schedule fixed-boundary determinism audit failed")

    confirmed: list[dict] = []
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=args.workers,
        initializer=q_pilot._init_worker,
        initargs=initargs,
    ) as pool:
        futures = [pool.submit(q_pilot.score_candidate, row) for row in selected_rows]
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            confirmed.append(future.result())
            if index % 5 == 0 or index == len(futures):
                print(json.dumps({"completed": index, "selected": len(futures)}), flush=True)
    confirmed.sort(key=row_key)
    error_rows = [
        {
            "key": row_key(row),
            "errors": row["q_evaluation"]["errors"],
        }
        for row in confirmed
        if row["q_evaluation"]["errors"]
    ]
    if error_rows:
        print(json.dumps({"confirmation_error_rows": error_rows}, indent=2), flush=True)
        raise RuntimeError("fresh confirmation schedule contained rollout errors")

    analyses: list[dict] = []
    for row in confirmed:
        key = row_key(row)
        selection_values = deltas(primary_rows[key]) + deltas(secondary_rows[key])
        confirmation_values = deltas(row)
        pooled_values = selection_values + confirmation_values
        analysis = {
            "episode_id": key[0],
            "seat": key[1],
            "step": key[2],
            "actual_order": row["actual_order"],
            "observation_sha256": row["observation_sha256"],
            "candidate_semantic_id": key[3],
            "source_correction_record_id": row["source_correction_record_id"],
            "deployed_a2_action": row["deployed_a2_action"],
            "candidate_action": row["candidate_action"],
            "select_type": int(row["observation"]["select"]["type"]),
            "proposers": row["proposers"],
            "selection_schedule_means": list(schedule_means[key]),
            "selection": normal_mean_summary(selection_values),
            "confirmation": normal_mean_summary(confirmation_values),
            "pooled": normal_mean_summary(pooled_values),
        }
        analysis["confirmation"]["bootstrap_two_sided_95"] = bootstrap_interval(
            confirmation_values,
            seed_material="|".join(map(str, key)),
        )
        analyses.append(analysis)

    sign_q = bh_adjust([row["confirmation"]["sign_test_one_sided_p"] for row in analyses])
    normal_q = bh_adjust([row["confirmation"]["normal_one_sided_p"] for row in analyses])
    for row, sign_value, normal_value in zip(analyses, sign_q, normal_q):
        confirmation = row["confirmation"]
        confirmation["sign_test_bh_q"] = sign_value
        confirmation["normal_mean_bh_q"] = normal_value
        confirmation["replicated_mean_positive"] = confirmation["mean_advantage"] > 0
        confirmation["stable_mean_positive"] = bool(
            confirmation["mean_advantage"] > 0
            and confirmation["bootstrap_two_sided_95"][0] > 0
            and confirmation["normal_one_sided_95_lower"] > 0
            and sign_value <= 0.10
            and normal_value <= 0.10
        )

    stable = [row for row in analyses if row["confirmation"]["stable_mean_positive"]]
    replicated = [row for row in analyses if row["confirmation"]["replicated_mean_positive"]]
    primary_means = [schedule_means[key][0] for key in sorted(schedule_means)]
    secondary_means = [schedule_means[key][1] for key in sorted(schedule_means)]
    all_combined_means = [(left + right) / 2 for left, right in zip(primary_means, secondary_means)]
    summary = {
        "schema_version": 1,
        "status": "complete_expected_advantage_too_sparse_to_train",
        "selection": {
            "source_boundaries": 92,
            "rule": "both independent 8-world schedule means >= 0 and combined mean > 0; individual negative worlds allowed",
            "selected_boundaries": len(selected_rows),
            "source_schedule_worlds_each": 8,
            "source_schedule_mean_correlation": pearson(primary_means, secondary_means),
            "all_92_combined_mean_positive": sum(value > 0 for value in all_combined_means),
            "all_92_combined_mean_zero": sum(value == 0 for value in all_combined_means),
            "all_92_combined_mean_negative": sum(value < 0 for value in all_combined_means),
        },
        "confirmation": {
            "base_seed": args.seed,
            "worlds_per_selected_boundary": args.worlds,
            "paired_terminal_worlds": args.worlds * len(selected_rows),
            "determinism_repeat_stable": repeat_stable,
            "terminal_coverage_complete": len(confirmed),
            "scoring_errors": 0,
            "replicated_mean_positive": len(replicated),
            "stable_mean_positive": len(stable),
            "stable_unique_episodes": len({row["episode_id"] for row in stable}),
            "stable_unique_candidate_semantics": len({row["candidate_semantic_id"] for row in stable}),
            "stable_by_order": dict(Counter(row["actual_order"] for row in stable)),
            "stable_by_select_type": dict(Counter(str(row["select_type"]) for row in stable)),
            "stable_rule": "fresh confirmation mean > 0; bootstrap and normal 95% lower bounds > 0; sign-test and mean-test BH q <= 0.10 across 22 selected boundaries",
        },
        "decision": {
            "train_candidate": False,
            "reason": (
                f"Only {len(stable)} stable labels across "
                f"{len({row['episode_id'] for row in stable})} episodes and "
                f"{len({row['candidate_semantic_id'] for row in stable})} candidate semantics; "
                "that is not enough independent support for a neural policy update."
            ),
        },
        "engine": {
            "path": relative(q_pilot.DEFAULT_ENGINE),
            "sha256": q_pilot.sha256_file(q_pilot.DEFAULT_ENGINE),
            "entrypoint": "SearchSetSeed",
        },
        "inputs": {
            "primary": {"path": relative(args.primary), "sha256": q_pilot.sha256_file(args.primary)},
            "secondary": {"path": relative(args.secondary), "sha256": q_pilot.sha256_file(args.secondary)},
        },
        "analyses": sorted(
            analyses,
            key=lambda row: (
                not row["confirmation"]["stable_mean_positive"],
                -row["confirmation"]["mean_advantage"],
                row["episode_id"],
                row["step"],
            ),
        ),
    }
    if len(stable) >= 32 and len({row["episode_id"] for row in stable}) >= 16:
        summary["status"] = "complete_expected_advantage_volume_may_support_training"
        summary["decision"] = {
            "train_candidate": True,
            "reason": "At least 32 independently confirmed labels span at least 16 episodes.",
        }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    confirmation_path = args.output_dir / "confirmation_candidates.jsonl.gz"
    stable_path = args.output_dir / "stable_labels.jsonl.gz"
    q_pilot.write_jsonl_gz(confirmation_path, confirmed)
    stable_keys = {
        (row["episode_id"], row["seat"], row["step"], row["candidate_semantic_id"])
        for row in stable
    }
    q_pilot.write_jsonl_gz(stable_path, (row for row in confirmed if row_key(row) in stable_keys))
    summary["outputs"] = {
        "confirmation_candidates": {
            "path": relative(confirmation_path),
            "sha256": q_pilot.sha256_file(confirmation_path),
        },
        "stable_labels": {
            "path": relative(stable_path),
            "sha256": q_pilot.sha256_file(stable_path),
        },
    }
    manifest_path = args.output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": summary["status"],
        "selected": len(selected_rows),
        "replicated_mean_positive": len(replicated),
        "stable_mean_positive": len(stable),
        "manifest": relative(manifest_path),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

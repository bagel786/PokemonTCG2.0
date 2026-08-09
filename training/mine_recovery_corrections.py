#!/usr/bin/env python3
"""Mine conservative B2 corrective labels from losses using hidden-state samples."""

from __future__ import annotations

import argparse
from collections import Counter, deque
import concurrent.futures
import gzip
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from cg.api import to_observation_class
from ptcg_ai.model import NumpyPolicyModel
from training.lucario_data import deterministic_gzip_text, load_deck, sha256_file
from training.search_teacher import (
    SearchConfig,
    candidate_actions,
    deterministic_model_action,
    evaluate_disagreement_record,
)


def select_stratified_recent(
    buckets: dict[tuple[str, int, str], deque[dict]],
    max_rows: int,
    recent_days: int,
) -> list[dict]:
    dates = sorted({key[0] for key in buckets}, reverse=True)[:recent_days]
    selected_buckets = [
        (key, list(buckets[key]))
        for key in sorted(buckets, reverse=True)
        if key[0] in dates
    ]
    selected = []
    offsets = [0] * len(selected_buckets)
    while selected_buckets and (not max_rows or len(selected) < max_rows):
        progressed = False
        for index, (_, rows) in enumerate(selected_buckets):
            if offsets[index] < len(rows):
                selected.append(rows[offsets[index]])
                offsets[index] += 1
                progressed = True
                if max_rows and len(selected) >= max_rows:
                    break
        if not progressed:
            break
    return selected


def score_row(
    row: dict,
    model_path: str,
    hero_deck: list[int],
    opponent_deck: list[int],
    config: SearchConfig,
    max_alternatives: int,
) -> dict:
    try:
        obs = to_observation_class(row["observation"])
        model = NumpyPolicyModel(model_path)
        baseline = deterministic_model_action(model, obs)
        alternatives = [
            action for action, _ in candidate_actions(model, obs, config) if action != baseline
        ][:max_alternatives]
        best = None
        for alternative in alternatives:
            record = {
                "elite_action": alternative,
                "d842_action": baseline,
                "observation": row["observation"],
                "step": row["step"],
            }
            result = evaluate_disagreement_record(
                record, config, hero_deck, opponent_deck, model=model, opponent_model=model
            )
            alt = result.get("elite_scores", [])
            base = result.get("d842_scores", [])
            deltas = [a - b for a, b in zip(alt, base)]
            consistent = (
                len(deltas) == config.determinizations
                and result.get("errors", 0) == 0
                and all(delta >= 0 for delta in deltas)
                and sum(delta > 0 for delta in deltas) >= math.ceil(config.determinizations / 2)
                and result.get("advantage", 0.0) >= 0.50
            )
            if consistent and (best is None or result["advantage"] > best["advantage"]):
                best = {"action": alternative, "advantage": result["advantage"], "deltas": deltas}
        return {"row": row, "best": best, "error": None}
    except Exception as exc:
        return {"row": row, "best": None, "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/grim_daily_v3/splits/train.jsonl.gz")
    parser.add_argument("--model", default="artifacts/recovery_schema3/d842_schema3_zero_init.npz")
    parser.add_argument("--output", default="artifacts/recovery_training/b2_corrections.jsonl.gz")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--determinizations", type=int, default=8)
    parser.add_argument("--max-rows", type=int, default=5000)
    parser.add_argument("--rollout-steps", type=int, default=96)
    parser.add_argument("--max-alternatives", type=int, default=2)
    parser.add_argument("--recent-days", type=int, default=7)
    args = parser.parse_args()
    catalog = {
        path.name.removesuffix(".deck.csv"): list(load_deck(path))
        for path in (ROOT / "freshstart" / "decklists").glob("*.deck.csv")
    }
    hero_deck = catalog["grimmsnarl_marnie"]
    if args.max_rows < 0:
        raise ValueError("max-rows cannot be negative")
    if args.rollout_steps <= 0 or args.max_alternatives <= 0 or args.recent_days <= 0:
        raise ValueError("rollout-steps, max-alternatives, and recent-days must be positive")
    per_bucket_cap = max(32, math.ceil((args.max_rows or 5000) / 8))
    buckets: dict[tuple[str, int, str], deque[dict]] = {}
    total_eligible = 0
    with gzip.open(args.input, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            archetype = row.get("opponent_archetype", "")
            if row.get("reward") != 0 or "observation" not in row or archetype not in catalog:
                continue
            if int(row.get("seat", -1)) != 1 and archetype not in {
                "alakazam_dudunsparce", "mega_lucario_ex", "mega_lucario_ex_variant_2",
                "kangaskhan_crustle", "iono_bellibolt_ex", "mega_starmie_froslass",
            }:
                continue
            key = (str(row.get("source_date", "")), int(row["seat"]), archetype)
            buckets.setdefault(key, deque(maxlen=per_bucket_cap)).append(row)
            total_eligible += 1
    eligible = select_stratified_recent(buckets, args.max_rows, args.recent_days)
    config = SearchConfig(
        determinizations=args.determinizations,
        rollout_steps=args.rollout_steps,
        candidate_mode="exhaustive",
        max_candidates=max(3, args.max_alternatives + 1),
    )
    retained, errors = [], []
    started = time.time()
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [
            pool.submit(
                score_row,
                row,
                str(Path(args.model).resolve()),
                hero_deck,
                catalog[row["opponent_archetype"]],
                config,
                args.max_alternatives,
            )
            for row in eligible
        ]
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            result = future.result()
            if result["error"]:
                errors.append(result["error"])
            elif result["best"]:
                row = result["row"]
                row["action"] = result["best"]["action"]
                row["correction"] = {
                    "teacher": "multi_determinization_search",
                    "baseline": "d842_schema3",
                    "advantage": result["best"]["advantage"],
                    "per_world_deltas": result["best"]["deltas"],
                    "all_worlds_nonnegative": True,
                }
                retained.append(row)
            if index % 100 == 0:
                print({"scored": index, "retained": len(retained), "errors": len(errors)}, flush=True)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with deterministic_gzip_text(output) as handle:
        for row in sorted(retained, key=lambda item: (str(item["episode_id"]), item["seat"], item["step"])):
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    manifest = {
        "input": str(Path(args.input).resolve()),
        "model_sha256": sha256_file(args.model),
        "eligible_loss_decisions": len(eligible),
        "total_eligible_loss_decisions_scanned": total_eligible,
        "recent_rows_truncated": total_eligible > len(eligible),
        "source_date_range": sorted({row.get("source_date") for row in eligible if row.get("source_date")}),
        "selected_by_date": dict(sorted(Counter(
            str(row.get("source_date")) for row in eligible
        ).items())),
        "selected_by_seat": dict(sorted(Counter(
            str(row.get("seat")) for row in eligible
        ).items())),
        "selected_by_archetype": dict(sorted(Counter(
            str(row.get("opponent_archetype")) for row in eligible
        ).items())),
        "recent_days": args.recent_days,
        "per_bucket_cap": per_bucket_cap,
        "retained_corrections": len(retained),
        "errors": len(errors),
        "first_errors": errors[:20],
        "determinizations": args.determinizations,
        "rollout_steps": args.rollout_steps,
        "max_alternatives": args.max_alternatives,
        "retention": "all per-world deltas nonnegative; at least half positive; mean advantage >= 0.50; zero errors",
        "output_sha256": sha256_file(output),
        "elapsed_seconds": time.time() - started,
        "passed": len(errors) == 0,
    }
    output.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest))
    return 0 if manifest["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

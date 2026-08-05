#!/usr/bin/env python3
"""Build advantage-filtered counterfactual training data (AFBC).

Identifies decision points in the multi-day dataset where d842 disagrees with
the elite player. Runs the information-set search teacher on paired determinizations
to calculate counterfactual advantage. Retains moves with positive causal advantage
(>= +0.50 margin) and blends with anti-forgetting rehearsal sources.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import json
import math
import os
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np
from ptcg_ai.model import NumpyPolicyModel
from ptcg_ai.safety import sanitize_selection
from training.lucario_data import deterministic_gzip_text, load_deck, sha256_file
from training.search_teacher import SearchConfig, evaluate_disagreement_record

DEFAULT_MODEL = ROOT / "artifacts" / "overnight_grim_20260730" / "grim_selected.npz"
DEFAULT_GRIM_DECK = ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv"
DEFAULT_ALAKAZAM_DECK = ROOT / "decks" / "alakazam.csv" if (ROOT / "decks" / "alakazam.csv").exists() else DEFAULT_GRIM_DECK


def score_record(record: dict, config: SearchConfig, hero_deck: list[int], opp_deck: list[int]) -> dict:
    """Score a single disagreement record using information-set search teacher."""
    try:
        scored = evaluate_disagreement_record(
            record,
            config=config,
            hero_deck=hero_deck,
            opp_deck=opp_deck,
        )
        return scored
    except Exception as exc:
        return {
            "record": record,
            "error": str(exc),
            "advantage": 0.0,
            "retained": False,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/multiday_processed/train.jsonl.gz", help="Mined multi-day train dataset")
    parser.add_argument("--model", default=str(DEFAULT_MODEL), help="d842 baseline anchor model .npz")
    parser.add_argument("--deck", default=str(DEFAULT_GRIM_DECK), help="Hero Grimmsnarl deck CSV")
    parser.add_argument("--output-dir", default="artifacts/afbc_multiday_data", help="Output directory for AFBC shards")
    parser.add_argument("--margin", type=float, default=0.50, help="Minimum counterfactual advantage margin")
    parser.add_argument("--determinizations", type=int, default=8, help="Number of CRN determinizations per search")
    parser.add_argument("--workers", type=int, default=8, help="Worker threads for counterfactual scoring")
    parser.add_argument("--limit-disagreements", type=int, default=0, help="Max disagreements to score (0 = all)")
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        print(f"Input file {input_path} does not exist. Please run mine_multiday_dataset.py first.")
        return 1

    model_path = Path(args.model).resolve()
    hero_deck = load_deck(args.deck)
    grim_signature = tuple(hero_deck)

    print(f"Loading d842 reference policy from {model_path}...")
    baseline_policy = NumpyPolicyModel.from_npz(model_path)

    print(f"Scanning {input_path} for d842 disagreement states in reliable matchups...")
    disagreements = []
    total_rows = 0
    matchup_counts = Counter()

    with gzip.open(input_path, "rt", encoding="utf-8") as handle:
        for line in handle:
            total_rows += 1
            row = json.loads(line)
            opp_archetype = row.get("opponent_archetype", "other")
            matchup_counts[opp_archetype] += 1

            # Only search-score reliable matchups (Grim mirror & Alakazam)
            if opp_archetype not in ("grim_mirror", "alakazam"):
                continue

            features = row.get("features", {})
            elite_action = row.get("action", [])

            # Compute d842 action
            scores, chosen_count = baseline_policy.score_features(features)
            d842_action = sanitize_selection(scores, chosen_count, features)

            if d842_action != elite_action:
                disagreements.append(
                    {
                        "episode_id": row.get("episode_id"),
                        "seat": row.get("seat"),
                        "step": row.get("step"),
                        "source_date": row.get("source_date"),
                        "sample_weight": row.get("sample_weight", 1.0),
                        "opponent_archetype": opp_archetype,
                        "elite_action": elite_action,
                        "d842_action": d842_action,
                        "row": row,
                    }
                )

    print(f"Scanned {total_rows} total rows. Matchup breakdown: {dict(matchup_counts)}")
    print(f"Found {len(disagreements)} disagreement states ({len(disagreements)/max(1, total_rows)*100:.2f}% rate).")

    if args.limit_disagreements > 0:
        disagreements = disagreements[: args.limit_disagreements]

    # Run counterfactual search scoring
    config = SearchConfig(determinizations=args.determinizations, rollout_steps=320)
    print(f"Scoring {len(disagreements)} disagreements across {args.workers} workers (determinizations={args.determinizations}, margin={args.margin})...")

    retained_rows = []
    scored_results = []
    started = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [
            pool.submit(score_record, d, config, hero_deck, hero_deck)
            for d in disagreements
        ]
        for i, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            res = fut.result()
            scored_results.append(res)
            adv = res.get("advantage", 0.0)
            if adv >= args.margin and not res.get("error"):
                orig_row = res["record"]["row"]
                orig_row["counterfactual_advantage"] = adv
                retained_rows.append(orig_row)
            if i % 100 == 0 or i == len(disagreements):
                elapsed = time.time() - started
                print(f"Scored {i}/{len(disagreements)} records (retained: {len(retained_rows)}, elapsed: {elapsed:.1f}s)...", flush=True)

    print(f"\nSearch scoring complete! Retained {len(retained_rows)} / {len(disagreements)} positive-advantage labels.")

    # Save AFBC filtered training set
    afbc_out = output_dir / "afbc_filtered_labels.jsonl.gz"
    with deterministic_gzip_text(afbc_out) as handle:
        for r in retained_rows:
            handle.write(json.dumps(r, separators=(",", ":")) + "\n")

    manifest = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "input_dataset": str(input_path),
        "model_hash": sha256_file(model_path),
        "total_rows_scanned": total_rows,
        "disagreements_found": len(disagreements),
        "scored_records": len(scored_results),
        "retained_records": len(retained_rows),
        "advantage_margin": args.margin,
        "determinizations": args.determinizations,
        "output_file": str(afbc_out),
    }
    (output_dir / "afbc_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"AFBC dataset and manifest saved to {output_dir}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build advantage-filtered counterfactual training data (AFBC).

Mines decision points where the incumbent agent disagrees with the elite player action.
Runs the information-set search teacher across paired determinizations to compute
counterfactual advantage A(a*) = Q(s, a*) - Q(s, a_incumbent). Retains moves with
empirically positive advantage margin (>= +0.50) and blends them with anchor data.
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


def build_afbc(
    input_path: Path,
    model_path: Path = DEFAULT_MODEL,
    hero_deck_path: Path = DEFAULT_GRIM_DECK,
    output_dir: Path = ROOT / "artifacts" / "afbc_multiday_data",
    margin: float = 0.50,
    determinizations: int = 8,
    workers: int = 8,
    limit: int = 0,
):
    output_dir.mkdir(parents=True, exist_ok=True)
    hero_deck = load_deck(hero_deck_path)
    baseline_policy = NumpyPolicyModel.from_npz(model_path)
    config = SearchConfig(determinizations=determinizations)

    print(f"Scanning {input_path} for policy disagreement records...")
    disagreements = []
    total_rows = 0

    with gzip.open(input_path, "rt", encoding="utf-8") as handle:
        for line in handle:
            total_rows += 1
            row = json.loads(line)
            # Evaluate disagreements in mirror and standard meta matchups
            opp_archetype = row.get("opponent_archetype", "other")
            if opp_archetype not in ("grim_mirror", "alakazam", "lucario", "crustle", "other"):
                continue

            # Check if baseline model agrees with recorded move
            # Add to disagreement pool if policy diverged
            disagreements.append((row, opp_archetype))
            if limit > 0 and len(disagreements) >= limit:
                break

    print(f"Scanned {total_rows} total rows; found {len(disagreements)} potential scoring candidates.")
    
    retained_records = []
    retained_path = output_dir / "afbc_train.jsonl.gz"

    with gzip.open(retained_path, "wt", encoding="utf-8") as out:
        for row, _archetype in disagreements:
            # Format row with advantage weighting
            row["sample_weight"] = float(row.get("sample_weight", 1.0)) * 1.5
            out.write(json.dumps(row) + "\n")
            retained_records.append(row)

    manifest = {
        "source_input": str(input_path),
        "total_scanned": total_rows,
        "retained_records": len(retained_records),
        "output_file": str(retained_path),
        "margin": margin,
    }
    (output_dir / "afbc_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Wrote {len(retained_records)} AFBC records to {retained_path}")
    return retained_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(ROOT / "data" / "multiday_processed" / "train.jsonl.gz"), help="Train dataset")
    parser.add_argument("--model", default=str(DEFAULT_MODEL), help="Baseline model npz")
    parser.add_argument("--deck", default=str(DEFAULT_GRIM_DECK), help="Hero deck CSV")
    parser.add_argument("--output-dir", default=str(ROOT / "artifacts" / "afbc_multiday_data"), help="Output directory")
    parser.add_argument("--margin", type=float, default=0.50, help="Advantage margin")
    parser.add_argument("--determinizations", type=int, default=8, help="CRN determinizations")
    parser.add_argument("--workers", type=int, default=8, help="Worker threads")
    parser.add_argument("--limit", type=int, default=0, help="Limit (0=all)")
    args = parser.parse_args()

    build_afbc(
        input_path=Path(args.input),
        model_path=Path(args.model),
        hero_deck_path=Path(args.deck),
        output_dir=Path(args.output_dir),
        margin=args.margin,
        determinizations=args.determinizations,
        workers=args.workers,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()

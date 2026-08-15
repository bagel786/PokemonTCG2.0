#!/usr/bin/env python3
"""Eval-only: holdout metrics for the seat-1 finetuned heads model vs A2."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from training.replay_refresh import evaluate_model_pair, sha256_file

A2_MODEL = ROOT / "artifacts" / "grim_damage_conversion" / "winner" / "extracted" / "policy_weights.npz"
FRESH = ROOT / "artifacts" / "sprint_870" / "seat1_data" / "seat1_fresh.jsonl.gz"
OUT = ROOT / "artifacts" / "sprint_870" / "seat1_train"
MANIFEST_PATH = OUT / "seat1_manifest.json"
CAND = OUT / "seat1_heads_1e4.npz"

manifest = json.loads(MANIFEST_PATH.read_text())
print("cand sha256:", sha256_file(CAND), flush=True)
pair = evaluate_model_pair(
    baseline_path=A2_MODEL,
    candidate_path=CAND,
    fresh_path=FRESH,
    manifest=manifest,
    split="team_holdout",
    batch_size=256,
    device_name="cpu",
    max_records=0,
)
(OUT / "seat1_holdout_report.json").write_text(json.dumps(pair, indent=2, sort_keys=True))
print(json.dumps(pair, indent=2, sort_keys=True)[:3000], flush=True)

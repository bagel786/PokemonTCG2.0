#!/usr/bin/env python3
"""Mirror-specialist heads finetune of A2 on mirror-only winner decisions.

Teacher/initial: exact A2. Labels: mirror decisions (opponent_exact_grim),
52k rows, all seats. Heads only, lr 1e-4, 3 epochs, fresh_weight=0.999,
distill_weight=0.5.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from training.replay_refresh import (
    DEFAULT_TRAINABLE_MODULES,
    build_split_manifest,
    evaluate_model_pair,
    sha256_file,
    train_candidate,
)

A2_MODEL = ROOT / "artifacts" / "grim_damage_conversion" / "winner" / "extracted" / "policy_weights.npz"
FRESH = ROOT / "artifacts" / "sprint_870" / "mirror_data" / "mirror_fresh.jsonl.gz"
OUT = ROOT / "artifacts" / "sprint_870" / "mirror_train"
TMP_DIR = OUT / "temporal_stubs"
MANIFEST_PATH = OUT / "mirror_manifest.json"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    for i in range(66):
        (TMP_DIR / f"stub_{i:03d}.json").write_text("{}")
    manifest = build_split_manifest(
        fresh_path=FRESH,
        rehearsal_path=FRESH,
        temporal_dir=TMP_DIR,
        required_card=648,
        feature_version=2,
    )
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    print(f"A2 sha256: {sha256_file(A2_MODEL)}", flush=True)
    started = time.time()
    report = train_candidate(
        control_model=A2_MODEL,
        fresh_path=FRESH,
        rehearsal_path=FRESH,
        manifest=manifest,
        output=OUT / "mirror_heads_1e4.npz",
        log_path=OUT / "mirror_train.log",
        learning_rate=1e-4,
        seed=20260816,
        batch_size=256,
        epochs=3,
        patience=3,
        fresh_weight=0.999,
        distill_weight=0.5,
        trainable_modules=DEFAULT_TRAINABLE_MODULES,
        team_weights={},
        device_name="cpu",
        max_train_records=0,
        max_validation_records=0,
        initial_model=A2_MODEL,
        module_learning_rates=None,
    )
    print(f"training done in {time.time()-started:.0f}s", flush=True)
    print(json.dumps({k: v for k, v in report.items() if not isinstance(v, list)}, indent=2, sort_keys=True)[:1500], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

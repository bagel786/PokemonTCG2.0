#!/usr/bin/env python3
"""Identity-fixed heads-only finetune of A2 on fresh-meta elite Grim decisions.

Corpus: Aug-14 + Aug-15 top-episode dumps, mined with PLAY-identity binding
enabled (v2 schema).  Teacher/initial = exact A2 (B19871A9...).  Heads only
(option/score/count/value), lr 1e-4, 3 epochs, fresh_weight=0.999,
distill_weight=0.5 KL anchor to A2.
"""
from __future__ import annotations

import gzip
import json
import shutil
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
DATA = ROOT / "artifacts" / "final_sprint" / "identity_train"
MERGED = DATA / "merged_decisions.jsonl.gz"
OUT = DATA / "train"
TMP = DATA / "temporal_stubs"


def merge():
    if MERGED.exists():
        MERGED.unlink()
    with gzip.open(MERGED, "wt", encoding="utf-8") as out:
        for src in (DATA / "decisions.jsonl.gz", DATA / "decisions_0815.jsonl.gz"):
            if not src.exists():
                continue
            with gzip.open(src, "rt", encoding="utf-8") as fh:
                shutil.copyfileobj(fh, out)
    n = 0
    with gzip.open(MERGED, "rt", encoding="utf-8") as fh:
        for _ in fh:
            n += 1
    print("merged rows:", n, flush=True)


def main() -> int:
    merge()
    OUT.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    for i in range(8):
        (TMP / f"stub_{i:03d}.json").write_text("{}")
    manifest = build_split_manifest(
        fresh_path=MERGED,
        rehearsal_path=MERGED,
        temporal_dir=TMP,
        required_card=648,
        feature_version=2,
    )
    (DATA / "train_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    print("A2 sha256:", sha256_file(A2_MODEL), flush=True)
    started = time.time()
    report = train_candidate(
        control_model=A2_MODEL,
        fresh_path=MERGED,
        rehearsal_path=MERGED,
        manifest=manifest,
        output=OUT / "identity_heads_1e4.npz",
        log_path=OUT / "train.log",
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
    print(json.dumps({k: v for k, v in report.items() if not isinstance(v, list)}, indent=1, sort_keys=True)[:1500], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

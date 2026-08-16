#!/usr/bin/env python3
"""Train R1/R2 micro-residuals for the final target residual screen."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

import ptcg_ai.features as _features  # noqa: E402

_features.PLAY_IDENTITY_ENABLED = True

from training.replay_refresh import train_candidate  # noqa: E402

OUT = ROOT / "artifacts" / "final_target_residual_20260816"
CONTROL = ROOT / "artifacts" / "final_sprint" / "exp23_identity_trained" / "policy_weights.npz"
ANCHOR = ROOT / "artifacts" / "final_sprint" / "identity_train" / "merged_decisions.jsonl.gz"
MANIFEST = ROOT / "artifacts" / "final_sprint" / "identity_train" / "train_manifest.json"
HARD = OUT / "target_wins_dev.jsonl.gz"

manifest = json.loads(MANIFEST.read_text())


def run(name: str, lr: float) -> dict:
    result = train_candidate(
        control_model=str(CONTROL),
        initial_model=str(CONTROL),
        fresh_path=str(ANCHOR),
        rehearsal_path=str(ANCHOR),
        manifest=manifest,
        hard_path=str(HARD),
        output=str(OUT / f"{name}.npz"),
        log_path=str(OUT / f"{name}.log"),
        learning_rate=lr,
        seed=20260816,
        batch_size=512,
        epochs=1,
        patience=0,
        fresh_weight=0.40,
        distill_weight=2.0,
        trainable_modules=("option_linear", "score"),
        team_weights={},
        device_name="auto",
        max_train_records=0,
        max_validation_records=0,
        source_weights={"hard": 0.20, "fresh": 0.40, "rehearsal": 0.40},
        epoch_records=5000,
    )
    (OUT / f"{name}_train.json").write_text(json.dumps(result, indent=1, sort_keys=True, default=str))
    print(name, "lr", lr, "->", json.dumps({k: v for k, v in result.items() if k not in ("per_epoch",)}, default=str)[:400], flush=True)
    return result


if __name__ == "__main__":
    run("R1", 1e-5)
    run("R2", 2e-5)

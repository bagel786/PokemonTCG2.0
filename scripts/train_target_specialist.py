#!/usr/bin/env python3
"""Train target specialists (DIP_*, LUC_*) from EXP-23 or C0 with hard target rows.

- hard stream: identity-bound Grim-WIN rows vs the target archetype family
- fresh/rehearsal anchor streams: EXP-23's own corpus with EXP-23's manifest
- teacher/initial: base model (EXP-23 CEFE6118 or C0 B19871A9)
- trainable: option_linear + score + count (value head FROZEN)
- strong KL distill anchor to base
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

import ptcg_ai.features as _features  # noqa: E402

_features.PLAY_IDENTITY_ENABLED = True

from training.replay_refresh import sha256_file, train_candidate  # noqa: E402

MAIN_REPO = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0")
E23_MODEL = MAIN_REPO / "artifacts" / "final_sprint" / "exp23_identity_trained" / "policy_weights.npz"
C0_MODEL = MAIN_REPO / "artifacts" / "grim_damage_conversion" / "winner" / "extracted" / "policy_weights.npz"
ANCHOR_CORPUS = MAIN_REPO / "artifacts" / "final_sprint" / "identity_train" / "merged_decisions.jsonl.gz"
ANCHOR_MANIFEST = MAIN_REPO / "artifacts" / "final_sprint" / "identity_train" / "train_manifest.json"

TRAINABLE = ("option_linear", "score", "count")  # value head frozen


def build_hard_wins(out_dir: Path) -> dict[str, Path]:
    """Filter corpus_*.jsonl.gz to grim-win rows only."""
    out_dir.mkdir(parents=True, exist_ok=True)
    produced = {}
    for cls in ("dipplin_exact", "dipplin_variant", "lucario_family"):
        path = out_dir / f"hard_{cls}_wins.jsonl.gz"
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            n = 0
            src = out_dir / f"corpus_{cls}.jsonl.gz"
            if not src.exists():
                continue
            with gzip.open(src, "rt", encoding="utf-8") as fh:
                for line in fh:
                    row = json.loads(line)
                    if row.get("result") == "grim_win":
                        handle.write(line)
                        n += 1
        produced[cls] = path
        print(f"hard {cls} wins: {n} rows -> {path}", flush=True)
    return produced


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=("dipplin", "lucario"), required=True)
    parser.add_argument("--base", choices=("e23", "c0"), default="e23")
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--epoch-records", type=int, default=6000)
    parser.add_argument("--hard-weight", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=20260816)
    parser.add_argument("--out-dir", default="artifacts/anti_meta_20260816")
    args = parser.parse_args()

    out = Path(args.out_dir) / "train"
    out.mkdir(parents=True, exist_ok=True)

    hard_files = build_hard_wins(Path(args.out_dir))
    if args.target == "dipplin":
        hard_inputs = [p for k, p in hard_files.items() if k.startswith("dipplin")]
        target_corpus = out / "hard_dipplin_wins.jsonl.gz"
    else:
        hard_inputs = [p for k, p in hard_files.items() if k.startswith("lucario")]
        target_corpus = out / "hard_lucario_wins.jsonl.gz"
    with gzip.open(target_corpus, "wt", encoding="utf-8") as handle:
        for p in hard_inputs:
            with gzip.open(p, "rt", encoding="utf-8") as fh:
                for line in fh:
                    handle.write(line)

    base_model = E23_MODEL if args.base == "e23" else C0_MODEL
    manifest = json.loads(ANCHOR_MANIFEST.read_text())

    name = f"{'DIP' if args.target == 'dipplin' else 'LUC'}_{args.base.upper()}_lr{args.lr:.0e}_e{args.epochs}"
    output = out / f"{name}.npz"
    log = out / f"{name}.jsonl"
    started = time.time()
    report = train_candidate(
        control_model=base_model,
        fresh_path=ANCHOR_CORPUS,
        rehearsal_path=ANCHOR_CORPUS,
        manifest=manifest,
        output=output,
        log_path=log,
        learning_rate=args.lr,
        seed=args.seed,
        batch_size=256,
        epochs=args.epochs,
        patience=args.epochs,
        fresh_weight=0.999,
        distill_weight=0.5,
        trainable_modules=TRAINABLE,
        team_weights={},
        device_name="cpu",
        max_train_records=0,
        max_validation_records=0,
        initial_model=base_model,
        hard_path=target_corpus,
        source_weights={"hard": args.hard_weight, "fresh": (1 - args.hard_weight) / 2, "rehearsal": (1 - args.hard_weight) / 2},
        epoch_records=args.epoch_records,
    )
    meta = {
        "name": name,
        "target": args.target,
        "base": args.base,
        "base_sha256": sha256_file(base_model),
        "target_corpus": str(target_corpus),
        "lr": args.lr,
        "epochs": args.epochs,
        "epoch_records": args.epoch_records,
        "hard_weight": args.hard_weight,
        "trainable": list(TRAINABLE),
        "elapsed_seconds": time.time() - started,
        "training": report,
    }
    (out / f"{name}.json").write_text(json.dumps(meta, indent=2, sort_keys=True))
    print(json.dumps({k: v for k, v in meta.items() if k != "training"}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

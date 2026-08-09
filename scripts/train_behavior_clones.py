#!/usr/bin/env python3
"""Train deck-specific deterministic policy clones from certified recent behavior rows."""

from __future__ import annotations

import argparse
import gzip
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from training.lucario_data import deterministic_gzip_text, sha256_file

TARGETS = {
    "lucario": {"mega_lucario_ex", "mega_lucario_ex_variant_2", "lucario", "lucario_v2"},
    "crustle": {"kangaskhan_crustle", "crustle"},
    "ogerpon": {"ogerpon"},
    "bellibolt": {"iono_bellibolt_ex", "bellibolt"},
    "starmie_froslass": {"mega_starmie_froslass", "starmie"},
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir", action="append", dest="input_dirs",
        help="Certified behavior-shard directory; repeat to combine days/sources",
    )
    parser.add_argument("--output-dir", default="artifacts/recovery_behavior_clones")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--minimum-decisions", type=int, default=1000)
    args = parser.parse_args()
    selected = {name: [] for name in TARGETS}
    input_dirs = args.input_dirs or ["data/grim_daily_v3/behavior_shards"]
    paths = sorted(
        {path for directory in input_dirs for path in Path(directory).glob("*.jsonl.gz")},
        reverse=True,
    )
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                for name, aliases in TARGETS.items():
                    if row.get("behavior_archetype") in aliases:
                        selected[name].append(row)
                        break
    output_dir = Path(args.output_dir)
    reports = {}
    for index, (name, rows) in enumerate(selected.items()):
        if len(rows) < args.minimum_decisions:
            raise RuntimeError(f"{name} clone has only {len(rows)} decisions; need {args.minimum_decisions}")
        data_path = output_dir / name / "recent_behavior.jsonl.gz"
        data_path.parent.mkdir(parents=True, exist_ok=True)
        with deterministic_gzip_text(data_path) as handle:
            for row in sorted(rows, key=lambda item: (str(item["episode_id"]), item["seat"], item["step"])):
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        model_path = output_dir / name / "policy_weights.npz"
        subprocess.run([
            sys.executable, "-m", "training.train_bc", str(data_path),
            "--output", str(model_path), "--feature-version", "3",
            "--epochs", str(args.epochs), "--batch-size", str(args.batch_size),
            "--seed", str(2026080700 + index),
        ], cwd=ROOT, check=True)
        reports[name] = {
            "decisions": len(rows),
            "dataset_sha256": sha256_file(data_path),
            "model": str(model_path),
            "model_sha256": sha256_file(model_path),
        }
    (output_dir / "manifest.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

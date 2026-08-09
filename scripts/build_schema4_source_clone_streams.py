#!/usr/bin/env python3
"""Create whole-episode train/validation streams for exact-Grim source clones."""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from training.lucario_data import deterministic_gzip_text, sha256_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", default="artifacts/live_grim_corpus_v4")
    parser.add_argument("--output-root", default="data/grim_source_clones_v4")
    args = parser.parse_args()
    source_root, output_root = Path(args.input_root), Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    manifest = {"status": "complete", "feature_version": 4, "sources": {}}
    for source in sorted(source_root.glob("submission_*.jsonl.gz")):
        submission_id = int(source.name.split("_")[1].split(".")[0])
        rows = []
        with gzip.open(source, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                bucket = zlib.crc32(str(row["episode_id"]).encode()) % 5
                row["split"] = "validation" if bucket == 0 else "train"
                row["objective_source"] = f"source_clone_{submission_id}"
                row["sample_weight"] = 1.0
                rows.append(row)
        destination = output_root / str(submission_id) / "decisions.jsonl.gz"
        destination.parent.mkdir(parents=True, exist_ok=True)
        with deterministic_gzip_text(destination) as handle:
            for row in sorted(rows, key=lambda item: (str(item["episode_id"]), item["seat"], item["step"])):
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        train_episodes = {str(row["episode_id"]) for row in rows if row["split"] == "train"}
        validation_episodes = {str(row["episode_id"]) for row in rows if row["split"] == "validation"}
        if train_episodes & validation_episodes:
            raise RuntimeError(f"clone split leaked episodes: {submission_id}")
        manifest["sources"][str(submission_id)] = {
            "rows": len(rows),
            "train_rows": sum(row["split"] == "train" for row in rows),
            "validation_rows": sum(row["split"] == "validation" for row in rows),
            "train_episodes": len(train_episodes),
            "validation_episodes": len(validation_episodes),
            "path": str(destination.resolve()),
            "sha256": sha256_file(destination),
        }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

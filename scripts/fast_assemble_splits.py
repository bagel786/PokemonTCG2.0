#!/usr/bin/env python3
"""Fast, low-memory streaming assembler for unified multiday dataset splits.

Streams directly line-by-line from daily shards to avoid in-memory RAM spikes.
"""

from __future__ import annotations

import datetime
import gzip
import json
import os
import sys
import time
import zlib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))

from training.lucario_data import deterministic_gzip_text
from training.replay_refresh import stable_team_bucket

TEMPORAL_DATE = "2026-08-03"


def main():
    extracted_root = ROOT / "data" / "daily_extracted"
    out_dir = ROOT / "data" / "multiday_processed"
    out_dir.mkdir(parents=True, exist_ok=True)

    all_shards = sorted(list(extracted_root.glob("*_decisions.jsonl.gz")))
    print(f"Streaming and assembling {len(all_shards)} daily shards into unified splits...", flush=True)

    out_train_path = out_dir / "train.jsonl.gz"
    out_val_path = out_dir / "validation.jsonl.gz"
    out_team_path = out_dir / "team_holdout.jsonl.gz"
    out_temp_path = out_dir / "temporal_holdout.jsonl.gz"
    out_all_path = out_dir / "multiday_winning_decisions.jsonl.gz"

    split_counts = Counter()
    archetype_counts = Counter()
    date_counts = Counter()
    total_decisions = 0
    seen_keys = set()

    started = time.time()

    with deterministic_gzip_text(out_train_path) as h_train, \
         deterministic_gzip_text(out_val_path) as h_val, \
         deterministic_gzip_text(out_team_path) as h_team, \
         deterministic_gzip_text(out_temp_path) as h_temp, \
         deterministic_gzip_text(out_all_path) as h_all:

        for shard in all_shards:
            if shard.stat().st_size <= 30:
                continue
            shard_date = shard.name.split("_decisions")[0]
            shard_rows = 0
            with gzip.open(shard, "rt", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    r = json.loads(line)
                    k = (str(r["episode_id"]), int(r["seat"]), int(r["step"]))
                    if k in seen_keys:
                        continue
                    seen_keys.add(k)

                    # Determine split
                    if r.get("source_date") == TEMPORAL_DATE:
                        split = "temporal"
                        h_target = h_temp
                    elif stable_team_bucket(r.get("team", "")) == 0:
                        split = "team_holdout"
                        h_target = h_team
                    elif (zlib.crc32(str(r.get("episode_id", "")).encode("utf-8")) % 10) == 0:
                        split = "validation"
                        h_target = h_val
                    else:
                        split = "train"
                        h_target = h_train

                    r["split"] = split
                    out_line = json.dumps(r, separators=(",", ":")) + "\n"
                    h_target.write(out_line)
                    h_all.write(out_line)

                    split_counts[split] += 1
                    archetype_counts[r.get("opponent_archetype", "other")] += 1
                    date_counts[r.get("source_date", shard_date)] += 1
                    total_decisions += 1
                    shard_rows += 1

            print(f"  Processed {shard.name}: {shard_rows} decisions", flush=True)

    elapsed = time.time() - started
    print(f"\nAssembly complete in {elapsed:.1f}s!", flush=True)
    print(f"Total unified exact Grim decisions: {total_decisions}", flush=True)
    print(f"Split breakdown: {dict(split_counts)}", flush=True)
    print(f"Archetype breakdown: {dict(archetype_counts)}", flush=True)

    manifest = {
        "created_at": datetime.datetime.now().isoformat(),
        "temporal_holdout_date": TEMPORAL_DATE,
        "total_shards": len(all_shards),
        "total_decisions": total_decisions,
        "split_counts": dict(split_counts),
        "archetype_counts": dict(archetype_counts),
        "date_counts": dict(sorted(date_counts.items())),
        "files": {
            "all": str(out_all_path),
            "train": str(out_train_path),
            "validation": str(out_val_path),
            "team_holdout": str(out_team_path),
            "temporal_holdout": str(out_temp_path),
        },
    }
    (out_dir / "multiday_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Manifest saved to {out_dir / 'multiday_manifest.json'}")


if __name__ == "__main__":
    main()

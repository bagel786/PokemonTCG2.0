#!/usr/bin/env python3
"""Extract and upweight Seat 1 (Going Second) and early opening setup decisions from multiday dataset."""

import gzip
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT_TRAIN = ROOT / "data" / "multiday_processed" / "train.jsonl.gz"
OUT_DIR = ROOT / "artifacts" / "seat1_data"
OUT_TRAIN = OUT_DIR / "seat1_train.jsonl.gz"
OUT_MANIFEST = OUT_DIR / "seat1_manifest.json"

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not INPUT_TRAIN.exists():
        print(f"Error: {INPUT_TRAIN} not found.")
        return 1

    print(f"Reading from {INPUT_TRAIN}...")
    start_time = time.time()
    
    total_read = 0
    seat_1_count = 0
    seat_1_early_count = 0
    seat_0_retained_count = 0
    
    out_rows = []

    with gzip.open(INPUT_TRAIN, "rt", encoding="utf-8") as f:
        for line in f:
            total_read += 1
            if not line.strip():
                continue
            row = json.loads(line)
            seat = row.get("seat", 0)
            step = row.get("step", 0)
            opp_arch = row.get("opponent_archetype", "other")
            base_weight = row.get("sample_weight", 1.0)
            
            if seat == 1:
                seat_1_count += 1
                if step <= 6:
                    seat_1_early_count += 1
                    # Opening setup / turn 1-2 bench defense
                    if opp_arch in ("lucario", "iono_bellibolt"):
                        row["sample_weight"] = base_weight * 3.5
                    else:
                        row["sample_weight"] = base_weight * 3.0
                else:
                    # Mid/late game going second
                    row["sample_weight"] = base_weight * 2.0
                out_rows.append(row)
            else:
                # Retain every 4th Seat-0 decision to prevent catastrophic forgetting
                if total_read % 4 == 0:
                    seat_0_retained_count += 1
                    row["sample_weight"] = base_weight * 0.5
                    out_rows.append(row)
            
            if total_read % 100000 == 0:
                print(f"Processed {total_read} rows | Seat 1: {seat_1_count} (Early: {seat_1_early_count}) | Retained: {len(out_rows)}")

    elapsed = time.time() - start_time
    print(f"\nCompleted scan in {elapsed:.1f}s.")
    print(f"Total read: {total_read}")
    print(f"Seat 1 extracted: {seat_1_count} (Early setup: {seat_1_early_count})")
    print(f"Seat 0 rehearsal retained: {seat_0_retained_count}")
    print(f"Total Seat-1 training stream size: {len(out_rows)}")

    print(f"Writing to {OUT_TRAIN}...")
    with gzip.open(OUT_TRAIN, "wt", encoding="utf-8") as out_f:
        for r in out_rows:
            out_f.write(json.dumps(r, separators=(",", ":")) + "\n")

    manifest = {
        "source": str(INPUT_TRAIN),
        "total_source_rows": total_read,
        "seat_1_total": seat_1_count,
        "seat_1_early": seat_1_early_count,
        "seat_0_retained": seat_0_retained_count,
        "total_training_rows": len(out_rows),
        "output_file": str(OUT_TRAIN),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, indent=2))
    print(f"Manifest written to {OUT_MANIFEST}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Assemble D1's source-balanced direct-policy and pairwise training corpus."""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from training.lucario_data import deterministic_gzip_text, sha256_file

SHARES = {"teacher": .65, "consensus": .20, "correction": .10, "rehearsal": .05}


def rows(paths):
    for path in paths:
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                if int(row.get("features", {}).get("feature_version", -1)) != 5:
                    raise ValueError(f"D1 refuses non-schema-5 data: {path}")
                yield row


def key(row):
    return str(row["episode_id"]), int(row["seat"]), int(row["step"])


def source(row):
    return str(row.get("source_submission_id") or row.get("source_team") or row.get("team") or row.get("source"))


def source_episode_balance(items, share):
    grouped = defaultdict(lambda: defaultdict(list))
    for row in items:
        grouped[source(row)][str(row["episode_id"])].append(row)
    if not grouped:
        raise ValueError("D1 objective slice is empty")
    result = []
    for source_groups in grouped.values():
        source_share = share / len(grouped)
        for episode_rows in source_groups.values():
            episode_share = source_share / len(source_groups)
            for original in episode_rows:
                row = dict(original)
                row["sample_weight"] = episode_share / len(episode_rows)
                result.append(row)
    return result


def write(path, items, split):
    ordered = sorted(items, key=key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with deterministic_gzip_text(path) as handle:
        for original in ordered:
            row = dict(original)
            row["split"] = split
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    return {
        "path": str(path.resolve()), "rows": len(ordered),
        "episodes": len({str(row["episode_id"]) for row in ordered}),
        "sha256": sha256_file(path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teacher", nargs="+", required=True)
    parser.add_argument("--consensus", nargs="+", required=True)
    parser.add_argument("--corrections", nargs="+", required=True)
    parser.add_argument("--rehearsal", nargs="+", required=True)
    parser.add_argument("--validation", nargs="+", required=True)
    parser.add_argument("--output-root", default="data/grim_d1_v5")
    args = parser.parse_args()

    objective = {
        "teacher": list(rows([ROOT / path for path in args.teacher])),
        "consensus": list(rows([ROOT / path for path in args.consensus])),
        "correction": list(rows([ROOT / path for path in args.corrections])),
        "rehearsal": list(rows([ROOT / path for path in args.rehearsal])),
    }
    if any(row.get("rejected_action") is None for row in objective["correction"]):
        raise ValueError("every certified correction must include a rejected complete action")

    # Higher-confidence objectives replace the same state rather than creating
    # contradictory duplicate labels.
    priority = ("rehearsal", "teacher", "consensus", "correction")
    owner = {}
    for name in priority:
        for row in objective[name]:
            owner[key(row)] = name
    train = []
    counts = Counter()
    for name in priority:
        unique = [row for row in objective[name] if owner[key(row)] == name]
        if not unique:
            continue
        for row in source_episode_balance(unique, SHARES[name]):
            row["objective_source"] = name
            train.append(row)
            counts[name] += 1
    if max(SHARES["rehearsal"], 0) > .10:
        raise AssertionError("R0/A2 rehearsal exceeded the ten-percent ceiling")

    validation = list(rows([ROOT / path for path in args.validation]))
    train_episodes = {str(row["episode_id"]) for row in train}
    validation_episodes = {str(row["episode_id"]) for row in validation}
    overlap = train_episodes & validation_episodes
    if overlap:
        raise RuntimeError(f"D1 whole-episode validation leakage: {next(iter(overlap))}")

    output = ROOT / args.output_root
    manifest = {
        "status": "complete", "feature_version": 5,
        "objective_shares": SHARES,
        "objective_rows_after_priority_dedupe": dict(counts),
        "split_unit": "whole_episode",
        "train": write(output / "train.jsonl.gz", train, "train"),
        "validation": write(output / "validation.jsonl.gz", validation, "validation"),
    }
    path = output / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

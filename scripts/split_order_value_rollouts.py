#!/usr/bin/env python3
"""Hash-split completed order-rollout shards by whole episode for value fitting."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


def split_name(episode_id: str) -> str:
    bucket = int(hashlib.sha256(episode_id.encode("utf-8")).hexdigest()[:8], 16) % 20
    if bucket < 14:
        return "train"
    if bucket < 17:
        return "validation"
    return "holdout"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def build(inputs: list[Path], output_dir: Path) -> dict:
    inputs = [path.resolve() for path in inputs]
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {name: output_dir / f"{name}.jsonl.gz" for name in ("train", "validation", "holdout")}
    handles = {
        name: gzip.GzipFile(filename="", mode="wb", fileobj=path.open("wb"), mtime=0)
        for name, path in outputs.items()
    }
    episode_split: dict[str, str] = {}
    episode_facts: dict[str, tuple[float, str, int]] = {}
    counts = Counter()
    split_orders: dict[str, set[str]] = defaultdict(set)
    split_seats: dict[str, set[int]] = defaultdict(set)
    try:
        for path in inputs:
            with gzip.open(path, "rt", encoding="utf-8") as source:
                for line_number, line in enumerate(source, 1):
                    row = json.loads(line)
                    episode_id = str(row.get("episode_id", ""))
                    if not episode_id:
                        raise ValueError(f"{path}:{line_number}: empty episode id")
                    split = episode_split.setdefault(episode_id, split_name(episode_id))
                    reward = float(row.get("terminal_reward", 99.0))
                    order = str(row.get("actual_order", ""))
                    seat = int(row.get("physical_seat", -1))
                    facts = (reward, order, seat)
                    if episode_id in episode_facts and episode_facts[episode_id] != facts:
                        raise ValueError(f"{path}:{line_number}: inconsistent episode facts")
                    episode_facts[episode_id] = facts
                    handles[split].write(line.encode("utf-8"))
                    counts[f"{split}_rows"] += 1
                    split_orders[split].add(order)
                    split_seats[split].add(seat)
    finally:
        for handle in handles.values():
            raw = handle.fileobj
            handle.close()
            raw.close()

    for episode_id, split in episode_split.items():
        reward, order, seat = episode_facts[episode_id]
        counts[f"{split}_episodes"] += 1
        counts[f"{split}_{'wins' if reward > 0 else 'losses' if reward < 0 else 'draws'}"] += 1
    for split in outputs:
        if split_orders[split] != {"first", "second"}:
            raise ValueError(f"{split} lacks both actual orders: {split_orders[split]}")
        if split_seats[split] != {0, 1}:
            raise ValueError(f"{split} lacks both physical seats: {split_seats[split]}")
        if not counts[f"{split}_wins"] or not counts[f"{split}_losses"]:
            raise ValueError(f"{split} lacks both terminal outcome classes")
    result = {
        "status": "complete",
        "split_method": "sha256(episode_id) mod 20: train 0-13, validation 14-16, holdout 17-19",
        "split_unit": "whole episode",
        "generation_schedule": "single rollout schedule; gameplay confirmation required",
        "inputs": [{"path": str(path), "sha256": sha256_file(path)} for path in inputs],
        "counts": dict(sorted(counts.items())),
        "outputs": {
            name: {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}
            for name, path in outputs.items()
        },
        "episode_overlap": {"train_validation": 0, "train_holdout": 0, "validation_holdout": 0},
    }
    (output_dir / "manifest.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", nargs="+", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    result = build([Path(path) for path in args.input], Path(args.output_dir))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

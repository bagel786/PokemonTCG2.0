#!/usr/bin/env python3
"""Merge and split fresh Grim demonstrations for the Candidate B BC refresh.

The daily corpus contains only winning decisions from the exact 60-card deck.
Teams are held out wholesale, episodes form an internal validation split, and
the newest pure-5k ladder submission is appended as a temporal retention set.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from training.lucario_data import (  # noqa: E402
    canonical_deck,
    deterministic_gzip_text,
    load_deck,
    sha256_file,
)
from training.replay_refresh import split_bucket, stable_team_bucket  # noqa: E402


EXPECTED_MODEL_SHA256 = "d842f85abfc44af9f41979f91795e22c92c179b62e04d5a0a2f9c734e70af1c3"


def rows(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line)


def row_key(row: dict) -> tuple[str, int, int]:
    return str(row["episode_id"]), int(row["seat"]), int(row["step"])


def unit_key(row: dict) -> tuple[str, int]:
    return str(row["episode_id"]), int(row["seat"])


def write_rows(path: Path, values: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with deterministic_gzip_text(temporary) as handle:
        for row in sorted(values, key=row_key):
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    temporary.replace(path)


def prepare(args: argparse.Namespace) -> dict:
    deck = load_deck(args.deck)
    model_hash = sha256_file(args.model)
    if model_hash != EXPECTED_MODEL_SHA256:
        raise RuntimeError(f"Candidate B must start from d842; found {model_hash}")

    daily_paths = [Path(path).resolve() for path in args.daily]
    holdout_path = Path(args.ladder_holdout).resolve()
    own_rehearsal_path = Path(args.own_rehearsal).resolve()
    historical_input_path = Path(args.historical).resolve()
    output_dir = Path(args.output_dir).resolve()
    combined_path = output_dir / "fresh_train_and_holdouts.jsonl.gz"
    daily_path = output_dir / "daily_winning_decisions.jsonl.gz"
    historical_path = output_dir / "historical_exact_rehearsal.jsonl.gz"

    seen = set()
    daily_rows = []
    duplicate_rows = 0
    daily_units: dict[tuple[str, int], dict] = {}
    input_rows = Counter()
    for path in daily_paths:
        for row in rows(path):
            input_rows[str(path)] += 1
            if canonical_deck(row.get("deck", [])) != deck:
                raise RuntimeError(f"non-exact Grim row in {path}: {row_key(row)}")
            if float(row.get("reward", 0.0)) <= 0:
                raise RuntimeError(f"non-winning daily label in {path}: {row_key(row)}")
            key = row_key(row)
            if key in seen:
                duplicate_rows += 1
                continue
            seen.add(key)
            daily_rows.append(row)
            unit = unit_key(row)
            daily_units.setdefault(unit, {
                "team": str(row.get("team", "")),
                "seat": int(row["seat"]),
                "mirror": bool(row.get("opponent_exact_grim", False)),
            })

    heldout_teams = {
        str(row.get("team", ""))
        for row in daily_rows
        if stable_team_bucket(str(row.get("team", ""))) == 0
    }
    split_units: dict[str, set[tuple[str, int]]] = defaultdict(set)
    combined = []
    daily_split_rows = []
    for source_row in daily_rows:
        row = dict(source_row)
        if str(row.get("team", "")) in heldout_teams:
            split = "holdout"
        elif split_bucket(str(row["episode_id"])) == 0:
            split = "validation"
        else:
            split = "train"
        row["split"] = split
        split_units[split].add(unit_key(row))
        daily_split_rows.append(row)
        combined.append(row)

    temporal_units = set()
    temporal_rows = 0
    for source_row in rows(holdout_path):
        if canonical_deck(source_row.get("deck", [])) != deck:
            raise RuntimeError(f"non-exact Grim ladder holdout row: {row_key(source_row)}")
        if source_row.get("source_model_sha256") != EXPECTED_MODEL_SHA256:
            raise RuntimeError(f"ladder holdout is not from d842: {row_key(source_row)}")
        key = row_key(source_row)
        if key in seen:
            raise RuntimeError(f"daily/ladder holdout leakage: {key}")
        seen.add(key)
        row = dict(source_row)
        row["split"] = "temporal"
        combined.append(row)
        temporal_units.add(unit_key(row))
        temporal_rows += 1

    # Reserve every exact-checkpoint ladder row so the historical anchor cannot
    # silently duplicate and overweight our own ladder behavior.
    own_rows = 0
    own_units = set()
    for own_row in rows(own_rehearsal_path):
        if canonical_deck(own_row.get("deck", [])) != deck:
            raise RuntimeError(f"non-exact Grim own rehearsal row: {row_key(own_row)}")
        if own_row.get("source_model_sha256") != EXPECTED_MODEL_SHA256:
            raise RuntimeError(f"own rehearsal is not from d842: {row_key(own_row)}")
        key = row_key(own_row)
        if key in seen:
            raise RuntimeError(f"own rehearsal overlaps fresh/temporal data: {key}")
        seen.add(key)
        own_units.add(unit_key(own_row))
        own_rows += 1

    historical_rows = []
    historical_seen = set()
    historical_counts = Counter()
    for historical_row in rows(historical_input_path):
        historical_counts["input_rows"] += 1
        if canonical_deck(historical_row.get("deck", [])) != deck:
            historical_counts["non_exact_rows_excluded"] += 1
            continue
        key = row_key(historical_row)
        if key in historical_seen:
            historical_counts["duplicate_rows_excluded"] += 1
            continue
        historical_seen.add(key)
        if key in seen:
            historical_counts["cross_source_rows_excluded"] += 1
            continue
        historical_rows.append(historical_row)
    historical_counts["output_rows"] = len(historical_rows)

    if not daily_split_rows or not temporal_rows:
        raise RuntimeError("Candidate B requires both daily demonstrations and ladder holdout rows")
    for required in ("train", "validation", "holdout"):
        if not split_units[required]:
            raise RuntimeError(f"empty required daily split: {required}")

    write_rows(daily_path, daily_split_rows)
    write_rows(combined_path, combined)
    write_rows(historical_path, historical_rows)

    split_row_counts = Counter(str(row["split"]) for row in combined)
    split_episode_counts = {
        split: len({str(row["episode_id"]) for row in combined if row["split"] == split})
        for split in ("train", "validation", "holdout", "temporal")
    }
    split_seats = {
        split: dict(sorted(Counter(str(seat) for _, seat in units).items()))
        for split, units in sorted(split_units.items())
    }
    split_mirrors = {
        split: sum(daily_units[unit]["mirror"] for unit in units)
        for split, units in sorted(split_units.items())
    }
    manifest = {
        "version": 1,
        "purpose": "Candidate B fresh elite BC labels plus untouched latest-5k temporal retention holdout",
        "required_card": 648,
        "feature_version": 2,
        "rules": {
            "train": "daily winning exact-Grim rows not assigned to a holdout",
            "internal_validation": "whole daily episodes with crc32(episode_id) % 10 == 0",
            "team_holdout": "whole daily teams with crc32(team) % 10 == 0",
            "temporal": "all public exact-Grim decisions from submission 55222011",
            "precedence": ["team_holdout", "internal_validation", "train"],
            "deduplication_key": ["episode_id", "seat", "step"],
        },
        "heldout_teams": sorted(heldout_teams),
        "temporal_episode_ids": sorted({episode for episode, _ in temporal_units}),
        "counts": {
            "rows": dict(sorted(split_row_counts.items())),
            "episodes": split_episode_counts,
            "daily_units": {split: len(units) for split, units in sorted(split_units.items())},
            "daily_unit_seats": split_seats,
            "daily_mirror_units": split_mirrors,
            "temporal_units": len(temporal_units),
            "own_rehearsal_rows": own_rows,
            "own_rehearsal_units": len(own_units),
            "historical": dict(sorted(historical_counts.items())),
            "duplicate_daily_rows_skipped": duplicate_rows,
        },
        "inputs": {
            "daily": [
                {"path": str(path), "sha256": sha256_file(path), "rows": input_rows[str(path)]}
                for path in daily_paths
            ],
            "ladder_holdout": {"path": str(holdout_path), "sha256": sha256_file(holdout_path)},
            "own_rehearsal": {
                "path": str(own_rehearsal_path),
                "sha256": sha256_file(own_rehearsal_path),
            },
            "historical": {
                "path": str(historical_input_path),
                "sha256": sha256_file(historical_input_path),
            },
            "model": {"path": str(Path(args.model).resolve()), "sha256": model_hash},
            "deck": {"path": str(Path(args.deck).resolve()), "sha256": sha256_file(args.deck)},
        },
        "outputs": {
            "daily": {"path": str(daily_path), "sha256": sha256_file(daily_path)},
            "combined": {"path": str(combined_path), "sha256": sha256_file(combined_path)},
            "historical_exact": {"path": str(historical_path), "sha256": sha256_file(historical_path)},
        },
        "leakage_checks": {
            "unique_rows_across_daily_and_temporal": True,
            "team_holdout_is_whole_team": True,
            "temporal_submission_excluded_from_rehearsal": True,
            "historical_is_exact_signature_only": True,
            "historical_cross_source_rows_excluded": True,
        },
    }
    manifest_path = output_dir / "split_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daily", action="append", required=True)
    parser.add_argument(
        "--ladder-holdout",
        default="artifacts/candidate_b_20260804/data/holdout_55222011.jsonl.gz",
    )
    parser.add_argument(
        "--own-rehearsal",
        default="artifacts/candidate_b_20260804/data/own_5k_rehearsal.jsonl.gz",
    )
    parser.add_argument("--historical", default="data/processed/elite-2026-07-30-31-v2ctl.jsonl.gz")
    parser.add_argument("--model", default="artifacts/overnight_grim_20260730/grim_selected.npz")
    parser.add_argument("--deck", default="freshstart/decklists/grimmsnarl_marnie.deck.csv")
    parser.add_argument("--output-dir", default="artifacts/candidate_b_20260804/refresh_data")
    args = parser.parse_args()
    manifest = prepare(args)
    print(json.dumps({"counts": manifest["counts"], "outputs": manifest["outputs"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

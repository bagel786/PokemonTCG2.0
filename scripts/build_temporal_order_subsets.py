#!/usr/bin/env python3
"""Split the leakage-safe temporal elite corpus by latched actual order.

Order is assigned to whole ``(episode_id, seat)`` trajectories.  Source
``seat`` must match the encoded acting seat.  A unit is actual-first when any
row encodes ``firstPlayer == yourIndex``; otherwise it is actual-second.  The
only permitted zero flag inside an actual-first trajectory is the turn-zero
IS_FIRST decision recorded before firstPlayer latches.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DIR = ROOT / "artifacts" / "emergency_strength_sprint" / "temporal_elite_schema3"
DEFAULT_OUTPUT_DIR = ROOT / "artifacts" / "elite_policy_candidates" / "temporal_order_second" / "data"
IS_FIRST_CONTEXT = 41

SOURCE_SPECS = {
    "train": {
        "filename": "train_winners_aug4_aug5_rank1_100.jsonl.gz",
        "sha256": "E29C1CF43703273EE49EEA204B8C4D24269A0335CAC6ED6C070D6B332316195E",
        "split": "train",
    },
    "holdout": {
        "filename": "holdout_winners_aug6_rank1_100.jsonl.gz",
        "sha256": "9B3F475EC1042DFC98B1B8E81C85CFF006C769C6BE2B79CB9EFB1D1C64036C94",
        "split": "temporal_holdout",
    },
    "hard_holdout": {
        "filename": "holdout_winners_aug6_rank1_20.jsonl.gz",
        "sha256": "4487864D28D001DD0F12A3C2EFE1C93FC66681499A6844AD424EB3BF53AD3979",
        "split": "temporal_holdout",
    },
}

EXPECTED_COUNTS = {
    "train": {"rows": 134540, "units": 1330, "first_rows": 70414, "first_units": 713,
              "second_rows": 64126, "second_units": 617, "pre_latch_rows": 711},
    "holdout": {"rows": 57672, "units": 561, "first_rows": 31296, "first_units": 314,
                "second_rows": 26376, "second_units": 247, "pre_latch_rows": 314},
    "hard_holdout": {"rows": 17030, "units": 169, "first_rows": 9506, "first_units": 96,
                     "second_rows": 7524, "second_units": 73, "pre_latch_rows": 96},
}


class SubsetError(RuntimeError):
    pass


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def coordinate(row: Mapping[str, Any]) -> tuple[str, int, int]:
    return str(row["episode_id"]), int(row["seat"]), int(row["step"])


def unit_key(row: Mapping[str, Any]) -> tuple[str, int]:
    return str(row["episode_id"]), int(row["seat"])


def _row_facts(row: Mapping[str, Any], expected_split: str) -> tuple[tuple[str, int], float, float, int]:
    if str(row.get("split")) != expected_split:
        raise SubsetError(f"unexpected split at {coordinate(row)}: {row.get('split')!r}")
    features = row.get("features")
    if not isinstance(features, Mapping) or int(features.get("feature_version", -1)) != 3:
        raise SubsetError(f"non-schema-3 row at {coordinate(row)}")
    global_features = features.get("global")
    options = features.get("options")
    if not isinstance(global_features, list) or len(global_features) < 4:
        raise SubsetError(f"missing encoded order features at {coordinate(row)}")
    if not isinstance(options, list) or not options:
        raise SubsetError(f"row has no selectable options at {coordinate(row)}")
    seat = int(row["seat"])
    encoded_seat = float(global_features[2])
    if encoded_seat != float(seat):
        raise SubsetError(
            f"source seat/encoded yourIndex mismatch at {coordinate(row)}: {seat} != {encoded_seat}"
        )
    first_flag = float(global_features[3])
    if first_flag not in (0.0, 1.0):
        raise SubsetError(f"non-binary encoded first-player flag at {coordinate(row)}: {first_flag}")
    turn = float(global_features[0])
    context = int(options[0]["context"])
    return unit_key(row), first_flag, turn, context


def scan_source(path: Path, expected_split: str) -> tuple[dict[tuple[str, int], str], dict[str, Any], set[tuple[str, int, int]]]:
    unit_rows: Counter[tuple[str, int]] = Counter()
    unit_flags: dict[tuple[str, int], set[float]] = defaultdict(set)
    unit_has_latched_turn: Counter[tuple[str, int]] = Counter()
    zero_rows: dict[tuple[str, int], list[tuple[tuple[str, int, int], float, int]]] = defaultdict(list)
    coordinates: set[tuple[str, int, int]] = set()
    episodes: set[str] = set()
    total = 0
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            key = coordinate(row)
            if key in coordinates:
                raise SubsetError(f"duplicate coordinate in {path}: {key}")
            coordinates.add(key)
            unit, flag, turn, context = _row_facts(row, expected_split)
            unit_rows[unit] += 1
            unit_flags[unit].add(flag)
            unit_has_latched_turn[unit] += int(turn > 0.0 or flag == 1.0)
            if flag == 0.0:
                zero_rows[unit].append((key, turn, context))
            episodes.add(unit[0])
            total += 1

    orders: dict[tuple[str, int], str] = {}
    counts: Counter[str] = Counter(rows=total, units=len(unit_rows), episodes=len(episodes))
    anomaly_contexts: Counter[str] = Counter()
    for unit in sorted(unit_rows):
        flags = unit_flags[unit]
        if not flags <= {0.0, 1.0} or not flags:
            raise SubsetError(f"invalid flag set for {unit}: {sorted(flags)}")
        order = "first" if 1.0 in flags else "second"
        orders[unit] = order
        counts[f"{order}_units"] += 1
        counts[f"{order}_rows"] += unit_rows[unit]
        if order == "first":
            anomalies = zero_rows[unit]
            for key, turn, context in anomalies:
                if turn != 0.0 or context != IS_FIRST_CONTEXT:
                    raise SubsetError(
                        f"non-pre-latch zero inside actual-first unit at {key}: turn={turn}, context={context}"
                    )
                counts["pre_latch_rows"] += 1
                anomaly_contexts[str(context)] += 1
            counts["first_units_without_pre_latch_row"] += int(not anomalies)
        elif not unit_has_latched_turn[unit]:
            raise SubsetError(f"actual-second unit has no post-latch turn evidence: {unit}")
    audit = {
        **dict(sorted(counts.items())),
        "pre_latch_contexts": dict(sorted(anomaly_contexts.items())),
        "source_seat_matches_encoded_your_index": total,
        "order_assignment_unit": ["episode_id", "seat"],
    }
    return orders, audit, coordinates


def _deterministic_gzip(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = path.open("wb")
    compressed = gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0)
    return raw, compressed


def write_subsets(
    source: Path,
    orders: Mapping[tuple[str, int], str],
    outputs: Mapping[str, Path],
) -> dict[str, dict[str, Any]]:
    handles = {}
    raw_handles = {}
    counts: dict[str, Counter[str]] = {"first": Counter(), "second": Counter()}
    units: dict[str, set[tuple[str, int]]] = {"first": set(), "second": set()}
    try:
        for order, path in outputs.items():
            raw, compressed = _deterministic_gzip(path)
            raw_handles[order] = raw
            handles[order] = compressed
        with gzip.open(source, "rt", encoding="utf-8") as source_handle:
            for line in source_handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                unit = unit_key(row)
                order = orders.get(unit)
                if order not in {"first", "second"}:
                    raise SubsetError(f"row was not assigned an order: {coordinate(row)}")
                row["actual_order"] = order
                row["actual_order_assignment"] = "whole_episode_seat_from_encoded_first_player_flag"
                rendered = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                handles[order].write(rendered.encode("utf-8"))
                counts[order]["rows"] += 1
                counts[order][f"feature_schema_{int(row['features']['feature_version'])}"] += 1
                units[order].add(unit)
    finally:
        for order in list(handles):
            handles[order].close()
            raw_handles[order].close()
    return {
        order: {
            "path": str(outputs[order].resolve()),
            "sha256": sha256_file(outputs[order]),
            "rows": counts[order]["rows"],
            "units": len(units[order]),
            "feature_schema": 3,
            "actual_order": order,
        }
        for order in ("first", "second")
    }


def _assert_expected(name: str, audit: Mapping[str, Any]) -> None:
    expected = EXPECTED_COUNTS[name]
    changed = {key: (audit.get(key), value) for key, value in expected.items() if audit.get(key) != value}
    if changed:
        raise SubsetError(f"{name} corpus counts changed: {changed}")


def build_subsets(source_dir: Path, output_dir: Path) -> dict[str, Any]:
    source_dir = source_dir.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    scans = {}
    source_coordinates = {}
    for name, spec in SOURCE_SPECS.items():
        path = source_dir / str(spec["filename"])
        if not path.is_file():
            raise FileNotFoundError(path)
        observed_hash = sha256_file(path)
        if observed_hash != spec["sha256"]:
            raise SubsetError(f"{name} source hash mismatch: {observed_hash}")
        orders, audit, coordinates = scan_source(path, str(spec["split"]))
        _assert_expected(name, audit)
        scans[name] = {"path": path, "orders": orders, "audit": audit}
        source_coordinates[name] = coordinates

    train_episodes = {unit[0] for unit in scans["train"]["orders"]}
    holdout_episodes = {unit[0] for unit in scans["holdout"]["orders"]}
    overlap = train_episodes & holdout_episodes
    if overlap:
        raise SubsetError(f"train/holdout episode leakage: {sorted(overlap)[:10]}")
    if not source_coordinates["hard_holdout"] <= source_coordinates["holdout"]:
        raise SubsetError("hard second-order holdout is not a coordinate subset of broad holdout")
    for coordinate_key in source_coordinates["hard_holdout"]:
        unit = coordinate_key[:2]
        if scans["hard_holdout"]["orders"][unit] != scans["holdout"]["orders"][unit]:
            raise SubsetError(f"hard/broad order assignment mismatch: {coordinate_key}")

    outputs = {}
    for name, scan in scans.items():
        paths = {
            order: output_dir / f"{name}_{order}.jsonl.gz" for order in ("first", "second")
        }
        outputs[name] = write_subsets(scan["path"], scan["orders"], paths)

    manifest = {
        "schema_version": 1,
        "kind": "temporal_elite_whole_trajectory_actual_order_subsets",
        "inputs": {
            name: {
                "path": str(scan["path"]),
                "sha256": SOURCE_SPECS[name]["sha256"],
                "audit": scan["audit"],
            }
            for name, scan in scans.items()
        },
        "rules": {
            "feature_schema": 3,
            "unit": ["episode_id", "seat"],
            "source_seat_must_equal_encoded_global_2_your_index": True,
            "actual_first": "any row in unit has encoded global[3] == 1",
            "actual_second": "all rows in unit have encoded global[3] == 0 and unit has post-latch turn evidence",
            "pre_latch_exception": "inside actual-first units only: global[3] == 0 is allowed solely at turn 0 / SelectContext.IS_FIRST (41)",
            "rows_are_never_split_across_orders": True,
        },
        "leakage": {
            "train_holdout_episode_overlap": [],
            "hard_holdout_coordinate_subset_of_broad": True,
            "hard_broad_order_assignments_identical": True,
        },
        "outputs": outputs,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    manifest = build_subsets(args.source_dir, args.output_dir)
    print(json.dumps({
        "manifest": str((args.output_dir / "manifest.json").resolve()),
        "outputs": manifest["outputs"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Audit scheduled and exact uint32 engine seeds for historical and PEVL runs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
FRESH = ROOT / "paper/data/fresh_confirmation/raw"
OUTPUT = ROOT / "paper/data/seed_namespace_audit.json"
UINT32_MAX = 2**32 - 1
PEVL_PROTOCOL_COMMIT = "803257f102232763fc88d28c14b668f9b62eb277"

HISTORICAL_FILES = (
    "grim_b0.json",
    "grim_d842_runtime.json",
    "grim_master_v1.json",
    "grim_replay_refresh.json",
    "starmie_v2_boss_atk.json",
    "dipplin_d1.json",
    "alakazam_2_4a_no_search.json",
)

TRACE_BASES = {
    "B0": 2026072700,
    "d842-runtime": 2026073700,
    "master-v1": 2026074700,
    "replay-refresh": 2026075700,
    "Alakazam-no-search": 2026078700,
}
FACTORIAL_BASES = {
    "B0": 2026082700,
    "d842-runtime": 2026083700,
    "master-v1": 2026084700,
    "replay-refresh": 2026085700,
    "Alakazam-no-search": 2026086700,
}
STRESS_BASES = {"Starmie": 2026092700, "Dipplin": 2026093700}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def engine_seed(scheduled_seed: int) -> int:
    return int(scheduled_seed) & UINT32_MAX


def schedule(base: int, per_order: int) -> list[int]:
    return [
        base + order_offset + index
        for order_offset in (0, 1_000_000)
        for index in range(per_order)
    ]


def summarize(values: Iterable[int]) -> dict:
    scheduled = [int(value) for value in values]
    converted = [engine_seed(value) for value in scheduled]
    collision_groups: dict[int, list[int]] = {}
    for requested, exact in zip(scheduled, converted):
        collision_groups.setdefault(exact, []).append(requested)
    collisions = {
        str(exact): requests
        for exact, requests in collision_groups.items()
        if len(set(requests)) > 1
    }
    return {
        "scheduled_count": len(scheduled),
        "scheduled_unique": len(set(scheduled)),
        "scheduled_min": min(scheduled),
        "scheduled_max": max(scheduled),
        "scheduled_outside_uint32": sum(not 0 <= value <= UINT32_MAX for value in scheduled),
        "conversion_changed": sum(left != right for left, right in zip(scheduled, converted)),
        "engine_seed_unique": len(set(converted)),
        "engine_seed_min": min(converted),
        "engine_seed_max": max(converted),
        "collision_groups": collisions,
        "passed_no_collision": not collisions and len(set(converted)) == len(converted),
    }


def main() -> int:
    historical_rows: list[dict] = []
    sources: list[dict] = []
    for filename in HISTORICAL_FILES:
        path = FRESH / filename
        payload = json.loads(path.read_text(encoding="utf-8"))
        sources.append({
            "path": str(path.relative_to(ROOT)),
            "sha256": sha256_file(path),
        })
        for row in payload["rows"]:
            if row["arm"] == "candidate":
                historical_rows.append({
                    "source": filename,
                    "scheduled_seed": int(row["seed"]),
                    "engine_seed_uint32": engine_seed(int(row["seed"])),
                    "actual_order": str(row["actual_order"]),
                    "pair_index": int(row["pair_index"]),
                })

    historical = summarize(row["scheduled_seed"] for row in historical_rows)
    historical["recorded_field_semantics"] = (
        "Historical JSON stores the requested Python integer under `seed`; "
        "the adapter passed ctypes.c_uint32(seed).value to BattleStartSeeded."
    )

    prospective_schedules = {
        "trace_preflight": {
            label: summarize(schedule(base, 25)) for label, base in TRACE_BASES.items()
        },
        "factorial": {
            label: summarize(schedule(base, 200)) for label, base in FACTORIAL_BASES.items()
        },
        "timed_search_stress": {
            label: summarize(schedule(base, 50)) for label, base in STRESS_BASES.items()
        },
    }
    prospective_all = [
        value
        for bases, count in ((TRACE_BASES, 25), (FACTORIAL_BASES, 200), (STRESS_BASES, 50))
        for base in bases.values()
        for value in schedule(base, count)
    ]
    prospective = summarize(prospective_all)
    historical_exact = {row["engine_seed_uint32"] for row in historical_rows}
    prospective_exact = {engine_seed(value) for value in prospective_all}

    result = {
        "conversion_rule": "scheduled_seed & 0xffffffff",
        "uint32_max": UINT32_MAX,
        "historical_fresh_confirmation": historical,
        "prospective_by_schedule": prospective_schedules,
        "prospective_all": prospective,
        "historical_prospective_engine_seed_overlap": sorted(historical_exact & prospective_exact),
        "prospective_passed": prospective["passed_no_collision"]
        and not (historical_exact & prospective_exact),
        "sources": sources,
        "provenance": {
            "script": str(Path(__file__).resolve().relative_to(ROOT)),
            "script_sha256": sha256_file(Path(__file__).resolve()),
            # This audit is evidence for the prospectively frozen design.  Bind
            # it to that design commit, rather than to whichever later commit
            # happens to regenerate the deterministic derived file.
            "git_commit": PEVL_PROTOCOL_COMMIT,
            "provenance_role": "protocol_commit",
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not result["prospective_passed"]:
        raise RuntimeError("prospective seed namespace failed collision/overlap audit")
    print(json.dumps({
        "output": str(OUTPUT),
        "historical": historical,
        "prospective": prospective,
        "historical_prospective_overlap": len(historical_exact & prospective_exact),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Recalculate central protocol statistics directly from retained raw rows.

This module deliberately does not import the production analyzers and does not
use processed summaries as numerical inputs.  Processed manuscript artifacts
are read only after calculation, as non-authoritative comparison targets.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


SCRIPT = Path(__file__).resolve()
FINAL = SCRIPT.parents[1]
ROOT = SCRIPT.parents[3]
PROTOCOL_COMMIT = "803257f102232763fc88d28c14b668f9b62eb277"
PROTOCOL_PATH = "paper/protocol/PEVL_PROSPECTIVE_PROTOCOL.md"
PROTOCOL_SHA256 = "8b9329b948a054fc7252b9c2662490890e0a8439ad852393c6e25f537c8b887e"
FROZEN_ANALYZER_PATH = "paper/scripts/analyze_pevl.py"
FROZEN_ANALYZER_SHA256 = "e258049cedeff13cc84c82e69a43f3416639c98d4e70d25c0799f06e33ba4f7a"
PROTOCOL_ID = "PEVL_PROSPECTIVE_PROTOCOL_20260824"
ORDER_OFFSET = 1_000_000
ORDERS = ("first", "second")
REWEIGHTING_DRAWS = 100_000
STRESS_REWEIGHTING_SEED = 2026083118
FACTORIAL_REWEIGHTING_SEED = 2026083117


class AuditError(ValueError):
    """Raised when a source, schema, or numerical invariant fails."""


# These are the Git-tracked retained acquisition records.  Their row arrays are
# the highest-priority quantitative source in this audit.  The prospective
# files are sanitized copies of locally retained proofs (paths were made
# relative and redistribution metadata was added), but their execution rows
# remain the raw acquisition rows.
EXPECTED_SOURCE_HASHES: dict[str, str] = {
    "paper/data/ablation/raw/c2_identity_a2_alakazam_no_search.json": "db010f55881867bee9a9954c4de764fa86e76e500ef5ea4ac5ce2f047b7b8416",
    "paper/data/ablation/raw/c2_identity_a2_dipplin.json": "27155ea8810d0d466b100fe10bbe9788e2bf73d3154908fbd0cc351461ba2ffa",
    "paper/data/ablation/raw/c2_identity_a2_grim_b0.json": "9027d8e1f8e223a9c1302f387eccf1e3f973398fd73614ae30046400930f9233",
    "paper/data/ablation/raw/c2_identity_a2_grim_d842_runtime.json": "600501d6b78552e9a410e586763e9b7673b66233520b6f46aaa8221839e45592",
    "paper/data/ablation/raw/c2_identity_a2_grim_master_v1.json": "bcaf8401c04a180567fa38e92931e1cffb9fda0447bb2e72132379216327d005",
    "paper/data/ablation/raw/c2_identity_a2_grim_replay_refresh.json": "7ef754cbb07ff21899990af9f7ea1d32a6fe74da45a6c732f5d3de4cddf73926",
    "paper/data/ablation/raw/c2_identity_a2_starmie.json": "26c08c7ad3bd20742b44ebb80d662eb9d85c67876ade83e5a0fbb15510656b3f",
    "paper/data/ablation/raw/c3_blind_trained_alakazam_no_search.json": "eb611718099704492fc2b4192cd87f9dcad67fbbbc75bbbe13aec4a74848fdd0",
    "paper/data/ablation/raw/c3_blind_trained_dipplin.json": "fc19c0062ecd04441ca93ba5bfe5d119fde0b0e5b8c89ff79011255053d1a891",
    "paper/data/ablation/raw/c3_blind_trained_grim_b0.json": "b8cea10f24913d9b2c1853c847e60d3d10e748f5d891948c8071a29444d53b96",
    "paper/data/ablation/raw/c3_blind_trained_grim_d842_runtime.json": "0070df3c12cd02c848fee621a849efe5a626c8aa8b0af00e220819f0ce0f5883",
    "paper/data/ablation/raw/c3_blind_trained_grim_master_v1.json": "a53390700ebff70f0514731ecde68435061254211ab125d691da3ab71c0ee246",
    "paper/data/ablation/raw/c3_blind_trained_grim_replay_refresh.json": "f1d2006c08a3fda6f847998185590132a7909273bf36fcb44ac5fe16166914a1",
    "paper/data/ablation/raw/c3_blind_trained_starmie.json": "9d2b0c987afd49c25e5c54814263c0eace8c8cc5eabe918548e5c2664ea3bf51",
    "paper/data/fresh_confirmation/raw/alakazam_2_4a_no_search.json": "e414b58f370c6457e36dcd145c6dbbad80a2fad178ce3112a01fc533ca25bb65",
    "paper/data/fresh_confirmation/raw/dipplin_d1.json": "3892c62c01a04a8b8c24a2d824827096c72ba7b543a97407e763d53b0dd0bac1",
    "paper/data/fresh_confirmation/raw/grim_b0.json": "3c161a3d52c0e2ee383cb6b7493ad5ded03ab320097bb6b184a7a71d086407fb",
    "paper/data/fresh_confirmation/raw/grim_d842_runtime.json": "b2d325adbfa752ea2ef05cc0e6c001ca5b2624e70aa5b3230fe61f16f2032370",
    "paper/data/fresh_confirmation/raw/grim_master_v1.json": "c52c072d1df4dd6d8dfbbf668d2aeeee553a50b6cb12b0157a523b1d9b2b9734",
    "paper/data/fresh_confirmation/raw/grim_replay_refresh.json": "1c31c89df874ba793112922026db322a2c24c30341b7d71b9562e87982e081ef",
    "paper/data/fresh_confirmation/raw/starmie_v2_boss_atk.json": "a25e535548268f23ec364de322a5b42566da35a4b0ada4eb6b6f3bf375457ab7",
    "paper/data/pevl/preflight/raw/c1_alakazam_no_search.json": "7844c370c35a6ecdc6ab05d3e902fb7e0fb10d623093ddc9f5ea0bdf10919b41",
    "paper/data/pevl/preflight/raw/c1_b0.json": "c19205bb2b5593a069b2257fd9f802e6ac25594bd9d6246afd6f632a74f7e3cd",
    "paper/data/pevl/preflight/raw/c1_d842.json": "2cb1af06351851a4790acba58bb43125a0bf933f857980bf5a2c0da65437a5ef",
    "paper/data/pevl/preflight/raw/c1_master.json": "10a802240062830dc922a4dab352a37e567519fac2884cf24728c027ca4fd999",
    "paper/data/pevl/preflight/raw/c1_replay.json": "53ffb50029bf614fe95d3bc9a9e9bee6c32757880ccdc1f99ac5e6f220f34749",
    "paper/data/pevl/preflight/raw/c2_alakazam_no_search.json": "5e320f89a3962cd37940cfc27f931b318e7b73763ef1e281bd4b0fd7d6a024c8",
    "paper/data/pevl/preflight/raw/c2_b0.json": "72a48bebe8f4a6f003228f47aba1f43489d9892e2e3973f631a4d51a2252fba7",
    "paper/data/pevl/preflight/raw/c2_d842.json": "ae1843682bcaf3d1a511fe8ce194705baaede500c6faefa9301f276daaa82f00",
    "paper/data/pevl/preflight/raw/c2_master.json": "76e39b00ea0baa009a310cae096d48e99ff8ec459942c2305f325cdd4f1c40e6",
    "paper/data/pevl/preflight/raw/c2_replay.json": "b7ec500f183238f0b211568694dea5028334044be282a8fd15dcc2cecef43958",
    "paper/data/pevl/preflight/raw/c3_alakazam_no_search.json": "8c902bc88d5740b94d21e31576914455e5a6901917301b10a0614525da5c523f",
    "paper/data/pevl/preflight/raw/c3_b0.json": "c59a044956d175fb6f0d43eed1e6888c9c195d59d63929dd5c5f9bb63da99b6a",
    "paper/data/pevl/preflight/raw/c3_d842.json": "8d95ff7549773601f8cd0e34873d4dbcc008c5393cfa1a58d80186fb1df2c5ca",
    "paper/data/pevl/preflight/raw/c3_master.json": "a1772522229932dfbd66e73bad6747a1b98b881b9da00236c3589aedf367aad5",
    "paper/data/pevl/preflight/raw/c3_replay.json": "e814c53e6b5bbf680494e81dea2669cef7093fd4af9936ad0c244a38cb2834af",
    "paper/data/pevl/preflight/raw/c4_alakazam_no_search.json": "ef193827053b6d32b9e1d8c0be33fe6c9ca5f1eb9368449d85249f87537ab716",
    "paper/data/pevl/preflight/raw/c4_b0.json": "55866a9c661bb9b6ac317a8e0a2c35b4459fa272ac7f849eee7adc7a3c0b1891",
    "paper/data/pevl/preflight/raw/c4_d842.json": "a05e64dadef9961d0feb517633f3cb25b2aa1210262d57dd6120db24ed846665",
    "paper/data/pevl/preflight/raw/c4_master.json": "d237172118b87a0e423d563147aaa992ab2e54f5754f90475d64a0ecb6c222b1",
    "paper/data/pevl/preflight/raw/c4_replay.json": "65fa19c99c178085e74efdee058561ba21fd998052ae64a2b0ec7c9e35e780ec",
    "paper/data/pevl/stress/raw/dipplin.json": "9e602ec4f55201a534582519664d0be9f2be320d976719c5cb223ceb5284ba22",
    "paper/data/pevl/stress/raw/starmie.json": "cf0fe2bc85e702c5713ddbd6b6aab0697244c5364d06c8b8f310ce8f5251adb3",
    "paper/data/pevl/factorial/raw/c2_alakazam_no_search.json": "36d508dc4419371878b0c12458d340657944b7bbe7e2f56bad1e510772ca42ba",
    "paper/data/pevl/factorial/raw/c2_b0.json": "c849b67724232f827d9fcca7a336e6182ac94c7807c4b624ed3e7a195bdbf55d",
    "paper/data/pevl/factorial/raw/c2_d842.json": "13d67523036b175d547bcbcf9a05087c47825250b17222899a443677143e9cd9",
    "paper/data/pevl/factorial/raw/c2_master.json": "27ada4a5546673f83017a6605b69b571e52ba44977e3bc566bc6adc4155a346c",
    "paper/data/pevl/factorial/raw/c2_replay.json": "ef51759755e705025644090dabbbeb98d41159fd0562ad2560bb8264d16d514d",
    "paper/data/pevl/factorial/raw/c3_alakazam_no_search.json": "b885d8d9685bf77b3e210d978ac810c78de7509197e75681bac27868df6acaf6",
    "paper/data/pevl/factorial/raw/c3_b0.json": "2e2e2fd12e970b51621e22af7828b7d9ba2e76391f9451a2043c5c183aa8f1a4",
    "paper/data/pevl/factorial/raw/c3_d842.json": "c9a9e180ebed69d4466cae5aa7e5f2a0c13c45e4857608fd60d519bf4b233b21",
    "paper/data/pevl/factorial/raw/c3_master.json": "218758bec05ab48833c653d2825d3fba14db9f37186f54980c4137ce1eaf4c6e",
    "paper/data/pevl/factorial/raw/c3_replay.json": "c2ab92fb07a567881d895d6a87df025f52279916b3e92f32198685882d36a998",
    "paper/data/pevl/factorial/raw/c4_alakazam_no_search.json": "513cfef6d6ad4e2a7e2bcd0b7138ec038d907ad32e29385f8947482be292ff34",
    "paper/data/pevl/factorial/raw/c4_b0.json": "64eb94ced8c4704819d2fc29fbf71411d83eac9c0abee94bd5f4fe26bb625110",
    "paper/data/pevl/factorial/raw/c4_d842.json": "306a91fbb888e2851935964e83d24822c66c38e181450db8b0e750c10dc15327",
    "paper/data/pevl/factorial/raw/c4_master.json": "f9db7c96705cbd39fc26ebe6dc255dcd4e7b15f773b88015b8ec2dbbb59eff75",
    "paper/data/pevl/factorial/raw/c4_replay.json": "3f188e641c7f332f5fa601cacd8dba6237dbab91b19075f04caa8b4f3090780f",
}


LEGACY_TOP_FIELDS = frozenset({
    "actual_orders", "base_seed", "candidate", "candidate_sha256", "control",
    "control_sha256", "elapsed_seconds", "engine", "engine_sha256", "games",
    "opponent", "opponent_sha256", "orders", "overall", "pairs_per_order",
    "production_engine", "production_engine_preserved",
    "production_engine_sha256_after", "production_engine_sha256_before",
    "rng_provenance", "rows", "workers",
})
LEGACY_ROW_FIELDS = frozenset({
    "actual_order", "arm", "decisions", "draw", "hero_policy_errors",
    "opponent_policy_errors", "pair_index", "physical_seat", "seed", "task_id",
    "trace_bytes", "trace_sha256", "win",
})
TRACE_TOP_FIELDS = frozenset({
    "admission_decision", "audit_mode", "base_seed", "claim", "engine",
    "engine_sha256", "excluded_from_trace", "execution_environment",
    "execution_plan", "hero_env", "hero_sha256", "max_decisions", "mismatches",
    "opponent_env", "opponent_sha256", "order_seed_offset", "passed",
    "protocol_commit", "protocol_id", "redistribution", "run_fingerprint_scope",
    "run_fingerprint_sha256", "run_uuid", "runs", "schedule_fingerprint_sha256",
    "seed_conversion", "seeds_per_order", "tasks", "trace_files", "trace_mode",
    "trace_payload_files_written",
})
PROSPECTIVE_ROW_FIELDS = frozenset({
    "actual_order", "arm", "decisions", "draw", "elapsed_wall_seconds",
    "engine_seed_uint32", "enqueue_position", "execution_variant", "hero_env",
    "hero_policy_errors", "max_decisions", "opponent_env", "opponent_policy_errors",
    "pair_index", "physical_seat", "process_start_method", "protocol_commit",
    "protocol_id", "public_trace_sha256", "requested_seed", "run_fingerprint_sha256",
    "run_uuid", "schedule_direction", "schedule_fingerprint_sha256",
    "scheduled_seed", "seed", "seed_conversion_rule", "task_id", "trace_bytes",
    "trace_mode", "trace_sha256", "win", "worker_count", "worker_pid",
    "worker_process_name",
})
FACTORIAL_TOP_FIELDS = frozenset({
    "actual_orders", "base_seed", "candidate", "candidate_sha256",
    "capture_trace_digest", "control", "control_sha256", "elapsed_seconds", "engine",
    "engine_sha256", "execution_environment", "execution_plan", "games", "hero_env",
    "max_decisions", "opponent", "opponent_env", "opponent_sha256",
    "order_seed_offset", "orders", "overall", "pairs_per_order", "production_engine",
    "production_engine_preserved", "production_engine_sha256_after",
    "production_engine_sha256_before", "protocol_commit", "protocol_id",
    "redistribution", "rng_provenance", "rows", "run_fingerprint_scope",
    "run_fingerprint_sha256", "run_uuid", "schedule_fingerprint_sha256",
    "seed_conversion", "workers",
})


HISTORICAL_BASES = {
    "b0": 202608230000,
    "d842_runtime": 202608231000,
    "master_v1": 202608232000,
    "replay_refresh": 202608233000,
    "starmie": 202608234000,
    "dipplin": 202608235000,
    "alakazam_no_search": 202608236000,
}
HISTORICAL_FILES = {
    "C2": {
        "b0": "paper/data/ablation/raw/c2_identity_a2_grim_b0.json",
        "d842_runtime": "paper/data/ablation/raw/c2_identity_a2_grim_d842_runtime.json",
        "master_v1": "paper/data/ablation/raw/c2_identity_a2_grim_master_v1.json",
        "replay_refresh": "paper/data/ablation/raw/c2_identity_a2_grim_replay_refresh.json",
        "starmie": "paper/data/ablation/raw/c2_identity_a2_starmie.json",
        "dipplin": "paper/data/ablation/raw/c2_identity_a2_dipplin.json",
        "alakazam_no_search": "paper/data/ablation/raw/c2_identity_a2_alakazam_no_search.json",
    },
    "C3": {
        "b0": "paper/data/ablation/raw/c3_blind_trained_grim_b0.json",
        "d842_runtime": "paper/data/ablation/raw/c3_blind_trained_grim_d842_runtime.json",
        "master_v1": "paper/data/ablation/raw/c3_blind_trained_grim_master_v1.json",
        "replay_refresh": "paper/data/ablation/raw/c3_blind_trained_grim_replay_refresh.json",
        "starmie": "paper/data/ablation/raw/c3_blind_trained_starmie.json",
        "dipplin": "paper/data/ablation/raw/c3_blind_trained_dipplin.json",
        "alakazam_no_search": "paper/data/ablation/raw/c3_blind_trained_alakazam_no_search.json",
    },
    "C4": {
        "b0": "paper/data/fresh_confirmation/raw/grim_b0.json",
        "d842_runtime": "paper/data/fresh_confirmation/raw/grim_d842_runtime.json",
        "master_v1": "paper/data/fresh_confirmation/raw/grim_master_v1.json",
        "replay_refresh": "paper/data/fresh_confirmation/raw/grim_replay_refresh.json",
        "starmie": "paper/data/fresh_confirmation/raw/starmie_v2_boss_atk.json",
        "dipplin": "paper/data/fresh_confirmation/raw/dipplin_d1.json",
        "alakazam_no_search": "paper/data/fresh_confirmation/raw/alakazam_2_4a_no_search.json",
    },
}
PREFLIGHT_BASES = {
    "b0": 2026072700,
    "d842": 2026073700,
    "master": 2026074700,
    "replay": 2026075700,
    "alakazam_no_search": 2026078700,
}
STRESS_BASES = {"starmie": 2026092700, "dipplin": 2026093700}
FACTORIAL_BASES = {
    "b0": 2026082700,
    "d842": 2026083700,
    "master": 2026084700,
    "replay": 2026085700,
    "alakazam_no_search": 2026086700,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def require_equal(observed: Any, expected: Any, label: str) -> None:
    if observed != expected:
        raise AuditError(f"{label}: expected {expected!r}, found {observed!r}")


def validate_exact_keys(value: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    observed = frozenset(value)
    if observed != expected:
        missing = sorted(expected - observed)
        unexpected = sorted(observed - expected)
        raise AuditError(f"{label} schema drift: missing={missing}, unexpected={unexpected}")


def validate_quantile_pair(quantiles: Sequence[float], label: str) -> list[float]:
    require(len(quantiles) == 2, f"{label}: quantile pair must contain two endpoints")
    low, high = (float(value) for value in quantiles)
    require(math.isfinite(low) and math.isfinite(high), f"{label}: nonfinite endpoint")
    require(low <= high, f"{label}: reversed quantile pair")
    return [low, high]


def _reject_json_constant(value: str) -> None:
    raise AuditError(f"JSON contains nonfinite constant {value}")


def count_finite_numbers(value: Any, label: str = "root") -> int:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return 0
    if isinstance(value, (int, float)):
        require(math.isfinite(float(value)), f"{label}: nonfinite numeric value")
        return 1
    if isinstance(value, list):
        return sum(count_finite_numbers(item, f"{label}[{index}]") for index, item in enumerate(value))
    if isinstance(value, dict):
        return sum(count_finite_numbers(item, f"{label}.{key}") for key, item in value.items())
    raise AuditError(f"{label}: unsupported JSON value type {type(value).__name__}")


def load_json_strict(path: Path) -> tuple[dict[str, Any], int]:
    value = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_json_constant)
    require(isinstance(value, dict), f"{path}: top-level JSON object required")
    return value, count_finite_numbers(value, str(path))


def source_role(path: str) -> str:
    if "/ablation/raw/" in path or "/fresh_confirmation/raw/" in path:
        return "historical_raw_acquisition"
    if "/preflight/raw/" in path:
        return "preflight_raw_acquisition"
    if "/stress/raw/" in path:
        return "stress_raw_acquisition"
    if "/factorial/raw/" in path:
        return "factorial_raw_acquisition"
    raise AuditError(f"unclassified source: {path}")


def load_and_verify_sources() -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    directories = (
        ROOT / "paper/data/ablation/raw",
        ROOT / "paper/data/fresh_confirmation/raw",
        ROOT / "paper/data/pevl/preflight/raw",
        ROOT / "paper/data/pevl/stress/raw",
        ROOT / "paper/data/pevl/factorial/raw",
    )
    actual_inventory = {
        path.relative_to(ROOT).as_posix()
        for directory in directories
        for path in directory.glob("*.json")
    }
    require_equal(actual_inventory, set(EXPECTED_SOURCE_HASHES), "raw source inventory")
    require_equal(sha256_file(ROOT / PROTOCOL_PATH), PROTOCOL_SHA256, "frozen protocol hash")
    frozen_analyzer = subprocess.run(
        ["git", "show", f"{PROTOCOL_COMMIT}:{FROZEN_ANALYZER_PATH}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    require_equal(
        hashlib.sha256(frozen_analyzer).hexdigest(),
        FROZEN_ANALYZER_SHA256,
        "frozen analyzer blob hash",
    )

    payloads: dict[str, dict[str, Any]] = {}
    manifest: list[dict[str, Any]] = []
    numeric_values_checked = 0
    role_counts: Counter[str] = Counter()
    for relative in sorted(EXPECTED_SOURCE_HASHES):
        path = ROOT / relative
        observed_hash = sha256_file(path)
        require_equal(observed_hash, EXPECTED_SOURCE_HASHES[relative], f"source hash {relative}")
        payload, numeric_count = load_json_strict(path)
        payloads[relative] = payload
        numeric_values_checked += numeric_count
        role = source_role(relative)
        role_counts[role] += 1
        manifest.append({"path": relative, "role": role, "sha256": observed_hash})
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return payloads, {
        "source_count": len(manifest),
        "role_counts": dict(sorted(role_counts.items())),
        "numeric_values_checked": numeric_values_checked,
        "nonfinite_values": 0,
        "source_manifest_sha256": hashlib.sha256(canonical).hexdigest(),
        "sources": manifest,
        "protocol": {"path": PROTOCOL_PATH, "sha256": PROTOCOL_SHA256},
        "frozen_analyzer": {
            "git_object": f"{PROTOCOL_COMMIT}:{FROZEN_ANALYZER_PATH}",
            "sha256": FROZEN_ANALYZER_SHA256,
            "role": "resolves the prose ambiguity by specifying a pooled overall stress resampling procedure and four separate stratum procedures; it supplies no data to this audit",
        },
    }


def require_int(value: Any, label: str, *, minimum: int | None = None) -> int:
    require(isinstance(value, int) and not isinstance(value, bool), f"{label}: integer required")
    result = int(value)
    if minimum is not None:
        require(result >= minimum, f"{label}: must be at least {minimum}")
    return result


def require_binary(value: Any, label: str) -> int:
    result = require_int(value, label)
    require(result in {0, 1}, f"{label}: binary value required")
    return result


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def expected_seed(base: int, order: str, index: int) -> int:
    return base + (ORDER_OFFSET if order == "second" else 0) + index


def validate_legacy_file(
    payload: dict[str, Any], *, path: str, base_seed: int
) -> dict[tuple[str, int, str], dict[str, Any]]:
    validate_exact_keys(payload, LEGACY_TOP_FIELDS, f"{path} top level")
    require_equal(payload["actual_orders"], list(ORDERS), f"{path} actual orders")
    require_equal(payload["base_seed"], base_seed, f"{path} base seed")
    require_equal(payload["pairs_per_order"], 200, f"{path} pairs per order")
    require_equal(payload["games"], 800, f"{path} games")
    require_equal(payload["production_engine_preserved"], True, f"{path} engine sentinel")
    require_equal(
        payload["production_engine_sha256_before"],
        payload["production_engine_sha256_after"],
        f"{path} production engine digest",
    )
    rows = payload.get("rows")
    require(isinstance(rows, list), f"{path}: rows array required")
    require_equal(len(rows), 800, f"{path} row count")
    mapped: dict[tuple[str, int, str], dict[str, Any]] = {}
    for position, row in enumerate(rows):
        require(isinstance(row, dict), f"{path} row {position}: object required")
        validate_exact_keys(row, LEGACY_ROW_FIELDS, f"{path} row {position}")
        order = row["actual_order"]
        arm = row["arm"]
        require(order in ORDERS, f"{path} row {position}: invalid order")
        require(arm in {"candidate", "control"}, f"{path} row {position}: invalid arm")
        index = require_int(row["pair_index"], f"{path} row {position} pair index")
        require(0 <= index < 200, f"{path} row {position}: pair index out of range")
        key = (order, index, arm)
        require(key not in mapped, f"{path}: duplicate row key {key}")
        require_equal(row["task_id"], f"{order}-{index:05d}-{arm}", f"{path} task id {key}")
        require_equal(row["seed"], expected_seed(base_seed, order, index), f"{path} seed {key}")
        require_equal(row["physical_seat"], index % 2, f"{path} seat {key}")
        win = require_binary(row["win"], f"{path} win {key}")
        draw = require_binary(row["draw"], f"{path} draw {key}")
        require(win + draw <= 1, f"{path}: simultaneous win and draw {key}")
        require_int(row["decisions"], f"{path} decisions {key}", minimum=0)
        require_int(row["hero_policy_errors"], f"{path} hero errors {key}", minimum=0)
        require_int(row["opponent_policy_errors"], f"{path} opponent errors {key}", minimum=0)
        require_equal(row["trace_bytes"], 0, f"{path} trace bytes {key}")
        require_equal(row["trace_sha256"], None, f"{path} trace digest {key}")
        mapped[key] = row
    require_equal(len(mapped), 800, f"{path} unique rows")
    return mapped


def audit_historical(payloads: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    control_rows: dict[tuple[str, str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    source_rows = 0
    controls_by_context: dict[str, set[str]] = defaultdict(set)
    for cell in ("C2", "C3", "C4"):
        for context in HISTORICAL_BASES:
            path = HISTORICAL_FILES[cell][context]
            mapped = validate_legacy_file(payloads[path], path=path, base_seed=HISTORICAL_BASES[context])
            source_rows += len(mapped)
            controls_by_context[context].add(str(payloads[path]["control_sha256"]))
            for order in ORDERS:
                for index in range(200):
                    control_rows[(context, order, index)][cell] = mapped[(order, index, "control")]

    require_equal(source_rows, 16_800, "historical raw execution rows")
    require_equal(len(control_rows), 2_800, "historical comparison units")
    for context, digests in controls_by_context.items():
        require_equal(len(digests), 1, f"historical control artifact identity {context}")

    totals: Counter[str] = Counter()
    by_context: dict[str, Counter[str]] = defaultdict(Counter)
    for (context, order, index), by_cell in sorted(control_rows.items()):
        require_equal(set(by_cell), {"C2", "C3", "C4"}, f"historical cell coverage {context}/{order}/{index}")
        rows = [by_cell[cell] for cell in ("C2", "C3", "C4")]
        schedule = {(row["seed"], row["physical_seat"], row["actual_order"], row["pair_index"]) for row in rows}
        require_equal(len(schedule), 1, f"historical cross-acquisition schedule {context}/{order}/{index}")
        outcome = {(row["win"], row["draw"]) for row in rows}
        errors = {(row["hero_policy_errors"], row["opponent_policy_errors"]) for row in rows}
        decisions = {row["decisions"] for row in rows}
        outcome_errors = {
            (row["win"], row["draw"], row["hero_policy_errors"], row["opponent_policy_errors"])
            for row in rows
        }
        available_record = {
            (
                row["win"], row["draw"], row["hero_policy_errors"],
                row["opponent_policy_errors"], row["decisions"],
            )
            for row in rows
        }
        flags = {
            "outcome_disagreement_units": len(outcome) != 1,
            "error_disagreement_units": len(errors) != 1,
            "decision_count_disagreement_units": len(decisions) != 1,
            "outcome_or_error_disagreement_units": len(outcome_errors) != 1,
            "available_record_disagreement_units": len(available_record) != 1,
        }
        totals["units"] += 1
        by_context[context]["units"] += 1
        for name, flag in flags.items():
            totals[name] += int(flag)
            by_context[context][name] += int(flag)

    require_equal(totals["outcome_disagreement_units"], 210, "historical outcome mismatches")
    require_equal(totals["error_disagreement_units"], 0, "historical error mismatches")
    require_equal(totals["decision_count_disagreement_units"], 457, "historical decision-count mismatches")
    require_equal(totals["available_record_disagreement_units"], 458, "historical available-record mismatches")
    contexts: dict[str, Any] = {}
    for context in sorted(by_context):
        row = by_context[context]
        contexts[context] = {
            **dict(row),
            "outcome_disagreement_percent": 100.0 * row["outcome_disagreement_units"] / row["units"],
            "available_record_disagreement_percent": 100.0 * row["available_record_disagreement_units"] / row["units"],
        }
    return {
        "analysis_unit": "opponent x actual-order x seed-condition cluster containing three separately acquired C1 control executions",
        "units": 2_800,
        "strata": 14,
        "contexts": 7,
        "raw_acquisition_rows": source_rows,
        "control_executions_compared": 8_400,
        "candidate_executions_not_used_in_mismatch_count": 8_400,
        "projection_definitions": {
            "outcome": ["win", "draw"],
            "error": ["hero_policy_errors", "opponent_policy_errors"],
            "decision_count": ["decisions"],
            "available_record": ["win", "draw", "hero_policy_errors", "opponent_policy_errors", "decisions"],
        },
        **dict(totals),
        "outcome_disagreement_percent": 100.0 * totals["outcome_disagreement_units"] / totals["units"],
        "available_record_disagreement_percent": 100.0 * totals["available_record_disagreement_units"] / totals["units"],
        "by_context": contexts,
        "order_checks": {"orders": list(ORDERS), "units_per_context_order": 200, "second_order_seed_offset": ORDER_OFFSET},
    }


def trace_file_map(
    payload: dict[str, Any], *, path: str, base_seed: int, tasks_per_order: int,
    variants: Mapping[str, tuple[int, str]], trace_mode: str,
) -> dict[str, dict[str, dict[str, Any]]]:
    validate_exact_keys(payload, TRACE_TOP_FIELDS, f"{path} top level")
    require_equal(payload["protocol_commit"], PROTOCOL_COMMIT, f"{path} protocol commit")
    require_equal(payload["protocol_id"], PROTOCOL_ID, f"{path} protocol id")
    require_equal(payload["base_seed"], base_seed, f"{path} base seed")
    require_equal(payload["order_seed_offset"], ORDER_OFFSET, f"{path} order offset")
    require_equal(payload["seeds_per_order"], tasks_per_order, f"{path} seeds per order")
    require_equal(payload["tasks"], 2 * tasks_per_order, f"{path} tasks")
    require_equal(payload["max_decisions"], 2_000, f"{path} decision cap")
    require_equal(payload["trace_mode"], trace_mode, f"{path} trace mode")
    require_equal(set(payload["runs"]), set(variants), f"{path} execution variants")
    runs: dict[str, dict[str, dict[str, Any]]] = {}
    natural_task_ids = [
        f"{order}-{index:03d}"
        for order in ORDERS
        for index in range(tasks_per_order)
    ]
    for variant, (worker_count, direction) in variants.items():
        rows = payload["runs"][variant]
        require(isinstance(rows, list), f"{path} {variant}: run rows required")
        require_equal(len(rows), 2 * tasks_per_order, f"{path} {variant} execution count")
        mapped: dict[str, dict[str, Any]] = {}
        for position, row in enumerate(rows):
            require(isinstance(row, dict), f"{path} {variant} row {position}: object required")
            validate_exact_keys(row, PROSPECTIVE_ROW_FIELDS, f"{path} {variant} row {position}")
            task_id = row["task_id"]
            require(task_id in natural_task_ids, f"{path} {variant}: unexpected task {task_id}")
            require(task_id not in mapped, f"{path} {variant}: duplicate task {task_id}")
            order, index_text = task_id.split("-")
            index = int(index_text)
            natural_position = (0 if order == "first" else tasks_per_order) + index
            expected_position = natural_position if direction == "forward" else 2 * tasks_per_order - 1 - natural_position
            require_equal(row["actual_order"], order, f"{path} {variant} order {task_id}")
            require_equal(row["scheduled_seed"], expected_seed(base_seed, order, index), f"{path} {variant} scheduled seed {task_id}")
            require_equal(row["requested_seed"], row["scheduled_seed"], f"{path} {variant} requested seed {task_id}")
            require_equal(row["engine_seed_uint32"], row["scheduled_seed"], f"{path} {variant} engine seed {task_id}")
            require_equal(row["seed"], row["scheduled_seed"], f"{path} {variant} alias seed {task_id}")
            require_equal(row["physical_seat"], index % 2, f"{path} {variant} seat {task_id}")
            require_equal(row["pair_index"], -1, f"{path} {variant} pair-index sentinel {task_id}")
            require_equal(row["execution_variant"], variant, f"{path} execution variant {task_id}")
            require_equal(row["worker_count"], worker_count, f"{path} worker count {task_id}")
            require_equal(row["schedule_direction"], direction, f"{path} direction {task_id}")
            require_equal(row["enqueue_position"], expected_position, f"{path} enqueue position {task_id}")
            require_equal(row["process_start_method"], "spawn", f"{path} start method {task_id}")
            require_equal(row["protocol_commit"], PROTOCOL_COMMIT, f"{path} row protocol commit {task_id}")
            require_equal(row["protocol_id"], PROTOCOL_ID, f"{path} row protocol id {task_id}")
            require_equal(row["trace_mode"], trace_mode, f"{path} row trace mode {task_id}")
            require_equal(row["trace_sha256"], row["public_trace_sha256"], f"{path} trace aliases {task_id}")
            require(is_sha256(row["trace_sha256"]), f"{path} {variant}: invalid trace digest {task_id}")
            require_int(row["trace_bytes"], f"{path} trace bytes {task_id}", minimum=1)
            require_int(row["decisions"], f"{path} decisions {task_id}", minimum=0)
            win = require_binary(row["win"], f"{path} win {task_id}")
            draw = require_binary(row["draw"], f"{path} draw {task_id}")
            require(win + draw <= 1, f"{path}: simultaneous win/draw {task_id}")
            require_int(row["hero_policy_errors"], f"{path} hero errors {task_id}", minimum=0)
            require_int(row["opponent_policy_errors"], f"{path} opponent errors {task_id}", minimum=0)
            elapsed = float(row["elapsed_wall_seconds"])
            require(math.isfinite(elapsed) and elapsed >= 0.0, f"{path} invalid elapsed time {task_id}")
            mapped[task_id] = row
        require_equal(set(mapped), set(natural_task_ids), f"{path} {variant} task coverage")
        runs[variant] = mapped

    for task_id in natural_task_ids:
        schedule_signatures = {
            (
                row["actual_order"], row["scheduled_seed"], row["engine_seed_uint32"],
                row["physical_seat"], json.dumps(row["hero_env"], sort_keys=True),
                json.dumps(row["opponent_env"], sort_keys=True), row["max_decisions"],
                row["schedule_fingerprint_sha256"], row["run_fingerprint_sha256"],
            )
            for row in (runs[name][task_id] for name in variants)
        }
        require_equal(len(schedule_signatures), 1, f"{path} cross-profile schedule {task_id}")

    if trace_mode == "full":
        require_equal(payload["trace_payload_files_written"], True, f"{path} trace payload marker")
        require_equal(set(payload["trace_files"]), set(variants), f"{path} trace inventory variants")
        for variant in variants:
            inventory = payload["trace_files"][variant]
            require_equal(set(inventory), set(natural_task_ids), f"{path} trace inventory {variant}")
            for task_id, digest in inventory.items():
                require_equal(digest, runs[variant][task_id]["trace_sha256"], f"{path} trace inventory digest {variant}/{task_id}")
    else:
        require_equal(payload["trace_payload_files_written"], False, f"{path} trace payload marker")
        require_equal(payload["trace_files"], {}, f"{path} retained trace inventory")
    return runs


def disagreement_flags(rows: Iterable[dict[str, Any]]) -> dict[str, bool]:
    values = list(rows)
    trace_digest = len({row["trace_sha256"] for row in values}) != 1
    trace_bytes = len({row["trace_bytes"] for row in values}) != 1
    outcome = len({(row["win"], row["draw"]) for row in values}) != 1
    errors = len({(row["hero_policy_errors"], row["opponent_policy_errors"]) for row in values}) != 1
    decisions = len({row["decisions"] for row in values}) != 1
    return {
        "trace_digest_disagreement": trace_digest,
        "trace_byte_count_disagreement": trace_bytes,
        "trace_projection_disagreement": trace_digest or trace_bytes,
        "outcome_disagreement": outcome,
        "error_disagreement": errors,
        "decision_count_disagreement": decisions,
        "any_required_disagreement": trace_digest or trace_bytes or outcome or errors or decisions,
    }


def verify_declared_mismatch_lists(
    payload: dict[str, Any], runs: Mapping[str, Mapping[str, dict[str, Any]]],
    *, baseline: str, path: str,
) -> None:
    expected_keys = set(runs) - {baseline}
    require_equal(set(payload["mismatches"]), expected_keys, f"{path} declared mismatch variants")
    for variant in expected_keys:
        observed = {
            task_id
            for task_id in runs[baseline]
            if runs[baseline][task_id]["trace_sha256"] != runs[variant][task_id]["trace_sha256"]
        }
        require_equal(observed, set(payload["mismatches"][variant]), f"{path} declared mismatches {variant}")


def audit_preflight(payloads: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    variants = {"single_a": (1, "forward"), "single_b": (1, "forward"), "workers_8": (8, "forward")}
    totals: Counter[str] = Counter()
    jobs: list[dict[str, Any]] = []
    seen_jobs: set[tuple[str, str]] = set()
    for arm in ("c1", "c2", "c3", "c4"):
        for context, base in PREFLIGHT_BASES.items():
            path = f"paper/data/pevl/preflight/raw/{arm}_{context}.json"
            payload = payloads[path]
            runs = trace_file_map(
                payload, path=path, base_seed=base, tasks_per_order=25,
                variants=variants, trace_mode="digest",
            )
            verify_declared_mismatch_lists(payload, runs, baseline="single_a", path=path)
            counts: Counter[str] = Counter()
            for task_id in sorted(runs["single_a"]):
                flags = disagreement_flags(runs[name][task_id] for name in variants)
                counts["trajectory_units"] += 1
                for field, flag in flags.items():
                    counts[f"{field}_units"] += int(flag)
            counts["executions"] = sum(len(run) for run in runs.values())
            totals.update(counts)
            seen_jobs.add((arm.upper(), context))
            jobs.append({"arm": arm.upper(), "context": context, **dict(counts)})
    require_equal(len(seen_jobs), 20, "preflight arm/context jobs")
    require_equal(totals["trajectory_units"], 1_000, "preflight trajectory units")
    require_equal(totals["executions"], 3_000, "preflight executions")
    for field in (
        "trace_digest_disagreement_units", "trace_byte_count_disagreement_units",
        "trace_projection_disagreement_units", "outcome_disagreement_units",
        "error_disagreement_units", "decision_count_disagreement_units",
        "any_required_disagreement_units",
    ):
        require_equal(totals[field], 0, f"preflight {field}")
    return {
        "analysis_unit": "arm x opponent x actual-order x seed-condition trajectory unit containing three executions",
        "jobs": 20,
        "arms": 4,
        "contexts": 5,
        "orders": 2,
        "units_per_job": 50,
        "profiles_per_unit": 3,
        **dict(totals),
        "mismatch_percentages": {
            field.removesuffix("_units") + "_percent": 100.0 * totals[field] / totals["trajectory_units"]
            for field in totals
            if field.endswith("disagreement_units")
        },
        "job_rows": sorted(jobs, key=lambda row: (row["arm"], row["context"])),
        "order_checks": {"orders": list(ORDERS), "units_per_job_order": 25, "second_order_seed_offset": ORDER_OFFSET},
    }


def binary_reweighting(values: Sequence[int], *, seed: int, draws: int = REWEIGHTING_DRAWS) -> dict[str, Any]:
    vector = np.asarray(values, dtype=np.float64)
    require(len(vector) > 0, "binary reweighting: empty vector")
    require(draws > 0, "binary reweighting: positive draw count required")
    require(np.all(np.isin(vector, [0.0, 1.0])), "binary reweighting: binary values required")
    rng = np.random.default_rng(seed)
    estimates = np.empty(draws, dtype=np.float64)
    cursor = 0
    while cursor < draws:
        batch = min(2_000, draws - cursor)
        indices = rng.integers(0, len(vector), size=(batch, len(vector)))
        estimates[cursor : cursor + batch] = vector[indices].mean(axis=1)
        cursor += batch
    return {
        "estimate": float(vector.mean()),
        "reweighting_quantiles_2_5_97_5": validate_quantile_pair(
            np.quantile(estimates, [0.025, 0.975]).tolist(), "binary reweighting"
        ),
        "reweighting_draws": draws,
        "reweighting_seed": seed,
    }


def stratified_binary_reweighting(
    strata: Mapping[str, Sequence[int]], *, seed: int, draws: int = REWEIGHTING_DRAWS,
) -> dict[str, Any]:
    require(strata, "stratified reweighting: strata required")
    require(draws > 0, "stratified reweighting: positive draw count required")
    vectors: dict[str, np.ndarray] = {}
    for key in sorted(strata):
        vector = np.asarray(strata[key], dtype=np.float64)
        require(len(vector) > 0, f"stratified reweighting: empty stratum {key}")
        require(np.all(np.isin(vector, [0.0, 1.0])), f"stratified reweighting: nonbinary stratum {key}")
        vectors[key] = vector
    rng = np.random.default_rng(seed)
    estimates = np.zeros(draws, dtype=np.float64)
    # One complete draw matrix is generated for each sorted stratum.  This
    # declares the RNG consumption order, so the seeded result is executable.
    for key in sorted(vectors):
        vector = vectors[key]
        indices = rng.integers(0, len(vector), size=(draws, len(vector)))
        estimates += vector[indices].mean(axis=1) / len(vectors)
    point = float(np.mean([vector.mean() for vector in vectors.values()]))
    return {
        "estimate": point,
        "reweighting_quantiles_2_5_97_5": validate_quantile_pair(
            np.quantile(estimates, [0.025, 0.975]).tolist(), "stratified reweighting"
        ),
        "reweighting_draws": draws,
        "reweighting_seed": seed,
        "strata": sorted(vectors),
        "stratum_weighting": "equal",
        "resampling_unit": "whole seed-condition cluster retaining all four execution profiles",
        "rng_order": "sorted stratum key, then all draws x all within-stratum positions",
    }


def audit_stress(payloads: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    variants = {
        "serial_forward": (1, "forward"),
        "serial_reverse": (1, "reverse"),
        "parallel_forward": (4, "forward"),
        "parallel_reverse": (4, "reverse"),
    }
    totals: Counter[str] = Counter()
    strata_vectors: dict[str, list[int]] = defaultdict(list)
    strata_counts: dict[str, Counter[str]] = defaultdict(Counter)
    pooled_vector: list[int] = []
    for context in sorted(STRESS_BASES):
        path = f"paper/data/pevl/stress/raw/{context}.json"
        payload = payloads[path]
        runs = trace_file_map(
            payload, path=path, base_seed=STRESS_BASES[context], tasks_per_order=50,
            variants=variants, trace_mode="full",
        )
        verify_declared_mismatch_lists(payload, runs, baseline="serial_forward", path=path)
        for task_id in sorted(runs["serial_forward"]):
            flags = disagreement_flags(runs[name][task_id] for name in variants)
            order = runs["serial_forward"][task_id]["actual_order"]
            stratum = f"{context}/{order}"
            totals["clusters"] += 1
            strata_counts[stratum]["clusters"] += 1
            trace_value = int(flags["trace_projection_disagreement"])
            pooled_vector.append(trace_value)
            strata_vectors[stratum].append(trace_value)
            for field, flag in flags.items():
                totals[f"{field}_clusters"] += int(flag)
                strata_counts[stratum][f"{field}_clusters"] += int(flag)
    totals["executions"] = totals["clusters"] * len(variants)
    require_equal(set(strata_vectors), {f"{context}/{order}" for context in STRESS_BASES for order in ORDERS}, "stress strata")
    for key, vector in strata_vectors.items():
        require_equal(len(vector), 50, f"stress stratum size {key}")
    require_equal(totals["clusters"], 200, "stress clusters")
    require_equal(totals["executions"], 800, "stress executions")
    require_equal(totals["trace_digest_disagreement_clusters"], 99, "stress trace digest disagreements")
    require_equal(totals["trace_projection_disagreement_clusters"], 99, "stress trace projection disagreements")
    require_equal(totals["trace_byte_count_disagreement_clusters"], 96, "stress trace byte-count disagreements")
    require_equal(totals["outcome_disagreement_clusters"], 47, "stress outcome disagreements")
    require_equal(totals["decision_count_disagreement_clusters"], 93, "stress decision-count disagreements")
    require_equal(totals["error_disagreement_clusters"], 0, "stress error disagreements")

    stratum_results: dict[str, Any] = {}
    for key in sorted(strata_vectors):
        counts = strata_counts[key]
        stratum_results[key] = {
            **dict(counts),
            "trace_disagreement": binary_reweighting(
                strata_vectors[key], seed=STRESS_REWEIGHTING_SEED
            ),
        }
    stratified = stratified_binary_reweighting(
        strata_vectors, seed=STRESS_REWEIGHTING_SEED
    )
    pooled = binary_reweighting(pooled_vector, seed=STRESS_REWEIGHTING_SEED)
    require(math.isclose(stratified["estimate"], 0.495, rel_tol=0.0, abs_tol=1e-15), "stress stratified estimate drift")
    require(np.allclose(stratified["reweighting_quantiles_2_5_97_5"], [0.46, 0.53], rtol=0.0, atol=1e-15), "stress stratified quantile drift")
    require(np.allclose(pooled["reweighting_quantiles_2_5_97_5"], [0.425, 0.565], rtol=0.0, atol=1e-15), "stress pooled quantile drift")
    return {
        "analysis_unit": "opponent x actual-order x seed-condition cluster containing four serial/parallel and forward/reverse executions",
        "clusters": 200,
        "executions": 800,
        "profiles_per_cluster": 4,
        **{key: value for key, value in totals.items() if key not in {"clusters", "executions"}},
        "disagreement_percentages": {
            key.removesuffix("_clusters") + "_percent": 100.0 * value / totals["clusters"]
            for key, value in totals.items()
            if key.endswith("_clusters")
        },
        "strata": stratum_results,
        "specified_pooled_whole_cluster_reweighting": {
            **pooled,
            "resampling_unit": "whole seed-condition cluster retaining all four execution profiles",
            "pooling": "all 200 fixed-battery clusters",
            "authority": f"frozen executable {PROTOCOL_COMMIT}:{FROZEN_ANALYZER_PATH} lines 374-376",
        },
        "alternative_stratified_whole_cluster_sensitivity": {
            **stratified,
            "role": "fixed-composition sensitivity calculation, distinct from the pooled procedure selected by the frozen executable",
        },
        "protocol_interpretation": {
            "finding_status": "PROSE_AMBIGUITY_RESOLVED_BY_FROZEN_EXECUTABLE",
            "prose_evidence": [
                "Protocol lines 115-116 define the seed-condition as the statistical/resampling cluster and say results are stratified by opponent and order.",
                "Protocol lines 165-168 specify 100,000 cluster draws over seed-condition units but do not say that the overall resampling occurs within strata; the factorial language explicitly does say within strata.",
            ],
            "executable_evidence": [
                "Frozen analyzer lines 350-353 compute four separate stratum resampling distributions.",
                "Frozen analyzer lines 374-376 compute the overall distribution by passing all 200 cluster indicators to one pooled resampling procedure.",
            ],
            "conclusion": "The specified overall result has pooled whole-cluster 2.5th and 97.5th reweighting quantiles [0.425, 0.565]. The within-stratum fixed-composition quantiles [0.46, 0.53] are a useful alternative sensitivity result, not a factual correction.",
            "recommended_wording": "Report pooled whole-cluster empirical reweighting quantiles for the 200-cluster fixed battery, report the four opponent-by-order quantiles separately, and do not label the pooled result stratified or a confidence interval.",
        },
        "order_checks": {"orders": list(ORDERS), "clusters_per_context_order": 50, "second_order_seed_offset": ORDER_OFFSET},
    }


def validate_factorial_file(
    payload: dict[str, Any], *, path: str, base_seed: int
) -> dict[tuple[str, int, str], dict[str, Any]]:
    validate_exact_keys(payload, FACTORIAL_TOP_FIELDS, f"{path} top level")
    require_equal(payload["actual_orders"], list(ORDERS), f"{path} actual orders")
    require_equal(payload["base_seed"], base_seed, f"{path} base seed")
    require_equal(payload["order_seed_offset"], ORDER_OFFSET, f"{path} order offset")
    require_equal(payload["pairs_per_order"], 200, f"{path} pairs per order")
    require_equal(payload["games"], 800, f"{path} games")
    require_equal(payload["protocol_commit"], PROTOCOL_COMMIT, f"{path} protocol commit")
    require_equal(payload["protocol_id"], PROTOCOL_ID, f"{path} protocol id")
    require_equal(payload["capture_trace_digest"], False, f"{path} trace capture flag")
    require_equal(payload["production_engine_preserved"], True, f"{path} production engine sentinel")
    require_equal(payload["production_engine_sha256_before"], payload["production_engine_sha256_after"], f"{path} production engine digest")
    rows = payload.get("rows")
    require(isinstance(rows, list), f"{path}: rows array required")
    require_equal(len(rows), 800, f"{path} row count")
    mapped: dict[tuple[str, int, str], dict[str, Any]] = {}
    for position, row in enumerate(rows):
        require(isinstance(row, dict), f"{path} row {position}: object required")
        validate_exact_keys(row, PROSPECTIVE_ROW_FIELDS, f"{path} row {position}")
        order = row["actual_order"]
        arm = row["arm"]
        require(order in ORDERS, f"{path} row {position}: invalid order")
        require(arm in {"candidate", "control"}, f"{path} row {position}: invalid arm")
        index = require_int(row["pair_index"], f"{path} row {position} pair index")
        require(0 <= index < 200, f"{path} row {position}: pair index out of range")
        key = (order, index, arm)
        require(key not in mapped, f"{path}: duplicate row {key}")
        require_equal(row["task_id"], f"{order}-{index:05d}-{arm}", f"{path} task id {key}")
        seed = expected_seed(base_seed, order, index)
        for field in ("scheduled_seed", "requested_seed", "engine_seed_uint32", "seed"):
            require_equal(row[field], seed, f"{path} {field} {key}")
        require_equal(row["physical_seat"], index % 2, f"{path} seat {key}")
        natural_unit = (0 if order == "first" else 200) + index
        expected_enqueue = 2 * natural_unit + (0 if arm == "candidate" else 1)
        require_equal(row["enqueue_position"], expected_enqueue, f"{path} enqueue position {key}")
        require_equal(row["worker_count"], 8, f"{path} worker count {key}")
        require_equal(row["process_start_method"], "spawn", f"{path} process start {key}")
        require_equal(row["execution_variant"], None, f"{path} execution variant {key}")
        require_equal(row["schedule_direction"], None, f"{path} schedule direction {key}")
        require_equal(row["protocol_commit"], PROTOCOL_COMMIT, f"{path} row protocol commit {key}")
        require_equal(row["protocol_id"], PROTOCOL_ID, f"{path} row protocol id {key}")
        require_equal(row["trace_mode"], "none", f"{path} trace mode {key}")
        require_equal(row["trace_sha256"], None, f"{path} trace digest {key}")
        require_equal(row["public_trace_sha256"], None, f"{path} public trace digest {key}")
        require_equal(row["trace_bytes"], 0, f"{path} trace bytes {key}")
        win = require_binary(row["win"], f"{path} win {key}")
        draw = require_binary(row["draw"], f"{path} draw {key}")
        require(win + draw <= 1, f"{path}: simultaneous win/draw {key}")
        require_int(row["decisions"], f"{path} decisions {key}", minimum=0)
        require_int(row["hero_policy_errors"], f"{path} hero errors {key}", minimum=0)
        require_int(row["opponent_policy_errors"], f"{path} opponent errors {key}", minimum=0)
        mapped[key] = row
    require_equal(len(mapped), 800, f"{path} unique row count")
    return mapped


def factorial_reweighting(arrays: Mapping[str, np.ndarray]) -> dict[str, Any]:
    require_equal(len(arrays), 10, "factorial reweighting strata")
    names = ("primary_c4_minus_c1", "representation_main", "training_main", "interaction")
    samples = {name: np.empty(REWEIGHTING_DRAWS, dtype=np.float64) for name in names}
    rng = np.random.default_rng(FACTORIAL_REWEIGHTING_SEED)
    cursor = 0
    while cursor < REWEIGHTING_DRAWS:
        batch = min(1_000, REWEIGHTING_DRAWS - cursor)
        totals = {name: np.zeros(batch, dtype=np.float64) for name in names}
        for key in sorted(arrays):
            matrix = arrays[key]
            require_equal(matrix.shape, (200, 4), f"factorial reweighting shape {key}")
            require(np.all(np.isin(matrix, [0.0, 1.0])), f"factorial reweighting nonbinary {key}")
            indices = rng.integers(0, 200, size=(batch, 200))
            means = matrix[indices].mean(axis=1)
            c1, c2, c3, c4 = (means[:, index] for index in range(4))
            totals["primary_c4_minus_c1"] += c4 - c1
            totals["representation_main"] += 0.5 * ((c2 - c1) + (c4 - c3))
            totals["training_main"] += 0.5 * ((c3 - c1) + (c4 - c2))
            totals["interaction"] += c4 - c3 - c2 + c1
        for name in names:
            samples[name][cursor : cursor + batch] = totals[name] / len(arrays)
        cursor += batch
    return {
        name: {
            "reweighting_quantiles_2_5_97_5": validate_quantile_pair(
                np.quantile(samples[name], [0.025, 0.975]).tolist(), f"factorial {name} reweighting"
            ),
            "reweighting_draws": REWEIGHTING_DRAWS,
            "reweighting_seed": FACTORIAL_REWEIGHTING_SEED,
            "resampling_unit": "whole paired cell-outcome vector within each opponent x actual-order stratum",
            "stratum_weighting": "equal",
            "rng_order": "1000-draw batches, then sorted stratum key",
        }
        for name in names
    }


def exact_two_sided_mcnemar(first_only: int, second_only: int) -> float:
    discordant = first_only + second_only
    if discordant == 0:
        return 1.0
    lower = min(first_only, second_only)
    tail_numerator = sum(math.comb(discordant, index) for index in range(lower + 1))
    return min(1.0, 2.0 * (tail_numerator / (2**discordant)))


def audit_factorial(payloads: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    acquisitions: dict[tuple[str, str], dict[tuple[str, int, str], dict[str, Any]]] = {}
    raw_rows = 0
    for cell in ("c2", "c3", "c4"):
        for context, base in FACTORIAL_BASES.items():
            path = f"paper/data/pevl/factorial/raw/{cell}_{context}.json"
            mapped = validate_factorial_file(payloads[path], path=path, base_seed=base)
            acquisitions[(cell, context)] = mapped
            raw_rows += len(mapped)
    require_equal(raw_rows, 12_000, "factorial raw execution rows")

    arrays: dict[str, np.ndarray] = {}
    all_vectors: list[list[int]] = []
    control_mismatches: Counter[str] = Counter()
    policy_error_executions = 0
    for context in sorted(FACTORIAL_BASES):
        for order in ORDERS:
            matrix = np.empty((200, 4), dtype=np.float64)
            for index in range(200):
                controls = [acquisitions[(cell, context)][(order, index, "control")] for cell in ("c2", "c3", "c4")]
                candidates = [acquisitions[(cell, context)][(order, index, "candidate")] for cell in ("c2", "c3", "c4")]
                schedule = {
                    (row["scheduled_seed"], row["engine_seed_uint32"], row["actual_order"], row["physical_seat"], row["pair_index"])
                    for row in [*controls, *candidates]
                }
                require_equal(len(schedule), 1, f"factorial cross-file schedule {context}/{order}/{index}")
                projection_sets = {
                    "outcome_disagreement_units": {(row["win"], row["draw"]) for row in controls},
                    "error_disagreement_units": {(row["hero_policy_errors"], row["opponent_policy_errors"]) for row in controls},
                    "decision_count_disagreement_units": {row["decisions"] for row in controls},
                    "available_record_disagreement_units": {
                        (row["win"], row["draw"], row["hero_policy_errors"], row["opponent_policy_errors"], row["decisions"])
                        for row in controls
                    },
                }
                for field, values in projection_sets.items():
                    control_mismatches[field] += int(len(values) != 1)
                policy_error_executions += sum(
                    int(row["hero_policy_errors"] != 0 or row["opponent_policy_errors"] != 0)
                    for row in [*controls, *candidates]
                )
                vector = [controls[0]["win"], candidates[0]["win"], candidates[1]["win"], candidates[2]["win"]]
                matrix[index] = vector
                all_vectors.append(vector)
            arrays[f"{context}/{order}"] = matrix
    for field, value in control_mismatches.items():
        require_equal(value, 0, f"factorial repeated-control {field}")
    require_equal(policy_error_executions, 0, "factorial policy-error executions")

    all_matrix = np.asarray(all_vectors, dtype=np.float64)
    require_equal(all_matrix.shape, (2_000, 4), "factorial analysis matrix")
    c1, c2, c3, c4 = (all_matrix[:, index] for index in range(4))
    counts = {f"C{index + 1}": int(all_matrix[:, index].sum()) for index in range(4)}
    rates = {cell: count / 2_000 for cell, count in counts.items()}
    estimates = {
        "primary_c4_minus_c1": float(np.mean(c4 - c1)),
        "representation_main": float(np.mean(0.5 * ((c2 - c1) + (c4 - c3)))),
        "training_main": float(np.mean(0.5 * ((c3 - c1) + (c4 - c2)))),
        "interaction": float(np.mean(c4 - c3 - c2 + c1)),
    }
    simple = {
        "c2_minus_c1": float(np.mean(c2 - c1)),
        "c3_minus_c1": float(np.mean(c3 - c1)),
        "c4_minus_c1": float(np.mean(c4 - c1)),
        "c4_minus_c2": float(np.mean(c4 - c2)),
        "c4_minus_c3": float(np.mean(c4 - c3)),
    }
    reweighting = factorial_reweighting(arrays)
    contrasts = {
        name: {"estimate": estimate, "estimate_percentage_points": 100.0 * estimate, **reweighting[name]}
        for name, estimate in estimates.items()
    }
    c4_only = int(np.sum((c4 == 1) & (c1 == 0)))
    c1_only = int(np.sum((c4 == 0) & (c1 == 1)))
    mcnemar = {
        "c4_only_wins": c4_only,
        "c1_only_wins": c1_only,
        "discordant_units": c4_only + c1_only,
        "exact_two_sided_p": exact_two_sided_mcnemar(c4_only, c1_only),
    }
    require_equal(counts, {"C1": 1236, "C2": 1242, "C3": 1215, "C4": 1247}, "factorial win counts")
    require_equal(rates, {"C1": 0.618, "C2": 0.621, "C3": 0.6075, "C4": 0.6235}, "factorial win rates")
    require_equal(estimates, {
        "primary_c4_minus_c1": 0.0055,
        "representation_main": 0.0095,
        "training_main": -0.004,
        "interaction": 0.013,
    }, "factorial contrasts")
    require_equal(c4_only, 358, "factorial C4-only wins")
    require_equal(c1_only, 347, "factorial C1-only wins")
    return {
        "analysis_unit": "opponent x actual-order x seed-condition paired unit with one aligned C1/C2/C3/C4 outcome vector",
        "units_per_cell": 2_000,
        "conceptual_cell_observations": 8_000,
        "raw_execution_rows": raw_rows,
        "candidate_executions": 6_000,
        "repeated_control_executions": 6_000,
        "repeated_control_units": 2_000,
        "strata": 10,
        "units_per_stratum": 200,
        "policy_error_executions": policy_error_executions,
        "repeated_control_mismatches": dict(control_mismatches),
        "cell_win_counts": counts,
        "cell_win_rates": rates,
        "cell_win_percentages": {cell: 100.0 * rate for cell, rate in rates.items()},
        "contrasts": contrasts,
        "simple_effects": simple,
        "mcnemar": mcnemar,
        "order_checks": {"orders": list(ORDERS), "units_per_context_order": 200, "second_order_seed_offset": ORDER_OFFSET},
    }


def parse_macros(path: Path) -> dict[str, str]:
    pattern = re.compile(r"\\newcommand\{\\([^}]+)\}\{([^}]*)\}")
    return dict(pattern.findall(path.read_text(encoding="utf-8")))


def close(observed: float, expected: float, *, tolerance: float = 1e-12) -> bool:
    return math.isclose(float(observed), float(expected), rel_tol=0.0, abs_tol=tolerance)


def audit_displayed_values(
    historical: Mapping[str, Any], preflight: Mapping[str, Any],
    stress: Mapping[str, Any], factorial: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    conflicts: list[dict[str, Any]] = []
    macros_path = FINAL / "results_macros.tex"
    macros = parse_macros(macros_path)
    count_expectations = {
        "HistoricalUnits": "2,800",
        "HistoricalOutcomeMismatch": str(historical["outcome_disagreement_units"]),
        "HistoricalAvailableRecordMismatch": str(historical["available_record_disagreement_units"]),
        "PreflightJobs": "20",
        "PreflightUnits": "1,000",
        "PreflightExecutions": "3,000",
        "PreflightMismatches": "0",
        "StressClusters": "200",
        "StressExecutions": "800",
        "StressTraceMismatch": str(stress["trace_projection_disagreement_clusters"]),
        "StressOutcomeMismatch": str(stress["outcome_disagreement_clusters"]),
        "StressDecisionMismatch": str(stress["decision_count_disagreement_clusters"]),
        "StressErrorMismatch": str(stress["error_disagreement_clusters"]),
        "ReweightingDraws": "100,000",
        "FactorialUnits": "2,000",
        "FactorialGames": "12,000",
        "FactorialControlMismatch": "0",
    }
    macro_checks = {
        name: {"observed": macros.get(name), "expected": expected, "status": "MATCH" if macros.get(name) == expected else "CONFLICT"}
        for name, expected in count_expectations.items()
    }
    for name, row in macro_checks.items():
        if row["status"] == "CONFLICT":
            conflicts.append({
                "id": f"macro_{name}", "severity": "BLOCKING_NUMERICAL_CONFLICT",
                "authoritative": row["expected"], "displayed": row["observed"],
                "location": str(macros_path.relative_to(ROOT)),
            })

    stress_specified = stress["specified_pooled_whole_cluster_reweighting"]
    stress_stratified = stress["alternative_stratified_whole_cluster_sensitivity"]
    displayed_stress = {
        "estimate_percent": float(macros["StressTracePct"]),
        "quantile_2_5_percent": float(macros["StressTraceLowPct"]),
        "quantile_97_5_percent": float(macros["StressTraceHighPct"]),
    }
    specified_stress = {
        "estimate_percent": 100.0 * stress_specified["estimate"],
        "quantile_2_5_percent": 100.0 * stress_specified["reweighting_quantiles_2_5_97_5"][0],
        "quantile_97_5_percent": 100.0 * stress_specified["reweighting_quantiles_2_5_97_5"][1],
    }
    stratified_stress = {
        "estimate_percent": 100.0 * stress_stratified["estimate"],
        "quantile_2_5_percent": 100.0 * stress_stratified["reweighting_quantiles_2_5_97_5"][0],
        "quantile_97_5_percent": 100.0 * stress_stratified["reweighting_quantiles_2_5_97_5"][1],
    }
    stress_quantiles_match_specified = all(close(displayed_stress[key], specified_stress[key]) for key in specified_stress)
    stress_quantiles_match_stratified = all(close(displayed_stress[key], stratified_stress[key]) for key in stratified_stress)
    if not stress_quantiles_match_specified:
        conflicts.append({
            "id": "stress_overall_reweighting_quantiles",
            "severity": "BLOCKING_NUMERICAL_CONFLICT",
            "authoritative_frozen_executable": specified_stress,
            "displayed": displayed_stress,
            "alternative_stratified_sensitivity": stratified_stress,
            "cause": "The displayed quantiles do not reproduce the prospectively frozen executable's pooled whole-cluster resampling procedure.",
            "locations": [
                "paper/final_protocol/results_macros.tex",
                "paper/final_protocol/main.tex",
                "paper/final_protocol/cover_letter.md",
                "paper/final_protocol/source_data/figure_4_timed_search.csv",
            ],
        })

    factor_macro_map = {
        "primary_c4_minus_c1": ("PrimaryEstimatePP", "PrimaryLowPP", "PrimaryHighPP"),
        "representation_main": ("RepresentationEstimatePP", "RepresentationLowPP", "RepresentationHighPP"),
        "training_main": ("TrainingEstimatePP", "TrainingLowPP", "TrainingHighPP"),
        "interaction": ("InteractionEstimatePP", "InteractionLowPP", "InteractionHighPP"),
    }
    factor_checks: dict[str, Any] = {}
    for name, macro_names in factor_macro_map.items():
        result = factorial["contrasts"][name]
        expected = [
            f"{result['estimate_percentage_points']:+.2f}",
            f"{100.0 * result['reweighting_quantiles_2_5_97_5'][0]:+.2f}",
            f"{100.0 * result['reweighting_quantiles_2_5_97_5'][1]:+.2f}",
        ]
        observed = [macros.get(macro) for macro in macro_names]
        factor_checks[name] = {"observed": observed, "expected": expected, "status": "MATCH" if observed == expected else "CONFLICT"}
        if observed != expected:
            conflicts.append({
                "id": f"factorial_display_{name}", "severity": "BLOCKING_NUMERICAL_CONFLICT",
                "authoritative": expected, "displayed": observed,
                "location": "paper/final_protocol/results_macros.tex",
            })
    figure_4_path = FINAL / "source_data/figure_4_timed_search.csv"
    with figure_4_path.open(encoding="utf-8", newline="") as handle:
        figure_4_rows = list(csv.DictReader(handle))
    require_equal(len(figure_4_rows), 5, "displayed stress figure row count")
    figure_4 = {
        row["stratum"]: {
            "clusters": int(row["clusters"]),
            "estimate": float(row["estimate"]),
            "quantile_2_5": float(row["quantile_2_5"]),
            "quantile_97_5": float(row["quantile_97_5"]),
        }
        for row in figure_4_rows
    }
    expected_figure_4 = {
        "Overall": {
            "clusters": 200,
            "estimate": stress_specified["estimate"],
            "quantile_2_5": stress_specified["reweighting_quantiles_2_5_97_5"][0],
            "quantile_97_5": stress_specified["reweighting_quantiles_2_5_97_5"][1],
        },
        "Timed-search A / order 1": {
            "clusters": 50,
            "estimate": stress["strata"]["starmie/first"]["trace_disagreement"]["estimate"],
            "quantile_2_5": stress["strata"]["starmie/first"]["trace_disagreement"]["reweighting_quantiles_2_5_97_5"][0],
            "quantile_97_5": stress["strata"]["starmie/first"]["trace_disagreement"]["reweighting_quantiles_2_5_97_5"][1],
        },
        "Timed-search A / order 2": {
            "clusters": 50,
            "estimate": stress["strata"]["starmie/second"]["trace_disagreement"]["estimate"],
            "quantile_2_5": stress["strata"]["starmie/second"]["trace_disagreement"]["reweighting_quantiles_2_5_97_5"][0],
            "quantile_97_5": stress["strata"]["starmie/second"]["trace_disagreement"]["reweighting_quantiles_2_5_97_5"][1],
        },
        "Timed-search B / order 1": {
            "clusters": 50,
            "estimate": stress["strata"]["dipplin/first"]["trace_disagreement"]["estimate"],
            "quantile_2_5": stress["strata"]["dipplin/first"]["trace_disagreement"]["reweighting_quantiles_2_5_97_5"][0],
            "quantile_97_5": stress["strata"]["dipplin/first"]["trace_disagreement"]["reweighting_quantiles_2_5_97_5"][1],
        },
        "Timed-search B / order 2": {
            "clusters": 50,
            "estimate": stress["strata"]["dipplin/second"]["trace_disagreement"]["estimate"],
            "quantile_2_5": stress["strata"]["dipplin/second"]["trace_disagreement"]["reweighting_quantiles_2_5_97_5"][0],
            "quantile_97_5": stress["strata"]["dipplin/second"]["trace_disagreement"]["reweighting_quantiles_2_5_97_5"][1],
        },
    }
    figure_4_checks: dict[str, Any] = {}
    for label, expected in expected_figure_4.items():
        observed = figure_4.get(label)
        matched = observed is not None and observed["clusters"] == expected["clusters"] and all(
            close(observed[key], expected[key]) for key in ("estimate", "quantile_2_5", "quantile_97_5")
        )
        figure_4_checks[label] = {"observed": observed, "expected": expected, "status": "MATCH" if matched else "CONFLICT"}

    figure_5_path = FINAL / "source_data/figure_5_factorial.csv"
    with figure_5_path.open(encoding="utf-8", newline="") as handle:
        figure_5_rows = list(csv.DictReader(handle))
    require_equal(len(figure_5_rows), 4, "displayed factorial figure row count")
    label_to_contrast = {
        "Total intervention": "primary_c4_minus_c1",
        "Representation contrast": "representation_main",
        "Training contrast": "training_main",
        "Interaction": "interaction",
    }
    figure_5_checks: dict[str, Any] = {}
    for row in figure_5_rows:
        name = label_to_contrast[row["contrast"]]
        result = factorial["contrasts"][name]
        observed = [
            float(row["estimate_pp"]),
            float(row["quantile_2_5_pp"]),
            float(row["quantile_97_5_pp"]),
        ]
        expected = [
            result["estimate_percentage_points"],
            100.0 * result["reweighting_quantiles_2_5_97_5"][0],
            100.0 * result["reweighting_quantiles_2_5_97_5"][1],
        ]
        matched = all(close(left, right) for left, right in zip(observed, expected))
        figure_5_checks[row["contrast"]] = {"observed": observed, "expected": expected, "status": "MATCH" if matched else "CONFLICT"}

    percentage_inventory = {
        "historical": {
            "outcome_disagreement_percent": historical["outcome_disagreement_percent"],
            "available_record_disagreement_percent": historical["available_record_disagreement_percent"],
        },
        "preflight": preflight["mismatch_percentages"],
        "stress": {
            **stress["disagreement_percentages"],
            "specified_pooled_quantiles_percent": [
                100.0 * value for value in stress_specified["reweighting_quantiles_2_5_97_5"]
            ],
            "alternative_fixed_composition_quantiles_percent": [
                100.0 * value for value in stress_stratified["reweighting_quantiles_2_5_97_5"]
            ],
            "strata": {
                key: {
                    "estimate_percent": 100.0 * value["trace_disagreement"]["estimate"],
                    "quantiles_percent": [
                        100.0 * endpoint
                        for endpoint in value["trace_disagreement"]["reweighting_quantiles_2_5_97_5"]
                    ],
                }
                for key, value in stress["strata"].items()
            },
        },
        "factorial": {
            "cell_win_percentages": factorial["cell_win_percentages"],
            "contrast_percentage_points": {
                name: {
                    "estimate": row["estimate_percentage_points"],
                    "reweighting_quantiles": [
                        100.0 * endpoint for endpoint in row["reweighting_quantiles_2_5_97_5"]
                    ],
                }
                for name, row in factorial["contrasts"].items()
            },
        },
    }
    return {
        "scope": "All central percentages, percentage-point quantities, and 2.5th/97.5th empirical reweighting quantiles displayed through results_macros.tex and the timed-search/factorial figure source CSVs.",
        "macro_count_checks": macro_checks,
        "stress_overall": {
            "displayed": displayed_stress,
            "specified_pooled": specified_stress,
            "alternative_stratified_sensitivity": stratified_stress,
            "matches_specified_pooled": stress_quantiles_match_specified,
            "matches_alternative_fixed_composition_sensitivity": stress_quantiles_match_stratified,
            "protocol_interpretation": stress["protocol_interpretation"],
        },
        "factorial_macro_checks": factor_checks,
        "mcnemar_recalculation": {
            "displayed_in_manuscript": False,
            "c4_only_wins": factorial["mcnemar"]["c4_only_wins"],
            "c1_only_wins": factorial["mcnemar"]["c1_only_wins"],
            "exact_two_sided_p": factorial["mcnemar"]["exact_two_sided_p"],
            "interpretation": "Numerically verified but not admitted for manuscript inference because its reference-distribution assumptions are not established.",
        },
        "figure_4_checks": figure_4_checks,
        "figure_5_checks": figure_5_checks,
        "percentage_inventory": percentage_inventory,
    }, conflicts


def build_report() -> dict[str, Any]:
    payloads, source_integrity = load_and_verify_sources()
    historical = audit_historical(payloads)
    preflight = audit_preflight(payloads)
    stress = audit_stress(payloads)
    factorial = audit_factorial(payloads)
    source_integrity["validation_checks"] = {
        "status": "PASS",
        "source_hashes_verified": source_integrity["source_count"],
        "exact_source_inventory": True,
        "exact_top_level_schemas_verified": 58,
        "exact_execution_row_schemas_verified": (
            historical["raw_acquisition_rows"]
            + preflight["executions"]
            + stress["executions"]
            + factorial["raw_execution_rows"]
        ),
        "analysis_units_explicit": True,
        "orders_and_seed_offsets_verified": True,
        "stratum_sizes_verified": True,
        "all_generated_quantile_pairs_finite_and_ordered": True,
    }
    display_audit, conflicts = audit_displayed_values(historical, preflight, stress, factorial)
    return {
        "status": "PASS" if not conflicts else "CONFLICT",
        "audit_id": "independent-raw-row-statistics-v1",
        "protocol_commit": PROTOCOL_COMMIT,
        "authoritative_source_hierarchy": [
            "Git-tracked retained raw acquisition row arrays under paper/data/*/raw",
            "prospectively frozen protocol and declared analysis units",
            "prospectively frozen executable for details left ambiguous by the protocol prose (interpretation only, never imported for row values)",
            "this independent executable reaggregation",
            "processed summaries, generated macros, figures, and manuscript prose (comparison targets only)",
        ],
        "independence_boundary": "No production analyzer, processed unit CSV, or processed summary supplies a numerator, denominator, outcome, mismatch flag, or reweighting input. Processed display artifacts are read only after raw-row calculation.",
        "source_integrity": source_integrity,
        "historical": historical,
        "preflight": preflight,
        "timed_search_stress": stress,
        "factorial": factorial,
        "displayed_value_audit": display_audit,
        "conflicts": conflicts,
        "limitations": [
            "The tracked stress rows contain trace digests and byte counts but not the restricted trace lines; earliest-divergence actor localization is outside this row-level numerical audit.",
            "Empirical reweighting quantiles condition on the fixed engineering battery and do not describe a sampled population of new opponents, seeds, hardware contexts, or training runs.",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path,
        default=FINAL / "source_data/independent_statistics_verification.json",
    )
    parser.add_argument("--check", action="store_true", help="Compare a recomputation with the existing output instead of writing")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report()
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.check:
        require(args.output.exists(), f"audit output missing: {args.output}")
        require_equal(args.output.read_text(encoding="utf-8"), serialized, "independent audit output")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(json.dumps({"status": report["status"], "conflicts": len(report["conflicts"]), "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

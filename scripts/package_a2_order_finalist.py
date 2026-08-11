#!/usr/bin/env python3
"""Build one deterministic actual-order router on the pinned A2 shield runtime."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import package_a2_finalist as a2


DEFAULT_OUTPUT = ROOT / "artifacts" / "elite_policy_candidates" / "temporal_order_second" / "package"
ROUTER_SOURCE = ROOT / "ptcg_ai" / "a2_order_router.py"
METRICS = (
    "count_accuracy",
    "single_index_top1",
    "single_index_top3",
    "single_semantic_nonforced_top1",
    "single_semantic_top3_eligible",
)
GATE_THRESHOLDS = {
    "broad_single_index_top1_delta": 0.005,
    "hard_single_index_top1_delta": 0.005,
    "broad_single_index_top3_delta_min": -0.001,
    "hard_single_index_top3_delta_min": -0.001,
    "broad_count_accuracy_delta_min": -0.001,
    "hard_count_accuracy_delta_min": -0.001,
}
GAMEPLAY_MIN_PAIRS_PER_ORDER = 1_000
CERTIFIED_DETERMINISTIC_ENGINE_SHA256 = "11662D6D96FEBB8ACA8F500BDFDE520AE0F1686AB3959EEF90AA16C958E68188"
PINNED_PRODUCTION_ENGINE_SHA256 = "EAE88634E26DC31D94150A4D8202FC9D32596B8C688EF67E14CB4088CD4D5771"
_SHA256_PATTERN = re.compile(r"[0-9A-Fa-f]{64}\Z")


def _main_source() -> str:
    return '''"""Actual-order temporal specialist on authentic A2 shield runtime."""

import os
os.environ["PTCG_TEMP"] = "0"
os.environ["PTCG_SEARCH"] = "0"
os.environ["PTCG_TACTICAL_SHIELD"] = "1"

from ptcg_ai.a2_order_router import ActualOrderAgent

_AGENT = ActualOrderAgent()

def agent(obs_dict: dict) -> list[int]:
    return _AGENT(obs_dict)
'''


def _load_report(path: Path) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise a2.PackageError(f"could not read held-out gate report {path}: {exc}") from exc
    if report.get("evaluation_scope") != "stateless_npz_ranker_only; runtime overrides and search are excluded":
        raise a2.PackageError(f"unexpected held-out report scope: {path}")
    return report


def _metric_values(report: Mapping[str, Any], model: str) -> dict[str, float]:
    try:
        rates = report["results"][model]["overall"]["rates"]
        return {name: float(rates[name]["value"]) for name in METRICS}
    except (KeyError, TypeError, ValueError) as exc:
        raise a2.PackageError(f"held-out report is missing {model} metrics") from exc


def heldout_gate(
    broad_path: Path,
    hard_path: Path,
    first_model_sha256: str,
    second_model_sha256: str,
) -> dict[str, Any]:
    scopes = {}
    for name, path in (("broad_second", broad_path), ("hard_second", hard_path)):
        report = _load_report(path)
        models = report.get("models", {})
        observed_first = str(models.get("temporal_full", {}).get("sha256", "")).upper()
        observed_second = str(models.get("second_specialist", {}).get("sha256", "")).upper()
        if observed_first != first_model_sha256 or observed_second != second_model_sha256:
            raise a2.PackageError(
                f"held-out {name} model identity mismatch: {observed_first}, {observed_second}"
            )
        baseline = _metric_values(report, "temporal_full")
        specialist = _metric_values(report, "second_specialist")
        scopes[name] = {
            "path": str(path.resolve()),
            "sha256": a2.sha256_file(path),
            "rows": int(report["rows_considered"]),
            "baseline": baseline,
            "specialist": specialist,
            "delta": {metric: specialist[metric] - baseline[metric] for metric in METRICS},
        }
    broad = scopes["broad_second"]["delta"]
    hard = scopes["hard_second"]["delta"]
    checks = {
        "distinct_second_model": second_model_sha256 != first_model_sha256,
        "broad_single_index_top1_material": broad["single_index_top1"] >= GATE_THRESHOLDS["broad_single_index_top1_delta"],
        "hard_single_index_top1_material": hard["single_index_top1"] >= GATE_THRESHOLDS["hard_single_index_top1_delta"],
        "broad_single_index_top3_retained": broad["single_index_top3"] >= GATE_THRESHOLDS["broad_single_index_top3_delta_min"],
        "hard_single_index_top3_retained": hard["single_index_top3"] >= GATE_THRESHOLDS["hard_single_index_top3_delta_min"],
        "broad_count_retained": broad["count_accuracy"] >= GATE_THRESHOLDS["broad_count_accuracy_delta_min"],
        "hard_count_retained": hard["count_accuracy"] >= GATE_THRESHOLDS["hard_count_accuracy_delta_min"],
    }
    return {
        "passed": all(checks.values()),
        "diagnostic_only": True,
        "gameplay_eligible": False,
        "thresholds": dict(GATE_THRESHOLDS),
        "checks": checks,
        "scopes": scopes,
    }


def _load_gameplay_report(path: Path) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise a2.PackageError(f"could not read gameplay evidence {path}: {exc}") from exc
    if not isinstance(report, dict):
        raise a2.PackageError(f"gameplay evidence must be a JSON object: {path}")
    return report


def _normalized_sha256(value: Any) -> str | None:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        return None
    return value.upper()


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    converted = float(value)
    return converted if math.isfinite(converted) else None


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _summary_view(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    interval = value.get("paired_95_ci")
    interval_values = (
        [_finite_number(item) for item in interval]
        if isinstance(interval, list) and len(interval) == 2
        else [None, None]
    )
    return {
        "pairs": _nonnegative_int(value.get("pairs")),
        "paired_difference": _finite_number(value.get("paired_difference")),
        "paired_95_ci": interval_values,
        "discordant_candidate_wins": _nonnegative_int(value.get("discordant_candidate_wins")),
        "discordant_control_wins": _nonnegative_int(value.get("discordant_control_wins")),
        "candidate_policy_errors": _nonnegative_int(value.get("candidate_policy_errors")),
        "control_policy_errors": _nonnegative_int(value.get("control_policy_errors")),
        "opponent_policy_errors": _nonnegative_int(value.get("opponent_policy_errors")),
    }


def gameplay_gate(path: Path, candidate_tree_sha256: str) -> dict[str, Any]:
    """Validate deterministic paired gameplay evidence for the staged router.

    The actual-first policy is required to be outcome-identical to authentic
    A2.  Promotion therefore rests entirely on a positive actual-second effect
    whose two-sided paired 95% interval also keeps the overall effect above 0.
    """

    report = _load_gameplay_report(path)
    orders_value = report.get("orders")
    orders = orders_value if isinstance(orders_value, Mapping) else {}
    first = _summary_view(orders.get("first"))
    second = _summary_view(orders.get("second"))
    overall = _summary_view(report.get("overall"))
    summaries = [summary for summary in (first, second, overall) if summary is not None]

    production_before = _normalized_sha256(report.get("production_engine_sha256_before"))
    production_after = _normalized_sha256(report.get("production_engine_sha256_after"))
    rng_value = report.get("rng_provenance")
    rng = rng_value if isinstance(rng_value, Mapping) else {}
    pinned_a2 = a2.FROZEN_SOURCE_TREE_SHA256.upper()
    expected_candidate = candidate_tree_sha256.upper()
    pairs_per_order = _nonnegative_int(report.get("pairs_per_order"))
    games = _nonnegative_int(report.get("games"))

    errors_complete_and_zero = (
        len(summaries) == 3
        and all(
            summary[name] == 0
            for summary in summaries
            for name in (
                "candidate_policy_errors",
                "control_policy_errors",
                "opponent_policy_errors",
            )
        )
    )
    checks = {
        "candidate_matches_fresh_stage": _normalized_sha256(report.get("candidate_sha256")) == expected_candidate,
        "control_is_pinned_authentic_a2": _normalized_sha256(report.get("control_sha256")) == pinned_a2,
        "opponent_is_pinned_authentic_a2": _normalized_sha256(report.get("opponent_sha256")) == pinned_a2,
        "certified_deterministic_engine": (
            _normalized_sha256(report.get("engine_sha256"))
            == CERTIFIED_DETERMINISTIC_ENGINE_SHA256
        ),
        "deterministic_paired_rng": (
            rng.get("engine") == "local_seeded_mt19937"
            and rng.get("deviceRand") is False
            and rng.get("native_gameplay_random_device") is False
            and rng.get("same_seed_within_candidate_control_pair") is True
            and rng.get("same_actual_order_and_physical_seat_within_pair") is True
        ),
        "production_engine_preserved": (
            report.get("production_engine_preserved") is True
            and production_before == PINNED_PRODUCTION_ENGINE_SHA256
            and production_after == PINNED_PRODUCTION_ENGINE_SHA256
        ),
        "both_actual_orders_present": first is not None and second is not None,
        "minimum_pairs_per_order": (
            pairs_per_order is not None
            and pairs_per_order >= GAMEPLAY_MIN_PAIRS_PER_ORDER
            and first is not None
            and second is not None
            and first["pairs"] is not None
            and second["pairs"] is not None
            and first["pairs"] >= GAMEPLAY_MIN_PAIRS_PER_ORDER
            and second["pairs"] >= GAMEPLAY_MIN_PAIRS_PER_ORDER
        ),
        "complete_game_count": (
            games is not None
            and pairs_per_order is not None
            and games == 4 * pairs_per_order
        ),
        "zero_all_policy_errors": errors_complete_and_zero,
        "first_order_exact_parity": (
            first is not None
            and first["paired_difference"] == 0.0
            and first["discordant_candidate_wins"] == 0
            and first["discordant_control_wins"] == 0
        ),
        "second_order_two_sided_95_lower_positive": (
            second is not None
            and second["paired_95_ci"][0] is not None
            and second["paired_95_ci"][0] > 0.0
        ),
        "overall_two_sided_95_lower_positive": (
            overall is not None
            and overall["paired_95_ci"][0] is not None
            and overall["paired_95_ci"][0] > 0.0
        ),
    }
    return {
        "provided": True,
        "passed": all(checks.values()),
        "gameplay_eligible": all(checks.values()),
        "path": str(path.resolve()),
        "sha256": a2.sha256_file(path),
        "minimum_pairs_per_order": GAMEPLAY_MIN_PAIRS_PER_ORDER,
        "checks": checks,
        "identities": {
            "candidate_tree_sha256": _normalized_sha256(report.get("candidate_sha256")),
            "fresh_stage_tree_sha256": expected_candidate,
            "control_tree_sha256": _normalized_sha256(report.get("control_sha256")),
            "opponent_tree_sha256": _normalized_sha256(report.get("opponent_sha256")),
            "pinned_authentic_a2_tree_sha256": pinned_a2,
            "engine_sha256": _normalized_sha256(report.get("engine_sha256")),
            "certified_deterministic_engine_sha256": CERTIFIED_DETERMINISTIC_ENGINE_SHA256,
            "production_engine_sha256_before": production_before,
            "production_engine_sha256_after": production_after,
            "pinned_production_engine_sha256": PINNED_PRODUCTION_ENGINE_SHA256,
        },
        "pairs_per_order": pairs_per_order,
        "games": games,
        "rng_provenance": dict(rng),
        "orders": {"first": first, "second": second},
        "overall": overall,
    }


def stage_order_package(
    source_archive: Path,
    first_model: Path,
    second_model: Path,
    destination: Path,
) -> dict[str, Any]:
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise a2.PackageError(f"order package stage must be empty: {destination}")
    a2.safe_extract(source_archive, destination)
    source = a2.verify_source_runtime(destination)
    first = a2.validate_model(first_model)
    second = a2.validate_model(second_model)
    if first["model_schema_version"] != 3 or second["model_schema_version"] != 3:
        raise a2.PackageError("temporal order policies must both use schema 3")
    shutil.copyfile(first_model, destination / "policy_first.npz")
    shutil.copyfile(second_model, destination / "policy_second.npz")
    shutil.copyfile(ROUTER_SOURCE, destination / "ptcg_ai" / "a2_order_router.py")
    (destination / "main.py").write_text(_main_source(), encoding="utf-8", newline="\n")
    packaged_first = a2.validate_model(destination / "policy_first.npz")
    packaged_second = a2.validate_model(destination / "policy_second.npz")
    if packaged_first["sha256"] != first["sha256"] or packaged_second["sha256"] != second["sha256"]:
        raise a2.PackageError("order policy copy hash mismatch")
    if a2.sha256_file(destination / a2.MODEL_MEMBER) != a2.FROZEN_SOURCE_MODEL_SHA256:
        raise a2.PackageError("authentic A2 fallback model changed")
    if a2.sha256_file(destination / "deck.csv") != a2.FROZEN_RAW_DECK_SHA256:
        raise a2.PackageError("authentic A2 deck changed")
    file_hashes = a2.package_file_hashes(destination)
    runtime_tree, runtime_files = a2.runtime_source_tree_sha256(destination)
    return {
        "source": source,
        "first_model": first,
        "second_model": second,
        "package_file_sha256": file_hashes,
        "package_tree_sha256": a2.package_tree_sha256(destination),
        "runtime_source_tree_sha256": runtime_tree,
        "runtime_source_files": runtime_files,
        "entrypoint_sha256": a2.sha256_file(destination / "main.py"),
        "router_sha256": a2.sha256_file(destination / "ptcg_ai" / "a2_order_router.py"),
    }


def sterile_smoke(archive: Path, first_sha: str, second_sha: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="a2-order-smoke-") as directory:
        stage = Path(directory)
        a2.safe_extract(archive, stage)
        code = f'''
import hashlib, json, pathlib, sys
sys.path.insert(0, {str(stage)!r})
namespace = {{"__name__": "submission_entry"}}
exec(compile(pathlib.Path("main.py").read_text(encoding="utf-8"), "main.py", "exec"), namespace)
agent = namespace["_AGENT"]
deck = namespace["agent"]({{"select": None, "current": None, "logs": []}})
assert len(deck) == 60
assert type(agent).__name__ == "ActualOrderAgent"
assert agent.actual_order is None
assert int(agent.policy_first.policy.model.feature_version) == 3
assert int(agent.policy_second.policy.model.feature_version) == 3
digest = lambda name: hashlib.sha256(pathlib.Path(name).read_bytes()).hexdigest().upper()
assert digest("policy_first.npz") == {first_sha!r}
assert digest("policy_second.npz") == {second_sha!r}
print(json.dumps({{"deck_card_count": len(deck), "router": type(agent).__name__, "first_schema": 3, "second_schema": 3}}))
'''
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        for key in a2.BEHAVIOR_ENV_KEYS:
            environment.pop(key, None)
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", code], cwd=stage, env=environment,
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode:
            raise a2.PackageError(
                "sterile A2 order package smoke failed: "
                + (result.stderr.strip() or result.stdout.strip())
            )
        try:
            payload = json.loads(result.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise a2.PackageError(f"malformed order smoke output: {result.stdout!r}") from exc
        return {"passed": True, "isolated_python": True, "bytecode_disabled": True, **payload}


def build_order_package(
    *,
    first_model: Path,
    second_model: Path,
    broad_gate: Path,
    hard_gate: Path,
    gameplay_evidence: Path | None = None,
    output_dir: Path = DEFAULT_OUTPUT,
    name: str = "temporal_order_second_a2_shield",
    source_archive: Path = a2.DEFAULT_SOURCE_ARCHIVE,
) -> dict[str, Any]:
    name = a2._validate_name(name)
    first_model = first_model.resolve()
    second_model = second_model.resolve()
    source_archive = source_archive.resolve()
    output_dir = output_dir.resolve()
    if a2.sha256_file(source_archive) != a2.FROZEN_SOURCE_ARCHIVE_SHA256:
        raise a2.PackageError("order package source is not the pinned authentic A2 archive")
    first = a2.validate_model(first_model)
    second = a2.validate_model(second_model)
    gate = heldout_gate(broad_gate.resolve(), hard_gate.resolve(), first["sha256"], second["sha256"])
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / f"{name}.tar.gz"
    manifest_path = output_dir / f"{name}.manifest.json"
    with tempfile.TemporaryDirectory(prefix="a2-order-build-", dir=output_dir) as directory:
        work = Path(directory)
        stages = [work / "first", work / "second"]
        metadata = [stage_order_package(source_archive, first_model, second_model, stage) for stage in stages]
        if metadata[0] != metadata[1]:
            raise a2.PackageError("fresh A2 order package stages differ")
        archives = [work / "first.tar.gz", work / "second.tar.gz"]
        for stage, archive in zip(stages, archives):
            a2.deterministic_tar(stage, archive)
        hashes = [a2.sha256_file(path) for path in archives]
        if hashes[0] != hashes[1]:
            raise a2.PackageError(f"A2 order package is not deterministic: {hashes}")
        smoke = sterile_smoke(archives[0], first["sha256"], second["sha256"])
        staged_archive = work / "final.tar.gz"
        shutil.copyfile(archives[0], staged_archive)
        meta = metadata[0]
        gameplay = (
            gameplay_gate(gameplay_evidence.resolve(), meta["package_tree_sha256"])
            if gameplay_evidence is not None
            else {
                "provided": False,
                "passed": False,
                "gameplay_eligible": False,
                "minimum_pairs_per_order": GAMEPLAY_MIN_PAIRS_PER_ORDER,
            }
        )
        status = (
            "packaged_gameplay_promoted"
            if gameplay["passed"]
            else "packaged_gameplay_rejected"
            if gameplay["provided"]
            else "packaged_gameplay_unverified"
        )
        manifest = {
            "schema_version": 1,
            "status": status,
            "source_runtime": {
                "archive": str(source_archive),
                "archive_sha256": a2.FROZEN_SOURCE_ARCHIVE_SHA256,
                "extracted_tree_sha256": meta["source"]["extracted_tree_sha256"],
                "runtime_source_tree_sha256": meta["source"]["runtime_source_tree_sha256"],
                "fallback_model_sha256": meta["source"]["source_model"]["sha256"],
                "deck": meta["source"]["deck"],
            },
            "models": {
                "first": {
                    "role": "behavior-identical authentic A2 actual-first policy",
                    "path": str(first_model),
                    **first,
                },
                "second": {
                    "role": "learned actual-second policy",
                    "path": str(second_model),
                    **second,
                },
                "distinct": first["sha256"] != second["sha256"],
            },
            "routing": {
                "order_source": "latched current.firstPlayer compared with current.yourIndex",
                "pre_latch_policy": "first",
                "candidate_failure_fallback": "authentic A2 shield",
                "first_policy": "behavior-identical authentic A2",
                "second_policy": "learned actual-second policy",
                "runtime_controls": dict(a2.RUNTIME_CONTROLS),
                "entrypoint_sha256": meta["entrypoint_sha256"],
                "router_sha256": meta["router_sha256"],
                "runtime_source_tree_sha256": meta["runtime_source_tree_sha256"],
            },
            "heldout_second_gate": gate,
            "gameplay_promotion_gate": gameplay,
            "output": {
                "archive": str(archive_path),
                "archive_sha256": hashes[0],
                "archive_bytes": staged_archive.stat().st_size,
                "extracted_tree_sha256": meta["package_tree_sha256"],
            },
            "verification": {
                "deterministic_double_build": True,
                "first_archive_sha256": hashes[0],
                "second_archive_sha256": hashes[1],
                "sterile_smoke": smoke,
                "cache_free_archive": True,
            },
            "deployment": {
                "gameplay_run": gameplay["provided"],
                "gameplay_eligible": gameplay["passed"],
                "uploaded": False,
                "cloud_started": False,
            },
        }
        staged_manifest = work / "final.manifest.json"
        staged_manifest.write_text(
            json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8", newline="\n",
        )
        os.replace(staged_archive, archive_path)
        os.replace(staged_manifest, manifest_path)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first-model", type=Path, required=True)
    parser.add_argument("--second-model", type=Path, required=True)
    parser.add_argument("--broad-gate", type=Path, required=True)
    parser.add_argument("--hard-gate", type=Path, required=True)
    parser.add_argument("--gameplay-evidence", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--name", default="temporal_order_second_a2_shield")
    parser.add_argument("--source-archive", type=Path, default=a2.DEFAULT_SOURCE_ARCHIVE)
    args = parser.parse_args()
    result = build_order_package(
        first_model=args.first_model,
        second_model=args.second_model,
        broad_gate=args.broad_gate,
        hard_gate=args.hard_gate,
        gameplay_evidence=args.gameplay_evidence,
        output_dir=args.output_dir,
        name=args.name,
        source_archive=args.source_archive,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

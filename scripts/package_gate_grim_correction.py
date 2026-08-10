#!/usr/bin/env python3
"""Build and locally gate a correction-only Grimmsnarl package.

This command is deliberately incapable of uploading a submission or starting a
cloud worker.  It packages from the byte-exact d842 archive, and the evaluation
subcommand compares extracted packages through the native forced-order runner.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing as mp
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from scripts import build_recovery_probes
from training import evaluate_forced_order
from training.evaluation_schema import sha256_path


FROZEN_ARCHIVE_SHA256 = "3ECB0BBF119E23C31905E39E19ECA8F6145104AAEFFC0A5675D2FE03855BB458"
FROZEN_MODEL_SHA256 = "D842F85ABFC44AF9F41979F91795E22C92C179B62E04D5A0A2F9C734E70AF1C3"
FROZEN_RAW_DECK_SHA256 = "92B92BAC9F9163ECFF933B3DC39294D2CC154C8684F3C8497877661419EBC59D"
FROZEN_CANONICAL_DECK_SHA256 = "C20A8A46F5C635773754F03103652F5C534B13DC622448ED2255A97234C103AF"
FROZEN_LINUX_ENGINE_SHA256 = "D16244A3157FC55C3314F08DCC7C5179168697D78C105B95C7DEBD556B764BB7"
FROZEN_WINDOWS_ENGINE_SHA256 = "EAE88634E26DC31D94150A4D8202FC9D32596B8C688EF67E14CB4088CD4D5771"
FROZEN_SCHEMA3_ANCHOR_SHA256 = "2715C6FDB8A85404ABCFF183FD3A61B419DA1402F11A29BA51676753C57A6B1B"
FROZEN_BEHAVIOR_SHA256 = "509A2D2DD655C33FCFA2803C2A973A6E285AA8D9215A960F7B4C2B67282BAB72"
Z_ONE_SIDED_95 = 1.6448536269514722
EPSILON = 1e-12

DEFAULT_REFERENCE = ROOT / "grimmsnarl_5k_reference.tar.gz"
DEFAULT_MIGRATION_AUDIT = ROOT / "artifacts/recovery_schema3/d842_schema3_zero_init.json"
DEFAULT_RETENTION = {
    "master_v1": ROOT / "artifacts/recovery_final/opponents/master_v1",
    "replay_refresh": ROOT / "artifacts/recovery_final/opponents/replay_refresh",
    "v2_2": ROOT / "artifacts/recovery_final/opponents/v2_2",
    "alakazam_2_4a": ROOT / "freshstart/elite_submissions/alakazam_2_4a",
    "alakazam_2_7": ROOT / "freshstart/elite_submissions/alakazam_2_7",
}
EXPECTED_RETENTION_TREE_SHA256 = {
    "master_v1": "CD9FE758D8D96A6D68A7676B80E7A69C21608ABD090CC0F948B386998F42FB3C",
    "replay_refresh": "DEB70CD2CDC58552A7859D8FCD508BEFEED90660165659B80DF0B272BDAD5F7C",
    "v2_2": "84EBE01FCCAFFD761F4AC88A1C5EF0558B5C8BD5891E2F95AF95F6CA91533C98",
    "alakazam_2_4a": "3D447356DB257A3AB1F0025A15E9EC05982D567EEF0DDBF3D9F2F34B6E50B912",
    "alakazam_2_7": "0D4C9F7B9F1572B5823DC16631E6CD66E1928790E81157DB0A72A3ED0709EBE9",
}


class GateError(RuntimeError):
    """A fail-closed packaging or evaluation invariant failed."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def canonical_deck_sha256(cards: Iterable[Any]) -> str:
    try:
        values = tuple(sorted(int(card) for card in cards))
    except (TypeError, ValueError) as exc:
        raise GateError(f"deck contains a non-integer card id: {exc}") from exc
    if len(values) != 60:
        raise GateError(f"deck must contain exactly 60 cards, got {len(values)}")
    return hashlib.sha256(",".join(map(str, values)).encode("ascii")).hexdigest().upper()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def write_immutable_json(path: str | Path, value: Any) -> None:
    """Create an evidence file once; an identical rerun is harmless."""

    target = Path(path)
    payload = _json_bytes(value)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != payload:
            raise GateError(f"refusing to overwrite immutable manifest: {target}")
        return
    with target.open("xb") as handle:
        handle.write(payload)


def _cache_file(path: Path) -> bool:
    lowered = {part.lower() for part in path.parts}
    return bool(
        lowered.intersection({"__pycache__", ".pytest_cache", ".mypy_cache", ".cache"})
        or path.suffix.lower() in {".pyc", ".pyo"}
    )


def _tree_hashes(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root)
        if _cache_file(relative):
            raise GateError(f"cache artifact is forbidden in a package: {relative.as_posix()}")
        result[relative.as_posix()] = sha256_file(path)
    return result


def verify_frozen_reference(stage: Path) -> dict[str, Any]:
    """Verify all frozen identities on a newly extracted reference tree."""

    required = {
        "policy_weights.npz": FROZEN_MODEL_SHA256,
        "deck.csv": FROZEN_RAW_DECK_SHA256,
        "cg/libcg.so": FROZEN_LINUX_ENGINE_SHA256,
    }
    mismatches = {}
    for relative, expected in required.items():
        path = stage / relative
        actual = sha256_file(path) if path.is_file() else None
        if actual != expected:
            mismatches[relative] = {"expected": expected, "actual": actual}
    if mismatches:
        raise GateError("frozen d842 extraction mismatch: " + json.dumps(mismatches, sort_keys=True))
    deck = [line for line in (stage / "deck.csv").read_text(encoding="utf-8").splitlines() if line.strip()]
    canonical = canonical_deck_sha256(deck)
    if canonical != FROZEN_CANONICAL_DECK_SHA256:
        raise GateError(
            f"canonical deck mismatch: expected {FROZEN_CANONICAL_DECK_SHA256}, got {canonical}"
        )
    hashes = _tree_hashes(stage)
    return {
        "archive_sha256": FROZEN_ARCHIVE_SHA256,
        "model_sha256": hashes["policy_weights.npz"],
        "raw_deck_sha256": hashes["deck.csv"],
        "canonical_deck_sha256": canonical,
        "linux_engine_sha256": hashes["cg/libcg.so"],
        "tree_sha256": sha256_path(stage).upper(),
        "file_count": len(hashes),
    }


def inspect_candidate_model(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise GateError(f"candidate model does not exist: {path}")
    try:
        with np.load(path, allow_pickle=False) as arrays:
            schema = int(np.asarray(arrays["model_schema_version"]).item())
            names = sorted(arrays.files)
            for name in names:
                value = np.asarray(arrays[name])
                if value.dtype.kind in "fc" and not bool(np.isfinite(value).all()):
                    raise GateError(f"candidate array contains non-finite values: {name}")
    except GateError:
        raise
    except Exception as exc:
        raise GateError(f"candidate is not a valid inference NPZ: {exc}") from exc
    if schema != 3:
        raise GateError(f"correction-only candidate must use schema 3, got schema {schema}")
    return {"sha256": sha256_file(path), "schema": schema, "array_names": names}


def verify_training_audit(
    candidate_model: Path,
    training_manifest_path: Path,
    migration_manifest_path: Path,
    *,
    minimum_corrections: int = 250,
) -> dict[str, Any]:
    """Bind one qualified correction-only run to the exact d842 anchor."""

    try:
        training = json.loads(training_manifest_path.read_text(encoding="utf-8"))
        migration = json.loads(migration_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError(f"could not read training provenance: {exc}") from exc
    candidate = inspect_candidate_model(candidate_model)
    if training.get("qualified") is not True or training.get("prototype") is not False:
        raise GateError("training manifest is not a qualified, non-prototype correction-only run")
    dataset = training.get("dataset")
    settings = training.get("settings")
    runs = training.get("runs")
    if not isinstance(dataset, dict) or not isinstance(settings, dict) or not isinstance(runs, list):
        raise GateError("training manifest is missing dataset/settings/runs audit sections")
    unique_corrections = int(dataset.get("unique_corrections", -1))
    if unique_corrections < minimum_corrections:
        raise GateError(f"training used fewer than {minimum_corrections} certified corrections")
    if int(dataset.get("correction_episode_groups", -1)) < 30:
        raise GateError("training used corrections from fewer than 30 independent episodes")
    if "episode" not in str(dataset.get("split_unit", "")).lower():
        raise GateError("training audit does not prove episode-atomic splitting")
    if dataset.get("rehearsal_labels") != "recomputed from anchor; replay actions ignored":
        raise GateError("training audit does not prove exact-anchor rehearsal labels")
    anchor_sha = str(dataset.get("anchor_sha256", "")).upper()
    if anchor_sha != FROZEN_SCHEMA3_ANCHOR_SHA256:
        raise GateError(f"unexpected schema-3 training anchor: {anchor_sha or '<missing>'}")
    if str(dataset.get("anchor_behavior_sha256", "")).upper() != FROZEN_BEHAVIOR_SHA256:
        raise GateError("training anchor behavior digest is not exact d842")
    certification_kinds = dataset.get("certification_kinds")
    if certification_kinds != {"complete_turn_v1": unique_corrections}:
        raise GateError("every packaged correction must have the complete-turn-v1 certificate")
    if str(migration.get("source_sha256", "")).upper() != FROZEN_MODEL_SHA256:
        raise GateError("schema-3 migration is not anchored to D842F85A")
    if str(migration.get("output_sha256", "")).upper() != anchor_sha:
        raise GateError("schema-3 migration output does not match the training anchor")
    migration_description = str(migration.get("migration", "")).lower()
    if "zero" not in migration_description or "unchanged" not in migration_description:
        raise GateError("schema-3 migration audit is not behavior-preserving")
    modules = tuple(str(value) for value in settings.get("trainable_modules", ()))
    if not modules or not set(modules).issubset({"score", "count"}):
        raise GateError(f"training was not correction-only score/count tuning: {modules}")
    if candidate["sha256"] in {FROZEN_MODEL_SHA256, anchor_sha}:
        raise GateError("qualified candidate is byte-identical to its frozen anchor")
    matches = [
        run for run in runs
        if isinstance(run, dict)
        and run.get("qualified") is True
        and str(run.get("sha256", "")).upper() == candidate["sha256"]
    ]
    if len(matches) != 1:
        raise GateError("candidate hash must identify exactly one qualified training run")
    selected = matches[0]
    if str(selected.get("anchor_sha256", "")).upper() != anchor_sha:
        raise GateError("selected training run has the wrong anchor")
    artifact_audit = selected.get("artifact_audit")
    if not isinstance(artifact_audit, dict):
        raise GateError("selected run has no post-export artifact audit")
    try:
        correction_lift = float(artifact_audit["correction_lift"])
        change_rate = float(artifact_audit["rehearsal_change_rate"])
        minimum_lift = float(settings["min_correction_lift"])
        maximum_change = float(settings["max_change_rate"])
        correction_anchor_identity = float(artifact_audit["correction_anchor_identity"])
        rehearsal_anchor_identity = float(artifact_audit["rehearsal_anchor_identity"])
    except (KeyError, TypeError, ValueError) as exc:
        raise GateError(f"selected run has incomplete numeric gates: {exc}") from exc
    if not all(math.isfinite(value) for value in (
        correction_lift, change_rate, minimum_lift, maximum_change,
        correction_anchor_identity, rehearsal_anchor_identity,
    )):
        raise GateError("selected run contains non-finite audit metrics")
    if correction_lift + EPSILON < minimum_lift or change_rate > maximum_change + EPSILON:
        raise GateError("selected exported model fails its declared correction/change gates")
    if correction_anchor_identity != 1.0 or rehearsal_anchor_identity != 1.0:
        raise GateError("selected run was not audited against the exact anchor behavior")
    selected_modules = tuple(str(value) for value in selected.get("trainable_parameters", ()))
    selected_roots = {re.split(r"[._]", value, maxsplit=1)[0] for value in selected_modules}
    if not selected_modules or not selected_roots.issubset({"score", "count"}):
        raise GateError("selected run reports parameters outside the score/count modules")
    return {
        "training_manifest_sha256": sha256_file(training_manifest_path),
        "migration_manifest_sha256": sha256_file(migration_manifest_path),
        "qualified": True,
        "prototype": False,
        "unique_corrections": int(dataset["unique_corrections"]),
        "correction_episode_groups": int(dataset.get("correction_episode_groups", 0)),
        "corrections_sha256": str(dataset.get("corrections_sha256", "")).upper(),
        "rehearsal_sha256": str(dataset.get("rehearsal_sha256", "")).upper(),
        "anchor_schema3_sha256": anchor_sha,
        "anchor_behavior_sha256": FROZEN_BEHAVIOR_SHA256,
        "anchor_source_sha256": FROZEN_MODEL_SHA256,
        "trainable_modules": list(modules),
        "settings": {
            key: settings.get(key)
            for key in (
                "seeds", "epochs", "learning_rate", "distill_weight", "correction_weight",
                "max_change_rate", "min_correction_lift",
            )
        },
        "selected_run": {
            "seed": selected.get("seed"),
            "model_sha256": candidate["sha256"],
            "anchor_sha256": anchor_sha,
            "correction_lift": correction_lift,
            "rehearsal_change_rate": change_rate,
            "trainable_parameters": selected.get("trainable_parameters"),
            "artifact_audit": artifact_audit,
        },
    }


def verify_candidate_tree(reference: Path, candidate: Path, candidate_model_sha256: str) -> dict[str, Any]:
    reference_hashes = _tree_hashes(reference)
    candidate_hashes = _tree_hashes(candidate)
    if set(reference_hashes) != set(candidate_hashes):
        missing = sorted(set(reference_hashes) - set(candidate_hashes))
        extra = sorted(set(candidate_hashes) - set(reference_hashes))
        raise GateError(f"candidate runtime tree changed: missing={missing}, extra={extra}")
    changed = [name for name in reference_hashes if reference_hashes[name] != candidate_hashes[name]]
    if changed != ["policy_weights.npz"]:
        raise GateError(f"candidate may replace only policy_weights.npz, changed={changed}")
    if candidate_hashes["policy_weights.npz"] != candidate_model_sha256:
        raise GateError("packaged model hash differs from the trained candidate")
    deck = [line for line in (candidate / "deck.csv").read_text(encoding="utf-8").splitlines() if line.strip()]
    if candidate_hashes["deck.csv"] != FROZEN_RAW_DECK_SHA256:
        raise GateError("candidate raw deck changed")
    if canonical_deck_sha256(deck) != FROZEN_CANONICAL_DECK_SHA256:
        raise GateError("candidate canonical deck changed")
    if candidate_hashes["cg/libcg.so"] != FROZEN_LINUX_ENGINE_SHA256:
        raise GateError("candidate Linux engine changed")
    return {
        "tree_sha256": sha256_path(candidate).upper(),
        "file_count": len(candidate_hashes),
        "only_changed_file": "policy_weights.npz",
        "model_sha256": candidate_hashes["policy_weights.npz"],
        "raw_deck_sha256": candidate_hashes["deck.csv"],
        "canonical_deck_sha256": FROZEN_CANONICAL_DECK_SHA256,
        "linux_engine_sha256": candidate_hashes["cg/libcg.so"],
    }


SMOKE_SOURCE = r'''
import json, os, pathlib, sys, time
root=pathlib.Path.cwd()
sys.path.insert(0,str(root))
namespace={"__name__":"submission_entry"}
assert "__file__" not in namespace
source=(root/"main.py").read_text(encoding="utf-8")
exec(compile(source,"main.py","exec"),namespace)
assert "__file__" not in namespace
agent=namespace["agent"]
deck=agent({"select":None,"current":None,"logs":[]})
assert len(deck)==60
games=int(os.environ.get("GRIM_SMOKE_GAMES","0"))
decisions=0
invalid=0
deterministic=True
latencies=[]
if games:
 from cg.api import to_observation_class
 from cg.game import battle_finish,battle_select,battle_start
 for _ in range(games):
  raw,started=battle_start(deck,deck)
  assert not started.errorType
  try:
   while True:
    obs=to_observation_class(raw)
    if obs.current is not None and int(obs.current.result)>=0: break
    begin=time.perf_counter(); action=agent(raw); latencies.append(time.perf_counter()-begin)
    again=agent(raw); deterministic=deterministic and action==again
    count=len(obs.select.option)
    valid=(len(action)==len(set(action)) and int(obs.select.minCount)<=len(action)<=int(obs.select.maxCount)
           and all(0<=int(index)<count for index in action))
    if not valid:
     invalid+=1
     raise AssertionError("invalid policy selection")
    raw=battle_select(action); decisions+=1
    assert decisions < 10000
  finally:
   battle_finish()
errors=int(getattr(namespace.get("_AGENT"),"errors",0) or 0)
latencies.sort()
result={"passed":errors==0 and invalid==0 and deterministic,"platform":sys.platform,
 "python":sys.version.split()[0],
 "games":games,"decisions":decisions,"policy_errors":errors,"invalid_actions":invalid,
 "deterministic_duplicate_decisions":deterministic,"raw_source_without_file":True,
 "latency_p99_ms":(1000*latencies[min(len(latencies)-1,int(len(latencies)*.99))] if latencies else None)}
print(json.dumps(result,sort_keys=True))
assert result["passed"]
'''


def _extract_archive(archive: Path, destination: Path) -> None:
    build_recovery_probes.safe_extract(archive, destination)


def smoke_archive(archive: Path, *, games: int, require_linux: bool) -> dict[str, Any]:
    if games < 0:
        raise GateError("smoke game count cannot be negative")
    if require_linux and not sys.platform.startswith("linux"):
        raise GateError("Linux smoke must execute under a Linux Python interpreter")
    with tempfile.TemporaryDirectory(prefix="grim-correction-smoke-") as temporary:
        stage = Path(temporary)
        _extract_archive(archive, stage)
        candidate_hashes = _tree_hashes(stage)
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment.update({
            "PYTHONDONTWRITEBYTECODE": "1",
            "PTCG_TEMP": "0",
            "PTCG_SEARCH": "0",
            "GRIM_SMOKE_GAMES": str(games),
        })
        completed = subprocess.run(
            [sys.executable, "-I", "-c", SMOKE_SOURCE],
            cwd=stage,
            env=environment,
            text=True,
            capture_output=True,
            timeout=max(60, 300 * max(1, games)),
            check=False,
        )
        if completed.returncode:
            raise GateError(
                "sterile package smoke failed: "
                + (completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}")
            )
        try:
            payload = json.loads(completed.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise GateError(f"sterile package smoke returned invalid JSON: {exc}") from exc
    payload.update({
        "archive_sha256": sha256_file(archive),
        "model_sha256": candidate_hashes["policy_weights.npz"],
        "raw_deck_sha256": candidate_hashes["deck.csv"],
        "canonical_deck_sha256": FROZEN_CANONICAL_DECK_SHA256,
        "linux_engine_sha256": candidate_hashes["cg/libcg.so"],
    })
    if require_linux and not str(payload.get("platform", "")).startswith("linux"):
        raise GateError("smoke report did not originate on Linux")
    return payload


def verify_linux_smoke_report(report: Mapping[str, Any], archive: Path, model_sha256: str) -> dict[str, Any]:
    required = {
        "archive_sha256": sha256_file(archive),
        "model_sha256": model_sha256,
        "raw_deck_sha256": FROZEN_RAW_DECK_SHA256,
        "canonical_deck_sha256": FROZEN_CANONICAL_DECK_SHA256,
        "linux_engine_sha256": FROZEN_LINUX_ENGINE_SHA256,
    }
    mismatches = {
        key: {"expected": expected, "actual": str(report.get(key, "")).upper()}
        for key, expected in required.items()
        if str(report.get(key, "")).upper() != expected
    }
    checks = {
        "passed": report.get("passed") is True,
        "linux": str(report.get("platform", "")).startswith("linux"),
        "games": int(report.get("games", 0)) >= 2,
        "decisions": int(report.get("decisions", 0)) > 0,
        "zero_policy_errors": int(report.get("policy_errors", -1)) == 0,
        "zero_invalid_actions": int(report.get("invalid_actions", -1)) == 0,
        "deterministic": report.get("deterministic_duplicate_decisions") is True,
        "raw_source_without_file": report.get("raw_source_without_file") is True,
        "hashes": not mismatches,
    }
    if not all(checks.values()):
        raise GateError(
            "Linux smoke report failed package binding: "
            + json.dumps({"checks": checks, "mismatches": mismatches}, sort_keys=True)
        )
    return {**dict(report), "checks": checks}


def _copy_immutable(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if sha256_file(source) != sha256_file(target):
            raise GateError(f"refusing to overwrite a different candidate archive: {target}")
        return
    shutil.copyfile(source, target)


def build_candidate(
    *,
    candidate_model: Path,
    training_manifest: Path,
    migration_manifest: Path,
    output_dir: Path,
    linux_smoke_report: Path | None = None,
    allow_pending_linux_smoke: bool = False,
) -> dict[str, Any]:
    reference = DEFAULT_REFERENCE.resolve()
    if build_recovery_probes.CONTROL.resolve() != reference:
        raise GateError("build_unshielded is not bound to the expected frozen reference path")
    if sha256_file(reference) != FROZEN_ARCHIVE_SHA256:
        raise GateError("reference archive is not byte-exact 3ECB0BBF")
    training_audit = verify_training_audit(candidate_model, training_manifest, migration_manifest)
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="grim-correction-build-") as temporary:
        workspace = Path(temporary)
        frozen_stage = workspace / "fresh_reference"
        frozen_stage.mkdir()
        _extract_archive(reference, frozen_stage)
        frozen = verify_frozen_reference(frozen_stage)

        # Reuse the historical package builder twice from independent outputs.
        first = build_recovery_probes.build_unshielded(
            "grim_correction_candidate", candidate_model, workspace / "pass_one"
        )
        second = build_recovery_probes.build_unshielded(
            "grim_correction_candidate", candidate_model, workspace / "pass_two"
        )
        first_archive = Path(first["archive"])
        second_archive = Path(second["archive"])
        if sha256_file(first_archive) != sha256_file(second_archive):
            raise GateError("two clean candidate builds were not byte-identical")
        first_stage = workspace / "candidate_one"
        second_stage = workspace / "candidate_two"
        first_stage.mkdir(); second_stage.mkdir()
        _extract_archive(first_archive, first_stage)
        _extract_archive(second_archive, second_stage)
        candidate_tree = verify_candidate_tree(frozen_stage, first_stage, training_audit["selected_run"]["model_sha256"])
        second_tree = verify_candidate_tree(frozen_stage, second_stage, training_audit["selected_run"]["model_sha256"])
        if candidate_tree["tree_sha256"] != second_tree["tree_sha256"]:
            raise GateError("independently extracted candidate trees differ")
        portable_smoke = smoke_archive(first_archive, games=0, require_linux=False)
        final_archive = output_dir / "grim_correction_candidate.tar.gz"
        _copy_immutable(first_archive, final_archive)

    linux_report: dict[str, Any] | None
    if linux_smoke_report is not None:
        try:
            supplied = json.loads(linux_smoke_report.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GateError(f"could not read Linux smoke report: {exc}") from exc
        linux_report = verify_linux_smoke_report(
            supplied, final_archive, training_audit["selected_run"]["model_sha256"]
        )
    elif sys.platform.startswith("linux"):
        linux_report = verify_linux_smoke_report(
            smoke_archive(final_archive, games=4, require_linux=True),
            final_archive,
            training_audit["selected_run"]["model_sha256"],
        )
    else:
        linux_report = None

    result = {
        "schema_version": 1,
        "status": "packaged_qualified" if linux_report else "development_build_pending_linux_smoke",
        "qualified_for_evaluation": bool(linux_report),
        "frozen_inputs": frozen,
        "training_audit": training_audit,
        "output": {
            "archive_name": final_archive.name,
            "archive_sha256": sha256_file(final_archive),
            "archive_bytes": final_archive.stat().st_size,
            **candidate_tree,
        },
        "build_audit": {
            "fresh_reference_extraction_verified_before_model_replacement": True,
            "builder": "scripts.build_recovery_probes.build_unshielded",
            "deterministic_double_build": True,
            "cache_files_excluded": True,
            "only_policy_weights_replaced": True,
            "portable_raw_source_without_file": portable_smoke,
            "linux_smoke": linux_report,
        },
        "deployment": {"uploaded": False, "azure_started": False},
    }
    if linux_report:
        write_immutable_json(output_dir / "package_manifest.json", result)
    elif allow_pending_linux_smoke:
        write_immutable_json(output_dir / "development_build_manifest.json", result)
    else:
        raise GateError(
            "candidate built but is not qualified: run the linux-smoke subcommand on Linux "
            "and supply its bound report"
        )
    return result


def _safe_extract_zip(archive: Path, destination: Path) -> None:
    root = destination.resolve()
    with zipfile.ZipFile(archive) as handle:
        for member in handle.infolist():
            target = (destination / member.filename).resolve()
            if target != root and root not in target.parents:
                raise GateError(f"unsafe ZIP member: {member.filename}")
        handle.extractall(destination)


def _materialize_submission(source: Path, destination: Path) -> Path:
    if source.is_dir():
        result = source.resolve()
    elif source.is_file() and zipfile.is_zipfile(source):
        destination.mkdir(parents=True)
        _safe_extract_zip(source, destination)
        result = destination
    elif source.is_file() and tarfile.is_tarfile(source):
        destination.mkdir(parents=True)
        _extract_archive(source, destination)
        result = destination
    else:
        raise GateError(f"submission path is neither a directory nor a supported archive: {source}")
    if not (result / "main.py").is_file() or not (result / "deck.csv").is_file():
        children = [item for item in result.iterdir() if item.is_dir()] if result.is_dir() else []
        if len(children) == 1 and (children[0] / "main.py").is_file() and (children[0] / "deck.csv").is_file():
            result = children[0]
        else:
            raise GateError(f"submission lacks root main.py/deck.csv: {source}")
    deck = [line for line in (result / "deck.csv").read_text(encoding="utf-8").splitlines() if line.strip()]
    canonical_deck_sha256(deck)
    return result


def _seed_for(base_seed: int, cell: str) -> int:
    digest = hashlib.sha256(f"{base_seed}:{cell}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


def build_evaluation_schedule(
    *,
    candidate: Path,
    control: Path,
    retention: Mapping[str, Path],
    direct_games: int,
    retention_games: int,
    seed: int,
    max_decisions: int,
) -> tuple[list[tuple], dict[str, dict[str, Any]]]:
    if direct_games <= 0 or direct_games % 4:
        raise GateError("direct games must be positive and divisible by four")
    if retention_games <= 0 or retention_games % 4:
        raise GateError("retention games per opponent must be positive and divisible by four")
    if not retention:
        raise GateError("at least one retention opponent is required")
    schedule: list[tuple] = []
    metadata: dict[str, dict[str, Any]] = {}

    def add(cell: str, hero: Path, opponent: Path, order: str, games: int) -> None:
        cell_seed = _seed_for(seed, cell)
        metadata[cell] = {"order": order, "games": games, "seed": cell_seed}
        for index in range(games):
            schedule.append((cell, index, str(hero), str(opponent), order, cell_seed, max_decisions))

    for order in ("first", "second"):
        add(f"direct:{order}", candidate, control, order, direct_games // 2)
    for name, opponent in sorted(retention.items()):
        for order in ("first", "second"):
            # Identical seed/index/seat schedules bind the two arms.  The native
            # engine still uses std::random_device, so inference remains
            # independent-binomial and the manifest says so explicitly.
            common_seed = _seed_for(seed, f"retention:{name}:{order}")
            for arm, hero in (("candidate", candidate), ("control", control)):
                cell = f"retention:{name}:{order}:{arm}"
                metadata[cell] = {"order": order, "games": retention_games // 2, "seed": common_seed}
                for index in range(retention_games // 2):
                    schedule.append((cell, index, str(hero), str(opponent), order, common_seed, max_decisions))
    return schedule, metadata


def _run_scheduled_game(spec: tuple) -> tuple[str, int, dict[str, Any]]:
    cell, index, hero, opponent, order, seed, max_decisions = spec
    row = evaluate_forced_order.run_game((index, hero, opponent, order, seed, max_decisions))
    return cell, index, row


def execute_schedule(
    schedule: Sequence[tuple],
    *,
    workers: int,
    runner: Callable[[tuple], tuple[str, int, dict[str, Any]]] | None = None,
) -> dict[str, dict[int, dict[str, Any]]]:
    if workers <= 0:
        raise GateError("worker count must be positive")
    grouped: dict[str, dict[int, dict[str, Any]]] = {}
    run_one = runner or _run_scheduled_game
    if runner is not None or workers == 1:
        iterator = map(run_one, schedule)
        pool = None
    else:
        pool = mp.get_context("spawn").Pool(workers)
        iterator = pool.imap_unordered(run_one, schedule, chunksize=4)
    failed = False
    try:
        for completed, (cell, index, row) in enumerate(iterator, 1):
            cells = grouped.setdefault(cell, {})
            if index in cells:
                raise GateError(f"duplicate game result: {cell}/{index}")
            cells[index] = row
            if runner is None and completed % 500 == 0:
                print(json.dumps({"completed_games": completed, "scheduled_games": len(schedule)}), flush=True)
    except BaseException:
        failed = True
        raise
    finally:
        if pool is not None:
            if failed:
                pool.terminate()
            else:
                pool.close()
            pool.join()
    return grouped


def _summarize_cell(
    rows: Mapping[int, Mapping[str, Any]], expected: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[int, int]]:
    games = int(expected["games"])
    if set(rows) != set(range(games)):
        raise GateError("evaluation cell has incomplete or duplicate game-index coverage")
    order = str(expected["order"])
    if any(row.get("actual_order") != order for row in rows.values()):
        raise GateError("forced-order cell reported the wrong actual order")
    seats = {"0": {"games": 0, "wins": 0}, "1": {"games": 0, "wins": 0}}
    wins = draws = hero_errors = opponent_errors = decisions = 0
    outcomes = {}
    for index, row in rows.items():
        win = int(row.get("win", -1)); draw = int(row.get("draw", -1))
        seat = str(row.get("physical_seat"))
        if win not in (0, 1) or draw not in (0, 1) or seat not in seats or win + draw > 1:
            raise GateError("forced-order runner returned an invalid game result")
        wins += win; draws += draw; outcomes[index] = win
        hero_errors += int(row.get("hero_errors", -1))
        opponent_errors += int(row.get("opponent_errors", -1))
        decisions += int(row.get("decisions", -1))
        seats[seat]["games"] += 1; seats[seat]["wins"] += win
    if any(value < 0 for value in (hero_errors, opponent_errors, decisions)):
        raise GateError("forced-order runner omitted error/decision accounting")
    if any(cell["games"] != games // 2 for cell in seats.values()):
        raise GateError("physical-seat schedule is not balanced")
    summary = {
        "games": games,
        "wins": wins,
        "draws": draws,
        "win_rate": wins / games,
        "one_sided_95_lower": evaluate_forced_order.wilson_lower(wins, games),
        "actual_order": order,
        "physical_seats": seats,
        "hero_policy_errors": hero_errors,
        "opponent_policy_errors": opponent_errors,
        "decisions": decisions,
        "seed": int(expected["seed"]),
        "actual_order_accounting_complete": True,
    }
    return summary, outcomes


def _merge_cells(cells: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not cells:
        raise GateError("cannot merge an empty evaluation")
    games = sum(int(cell["games"]) for cell in cells)
    wins = sum(int(cell["wins"]) for cell in cells)
    return {
        "games": games,
        "wins": wins,
        "draws": sum(int(cell["draws"]) for cell in cells),
        "win_rate": wins / games,
        "one_sided_95_lower": evaluate_forced_order.wilson_lower(wins, games),
        "hero_policy_errors": sum(int(cell["hero_policy_errors"]) for cell in cells),
        "opponent_policy_errors": sum(int(cell["opponent_policy_errors"]) for cell in cells),
        "decisions": sum(int(cell["decisions"]) for cell in cells),
        "actual_order_accounting_complete": all(cell.get("actual_order_accounting_complete") is True for cell in cells),
    }


def direct_strength_gate(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
    *,
    minimum_rate: float = 0.54,
    minimum_lower: float = 0.53,
    order_floor: float = 0.50,
) -> dict[str, Any]:
    aggregate = _merge_cells([first, second])
    checks = {
        "balanced_first_second": int(first["games"]) == int(second["games"]),
        "candidate_win_rate_at_least_54_percent": aggregate["win_rate"] + EPSILON >= minimum_rate,
        "one_sided_wilson_lower_at_least_53_percent": aggregate["one_sided_95_lower"] + EPSILON >= minimum_lower,
        "first_order_no_regression": float(first["win_rate"]) + EPSILON >= order_floor,
        "second_order_no_regression": float(second["win_rate"]) + EPSILON >= order_floor,
        "zero_policy_errors": aggregate["hero_policy_errors"] == 0 and aggregate["opponent_policy_errors"] == 0,
        "actual_order_accounting_complete": aggregate["actual_order_accounting_complete"] is True,
    }
    return {
        "passed": all(checks.values()),
        "thresholds": {
            "minimum_win_rate": minimum_rate,
            "minimum_one_sided_95_lower": minimum_lower,
            "minimum_each_order_win_rate": order_floor,
        },
        "checks": checks,
        "aggregate": aggregate,
        "orders": {"first": dict(first), "second": dict(second)},
    }


def _independent_stratified_lower(pairs: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]]) -> dict[str, Any]:
    if not pairs:
        raise GateError("retention inference has no opponent strata")
    total = sum(int(candidate["games"]) for candidate, _ in pairs)
    difference = variance = 0.0
    for candidate, control in pairs:
        cn = int(candidate["games"]); bn = int(control["games"])
        if cn <= 0 or cn != bn:
            raise GateError("candidate/control retention samples are incomplete or unequal")
        pc = int(candidate["wins"]) / cn; pb = int(control["wins"]) / bn
        weight = cn / total
        difference += weight * (pc - pb)
        variance += weight * weight * (pc * (1 - pc) / cn + pb * (1 - pb) / bn)
    return {
        "difference": difference,
        "one_sided_95_lower": difference - Z_ONE_SIDED_95 * math.sqrt(variance),
        "method": "opponent_stratified_independent_binomial",
    }


def _paired_schedule_lower(differences: Sequence[int]) -> dict[str, Any]:
    if len(differences) < 2 or any(value not in (-1, 0, 1) for value in differences):
        raise GateError("paired schedule requires at least two valid binary outcome differences")
    size = len(differences)
    mean = sum(differences) / size
    variance = sum((value - mean) ** 2 for value in differences) / (size - 1)
    return {
        "difference": mean,
        "one_sided_95_lower": mean - Z_ONE_SIDED_95 * math.sqrt(variance / size),
        "method": "actual_order_physical_seat_schedule_pairs",
        "pairs": size,
        "discordant_candidate_wins": sum(value == 1 for value in differences),
        "discordant_control_wins": sum(value == -1 for value in differences),
        "native_deals_paired": False,
    }


def retention_gate(
    summaries: Mapping[str, Mapping[str, Mapping[str, Any]]],
    outcomes: Mapping[str, Mapping[str, Mapping[str, Mapping[int, int]]]],
    *,
    minimum_aggregate_lower: float = -0.02,
    maximum_opponent_regression: float = 0.03,
) -> dict[str, Any]:
    if not summaries or set(summaries) != set(outcomes):
        raise GateError("retention opponent results are incomplete")
    pairs = []
    paired_differences: list[int] = []
    opponents = {}
    all_errors_zero = True
    all_accounted = True
    for name in sorted(summaries):
        candidate_orders = summaries[name].get("candidate", {})
        control_orders = summaries[name].get("control", {})
        if set(candidate_orders) != {"first", "second"} or set(control_orders) != {"first", "second"}:
            raise GateError(f"retention opponent is missing an order/arm: {name}")
        candidate = _merge_cells([candidate_orders["first"], candidate_orders["second"]])
        control = _merge_cells([control_orders["first"], control_orders["second"]])
        if candidate["games"] != control["games"]:
            raise GateError(f"retention arm sizes differ: {name}")
        difference = candidate["win_rate"] - control["win_rate"]
        point_passed = difference + EPSILON >= -maximum_opponent_regression
        errors_zero = all(
            int(cell[key]) == 0
            for cell in (candidate, control)
            for key in ("hero_policy_errors", "opponent_policy_errors")
        )
        accounted = candidate["actual_order_accounting_complete"] and control["actual_order_accounting_complete"]
        all_errors_zero &= errors_zero
        all_accounted &= bool(accounted)
        opponents[name] = {
            "candidate": candidate,
            "control": control,
            "point_difference": difference,
            "no_regression_over_3_points": point_passed,
            "zero_policy_errors": errors_zero,
        }
        pairs.append((candidate, control))
        for order in ("first", "second"):
            candidate_outcomes = outcomes[name]["candidate"][order]
            control_outcomes = outcomes[name]["control"][order]
            if set(candidate_outcomes) != set(control_outcomes):
                raise GateError(f"paired retention schedule differs: {name}/{order}")
            paired_differences.extend(
                candidate_outcomes[index] - control_outcomes[index]
                for index in sorted(candidate_outcomes)
            )
    independent = _independent_stratified_lower(pairs)
    schedule_paired = _paired_schedule_lower(paired_differences)
    conservative_lower = min(
        independent["one_sided_95_lower"], schedule_paired["one_sided_95_lower"]
    )
    checks = {
        "aggregate_one_sided_lower_at_least_minus_2_points": conservative_lower + EPSILON >= minimum_aggregate_lower,
        "no_opponent_point_regression_over_3_points": all(
            row["no_regression_over_3_points"] for row in opponents.values()
        ),
        "zero_policy_errors": all_errors_zero,
        "actual_order_accounting_complete": all_accounted,
    }
    return {
        "passed": all(checks.values()),
        "thresholds": {
            "minimum_aggregate_one_sided_95_lower": minimum_aggregate_lower,
            "maximum_opponent_point_regression": maximum_opponent_regression,
        },
        "checks": checks,
        "aggregate": {
            "difference": independent["difference"],
            "one_sided_95_lower": conservative_lower,
            "gate_uses_more_conservative_of": [independent["method"], schedule_paired["method"]],
            "independent_binomial": independent,
            "schedule_paired": schedule_paired,
            "rng_provenance": {
                "python_schedule_paired": True,
                "actual_order_and_physical_seat_paired": True,
                "native_engine_deals_paired": False,
                "reason": "BattleStart seeds the native engine through std::random_device",
            },
        },
        "opponents": opponents,
    }


def validate_package_manifest(manifest_path: Path, candidate_archive: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError(f"could not read package manifest: {exc}") from exc
    if manifest.get("qualified_for_evaluation") is not True or manifest.get("status") != "packaged_qualified":
        raise GateError("candidate package has not passed the bound Linux smoke")
    expected = str(manifest.get("output", {}).get("archive_sha256", "")).upper()
    if not expected or sha256_file(candidate_archive) != expected:
        raise GateError("candidate archive does not match its immutable package manifest")
    frozen = manifest.get("frozen_inputs", {})
    exact = {
        "archive_sha256": FROZEN_ARCHIVE_SHA256,
        "model_sha256": FROZEN_MODEL_SHA256,
        "raw_deck_sha256": FROZEN_RAW_DECK_SHA256,
        "canonical_deck_sha256": FROZEN_CANONICAL_DECK_SHA256,
        "linux_engine_sha256": FROZEN_LINUX_ENGINE_SHA256,
    }
    if any(str(frozen.get(key, "")).upper() != value for key, value in exact.items()):
        raise GateError("package manifest does not bind all frozen d842 identities")
    return manifest


def verify_host_engine() -> dict[str, Any]:
    linux = ROOT / "vendor/cg/libcg.so"
    windows = ROOT / "vendor/cg/cg.dll"
    if sha256_file(linux) != FROZEN_LINUX_ENGINE_SHA256:
        raise GateError("local evaluation bundle has the wrong Linux engine")
    if sha256_file(windows) != FROZEN_WINDOWS_ENGINE_SHA256:
        raise GateError("local evaluation bundle has the wrong Windows engine")
    return {
        "linux_engine_sha256": FROZEN_LINUX_ENGINE_SHA256,
        "windows_engine_sha256": FROZEN_WINDOWS_ENGINE_SHA256,
        "evaluation_platform": platform.system().lower(),
    }


def run_evaluation(
    *,
    candidate_archive: Path,
    package_manifest_path: Path,
    retention_sources: Mapping[str, Path],
    output_path: Path,
    direct_games: int = 10_000,
    retention_games: int = 2_000,
    workers: int = max(1, (mp.cpu_count() or 2) - 1),
    seed: int = 2026080901,
    max_decisions: int = 2_000,
    runner: Callable[[tuple], tuple[str, int, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    package_manifest = validate_package_manifest(package_manifest_path, candidate_archive)
    engine = verify_host_engine()
    if sha256_file(DEFAULT_REFERENCE) != FROZEN_ARCHIVE_SHA256:
        raise GateError("local evaluation control is not the byte-exact d842 archive")
    if set(retention_sources) != set(DEFAULT_RETENTION):
        # The paths are configurable; the mandatory five opponent identities
        # are not.  This prevents a convenient subset from certifying retention.
        raise GateError(
            "retention configuration must contain exactly: " + ", ".join(sorted(DEFAULT_RETENTION))
        )
    if len(set(retention_sources.values())) != len(retention_sources):
        raise GateError("retention opponents must resolve from distinct sources")
    with tempfile.TemporaryDirectory(prefix="grim-correction-evaluation-") as temporary:
        workspace = Path(temporary)
        candidate = _materialize_submission(candidate_archive, workspace / "candidate")
        control = _materialize_submission(DEFAULT_REFERENCE, workspace / "control")
        # Recheck both extracted hero packages, not only their outer archives.
        if sha256_file(candidate / "policy_weights.npz") != str(
            package_manifest["training_audit"]["selected_run"]["model_sha256"]
        ).upper():
            raise GateError("evaluated candidate contains the wrong model")
        verify_frozen_reference(control)
        opponents = {
            name: _materialize_submission(source, workspace / "opponents" / name)
            for name, source in sorted(retention_sources.items())
        }
        opponent_hashes = {name: sha256_path(path).upper() for name, path in opponents.items()}
        mismatched_opponents = {
            name: {"expected": EXPECTED_RETENTION_TREE_SHA256[name], "actual": observed}
            for name, observed in opponent_hashes.items()
            if observed != EXPECTED_RETENTION_TREE_SHA256[name]
        }
        if mismatched_opponents:
            raise GateError(
                "retention configuration does not contain the frozen authentic packages: "
                + json.dumps(mismatched_opponents, sort_keys=True)
            )
        provenance = {
            "candidate_archive_sha256": sha256_file(candidate_archive),
            "candidate_tree_sha256": sha256_path(candidate).upper(),
            "control_archive_sha256": sha256_file(DEFAULT_REFERENCE),
            "control_tree_sha256": sha256_path(control).upper(),
            "opponent_tree_sha256": opponent_hashes,
            **engine,
        }
        schedule, metadata = build_evaluation_schedule(
            candidate=candidate,
            control=control,
            retention=opponents,
            direct_games=direct_games,
            retention_games=retention_games,
            seed=seed,
            max_decisions=max_decisions,
        )
        raw = execute_schedule(schedule, workers=workers, runner=runner)
        expected_cells = set(metadata)
        if set(raw) != expected_cells:
            raise GateError("evaluation did not return every scheduled cell")
        summaries = {}
        outcome_cells = {}
        for cell in sorted(metadata):
            summaries[cell], outcome_cells[cell] = _summarize_cell(raw[cell], metadata[cell])

    direct = direct_strength_gate(summaries["direct:first"], summaries["direct:second"])
    retention_summary: dict[str, dict[str, dict[str, Any]]] = {}
    retention_outcomes: dict[str, dict[str, dict[str, dict[int, int]]]] = {}
    for name in sorted(retention_sources):
        retention_summary[name] = {"candidate": {}, "control": {}}
        retention_outcomes[name] = {"candidate": {}, "control": {}}
        for order in ("first", "second"):
            for arm in ("candidate", "control"):
                cell = f"retention:{name}:{order}:{arm}"
                retention_summary[name][arm][order] = summaries[cell]
                retention_outcomes[name][arm][order] = outcome_cells[cell]
    retention_result = retention_gate(retention_summary, retention_outcomes)
    qualified = direct["passed"] and retention_result["passed"]
    result = {
        "schema_version": 1,
        "status": "qualified" if qualified else "rejected",
        "qualified": qualified,
        "configuration": {
            "direct_games": direct_games,
            "direct_games_per_order": direct_games // 2,
            "retention_games_per_opponent_per_arm": retention_games,
            "retention_games_per_order_per_arm": retention_games // 2,
            "retention_opponents": sorted(retention_sources),
            "seed": seed,
            "max_decisions": max_decisions,
            "forced_actual_orders": ["first", "second"],
        },
        "provenance": {
            **provenance,
            "package_manifest_sha256": sha256_file(package_manifest_path),
        },
        "gates": {"direct_strength": direct, "retention": retention_result},
        "deployment": {"uploaded": False, "azure_started": False},
    }
    write_immutable_json(output_path, result)
    return result


def _retention_arguments(values: Sequence[str] | None) -> dict[str, Path]:
    if not values:
        return dict(DEFAULT_RETENTION)
    result = {}
    for value in values:
        if "=" not in value:
            raise GateError(f"retention value must be NAME=PATH: {value!r}")
        name, raw_path = value.split("=", 1)
        if not re.fullmatch(r"[a-z0-9_]+", name):
            raise GateError(f"invalid retention opponent name: {name!r}")
        if name in result:
            raise GateError(f"duplicate retention opponent: {name}")
        result[name] = Path(raw_path).resolve()
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="hash-verify and deterministically package a trained model")
    build.add_argument("--candidate-model", type=Path, required=True)
    build.add_argument("--training-manifest", type=Path, required=True)
    build.add_argument("--anchor-migration-manifest", type=Path, default=DEFAULT_MIGRATION_AUDIT)
    build.add_argument("--output-dir", type=Path, default=ROOT / "artifacts/grim_correction_candidate")
    build.add_argument("--linux-smoke-report", type=Path)
    build.add_argument("--allow-pending-linux-smoke", action="store_true")

    smoke = subparsers.add_parser("linux-smoke", help="run the bound raw-source smoke under Linux")
    smoke.add_argument("--archive", type=Path, required=True)
    smoke.add_argument("--games", type=int, default=4)
    smoke.add_argument("--output", type=Path, required=True)

    evaluate = subparsers.add_parser("evaluate", help="run local package-vs-package promotion gates")
    evaluate.add_argument("--candidate-archive", type=Path, required=True)
    evaluate.add_argument("--package-manifest", type=Path, required=True)
    evaluate.add_argument(
        "--retention", action="append",
        help="NAME=PATH; repeat for the mandatory five names (paths may be archives or directories)",
    )
    evaluate.add_argument("--direct-games", type=int, default=10_000)
    evaluate.add_argument("--retention-games", type=int, default=2_000)
    evaluate.add_argument("--workers", type=int, default=max(1, (mp.cpu_count() or 2) - 1))
    evaluate.add_argument("--seed", type=int, default=2026080901)
    evaluate.add_argument("--max-decisions", type=int, default=2_000)
    evaluate.add_argument("--output", type=Path, default=ROOT / "artifacts/grim_correction_candidate/promotion_manifest.json")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "build":
            result = build_candidate(
                candidate_model=args.candidate_model.resolve(),
                training_manifest=args.training_manifest.resolve(),
                migration_manifest=args.anchor_migration_manifest.resolve(),
                output_dir=args.output_dir.resolve(),
                linux_smoke_report=args.linux_smoke_report.resolve() if args.linux_smoke_report else None,
                allow_pending_linux_smoke=args.allow_pending_linux_smoke,
            )
        elif args.command == "linux-smoke":
            result = smoke_archive(args.archive.resolve(), games=args.games, require_linux=True)
            result = verify_linux_smoke_report(result, args.archive.resolve(), result["model_sha256"])
            write_immutable_json(args.output.resolve(), result)
        else:
            result = run_evaluation(
                candidate_archive=args.candidate_archive.resolve(),
                package_manifest_path=args.package_manifest.resolve(),
                retention_sources=_retention_arguments(args.retention),
                output_path=args.output.resolve(),
                direct_games=args.direct_games,
                retention_games=args.retention_games,
                workers=args.workers,
                seed=args.seed,
                max_decisions=args.max_decisions,
            )
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
        if args.command == "evaluate" and not result["qualified"]:
            return 3
        if args.command == "build" and not result["qualified_for_evaluation"]:
            return 2
        return 0
    except (GateError, FileNotFoundError, ValueError) as exc:
        print(json.dumps({"status": "failed_closed", "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

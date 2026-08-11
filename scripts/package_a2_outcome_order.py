#!/usr/bin/env python3
"""Package two schema-2 outcome-PPO policies on the pinned A2 shield runtime.

This command only builds and verifies a local deterministic archive.  It does
not run games, upload a submission, or start remote resources.  The original
``policy_weights.npz`` remains byte-exact A2 and is the router's fail-closed
policy.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import package_a2_finalist as a2


DEFAULT_OUTPUT_DIR = ROOT / "artifacts" / "emergency_strength_sprint" / "a2_outcome_ppo" / "package"
ROUTER_SOURCE = ROOT / "ptcg_ai" / "a2_outcome_order_router.py"
ADDED_MEMBERS = frozenset(
    {
        "policy_first.npz",
        "policy_second.npz",
        "ptcg_ai/a2_outcome_order_router.py",
    }
)


def _main_source() -> str:
    return '''"""A2 outcome-PPO actual-order entry point."""

import os
os.environ["PTCG_TEMP"] = "0"
os.environ["PTCG_SEARCH"] = "0"
os.environ["PTCG_TACTICAL_SHIELD"] = "1"

from ptcg_ai.a2_outcome_order_router import OutcomeOrderAgent

_AGENT = OutcomeOrderAgent()

def agent(obs_dict: dict) -> list[int]:
    return _AGENT(obs_dict)
'''


def require_schema2(path: Path) -> dict[str, Any]:
    metadata = a2.validate_model(path)
    if metadata["model_schema_version"] != 2:
        raise a2.PackageError(f"outcome-PPO order model must use schema 2: {path}")
    return metadata


def stage_package(
    source_archive: Path,
    first_model: Path,
    second_model: Path,
    destination: Path,
) -> dict[str, Any]:
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise a2.PackageError(f"outcome order stage must be empty: {destination}")
    a2.safe_extract(source_archive, destination)
    source = a2.verify_source_runtime(destination)
    before = dict(source["file_sha256"])
    first = require_schema2(first_model)
    second = require_schema2(second_model)

    shutil.copyfile(first_model, destination / "policy_first.npz")
    shutil.copyfile(second_model, destination / "policy_second.npz")
    router_target = destination / "ptcg_ai" / "a2_outcome_order_router.py"
    shutil.copyfile(ROUTER_SOURCE, router_target)
    (destination / "main.py").write_text(_main_source(), encoding="utf-8", newline="\n")

    packaged_first = require_schema2(destination / "policy_first.npz")
    packaged_second = require_schema2(destination / "policy_second.npz")
    if packaged_first["sha256"] != first["sha256"] or packaged_second["sha256"] != second["sha256"]:
        raise a2.PackageError("outcome policy copy hash mismatch")
    if a2.sha256_file(destination / a2.MODEL_MEMBER) != a2.FROZEN_SOURCE_MODEL_SHA256:
        raise a2.PackageError("authentic A2 fail-closed model changed")
    if a2.sha256_file(destination / "deck.csv") != a2.FROZEN_RAW_DECK_SHA256:
        raise a2.PackageError("authentic A2 deck changed")

    after = a2.package_file_hashes(destination)
    expected_members = set(before) | set(ADDED_MEMBERS)
    if set(after) != expected_members:
        raise a2.PackageError(
            "unexpected runtime member change: "
            f"missing={sorted(expected_members - set(after))}, extra={sorted(set(after) - expected_members)}"
        )
    altered_source_members = sorted(name for name in before if before[name] != after[name])
    if altered_source_members != ["main.py"]:
        raise a2.PackageError(f"unexpected authentic A2 source changes: {altered_source_members}")
    for name, digest in before.items():
        if name != "main.py" and after[name] != digest:
            raise a2.PackageError(f"authentic A2 member changed: {name}")

    runtime_tree, runtime_files = a2.runtime_source_tree_sha256(destination)
    return {
        "source": source,
        "first_model": first,
        "second_model": second,
        "package_file_sha256": after,
        "package_tree_sha256": a2.package_tree_sha256(destination),
        "runtime_source_tree_sha256": runtime_tree,
        "runtime_source_files": runtime_files,
        "entrypoint_sha256": a2.sha256_file(destination / "main.py"),
        "router_sha256": a2.sha256_file(router_target),
        "altered_source_members": altered_source_members,
        "added_members": sorted(ADDED_MEMBERS),
    }


def sterile_smoke(archive: Path, first_sha256: str, second_sha256: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="a2-outcome-order-smoke-") as directory:
        stage = Path(directory)
        a2.safe_extract(archive, stage)
        code = f'''
import hashlib
import json
import os
import pathlib
import sys
sys.path.insert(0, {str(stage)!r})
namespace = {{"__name__": "submission_entry"}}
source = pathlib.Path("main.py").read_text(encoding="utf-8")
exec(compile(source, "main.py", "exec"), namespace)
agent = namespace["_AGENT"]
deck = namespace["agent"]({{"select": None, "current": None, "logs": []}})
digest = lambda name: hashlib.sha256(pathlib.Path(name).read_bytes()).hexdigest().upper()
assert type(agent).__name__ == "OutcomeOrderAgent"
assert len(deck) == 60 and len(agent.deck) == 60
assert agent.actual_order is None
assert int(agent.exact.policy.model.feature_version) == 2
assert int(agent.policy_first.policy.model.feature_version) == 2
assert int(agent.policy_second.policy.model.feature_version) == 2
assert digest("policy_weights.npz") == {a2.FROZEN_SOURCE_MODEL_SHA256!r}
assert digest("policy_first.npz") == {first_sha256!r}
assert digest("policy_second.npz") == {second_sha256!r}
controls = {{key: os.environ.get(key) for key in {sorted(a2.RUNTIME_CONTROLS)!r}}}
assert controls == {dict(sorted(a2.RUNTIME_CONTROLS.items()))!r}
print(json.dumps({{
    "deck_card_count": len(deck),
    "router": type(agent).__name__,
    "exact_schema": 2,
    "first_schema": 2,
    "second_schema": 2,
    "runtime_controls": controls,
}}))
'''
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        for key in a2.BEHAVIOR_ENV_KEYS:
            environment.pop(key, None)
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", code],
            cwd=stage,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode:
            raise a2.PackageError(
                "sterile A2 outcome order smoke failed: "
                + (result.stderr.strip() or result.stdout.strip())
            )
        try:
            payload = json.loads(result.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise a2.PackageError(f"malformed outcome order smoke output: {result.stdout!r}") from exc
        cache_free = not any(a2._is_cache_name(path.relative_to(stage).parts) for path in stage.rglob("*"))
        if not cache_free:
            raise a2.PackageError("sterile outcome order smoke generated cache files")
        return {
            "passed": True,
            "isolated_python": True,
            "bytecode_disabled": True,
            "cache_free_after_smoke": True,
            **payload,
        }


def build_package(
    *,
    first_model: str | Path,
    second_model: str | Path,
    name: str = "a2_outcome_ppo_order_router",
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    source_archive: str | Path = a2.DEFAULT_SOURCE_ARCHIVE,
) -> dict[str, Any]:
    first_path = Path(first_model).resolve()
    second_path = Path(second_model).resolve()
    source_path = Path(source_archive).resolve()
    output_path = Path(output_dir).resolve()
    package_name = a2._validate_name(name)
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    source_hash = a2.sha256_file(source_path)
    if source_hash != a2.FROZEN_SOURCE_ARCHIVE_SHA256:
        raise a2.PackageError(
            "pinned authentic A2 source archive mismatch: "
            f"expected {a2.FROZEN_SOURCE_ARCHIVE_SHA256}, got {source_hash}"
        )
    first = require_schema2(first_path)
    second = require_schema2(second_path)
    output_path.mkdir(parents=True, exist_ok=True)
    archive_path = output_path / f"{package_name}.tar.gz"
    manifest_path = output_path / f"{package_name}.manifest.json"
    protected = {source_path, first_path, second_path}
    if archive_path.resolve() in protected or manifest_path.resolve() in protected:
        raise a2.PackageError("output would overwrite an input")

    with tempfile.TemporaryDirectory(prefix=f"a2-outcome-order-{package_name}-", dir=output_path) as directory:
        work = Path(directory)
        stages = [work / "first", work / "second"]
        metadata = [stage_package(source_path, first_path, second_path, stage) for stage in stages]
        if metadata[0] != metadata[1]:
            raise a2.PackageError("fresh A2 outcome order stages differ")
        archives = [work / "first.tar.gz", work / "second.tar.gz"]
        for stage, archive in zip(stages, archives):
            a2.deterministic_tar(stage, archive)
        archive_hashes = [a2.sha256_file(archive) for archive in archives]
        if archive_hashes[0] != archive_hashes[1]:
            raise a2.PackageError(f"outcome order package is not deterministic: {archive_hashes}")
        smoke = sterile_smoke(archives[0], first["sha256"], second["sha256"])
        meta = metadata[0]
        with tempfile.TemporaryDirectory(prefix="a2-outcome-order-verify-", dir=work) as verify_directory:
            verified_stage = Path(verify_directory)
            a2.safe_extract(archives[0], verified_stage)
            if a2.package_file_hashes(verified_stage) != meta["package_file_sha256"]:
                raise a2.PackageError("archive extraction changed package files")
            if a2.package_tree_sha256(verified_stage) != meta["package_tree_sha256"]:
                raise a2.PackageError("archive extraction changed package tree")

        staged_archive = work / "final.tar.gz"
        shutil.copyfile(archives[0], staged_archive)
        manifest = {
            "schema_version": 1,
            "status": "packaged_unverified_by_gameplay",
            "label": package_name,
            "source_runtime": {
                "archive": str(source_path),
                "archive_sha256": a2.FROZEN_SOURCE_ARCHIVE_SHA256,
                "extracted_tree_sha256": meta["source"]["extracted_tree_sha256"],
                "fallback_model_sha256": a2.FROZEN_SOURCE_MODEL_SHA256,
                "deck": meta["source"]["deck"],
            },
            "models": {
                "first": {"input": str(first_path), "role": "actual-first outcome-PPO", **first},
                "second": {"input": str(second_path), "role": "actual-second outcome-PPO", **second},
            },
            "routing": {
                "order_source": "latched current.firstPlayer compared with current.yourIndex",
                "pre_latch_policy": "byte-exact authentic A2",
                "candidate_failure_fallback": "byte-exact authentic A2",
                "runtime_controls": dict(a2.RUNTIME_CONTROLS),
                "temperature": 0,
                "native_search": False,
                "tactical_shield": True,
                "entrypoint_sha256": meta["entrypoint_sha256"],
                "router_sha256": meta["router_sha256"],
                "runtime_source_tree_sha256": meta["runtime_source_tree_sha256"],
                "altered_source_members": meta["altered_source_members"],
                "added_members": meta["added_members"],
            },
            "output": {
                "archive": str(archive_path),
                "archive_sha256": archive_hashes[0],
                "archive_bytes": staged_archive.stat().st_size,
                "extracted_tree_sha256": meta["package_tree_sha256"],
            },
            "verification": {
                "fresh_stage_count": 2,
                "deterministic_tar": True,
                "first_archive_sha256": archive_hashes[0],
                "second_archive_sha256": archive_hashes[1],
                "safe_archive_extraction": True,
                "cache_free_package": True,
                "authentic_a2_fallback_preserved": True,
                "authentic_a2_deck_preserved": True,
                "sterile_init_smoke": smoke,
            },
            "deployment": {
                "games_run": False,
                "gameplay_promoted": False,
                "uploaded": False,
                "cloud_started": False,
            },
        }
        staged_manifest = work / "final.manifest.json"
        staged_manifest.write_text(
            json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(staged_archive, archive_path)
        os.replace(staged_manifest, manifest_path)
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first-model", type=Path, required=True)
    parser.add_argument("--second-model", type=Path, required=True)
    parser.add_argument("--name", default="a2_outcome_ppo_order_router")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--source-archive", type=Path, default=a2.DEFAULT_SOURCE_ARCHIVE)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = build_package(
            first_model=args.first_model,
            second_model=args.second_model,
            name=args.name,
            output_dir=args.output_dir,
            source_archive=args.source_archive,
        )
    except (a2.PackageError, FileNotFoundError, OSError) as exc:
        print(json.dumps({"status": "failed_closed", "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Package an outcome-grounded categorical A2/temporal router."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import package_a2_finalist as a2


DEFAULT_A2_SCHEMA3 = ROOT / "artifacts/emergency_strength_sprint/temporal_elite_schema3/a2_schema3_zero_init.npz"
DEFAULT_TEMPORAL = ROOT / "artifacts/elite_policy_candidates/temporal_continue_lr25/policy_weights.npz"
ROUTER_SOURCE = ROOT / "ptcg_ai/empirical_policy_router.py"
SEMANTIC_SOURCE = ROOT / "ptcg_ai/temporal_context_gate.py"


def main_source() -> str:
    return '''"""Outcome-grounded categorical router on the authentic A2 runtime."""

import os
os.environ["PTCG_TEMP"] = "0"
os.environ["PTCG_SEARCH"] = "0"
os.environ["PTCG_TACTICAL_SHIELD"] = "1"

from ptcg_ai.empirical_policy_router import EmpiricalPolicyRouterAgent

_AGENT = EmpiricalPolicyRouterAgent()

def agent(obs_dict: dict) -> list[int]:
    return _AGENT(obs_dict)
'''


def validate_config(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if int(value.get("schema_version", 0)) != 1:
        raise a2.PackageError("unsupported empirical router schema")
    if value.get("actual_order") not in {"first", "second", "both"}:
        raise a2.PackageError("invalid actual_order")
    routes = value.get("temporal_routes")
    allowed = {"context", "a2_option_type", "temporal_option_type"}
    if not isinstance(routes, list) or not routes:
        raise a2.PackageError("temporal_routes must be non-empty")
    for route in routes:
        if not isinstance(route, dict) or not route or set(route) - allowed:
            raise a2.PackageError(f"invalid route: {route!r}")
        if any(not isinstance(cell, int) or cell < 0 for cell in route.values()):
            raise a2.PackageError(f"invalid route value: {route!r}")
    return value


def smoke(archive: Path, expected: dict[str, str]) -> dict:
    with tempfile.TemporaryDirectory(prefix="empirical-router-smoke-") as directory:
        stage = Path(directory)
        a2.safe_extract(archive, stage)
        code = f'''
import hashlib, json, pathlib, sys
sys.path.insert(0, {str(stage)!r})
namespace = {{"__name__": "submission_entry"}}
exec(compile(pathlib.Path("main.py").read_text(encoding="utf-8"), "main.py", "exec"), namespace)
agent = namespace["_AGENT"]
deck = namespace["agent"]({{"select": None, "current": None, "logs": []}})
digest = lambda name: hashlib.sha256(pathlib.Path(name).read_bytes()).hexdigest().upper()
assert len(deck) == 60
assert type(agent).__name__ == "EmpiricalPolicyRouterAgent"
assert digest("policy_a2_schema3.npz") == {expected['a2']!r}
assert digest("policy_continuation.npz") == {expected['temporal']!r}
assert digest("empirical_router.json") == {expected['config']!r}
print(json.dumps({{"agent": type(agent).__name__, "deck_cards": len(deck), "routes": len(agent.routes), "actual_order": agent.actual_order}}))
'''
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", code],
            cwd=stage,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode:
            raise a2.PackageError(result.stderr.strip() or result.stdout.strip())
        return json.loads(result.stdout.strip().splitlines()[-1])


def build(
    source: Path,
    a2_model: Path,
    temporal_model: Path,
    config: Path,
    output: Path,
    evidence: list[Path],
) -> dict:
    for path in (source, a2_model, temporal_model, config, ROUTER_SOURCE, SEMANTIC_SOURCE, *evidence):
        if not path.is_file():
            raise FileNotFoundError(path)
    if a2.sha256_file(source) != a2.FROZEN_SOURCE_ARCHIVE_SHA256:
        raise a2.PackageError("source is not authentic A2 shield")
    config_value = validate_config(config)
    a2_info = a2.validate_model(a2_model)
    temporal_info = a2.validate_model(temporal_model)
    if a2_info["model_schema_version"] != 3 or temporal_info["model_schema_version"] != 3:
        raise a2.PackageError("router requires two schema-3 models")
    output.mkdir(parents=True, exist_ok=False)
    extracted = output / "extracted"
    archive = output / "empirical_policy_router.tar.gz"
    with tempfile.TemporaryDirectory(prefix="empirical-router-stage-", dir=output) as directory:
        stage = Path(directory) / "stage"
        a2.safe_extract(source, stage)
        source_audit = a2.verify_source_runtime(stage)
        shutil.copyfile(a2_model, stage / "policy_a2_schema3.npz")
        shutil.copyfile(temporal_model, stage / "policy_continuation.npz")
        shutil.copyfile(config, stage / "empirical_router.json")
        shutil.copyfile(ROUTER_SOURCE, stage / "ptcg_ai/empirical_policy_router.py")
        shutil.copyfile(SEMANTIC_SOURCE, stage / "ptcg_ai/temporal_context_gate.py")
        (stage / "main.py").write_text(main_source(), encoding="utf-8", newline="\n")
        if a2.sha256_file(stage / "deck.csv") != a2.FROZEN_RAW_DECK_SHA256:
            raise a2.PackageError("deck changed")
        a2.deterministic_tar(stage, archive)
        shutil.copytree(stage, extracted)
    expected = {
        "a2": a2.sha256_file(a2_model),
        "temporal": a2.sha256_file(temporal_model),
        "config": a2.sha256_file(config),
    }
    result = {
        "schema_version": 1,
        "status": "packaged_pending_gameplay",
        "source_archive_sha256": a2.sha256_file(source),
        "source_runtime_tree_sha256": source_audit["runtime_source_tree_sha256"],
        "config": config_value,
        "config_sha256": expected["config"],
        "a2_model_sha256": expected["a2"],
        "temporal_model_sha256": expected["temporal"],
        "runtime_private_information": False,
        "archive": str(archive.resolve()),
        "archive_sha256": a2.sha256_file(archive),
        "extracted": str(extracted.resolve()),
        "tree_sha256": a2.package_tree_sha256(extracted),
        "evidence": [
            {"path": str(path.resolve()), "sha256": a2.sha256_file(path)} for path in evidence
        ],
        "smoke": smoke(archive, expected),
        "uploaded": False,
    }
    (output / "manifest.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=a2.DEFAULT_SOURCE_ARCHIVE)
    parser.add_argument("--a2-model", type=Path, default=DEFAULT_A2_SCHEMA3)
    parser.add_argument("--temporal-model", type=Path, default=DEFAULT_TEMPORAL)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, action="append", default=[])
    args = parser.parse_args()
    result = build(args.source, args.a2_model, args.temporal_model, args.config, args.output, args.evidence)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

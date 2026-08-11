#!/usr/bin/env python3
"""Package the frozen learned A2/temporal context gate; never upload it."""

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
DEFAULT_CONTINUATION = ROOT / "artifacts/elite_policy_candidates/temporal_continue_lr25/policy_weights.npz"
DEFAULT_GATE = ROOT / "artifacts/elite_policy_candidates/temporal_context_gate_screen/context_gate_weights.npz"
DEFAULT_GATE_MANIFEST = ROOT / "artifacts/elite_policy_candidates/temporal_context_gate_screen/context_gate_weights.manifest.json"
DEFAULT_SCREEN = ROOT / "artifacts/elite_policy_candidates/temporal_context_gate_screen/report.json"
DEFAULT_OUTPUT = ROOT / "artifacts/elite_policy_candidates/temporal_context_gate_screen/package"
RUNTIME_SOURCE = ROOT / "ptcg_ai/temporal_context_gate.py"


def main_source() -> str:
    return '''"""Learned public-state gate on the authentic A2 shield runtime."""

import os
os.environ["PTCG_TEMP"] = "0"
os.environ["PTCG_SEARCH"] = "0"
os.environ["PTCG_TACTICAL_SHIELD"] = "1"

from ptcg_ai.temporal_context_gate import TemporalContextGateAgent

_AGENT = TemporalContextGateAgent()

def agent(obs_dict: dict) -> list[int]:
    return _AGENT(obs_dict)
'''


def validate_gate(path: Path) -> dict:
    import numpy as np

    expected = {
        "coef": (858,), "bias": (), "mean": (858,), "std": (858,),
        "threshold": (), "schema_version": (),
    }
    with np.load(path, allow_pickle=False) as arrays:
        if set(arrays.files) != set(expected):
            raise a2.PackageError(f"gate arrays changed: {sorted(arrays.files)}")
        shapes = {name: tuple(arrays[name].shape) for name in arrays.files}
        if shapes != expected:
            raise a2.PackageError(f"gate shapes changed: {shapes}")
        for name in arrays.files:
            if not np.issubdtype(arrays[name].dtype, np.number) or not np.all(np.isfinite(arrays[name])):
                raise a2.PackageError(f"gate array is not finite numeric: {name}")
        if int(arrays["schema_version"].item()) != 1 or float(arrays["threshold"].item()) != 0.5:
            raise a2.PackageError("gate schema or threshold changed")
        if np.any(arrays["std"] <= 0.0):
            raise a2.PackageError("gate normalization contains nonpositive scale")
    return {"sha256": a2.sha256_file(path), "bytes": path.stat().st_size, "array_shapes": shapes}


def stage_package(
    source_archive: Path,
    a2_schema3: Path,
    continuation: Path,
    gate: Path,
    destination: Path,
) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise a2.PackageError(f"context-gate stage must be empty: {destination}")
    a2.safe_extract(source_archive, destination)
    source = a2.verify_source_runtime(destination)
    a2_model = a2.validate_model(a2_schema3)
    continuation_model = a2.validate_model(continuation)
    gate_model = validate_gate(gate)
    if a2_model["model_schema_version"] != 3 or continuation_model["model_schema_version"] != 3:
        raise a2.PackageError("context gate requires two schema-3 policies")
    shutil.copyfile(a2_schema3, destination / "policy_a2_schema3.npz")
    shutil.copyfile(continuation, destination / "policy_continuation.npz")
    shutil.copyfile(gate, destination / "context_gate_weights.npz")
    shutil.copyfile(RUNTIME_SOURCE, destination / "ptcg_ai/temporal_context_gate.py")
    (destination / "main.py").write_text(main_source(), encoding="utf-8", newline="\n")
    if a2.sha256_file(destination / "policy_weights.npz") != a2.FROZEN_SOURCE_MODEL_SHA256:
        raise a2.PackageError("authentic schema-2 A2 fallback changed")
    if a2.sha256_file(destination / "deck.csv") != a2.FROZEN_RAW_DECK_SHA256:
        raise a2.PackageError("authentic A2 deck changed")
    copies = {
        "policy_a2_schema3.npz": a2_model["sha256"],
        "policy_continuation.npz": continuation_model["sha256"],
        "context_gate_weights.npz": gate_model["sha256"],
    }
    for name, expected in copies.items():
        if a2.sha256_file(destination / name) != expected:
            raise a2.PackageError(f"copy hash mismatch: {name}")
    runtime_tree, runtime_files = a2.runtime_source_tree_sha256(destination)
    return {
        "source": source,
        "a2_schema3": a2_model,
        "continuation": continuation_model,
        "gate": gate_model,
        "package_tree_sha256": a2.package_tree_sha256(destination),
        "package_file_sha256": a2.package_file_hashes(destination),
        "runtime_source_tree_sha256": runtime_tree,
        "runtime_source_files": runtime_files,
        "entrypoint_sha256": a2.sha256_file(destination / "main.py"),
        "router_sha256": a2.sha256_file(destination / "ptcg_ai/temporal_context_gate.py"),
    }


def sterile_smoke(archive: Path, identities: dict[str, str]) -> dict:
    with tempfile.TemporaryDirectory(prefix="temporal-context-gate-smoke-") as directory:
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
assert type(agent).__name__ == "TemporalContextGateAgent"
assert int(agent.exact.policy.model.feature_version) == 3
assert int(agent.continuation.policy.model.feature_version) == 3
assert agent.gate.coef.shape == (858,)
assert digest("policy_a2_schema3.npz") == {identities["a2"]!r}
assert digest("policy_continuation.npz") == {identities["continuation"]!r}
assert digest("context_gate_weights.npz") == {identities["gate"]!r}
print(json.dumps({{"deck_card_count": len(deck), "agent": type(agent).__name__, "feature_count": 858}}))
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
            raise a2.PackageError(result.stderr.strip() or result.stdout.strip())
        return json.loads(result.stdout.strip().splitlines()[-1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-archive", type=Path, default=a2.DEFAULT_SOURCE_ARCHIVE)
    parser.add_argument("--a2-schema3", type=Path, default=DEFAULT_A2_SCHEMA3)
    parser.add_argument("--continuation", type=Path, default=DEFAULT_CONTINUATION)
    parser.add_argument("--gate", type=Path, default=DEFAULT_GATE)
    parser.add_argument("--gate-manifest", type=Path, default=DEFAULT_GATE_MANIFEST)
    parser.add_argument("--screen-report", type=Path, default=DEFAULT_SCREEN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    for path in (
        args.source_archive, args.a2_schema3, args.continuation, args.gate,
        args.gate_manifest, args.screen_report, RUNTIME_SOURCE,
    ):
        if not path.is_file():
            raise a2.PackageError(f"missing input: {path}")
    if args.output.exists() and any(args.output.iterdir()):
        raise a2.PackageError(f"output must not already contain files: {args.output}")
    args.output.mkdir(parents=True, exist_ok=True)
    extracted = args.output / "extracted"
    stage = stage_package(
        args.source_archive, args.a2_schema3, args.continuation, args.gate, extracted
    )
    archive = args.output / "a2_temporal_context_gate.tar.gz"
    a2.deterministic_tar(extracted, archive)
    identities = {
        "a2": stage["a2_schema3"]["sha256"],
        "continuation": stage["continuation"]["sha256"],
        "gate": stage["gate"]["sha256"],
    }
    smoke = sterile_smoke(archive, identities)
    screen = json.loads(args.screen_report.read_text(encoding="utf-8"))
    manifest = {
        "schema_version": 1,
        "kind": "a2_temporal_context_gate_candidate",
        "status": "packaged_pending_fresh_deterministic_gameplay",
        "selection_frozen_before_gameplay": True,
        "routing_scope": "single-action semantic disagreements only; exact A2 otherwise and on failure",
        "runtime_controls": dict(a2.RUNTIME_CONTROLS),
        "source_archive": {"path": str(args.source_archive), "sha256": a2.sha256_file(args.source_archive)},
        "screen_report": {"path": str(args.screen_report), "sha256": a2.sha256_file(args.screen_report)},
        "gate_manifest": {"path": str(args.gate_manifest), "sha256": a2.sha256_file(args.gate_manifest)},
        "selected_candidate": screen["selected_candidate"],
        "stage": stage,
        "archive": {"path": str(archive), "sha256": a2.sha256_file(archive), "bytes": archive.stat().st_size},
        "sterile_smoke": smoke,
        "uploaded": False,
    }
    manifest_path = args.output / "a2_temporal_context_gate.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "extracted": str(extracted.resolve()),
        "archive": str(archive.resolve()),
        "archive_sha256": manifest["archive"]["sha256"],
        "package_tree_sha256": stage["package_tree_sha256"],
        "manifest": str(manifest_path.resolve()),
        "smoke": smoke,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

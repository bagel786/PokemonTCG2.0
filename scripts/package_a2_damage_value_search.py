#!/usr/bin/env python3
"""Package the late-game value-search screen on the authentic A2 runtime."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.package_a2_finalist import (  # noqa: E402
    FROZEN_RAW_DECK_SHA256,
    FROZEN_SOURCE_ARCHIVE_SHA256,
    MODEL_MEMBER,
    PackageError,
    deterministic_tar,
    package_file_hashes,
    package_tree_sha256,
    safe_extract,
    sha256_file,
    validate_model,
    verify_source_runtime,
)


DEFAULT_SOURCE = ROOT / "artifacts" / "recovery_probes" / "a2_v2_shield.tar.gz"
DEFAULT_MODEL = ROOT / "artifacts" / "elite_policy_candidates" / "a2_order_public_value" / "policy_weights.npz"
DEFAULT_OUTPUT = ROOT / "artifacts" / "elite_policy_candidates" / "a2_order_public_value_search"
RUNTIME_FILES = (
    "ptcg_ai/archetypes.py",
    "ptcg_ai/damage_value_search.py",
    "ptcg_ai/search.py",
)
OLD_IMPORT = "            from .model import NeuralPolicy\n\n            self.policy = NeuralPolicy(model_path, fallback)"
NEW_IMPORT = (
    "            from .damage_value_search import DamageValueSearchPolicy\n\n"
    "            self.policy = DamageValueSearchPolicy(\n"
    "                model_path, fallback, self.deck, min_turn=6, timeout_ms=250.0\n"
    "            )"
)


def _value_only_change(base: Path, candidate: Path) -> list[str]:
    with np.load(base, allow_pickle=False) as old, np.load(candidate, allow_pickle=False) as new:
        if set(old.files) != set(new.files):
            raise PackageError("candidate model array set differs from authentic A2")
        changed = sorted(name for name in old.files if not np.array_equal(old[name], new[name]))
    if set(changed) != {"value_b", "value_w"}:
        raise PackageError(f"expected a value-only model change, got {changed}")
    return changed


def _patch_agent(stage: Path) -> None:
    path = stage / "ptcg_ai" / "agent.py"
    source = path.read_text(encoding="utf-8")
    if source.count(OLD_IMPORT) != 1:
        raise PackageError("authentic A2 agent hook did not match exactly once")
    path.write_text(source.replace(OLD_IMPORT, NEW_IMPORT), encoding="utf-8", newline="\n")


def _smoke(stage: Path, expected_model_hash: str) -> dict:
    code = f'''
import json
import pathlib
import sys
sys.path.insert(0, {str(stage)!r})
namespace = {{"__name__": "submission_entry"}}
exec(compile(pathlib.Path("main.py").read_text(encoding="utf-8"), "main.py", "exec"), namespace)
agent = namespace["_AGENT"]
deck = namespace["agent"]({{"select": None, "current": None, "logs": []}})
assert type(agent.policy).__name__ == "DamageValueSearchPolicy"
assert type(agent.policy.base).__name__ == "NeuralPolicy"
assert agent.policy.min_turn == 6
assert agent.policy.search.timeout_ms == 250.0
assert len(deck) == len(agent.deck) == 60
print(json.dumps({{"policy": type(agent.policy).__name__, "min_turn": agent.policy.min_turn, "timeout_ms": agent.policy.search.timeout_ms, "deck_cards": len(deck)}}))
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
        raise PackageError(result.stderr.strip() or result.stdout.strip() or "sterile smoke failed")
    if sha256_file(stage / MODEL_MEMBER) != expected_model_hash:
        raise PackageError("smoke stage model hash mismatch")
    return json.loads(result.stdout.strip().splitlines()[-1])


def build(source: Path, model: Path, output: Path) -> dict:
    source = source.resolve()
    model = model.resolve()
    output = output.resolve()
    if sha256_file(source) != FROZEN_SOURCE_ARCHIVE_SHA256:
        raise PackageError("source is not the hash-pinned authentic A2 shield archive")
    candidate = validate_model(model)
    output.mkdir(parents=True, exist_ok=True)
    submission = output / "submission"
    archive = output / "submission.tar.gz"
    manifest_path = output / "package_manifest.json"
    if submission.exists() or archive.exists() or manifest_path.exists():
        raise PackageError(f"output already exists: {output}")

    with tempfile.TemporaryDirectory(prefix="a2-damage-search-", dir=output) as directory:
        stage = Path(directory) / "stage"
        safe_extract(source, stage)
        source_audit = verify_source_runtime(stage)
        changed_arrays = _value_only_change(stage / MODEL_MEMBER, model)
        shutil.copyfile(model, stage / MODEL_MEMBER)
        for relative in RUNTIME_FILES:
            source_file = ROOT / relative
            if not source_file.is_file():
                raise FileNotFoundError(source_file)
            shutil.copyfile(source_file, stage / relative)
        _patch_agent(stage)
        if sha256_file(stage / "deck.csv") != FROZEN_RAW_DECK_SHA256:
            raise PackageError("deck changed while staging value search")
        smoke = _smoke(stage, candidate["sha256"])
        deterministic_tar(stage, archive)
        shutil.copytree(stage, submission)

    runtime_hashes = package_file_hashes(submission)
    manifest = {
        "schema_version": 1,
        "status": "screen_only",
        "source_archive": str(source),
        "source_archive_sha256": FROZEN_SOURCE_ARCHIVE_SHA256,
        "source_runtime_tree_sha256": source_audit["runtime_source_tree_sha256"],
        "candidate_model": str(model),
        "candidate_model_sha256": candidate["sha256"],
        "changed_model_arrays": changed_arrays,
        "policy_arrays_frozen": True,
        "runtime": {
            "base": "authentic_a2_tactical_shield",
            "search_scope": "turn>=6 fixed-count damage/heal targets with public Grim-line evidence",
            "general_one_ply_enabled": False,
            "candidate_evaluation": "one frozen determinization; independent fresh native root per candidate",
            "nonterminal_opponent_to_act": "reject search attempt and preserve shielded A2 action",
            "min_turn": 6,
            "max_candidates": 3,
            "ambiguity_margin": 0.35,
            "timeout_ms": 250.0,
            "exact_deck_assumption": "uses the submitted Grim deck as opponent determinization after public Grim-line evidence; variants remain a caveat",
            "added_files": list(RUNTIME_FILES),
            "patched_files": ["ptcg_ai/agent.py"],
        },
        "output": {
            "submission": str(submission),
            "archive": str(archive),
            "archive_sha256": sha256_file(archive),
            "tree_sha256": package_tree_sha256(submission),
            "file_sha256": runtime_hashes,
        },
        "verification": {
            "sterile_init": smoke,
            "deck_unchanged": True,
            "value_only_model_change": True,
        },
        "deployment": {"games_run": False, "uploaded": False},
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        result = build(args.source, args.model, args.output)
    except (FileNotFoundError, OSError, PackageError, ValueError) as exc:
        print(json.dumps({"status": "failed_closed", "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

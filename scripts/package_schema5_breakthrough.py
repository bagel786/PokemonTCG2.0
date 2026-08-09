#!/usr/bin/env python3
"""Build a deterministic, fail-closed M0 or D1 Kaggle package."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
R0_ROOT = ROOT / "artifacts" / "recovery_r0_package" / "extracted" / "r0_play_binding"
R0_ARCHIVE_SHA256 = "AC0E9B174AE99911AD9E04F82E912E43AB7E9FFA130D297C04FEDCF34247058B"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(bytes.fromhex(sha256(path)))
    return digest.hexdigest().upper()


def deterministic_tar(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    with destination.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for path in sorted(p for p in source.rglob("*") if p.is_file()):
                    info = archive.gettarinfo(str(path), arcname=path.relative_to(source).as_posix())
                    info.mtime = info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    with path.open("rb") as handle:
                        archive.addfile(info, handle)


def validate(stage: Path, mode: str, model_hash: str) -> dict:
    code = f"""
import json, os, time
os.environ['PTCG_SEARCH']='0'
import main
deck=main.agent({{'select':None,'logs':[],'current':None}})
assert len(deck)==60
agent=main._AGENT
assert agent.errors==0
assert {'agent.mirror_specialist is not None and not hasattr(agent.policy, "model")' if mode == 'm0' else 'hasattr(agent.policy, "model")'}
policy=agent.mirror_specialist if {mode == 'm0'} else agent.policy
assert policy.model_sha256.upper() == '{model_hash}'
print(json.dumps({{'deck_cards':len(deck),'model_loaded':True,'policy_errors':agent.errors}}))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(stage)
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=stage, env=env,
        text=True, capture_output=True, timeout=120,
    )
    if result.returncode:
        raise RuntimeError(f"sterile validation failed:\n{result.stdout}\n{result.stderr}")
    return json.loads(result.stdout.strip().splitlines()[-1])


def package(mode: str, model: Path, output: Path, runtime: Path | None) -> dict:
    if mode not in {"m0", "d1"}:
        raise ValueError(mode)
    if not model.is_file():
        raise FileNotFoundError(model)
    if not R0_ROOT.is_dir():
        raise FileNotFoundError(R0_ROOT)
    r0_archive = R0_ROOT.parent.parent / "r0_play_binding.tar.gz"
    if not r0_archive.is_file() or sha256(r0_archive) != R0_ARCHIVE_SHA256:
        raise RuntimeError("R0 control archive is missing or hash-mismatched")
    model_hash = sha256(model)
    with tempfile.TemporaryDirectory(prefix=f"ptcg-{mode}-") as temporary:
        stage = Path(temporary) / "agent"
        shutil.copytree(R0_ROOT, stage, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.rmtree(stage / "ptcg_ai")
        shutil.copytree(ROOT / "ptcg_ai", stage / "ptcg_ai", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for stale in ("direct_policy.npz", "mirror_direct.npz", "direct_runtime.json"):
            (stage / stale).unlink(missing_ok=True)
        destination = stage / ("mirror_direct.npz" if mode == "m0" else "direct_policy.npz")
        shutil.copy2(model, destination)
        if runtime is not None:
            if mode != "d1":
                raise RuntimeError("runtime gating is only valid for D1")
            payload = json.loads(runtime.read_text(encoding="utf-8"))
            if str(payload.get("model_sha256", "")).upper() != model_hash:
                raise RuntimeError("direct runtime manifest model hash mismatch")
            shutil.copy2(runtime, stage / "direct_runtime.json")
        validation = validate(stage, mode, model_hash)
        deterministic_tar(stage, output)
        staged_hash = tree_sha256(stage)
    manifest = {
        "status": "packaged_not_promoted",
        "mode": mode,
        "created_unix": time.time(),
        "source_model": str(model.resolve()),
        "model_sha256": model_hash,
        "archive": str(output.resolve()),
        "archive_sha256": sha256(output),
        "archive_size_bytes": output.stat().st_size,
        "r0_archive_sha256": R0_ARCHIVE_SHA256,
        "source_tree_sha256": tree_sha256(ROOT / "ptcg_ai"),
        "staged_tree_sha256": staged_hash,
        "runtime_manifest": str(runtime.resolve()) if runtime else None,
        "sterile_local_validation": validation,
    }
    manifest_path = output.with_suffix(output.suffix + ".json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("m0", "d1"), required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = package(args.mode, args.model, args.output, args.runtime)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

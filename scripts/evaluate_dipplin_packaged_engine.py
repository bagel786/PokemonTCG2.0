#!/usr/bin/env python3
"""Run the Dipplin evaluator with an extracted package's native engine.

The normal repository evaluator intentionally imports ``vendor/cg``.  Release
gating instead needs to prove that the Linux binary shipped in the candidate
archive can execute complete games.  Preloading the package copy here also
ensures spawned evaluator workers inherit the same ``cg`` module contract.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import multiprocessing as mp
import os
import sys
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
ENGINE_ROOT_ENV = "PTCG_PACKAGED_ENGINE_ROOT"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def preload_packaged_engine(engine_root: str | Path) -> ModuleType:
    """Load, or validate an already loaded, candidate Linux engine."""

    root = Path(engine_root).resolve()
    expected = (root / "cg/libcg.so").resolve()
    if not expected.is_file():
        raise RuntimeError(f"packaged Linux engine is missing: {expected}")

    loaded = sys.modules.get("cg.sim")
    if loaded is not None:
        actual = Path(str(getattr(loaded, "lib_path", ""))).resolve()
        if actual != expected:
            raise RuntimeError(
                f"wrong native engine loaded: expected {expected}, received {actual}"
            )
        return loaded

    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(root))
    loaded = importlib.import_module("cg.sim")
    actual = Path(str(getattr(loaded, "lib_path", ""))).resolve()
    if actual != expected:
        raise RuntimeError(
            f"wrong native engine loaded: expected {expected}, received {actual}"
        )
    return loaded


def engine_report() -> dict[str, str | int]:
    loaded = sys.modules.get("cg.sim")
    if loaded is None:
        raise RuntimeError("cg.sim has not been preloaded")
    path = Path(str(getattr(loaded, "lib_path", ""))).resolve()
    return {
        "pid": os.getpid(),
        "path": str(path),
        "sha256": _sha256(path),
    }


def _spawned_engine_report(_: int) -> dict[str, str | int]:
    return engine_report()


def spawn_smoke(worker_count: int = 2) -> dict[str, object]:
    """Prove spawned interpreters preload the same candidate engine."""

    parent = engine_report()
    context = mp.get_context("spawn")
    with context.Pool(worker_count) as pool:
        workers = pool.map(_spawned_engine_report, range(worker_count))
    for worker in workers:
        if worker["path"] != parent["path"] or worker["sha256"] != parent["sha256"]:
            raise RuntimeError(f"spawned worker engine mismatch: {worker!r}")
    return {"parent": parent, "workers": workers}


_configured_engine_root = os.environ.get(ENGINE_ROOT_ENV)
if _configured_engine_root:
    try:
        preload_packaged_engine(_configured_engine_root)
    except RuntimeError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    if not _configured_engine_root:
        raise SystemExit(f"{ENGINE_ROOT_ENV} must name a freshly extracted package")
    if sys.argv[1:] == ["--engine-spawn-smoke"]:
        print(json.dumps(spawn_smoke(), sort_keys=True))
        raise SystemExit(0)

    from scripts.evaluate_dipplin import main

    raise SystemExit(main())

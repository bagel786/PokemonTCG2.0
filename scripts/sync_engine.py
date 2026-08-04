#!/usr/bin/env python3
"""Download the current official sample-submission cg package and record hashes."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "vendor" / "cg"
REMOTE_ROOT = "sample_submission/sample_submission/cg"
FILES = [
    "__init__.py",
    "api.py",
    "game.py",
    "sim.py",
    "utils.py",
    "cg.dll",
    "libcg-arm64.so",
    "libcg.dylib",
    "libcg.so",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    for filename in FILES:
        subprocess.run(
            [
                "kaggle", "competitions", "download", "pokemon-tcg-ai-battle",
                "-f", f"{REMOTE_ROOT}/{filename}", "-p", str(TARGET), "-o", "-q",
            ],
            check=True,
        )
    manifest = {
        "competition": "pokemon-tcg-ai-battle",
        "remote_root": REMOTE_ROOT,
        "files": {
            filename: {"bytes": (TARGET / filename).stat().st_size, "sha256": sha256(TARGET / filename)}
            for filename in FILES
        },
    }
    (TARGET / "engine_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


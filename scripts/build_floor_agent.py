#!/usr/bin/env python3
"""Build a deterministic exact-deck A2 package with floor-preserving rails."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_wave1_agents import (
    BASE,
    BASE_SHA256,
    MODEL_SHA256,
    OUTPUT,
    deterministic_tar,
    entrypoint,
    patch_model,
    safe_extract,
    sha256,
    sterile_validate,
)

MODE = "floor"


def stage(destination: Path) -> dict:
    safe_extract(BASE, destination)
    if sha256(destination / "policy_weights.npz") != MODEL_SHA256:
        raise RuntimeError("A2 model hash mismatch")
    patch_model(destination)
    shutil.copy2(ROOT / "ptcg_ai/wave1_rails.py", destination / "ptcg_ai/wave1_rails.py")
    shutil.copy2(ROOT / "ptcg_ai/card_ids.py", destination / "ptcg_ai/card_ids.py")
    deck_path = destination / "deck.csv"
    cards = [int(line) for line in deck_path.read_text().splitlines() if line.strip()]
    if len(cards) != 60:
        raise RuntimeError("A2 base deck is not 60 cards")
    deck_sha = sha256(deck_path)
    (destination / "main.py").write_text(entrypoint(MODE, deck_sha), encoding="utf-8")
    metadata = {
        "label": "GRIM_FLOOR_RECOVERY_V1",
        "mode": MODE,
        "base_archive_sha256": BASE_SHA256,
        "model_sha256": MODEL_SHA256,
        "deck_sha256": deck_sha,
        "deck_multiset": dict(sorted(Counter(cards).items())),
        "temperature": 0,
        "search": False,
        "tactical_shield": True,
        "fallback": "A2",
        "rails": [
            "turn1_setup_search",
            "turn2_turn3_conversion",
            "punk_up",
            "munk_damage_source",
            "shadow_bullet_over_end",
        ],
    }
    (destination / "floor_manifest.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return metadata


def main() -> int:
    if sha256(BASE) != BASE_SHA256:
        raise SystemExit("pinned A2 archive hash mismatch")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    archive = OUTPUT / "grim_floor_v1.tar.gz"
    extracted = OUTPUT / "extracted_floor_v1"
    if extracted.exists():
        shutil.rmtree(extracted)
    with tempfile.TemporaryDirectory(prefix="grim-floor-v1-", dir=OUTPUT) as directory:
        work = Path(directory)
        first, second = work / "first", work / "second"
        first.mkdir()
        second.mkdir()
        metadata = stage(first)
        stage(second)
        a, b = work / "a.tar.gz", work / "b.tar.gz"
        deterministic_tar(first, a)
        deterministic_tar(second, b)
        if sha256(a) != sha256(b):
            raise RuntimeError("floor package is not deterministic")
        shutil.copy2(a, archive)
        shutil.copytree(first, extracted)
    result = {
        **metadata,
        "archive": str(archive.resolve()),
        "archive_sha256": sha256(archive),
        "archive_bytes": archive.stat().st_size,
        "deterministic_double_build": True,
        "sterile_validation": sterile_validate(archive, MODE),
    }
    target = OUTPUT / "floor_build_manifest.json"
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

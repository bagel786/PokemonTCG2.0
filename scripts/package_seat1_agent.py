#!/usr/bin/env python3
"""Package and self-test candidate_seat1_boosted into a submission archive."""

import hashlib
import json
import shutil
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG_DIR = ROOT / "artifacts" / "seat1_data" / "pkg_tmp"
OUT_TAR = ROOT / "artifacts" / "seat1_data" / "submission_seat1_boosted.tar.gz"
MODEL_PATH = ROOT / "artifacts" / "seat1_data" / "candidate_seat1_boosted.npz"
DECK_PATH = ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv"

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()

def main():
    if PKG_DIR.exists():
        shutil.rmtree(PKG_DIR)
    PKG_DIR.mkdir(parents=True, exist_ok=True)

    print("Copying package dependencies...")
    shutil.copytree(ROOT / "vendor" / "cg", PKG_DIR / "cg")
    shutil.copytree(ROOT / "ptcg_ai", PKG_DIR / "ptcg_ai")
    shutil.copy2(MODEL_PATH, PKG_DIR / "policy_weights.npz")
    shutil.copy2(DECK_PATH, PKG_DIR / "deck.csv")

    main_py = '"""Kaggle submission entry point."""\n\nfrom ptcg_ai import CompetitionAgent\n\n_AGENT = CompetitionAgent()\n\n\ndef agent(obs_dict: dict) -> list[int]:\n    return _AGENT(obs_dict)\n'
    (PKG_DIR / "main.py").write_text(main_py, encoding="utf-8")

    print(f"Building tar archive at {OUT_TAR}...")
    with tarfile.open(OUT_TAR, "w:gz") as tar:
        for item in PKG_DIR.iterdir():
            tar.add(item, arcname=item.name)

    tar_sha = sha256_file(OUT_TAR)
    model_sha = sha256_file(MODEL_PATH)
    deck_sha = sha256_file(DECK_PATH)

    manifest = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "archive": str(OUT_TAR),
        "archive_sha256": tar_sha,
        "model_sha256": model_sha,
        "deck_sha256": deck_sha,
        "size_bytes": OUT_TAR.stat().st_size,
    }
    (ROOT / "artifacts" / "seat1_data" / "submission_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Archive successfully created: {OUT_TAR.name} ({OUT_TAR.stat().st_size / (1024*1024):.2f} MB, SHA256: {tar_sha[:12]}...)")

    # Clean up temp dir
    shutil.rmtree(PKG_DIR)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

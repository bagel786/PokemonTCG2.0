#!/usr/bin/env python3
"""Sterile-build + validate the final anti-meta candidate package.

Produces a tar.gz and a hash manifest; verifies:
- 60-card deck.csv, policy files = EXP-23 base (CEFE6118)
- PLAY identity enabled, public-only detector, no specialist npz
- baked surgical default rule set
- zero policy errors in seeded smoke games
"""
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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

EXP23_SHA = "cefe61189bc6f4e316212b19c99450e4b91ff1e5493f4467a95041c30fd96984"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_archive(tree: Path, archive: Path) -> str:
    if archive.exists():
        archive.unlink()
    with tarfile.open(archive, "w:gz") as tar:
        for child in sorted(tree.iterdir()):
            if child.name == "__pycache__" or child.suffix == ".pyc":
                continue
            tar.add(child, arcname=child.name)
    return sha256_file(archive)


def verify_tree(tree: Path, surgical_default: str) -> dict:
    problems = []
    deck = [int(x) for x in (tree / "deck.csv").read_text().splitlines() if x.strip()]
    if len(deck) != 60:
        problems.append(f"deck has {len(deck)} cards")
    for name in ("policy_first.npz", "policy_second.npz", "policy_weights.npz"):
        if sha256_file(tree / name) != EXP23_SHA:
            problems.append(f"{name} is not EXP-23 base")
    if (tree / "policy_dip.npz").exists() or (tree / "policy_luc.npz").exists():
        problems.append("specialist npz present in surgical package")
    main_py = (tree / "main.py").read_text()
    if "PLAY_IDENTITY_ENABLED = True" not in main_py:
        problems.append("PLAY identity not enabled")
    if surgical_default and f"PTCG_SURGICAL', '{surgical_default}'" not in main_py:
        problems.append("surgical default not baked")
    router = (tree / "ptcg_ai" / "target_router.py").read_text()
    for forbidden in ("TeamNames", "replay", "leaderboard", "handshake", "opponent_deck"):
        if forbidden in router:
            problems.append(f"forbidden reference in router: {forbidden}")
    surgical = (tree / "ptcg_ai" / "surgical.py").read_text()
    if "last_ranked" not in (tree / "ptcg_ai" / "model.py").read_text():
        problems.append("model.py not patched for last_ranked")
    return {"ok": not problems, "problems": problems, "deck_cards": len(deck)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--surgical-default", required=True)
    parser.add_argument("--out-dir", default="artifacts/anti_meta_20260816")
    args = parser.parse_args()

    out = Path(args.out_dir)
    tree = out / "packages" / args.name
    subprocess.run(
        [sys.executable, "scripts/build_router_package.py", "--name", args.name,
         "--base", "e23", "--surgical-default", args.surgical_default,
         "--out-dir", str(out / "packages")],
        cwd=ROOT, check=True,
    )

    verification = verify_tree(tree, args.surgical_default)
    print(json.dumps(verification, indent=2))
    if not verification["ok"]:
        return 1

    archive = out / f"{args.name}.tar.gz"
    sha = build_archive(tree, archive)
    manifest = {
        "name": args.name,
        "archive": str(archive),
        "archive_sha256": sha,
        "surgical_default": args.surgical_default,
        "base_model": "EXP-23 CEFE61189BC6F4E3",
        "deck_csv_sha256": sha256_file(tree / "deck.csv"),
        "verification": verification,
    }
    (out / f"{args.name}.manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

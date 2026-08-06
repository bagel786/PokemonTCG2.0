#!/usr/bin/env python3
"""Package the Master Loss-Buckets Agent into a clean Kaggle submission tarball."""

import os
import shutil
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "freshstart" / "submission_template"
WEIGHTS_PATH = ROOT / "artifacts" / "loss_buckets_model" / "master_loss_buckets_policy.npz"
STAGING_DIR = ROOT / "artifacts" / "submission_staging_master"
TAR_PATH = ROOT / "artifacts" / "submission_master_v1.tar.gz"

def main():
    if not WEIGHTS_PATH.exists():
        print(f"Error: Weights file {WEIGHTS_PATH} not found.")
        return 1

    if STAGING_DIR.exists():
        shutil.rmtree(STAGING_DIR)
    STAGING_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Staging template files from {TEMPLATE_DIR}...")
    for item in TEMPLATE_DIR.iterdir():
        if item.is_file():
            shutil.copy2(item, STAGING_DIR / item.name)
        elif item.is_dir():
            shutil.copytree(item, STAGING_DIR / item.name)

    target_weights = STAGING_DIR / "weights.npz"
    print(f"Copying master policy weights to {target_weights}...")
    shutil.copy2(WEIGHTS_PATH, target_weights)

    print(f"Creating submission tarball at {TAR_PATH}...")
    if TAR_PATH.exists():
        TAR_PATH.unlink()

    with tarfile.open(TAR_PATH, "w:gz") as tar:
        for file_path in STAGING_DIR.rglob("*"):
            if file_path.is_file():
                arcname = file_path.relative_to(STAGING_DIR).as_posix()
                tar.add(file_path, arcname=arcname)

    size_mb = TAR_PATH.stat().st_size / (1024 * 1024)
    print(f"Successfully packaged {TAR_PATH.name} ({size_mb:.2f} MB)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

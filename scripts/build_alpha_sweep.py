#!/usr/bin/env python3
"""Build W(alpha) = A2 + alpha*(EXP23 - A2) policy packages for the sweep."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
A2_TREE = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/grim_damage_conversion/winner/extracted")
E23_TREE = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/final_sprint/exp23_identity_trained")
OUT = ROOT / "artifacts" / "global_swing_20260816" / "packages"
MODELS = ("policy_weights.npz", "policy_first.npz", "policy_second.npz")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_alpha(alpha: float) -> Path:
    dst = OUT / f"exp23_alpha_{str(alpha).replace('.', 'p')}"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(E23_TREE, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in MODELS:
        a2 = np.load(A2_TREE / name)
        e23 = np.load(E23_TREE / name)
        assert set(a2.keys()) == set(e23.keys()), name
        blended = {}
        for key in a2.keys():
            x, y = a2[key], e23[key]
            assert x.shape == y.shape and x.dtype == y.dtype, (name, key)
            blended[key] = x + alpha * (y - x)
        np.savez(dst / name, **blended)
    return dst


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--alphas", default="0.60,0.75,0.875,0.95,1.0")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {"base_a2": {}, "base_exp23": {}, "alphas": {}}
    for name in MODELS:
        manifest["base_a2"][name] = sha256_file(A2_TREE / name)
        manifest["base_exp23"][name] = sha256_file(E23_TREE / name)
    for token in args.alphas.split(","):
        alpha = float(token)
        tree = build_alpha(alpha)
        hashes = {name: sha256_file(tree / name) for name in MODELS}
        manifest["alphas"][str(alpha)] = {"tree": str(tree), "model_hashes": hashes}
        print(alpha, hashes)
    (OUT / "sweep_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

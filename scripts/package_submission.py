#!/usr/bin/env python3
"""Build and audit a Kaggle-ready tar.gz without modifying source directories."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_single_package(
    deck_name: str,
    model_path: Path | None,
    prior_path: Path | None,
    archive_name: str,
    output_dir: Path,
    specialist_model_path: Path | None = None,
) -> dict:
    deck = ROOT / "decks" / f"{deck_name}.csv"
    if not deck.exists():
        raise FileNotFoundError(f"deck not found: {deck}")
    if model_path is not None and not model_path.exists():
        raise FileNotFoundError(model_path)
    if prior_path is not None and not prior_path.exists():
        raise FileNotFoundError(prior_path)
    if specialist_model_path is not None and not specialist_model_path.exists():
        raise FileNotFoundError(specialist_model_path)

    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"{archive_name}.tar.gz"

    with tempfile.TemporaryDirectory(prefix="ptcg-package-") as temporary:
        stage = Path(temporary)
        shutil.copy2(ROOT / "submission" / "main.py", stage / "main.py")
        shutil.copy2(deck, stage / "deck.csv")
        shutil.copytree(
            ROOT / "ptcg_ai",
            stage / "ptcg_ai",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
        )
        engine_source = ROOT / "vendor" / "cg"
        if not engine_source.exists():
            raise RuntimeError("current official engine is not synced; run python scripts/sync_engine.py")
        shutil.copytree(
            engine_source,
            stage / "cg",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", "engine_manifest.json"),
        )
        if model_path is not None:
            shutil.copy2(model_path, stage / "policy_weights.npz")
        if prior_path is not None:
            shutil.copy2(prior_path, stage / "elite_prior.json")
        if specialist_model_path is not None:
            shutil.copy2(specialist_model_path, stage / "lucario_specialist.npz")
        with tarfile.open(archive, "w:gz") as bundle:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    bundle.add(path, arcname=path.relative_to(stage))

    with tarfile.open(archive, "r:gz") as bundle:
        members = {member.name for member in bundle.getmembers() if member.isfile()}
    required = {"main.py", "deck.csv", "ptcg_ai/agent.py", "cg/api.py", "cg/libcg.so"}
    missing = required - members
    if missing:
        raise RuntimeError(f"archive is missing required members: {sorted(missing)}")
    size_limit = int(197.7 * 1024 * 1024)
    if archive.stat().st_size > size_limit:
        raise RuntimeError(f"archive exceeds Kaggle limit: {archive.stat().st_size}")
    manifest = {
        "archive": str(archive),
        "bytes": archive.stat().st_size,
        "sha256": sha256(archive),
        "deck": deck_name,
        "deck_sha256": sha256(deck),
        "model": str(model_path) if model_path else "heuristic",
        "model_sha256": sha256(model_path) if model_path else None,
        "prior": str(prior_path) if prior_path else None,
        "prior_sha256": sha256(prior_path) if prior_path else None,
        "specialist_model": str(specialist_model_path) if specialist_model_path else None,
        "specialist_model_sha256": sha256(specialist_model_path) if specialist_model_path else None,
        "engine_linux_sha256": sha256(ROOT / "vendor" / "cg" / "libcg.so"),
        "members": len(members),
    }
    manifest_path = archive.with_suffix(archive.suffix + ".json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deck", choices=("grimmsnarl", "garchomp"), required=True)
    parser.add_argument("--model", help="optional promoted .npz model")
    parser.add_argument("--prior", help="optional replay-derived fallback JSON")
    parser.add_argument("--specialist-model", help="optional routed Lucario specialist .npz")
    parser.add_argument("--name", help="archive basename")
    parser.add_argument("--output-dir", default="artifacts")
    parser.add_argument(
        "--paired-control",
        action="store_true",
        help="Rule 3: also package the 5k reference control arm for paired Kaggle active queue deployment",
    )
    parser.add_argument(
        "--control-model",
        default="artifacts/overnight_grim_20260730/grim_selected.npz",
        help="path to 5k control baseline model",
    )
    args = parser.parse_args()

    output_dir = ROOT / args.output_dir
    model = Path(args.model).resolve() if args.model else None
    prior = Path(args.prior).resolve() if args.prior else None
    specialist_model = Path(args.specialist_model).resolve() if args.specialist_model else None
    name = args.name or f"{args.deck}-cleanroom"

    challenger_manifest = build_single_package(
        deck_name=args.deck,
        model_path=model,
        prior_path=prior,
        archive_name=name,
        output_dir=output_dir,
        specialist_model_path=specialist_model,
    )
    print("Challenger package generated:")
    print(json.dumps(challenger_manifest, indent=2))

    if args.paired_control:
        control_model_path = Path(args.control_model).resolve() if args.control_model else None
        control_manifest = build_single_package(
            deck_name="grimmsnarl",
            model_path=control_model_path,
            prior_path=prior,
            archive_name=f"grimmsnarl-5k-control-baseline",
            output_dir=output_dir,
            specialist_model_path=None,
        )
        print("\nRule 3 Paired Control package generated:")
        print(json.dumps(control_manifest, indent=2))
        print(
            "\n[IMPORTANT Rule 3] Submit both archives together so they occupy Kaggle's 2 active matchmaking slots."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

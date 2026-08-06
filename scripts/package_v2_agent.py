#!/usr/bin/env python3
"""Package Pokémon TCG AI v2 agent into a validated, standalone Kaggle tarball."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / "artifacts" / "v2_model" / "policy_weights.npz"
DEFAULT_DECK = ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv"
DEFAULT_OUT_TAR = ROOT / "artifacts" / "submission_v2_candidate.tar.gz"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def package_v2(
    model_path: Path = DEFAULT_MODEL,
    deck_path: Path = DEFAULT_DECK,
    output_tar: Path = DEFAULT_OUT_TAR,
) -> Path:
    if not model_path.exists():
        # Fallback to test run if main model is still training
        alt = ROOT / "artifacts" / "v2_test_run" / "policy_weights.npz"
        if alt.exists():
            model_path = alt
        else:
            raise FileNotFoundError(f"Model weights not found at {model_path}")

    if not deck_path.exists():
        raise FileNotFoundError(f"Deck file not found at {deck_path}")

    output_tar.parent.mkdir(parents=True, exist_ok=True)
    if output_tar.exists():
        output_tar.unlink()

    print(f"Building v2 submission bundle...")
    print(f"  Model: {model_path} ({sha256(model_path)[:10]}...)")
    print(f"  Deck:  {deck_path}")

    with tempfile.TemporaryDirectory(prefix="ptcg-v2-pkg-") as tmp:
        stage = Path(tmp)

        # 1. Copy main.py
        shutil.copy2(ROOT / "submission" / "main.py", stage / "main.py")

        # 2. Copy deck.csv
        shutil.copy2(deck_path, stage / "deck.csv")

        # 3. Copy ptcg_ai package
        shutil.copytree(
            ROOT / "ptcg_ai",
            stage / "ptcg_ai",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
        )

        # 4. Copy cg vendor engine
        shutil.copytree(
            ROOT / "vendor" / "cg",
            stage / "cg",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", "engine_manifest.json"),
        )

        # 5. Copy weights and priors
        shutil.copy2(model_path, stage / "policy_weights.npz")
        prior_file = ROOT / "freshstart" / "submission_template" / "elite_prior.json"
        if prior_file.exists():
            shutil.copy2(prior_file, stage / "elite_prior.json")

        # 6. Bundle tar.gz
        with tarfile.open(output_tar, "w:gz") as tar:
            for item in sorted(stage.rglob("*")):
                if item.is_file():
                    tar.add(item, arcname=item.relative_to(stage))

    size_mb = output_tar.stat().st_size / (1024 * 1024)
    print(f"Successfully packaged {output_tar.name} ({size_mb:.2f} MB)")

    # 7. Sandbox Verification
    print(f"Running sandbox verification on packaged tarball...")
    with tempfile.TemporaryDirectory(prefix="ptcg-v2-verify-") as test_dir:
        test_stage = Path(test_dir)
        with tarfile.open(output_tar, "r:gz") as tar:
            tar.extractall(test_stage)

        # Test agent initialization, deck submission, and archetype lookahead loading
        verification_script = (
            "import main\n"
            "deck = main.agent({'select': None, 'logs': [], 'current': None})\n"
            "assert len(deck) == 60, f'Bad deck len: {len(deck)}'\n"
            "from ptcg_ai.search import ArchetypeRegistry\n"
            "reg = ArchetypeRegistry()\n"
            "assert len(reg.archetypes) >= 10, f'Archetype registry empty or incomplete: {len(reg.archetypes)}'\n"
            "og_match, _, og_j = reg.match({96, 1})\n"
            "assert og_match == 'ogerpon', f'Failed to match Ogerpon archetype: {og_match}'\n"
            "gar_match, _, gar_j = reg.match({649, 2})\n"
            "assert gar_match == 'garchomp', f'Failed to match Garchomp archetype: {gar_match}'\n"
            "print(f'Sandbox verification passed: agent initialized, deck returned, {len(reg.archetypes)} archetypes active in Kaggle sandbox.')\n"
        )
        test_cmd = [sys.executable, "-c", verification_script]
        env = os.environ.copy()
        env["PYTHONPATH"] = f"{test_stage};{env.get('PYTHONPATH', '')}"

        res = subprocess.run(test_cmd, capture_output=True, text=True, cwd=str(test_stage), env=env)
        if res.returncode != 0:
            print(f"Sandbox test stderr: {res.stderr}")
            raise RuntimeError("Sandbox verification failed!")
        print(f"  {res.stdout.strip()}")

    manifest = {
        "tarball": str(output_tar),
        "size_bytes": output_tar.stat().st_size,
        "sha256": sha256(output_tar),
        "model_sha256": sha256(model_path),
        "deck_sha256": sha256(deck_path),
    }
    output_tar.with_suffix(output_tar.suffix + ".json").write_text(json.dumps(manifest, indent=2))
    print(f"Exported bundle manifest to {output_tar.name}.json")
    return output_tar


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=str(DEFAULT_MODEL), help="Model weights npz")
    parser.add_argument("--deck", default=str(DEFAULT_DECK), help="Deck CSV")
    parser.add_argument("--out", default=str(DEFAULT_OUT_TAR), help="Output tarball path")
    args = parser.parse_args()

    package_v2(
        model_path=Path(args.model),
        deck_path=Path(args.deck),
        output_tar=Path(args.out),
    )


if __name__ == "__main__":
    main()

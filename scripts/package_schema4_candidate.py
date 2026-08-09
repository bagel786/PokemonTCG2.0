#!/usr/bin/env python3
"""Build a deterministic schema-4 ensemble package and extracted test stage."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_recovery_probes import deterministic_tar, safe_extract, sha256, sterile_validate
from training.evaluation_schema import sha256_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="r1_relational")
    parser.add_argument("--base", default="artifacts/recovery_probes/extracted/a2_base/policy_weights.npz")
    parser.add_argument("--heads", nargs=3, required=True)
    parser.add_argument("--output-root", default="artifacts/recovery_r1_package")
    args = parser.parse_args()
    output_root = ROOT / args.output_root
    archive = output_root / f"{args.name}.tar.gz"
    extracted = output_root / "extracted" / args.name
    with tempfile.TemporaryDirectory(prefix=f"{args.name}-") as directory:
        stage = Path(directory)
        shutil.copytree(ROOT / "ptcg_ai", stage / "ptcg_ai", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copytree(ROOT / "vendor" / "cg", stage / "cg", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copy2(ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv", stage / "deck.csv")
        shutil.copy2(ROOT / args.base, stage / "a2_base.npz")
        head_names = []
        for index, source in enumerate(args.heads):
            name = f"residual_head_{index}.npz"
            shutil.copy2(ROOT / source, stage / name)
            head_names.append(name)
        (stage / "residual_manifest.json").write_text(json.dumps({
            "schema_version": 4,
            "base_model": "a2_base.npz",
            "residual_heads": head_names,
            "policy": "frozen_a2_plus_slot_aware_residual_consensus",
        }, indent=2), encoding="utf-8")
        (stage / "main.py").write_text(
            '"""Deterministic schema-4 Grimmsnarl candidate."""\n\n'
            "import os\n"
            'os.environ["PTCG_TEMP"] = "0"\n'
            'os.environ["PTCG_SEARCH"] = "0"\n'
            'os.environ["PTCG_TACTICAL_SHIELD"] = "1"\n\n'
            "from ptcg_ai import CompetitionAgent\n\n"
            "_AGENT = CompetitionAgent()\n\n"
            "def agent(obs_dict: dict) -> list[int]:\n"
            "    return _AGENT(obs_dict)\n",
            encoding="utf-8",
        )
        tree_hash = sha256_path(stage).upper()
        deterministic_tar(stage, archive)
    if extracted.exists():
        resolved = extracted.resolve()
        if output_root.resolve() not in resolved.parents:
            raise RuntimeError("schema-4 extracted path escaped output root")
        shutil.rmtree(extracted)
    extracted.mkdir(parents=True)
    safe_extract(archive, extracted)
    if sha256_path(extracted).upper() != tree_hash:
        raise RuntimeError("schema-4 package tree changed during archive round trip")
    manifest = {
        "status": "complete",
        "name": args.name,
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "archive": str(archive.resolve()),
        "archive_sha256": sha256(archive),
        "extracted": str(extracted.resolve()),
        "extracted_tree_sha256": tree_hash,
        "base": {"path": str((ROOT / args.base).resolve()), "sha256": sha256(ROOT / args.base)},
        "heads": [{"path": str((ROOT / path).resolve()), "sha256": sha256(ROOT / path)} for path in args.heads],
        "sterile_validation": sterile_validate(archive),
        "deterministic": True,
        "search": False,
        "choose_first": True,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "package_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

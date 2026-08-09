#!/usr/bin/env python3
"""Package all six trained B candidates with the approved tactical shield."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_recovery_probes import build, safe_extract
from training.evaluation_schema import sha256_path


def reset_stage(stage: Path, root: Path) -> None:
    resolved, resolved_root = stage.resolve(), root.resolve()
    if resolved_root not in resolved.parents:
        raise RuntimeError(f"candidate stage is outside output root: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True)


def main() -> int:
    farm_path = ROOT / "artifacts" / "recovery_training_azure" / "training_farm_manifest.json"
    farm = json.loads(farm_path.read_text())
    if farm.get("status") != "complete" or len(farm.get("results", [])) != 6:
        raise RuntimeError("refusing to package an incomplete recovery training farm")
    package_root = ROOT / "artifacts" / "recovery_final" / "candidate_packages"
    extracted_root = ROOT / "artifacts" / "recovery_final" / "candidates"
    package_root.mkdir(parents=True, exist_ok=True)
    extracted_root.mkdir(parents=True, exist_ok=True)
    packages = {}
    for row in sorted(farm["results"], key=lambda value: value["label"]):
        name = row["label"]
        model = Path(row["model"])
        if not model.exists():
            raise FileNotFoundError(model)
        package = build(name, model, package_root)
        if package["model_sha256"].lower() != row["model_sha256"].lower():
            raise RuntimeError(f"packaged model hash differs from training result: {name}")
        stage = extracted_root / name
        reset_stage(stage, extracted_root)
        safe_extract(Path(package["archive"]), stage)
        observed_tree = sha256_path(stage).upper()
        if observed_tree != package["extracted_tree_sha256"]:
            raise RuntimeError(f"candidate extracted-tree hash mismatch: {name}")
        packages[name] = {
            **package,
            "agent": str(stage.resolve()),
            "training_worker": row["worker"],
            "training_report": row["report"],
        }
    manifest = {
        "training_farm_manifest": str(farm_path.resolve()),
        "training_bundle_sha256": farm["bundle_sha256"],
        "candidates": packages,
    }
    output = ROOT / "artifacts" / "recovery_final" / "candidate_manifest.json"
    output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

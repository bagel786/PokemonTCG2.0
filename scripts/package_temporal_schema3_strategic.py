#!/usr/bin/env python3
"""Build the corrected strategic controller over the temporal schema-3 policy."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import tarfile
import tempfile
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = ROOT / "artifacts" / "recovery_probes" / "a2_v2_shield.tar.gz"
DEFAULT_TEMPORAL = (
    ROOT / "artifacts" / "elite_policy_candidates" / "temporal_schema3_full" / "policy_weights.npz"
)
DEFAULT_D842 = ROOT / "artifacts" / "recovery_probes" / "extracted" / "control" / "policy_weights.npz"
DEFAULT_OUTPUT_DIR = ROOT / "artifacts" / "strategic_playbook_temporal_schema3"
DEFAULT_FROZEN_V2 = ROOT / "artifacts" / "strategic_playbook" / "grimmsnarl_strategic_playbook.tar.gz"
EXPECTED_FROZEN_V2_SHA256 = "B604EED897BC772DD890336BD38552E99F663C9163AB3E2B496F1EC063C63A2C"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def sha256_tree(path: Path) -> str:
    """Hash package contents while ignoring transient Python bytecode."""
    digest = hashlib.sha256()
    for child in sorted(
        item
        for item in path.rglob("*")
        if item.is_file() and "__pycache__" not in item.parts and item.suffix != ".pyc"
    ):
        relative = child.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(child)))
    return digest.hexdigest().upper()


def model_schema(path: Path) -> int:
    with np.load(path, allow_pickle=False) as arrays:
        if "model_schema_version" not in arrays.files:
            return 1
        return int(np.asarray(arrays["model_schema_version"]).item())


def require_model_schema(path: Path, expected: int) -> None:
    observed = model_schema(path)
    if observed != expected:
        raise ValueError(f"{path} is schema {observed}, expected schema {expected}")


def safe_extract(archive: Path, destination: Path) -> None:
    root = destination.resolve()
    with tarfile.open(archive, "r:gz") as handle:
        for member in handle.getmembers():
            target = (destination / member.name).resolve()
            if target != root and root not in target.parents:
                raise ValueError(f"unsafe archive member: {member.name}")
            if member.issym() or member.islnk():
                raise ValueError(f"archive links are not allowed: {member.name}")
        handle.extractall(destination)


def deterministic_archive(stage: Path, output: Path) -> None:
    with output.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for path in sorted(item for item in stage.rglob("*") if item.is_file()):
                    if "__pycache__" in path.parts or path.suffix == ".pyc":
                        continue
                    info = archive.gettarinfo(str(path), arcname=path.relative_to(stage).as_posix())
                    info.mtime = 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    with path.open("rb") as handle:
                        archive.addfile(info, handle)


def strategic_config(*, preference_logit_margin: float = 0.75) -> dict:
    return {
        "name": "grimmsnarl_temporal_schema3_corrected_strategic",
        "architecture": "corrected_strategic_controller_over_temporal_schema3",
        "broad_base": "temporal_schema3_full",
        "broad_model_schema_version": 3,
        "fallback": "exact_d842",
        "router_minimum": 0.55,
        "preference_logit_margin": preference_logit_margin,
        "build_logit_margin": 0.20,
        "actual_second_build_logit_margin": 0.60,
        "commit_logit_margin": 0.50,
        "target_commit_logit_margin": 2.0,
        "enable_build_commitments": False,
        "enable_count_overrides": False,
        "enable_one_prize_hypotheses": False,
        "hidden_information": False,
        "search": False,
        "tactical_shield_application_count": 1,
        "sanitizer_application_count": 1,
    }


def _replace_extracted(stage: Path, destination: Path, output_dir: Path) -> None:
    resolved_output = output_dir.resolve()
    resolved_destination = destination.resolve()
    if resolved_destination.parent != resolved_output:
        raise RuntimeError("extracted package must be a direct child of the isolated output directory")
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(stage, destination)


def build_package(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    base: Path = DEFAULT_BASE,
    temporal_model: Path = DEFAULT_TEMPORAL,
    fallback_model: Path = DEFAULT_D842,
    strategic_runtime: Path = ROOT / "ptcg_ai" / "strategic_playbook.py",
    router_runtime: Path = ROOT / "ptcg_ai" / "matchup_playbook.py",
    frozen_v2: Path = DEFAULT_FROZEN_V2,
    preference_logit_margin: float = 0.75,
    enforce_known_frozen_v2: bool = True,
) -> dict:
    """Build an isolated package without mutating the frozen v2 artifact."""
    output_dir = output_dir.resolve()
    base = base.resolve()
    temporal_model = temporal_model.resolve()
    fallback_model = fallback_model.resolve()
    strategic_runtime = strategic_runtime.resolve()
    router_runtime = router_runtime.resolve()
    frozen_v2 = frozen_v2.resolve()

    require_model_schema(temporal_model, 3)
    require_model_schema(fallback_model, 2)
    frozen_before = sha256_file(frozen_v2)
    if enforce_known_frozen_v2 and frozen_before != EXPECTED_FROZEN_V2_SHA256:
        raise RuntimeError(
            "the frozen v2 archive is not the audited original: "
            f"{frozen_before} != {EXPECTED_FROZEN_V2_SHA256}"
        )
    runtime_before = sha256_file(strategic_runtime)
    router_before = sha256_file(router_runtime)
    config = strategic_config(preference_logit_margin=preference_logit_margin)

    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / "grimmsnarl_temporal_schema3_corrected_strategic.tar.gz"
    extracted_path = output_dir / "extracted"
    manifest_path = output_dir / "manifest.json"

    with tempfile.TemporaryDirectory(prefix="schema3-strategic-", dir=output_dir) as temporary_name:
        temporary = Path(temporary_name)
        stage = temporary / "stage"
        stage.mkdir()
        safe_extract(base, stage)

        # The strategic controller loads policy_a2.npz.  Keep the conventional
        # policy_weights.npz alias synchronized so package provenance is unambiguous.
        shutil.copyfile(temporal_model, stage / "policy_a2.npz")
        shutil.copyfile(temporal_model, stage / "policy_weights.npz")
        shutil.copyfile(fallback_model, stage / "policy_d842.npz")
        shutil.copyfile(router_runtime, stage / "ptcg_ai" / "matchup_playbook.py")
        shutil.copyfile(strategic_runtime, stage / "ptcg_ai" / "strategic_playbook.py")
        (stage / "strategic_config.json").write_text(
            json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (stage / "main.py").write_text(
            '"""Corrected strategic controller over the temporal schema-3 policy."""\n\n'
            "from ptcg_ai.strategic_playbook import StrategicPlaybookAgent\n\n"
            "_AGENT = StrategicPlaybookAgent()\n\n"
            "def agent(obs_dict: dict) -> list[int]:\n"
            "    return _AGENT(obs_dict)\n",
            encoding="utf-8",
        )
        staged_runtime_hash = sha256_file(stage / "ptcg_ai" / "strategic_playbook.py")
        staged_router_hash = sha256_file(stage / "ptcg_ai" / "matchup_playbook.py")
        if staged_runtime_hash != runtime_before or staged_router_hash != router_before:
            raise RuntimeError("staged controller source differs from the selected source")
        if sha256_file(stage / "policy_a2.npz") != sha256_file(temporal_model):
            raise RuntimeError("temporal policy copy failed")
        if sha256_file(stage / "policy_weights.npz") != sha256_file(temporal_model):
            raise RuntimeError("conventional temporal policy alias copy failed")

        first = temporary / "first.tar.gz"
        second = temporary / "second.tar.gz"
        deterministic_archive(stage, first)
        deterministic_archive(stage, second)
        first_hash = sha256_file(first)
        if first_hash != sha256_file(second):
            raise RuntimeError("archive build is not deterministic")
        shutil.copyfile(first, archive_path)
        _replace_extracted(stage, extracted_path, output_dir)

    if sha256_file(strategic_runtime) != runtime_before or sha256_file(router_runtime) != router_before:
        raise RuntimeError("controller source changed while the package was being built")
    frozen_after = sha256_file(frozen_v2)
    if frozen_after != frozen_before:
        raise RuntimeError("frozen v2 archive changed while the alternate package was being built")
    deck_lines = [line for line in (extracted_path / "deck.csv").read_text().splitlines() if line.strip()]
    if len(deck_lines) != 60:
        raise RuntimeError(f"packaged deck has {len(deck_lines)} cards, expected 60")

    manifest = {
        "name": config["name"],
        "config": config,
        "archive": str(archive_path),
        "archive_sha256": sha256_file(archive_path),
        "archive_size": archive_path.stat().st_size,
        "extracted": str(extracted_path),
        "extracted_tree_sha256": sha256_tree(extracted_path),
        "deterministic": True,
        "deck_card_count": len(deck_lines),
        "deck_sha256": sha256_file(extracted_path / "deck.csv"),
        "source_artifacts": {
            "authentic_base": {"path": str(base), "sha256": sha256_file(base)},
            "temporal_policy": {
                "path": str(temporal_model),
                "sha256": sha256_file(temporal_model),
                "schema_version": model_schema(temporal_model),
            },
            "fallback_policy": {
                "path": str(fallback_model),
                "sha256": sha256_file(fallback_model),
                "schema_version": model_schema(fallback_model),
            },
            "strategic_runtime": {"path": str(strategic_runtime), "sha256": runtime_before},
            "router_runtime": {"path": str(router_runtime), "sha256": router_before},
            "frozen_v2": {
                "path": str(frozen_v2),
                "sha256_before": frozen_before,
                "sha256_after": frozen_after,
                "preserved": frozen_before == frozen_after,
            },
        },
        "packaged_hashes": {
            "policy_a2": sha256_file(extracted_path / "policy_a2.npz"),
            "policy_weights": sha256_file(extracted_path / "policy_weights.npz"),
            "policy_d842": sha256_file(extracted_path / "policy_d842.npz"),
            "strategic_runtime": sha256_file(extracted_path / "ptcg_ai" / "strategic_playbook.py"),
            "router_runtime": sha256_file(extracted_path / "ptcg_ai" / "matchup_playbook.py"),
            "config": sha256_file(extracted_path / "strategic_config.json"),
            "entrypoint": sha256_file(extracted_path / "main.py"),
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--temporal-model", type=Path, default=DEFAULT_TEMPORAL)
    parser.add_argument("--fallback-model", type=Path, default=DEFAULT_D842)
    parser.add_argument("--frozen-v2", type=Path, default=DEFAULT_FROZEN_V2)
    parser.add_argument("--preference-logit-margin", type=float, default=0.75)
    args = parser.parse_args()
    manifest = build_package(
        output_dir=args.output_dir,
        base=args.base,
        temporal_model=args.temporal_model,
        fallback_model=args.fallback_model,
        frozen_v2=args.frozen_v2,
        preference_logit_margin=args.preference_logit_margin,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

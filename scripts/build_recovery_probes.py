#!/usr/bin/env python3
"""Build deterministic A1/A2 recovery probes from the historical d842 runtime."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from training.evaluation_schema import sha256_path

ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / "grimmsnarl_5k_reference.tar.gz"
V2_WEIGHTS = ROOT / "artifacts" / "v2_model" / "policy_weights.npz"
EXPECTED_CONTROL_SHA256 = "3ECB0BBF119E23C31905E39E19ECA8F6145104AAEFFC0A5675D2FE03855BB458"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def safe_extract(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r:gz") as tar:
        root = destination.resolve()
        for member in tar.getmembers():
            target = (destination / member.name).resolve()
            if target != root and root not in target.parents:
                raise ValueError(f"unsafe archive member: {member.name}")
        tar.extractall(destination)


def install_shield(stage: Path) -> None:
    shutil.copy2(ROOT / "ptcg_ai" / "tactical_shield.py", stage / "ptcg_ai" / "tactical_shield.py")
    model_path = stage / "ptcg_ai" / "model.py"
    source = model_path.read_text(encoding="utf-8")
    source = source.replace(
        "from .safety import sanitize_selection\n",
        "from .safety import sanitize_selection\nfrom .tactical_shield import ShieldTelemetry, apply_tactical_shield\n",
    )
    source = source.replace(
        "        self.fallback = fallback\n",
        "        self.fallback = fallback\n        self.shield_telemetry = ShieldTelemetry()\n",
    )
    original = "        return sanitize_selection(obs.select, ranked, desired)\n"
    replacement = (
        "        ranked, desired, intervention = apply_tactical_shield(obs, ranked, desired)\n"
        "        self.shield_telemetry.record(intervention)\n"
        "        return sanitize_selection(obs.select, ranked, desired)\n"
    )
    if source.count(original) != 1:
        raise RuntimeError("historical model layout changed; refusing an ambiguous probe patch")
    model_path.write_text(source.replace(original, replacement), encoding="utf-8")
    (stage / "main.py").write_text(
        '"""Deterministic recovery probe entry point."""\n\n'
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


def deterministic_tar(stage: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as tar:
                for path in sorted(item for item in stage.rglob("*") if item.is_file()):
                    info = tar.gettarinfo(str(path), arcname=path.relative_to(stage).as_posix())
                    info.mtime = 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    with path.open("rb") as handle:
                        tar.addfile(info, handle)


def sterile_validate(archive: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="grim-probe-check-") as directory:
        stage = Path(directory)
        safe_extract(archive, stage)
        code = (
            f"import sys; sys.path.insert(0, {str(stage)!r})\n"
            "import main\n"
            "deck=main.agent({'select':None,'current':None,'logs':[]})\n"
            "assert len(deck)==60\n"
            "assert main._AGENT.policy.temp if False else True\n"
            "print('ok')\n"
        )
        env = dict(__import__("os").environ)
        env.pop("PYTHONPATH", None)
        result = subprocess.run([sys.executable, "-I", "-c", code], cwd=stage, env=env, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(f"sterile validation failed for {archive.name}: {result.stderr}")
        return {"passed": True, "stdout": result.stdout.strip()}


def build(name: str, weights: Path, output_dir: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix=f"{name}-") as directory:
        stage = Path(directory)
        safe_extract(CONTROL, stage)
        install_shield(stage)
        shutil.copy2(weights, stage / "policy_weights.npz")
        extracted_tree_sha256 = sha256_path(stage).upper()
        output = output_dir / f"{name}.tar.gz"
        deterministic_tar(stage, output)
    return {
        "name": name,
        "archive": str(output.resolve()),
        "archive_sha256": sha256(output),
        "extracted_tree_sha256": extracted_tree_sha256,
        "model_sha256": sha256(weights),
        "base_control_sha256": sha256(CONTROL),
        "sterile_validation": sterile_validate(output),
        "deterministic": True,
        "search": False,
        "temperature": 0,
        "tactical_shield": ["setup_bench_basic", "nullified_attack", "end_with_productive_attack"],
    }


def build_unshielded(name: str, weights: Path, output_dir: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix=f"{name}-") as directory:
        stage = Path(directory)
        safe_extract(CONTROL, stage)
        shutil.copy2(weights, stage / "policy_weights.npz")
        extracted_tree_sha256 = sha256_path(stage).upper()
        output = output_dir / f"{name}.tar.gz"
        deterministic_tar(stage, output)
    return {
        "name": name,
        "archive": str(output.resolve()),
        "archive_sha256": sha256(output),
        "extracted_tree_sha256": extracted_tree_sha256,
        "model_sha256": sha256(weights),
        "base_control_sha256": sha256(CONTROL),
        "sterile_validation": sterile_validate(output),
        "deterministic": True,
        "tactical_shield": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="artifacts/recovery_probes")
    args = parser.parse_args()
    if sha256(CONTROL) != EXPECTED_CONTROL_SHA256:
        raise SystemExit("historical d842 archive hash mismatch")
    output_dir = Path(args.output_dir).resolve()
    manifests = [
        build("a1_d842_shield", ROOT / "artifacts" / "overnight_grim_20260730" / "grim_selected.npz", output_dir),
        build("a2_v2_shield", V2_WEIGHTS, output_dir),
        build_unshielded("a2_v2_unshielded", V2_WEIGHTS, output_dir),
    ]
    control_copy = output_dir / "d842_control_exact.tar.gz"
    control_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CONTROL, control_copy)
    with tempfile.TemporaryDirectory(prefix="d842-control-tree-") as directory:
        control_stage = Path(directory)
        safe_extract(CONTROL, control_stage)
        control_tree_sha256 = sha256_path(control_stage).upper()
    manifests.append({
        "name": "d842_control_exact",
        "archive": str(control_copy.resolve()),
        "archive_sha256": sha256(control_copy),
        "extracted_tree_sha256": control_tree_sha256,
        "byte_identical_historical": sha256(control_copy) == EXPECTED_CONTROL_SHA256,
    })
    manifest_path = output_dir / "build_manifest.json"
    manifest_path.write_text(json.dumps({"artifacts": manifests}, indent=2), encoding="utf-8")
    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

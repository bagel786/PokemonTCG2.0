#!/usr/bin/env python3
"""Build a deterministic dual-actual-order 5k+ archive from exact d842."""

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
CONTROL_HASH = "3ECB0BBF119E23C31905E39E19ECA8F6145104AAEFFC0A5675D2FE03855BB458"
FORBIDDEN_NAMES = {"director_config.json", "direct_policy.npz", "residual_manifest.json", "mirror_direct.npz"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def safe_extract(archive: Path, destination: Path) -> None:
    root = destination.resolve()
    with tarfile.open(archive, "r:gz") as handle:
        for member in handle.getmembers():
            target = (destination / member.name).resolve()
            if root != target and root not in target.parents:
                raise ValueError(f"unsafe archive member: {member.name}")
        handle.extractall(destination)


def require_schema2(path: Path) -> None:
    with np.load(path, allow_pickle=False) as weights:
        version = int(np.asarray(weights["model_schema_version"]).item())
    if version != 2:
        raise ValueError(f"{path} is schema {version}, expected exact schema 2")


def deterministic_archive(stage: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for path in sorted(item for item in stage.rglob("*") if item.is_file()):
                    relative = path.relative_to(stage).as_posix()
                    info = archive.gettarinfo(str(path), arcname=relative)
                    info.mtime = 0; info.uid = 0; info.gid = 0; info.uname = ""; info.gname = ""
                    with path.open("rb") as handle:
                        archive.addfile(info, handle)


def build(args: argparse.Namespace) -> dict:
    control = Path(args.control).resolve()
    first = Path(args.policy_first).resolve()
    second = Path(args.policy_second).resolve()
    if sha256(control) != CONTROL_HASH:
        raise ValueError("control archive is not byte-exact d842")
    require_schema2(first); require_schema2(second)
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="order-ppo-package-", dir=output.parent) as temporary:
        stage = Path(temporary) / "stage"
        stage.mkdir()
        safe_extract(control, stage)
        exact_model = stage / "policy_weights.npz"
        exact_hash = sha256(exact_model)
        shutil.copyfile(exact_model, stage / "policy_d842_exact.npz")
        shutil.copyfile(first, stage / "policy_first.npz")
        shutil.copyfile(second, stage / "policy_second.npz")
        shutil.copyfile(ROOT / "ptcg_ai" / "order_router.py", stage / "ptcg_ai" / "order_router.py")
        (stage / "main.py").write_text(
            '"""Controlled dual-actual-order 5k+ entry point."""\n\n'
            "from ptcg_ai.order_router import ActualOrderAgent\n\n"
            "_AGENT = ActualOrderAgent()\n\n"
            "def agent(obs_dict: dict) -> list[int]:\n    return _AGENT(obs_dict)\n",
            encoding="utf-8",
        )
        runtime = {
            "label": "CONTROLLED_LADDER_PROBE",
            "always_request_first": True,
            "order_source": "latched_current.firstPlayer",
            "policy_first_sha256": sha256(stage / "policy_first.npz"),
            "policy_second_sha256": sha256(stage / "policy_second.npz"),
            "exact_d842_model_sha256": exact_hash,
            "candidate_failure_fallback": "exact_d842",
        }
        (stage / "order_policy_manifest.json").write_text(
            json.dumps(runtime, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        present_forbidden = FORBIDDEN_NAMES.intersection(path.name for path in stage.rglob("*"))
        if present_forbidden:
            raise ValueError(f"forbidden runtime artifacts present: {sorted(present_forbidden)}")
        first_archive = Path(temporary) / "first.tar.gz"
        second_archive = Path(temporary) / "second.tar.gz"
        deterministic_archive(stage, first_archive)
        deterministic_archive(stage, second_archive)
        if sha256(first_archive) != sha256(second_archive):
            raise RuntimeError("candidate archive is not deterministic")
        shutil.copyfile(first_archive, output)
    manifest = {
        **runtime,
        "archive": str(output),
        "archive_sha256": sha256(output),
        "control_archive_sha256": CONTROL_HASH,
        "deck_unchanged": True,
        "deterministic_archive": True,
        "no_r0_director_d1_search": True,
    }
    manifest_path = Path(args.manifest).resolve()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control", default="grimmsnarl_5k_reference.tar.gz")
    parser.add_argument("--policy-first", required=True)
    parser.add_argument("--policy-second", required=True)
    parser.add_argument("--output", default="artifacts/order_ppo/5k_plus.tar.gz")
    parser.add_argument("--manifest", default="artifacts/order_ppo/package_manifest.json")
    args = parser.parse_args()
    print(json.dumps(build(args), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

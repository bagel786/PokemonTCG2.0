#!/usr/bin/env python3
"""Build a deterministic A2/d842/master logit-mix submission archive."""

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
DEFAULT_D842 = ROOT / "artifacts" / "recovery_probes" / "extracted" / "control" / "policy_weights.npz"
DEFAULT_A2 = ROOT / "artifacts" / "recovery_probes" / "extracted" / "a2" / "policy_weights.npz"
DEFAULT_MASTER = ROOT / "artifacts" / "recovery_final" / "opponents" / "master_v1" / "policy_weights.npz"


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


def parse_weights(value: str) -> dict[str, float]:
    result = {}
    for part in value.split(","):
        key, raw = part.split("=", 1)
        result[key.strip()] = float(raw)
    return result


def require_schema2(path: Path) -> None:
    with np.load(path, allow_pickle=False) as weights:
        version = int(np.asarray(weights["model_schema_version"]).item())
    if version != 2:
        raise ValueError(f"{path} is schema {version}, expected 2")


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--weights", default="d842=0.5,a2=0.5")
    parser.add_argument("--first-weights")
    parser.add_argument("--second-weights")
    parser.add_argument("--phase-mode", choices=("none", "early_a2", "development_combat", "continuity"), default="none")
    parser.add_argument("--early-turns", type=int, default=3)
    parser.add_argument("--late-weights")
    parser.add_argument("--development-weights")
    parser.add_argument("--combat-weights")
    parser.add_argument("--stable-weights")
    parser.add_argument("--unstable-weights")
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--d842", type=Path, default=DEFAULT_D842)
    parser.add_argument("--a2", type=Path, default=DEFAULT_A2)
    parser.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--extract", type=Path)
    args = parser.parse_args()
    for path in (args.d842, args.a2, args.master):
        require_schema2(path)
    config = {"name": args.name, "weights": parse_weights(args.weights), "phase_mode": args.phase_mode}
    for key in ("first_weights", "second_weights", "late_weights", "development_weights", "combat_weights", "stable_weights", "unstable_weights"):
        raw = getattr(args, key)
        if raw:
            config[key] = parse_weights(raw)
    config["early_turns"] = args.early_turns
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="policy-mix-", dir=args.output.parent) as temporary:
        stage = Path(temporary) / "stage"; stage.mkdir()
        safe_extract(args.base.resolve(), stage)
        shutil.copyfile(args.d842, stage / "policy_d842.npz")
        shutil.copyfile(args.a2, stage / "policy_a2.npz")
        if "master" in json.dumps(config):
            shutil.copyfile(args.master, stage / "policy_master.npz")
        shutil.copyfile(ROOT / "ptcg_ai" / "logit_mix.py", stage / "ptcg_ai" / "logit_mix.py")
        (stage / "mix_config.json").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (stage / "main.py").write_text(
            '"""Emergency population-strength logit mixture."""\n\n'
            "from ptcg_ai.logit_mix import MixedPolicyAgent\n\n"
            "_AGENT = MixedPolicyAgent()\n\n"
            "def agent(obs_dict: dict) -> list[int]:\n    return _AGENT(obs_dict)\n",
            encoding="utf-8",
        )
        first = Path(temporary) / "one.tar.gz"; second = Path(temporary) / "two.tar.gz"
        deterministic_archive(stage, first); deterministic_archive(stage, second)
        if sha256(first) != sha256(second):
            raise RuntimeError("archive build is not deterministic")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(first, args.output)
        if args.extract:
            if args.extract.exists():
                shutil.rmtree(args.extract)
            shutil.copytree(stage, args.extract)
    manifest = {
        "name": args.name, "config": config, "archive": str(args.output.resolve()),
        "archive_sha256": sha256(args.output), "base_sha256": sha256(args.base),
        "deck_sha256": sha256((args.extract or Path(temporary)) / "deck.csv") if args.extract else None,
        "model_hashes": {"d842": sha256(args.d842), "a2": sha256(args.a2), "master": sha256(args.master)},
        "runtime_sha256": sha256(ROOT / "ptcg_ai" / "logit_mix.py"), "deterministic": True,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

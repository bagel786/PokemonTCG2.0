#!/usr/bin/env python3
"""Build a deterministic public-information matchup-playbook submission."""

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
DEFAULT_A2 = ROOT / "artifacts" / "recovery_probes" / "extracted" / "a2" / "policy_weights.npz"
DEFAULT_D842 = ROOT / "artifacts" / "recovery_probes" / "extracted" / "control" / "policy_weights.npz"
ALL_ROUTES = ("grim", "alakazam", "lopunny", "dragapult", "crustle", "ogerpon",
              "lucario", "dipplin", "garchomp", "mewtwo", "bellibolt", "starmie")


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
    with np.load(path, allow_pickle=False) as arrays:
        version = int(np.asarray(arrays["model_schema_version"]).item())
    if version != 2:
        raise ValueError(f"{path} is schema {version}, expected schema 2")


def deterministic_archive(stage: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for path in sorted(item for item in stage.rglob("*") if item.is_file()):
                    info = archive.gettarinfo(str(path), arcname=path.relative_to(stage).as_posix())
                    info.mtime = 0; info.uid = 0; info.gid = 0; info.uname = ""; info.gname = ""
                    with path.open("rb") as handle:
                        archive.addfile(info, handle)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--actual-second-scale", type=float, required=True)
    parser.add_argument("--matchup-scale", type=float, required=True)
    parser.add_argument("--matchup-second-multiplier", type=float, default=1.0)
    parser.add_argument("--surgical", action="store_true")
    parser.add_argument("--router-minimum", type=float, default=.55)
    parser.add_argument("--enabled-routes", default=",".join(ALL_ROUTES))
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--a2", type=Path, default=DEFAULT_A2)
    parser.add_argument("--d842", type=Path, default=DEFAULT_D842)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--extract", type=Path)
    args = parser.parse_args()
    require_schema2(args.a2); require_schema2(args.d842)
    routes = [value.strip() for value in args.enabled_routes.split(",") if value.strip()]
    unknown = sorted(set(routes) - set(ALL_ROUTES))
    if unknown:
        raise ValueError(f"unknown routes: {unknown}")
    config = {
        "name": args.name, "broad_base": "full_a2", "fallback": "exact_d842",
        "actual_second_scale": args.actual_second_scale,
        "matchup_scale": args.matchup_scale,
        "matchup_second_multiplier": args.matchup_second_multiplier,
        "surgical": args.surgical,
        "router_minimum": args.router_minimum,
        "enabled_routes": routes,
        "hidden_information": False, "search": False,
        "tactical_shield_application_count": 1,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="matchup-playbook-", dir=args.output.parent) as temporary:
        stage = Path(temporary) / "stage"; stage.mkdir()
        safe_extract(args.base.resolve(), stage)
        shutil.copyfile(args.a2, stage / "policy_a2.npz")
        shutil.copyfile(args.d842, stage / "policy_d842.npz")
        shutil.copyfile(ROOT / "ptcg_ai" / "matchup_playbook.py", stage / "ptcg_ai" / "matchup_playbook.py")
        (stage / "matchup_config.json").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (stage / "main.py").write_text(
            '"""Public-information matchup-conditioned Grimmsnarl agent."""\n\n'
            "from ptcg_ai.matchup_playbook import MatchupPlaybookAgent\n\n"
            "_AGENT = MatchupPlaybookAgent()\n\n"
            "def agent(obs_dict: dict) -> list[int]:\n    return _AGENT(obs_dict)\n",
            encoding="utf-8",
        )
        first = Path(temporary) / "first.tar.gz"; second = Path(temporary) / "second.tar.gz"
        deterministic_archive(stage, first); deterministic_archive(stage, second)
        if sha256(first) != sha256(second):
            raise RuntimeError("archive build is not deterministic")
        shutil.copyfile(first, args.output)
        if args.extract:
            if args.extract.exists():
                shutil.rmtree(args.extract)
            shutil.copytree(stage, args.extract)
    manifest = {
        "name": args.name, "config": config,
        "archive": str(args.output.resolve()), "archive_sha256": sha256(args.output),
        "archive_size": args.output.stat().st_size, "base_sha256": sha256(args.base),
        "deck_sha256": sha256(args.extract / "deck.csv") if args.extract else None,
        "model_hashes": {"a2": sha256(args.a2), "d842": sha256(args.d842)},
        "runtime_sha256": sha256(ROOT / "ptcg_ai" / "matchup_playbook.py"),
        "deterministic": True,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

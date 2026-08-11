#!/usr/bin/env python3
"""Build the deterministic persistent-strategy Grimmsnarl v2 submission."""

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
DEFAULT_OUTPUT = ROOT / "artifacts" / "strategic_playbook" / "grimmsnarl_strategic_playbook.tar.gz"

FOCUSED_ROUTE_OBJECTIVES = {
    "grim": [
        "closeout_prize_route", "deny_evolution_engine",
    ],
    "alakazam": [
        "closeout_prize_route", "deny_evolution_engine", "pressure_primary_attacker",
    ],
    "lopunny": ["closeout_prize_route", "pressure_primary_attacker"],
    "dragapult": [
        "closeout_prize_route", "deny_evolution_engine", "pressure_primary_attacker",
    ],
    "crustle": ["closeout_prize_route", "deny_stadium_engine", "deny_evolution_engine"],
    "kangaskhan_generic": ["closeout_prize_route", "pressure_primary_attacker"],
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


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
    with output.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for path in sorted(item for item in stage.rglob("*") if item.is_file()):
                    info = archive.gettarinfo(str(path), arcname=path.relative_to(stage).as_posix())
                    info.mtime = 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    with path.open("rb") as handle:
                        archive.addfile(info, handle)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--a2", type=Path, default=DEFAULT_A2)
    parser.add_argument("--d842", type=Path, default=DEFAULT_D842)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=ROOT / "artifacts" / "strategic_playbook" / "manifest.json")
    parser.add_argument("--extract", type=Path, default=ROOT / "artifacts" / "strategic_playbook" / "extracted")
    parser.add_argument("--preference-logit-margin", type=float, default=.75)
    parser.add_argument("--enable-one-prize-hypotheses", action="store_true")
    parser.add_argument(
        "--focused-actual-second",
        action="store_true",
        help="build the lean actual-second target/stadium/evolution overlay",
    )
    args = parser.parse_args()
    require_schema2(args.a2)
    require_schema2(args.d842)
    config = {
        "name": "grimmsnarl_strategic_playbook_v2",
        "architecture": "persistent_options_over_full_a2",
        "broad_base": "full_a2",
        "fallback": "exact_d842",
        "router_minimum": .55,
        "preference_logit_margin": args.preference_logit_margin,
        "build_logit_margin": .20,
        "actual_second_build_logit_margin": .60,
        "commit_logit_margin": .50,
        "target_commit_logit_margin": 2.0,
        "enable_build_commitments": False,
        "enable_count_overrides": False,
        "enable_one_prize_hypotheses": args.enable_one_prize_hypotheses,
        "hidden_information": False,
        "search": False,
        "tactical_shield_application_count": 1,
        "sanitizer_application_count": 1,
    }
    if args.focused_actual_second:
        config.update({
            "name": "grimmsnarl_strategic_v2_focused_second",
            "architecture": "actual_second_public_matchup_target_overlay_over_full_a2",
            "fallback": "full_a2",
            "actual_second_only": True,
            "preserve_is_first_a2": True,
            "enabled_routes": sorted(FOCUSED_ROUTE_OBJECTIVES),
            "allowed_route_statuses": ["provisional", "high_confidence", "locked"],
            "route_objectives": FOCUSED_ROUTE_OBJECTIVES,
            "require_main_for_plan": True,
            "require_owned_nested_prompts": True,
            "max_root_overrides_per_turn": 1,
            "enable_build_commitments": False,
            "enable_count_overrides": False,
            "enable_setup_count_overrides": False,
            "enable_one_prize_hypotheses": False,
            "build_suppresses_attack": False,
            "build_suppresses_optional_support": False,
            "commit_logit_margin": 1.25,
            "target_commit_logit_margin": 2.0,
            "preference_logit_margin": .75,
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="strategic-playbook-", dir=args.output.parent) as temporary:
        temporary = Path(temporary)
        stage = temporary / "stage"
        stage.mkdir()
        safe_extract(args.base.resolve(), stage)
        shutil.copyfile(args.a2, stage / "policy_a2.npz")
        shutil.copyfile(args.d842, stage / "policy_d842.npz")
        for name in ("matchup_playbook.py", "strategic_playbook.py"):
            shutil.copyfile(ROOT / "ptcg_ai" / name, stage / "ptcg_ai" / name)
        (stage / "strategic_config.json").write_text(
            json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (stage / "main.py").write_text(
            '"""Persistent strategic Grimmsnarl competition entry point."""\n\n'
            "import os\n"
            'os.environ["PTCG_TEMP"] = "0"\n'
            'os.environ["PTCG_SEARCH"] = "0"\n'
            'os.environ["PTCG_TACTICAL_SHIELD"] = "1"\n\n'
            "from ptcg_ai.strategic_playbook import StrategicPlaybookAgent\n\n"
            "_AGENT = StrategicPlaybookAgent()\n\n"
            "def agent(obs_dict: dict) -> list[int]:\n    return _AGENT(obs_dict)\n",
            encoding="utf-8",
        )
        first, second = temporary / "first.tar.gz", temporary / "second.tar.gz"
        deterministic_archive(stage, first)
        deterministic_archive(stage, second)
        if sha256(first) != sha256(second):
            raise RuntimeError("archive build is not deterministic")
        shutil.copyfile(first, args.output)
        if args.extract:
            resolved_extract = args.extract.resolve()
            resolved_parent = args.output.parent.resolve()
            if resolved_parent not in resolved_extract.parents:
                raise RuntimeError("extract directory must remain under the strategic artifact directory")
            if args.extract.exists():
                shutil.rmtree(args.extract)
            shutil.copytree(stage, args.extract)
    manifest = {
        "name": config["name"], "config": config,
        "archive": str(args.output.resolve()), "archive_sha256": sha256(args.output),
        "archive_size": args.output.stat().st_size, "base_sha256": sha256(args.base),
        "deck_sha256": sha256(args.extract / "deck.csv"),
        "model_hashes": {"a2": sha256(args.a2), "d842": sha256(args.d842)},
        "runtime_sha256": sha256(ROOT / "ptcg_ai" / "strategic_playbook.py"),
        "router_runtime_sha256": sha256(ROOT / "ptcg_ai" / "matchup_playbook.py"),
        "config_sha256": sha256(args.extract / "strategic_config.json"),
        "entrypoint_sha256": sha256(args.extract / "main.py"),
        "deterministic": True,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

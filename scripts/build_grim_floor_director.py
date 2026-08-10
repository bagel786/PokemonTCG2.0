#!/usr/bin/env python3
"""Build the hash-pinned Original-5k Grim Floor Director package."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "grimmsnarl_5k_reference.tar.gz"
OUTPUT = ROOT / "artifacts" / "grim_5k_floor_director"
BASE_SHA256 = "3ECB0BBF119E23C31905E39E19ECA8F6145104AAEFFC0A5675D2FE03855BB458"
MODEL_SHA256 = "D842F85ABFC44AF9F41979F91795E22C92C179B62E04D5A0A2F9C734E70AF1C3"
DECK_SHA256 = "92B92BAC9F9163ECFF933B3DC39294D2CC154C8684F3C8497877661419EBC59D"
ENGINE_HASHES = {
    "cg/api.py": "593F1298E52A635F90F8F505A52113E9AF114F444C293404E37906F18EE06CED",
    "cg/game.py": "3BD3D4F4A369A11E6D2F5DA9094CF15EBC410A2221835E6417B7CFF4883F1FC2",
    "cg/cg.dll": "EAE88634E26DC31D94150A4D8202FC9D32596B8C688EF67E14CB4088CD4D5771",
}
RUNTIME_FILES = (
    "card_ids.py", "view.py", "prevention.py", "prevention.json",
    "tactical_shield.py", "wave1_rails.py", "grim_floor_controller.py",
    "floor_policy.json",
)


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
            if target != root and root not in target.parents:
                raise ValueError(f"unsafe archive member: {member.name}")
        handle.extractall(destination)


def deterministic_tar(stage: Path, output: Path) -> None:
    with output.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for path in sorted(p for p in stage.rglob("*") if p.is_file()):
                    info = archive.gettarinfo(str(path), arcname=path.relative_to(stage).as_posix())
                    info.mtime = 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    with path.open("rb") as handle:
                        archive.addfile(info, handle)


def verify_frozen(stage: Path) -> None:
    expected = {"policy_weights.npz": MODEL_SHA256, "deck.csv": DECK_SHA256, **ENGINE_HASHES}
    mismatches = {
        name: {"expected": wanted, "actual": sha256(stage / name)}
        for name, wanted in expected.items() if sha256(stage / name) != wanted
    }
    if mismatches:
        raise RuntimeError("frozen 5k input mismatch: " + json.dumps(mismatches, sort_keys=True))
    cards = [int(x) for x in (stage / "deck.csv").read_text().splitlines() if x.strip()]
    if len(cards) != 60:
        raise RuntimeError("frozen deck is not exactly 60 cards")


def patch_runtime(stage: Path) -> None:
    model = stage / "ptcg_ai" / "model.py"
    source = model.read_text(encoding="utf-8")
    import_anchor = "from .safety import sanitize_selection\n"
    init_anchor = "        self.fallback = fallback\n"
    return_anchor = "        return sanitize_selection(obs.select, ranked, desired)\n"
    if source.count(import_anchor) != 1 or source.count(init_anchor) != 1 or source.count(return_anchor) != 1:
        raise RuntimeError("ambiguous original model anchors; refusing patch")
    source = source.replace(import_anchor, import_anchor + "from .grim_floor_controller import GrimFloorController\n")
    source = source.replace(init_anchor, init_anchor + "        self.floor_controller = GrimFloorController()\n")
    source = source.replace(
        return_anchor,
        "        ranked, desired, _ = self.floor_controller.apply(obs, ranked, desired)\n"
        + return_anchor,
    )
    choose_anchor = "    def choose(self, obs) -> list[int]:\n"
    if source.count(choose_anchor) != 1:
        raise RuntimeError("ambiguous choose anchor")
    source = source.replace(
        choose_anchor,
        "    def reset(self) -> None:\n"
        "        self.floor_controller.reset()\n\n"
        + choose_anchor,
    )
    model.write_text(source, encoding="utf-8")

    agent = stage / "ptcg_ai" / "agent.py"
    source = agent.read_text(encoding="utf-8")
    handshake = "        if obs.select is None:\n            self.errors = 0\n            return list(self.deck)\n"
    replacement = (
        "        if obs.select is None:\n"
        "            self.errors = 0\n"
        "            if hasattr(self.policy, \"reset\"):\n"
        "                self.policy.reset()\n"
        "            return list(self.deck)\n"
    )
    if source.count(handshake) != 1:
        raise RuntimeError("ambiguous deck-handshake anchor")
    agent.write_text(source.replace(handshake, replacement), encoding="utf-8")


def entrypoint(deck_hash: str, policy_hash: str) -> str:
    return f'''"""Original-5k Grim Floor Director entry point."""
import hashlib
from pathlib import Path

def _find(name):
    for candidate in (Path(name), Path("/kaggle_simulations/agent") / name):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(name)

_DECK = _find("deck.csv")
_POLICY = _find("ptcg_ai/floor_policy.json")
if hashlib.sha256(_DECK.read_bytes()).hexdigest().upper() != {deck_hash!r}:
    raise RuntimeError("frozen Grimmsnarl deck hash mismatch")
if hashlib.sha256(_POLICY.read_bytes()).hexdigest().upper() != {policy_hash!r}:
    raise RuntimeError("floor policy hash mismatch")

from ptcg_ai import CompetitionAgent
_AGENT = CompetitionAgent(deck_path=_DECK)

def agent(obs_dict: dict) -> list[int]:
    return _AGENT(obs_dict)
'''


def stage(destination: Path) -> dict:
    safe_extract(BASE, destination)
    verify_frozen(destination)
    for name in RUNTIME_FILES:
        shutil.copy2(ROOT / "ptcg_ai" / name, destination / "ptcg_ai" / name)
    patch_runtime(destination)
    policy_hash = sha256(destination / "ptcg_ai" / "floor_policy.json")
    (destination / "main.py").write_text(entrypoint(DECK_SHA256, policy_hash), encoding="utf-8")
    cards = [int(x) for x in (destination / "deck.csv").read_text().splitlines() if x.strip()]
    metadata = {
        "label": "ORIGINAL_5K_GRIM_FLOOR_DIRECTOR_V1",
        "base_archive_sha256": BASE_SHA256,
        "model_sha256": MODEL_SHA256,
        "deck_sha256": DECK_SHA256,
        "engine_hashes": ENGINE_HASHES,
        "floor_policy_sha256": policy_hash,
        "deck_multiset": dict(sorted(Counter(cards).items())),
        "temperature": 0,
        "runtime_search": False,
        "policy_status": "development_candidate",
    }
    (destination / "floor_build.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return metadata


def sterile_validate(archive: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="grim-5k-floor-sterile-") as directory:
        target = Path(directory)
        safe_extract(archive, target)
        code = (
            "import json,pathlib,sys\n"
            f"sys.path.insert(0,{str(target)!r})\n"
            "ns={'__name__':'submission_entry'}\n"
            "exec(compile(pathlib.Path('main.py').read_text(),'main.py','exec'),ns)\n"
            "deck=ns['agent']({'select':None,'current':None,'logs':[]})\n"
            "ctl=ns['_AGENT'].policy.floor_controller\n"
            "assert len(deck)==60 and ctl.route=='unknown'\n"
            "print(json.dumps({'deck':len(deck),'route':ctl.route,'search':False}))\n"
        )
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        result = subprocess.run(
            [sys.executable, "-I", "-c", code], cwd=target, env=env,
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode:
            raise RuntimeError("sterile raw-source validation failed: " + result.stderr)
        return {"passed": True, "stdout": result.stdout.strip()}


def main() -> int:
    if sha256(BASE) != BASE_SHA256:
        raise SystemExit("pinned original-5k archive hash mismatch")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="grim-5k-floor-build-", dir=OUTPUT) as directory:
        root = Path(directory)
        first, second = root / "first", root / "second"
        first.mkdir()
        second.mkdir()
        metadata = stage(first)
        stage(second)
        a, b = root / "first.tar.gz", root / "second.tar.gz"
        deterministic_tar(first, a)
        deterministic_tar(second, b)
        if sha256(a) != sha256(b):
            raise RuntimeError("two clean builds were not byte-identical")
        archive = OUTPUT / "grim_5k_floor_director_v1.tar.gz"
        shutil.copy2(a, archive)
        extracted = OUTPUT / "extracted_v1"
        if extracted.exists():
            # This is a generated, version-scoped directory beneath OUTPUT.
            # Replacing it makes repeated clean builds useful to auditors.
            if extracted.resolve().parent != OUTPUT.resolve():
                raise RuntimeError(f"unsafe generated extraction target: {extracted}")
            shutil.rmtree(extracted)
        shutil.copytree(first, extracted)
    result = {
        **metadata,
        "archive": str(archive.resolve()),
        "archive_sha256": sha256(archive),
        "archive_bytes": archive.stat().st_size,
        "deterministic_double_build": True,
        "sterile_validation": sterile_validate(archive),
    }
    (OUTPUT / "build_manifest.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

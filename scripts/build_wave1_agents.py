#!/usr/bin/env python3
"""Build hash-pinned A2 Wave-1 Fan and early-tempo ladder packages."""

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
BASE = ROOT / "artifacts" / "recovery_probes" / "a2_v2_shield.tar.gz"
OUTPUT = ROOT / "artifacts" / "wave1_push"
BASE_SHA256 = "0958BD8847266EFBC38658D62B9AC4DCD62A9AAED3D1098F093A677AFCBFED4C"
MODEL_SHA256 = "B19871A9F1499C2460AE266E58194ACAB1D8C90B390FA5CF24ED94B9A2B6BDA8"

TOOL_SCRAPPER = 1137
DAWN = 1231
HANDHELD_FAN = 1161


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def deck_hash(cards: list[int]) -> str:
    payload = "".join(f"{card}\n" for card in cards).encode("ascii")
    return hashlib.sha256(payload).hexdigest().upper()


def safe_extract(archive: Path, destination: Path) -> None:
    root = destination.resolve()
    with tarfile.open(archive, "r:gz") as handle:
        for member in handle.getmembers():
            target = (destination / member.name).resolve()
            if target != root and root not in target.parents:
                raise ValueError(f"unsafe archive member: {member.name}")
        handle.extractall(destination)


def deterministic_tar(stage: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
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


def patch_model(stage: Path) -> None:
    model = stage / "ptcg_ai" / "model.py"
    source = model.read_text(encoding="utf-8")
    if "import os\n" not in source:
        source = source.replace("from pathlib import Path\n", "import os\nfrom pathlib import Path\n")
    import_anchor = "from .tactical_shield import ShieldTelemetry, apply_tactical_shield\n"
    init_anchor = "        self.shield_telemetry = ShieldTelemetry()\n"
    apply_anchor = "        ranked, desired, intervention = apply_tactical_shield(obs, ranked, desired)\n"
    if source.count(import_anchor) != 1 or source.count(init_anchor) != 1 or source.count(apply_anchor) != 1:
        raise RuntimeError("A2 model layout changed; refusing ambiguous Wave-1 patch")
    source = source.replace(import_anchor, import_anchor + "from .wave1_rails import Wave1Rail\n")
    source = source.replace(
        init_anchor,
        init_anchor + '        self.wave1_rail = Wave1Rail(os.environ.get("PTCG_WAVE1_RAIL", "off"))\n',
    )
    source = source.replace(
        apply_anchor,
        "        ranked, desired, _ = self.wave1_rail.apply(obs, ranked, desired)\n" + apply_anchor,
    )
    model.write_text(source, encoding="utf-8")


def entrypoint(mode: str, expected_deck_hash: str) -> str:
    return f'''"""Hash-guarded Wave-1 {mode} ladder entry point."""

import hashlib
import os
from pathlib import Path

os.environ["PTCG_TEMP"] = "0"
os.environ["PTCG_SEARCH"] = "0"
os.environ["PTCG_TACTICAL_SHIELD"] = "1"
os.environ["PTCG_WAVE1_RAIL"] = {mode!r}

def _find_deck():
    candidates = [Path("deck.csv"), Path(__file__).resolve().parent / "deck.csv", Path("/kaggle_simulations/agent/deck.csv")]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("deck.csv")

_DECK_PATH = _find_deck()
_EXPECTED_DECK_SHA256 = {expected_deck_hash!r}
if hashlib.sha256(_DECK_PATH.read_bytes()).hexdigest().upper() != _EXPECTED_DECK_SHA256:
    raise RuntimeError("Wave-1 deck hash mismatch")

from ptcg_ai import CompetitionAgent

_AGENT = CompetitionAgent(deck_path=_DECK_PATH)

def agent(obs_dict: dict) -> list[int]:
    return _AGENT(obs_dict)
'''


def variant_deck(base: list[int]) -> list[int]:
    result = list(base)
    result[result.index(TOOL_SCRAPPER)] = HANDHELD_FAN
    result[result.index(DAWN)] = HANDHELD_FAN
    expected = Counter(base)
    expected[TOOL_SCRAPPER] -= 1
    expected[DAWN] -= 1
    expected[HANDHELD_FAN] += 2
    expected += Counter()
    if Counter(result) != expected:
        raise RuntimeError("Handheld Fan deck mutation is not the approved two-card swap")
    return result


def stage_package(mode: str, destination: Path) -> dict:
    safe_extract(BASE, destination)
    if sha256(destination / "policy_weights.npz") != MODEL_SHA256:
        raise RuntimeError("A2 model hash mismatch")
    patch_model(destination)
    shutil.copy2(ROOT / "ptcg_ai" / "wave1_rails.py", destination / "ptcg_ai" / "wave1_rails.py")
    shutil.copy2(ROOT / "ptcg_ai" / "card_ids.py", destination / "ptcg_ai" / "card_ids.py")
    cards = [int(line) for line in (destination / "deck.csv").read_text().splitlines() if line.strip()]
    if len(cards) != 60:
        raise RuntimeError("A2 base deck is not 60 cards")
    base_counts = Counter(cards)
    if mode == "fan":
        cards = variant_deck(cards)
    elif mode != "tempo":
        raise ValueError(mode)
    (destination / "deck.csv").write_text("".join(f"{card}\n" for card in cards), encoding="ascii")
    expected_deck_hash = sha256(destination / "deck.csv")
    (destination / "main.py").write_text(entrypoint(mode, expected_deck_hash), encoding="utf-8")
    metadata = {
        "label": "WAVE1_PUBLIC_TOP_GRIM_PROBE",
        "mode": mode,
        "base_archive_sha256": BASE_SHA256,
        "model_sha256": MODEL_SHA256,
        "deck_sha256": expected_deck_hash,
        "deck_multiset": dict(sorted(Counter(cards).items())),
        "base_deck_multiset": dict(sorted(base_counts.items())),
        "temperature": 0,
        "search": False,
        "tactical_shield": True,
        "fallback": "A2",
        "rails": (
            ["fan_attach", "fan_energy", "fan_sink"]
            if mode == "fan"
            else ["turn1_setup_search", "turn2_conversion", "punk_up", "munk_damage_source"]
        ),
    }
    (destination / "wave1_manifest.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return metadata


def sterile_validate(archive: Path, mode: str) -> dict:
    with tempfile.TemporaryDirectory(prefix=f"wave1-{mode}-sterile-") as directory:
        stage = Path(directory)
        safe_extract(archive, stage)
        code = (
            "import json, pathlib, sys\n"
            f"sys.path.insert(0, {str(stage)!r})\n"
            "import main\n"
            "deck=main.agent({'select':None,'current':None,'logs':[]})\n"
            "assert len(deck)==60\n"
            f"assert main._AGENT.policy.wave1_rail.mode == {mode!r}\n"
            "print(json.dumps({'deck':len(deck),'mode':main._AGENT.policy.wave1_rail.mode}))\n"
        )
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        result = subprocess.run(
            [sys.executable, "-I", "-c", code], cwd=stage, env=env,
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode:
            raise RuntimeError(f"sterile validation failed for {mode}: {result.stderr}")
        return {"passed": True, "stdout": result.stdout.strip()}


def build_one(mode: str) -> dict:
    output = OUTPUT / f"grim_wave1_{mode}.tar.gz"
    with tempfile.TemporaryDirectory(prefix=f"wave1-{mode}-", dir=OUTPUT) as directory:
        first = Path(directory) / "first"
        second = Path(directory) / "second"
        first.mkdir()
        second.mkdir()
        metadata = stage_package(mode, first)
        stage_package(mode, second)
        a = Path(directory) / "a.tar.gz"
        b = Path(directory) / "b.tar.gz"
        deterministic_tar(first, a)
        deterministic_tar(second, b)
        if sha256(a) != sha256(b):
            raise RuntimeError(f"{mode} package is not deterministic")
        shutil.copy2(a, output)
    return {
        **metadata,
        "archive": str(output.resolve()),
        "archive_sha256": sha256(output),
        "archive_bytes": output.stat().st_size,
        "deterministic_double_build": True,
        "sterile_validation": sterile_validate(output, mode),
    }


def main() -> int:
    if sha256(BASE) != BASE_SHA256:
        raise SystemExit("pinned A2 archive hash mismatch")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    packages = [build_one("fan"), build_one("tempo")]
    manifest = {
        "base": str(BASE.resolve()),
        "base_sha256": BASE_SHA256,
        "packages": packages,
    }
    target = OUTPUT / "build_manifest.json"
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

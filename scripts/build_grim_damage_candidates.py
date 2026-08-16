#!/usr/bin/env python3
"""Materialize local A2 control and narrowly scoped microsprint candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "artifacts/emergency_d842/grim_a2_ordered.tar.gz"
BASE_SHA256 = "E0F3C7CFF1AACD6884442B6E9C44E3712FA305183D839B8F89E5BF2DC2738BC4"
MODEL_SHA256 = "B19871A9F1499C2460AE266E58194ACAB1D8C90B390FA5CF24ED94B9A2B6BDA8"
DECK_SHA256 = "92B92BAC9F9163ECFF933B3DC39294D2CC154C8684F3C8497877661419EBC59D"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        name = path.relative_to(root).as_posix().encode()
        digest.update(len(name).to_bytes(4, "big")); digest.update(name)
        digest.update(bytes.fromhex(sha256(path)))
    return digest.hexdigest().upper()


def extract(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    root = destination.resolve()
    with tarfile.open(BASE, "r:gz") as archive:
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if target != root and root not in target.parents:
                raise RuntimeError(f"unsafe archive member: {member.name}")
        archive.extractall(destination)


def verify_base(stage: Path) -> None:
    if sha256(stage / "policy_weights.npz") != MODEL_SHA256:
        raise RuntimeError("A2 policy_weights hash mismatch")
    if sha256(stage / "policy_first.npz") != MODEL_SHA256 or sha256(stage / "policy_second.npz") != MODEL_SHA256:
        raise RuntimeError("ordered A2 model hashes mismatch")
    if sha256(stage / "deck.csv") != DECK_SHA256:
        raise RuntimeError("A2 deck hash mismatch")


def install_punk_only(stage: Path) -> None:
    model_path = stage / "ptcg_ai/model.py"
    source = model_path.read_text()
    source = source.replace("from pathlib import Path\n", "import os\nfrom pathlib import Path\n")
    source = source.replace(
        "from .tactical_shield import ShieldTelemetry, apply_tactical_shield\n",
        "from .tactical_shield import ShieldTelemetry, apply_tactical_shield\nfrom .wave1_rails import Wave1Rail\n",
    )
    source = source.replace(
        "        self.shield_telemetry = ShieldTelemetry()\n",
        "        self.shield_telemetry = ShieldTelemetry()\n"
        "        mode = 'off' if Path(path).name == 'policy_d842_exact.npz' else os.environ.get('PTCG_WAVE1_RAIL', 'off')\n"
        "        self.wave1_rail = Wave1Rail(mode)\n",
    )
    source = source.replace(
        "        ranked, desired, intervention = apply_tactical_shield(obs, ranked, desired)\n",
        "        ranked, desired, _ = self.wave1_rail.apply(obs, ranked, desired)\n"
        "        ranked, desired, intervention = apply_tactical_shield(obs, ranked, desired)\n",
    )
    source = source.replace(
        "        self.shield_telemetry.record(intervention)\n",
        "        self.shield_telemetry.record(intervention)\n"
        "        ranked, desired, _ = self.wave1_rail.apply_post_shield(obs, ranked, desired)\n",
    )
    required = ("from .wave1_rails import Wave1Rail", "self.wave1_rail.apply(", "self.wave1_rail.apply_post_shield(")
    if any(source.count(token) != 1 for token in required):
        raise RuntimeError("ambiguous A2 model patch")
    model_path.write_text(source)
    shutil.copy2(ROOT / "ptcg_ai/wave1_rails.py", stage / "ptcg_ai/wave1_rails.py")
    shutil.copy2(ROOT / "ptcg_ai/card_ids.py", stage / "ptcg_ai/card_ids.py")
    main_path = stage / "main.py"
    main = main_path.read_text()
    main = main.replace(
        '"""Controlled dual-actual-order 5k+ entry point."""\n\n',
        '"""Controlled dual-actual-order A2 plus isolated Punk Up."""\n\n'
        "import os\n"
        "os.environ['PTCG_WAVE1_RAIL'] = 'punk_only'\n\n",
    )
    if main.count("PTCG_WAVE1_RAIL") != 1:
        raise RuntimeError("ambiguous candidate entrypoint patch")
    main_path.write_text(main)


def install_damage_v0(stage: Path) -> None:
    model_path = stage / "ptcg_ai/model.py"
    source = model_path.read_text()
    source = source.replace("from pathlib import Path\n", "import os\nfrom pathlib import Path\n")
    source = source.replace(
        "from .tactical_shield import ShieldTelemetry, apply_tactical_shield\n",
        "from .tactical_shield import ShieldTelemetry, apply_tactical_shield\n"
        "from .grim_damage_solver import GrimDamageSolver\n",
    )
    source = source.replace(
        "        self.shield_telemetry = ShieldTelemetry()\n",
        "        self.shield_telemetry = ShieldTelemetry()\n"
        "        enabled = (Path(path).name != 'policy_d842_exact.npz' and "
        "os.environ.get('PTCG_GRIM_DAMAGE_SOLVER') == 'v0')\n"
        "        self.damage_solver = GrimDamageSolver(enabled)\n",
    )
    source = source.replace(
        "    def choose(self, obs) -> list[int]:\n",
        "    def reset(self) -> None:\n"
        "        self.damage_solver.reset()\n\n"
        "    def choose(self, obs) -> list[int]:\n",
    )
    source = source.replace(
        "        self.shield_telemetry.record(intervention)\n",
        "        self.shield_telemetry.record(intervention)\n"
        "        ranked, desired, _ = self.damage_solver.apply(obs, ranked, desired)\n",
    )
    required = (
        "from .grim_damage_solver import GrimDamageSolver",
        "self.damage_solver = GrimDamageSolver(enabled)",
        "self.damage_solver.apply(obs, ranked, desired)",
        "self.damage_solver.reset()",
    )
    if any(source.count(token) != 1 for token in required):
        raise RuntimeError("ambiguous A2 damage-solver model patch")
    model_path.write_text(source)
    for name in ("grim_damage_solver.py", "prevention.py", "prevention.json"):
        shutil.copy2(ROOT / "ptcg_ai" / name, stage / "ptcg_ai" / name)

    main_path = stage / "main.py"
    main = main_path.read_text().replace(
        '"""Controlled dual-actual-order 5k+ entry point."""\n\n',
        '"""Controlled dual-actual-order A2 plus exact damage conversion V0."""\n\n'
        "import os\n"
        "os.environ['PTCG_GRIM_DAMAGE_SOLVER'] = 'v0'\n\n",
    )
    if main.count("PTCG_GRIM_DAMAGE_SOLVER") != 1:
        raise RuntimeError("ambiguous damage candidate entrypoint patch")
    main_path.write_text(main)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/grim_damage_conversion/candidates")
    args = parser.parse_args()
    if sha256(BASE) != BASE_SHA256:
        raise SystemExit("ordered A2 control archive hash mismatch")
    if args.output.exists():
        shutil.rmtree(args.output)
    args.output.mkdir(parents=True)
    control = args.output / "a2_control"
    punk = args.output / "a2_punk_only"
    damage = args.output / "a2_damage_v0"
    extract(control); verify_base(control)
    extract(punk); verify_base(punk); install_punk_only(punk)
    extract(damage); verify_base(damage); install_damage_v0(damage)
    manifest = {
        "base_archive": str(BASE), "base_archive_sha256": sha256(BASE),
        "model_sha256": MODEL_SHA256, "deck_sha256": DECK_SHA256,
        "control": {"path": str(control), "tree_sha256": tree_sha256(control)},
        "punk_only": {"path": str(punk), "tree_sha256": tree_sha256(punk),
                      "mode": "punk_only", "allowed_interventions": [
                          "punk_up_activate", "punk_up_energy_count", "punk_up_target"]},
        "damage_v0": {"path": str(damage), "tree_sha256": tree_sha256(damage),
                      "mode": "v0", "allowed_interventions": [
                          "munk_exact_conversion", "shadow_exact_conversion"]},
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

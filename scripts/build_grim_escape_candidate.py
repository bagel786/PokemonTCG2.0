#!/usr/bin/env python3
"""Build the isolated A2+Damage V0 dead-support escape candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "artifacts/grim_damage_conversion/candidates/a2_damage_v0"
BASE_TREE_SHA256 = "13426288358D597EAD809E45C364C7F7B9274A6EEBF55DDD942142E3326535C3"
MODEL_SHA256 = "B19871A9F1499C2460AE266E58194ACAB1D8C90B390FA5CF24ED94B9A2B6BDA8"
DECK_SHA256 = "92B92BAC9F9163ECFF933B3DC39294D2CC154C8684F3C8497877661419EBC59D"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        name = path.relative_to(root).as_posix().encode()
        digest.update(len(name).to_bytes(4, "big"))
        digest.update(name)
        digest.update(bytes.fromhex(sha256(path)))
    return digest.hexdigest().upper()


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if source.count(old) != 1:
        raise RuntimeError(f"ambiguous model patch for {label}: found {source.count(old)} anchors")
    return source.replace(old, new)


def verify_frozen_tree(root: Path) -> None:
    if tree_sha256(root) != BASE_TREE_SHA256:
        raise RuntimeError("A2+Damage V0 base tree hash mismatch")
    for name in ("policy_weights.npz", "policy_first.npz", "policy_second.npz"):
        if sha256(root / name) != MODEL_SHA256:
            raise RuntimeError(f"frozen A2 model hash mismatch: {name}")
    if sha256(root / "deck.csv") != DECK_SHA256:
        raise RuntimeError("frozen Grim deck hash mismatch")


def install_escape(candidate: Path) -> None:
    for name in ("card_ids.py", "grim_guardrails.py", "grim_variance_floor.py"):
        shutil.copy2(ROOT / "ptcg_ai" / name, candidate / "ptcg_ai" / name)

    model_path = candidate / "ptcg_ai/model.py"
    source = model_path.read_text(encoding="utf-8")
    source = replace_once(
        source,
        "from .grim_damage_solver import GrimDamageSolver\n",
        "from .grim_damage_solver import GrimDamageSolver\n"
        "from .grim_variance_floor import GrimVarianceConfig, GrimVarianceFloorDirector\n",
        "escape import",
    )
    source = replace_once(
        source,
        "        self.damage_solver = GrimDamageSolver(enabled)\n",
        "        self.damage_solver = GrimDamageSolver(enabled)\n"
        "        escape_enabled = (Path(path).name != 'policy_d842_exact.npz' and "
        "os.environ.get('PTCG_GRIM_ESCAPE_SOLVER') == 'v0')\n"
        "        self.escape_director = (\n"
        "            GrimVarianceFloorDirector(\n"
        "                GrimVarianceConfig(dead_active_escape=True),\n"
        "                budgets={\n"
        "                    'setup_active': 0, 'setup_bench': 0,\n"
        "                    'shadow_over_retreat': 0, 'shadow_over_boss': 0,\n"
        "                },\n"
        "            ) if escape_enabled else None\n"
        "        )\n"
        "        self.escape_last_intervention = None\n",
        "escape initialization",
    )
    source = replace_once(
        source,
        "    def reset(self) -> None:\n        self.damage_solver.reset()\n",
        "    def reset(self) -> None:\n"
        "        self.damage_solver.reset()\n"
        "        self.escape_last_intervention = None\n"
        "        if self.escape_director is not None:\n"
        "            self.escape_director.reset()\n",
        "escape reset",
    )
    source = replace_once(
        source,
        "        ranked, desired, _ = self.damage_solver.apply(obs, ranked, desired)\n"
        "        return sanitize_selection(obs.select, ranked, desired)\n",
        "        self.escape_last_intervention = None\n"
        "        escape_ok = self.escape_director is not None\n"
        "        if escape_ok:\n"
        "            try:\n"
        "                ranked, desired, self.escape_last_intervention = "
        "self.escape_director.apply(obs, ranked, desired)\n"
        "            except Exception:\n"
        "                self.escape_director.reset()\n"
        "                self.escape_last_intervention = None\n"
        "                escape_ok = False\n"
        "        ranked, desired, _ = self.damage_solver.apply(obs, ranked, desired)\n"
        "        action = sanitize_selection(obs.select, ranked, desired)\n"
        "        if escape_ok:\n"
        "            try:\n"
        "                self.escape_director.commit(obs, action)\n"
        "            except Exception:\n"
        "                self.escape_director.reset()\n"
        "        return action\n",
        "escape application",
    )
    model_path.write_text(source, encoding="utf-8")

    main_path = candidate / "main.py"
    main = main_path.read_text(encoding="utf-8")
    main = replace_once(
        main,
        "os.environ['PTCG_GRIM_DAMAGE_SOLVER'] = 'v0'\n",
        "os.environ['PTCG_GRIM_DAMAGE_SOLVER'] = 'v0'\n"
        "os.environ['PTCG_GRIM_ESCAPE_SOLVER'] = 'v0'\n",
        "escape environment",
    )
    main_path.write_text(main, encoding="utf-8")


def build(output: Path) -> dict:
    verify_frozen_tree(BASE)
    if output.exists():
        raise RuntimeError(f"refusing to overwrite existing candidate: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(BASE, output)
    install_escape(output)

    for name in ("policy_weights.npz", "policy_first.npz", "policy_second.npz"):
        if sha256(output / name) != MODEL_SHA256:
            raise RuntimeError(f"candidate changed frozen A2 model: {name}")
    if sha256(output / "deck.csv") != DECK_SHA256:
        raise RuntimeError("candidate changed frozen Grim deck")

    report = {
        "schema": "grim-a2-damage-v0-escape-only-build-v1",
        "base": str(BASE.relative_to(ROOT)),
        "base_tree_sha256": BASE_TREE_SHA256,
        "candidate": str(output.relative_to(ROOT)),
        "candidate_tree_sha256": tree_sha256(output),
        "frozen_model_sha256": MODEL_SHA256,
        "frozen_deck_sha256": DECK_SHA256,
        "enabled": ["damage_v0", "dead_support_escape"],
        "disabled": ["punk_up", "legacy_grim_guardrails", "search", "reranking", "training"],
        "escape_reasons": [
            "variance_floor:attach_to_escape_dead_support",
            "variance_floor:complete_escape_retreat",
            "variance_floor:dead_support_retreat_to_ready_grim",
            "variance_floor:escape_promote_ready_grim",
        ],
        "modified_runtime_sha256": {
            name: sha256(output / name)
            for name in (
                "main.py",
                "ptcg_ai/model.py",
                "ptcg_ai/card_ids.py",
                "ptcg_ai/grim_guardrails.py",
                "ptcg_ai/grim_variance_floor.py",
            )
        },
    }
    manifest = output.parent / "build_manifest.json"
    manifest.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts/grim_final_escape/candidate",
    )
    args = parser.parse_args()
    print(json.dumps(build(args.output.resolve()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

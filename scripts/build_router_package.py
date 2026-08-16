#!/usr/bin/env python3
"""Build EXP-23 target-router package trees for local evaluation."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN_REPO = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0")
E23_TREE = MAIN_REPO / "artifacts" / "final_sprint" / "exp23_identity_trained"
C0_TREE = MAIN_REPO / "artifacts" / "grim_damage_conversion" / "winner" / "extracted"

EXCLUDE = {"__pycache__"}


def copy_tree(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name in EXCLUDE or item.suffix == ".pyc":
            continue
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(item, target)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--base", choices=("e23", "c0"), default="e23")
    parser.add_argument("--dip-model", default="")
    parser.add_argument("--luc-model", default="")
    parser.add_argument("--surgical-default", default="", help="bake PTCG_SURGICAL default into main.py")
    parser.add_argument("--out-dir", default="artifacts/anti_meta_20260816/packages")
    args = parser.parse_args()

    src = E23_TREE if args.base == "e23" else C0_TREE
    dst = Path(args.out_dir) / args.name
    if dst.exists():
        shutil.rmtree(dst)
    copy_tree(src, dst)

    if args.base == "c0":
        for f in ("policy_first.npz", "policy_second.npz", "policy_weights.npz"):
            shutil.copy2(C0_TREE / f, dst / f)

    for module in ("target_router.py", "surgical.py", "endgame_lethal.py", "search.py", "archetypes.py"):
        shutil.copy2(ROOT / "ptcg_ai" / module, dst / "ptcg_ai" / module)
    model_py = dst / "ptcg_ai" / "model.py"
    text = model_py.read_text()
    if "last_ranked" not in text:
        text = text.replace(
            "        self.damage_solver = GrimDamageSolver(enabled)",
            "        self.damage_solver = GrimDamageSolver(enabled)\n        self.last_ranked = []",
        )
        text = text.replace(
            "        ranked, desired, _ = self.damage_solver.apply(obs, ranked, desired)\n        return sanitize_selection(obs.select, ranked, desired)",
            "        ranked, desired, _ = self.damage_solver.apply(obs, ranked, desired)\n        self.last_ranked = list(ranked)\n        return sanitize_selection(obs.select, ranked, desired)",
        )
        model_py.write_text(text)
    surgical_line = (
        f"os.environ.setdefault('PTCG_SURGICAL', '{args.surgical_default}')\n"
        if args.surgical_default else ""
    )
    main_py = (
        '"""EXP-23 target-router package (evaluation build)."""\n\n'
        "import os\n"
        "os.environ['PTCG_GRIM_DAMAGE_SOLVER'] = 'v0'\n"
        + surgical_line +
        "\nfrom ptcg_ai.target_router import TargetRouterAgent\n"
        "import ptcg_ai.features as _features\n"
        "_features.PLAY_IDENTITY_ENABLED = True\n\n"
        "_AGENT = TargetRouterAgent()\n\n"
        "def agent(obs_dict: dict) -> list[int]:\n"
        "    return _AGENT(obs_dict)\n"
    )
    (dst / "main.py").write_text(main_py)

    meta = {"name": args.name, "base": args.base}
    if args.dip_model:
        shutil.copy2(args.dip_model, dst / "policy_dip.npz")
        meta["dip_model"] = args.dip_model
    if args.luc_model:
        shutil.copy2(args.luc_model, dst / "policy_luc.npz")
        meta["luc_model"] = args.luc_model
    (dst / "router_meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True))
    print(json.dumps(meta, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

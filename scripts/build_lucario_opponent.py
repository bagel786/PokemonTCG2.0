#!/usr/bin/env python3
"""Build a Lucario opponent package (PPO2/PPO1) for local paired evaluation."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN_REPO = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0")
C0_TREE = MAIN_REPO / "artifacts" / "grim_damage_conversion" / "winner" / "extracted"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--out-dir", default="artifacts/anti_meta_20260816/packages")
    args = parser.parse_args()

    dst = Path(args.out_dir) / args.name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(
        C0_TREE, dst,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.npz", "deck.csv", "main.py", "order_policy_manifest.json", "elite_prior.json"),
    )
    deck_src = ROOT / "freshstart" / "decklists" / "mega_lucario_ex.deck.csv"
    shutil.copy2(deck_src, dst / "deck.csv")
    shutil.copy2(args.model, dst / "policy_weights.npz")
    (dst / "main.py").write_text(
        '"""Lucario evaluation package (generic CompetitionAgent entry)."""\n\n'
        "from ptcg_ai.agent import CompetitionAgent\n\n"
        "_AGENT = CompetitionAgent()\n\n"
        "def agent(obs_dict: dict) -> list[int]:\n"
        "    return _AGENT(obs_dict)\n"
    )
    meta = {"name": args.name, "model": args.model, "deck": str(deck_src)}
    (dst / "opponent_meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True))
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

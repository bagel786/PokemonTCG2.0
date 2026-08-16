#!/usr/bin/env python3
"""Scan local raw episode JSONs; classify both seat decks; emit target-vs-Grim inventory."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.dipplin.cards import EXACT_DECK as DIP_EXACT  # noqa: E402
from training.lucario_data import canonical_deck, load_deck  # noqa: E402

GRIM = load_deck(ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv")
LUC_EXACT = load_deck(ROOT / "freshstart" / "decklists" / "mega_lucario_ex.deck.csv")
LUC_VARIANT2 = load_deck(ROOT / "freshstart" / "decklists" / "mega_lucario_ex_variant_2.deck.csv")
DIP_EXACT = canonical_deck(DIP_EXACT)

# Festival-Lead family: Grookey + Thwackey + Dipplin + Festival Grounds
DIP_FAMILY_IDS = {89, 90, 93, 1245}
LUC_FAMILY_IDS = {678, 677, 673, 674, 675, 676}
DIP_CORE_IDS = {42, 88, 89, 90, 92, 93, 1245}
LUC_CORE_IDS = {673, 674, 675, 676, 677, 678}


def classify_deck(sig: tuple[int, ...]) -> str:
    s = set(sig)
    if sig == GRIM:
        return "grim"
    if sig == DIP_EXACT:
        return "dipplin_exact"
    if DIP_FAMILY_IDS <= s and s & {89, 90, 93}:
        return "dipplin_variant"
    if sig in (LUC_EXACT, LUC_VARIANT2):
        return "lucario_exact" if sig == LUC_EXACT else "lucario_variant2"
    if 678 in s and s & {677, 673, 674}:
        return "lucario_family"
    if s & DIP_CORE_IDS:
        return "dipplin_related"
    if s & LUC_CORE_IDS:
        return "lucario_related"
    return "other"


def scan_file(path: Path) -> dict | None:
    try:
        episode = json.loads(path.read_text())
    except Exception:
        return None
    steps = episode.get("steps", [])
    if len(steps) < 2:
        return None
    try:
        decks = [canonical_deck(steps[1][seat].get("action", []) or []) for seat in (0, 1)]
    except Exception:
        return None
    if len(decks) != 2 or len(decks[0]) != 60 or len(decks[1]) != 60:
        return None
    info = episode.get("info", {}) or {}
    names = info.get("TeamNames", ["seat_0", "seat_1"])
    rewards = episode.get("rewards", [])
    raw_id = episode.get("id")
    try:
        episode_id = int(raw_id)
    except (TypeError, ValueError):
        episode_id = str(raw_id or path.stem)
    return {
        "episode_id": episode_id,
        "file": str(path),
        "teams": names,
        "classes": [classify_deck(decks[0]), classify_deck(decks[1])],
        "decks": [list(decks[0]), list(decks[1])],
        "rewards": rewards,
        "n_steps": len(steps),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--roots", nargs="+", required=True)
    parser.add_argument("--output", default="artifacts/anti_meta_20260816/local_scan.json")
    args = parser.parse_args()

    files: set[Path] = set()
    for root in args.roots:
        root_path = Path(root)
        if not root_path.exists():
            print(f"missing root: {root}", flush=True)
            continue
        if root_path.is_file():
            files.add(root_path)
        else:
            files.update(root_path.rglob("*.json"))

    rows = []
    for path in sorted(files):
        row = scan_file(path)
        if row:
            rows.append(row)

    by_pair = Counter(f"{r['classes'][0]}|{r['classes'][1]}" for r in rows)
    target_grim = [
        r for r in rows
        if "grim" in r["classes"]
        and any(c in r["classes"] for c in ("dipplin_exact", "dipplin_variant", "lucario_exact", "lucario_variant2", "lucario_family"))
    ]
    out = {
        "total_episodes_scanned": len(rows),
        "pair_counts": dict(sorted(by_pair.items())),
        "target_vs_grim": len(target_grim),
        "target_grim_episodes": sorted(target_grim, key=lambda r: str(r["episode_id"])),
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(out, indent=2))
    print(json.dumps({
        "total": len(rows),
        "pairs": dict(sorted(by_pair.items())),
        "target_vs_grim": len(target_grim),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

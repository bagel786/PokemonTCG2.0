#!/usr/bin/env python3
"""Filter existing decision corpora for rows whose opponent deck matches target archetypes."""
from __future__ import annotations

import argparse
import gzip
import hashlib
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

DIP_FAMILY_IDS = {89, 90, 93, 1245}
LUC_FAMILY_IDS = {678, 677, 673, 674, 675, 676}


def deck_hash(signature: tuple[int, ...]) -> str:
    payload = ",".join(map(str, signature)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def classify_deck(sig: tuple[int, ...]) -> str:
    s = set(sig)
    if sig == GRIM:
        return "grim"
    if sig == DIP_EXACT:
        return "dipplin_exact"
    if DIP_FAMILY_IDS <= s and s & {89, 90, 93}:
        return "dipplin_variant"
    if sig == LUC_EXACT:
        return "lucario_exact"
    if sig == LUC_VARIANT2:
        return "lucario_variant2"
    if 678 in s and s & {677, 673, 674}:
        return "lucario_family"
    return "other"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpora", nargs="+", required=True)
    parser.add_argument("--output-dir", default="artifacts/anti_meta_20260816")
    args = parser.parse_args()

    target_sigs: dict[str, tuple[int, ...]] = {
        "dipplin_exact": DIP_EXACT,
        "lucario_exact": LUC_EXACT,
        "lucario_variant2": LUC_VARIANT2,
    }
    target_hashes = {deck_hash(sig): name for name, sig in target_sigs.items()}

    rows_by_target: dict[str, list[dict]] = {}
    counts: Counter = Counter()
    for corpus_path in args.corpora:
        corpus = Path(corpus_path)
        opener = gzip.open if corpus.suffix == ".gz" else open
        with opener(corpus, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                h = row.get("opponent_deck_sha256")
                name = target_hashes.get(h)
                if name is None:
                    counts["non_target_rows"] += 1
                    continue
                counts[f"target_rows_{name}"] += 1
                rows_by_target.setdefault(name, []).append(row)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"counts": dict(counts)}
    for name, rows in rows_by_target.items():
        path = out_dir / f"corpus_{name}.jsonl.gz"
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        episodes = sorted({str(r["episode_id"]) for r in rows})
        teams = sorted({str(r["team"]) for r in rows})
        report[name] = {
            "rows": len(rows),
            "episodes": len(episodes),
            "teams": teams,
            "path": str(path),
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

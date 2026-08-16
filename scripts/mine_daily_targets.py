#!/usr/bin/env python3
"""Fast two-pass daily-dump target miner.

Pass 1 (fast): read only the head of each episode file to find the two 60-card
handshakes; classify both seats. Keep target-vs-Grim files + a bounded sample
of grim-vs-other files (negative population for detector FP analysis).

Pass 2 (slow): full parse of retained files; mine Grim-seat rows.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.dipplin.cards import EXACT_DECK as DIP_EXACT  # noqa: E402
import ptcg_ai.features as _features  # noqa: E402

_features.PLAY_IDENTITY_ENABLED = True

from training.lucario_data import canonical_deck, load_deck  # noqa: E402

GRIM = load_deck(ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv")
LUC_EXACT = load_deck(ROOT / "freshstart" / "decklists" / "mega_lucario_ex.deck.csv")
LUC_VARIANT2 = load_deck(ROOT / "freshstart" / "decklists" / "mega_lucario_ex_variant_2.deck.csv")
DIP_EXACT = canonical_deck(DIP_EXACT)
DIP_FAMILY_IDS = {89, 90, 93, 1245}
LUC_FAMILY_IDS = {678, 677, 673, 674, 675, 676}

ACTION_RE = re.compile(rb'"action":\s*\[\[([^\]]*)\],\s*\[([^\]]*)\]')
ACTION_RE_FLAT = re.compile(rb'"action":\s*\[([^\]]*)\]')


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


def target_of(cls: str) -> str | None:
    if cls.startswith("dipplin_"):
        return "dipplin"
    if cls.startswith("lucario_"):
        return "lucario"
    return None


def read_handshakes(path: Path) -> list[tuple[int, ...]] | None:
    with path.open("rb") as handle:
        head = handle.read(400_000)
    for match in ACTION_RE.finditer(head):
        try:
            cards_a = [int(x) for x in match.group(1).split(b",") if x.strip()]
            cards_b = [int(x) for x in match.group(2).split(b",") if x.strip()]
        except ValueError:
            continue
        if (
            len(cards_a) == 60
            and len(cards_b) == 60
            and all(0 < c < 2000 for c in cards_a + cards_b)
        ):
            return [tuple(sorted(cards_a)), tuple(sorted(cards_b))]
    decks = []
    for match in ACTION_RE_FLAT.finditer(head):
        body = match.group(1)
        try:
            cards = [int(x) for x in body.split(b",") if x.strip()]
        except ValueError:
            continue
        if len(cards) == 60 and all(0 < c < 2000 for c in cards):
            decks.append(tuple(sorted(cards)))
        if len(decks) == 2:
            return decks
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--out-dir", default="artifacts/anti_meta_20260816")
    parser.add_argument("--neg-sample", type=int, default=150)
    args = parser.parse_args()

    out = Path(args.out_dir)
    raw_dir = out / f"raw_{args.date.replace('-', '')}"
    neg_dir = out / f"rawneg_{args.date.replace('-', '')}"
    raw_dir.mkdir(parents=True, exist_ok=True)
    neg_dir.mkdir(parents=True, exist_ok=True)

    retained: list[tuple[Path, tuple[int, ...], tuple[int, ...]]] = []
    neg_kept = 0
    counts = Counter()
    files = sorted(Path(args.dump).glob("*.json"))

    for path in files:
        decks = read_handshakes(path)
        if decks is None:
            counts["unreadable"] += 1
            continue
        classes = [classify_deck(decks[s]) for s in (0, 1)]
        counts["games"] += 1
        grim_seat = None
        target_cls = None
        for seat in (0, 1):
            if classes[seat] == "grim":
                grim_seat = seat
            elif (t := target_of(classes[seat])):
                target_cls = classes[seat]
        if grim_seat is not None and target_cls is not None:
            counts[f"target_{target_cls}"] += 1
            retained.append((path, decks[0], decks[1]))
            continue
        if grim_seat is not None and neg_kept < args.neg_sample:
            neg_kept += 1
            retained.append((path, decks[0], decks[1]))

    counts["neg_kept"] = neg_kept
    print(json.dumps({"pass1": dict(counts)}, sort_keys=True), flush=True)

    if not retained:
        (out / f"units_{args.date.replace('-', '')}.json").write_text("{}")
        return 0

    # Pass 2: full parse of retained files.
    from ptcg_ai.replay import episode_reward, iter_decisions  # noqa: E402

    wins: dict[str, list] = {}
    losses: dict[str, list] = {}
    units = []
    row_counts = Counter()
    for path, deck_a, deck_b in retained:
        try:
            episode = json.loads(path.read_text())
        except Exception:
            counts["parse_fail"] += 1
            continue
        info = episode.get("info", {}) or {}
        names = info.get("TeamNames", ["seat_0", "seat_1"])
        classes = [classify_deck(deck_a), classify_deck(deck_b)]
        grim_seat = next((s for s in (0, 1) if classes[s] == "grim"), None)
        target_cls = next((classes[s] for s in (0, 1) if target_of(classes[s])), None)
        episode_id = str(info.get("EpisodeId", episode.get("id", path.stem)))
        if grim_seat is None or target_cls is None:
            shutil_dest = neg_dir / f"{episode_id}.json"
        else:
            shutil_dest = raw_dir / f"{episode_id}.json"
        import shutil
        shutil.copy(path, shutil_dest)
        if grim_seat is None or target_cls is None:
            continue
        target_name = target_of(target_cls)
        grim_team = names[grim_seat]
        target_team = names[1 - grim_seat]
        reward = episode_reward(episode, grim_seat)
        result = "grim_win" if reward == 1.0 else "grim_loss"
        counts[f"result_{result}_{target_name}"] += 1
        units.append({
            "episode_id": episode_id,
            "target_archetype": target_cls,
            "grim_team": grim_team,
            "target_team": target_team,
            "result": result,
            "grim_seat": grim_seat,
            "date": args.date,
        })
        rows = []
        for record in iter_decisions(episode, {grim_team}, feature_version=2):
            row = record.to_json()
            if int(row.get("seat", -1)) != grim_seat:
                continue
            row["target_archetype"] = target_cls
            row["target_team"] = target_team
            row["grim_team"] = grim_team
            row["result"] = result
            row["source_date"] = args.date
            row["source_dataset"] = f"kaggle/pokemon-tcg-ai-battle-episodes-{args.date}"
            rows.append(row)
        bucket = wins if result == "grim_win" else losses
        bucket.setdefault(target_cls, []).extend(rows)

    for name, bucket in (("wins", wins), ("losses", losses)):
        for cls, rows in bucket.items():
            fname = f"{name}_{cls}.jsonl.gz"
            with gzip.open(out / fname, "wt", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, separators=(",", ":")) + "\n")
            row_counts[f"rows_{name}_{cls}"] = len(rows)

    report = {"date": args.date, "counts": dict(counts), "row_counts": dict(row_counts), "units": units}
    (out / f"units_{args.date.replace('-', '')}.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({"final": dict(counts), "rows": dict(row_counts)}, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Detector discovery + latency evaluation from raw episodes.

Offline truth = 60-card handshake. Runtime signals = public opponent state
(active/bench/preEvolutions/discard/stadium) only.

Reports per-target:
  - precision/recall/false-positives over a negative population
  - detection latency: detected before Grim's 1st/2nd/3rd MAIN, later, never
  - split by actual order (first/second)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.dipplin.cards import EXACT_DECK as DIP_EXACT  # noqa: E402
from training.lucario_data import canonical_deck, load_deck  # noqa: E402

GRIM = load_deck(ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv")
DIP_EXACT = canonical_deck(DIP_EXACT)

# Card identity sets.
DIP_IDS = {42, 88, 89, 90, 92, 93, 1245}
DIP_DISTINCTIVE = {88, 89, 90, 1245}  # not shared with Hydrapple/other decks
DIP_COMMON = {42, 92, 93}  # shared with Hydrapple lists
LUC_IDS = {673, 674, 675, 676, 677, 678}
LUC_DISTINCTIVE = {673, 674, 677, 678}
LUC_COMMON = {675, 676}


def classify_deck(sig: tuple[int, ...]) -> str:
    s = set(sig)
    if sig == GRIM:
        return "grim"
    if sig == DIP_EXACT:
        return "dipplin_exact"
    if {89, 90, 93, 1245} <= s and s & {89, 90, 93}:
        return "dipplin_variant"
    if sig == load_deck(ROOT / "freshstart" / "decklists" / "mega_lucario_ex.deck.csv"):
        return "lucario_exact"
    if sig == load_deck(ROOT / "freshstart" / "decklists" / "mega_lucario_ex_variant_2.deck.csv"):
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


def public_ids(obs: dict, opponent_index: int) -> Counter:
    ids: Counter = Counter()
    current = obs.get("current")
    if not current:
        return ids
    players = current.get("players") or []
    if opponent_index >= len(players):
        return ids
    opp = players[opponent_index] or {}
    for slot in (opp.get("active") or []):
        if slot:
            ids[int(slot["id"])] += 1
            for pre in slot.get("preEvolution") or []:
                ids[int(pre["id"])] += 1
    for slot in opp.get("bench") or []:
        if slot:
            ids[int(slot["id"])] += 1
            for pre in slot.get("preEvolution") or []:
                ids[int(pre["id"])] += 1
    for card in opp.get("discard") or []:
        if card:
            ids[int(card["id"])] += 1
    for card in current.get("stadium") or []:
        if card:
            ids[int(card["id"])] += 1
    return ids


def rule_confidence(ids: set[int], target: str) -> str | None:
    """Return 'pending' on weak signal, 'high' on strong signal, else None."""
    if target == "dipplin":
        distinct = ids & DIP_DISTINCTIVE
        common = ids & DIP_COMMON
        if 90 in ids or 89 in ids or 88 in ids:
            return "high"
        if len(distinct) >= 2:
            return "high"
        if len(distinct) >= 1 and len(common) >= 1:
            return "high"
        if len(common) >= 2:
            return "pending"
        return None
    if target == "lucario":
        distinct = ids & LUC_DISTINCTIVE
        common = ids & LUC_COMMON
        if 678 in ids:
            return "high"
        if 677 in ids and (ids & {673, 674, 675, 676}):
            return "high"
        if 673 in ids or 674 in ids:
            return "high"
        if len(distinct) >= 2:
            return "high"
        if 675 in ids and 676 in ids:
            return "pending"
        return None
    return None


def walk_episode(episode: dict, grim_seat: int, target: str, confidence_required: str = "high"):
    """Return (detected_bool, first_detection_info, grim_main_count_before)."""
    steps = episode.get("steps") or []
    grim_main_seen = 0
    first = None
    for step_index, row in enumerate(steps):
        if grim_seat >= len(row):
            continue
        cell = row[grim_seat]
        obs = cell.get("observation") or {}
        current = obs.get("current")
        if not current:
            continue
        select = obs.get("select") or {}
        ids = set(public_ids(obs, 1 - int(current.get("yourIndex", grim_seat))))
        conf = rule_confidence(ids, target)
        if conf and confidence_required in (conf, "any") and first is None:
            first = {
                "step": step_index,
                "turn": current.get("turn"),
                "grim_main_seen": grim_main_seen,
                "conf": conf,
                "ids": sorted(ids & (DIP_IDS | LUC_IDS)),
            }
            if confidence_required != "any":
                return True, first, grim_main_seen
        if select.get("context") is not None and int(select.get("context", -1)) == 0:
            grim_main_seen += 1
    return first is not None, first, grim_main_seen


def load_handshake(path: Path) -> list[tuple[int, ...]] | None:
    import re
    action_re = re.compile(rb'"action":\s*\[\[([^\]]*)\],\s*\[([^\]]*)\]')
    flat_re = re.compile(rb'"action":\s*\[([^\]]*)\]')
    with path.open("rb") as handle:
        head = handle.read(400_000)
    for match in action_re.finditer(head):
        try:
            a = [int(x) for x in match.group(1).split(b",") if x.strip()]
            b = [int(x) for x in match.group(2).split(b",") if x.strip()]
        except ValueError:
            continue
        if len(a) == 60 and len(b) == 60 and all(0 < c < 2000 for c in a + b):
            return [tuple(sorted(a)), tuple(sorted(b))]
    decks = []
    for match in flat_re.finditer(head):
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
    parser.add_argument("--target-dir", required=True, help="raw target-vs-grim episodes")
    parser.add_argument("--neg-dir", default=None, help="raw grim-vs-other episodes (FP population)")
    parser.add_argument("--confidence", choices=("high", "any"), default="high")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    results = defaultdict(list)
    for path in sorted(Path(args.target_dir).glob("*.json")):
        try:
            episode = json.loads(path.read_text())
        except Exception:
            continue
        decks = load_handshake(path)
        if decks is None:
            continue
        classes = [classify_deck(decks[s]) for s in (0, 1)]
        grim_seat = next((s for s in (0, 1) if classes[s] == "grim"), None)
        target_cls = next((classes[s] for s in (0, 1) if target_of(classes[s])), None)
        if grim_seat is None or target_cls is None:
            continue
        target = target_of(target_cls)
        detected, first, mains = walk_episode(episode, grim_seat, target, args.confidence)
        info = episode.get("info", {}) or {}
        results[target].append({
            "episode_id": str(info.get("EpisodeId", path.stem)),
            "detected": detected,
            "first": first,
            "grim_main_seen": mains,
            "archetype": target_cls,
            "target_team": (info.get("TeamNames") or ["", ""])[1 - grim_seat],
        })

    false_positives = Counter()
    neg_games = 0
    if args.neg_dir:
        for path in sorted(Path(args.neg_dir).glob("*.json")):
            try:
                episode = json.loads(path.read_text())
            except Exception:
                continue
            decks = load_handshake(path)
            if decks is None:
                continue
            classes = [classify_deck(decks[s]) for s in (0, 1)]
            grim_seat = next((s for s in (0, 1) if classes[s] == "grim"), None)
            if grim_seat is None:
                continue
            neg_games += 1
            for target in ("dipplin", "lucario"):
                detected, _, _ = walk_episode(episode, grim_seat, target, args.confidence)
                if detected:
                    false_positives[target] += 1

    report = {}
    for target, rows in results.items():
        detected = sum(r["detected"] for r in rows)
        by_bucket = Counter()
        for r in rows:
            f = r["first"]
            if not r["detected"]:
                by_bucket["never"] += 1
            elif f["grim_main_seen"] < 1:
                by_bucket["before_main1"] += 1
            elif f["grim_main_seen"] < 2:
                by_bucket["before_main2"] += 1
            elif f["grim_main_seen"] < 3:
                by_bucket["before_main3"] += 1
            else:
                by_bucket["later"] += 1
        report[target] = {
            "games": len(rows),
            "detected": detected,
            "recall": detected / max(1, len(rows)),
            "by_bucket": dict(by_bucket),
            "false_positives_on_negatives": false_positives[target],
            "negative_games": neg_games,
            "fp_rate": false_positives[target] / max(1, neg_games),
        }
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

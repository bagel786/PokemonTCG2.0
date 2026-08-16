#!/usr/bin/env python3
"""Archetype win/loss report across recent Kaggle submissions.

For each submission dir (data/replays/<id>): read episodes_metadata.json to
find our seat and reward, extract the OPPONENT's full 60-card deck from the
replay's initial visualize block, classify it by best card-overlap against the
repo's known archetype decklists, and aggregate W/L per archetype.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DECKLIST_DIR = ROOT / "freshstart" / "decklists"
EXTRA_DECKS = {
    "starmie": "/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/sprint_870/opponents/starmie_v2_boss_atk/deck.csv",
}
KNOWN = {
    "grimmsnarl": "grimmsnarl_marnie.deck.csv",
    "dragapult": "dragapult_ex.deck.csv",
    "alakazam": "alakazam_dudunsparce.deck.csv",
    "crustle/kangaskhan": "kangaskhan_crustle.deck.csv",
    "bellibolt": "iono_bellibolt_ex.deck.csv",
    "lucario": "mega_lucario_ex.deck.csv",
    "garchomp": "cynthias_garchomp_ex.deck.csv",
    "mewtwo": "team_rockets_mewtwo_ex.deck.csv",
}


def load_card_map() -> dict[int, str]:
    card_map = {}
    p = ROOT / "freshstart" / "data" / "EN_Card_Data.csv"
    if p.exists():
        reader = csv.DictReader(p.read_text(encoding="utf-8-sig").splitlines())
        for row in reader:
            try:
                card_map[int(row.get("Card ID"))] = row.get("Card Name") or "?"
            except (TypeError, ValueError):
                continue
    return card_map


def classify_deck(deck: list[int], known: dict[str, list[int]], card_map: dict[int, str], pokemon_ids: set[int]) -> str:
    deck_set = Counter(deck)
    best_name, best_score = "other", 0
    for name, kdeck in known.items():
        kpok = Counter(cid for cid in kdeck if cid in pokemon_ids)
        shared = sum(min(deck_set[cid], count) for cid, count in kpok.items())
        if shared > best_score:
            best_name, best_score = name, shared
    if best_score < 3:
        counts = Counter(card_map.get(cid, str(cid)) for cid in deck)
        key = [n for n, _ in counts.most_common(3)]
        return f"other[{','.join(key)}]"
    return best_name


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-root", required=True)
    parser.add_argument("--submissions", required=True, help="comma-separated submission ids")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    replay_root = Path(args.replay_root)
    known: dict[str, list[int]] = {}
    for name, filename in KNOWN.items():
        path = DECKLIST_DIR / filename
        if path.exists():
            known[name] = [int(x) for x in path.read_text().splitlines() if x.strip()]
    for name, path in EXTRA_DECKS.items():
        p = Path(path)
        if p.exists():
            known[name] = [int(x) for x in p.read_text().splitlines() if x.strip()]
    card_map = load_card_map()
    sys.path.insert(0, str(ROOT / "vendor"))
    from cg.api import all_card_data

    pokemon_ids = {int(card.cardId) for card in all_card_data() if int(card.hp) > 0}

    report = {"per_submission": {}, "per_archetype": {}}
    archetype_rows: dict[str, list[dict]] = defaultdict(list)
    for token in args.submissions.split(","):
        sub = token.strip()
        d = replay_root / sub
        meta_path = d / "episodes_metadata.json"
        if not meta_path.exists():
            report["per_submission"][sub] = {"error": "no metadata"}
            continue
        metadata = json.loads(meta_path.read_text())
        wins = losses = draws = 0
        per_arch: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
        skipped = 0
        for meta in metadata:
            agents = meta["agents"]
            ours = next((i for i, a in enumerate(agents) if str(a.get("submissionId")) == sub), None)
            if ours is None:
                skipped += 1
                continue
            opp_seat = 1 - ours
            reward = int(agents[ours].get("reward", 0))
            outcome = 1 if reward > 0 else (0 if reward < 0 else 2)
            if outcome == 1:
                wins += 1
            elif outcome == 0:
                losses += 1
            else:
                draws += 1
            replay_path = d / f"episode-{meta['id']}-replay.json"
            archetype = "unknown"
            if replay_path.exists():
                try:
                    episode = json.loads(replay_path.read_text())
                    revealed: set[int] = set()
                    for step_list in episode.get("steps", []):
                        for entry in step_list:
                            obs = entry.get("observation") or {}
                            current = obs.get("current") or {}
                            players = current.get("players") or []
                            if opp_seat >= len(players):
                                continue
                            opp = players[opp_seat] or {}
                            for zone in ("active", "bench", "discard"):
                                for card in opp.get(zone) or []:
                                    if card and card.get("id") is not None:
                                        revealed.add(int(card["id"]))
                            for poke in (opp.get("active") or []) + (opp.get("bench") or []):
                                if not poke:
                                    continue
                                for pre in poke.get("preEvolution") or []:
                                    if pre and pre.get("id") is not None:
                                        revealed.add(int(pre["id"]))
                    archetype = classify_deck(sorted(revealed), known, card_map, pokemon_ids)
                except Exception:
                    archetype = "parse_error"
            per_arch[archetype][outcome] += 1
            archetype_rows[archetype].append(
                {"submission": sub, "episode": meta["id"], "outcome": outcome}
            )
        report["per_submission"][sub] = {
            "episodes": len(metadata),
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "skipped_unknown_seat": skipped,
            "by_archetype": {
                k: {"w": v[1], "l": v[0], "d": v[2]} for k, v in sorted(per_arch.items())
            },
        }

    for archetype, rows in archetype_rows.items():
        w = sum(1 for r in rows if r["outcome"] == 1)
        l = sum(1 for r in rows if r["outcome"] == 0)
        d = sum(1 for r in rows if r["outcome"] == 2)
        report["per_archetype"][archetype] = {
            "games": len(rows), "wins": w, "losses": l, "draws": d,
            "win_rate": w / max(1, len(rows)),
            "submissions": sorted({r["submission"] for r in rows}),
        }

    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("PER ARCHETYPE (sorted by games):")
    for archetype, s in sorted(
        report["per_archetype"].items(), key=lambda kv: -kv[1]["games"]
    ):
        print(
            f"  {archetype:24s} games={s['games']:3d} W={s['wins']:2d} L={s['losses']:2d} "
            f"D={s['draws']}  WR={s['win_rate']:.2f}"
        )
    print("\nPER SUBMISSION:")
    for sub, s in report["per_submission"].items():
        print(f"  {sub}: {s.get('wins')}W-{s.get('losses')}L-{s.get('draws')}D")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

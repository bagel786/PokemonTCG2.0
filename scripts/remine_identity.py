#!/usr/bin/env python3
"""Re-mine retained raw dirs with PLAY identity binding enabled."""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

import ptcg_ai.features as _features  # noqa: E402

_features.PLAY_IDENTITY_ENABLED = True

from ptcg_ai.dipplin.cards import EXACT_DECK as DIP_EXACT  # noqa: E402
from ptcg_ai.replay import episode_reward, iter_decisions  # noqa: E402
from scripts.mine_daily_targets import classify_deck, target_of, read_handshakes  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--out-dir", default="artifacts/anti_meta_20260816")
    args = parser.parse_args()

    out = Path(args.out_dir)
    wins: dict[str, list] = {}
    losses: dict[str, list] = {}
    counts = Counter()
    play_opts = 0
    play_bound = 0

    for path in sorted(Path(args.raw_dir).glob("*.json")):
        try:
            episode = json.loads(path.read_text())
        except Exception:
            continue
        decks = read_handshakes(path)
        if decks is None:
            continue
        classes = [classify_deck(decks[s]) for s in (0, 1)]
        grim_seat = next((s for s in (0, 1) if classes[s] == "grim"), None)
        target_cls = next((classes[s] for s in (0, 1) if target_of(classes[s])), None)
        if grim_seat is None or target_cls is None:
            continue
        info = episode.get("info", {}) or {}
        names = info.get("TeamNames", ["seat_0", "seat_1"])
        grim_team = names[grim_seat]
        target_team = names[1 - grim_seat]
        reward = episode_reward(episode, grim_seat)
        result = "grim_win" if reward == 1.0 else "grim_loss"
        counts[f"{result}_{target_of(target_cls)}"] += 1
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
            for option in row["features"].get("options", []):
                if option.get("option_type") == 7:
                    play_opts += 1
                    if int(option.get("source_card", 0)) != 0:
                        play_bound += 1
            rows.append(row)
        bucket = wins if result == "grim_win" else losses
        bucket.setdefault(target_cls, []).extend(rows)

    for name, bucket in (("wins", wins), ("losses", losses)):
        for cls, rows in bucket.items():
            with gzip.open(out / f"{name}_{cls}_{args.date.replace('-', '')}.jsonl.gz", "wt", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, separators=(",", ":")) + "\n")
            counts[f"rows_{name}_{cls}"] = len(rows)
    counts["play_options"] = play_opts
    counts["play_bound"] = play_bound
    counts["play_binding_rate"] = play_bound / max(1, play_opts)
    print(json.dumps(dict(counts), sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

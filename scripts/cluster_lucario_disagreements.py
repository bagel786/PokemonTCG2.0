#!/usr/bin/env python3
"""Lucario semantic disagreement clustering.

On real Lucario-vs-Grim WIN rows (teacher = winning Grim player), compare
EXP-23's semantic decision with the teacher's. Cluster disagreements into
action-family buckets with team breadth and phase splits.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

import torch

from training.train_bc import PolicyNet, collate, load_npz_weights
from training.replay_refresh import _decision

TYPE_NAMES = {0: "NUMBER", 1: "YES", 2: "NO", 3: "CARD", 4: "TOOL", 5: "ENERGY_CARD",
              6: "ENERGY", 7: "PLAY", 8: "ATTACH", 9: "EVOLVE", 10: "ABILITY",
              11: "DISCARD", 12: "RETREAT", 13: "ATTACK", 14: "END", 15: "SKILL", 16: "SPECCOND"}


def action_signature(action, options):
    parts = []
    for idx in sorted(action):
        if idx >= len(options):
            continue
        opt = options[idx]
        t = opt.get("option_type", -1)
        name = TYPE_NAMES.get(t, str(t))
        if t == 7:
            name = f"PLAY:{opt.get('source_card', 0)}"
        elif t == 13:
            name = f"ATTACK:{opt.get('attack_id', 0)}"
        elif t == 10:
            name = f"ABILITY:{opt.get('source_card', 0)}"
        parts.append(name)
    return tuple(sorted(parts))


def phase(turn):
    if turn <= 3:
        return "early"
    if turn <= 7:
        return "mid"
    return "late"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default="artifacts/anti_meta_20260816/corpus_lucario_family.jsonl.gz")
    parser.add_argument("--base", default="/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/final_sprint/exp23_identity_trained/policy_weights.npz")
    args = parser.parse_args()

    model = PolicyNet(2)
    load_npz_weights(model, args.base)
    model.eval()

    rows = []
    with gzip.open(args.corpus, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("result") == "grim_win":
                rows.append(row)

    buckets = defaultdict(lambda: {
        "count": 0, "games": set(), "teams": set(), "phases": Counter(),
    })
    total_disc = 0
    total_rows = 0
    batch_size = 64
    for i in range(0, len(rows), batch_size):
        chunk = rows[i : i + batch_size]
        batch = collate(chunk)
        with torch.no_grad():
            logits, count_logits, _ = model(batch)
        for j, row in enumerate(chunk):
            total_rows += 1
            elite = set(row["action"])
            predicted = set(_decision(logits, count_logits, batch, j))
            if elite == predicted:
                continue
            total_disc += 1
            options = row["features"]["options"]
            elite_sig = action_signature(elite, options)
            pred_sig = action_signature(predicted, options)
            ctx = str(options[0].get("context") if options else -1)
            key = (ctx, tuple(pred_sig), tuple(elite_sig))
            bucket = buckets[key]
            bucket["count"] += 1
            bucket["games"].add(str(row.get("episode_id")))
            bucket["teams"].add(str(row.get("target_team", row.get("team", ""))))
            bucket["phases"][phase(int(row.get("turn", 0)))] += 1

    top = sorted(buckets.items(), key=lambda kv: -kv[1]["count"])[:30]
    print(f"total win rows: {total_rows}, disagreements: {total_disc}")
    print(f"{'CTX':>4} {'EXP23 -> ':>28} {'TEACHER -> ':>28} {'N':>5} {'GAMES':>6} {'TEAMS':>6} PHASES")
    for (ctx, pred, elite), meta in top:
        print(f"{ctx:>4} {','.join(pred):>28} {','.join(elite):>28} {meta['count']:>5} {len(meta['games']):>6} {len(meta['teams']):>6} {dict(meta['phases'])}")

    out = {
        "total_win_rows": total_rows,
        "disagreements": total_disc,
        "top_buckets": [
            {"ctx": ctx, "exp23": list(pred), "teacher": list(elite), **{k: (sorted(v) if isinstance(v, set) else dict(v)) for k, v in meta.items()}}
            for (ctx, pred, elite), meta in top
        ],
    }
    Path("artifacts/anti_meta_20260816/lucario_clusters.json").write_text(json.dumps(out, indent=2, sort_keys=True, default=list))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

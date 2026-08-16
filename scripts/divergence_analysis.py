#!/usr/bin/env python3
"""Divergence analysis: on target-corpus rows, where DIP/LUC specialists differ
from EXP-23, which side does the elite winner agree with?
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--base", default="/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/final_sprint/exp23_identity_trained/policy_weights.npz")
    parser.add_argument("--specialist", required=True)
    args = parser.parse_args()

    base_model = PolicyNet(2)
    load_npz_weights(base_model, args.base)
    base_model.eval()
    spec_model = PolicyNet(2)
    load_npz_weights(spec_model, args.specialist)
    spec_model.eval()

    rows = []
    with gzip.open(args.corpus, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("result") == "grim_win":
                rows.append(row)

    verdicts = Counter()
    by_source: dict[str, Counter] = defaultdict(Counter)
    by_ctx: dict[str, Counter] = defaultdict(Counter)
    batch_size = 64
    examples = []
    for i in range(0, len(rows), batch_size):
        chunk = rows[i : i + batch_size]
        batch = collate(chunk)
        with torch.no_grad():
            la, ca, _ = base_model(batch)
            lb, cb, _ = spec_model(batch)
        for j, row in enumerate(chunk):
            elite = set(row["action"])
            a = set(_decision(la, ca, batch, j))
            b = set(_decision(lb, cb, batch, j))
            if a == b:
                verdicts["agree"] += 1
                continue
            verdicts["diverge"] += 1
            if elite == b:
                verdicts["elite_agrees_specialist"] += 1
            elif elite == a:
                verdicts["elite_agrees_base"] += 1
            else:
                verdicts["elite_neither"] += 1
            opts = row["features"]["options"]
            for idx in row["action"]:
                if idx < len(opts):
                    opt = opts[idx]
                    if opt.get("option_type") == 7:
                        src = str(opt.get("source_card", 0))
                        if elite == b:
                            by_source[src]["spec_right"] += 1
                        elif elite == a:
                            by_source[src]["base_right"] += 1
                        else:
                            by_source[src]["neither"] += 1
            ctx = str(opts[0].get("context") if opts else -1)
            key = "spec" if elite == b else ("base" if elite == a else "neither")
            by_ctx[ctx][key] += 1
            if len(examples) < 25 and (elite == a or elite == b):
                examples.append({
                    "episode_id": row.get("episode_id"),
                    "turn": row.get("turn"),
                    "ctx": ctx,
                    "elite_side": "specialist" if elite == b else "base",
                    "base_plays": sorted({str(opts[i2].get("source_card", 0)) for i2 in a if i2 < len(opts)}),
                    "spec_plays": sorted({str(opts[i2].get("source_card", 0)) for i2 in b if i2 < len(opts)}),
                    "elite_plays": sorted({str(opts[i2].get("source_card", 0)) for i2 in elite if i2 < len(opts)}),
                })

    report = {
        "verdicts": dict(verdicts),
        "by_source": {k: dict(v) for k, v in sorted(by_source.items(), key=lambda kv: -sum(kv[1].values()))[:25]},
        "by_ctx": {k: dict(v) for k, v in sorted(by_ctx.items())},
        "examples": examples,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

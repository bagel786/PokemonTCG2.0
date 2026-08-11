#!/usr/bin/env python3
"""Replay live episodes through the shipped router and the shipped A2 package.

Answers "does 55434964 actually decide differently from A2?" by feeding both
agents the identical observation stream from our own seat in each ladder game
and counting divergences, split by actual order.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.external import ExternalSubmissionAgent

ROUTER = ROOT / "artifacts/elite_policy_candidates/empirical_router_v2_broad/package/extracted"
A2 = ROOT / "artifacts/emergency_d842/extracted_a2_ordered"
SUB = 55434964
REPLAYS = ROOT / "data" / "replays" / str(SUB)


def main() -> int:
    meta = json.loads((REPLAYS / "episodes_metadata.json").read_text())
    router = ExternalSubmissionAgent(ROUTER)
    a2 = ExternalSubmissionAgent(A2)
    totals = Counter()
    print(f"{'ep':>10} {'res':<5} {'order':<7} {'decisions':>9} {'differ':>7} {'isFirst router/a2':>20}")
    try:
        for entry in sorted(meta, key=lambda e: e["createTime"]):
            if entry["type"] != "EPISODE_TYPE_PUBLIC":
                continue
            mine = [a for a in entry["agents"] if a["submissionId"] == SUB][0]
            seat = mine.get("index", 0)
            path = REPLAYS / f"episode-{entry['id']}-replay.json"
            steps = json.loads(path.read_text())["steps"]
            reset = {"select": None, "logs": [], "current": None, "search_begin_input": None}
            router(reset)
            a2(reset)
            n = differ = 0
            coin = ""
            order = None
            for step in steps:
                if seat >= len(step) or str(step[seat].get("status", "")).upper() != "ACTIVE":
                    continue
                raw = step[seat].get("observation") or {}
                if raw.get("select") is None:
                    continue
                r_act, a_act = router(raw), a2(raw)
                ctx = int((raw.get("select") or {}).get("context", -1))
                if ctx == 41:
                    coin = f"{r_act}/{a_act}"
                cur = raw.get("current") or {}
                if order is None and cur.get("firstPlayer") in (0, 1):
                    order = "first" if int(cur["firstPlayer"]) == seat else "second"
                n += 1
                if r_act != a_act:
                    differ += 1
                    totals[f"differ_{order}"] += 1
                totals[f"decisions_{order}"] += 1
            totals["decisions"] += n
            totals["differ"] += differ
            print(f"{entry['id']:>10} {'WIN' if mine['reward'] > 0 else 'LOSS':<5} "
                  f"{str(order):<7} {n:>9} {differ:>7} {coin:>20}")
    finally:
        router.close()
        a2.close()
    print(f"\ntotals: {dict(totals)}")
    print(f"overall divergence rate: {totals['differ']}/{totals['decisions']} "
          f"= {totals['differ']/max(1,totals['decisions']):.3%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

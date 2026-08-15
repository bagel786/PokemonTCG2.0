#!/usr/bin/env python3
"""Live-replay audit: reconstruct our decisions from the 4-subs live replay
bank with a local control (C0) and a candidate package, and report where the
candidate diverges, by bucket/order/outcome.

This calibrates narrow rails against the ACTUAL live field (not local proxies).
Usage: .venv/bin/python scripts/audit_live_rails.py --candidate <dir> --control <dir>
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "vendor"))
from loss_buckets_live import archetype, card_names, pokemon_seen  # noqa: E402
from ptcg_ai.external import ExternalSubmissionAgent  # noqa: E402

SUBS = (55513649, 55513642, 55491471, 55491464)
REPLAYS = ROOT / "data" / "replays"


def safe_pokemon_seen(cur, idx, names, ismon):
    import copy
    c = copy.deepcopy(cur)
    pl = c["players"][idx]
    pl["active"] = [s for s in (pl.get("active") or []) if s]
    pl["bench"] = [s for s in (pl.get("bench") or []) if s]
    pl["discard"] = [s for s in (pl.get("discard") or []) if s]
    return pokemon_seen(c, idx, names, ismon)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--control", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    cand = ExternalSubmissionAgent(args.candidate)
    ctl = ExternalSubmissionAgent(args.control)
    names, ismon = card_names()

    stats = defaultdict(lambda: Counter())
    rows = []
    for sub in SUBS:
        meta = json.loads((REPLAYS / str(sub) / "episodes_metadata.json").read_text())
        for ep in meta:
            if ep.get("state") != "COMPLETED" or ep.get("type") != "EPISODE_TYPE_PUBLIC":
                continue
            me = next((a for a in ep["agents"] if a.get("submissionId") == sub), None)
            if me is None or me.get("reward") is None:
                continue
            seat = me.get("index")
            if seat is None:
                seat = 0
            rp = REPLAYS / str(sub) / f"episode-{ep['id']}-replay.json"
            if not rp.exists():
                continue
            replay = json.loads(rp.read_text())
            win = me["reward"] > 0
            best, best_key = None, (-1, -1)
            for step in replay.get("steps", []):
                for row in step:
                    c = (row.get("observation") or {}).get("current")
                    if c and c.get("turn") is not None:
                        key = (int(c.get("turn") or 0), int(c.get("turnActionCount") or 0))
                        if key >= best_key:
                            best_key, best = key, c
            arch = archetype(safe_pokemon_seen(best, 1 - seat, names, ismon)) if best else "unknown"
            # walk our decision rows
            n_div = 0
            n_ctl_mismatch = 0
            try:
                ctl({"select": None})
                cand({"select": None})
            except Exception:
                pass
            for step in replay.get("steps", []):
                for row in step:
                    obs = row.get("observation") or {}
                    cur = obs.get("current")
                    if cur is None or cur.get("yourIndex") != seat:
                        continue
                    if obs.get("select") is None:
                        continue
                    recorded = row.get("action") or []
                    if not recorded:
                        continue
                    try:
                        ctl_a = ctl(obs)
                        cand_a = cand(obs)
                    except Exception:
                        continue
                    if ctl_a != recorded:
                        n_ctl_mismatch += 1
                        continue
                    if cand_a != ctl_a:
                        n_div += 1
                        ctx = int(obs["select"].get("context") or 0)
                        stats["by_ctx"][ctx] += 1
                        rows.append({
                            "sub": sub, "episode": ep["id"], "win": win, "arch": arch,
                            "seat_order": 0 if int(cur.get("firstPlayer") or -1) == seat else 1,
                            "turn": int(cur.get("turn") or 0), "ctx": ctx,
                            "ctl": ctl_a, "cand": cand_a,
                        })
            key = (arch, 0 if int((best or {}).get("firstPlayer", -1)) == seat else 1, win)
            stats["games_div"][(arch, key[1], win)] += n_div

    out = {
        "candidate": args.candidate,
        "control": args.control,
        "divergences": len(rows),
        "ctl_mismatches": n_ctl_mismatch,
        "by_ctx": dict(sorted(stats["by_ctx"].items())),
        "by_bucket": {},
        "rows": rows,
    }
    by = defaultdict(lambda: [0, 0, 0])  # bucket/order -> [n_games, n_div, n_win_games_with_div]
    for r in rows:
        k = (r["arch"], r["seat_order"])
        by[k][1] += 1
        by[k][2] += int(r["win"])
    for k, v in sorted(by.items()):
        out["by_bucket"][f"{k[0]}|order{k[1]}"] = {"div": v[1], "div_in_win_games": v[2]}
    Path(args.output).write_text(json.dumps(out, indent=1, sort_keys=True))
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

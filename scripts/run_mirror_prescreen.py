#!/usr/bin/env python3
"""Drive the fast candidate tournament across all 5 mirror-specialist candidates.

Runs each candidate through the archive-faithful mirror harness vs all four
opponents + the v2.2 control, writes one JSON per candidate, and prints a
ranked summary with per-candidate gate verdicts. Use --games 2000 for a fast
pre-screen, --games 10000 for the full gate.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from mirror_tournament import V2_BASE, report_gates, run_pair, wilson  # noqa: E402

SCRATCH = Path(
    "C:/Users/safba/AppData/Local/Temp/claude/"
    "c--Users-safba-Downloads-PokemonTCG2-0/"
    "cdb1c505-0eab-48b8-b9cd-55e6af7782b1/scratchpad"
)

CANDIDATES = {
    "loss_buckets": ROOT / "artifacts/loss_buckets_model/master_loss_buckets_policy.npz",
    "v2_search_off": ROOT / "artifacts/v2_model/policy_weights.npz",
    "seat1_boosted": ROOT / "artifacts/seat1_data/candidate_seat1_boosted.npz",
    "ref5k_d842": SCRATCH / "opponents/ref5k/policy_weights.npz",
    "replay_refresh": SCRATCH / "opponents/replay_refresh/policy_weights.npz",
}

OPPONENTS = {
    "v2_2": SCRATCH / "v22",
    "master_v1": SCRATCH / "opponents/master_v1",
    "ref5k": SCRATCH / "opponents/ref5k",
    "replay": SCRATCH / "opponents/replay_refresh",
}
CONTROL = SCRATCH / "v22"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--games", type=int, default=2000, help="games per (candidate,opponent)")
    ap.add_argument("--workers", type=int, default=max(1, (mp.cpu_count() or 2) - 1))
    ap.add_argument("--seed", type=int, default=20260806)
    ap.add_argument("--outdir", default=str(ROOT / "artifacts" / "mirror_tournament"))
    ap.add_argument("--control", action="store_true", help="also run v2.2-vs-v2.2 control")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    summary = []

    for cand_name, cand_path in CANDIDATES.items():
        if not Path(cand_path).exists():
            print(f"!! SKIP {cand_name}: missing {cand_path}", flush=True)
            continue
        print(f"\n==================== CANDIDATE: {cand_name} ====================", flush=True)
        t0 = time.time()
        result = {"candidate": cand_name, "candidate_path": str(cand_path),
                  "base": str(V2_BASE), "games_per_opp": args.games, "opponents": {}}
        for opp_name, opp_dir in OPPONENTS.items():
            r = run_pair(str(cand_path), str(cand_path), str(opp_dir),
                         args.games, args.workers, args.seed)
            result["opponents"][opp_name] = r
            print(f"  {opp_name:10} {r['wins']}/{r['games']} ({r['win_rate']*100:.2f}%) "
                  f"WilsonLB={r['wilson_95'][0]*100:.2f} "
                  f"s0={r['seat0']['win_rate']*100:.1f} s1={r['seat1']['win_rate']*100:.1f} "
                  f"err h={r['hero_errors']} o={r['opp_errors']}", flush=True)

        agg_w = sum(o["wins"] for o in result["opponents"].values())
        agg_g = sum(o["games"] for o in result["opponents"].values())
        lo, hi = wilson(agg_w, agg_g)
        result["aggregate"] = {
            "wins": agg_w, "games": agg_g, "win_rate": agg_w / agg_g if agg_g else 0.0,
            "wilson_95": [lo, hi],
            "equal_weight_mean": sum(o["win_rate"] for o in result["opponents"].values())
            / max(1, len(result["opponents"])),
        }
        if args.control:
            result["control"] = run_pair(str(cand_path), str(cand_path), str(CONTROL),
                                         args.games, args.workers, args.seed,
                                         control_dir=str(CONTROL))
        result["gates"] = report_gates(result)
        result["seconds"] = round(time.time() - t0, 1)

        (outdir / f"{cand_name}.json").write_text(json.dumps(result, indent=2, sort_keys=True))
        agg = result["aggregate"]
        print(f"  AGG {agg['win_rate']*100:.2f}% WilsonLB={agg['wilson_95'][0]*100:.2f} "
              f"eqmean={agg['equal_weight_mean']*100:.2f} PASS={result['gates']['PASS']} "
              f"({result['seconds']}s)", flush=True)
        summary.append((cand_name, agg["win_rate"], agg["wilson_95"][0],
                        agg["equal_weight_mean"], result["gates"]["PASS"]))

    print("\n==================== RANKED SUMMARY ====================", flush=True)
    for name, wr, lb, eq, passed in sorted(summary, key=lambda x: -x[3]):
        print(f"  {name:16} agg={wr*100:6.2f}%  WilsonLB={lb*100:6.2f}  "
              f"eqmean={eq*100:6.2f}  gatesPASS={passed}", flush=True)
    (outdir / "_summary.json").write_text(json.dumps(
        [{"candidate": n, "agg": wr, "wilson_lb": lb, "eqmean": eq, "pass": p}
         for n, wr, lb, eq, p in summary], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

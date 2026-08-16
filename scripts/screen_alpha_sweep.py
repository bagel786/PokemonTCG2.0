#!/usr/bin/env python3
"""Cheap replay screen: alpha-shrinkage sweep vs elite actions on CERT holdouts."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

OVERNIGHT = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0-overnight")
sys.path.insert(0, str(OVERNIGHT / "scripts" / "overnight_20260816"))
sys.path.insert(0, str(OVERNIGHT))
sys.path.insert(0, str(OVERNIGHT / "vendor"))

from replay_disagreement import (  # noqa: E402
    CERT_TEAMS,
    action_semantic,
    collect_units,
    elite_index_for,
    join_records,
    run_package_on_units,
)

ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = OVERNIGHT / "artifacts" / "overnight_20260816" / "heldout_raw"
PKG_ROOT = ROOT / "artifacts" / "global_swing_20260816" / "packages"
C0 = "/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/grim_damage_conversion/winner/extracted"
E23 = "/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/final_sprint/exp23_identity_trained"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    units_0813 = collect_units([RAW_ROOT / "2026-08-13"], CERT_TEAMS)
    units_b = collect_units([RAW_ROOT / "2026-08-14", RAW_ROOT / "2026-08-15"], CERT_TEAMS)

    packages = {
        "c0": C0,
        "exp23": E23,
        "a60": str(PKG_ROOT / "exp23_alpha_0p6"),
        "a75": str(PKG_ROOT / "exp23_alpha_0p75"),
        "a875": str(PKG_ROOT / "exp23_alpha_0p875"),
        "a95": str(PKG_ROOT / "exp23_alpha_0p95"),
    }
    report = {"datasets": {}, "packages": {name: str(path) for name, path in packages.items()}}
    for dataset_name, units in (("CERT-B(0813)", units_0813), ("CERT-B", units_b)):
        runs = {name: run_package_on_units(name, path, units, args.workers) for name, path in packages.items()}
        joined, elite_rows = join_records(units, elite_index_for(units), runs)
        error_rows = {
            name: [r for r in results if r.get("fatal") or int(r.get("errors", 0)) != 0]
            for name, results in runs.items()
        }
        dataset = {"units": len(units), "errors": {name: len(v) for name, v in error_rows.items()}}
        per_package = {}
        exp23_sem = {}
        for name, results in runs.items():
            rows = []
            for result in results:
                if result.get("fatal"):
                    continue
                for record in result["records"]:
                    key = (result["episode"], result["seat"], record["step"])
                    rows.append({"key": key, "record": record})
            decisive = []
            total_disagree_vs_e23 = 0
            total = 0
            early = mid = late = 0
            order_first = order_second = 0
            family_delta = Counter()
            context_delta = Counter()
            for row in rows:
                key = row["key"]
                record = row["record"]
                elite = elite_rows.get(key)
                if elite is None:
                    continue
                obs = elite["obs"]
                try:
                    sem_cand = action_semantic(obs, record["package_action"])
                    sem_elite = action_semantic(obs, record["elite_action"])
                    sem_c0 = None
                except Exception:
                    continue
                total += 1
                if name == "exp23":
                    exp23_sem[key] = sem_cand
                else:
                    sem_e23 = exp23_sem.get(key)
                    if sem_e23 is not None and sem_cand != sem_e23:
                        total_disagree_vs_e23 += 1
                        family_delta[(sem_e23[:2], sem_cand[:2])] += 1
                        context_delta[record["context"]] += 1
                c0rec = joined[key].get("c0")
                if c0rec is not None:
                    try:
                        sem_c0 = action_semantic(obs, c0rec["package_action"])
                    except Exception:
                        sem_c0 = None
                if sem_cand != sem_c0:
                    if sem_cand == sem_elite:
                        cls = "cand_approved"
                    elif sem_c0 is not None and sem_c0 == sem_elite:
                        cls = "c0_approved"
                    else:
                        cls = "abstain"
                    decisive.append({"cls": cls, "episode": key[0], "record": record})
                    if cls == "cand_approved":
                        turn = int(record.get("turn", 0) or 0)
                        if turn <= 6:
                            early += 1
                        elif turn <= 14:
                            mid += 1
                        else:
                            late += 1
                        if record.get("hero_order") == "first":
                            order_first += 1
                        elif record.get("hero_order") == "second":
                            order_second += 1
            approved = sum(1 for d in decisive if d["cls"] == "cand_approved")
            c0appr = sum(1 for d in decisive if d["cls"] == "c0_approved")
            per_package[name] = {
                "decisions_total": total,
                "decisive": len(decisive),
                "elite_approved": approved,
                "c0_approved": c0appr,
                "elite_approval_ratio": approved / max(1, approved + c0appr),
                "approval_early_mid_late": [early, mid, late],
                "approval_by_order": [order_first, order_second],
                "disagreements_vs_exp23": total_disagree_vs_e23,
                "context_delta_top": dict(context_delta.most_common(6)),
                "family_delta_top": [list(k) + [v] for k, v in family_delta.most_common(8)],
            }
        dataset["packages"] = per_package
        report["datasets"][dataset_name] = dataset

    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    for dataset_name, dataset in report["datasets"].items():
        print("==", dataset_name, "units", dataset["units"], "errors", dataset["errors"])
        for name, p in dataset["packages"].items():
            print(
                f"  {name}: decisive={p['decisive']} ratio={p['elite_approval_ratio']:.3f} "
                f"e/m/l={p['approval_early_mid_late']} f/s={p['approval_by_order']} "
                f"vs_e23_disagree={p['disagreements_vs_exp23']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Policy zoo on current-submission loss states (and matched wins).

For each decision in the selected episodes, compute semantic actions of:
- exp23 (recorded elite action), c0 (A2), d842 (5k line).
Look for consensus: c0 == d842 != exp23. Report counts by context, action
family, turn band, and loss/won split.
"""
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

from replay_disagreement import _run_worker  # noqa: E402

PKGS = {
    "c0": "/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/grim_damage_conversion/winner/extracted",
    "d842": "/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/overnight_20260816/d842_runtime",
}

OPTION_NAMES = {0: "NUMBER", 1: "YES", 2: "NO", 3: "CARD", 4: "TOOL_CARD", 5: "ENERGY_CARD",
                6: "ENERGY", 7: "PLAY", 8: "ATTACH", 9: "EVOLVE", 10: "ABILITY",
                11: "DISCARD", 12: "RETREAT", 13: "ATTACK", 14: "END", 15: "SKILL",
                16: "SPECIAL_CONDITION"}
CTX_NAMES = {0: "MAIN", 1: "SETUP_ACTIVE", 2: "SETUP_BENCH", 3: "SWITCH", 4: "TO_ACTIVE",
             5: "TO_BENCH", 6: "TO_FIELD", 7: "TO_HAND", 8: "DISCARD", 9: "TO_DECK",
             10: "TO_DECK_BOTTOM", 11: "TO_PRIZE", 12: "NOT_MOVE", 13: "DAMAGE_COUNTER",
             14: "DAMAGE_COUNTER_ANY", 15: "DAMAGE", 16: "REMOVE_DAMAGE_COUNTER",
             17: "HEAL", 18: "EVOLVES_FROM", 19: "EVOLVES_TO", 20: "DEVOLVE",
             21: "ATTACH_FROM", 22: "ATTACH_TO", 23: "DETACH_FROM", 24: "LOOK",
             25: "EFFECT_TARGET", 26: "DISCARD_ENERGY_CARD", 27: "DISCARD_TOOL_CARD"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", required=True, nargs="+",
                        help="sub_id:episode_id:seat[,label] per loss/win episode")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    units = []
    for token in args.episodes:
        parts = token.split(",")
        sub, ep, seat = parts[0].split(":")
        label = parts[1] if len(parts) > 1 else ""
        units.append(
            {
                "episode": ep,
                "path": str(OVERNIGHT / "data" / "replays" / sub / f"episode-{ep}-replay.json"),
                "seat": int(seat),
                "label": label,
            }
        )

    runs = {}
    for name, path in PKGS.items():
        results = []
        for u in units:
            results.append(_run_worker({"package": path, "episode": u["path"], "seat": u["seat"], "team": u.get("label")}))
        runs[name] = results
    records = {}
    for name, results in runs.items():
        for r in results:
            if r.get("fatal"):
                continue
            for rec in r["records"]:
                records.setdefault((r["episode"], r["seat"], rec["step"]), {})[name] = rec

    consensus = Counter()
    consensus_ctx = Counter()
    consensus_band = Counter()
    consensus_episodes = Counter()
    total = Counter()
    unit_by_episode = {}
    for u in units:
        for k in records:
            if k[0].endswith(u["episode"]):
                unit_by_episode[k[0]] = u
    for key, by_pkg in records.items():
        episode = key[0]
        unit = unit_by_episode.get(episode)
        if unit is None:
            continue
        label = unit["label"]
        if "c0" not in by_pkg or "d842" not in by_pkg:
            continue
        rec = by_pkg["c0"]
        if by_pkg["c0"]["package_action"] == by_pkg["d842"]["package_action"] and \
           by_pkg["c0"]["package_action"] != rec["elite_action"]:
            consensus[label] += 1
            consensus_ctx[label, rec["context"]] += 1
            band = "early" if int(rec["turn"]) <= 6 else ("mid" if int(rec["turn"]) <= 14 else "late")
            consensus_band[label, band] += 1
            consensus_episodes[label, episode] += 1
        total[label] += 1

    summary = {
        "units": len(units),
        "total_decisions": dict(total),
        "consensus_c0d842_vs_exp23": dict(consensus),
        "consensus_rate": {k: consensus[k] / max(1, total[k]) for k in consensus},
        "consensus_by_ctx": {str(k): v for k, v in consensus_ctx.most_common(20)},
        "consensus_by_band": {str(k): v for k, v in consensus_band.most_common(10)},
        "distinct_episodes_with_consensus": {k: len({e for (l, e), _ in consensus_episodes.items() if l == k}) for k in consensus},
    }
    Path(args.output).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

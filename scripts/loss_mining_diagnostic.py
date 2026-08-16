#!/usr/bin/env python3
"""10-minute diagnostic: EXP23-vs-C0 semantic action clusters on LIVE losses.

Looks ONLY for a cluster satisfying: >=3 distinct losses, rare in wins, same
action-family transition, simple public-state predicate. Reports clusters or
KILL verdict.
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

from replay_disagreement import (  # noqa: E402
    action_semantic,
    elite_index_for,
    load_episode,
    run_package_on_units,
    walk_episode,
)

SUBMISSION = 55556726


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()

    replay_dir = Path(args.replay_dir)
    metadata = json.loads((replay_dir / "episodes_metadata.json").read_text())
    units = []
    for meta in metadata:
        agents = meta["agents"]
        ours = [a for a in agents if a.get("submissionId") == SUBMISSION]
        if not ours:
            continue
        seat = int(ours[0].get("index", agents.index(ours[0])))
        won = int(ours[0].get("reward", 0)) > 0
        units.append(
            {
                "episode": str(meta["id"]),
                "path": str(replay_dir / f"episode-{meta['id']}-replay.json"),
                "seat": seat,
                "won": won,
            }
        )

    c0 = "/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/grim_damage_conversion/winner/extracted"
    c0_results = run_package_on_units("c0", c0, units, args.workers)
    c0_records = {
        (r["episode"], r["seat"]): r for r in c0_results
    }
    def find_record(episode_id, seat):
        for suffix in (f"episode-{episode_id}-replay", episode_id):
            found = c0_records.get((suffix, seat))
            if found is not None:
                return found
        return None

    lost_clusters = Counter()
    won_clusters = Counter()
    lost_episodes = Counter()
    won_episodes = Counter()
    total_decisions = 0
    disagreements = 0
    for unit in units:
        episode_id = unit["episode"]
        result = find_record(episode_id, unit["seat"])
        if result is None or result.get("fatal"):
            continue
        elite_index = elite_index_for([unit])
        elite_rows = {
            row["step"]: row for row in elite_index.get((episode_id, unit["seat"]), [])
        }
        for record in result["records"]:
            total_decisions += 1
            elite = elite_rows.get(record["step"])
            if elite is None:
                continue
            try:
                sem_exp23 = action_semantic(elite["obs"], elite["action"])
                sem_c0 = action_semantic(elite["obs"], record["package_action"])
            except Exception:
                continue
            if sem_exp23 == sem_c0:
                continue
            disagreements += 1
            key = (sem_exp23[0], sem_c0[0], record["context"])
            if unit["won"]:
                won_clusters[key] += 1
                won_episodes[key, episode_id] = 1
            else:
                lost_clusters[key] += 1
                lost_episodes[key, episode_id] = 1

    report = {
        "units": len(units),
        "lost_episodes": sum(1 for u in units if not u["won"]),
        "won_episodes": sum(1 for u in units if u["won"]),
        "total_decisions": total_decisions,
        "disagreements": disagreements,
        "clusters": [],
    }
    for key, count in lost_clusters.most_common():
        n_lost_episodes = sum(1 for (k, e) in lost_episodes if k == key)
        n_won_episodes = sum(1 for (k, e) in won_episodes if k == key)
        report["clusters"].append(
            {
                "exp23_family": key[0],
                "c0_family": key[1],
                "context": key[2],
                "lost_decisions": count,
                "distinct_lost_episodes": n_lost_episodes,
                "won_decisions": won_clusters.get(key, 0),
                "distinct_won_episodes": n_won_episodes,
            }
        )
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=1)[:3000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

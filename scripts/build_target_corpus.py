#!/usr/bin/env python3
"""Merge daily target rows into the anti-meta corpus with holdout discipline.

Rules:
- dedupe on (episode_id, seat, step)
- exclude rows whose grim team is in CERT heldout teams (frozen set)
- exclude episodes that EXP-23 already trained on (identity_train units)
- partition wins (positive demos) / losses (diagnostics)
- report breadth: teams, games, identity-binding rate, turn-band counts
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MAIN_REPO = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0")

HELDOUT_TEAMS = {"matsurih", "lollipop947", "Mint120", "GrimmsnaRL", "Dreamer", "TMTA"}


def exp23_exposed_episodes(units_paths: list[Path]) -> set[str]:
    exposed = set()
    for path in units_paths:
        if not path.exists():
            continue
        with path.open("rt") as handle:
            for line in handle:
                row = json.loads(line)
                if str(row.get("team", "")) not in HELDOUT_TEAMS:
                    exposed.add(str(row.get("episode_id", "")))
    return exposed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", nargs="+", required=True, help="YYYYMMDD labels")
    parser.add_argument("--out-dir", default="artifacts/anti_meta_20260816")
    args = parser.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    exposed = exp23_exposed_episodes(
        [MAIN_REPO / "artifacts" / "final_sprint" / "identity_train" / "units.jsonl",
         MAIN_REPO / "artifacts" / "final_sprint" / "identity_train" / "units_0815.jsonl"]
    )

    sources = []
    for day in args.days:
        for kind in ("wins", "losses"):
            for cls in ("dipplin_exact", "dipplin_variant", "lucario_family", "lucario_exact", "lucario_variant2"):
                path = out / f"{kind}_{cls}_{day}.jsonl.gz"
                if path.exists():
                    sources.append((day, kind, cls, path))

    seen: set[tuple[str, int, int]] = set()
    buckets: dict[str, list[dict]] = defaultdict(list)
    stats: Counter = Counter()
    team_stats: dict[str, Counter] = defaultdict(Counter)
    play_opts = 0
    play_identity_bound = 0
    turn_bands: Counter = Counter()
    forced = 0
    total = 0
    per_episode_meta: dict[str, dict] = {}

    for day, kind, cls, path in sources:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                episode = str(row.get("episode_id", ""))
                key = (episode, int(row.get("seat", -1)), int(row.get("step", -1)))
                if key in seen:
                    stats["duplicates"] += 1
                    continue
                seen.add(key)
                grim_team = str(row.get("grim_team", row.get("team", "")))
                if grim_team in HELDOUT_TEAMS:
                    stats["heldout_team_excluded"] += 1
                    continue
                row["exp23_exposed_episode"] = episode in exposed
                if episode in exposed:
                    stats["exp23_exposed_episode_rows"] += 1
                stats["kept"] += 1
                total += 1
                turn = int(row.get("turn", 0))
                if turn <= 3:
                    band = "early"
                elif turn <= 7:
                    band = "mid"
                else:
                    band = "late"
                turn_bands[band] += 1
                if "features" in row:
                    for option in row["features"].get("options", []):
                        if option.get("option_type") == 7:  # PLAY
                            play_opts += 1
                            if int(option.get("source_card", 0)) != 0:
                                play_identity_bound += 1
                row["day"] = day
                row["split_bucket"] = kind
                buckets[cls].append(row)
                team_stats[cls]["grim_" + grim_team] += 1
                target_team = str(row.get("target_team", ""))
                team_stats[cls]["target_" + target_team] += 1
                ep = per_episode_meta.setdefault(
                    episode,
                    {
                        "grim_team": grim_team,
                        "target_team": row.get("target_team", ""),
                        "target_archetype": cls,
                        "result": kind,
                        "day": day,
                    },
                )
                if ep["result"] == "losses" and kind == "wins":
                    ep["result"] = "wins"
                if kind == "losses" and ep["result"] == "wins":
                    pass

    for cls, rows in buckets.items():
        fname = f"corpus_{cls}.jsonl.gz"
        with gzip.open(out / fname, "wt", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        stats[f"rows_{cls}"] = len(rows)

    # Per-class breadth report
    breadth = {}
    for cls in ("dipplin_exact", "dipplin_variant", "lucario_family", "lucario_exact", "lucario_variant2"):
        rows = buckets.get(cls, [])
        if not rows:
            continue
        eps = {}
        for row in rows:
            key = (str(row.get("episode_id")), row.get("result"))
            eps.setdefault(key, set()).add(str(row.get("grim_team", "")))
        win_eps = {e for (e, r) in eps if r == "grim_win"}
        loss_eps = {e for (e, r) in eps if r == "grim_loss"}
        grim_teams = {str(r.get("grim_team", "")) for r in rows}
        target_teams = {str(r.get("target_team", "")) for r in rows}
        breadth[cls] = {
            "rows": len(rows),
            "grim_win_games": len(win_eps),
            "grim_loss_games": len(loss_eps),
            "unique_grim_teams": sorted(grim_teams),
            "unique_target_teams": sorted(target_teams),
            "days": sorted({str(r.get("day", "")) for r in rows}),
        }

    report = {
        "days": args.days,
        "heldout_teams": sorted(HELDOUT_TEAMS),
        "exp23_exposed_episodes": len(exposed),
        "stats": dict(stats),
        "play_identity_binding_rate": play_identity_bound / max(1, play_opts),
        "play_options": play_opts,
        "turn_bands": dict(turn_bands),
        "total_rows": total,
        "breadth": breadth,
    }
    (out / "corpus_report.json").write_text(json.dumps(report, indent=2, sort_keys=True))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

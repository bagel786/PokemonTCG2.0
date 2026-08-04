#!/usr/bin/env python3
"""Did the policy stop firing blanked attacks into damage immunity?

Win rate cannot answer this: a warm-started policy beats a weak Crustle anyway
while still throwing dead attacks. So measure behaviour directly, and report
*offered* alongside *taken* -- an option that is never offered is a deck or
board-development problem, not a policy choice.

For grimmsnarl_marnie specifically the working line is Morgrem's Corkscrew Punch
(60, {D}{D}, non-ex) plus the Froslass/Munkidori abilities. Their attacks cost
{W}/{P} and this deck runs only {D}, so they are never payable.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / "vendor").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

from cg.api import OptionType, all_attack  # noqa: E402

ABILITY = int(OptionType.ABILITY)


def summarize(path: Path, opponent_substring: str) -> dict:
    names = {a.attackId: (a.name, a.damage) for a in all_attack()}
    offered, taken, blanked_offered, blanked_taken = Counter(), Counter(), Counter(), Counter()
    abilities_offered = abilities_taken = 0
    games = set()
    for line in gzip.open(path, "rt"):
        row = json.loads(line)
        if opponent_substring not in row.get("opponent", ""):
            continue
        games.add(row["episode_id"])
        options = row["features"]["options"]
        chosen = set(row["action"])
        for index, option in enumerate(options):
            numeric = option.get("numeric") or []
            nullified = len(numeric) >= 13 and numeric[-1] > 0
            attack_id = option.get("attack_id", 0)
            if option.get("option_type") == ABILITY:
                abilities_offered += 1
                abilities_taken += index in chosen
            if not attack_id:
                continue
            offered[attack_id] += 1
            blanked_offered[attack_id] += nullified
            if index in chosen:
                taken[attack_id] += 1
                blanked_taken[attack_id] += nullified
    total_taken = sum(taken.values())
    return {
        "file": str(path),
        "games": len(games),
        "attacks_taken": total_taken,
        "blanked_taken": sum(blanked_taken.values()),
        "blanked_rate": sum(blanked_taken.values()) / max(1, total_taken),
        "abilities_offered": abilities_offered,
        "abilities_taken": abilities_taken,
        "rows": [
            {
                "attack_id": attack_id,
                "name": names.get(attack_id, ("?", 0))[0],
                "damage": names.get(attack_id, ("?", 0))[1],
                "offered": count,
                "taken": taken[attack_id],
                "blanked_taken": blanked_taken[attack_id],
            }
            for attack_id, count in offered.most_common()
        ],
    }


def render(summary: dict) -> str:
    lines = [
        f"{summary['file']}",
        f"  {summary['games']} games, {summary['attacks_taken']} attacks taken, "
        f"{summary['blanked_taken']} blanked ({summary['blanked_rate']:.1%})",
        f"  abilities: {summary['abilities_taken']} taken / {summary['abilities_offered']} offered",
        "  %-6s %-26s %6s %7s %6s %8s" % ("id", "attack", "dmg", "offered", "taken", "blanked"),
    ]
    for row in summary["rows"]:
        lines.append(
            "  %-6d %-26s %6s %7d %6d %8d"
            % (row["attack_id"], row["name"], row["damage"], row["offered"], row["taken"], row["blanked_taken"])
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("rollouts", nargs="+")
    parser.add_argument("--opponent", default="crustle", help="substring match on the opponent name")
    parser.add_argument("--output")
    args = parser.parse_args()
    summaries = [summarize(Path(p), args.opponent) for p in args.rollouts]
    for summary in summaries:
        print(render(summary))
        print()
    if len(summaries) > 1:
        first, last = summaries[0], summaries[-1]
        print("DELTA blanked-attack rate: %.1f%% -> %.1f%%  (%+.1f pp)" % (
            100 * first["blanked_rate"], 100 * last["blanked_rate"],
            100 * (last["blanked_rate"] - first["blanked_rate"]),
        ))
    if args.output:
        Path(args.output).write_text(json.dumps(summaries, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

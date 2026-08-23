#!/usr/bin/env python3
"""Sanitize and stratify the fresh 2026-08-13 held-out replay reanalysis."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))
OPTION_NAMES = {
    0: "number", 1: "yes", 2: "no", 3: "card", 4: "tool_card",
    5: "energy_card", 6: "energy", 7: "play", 8: "attach", 9: "evolve",
    10: "ability", 11: "discard", 12: "retreat", 13: "attack", 14: "end",
    15: "skill", 16: "special_condition",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity_state(obs_dict: dict) -> str:
    from scripts.overnight_20260816 import replay_disagreement as historical

    obs = historical.to_observation_class(obs_dict)
    source_cards = []
    for option in obs.select.option:
        if option.type != historical.OptionType.PLAY:
            continue
        selected = None
        if option.area is None:
            hand = obs.current.players[obs.current.yourIndex].hand or []
            index = option.index
            if index is not None and 0 <= index < len(hand) and hand[index] is not None:
                selected = hand[index]
        else:
            selected = historical.resolve_area_card(
                obs, option.area, option.index, option.playerIndex
            )
        source_cards.append(int(selected.id if selected is not None else option.cardId or 0))
    return "multi_play_identity" if len({value for value in source_cards if value > 0}) >= 2 else "other"


def action_family(obs_dict: dict, action: list[int]) -> str:
    from scripts.overnight_20260816 import replay_disagreement as historical

    obs = historical.to_observation_class(obs_dict)
    option_types = sorted({
        int(obs.select.option[index].type)
        for index in action
        if 0 <= int(index) < len(obs.select.option)
    })
    return "+".join(OPTION_NAMES.get(value, str(value)) for value in option_types) or "empty"


def bootstrap(rows: list[dict], iterations: int, seed: int) -> dict:
    counts = Counter(row["cls"] for row in rows)
    binary = counts["cand_approved"] + counts["c0_approved"]
    result = {
        "disagreements": len(rows),
        "candidate_approved": counts["cand_approved"],
        "control_approved": counts["c0_approved"],
        "abstain": counts["abstain"],
        "binary_decisive": binary,
        "approval": counts["cand_approved"] / binary if binary else None,
        "episodes": len({row["episode"] for row in rows}),
    }
    if not binary:
        result["episode_bootstrap_95_ci"] = [None, None]
        return result
    by_episode = defaultdict(list)
    for row in rows:
        by_episode[row["episode"]].append(row["cls"])
    episodes = sorted(by_episode)
    numerators = np.asarray([
        sum(value == "cand_approved" for value in by_episode[episode]) for episode in episodes
    ], dtype=np.int64)
    denominators = np.asarray([
        sum(value in {"cand_approved", "c0_approved"} for value in by_episode[episode])
        for episode in episodes
    ], dtype=np.int64)
    rng = np.random.default_rng(seed)
    samples = np.empty(iterations, dtype=np.float64)
    batch = 2_000
    for start in range(0, iterations, batch):
        stop = min(iterations, start + batch)
        picked = rng.integers(0, len(episodes), size=(stop - start, len(episodes)))
        denominator = denominators[picked].sum(axis=1)
        numerator = numerators[picked].sum(axis=1)
        samples[start:stop] = np.divide(
            numerator, denominator, out=np.full(stop - start, np.nan), where=denominator > 0
        )
    result["episode_bootstrap_95_ci"] = [
        float(np.nanpercentile(samples, 2.5)), float(np.nanpercentile(samples, 97.5))
    ]
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "paper/data/heldout_0813_summary.json",
    )
    parser.add_argument("--iterations", type=int, default=100_000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    historical_summary = json.loads(args.summary.read_text(encoding="utf-8"))
    rows = []
    with gzip.open(args.rows, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            rows.append({
                "episode": str(row["episode"]),
                "team": str(row.get("team", "")),
                "hero_order": str(row.get("hero_order", "unknown")),
                "turn": int(row.get("turn", -1)),
                "turn_band": "early" if int(row.get("turn", -1)) <= 3 else (
                    "mid" if int(row.get("turn", -1)) <= 7 else "late"
                ),
                "context": str(row.get("context", "unknown")),
                "action_family": action_family(row["obs"], row["elite"]),
                "cls": str(row["cls"]),
                "identity_state": identity_state(row["obs"]),
            })
    groups = defaultdict(list)
    for row in rows:
        groups[row["identity_state"]].append(row)
    team_names = sorted({row["team"] for row in rows})
    team_results = {
        f"heldout_team_{index + 1}": bootstrap(
            [row for row in rows if row["team"] == team], args.iterations, 20260840 + index
        )
        for index, team in enumerate(team_names)
    }
    team_approvals = [value["approval"] for value in team_results.values() if value["approval"] is not None]
    sanitized = {
        "schema_version": 1,
        "label": "fresh_reanalysis_of_retained_2026_08_13_heldout_replays",
        "method": "historical semantic-action classifier; episode-clustered bootstrap",
        "important_estimand_note": (
            "Approval is conditional on candidate-control semantic disagreement and excludes abstentions; "
            "it is not a gameplay win rate."
        ),
        "source": {
            "historical_evaluator": "scripts/overnight_20260816/replay_disagreement.py",
            "historical_evaluator_sha256": sha256_file(
                ROOT / "scripts/overnight_20260816/replay_disagreement.py"
            ),
            "raw_summary_sha256": sha256_file(args.summary),
            "raw_rows_sha256": sha256_file(args.rows),
            "sanitizer": str(Path(__file__).resolve().relative_to(ROOT)),
            "sanitizer_sha256": sha256_file(Path(__file__).resolve()),
        },
        "coverage": {
            "episodes_discovered": historical_summary.get("episodes_discovered"),
            "units_discovered": historical_summary.get("units_discovered"),
            "fatal": historical_summary.get("fatal"),
            "excluded": historical_summary.get("excluded"),
        },
        "overall": bootstrap(rows, args.iterations, 20260827),
        "by_identity_state": {
            name: bootstrap(group, args.iterations, 20260828 + index)
            for index, (name, group) in enumerate(sorted(groups.items()))
        },
        "by_actual_order": {
            name: bootstrap([row for row in rows if row["hero_order"] == name], args.iterations, 20260830 + index)
            for index, name in enumerate(sorted({row["hero_order"] for row in rows}))
        },
        "by_turn_band": {
            name: bootstrap([row for row in rows if row["turn_band"] == name], args.iterations, 20260850 + index)
            for index, name in enumerate(sorted({row["turn_band"] for row in rows}))
        },
        "by_context": {
            name: bootstrap([row for row in rows if row["context"] == name], args.iterations, 20260860 + index)
            for index, name in enumerate(sorted({row["context"] for row in rows}))
        },
        "by_action_family": {
            name: bootstrap([row for row in rows if row["action_family"] == name], args.iterations, 20260870 + index)
            for index, name in enumerate(sorted({row["action_family"] for row in rows}))
        },
        "by_team": team_results,
        "team_balanced_approval": float(np.mean(team_approvals)) if team_approvals else None,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(sanitized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "disagreements": len(rows),
        "approval": sanitized["overall"]["approval"],
        "ci": sanitized["overall"]["episode_bootstrap_95_ci"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

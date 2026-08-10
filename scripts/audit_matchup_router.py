#!/usr/bin/env python3
"""Audit public-only matchup routing against replay handshake labels offline."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "vendor"))

from cg.api import to_observation_class
from ptcg_ai.matchup_playbook import PublicArchetypeRouter
from ptcg_ai.replay import load_episode
from scripts.crawl_grim_daily import classify, load_archetype_catalog
from training.lucario_data import canonical_deck, load_deck


def route_for(label: str) -> str:
    value = label.lower()
    for needle, route in (
        ("grimmsnarl", "grim"), ("alakazam", "alakazam"), ("lopunny", "lopunny"),
        ("dragapult", "dragapult"), ("crustle", "crustle"), ("kangaskhan_toolbox", "ogerpon"),
        ("ogerpon", "ogerpon"), ("lucario", "lucario"), ("dipplin", "dipplin"),
        ("garchomp", "garchomp"), ("mewtwo", "mewtwo"), ("bellibolt", "bellibolt"),
        ("starmie", "starmie"),
    ):
        if needle in value:
            return route
    return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replays", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum", type=float, default=.55)
    args = parser.parse_args()
    exact = load_deck(ROOT / "freshstart/decklists/grimmsnarl_marnie.deck.csv")
    catalog = load_archetype_catalog(ROOT / "freshstart/decklists")
    decisions = Counter(); episodes = Counter(); matrix = defaultdict(Counter)
    seen_paths = set()
    for replay_root in args.replays:
        for path in sorted(replay_root.rglob("*.json")):
            if not (path.name.startswith("episode-") and path.name.endswith("-replay.json")):
                continue
            resolved = str(path.resolve())
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            try:
                episode = load_episode(path); steps = episode.get("steps") or []
                if len(steps) < 2 or len(steps[1]) < 2:
                    continue
                decks = [canonical_deck(steps[1][seat].get("action") or []) for seat in (0, 1)]
                for seat in (0, 1):
                    if decks[seat] != exact:
                        continue
                    truth_label = classify(decks[1 - seat], catalog)
                    truth = route_for(truth_label)
                    router = PublicArchetypeRouter(args.minimum)
                    final_route = "unknown"; routed_once = False; first_turn = None
                    local_decisions = 0
                    for step in steps:
                        if seat >= len(step) or str(step[seat].get("status", "")).upper() != "ACTIVE":
                            continue
                        raw = step[seat].get("observation") or {}
                        if raw.get("select") is None or raw.get("current") is None:
                            continue
                        route, confidence = router.update(to_observation_class(raw))
                        local_decisions += 1; decisions["total"] += 1
                        decisions[f"truth:{truth}"] += 1; decisions[f"route:{route}"] += 1
                        matrix[truth][route] += 1
                        if route != "unknown":
                            decisions["routed"] += 1
                            if route == truth:
                                decisions["correct_routed"] += 1
                            if not routed_once:
                                routed_once = True
                                first_turn = int((raw.get("current") or {}).get("turn", 0) or 0)
                        if confidence >= .85:
                            decisions["high_confidence"] += 1
                            if route == truth:
                                decisions["correct_high_confidence"] += 1
                        final_route = route
                    if local_decisions:
                        episodes["total"] += 1; episodes[f"truth:{truth}"] += 1
                        episodes[f"final:{final_route}"] += 1
                        if final_route != "unknown":
                            episodes["routed"] += 1
                        if final_route == truth:
                            episodes["correct_final"] += 1
                            if truth != "unknown":
                                episodes["correct_final_supported"] += 1
                        if truth == "unknown" and final_route == "unknown":
                            episodes["correct_unknown_fallback"] += 1
                        if first_turn is not None:
                            episodes["first_route_turn_sum"] += first_turn
            except Exception:
                episodes["failures"] += 1
    result = {
        "decisions": dict(decisions), "episodes": dict(episodes),
        "decision_coverage": decisions["routed"] / decisions["total"] if decisions["total"] else 0,
        "routed_accuracy": decisions["correct_routed"] / decisions["routed"] if decisions["routed"] else 0,
        "high_confidence_accuracy": decisions["correct_high_confidence"] / decisions["high_confidence"] if decisions["high_confidence"] else 0,
        "episode_final_accuracy": episodes["correct_final"] / episodes["total"] if episodes["total"] else 0,
        "episode_final_accuracy_supported": episodes["correct_final_supported"] / max(1, episodes["total"] - episodes["truth:unknown"]),
        "mean_first_route_turn": episodes["first_route_turn_sum"] / episodes["routed"] if episodes["routed"] else None,
        "matrix": {truth: dict(rows) for truth, rows in sorted(matrix.items())},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 1 if episodes["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

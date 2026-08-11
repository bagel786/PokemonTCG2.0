#!/usr/bin/env python3
"""Replay-state behavior audit for strategic v2 versus A2 and frozen v1."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.external import ExternalSubmissionAgent
from ptcg_ai.replay import load_episode
from training.lucario_data import canonical_deck, load_deck


DEFAULT_V2 = ROOT / "artifacts" / "strategic_playbook" / "extracted"
DEFAULT_V1 = ROOT / "artifacts" / "matchup_playbook" / "extracted" / "grimmsnarl_matchup_playbook"
DEFAULT_A2 = ROOT / "artifacts" / "recovery_probes" / "extracted" / "a2"


def truth_route(deck: tuple[int, ...]) -> str:
    ids = set(deck)
    for route, main in (
        ("grim", {647, 648}), ("alakazam", {742, 743}), ("lopunny", {849}),
        ("dragapult", {120, 121}), ("archaludon", {170, 190, 840}), ("crustle", {345}),
        ("lucario", {678}), ("dipplin", {90, 93}), ("garchomp", {342, 380, 381}),
        ("mewtwo", {401, 431}), ("bellibolt", {269}), ("starmie", {861, 1031}),
    ):
        if ids & main:
            return route
    if ids & {96, 108, 184, 272}:
        return "ogerpon"
    if 756 in ids:
        return "kangaskhan_generic"
    return "unknown"


def numeric_counter(value) -> Counter:
    return Counter({str(key): int(number) for key, number in dict(value).items()
                    if isinstance(number, (int, float))})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replays", type=Path, nargs="+", required=True)
    parser.add_argument("--v2", type=Path, default=DEFAULT_V2)
    parser.add_argument("--v1", type=Path, default=DEFAULT_V1)
    parser.add_argument("--a2", type=Path, default=DEFAULT_A2)
    parser.add_argument("--max-decisions", type=int, default=10_000)
    parser.add_argument("--max-traces", type=int, default=12)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    exact = load_deck(ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv")
    v2, v1, a2 = (ExternalSubmissionAgent(path) for path in (args.v2, args.v1, args.a2))
    counts, routes, objectives, phases = Counter(), defaultdict(Counter), Counter(), Counter()
    route_objectives = defaultdict(Counter)
    changed_turns: dict[tuple[int, int, int], list[dict]] = defaultdict(list)
    seen_paths: set[str] = set()
    objective_durations: list[int] = []
    termination = Counter()
    try:
        stop = False
        for replay_root in args.replays:
            if stop:
                break
            for path in sorted(replay_root.rglob("episode-*-replay.json")):
                resolved = str(path.resolve())
                if resolved in seen_paths:
                    continue
                seen_paths.add(resolved)
                try:
                    episode = load_episode(path)
                    steps = episode.get("steps") or []
                    if len(steps) < 2 or len(steps[1]) < 2:
                        continue
                    decks = [canonical_deck(steps[1][seat].get("action") or []) for seat in (0, 1)]
                    for seat in (0, 1):
                        if decks[seat] != exact:
                            continue
                        reset = {"select": None, "logs": [], "current": None, "search_begin_input": None}
                        v2(reset); v1(reset); a2(reset)
                        truth = truth_route(decks[1 - seat])
                        last_turn = 0
                        for step in steps:
                            if counts["decisions"] >= args.max_decisions:
                                stop = True
                                break
                            if seat >= len(step) or str(step[seat].get("status", "")).upper() != "ACTIVE":
                                continue
                            raw = step[seat].get("observation") or {}
                            if raw.get("select") is None or raw.get("current") is None:
                                continue
                            v2_action, v1_action, a2_action = v2(raw), v1(raw), a2(raw)
                            inner = v2.module._AGENT
                            last = dict(getattr(inner.policy, "last", {}))
                            route = str(last.get("route", "unknown"))
                            objective = str(last.get("objective", "unknown"))
                            phase = str(last.get("phase", "unknown"))
                            order = "second" if last.get("actual_second") else "first"
                            turn = int((raw.get("current") or {}).get("turn", 0) or 0)
                            own_turn = (turn + 1) // 2 if int((raw.get("current") or {}).get("firstPlayer", -1)) == seat else turn // 2
                            last_turn = max(last_turn, own_turn)
                            changed_a2, changed_v1 = v2_action != a2_action, v2_action != v1_action
                            counts["decisions"] += 1
                            counts[f"decisions_{order}"] += 1
                            counts["changes_vs_a2"] += changed_a2
                            counts["changes_vs_v1"] += changed_v1
                            counts[f"changes_vs_a2_{order}"] += changed_a2
                            counts[f"truth:{truth}"] += 1
                            if changed_a2:
                                semantic = last.get("semantic") or {}
                                counts[f"change_objective:{objective}"] += 1
                                counts[f"change_reason:{semantic.get('reason', 'none')}"] += 1
                                counts[f"change_context:{semantic.get('context', 'none')}"] += 1
                                counts[f"change_action:{semantic.get('reason', 'none')}:{semantic.get('type', 'none')}:{semantic.get('source_id', 'none')}"] += 1
                            routes[route]["decisions"] += 1
                            routes[route]["changes_vs_a2"] += changed_a2
                            objectives[objective] += 1
                            phases[phase] += 1
                            route_objectives[route][objective] += 1
                            key = (int(path.stem.split("-")[1]), seat, own_turn)
                            changed_turns[key].append({
                                "public_turn": turn, "route": route, "truth": truth, "phase": phase,
                                "objective": objective, "enforcement": last.get("enforcement"),
                                "objective_reason": last.get("objective_reason"), "target_serial": last.get("target_serial"),
                                "a2": a2_action, "v1": v1_action, "v2": v2_action,
                                "changed_vs_a2": changed_a2, "semantic": last.get("semantic"),
                            })
                        telemetry = numeric_counter(getattr(v2.module._AGENT.policy, "telemetry", {}))
                        counts["cross_turn_commitments"] += telemetry["cross_turn_commitments"]
                        for key, value in telemetry.items():
                            if key.startswith("termination:"):
                                termination[key.removeprefix("termination:")] += value
                        events = list(getattr(v2.module._AGENT.policy, "objective_events", []))
                        for index, event in enumerate(events):
                            end = int(events[index + 1]["turn"]) if index + 1 < len(events) else last_turn + 1
                            objective_durations.append(max(1, end - int(event["turn"])))
                    if stop:
                        break
                except Exception as exc:
                    counts["replay_failures"] += 1
                    if counts["replay_failures"] <= 5:
                        counts[f"failure:{type(exc).__name__}"] += 1
        changed_complete = [(key, rows) for key, rows in changed_turns.items() if any(row["changed_vs_a2"] for row in rows)]
        traces = [
            {"episode_id": key[0], "seat": key[1], "own_turn": key[2], "decisions": rows}
            for key, rows in changed_complete[:args.max_traces]
        ]
        result = {
            "candidate": str(args.v2.resolve()), "v1": str(args.v1.resolve()), "a2": str(args.a2.resolve()),
            "counts": dict(counts),
            "change_rate_vs_a2": counts["changes_vs_a2"] / max(1, counts["decisions"]),
            "change_rate_vs_v1": counts["changes_vs_v1"] / max(1, counts["decisions"]),
            "actual_first_change_rate": counts["changes_vs_a2_first"] / max(1, counts["decisions_first"]),
            "actual_second_change_rate": counts["changes_vs_a2_second"] / max(1, counts["decisions_second"]),
            "per_route": {
                route: {**dict(values), "change_rate_vs_a2": values["changes_vs_a2"] / max(1, values["decisions"])}
                for route, values in sorted(routes.items())
            },
            "objective_frequency": dict(objectives), "phase_frequency": dict(phases),
            "route_objective_frequency": {route: dict(values) for route, values in sorted(route_objectives.items())},
            "complete_turns_observed": len(changed_turns), "complete_turns_changed": len(changed_complete),
            "cross_turn_commitments": counts["cross_turn_commitments"],
            "average_objective_duration_own_turns": sum(objective_durations) / max(1, len(objective_durations)),
            "termination_reasons": dict(termination), "representative_complete_turn_traces": traces,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({key: result[key] for key in (
            "change_rate_vs_a2", "change_rate_vs_v1", "actual_first_change_rate",
            "actual_second_change_rate", "complete_turns_changed", "cross_turn_commitments"
        )}, indent=2))
        return 1 if counts["replay_failures"] else 0
    finally:
        v2.close(); v1.close(); a2.close()


if __name__ == "__main__":
    raise SystemExit(main())

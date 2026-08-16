#!/usr/bin/env python3
"""Replay-sequential scope audit for microsprint candidate packages."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

from ptcg_ai.external import ExternalSubmissionAgent  # noqa: E402


def semantic(select: dict, action: list[int]) -> tuple:
    fields = ("type", "number", "area", "index", "playerIndex", "inPlayArea", "inPlayIndex", "attackId")
    return tuple(tuple((field, (select["option"][i] or {}).get(field)) for field in fields) for i in action)


def intervention_reason(agent: ExternalSubmissionAgent, scope: str) -> str | None:
    router = getattr(agent.module, "_AGENT", None)
    order = getattr(router, "actual_order", None)
    selected = getattr(router, f"policy_{order}", None)
    policy = getattr(selected, "policy", None)
    if scope == "punk":
        return getattr(getattr(policy, "wave1_rail", None), "last_intervention", None)
    if scope == "damage":
        return getattr(getattr(policy, "damage_solver", None), "last_intervention", None)
    return getattr(policy, "escape_last_intervention", None)


def errors(agent: ExternalSubmissionAgent) -> int:
    return int(agent.errors) + int(getattr(getattr(agent.module, "_AGENT", None), "errors", 0) or 0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--replays", type=Path, default=ROOT / "data/replays/55399728")
    parser.add_argument("--submission-id", type=int, default=55399728)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scope", choices=("punk", "damage", "escape"), default="punk")
    args = parser.parse_args()
    metadata = json.loads((args.replays / "episodes_metadata.json").read_text())
    meta = {int(row["id"]): row for row in metadata}
    candidate = ExternalSubmissionAgent(args.candidate, {})
    control = ExternalSubmissionAgent(args.control, {})
    counts = Counter(); changes = []; latencies = []
    try:
        for path in sorted(args.replays.glob("episode-*-replay.json")):
            episode = int(path.stem.split("-")[1])
            hero = next(i for i, agent in enumerate(meta[episode]["agents"])
                        if int(agent.get("submissionId", -1)) == args.submission_id)
            replay = json.loads(path.read_text())
            candidate({"select": None, "current": None, "logs": []})
            control({"select": None, "current": None, "logs": []})
            for step_index, step in enumerate(replay.get("steps", [])):
                if hero >= len(step) or str(step[hero].get("status", "")).upper() != "ACTIVE":
                    continue
                obs = step[hero].get("observation") or {}
                select = obs.get("select")
                if not select or not obs.get("current"):
                    continue
                start = time.perf_counter(); candidate_action = candidate(obs)
                latencies.append((time.perf_counter() - start) * 1000)
                control_action = control(obs)
                counts["decisions"] += 1
                legal = lambda action: (
                    isinstance(action, list) and len(set(action)) == len(action)
                    and select["minCount"] <= len(action) <= select["maxCount"]
                    and all(isinstance(i, int) and 0 <= i < len(select["option"]) for i in action)
                )
                counts["candidate_illegal"] += int(not legal(candidate_action))
                reason = intervention_reason(candidate, args.scope)
                if reason:
                    counts[f"intervention:{reason}"] += 1
                changed = semantic(select, candidate_action) != semantic(select, control_action)
                counts["changed"] += int(changed)
                effect = (select.get("effect") or select.get("contextCard") or {}).get("id")
                context = int(select.get("context", -1))
                if args.scope == "punk":
                    scoped = effect == 648 and context in {21, 22, 43}
                elif args.scope == "damage":
                    scoped = (effect == 112 and context == 13) or (effect == 648 and context == 15)
                else:
                    scoped = reason in {
                        "variance_floor:attach_to_escape_dead_support",
                        "variance_floor:complete_escape_retreat",
                        "variance_floor:dead_support_retreat_to_ready_grim",
                        "variance_floor:escape_promote_ready_grim",
                    }
                counts["changed_outside_scope"] += int(changed and not scoped)
                if changed and len(changes) < 50:
                    changes.append({"episode": episode, "step": step_index,
                                    "order": "first" if obs["current"]["firstPlayer"] == hero else "second",
                                    "context": context, "effect": effect, "reason": reason,
                                    "control": control_action, "candidate": candidate_action})
    finally:
        candidate_errors, control_errors = errors(candidate), errors(control)
        candidate.close(); control.close()
    ordered = sorted(latencies)
    percentile = lambda p: ordered[min(len(ordered) - 1, int(p * len(ordered)))] if ordered else 0.0
    report = {
        "candidate": str(args.candidate), "control": str(args.control), "scope": args.scope,
        "replays": str(args.replays), "counts": dict(counts),
        "change_rate": counts["changed"] / max(1, counts["decisions"]),
        "candidate_errors": candidate_errors, "control_errors": control_errors,
        "latency_ms": {"p50": percentile(.50), "p95": percentile(.95), "p99": percentile(.99),
                       "max": max(latencies, default=0.0)},
        "representative_changes": changes,
        "passed_scope": not counts["candidate_illegal"] and not counts["changed_outside_scope"]
                        and not candidate_errors and not control_errors,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "representative_changes"}, indent=2))
    return 0 if report["passed_scope"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

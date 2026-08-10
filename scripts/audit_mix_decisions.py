#!/usr/bin/env python3
"""Measure replay-state action changes and legality for one mixed policy."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.external import ExternalSubmissionAgent
from ptcg_ai.replay import load_episode


def canonical(deck) -> tuple[int, ...]:
    return tuple(sorted(int(card) for card in deck))


def legal(obs: dict, action: list[int]) -> bool:
    select = obs["select"]
    count = len(select.get("option") or [])
    return (
        isinstance(action, list)
        and int(select.get("minCount", 0)) <= len(action) <= int(select.get("maxCount", 0))
        and len(set(action)) == len(action)
        and all(isinstance(index, int) and 0 <= index < count for index in action)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--a2", type=Path, default=ROOT / "artifacts/recovery_probes/extracted/a2")
    parser.add_argument("--d842", type=Path, default=ROOT / "artifacts/recovery_probes/extracted/control")
    parser.add_argument("--replays", type=Path, nargs="+", required=True)
    parser.add_argument("--limit", type=int, default=25_000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    candidate = ExternalSubmissionAgent(args.candidate)
    a2 = ExternalSubmissionAgent(args.a2)
    d842 = ExternalSubmissionAgent(args.d842)
    exact = canonical(candidate.deck)
    counts = Counter()
    try:
        stop = False
        for root in args.replays:
            for path in sorted(root.rglob("*.json")):
                if not (path.name.startswith("episode-") and path.name.endswith("-replay.json")):
                    continue
                try:
                    episode = load_episode(path)
                    steps = episode.get("steps") or []
                    seats = [seat for seat in (0, 1) if len(steps) > 1 and seat < len(steps[1])
                             and canonical(steps[1][seat].get("action") or []) == exact]
                    for seat in seats:
                        # Replay states are sequential within an episode. Reset every
                        # stateful submission at the same public deck handshake used
                        # by the competition runtime before starting a new episode.
                        inner = getattr(candidate.module, "_AGENT", None)
                        policy = getattr(inner, "policy", None)
                        if policy is not None and hasattr(policy, "reset"):
                            policy.reset()
                        for step in steps:
                            if seat >= len(step) or str(step[seat].get("status", "")).upper() != "ACTIVE":
                                continue
                            obs = step[seat].get("observation") or {}
                            select = obs.get("select")
                            if not select or not select.get("option") or obs.get("current") is None:
                                continue
                            before = (candidate.errors, a2.errors, d842.errors)
                            choice = candidate(obs); a2_choice = a2(obs); d842_choice = d842(obs)
                            counts["decisions"] += 1
                            order = "first" if int(obs["current"].get("firstPlayer", -1)) == seat else "second"
                            counts[f"decisions_{order}"] += 1
                            if sorted(choice) != sorted(a2_choice):
                                counts["changes_vs_a2"] += 1; counts[f"changes_vs_a2_{order}"] += 1
                                inner = getattr(candidate.module, "_AGENT", None)
                                policy = getattr(inner, "policy", None)
                                detail = getattr(policy, "last", {}) if policy is not None else {}
                                route = str(detail.get("route", "unknown"))
                                counts[f"changes_vs_a2_route:{route}"] += 1
                                reasons = detail.get("selected_reasons") or ["unattributed"]
                                for reason in reasons:
                                    counts[f"changes_vs_a2_reason:{reason}"] += 1
                                context = int(select.get("context", -1))
                                counts[f"changes_vs_a2_context:{context}"] += 1
                            if sorted(choice) != sorted(d842_choice):
                                counts["changes_vs_d842"] += 1; counts[f"changes_vs_d842_{order}"] += 1
                            if not legal(obs, choice):
                                counts["illegal"] += 1
                            if (candidate.errors, a2.errors, d842.errors) != before:
                                counts["exceptions"] += 1
                            if counts["decisions"] >= args.limit:
                                stop = True; break
                        if stop: break
                except Exception:
                    counts["replay_failures"] += 1
                if stop: break
            if stop: break
    finally:
        candidate.close(); a2.close(); d842.close()
    n = counts["decisions"]
    result = {"candidate": str(args.candidate.resolve()), "counts": dict(counts)}
    for baseline in ("a2", "d842"):
        result[f"change_rate_vs_{baseline}"] = counts[f"changes_vs_{baseline}"] / n if n else 0
        for order in ("first", "second"):
            total = counts[f"decisions_{order}"]
            result[f"change_rate_vs_{baseline}_{order}"] = counts[f"changes_vs_{baseline}_{order}"] / total if total else 0
    result["passed"] = counts["illegal"] == counts["exceptions"] == counts["replay_failures"] == 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

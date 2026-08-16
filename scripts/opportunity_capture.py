#!/usr/bin/env python3
"""Opportunity-capture analysis: replay raw target episodes through EXP-23 and
the dynamic router; find the first decision where the specialist disagrees with
the base; check whether the route was locked before that decision.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.external import ExternalSubmissionAgent  # noqa: E402
from scripts.eval_detector import load_handshake, classify_deck, target_of  # noqa: E402


def option_key(option: dict) -> tuple:
    return (
        option.get("type"),
        option.get("context"),
        option.get("cardId") or 0,
        option.get("attackId") or 0,
        option.get("area") or 0,
        option.get("inPlayArea") or 0,
        round((option.get("number") or 0) / 20, 6),
        round((option.get("count") or 0) / 10, 6),
        round((option.get("hp") or 0) / 400, 6),
        round((option.get("maxHp") or 0) / 400, 6),
        round((option.get("nEnergies") or 0) / 10, 6),
        round((option.get("nTools") or 0) / 4, 6),
        round((option.get("prizeValue") or 0) / 3, 6),
        int(option.get("appearThisTurn") or 0),
        int(option.get("playerIndex") or 0),
    )


def semantic(action: list[int], options: list[dict]) -> tuple:
    return tuple(sorted(option_key(options[i]) for i in action))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--base-package", default="/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/final_sprint/exp23_identity_trained")
    parser.add_argument("--router-package", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    results = []
    for path in sorted(Path(args.raw_dir).glob("*.json")):
        try:
            episode = json.loads(path.read_text())
        except Exception:
            continue
        decks = load_handshake(path)
        if decks is None:
            continue
        classes = [classify_deck(decks[s]) for s in (0, 1)]
        grim_seat = next((s for s in (0, 1) if classes[s] == "grim"), None)
        target_cls = next((classes[s] for s in (0, 1) if target_of(classes[s])), None)
        if grim_seat is None or target_cls is None:
            continue
        if target_of(target_cls) != args.target:
            continue
        steps = episode.get("steps") or []
        if len(steps) < 2:
            continue
        base_agent = ExternalSubmissionAgent(args.base_package, {})
        router_agent = ExternalSubmissionAgent(args.router_package, {})
        first_disagreement = None
        lock_time = None
        pending_time = None
        n_decisions = 0
        n_disagreements = 0
        forced = False
        detected = False
        for step_index in range(len(steps)):
            cell = steps[step_index][grim_seat]
            obs = cell.get("observation") or {}
            if not obs or obs.get("select") is None:
                if step_index == 0 and n_decisions == 0:
                    base_agent(obs)
                    router_agent(obs)
                continue
            select = obs.get("select") or {}
            ctx = int(select.get("context", -1))
            n_decisions += 1
            try:
                action_base = base_agent(obs)
            except Exception:
                action_base = None
            try:
                action_router = router_agent(obs)
            except Exception:
                action_router = None
            router_state = getattr(router_agent.module, "_AGENT", None)
            if router_state is not None:
                route = getattr(router_state, "route", None)
                pending = getattr(router_state, "pending", None)
                if lock_time is None and route == args.target:
                    lock_time = step_index
                if pending_time is None and (pending == args.target or route == args.target):
                    detected = True
                    pending_time = step_index
            if action_base is not None and action_router is not None:
                if semantic(action_base, select.get("option") or []) != semantic(action_router, select.get("option") or []):
                    n_disagreements += 1
                    if first_disagreement is None:
                        first_disagreement = step_index
            del action_base, action_router
        captured = None
        if first_disagreement is None:
            captured = "no_disagreements"
        elif lock_time is not None and lock_time <= first_disagreement:
            captured = "captured"
        else:
            captured = "missed"
        info = episode.get("info", {}) or {}
        results.append({
            "episode_id": str(info.get("EpisodeId", path.stem)),
            "archetype": target_cls,
            "first_disagreement": first_disagreement,
            "lock_time": lock_time,
            "detected": detected,
            "n_decisions": n_decisions,
            "n_disagreements": n_disagreements,
            "captured": captured,
        })

    report = {
        "games": len(results),
        "games_with_disagreement": sum(r["first_disagreement"] is not None for r in results),
        "capture_counts": dict(Counter(r["captured"] for r in results)),
        "opportunity_capture": (
            sum(r["captured"] == "captured" for r in results)
            / max(1, sum(r["captured"] in ("captured", "missed") for r in results))
        ),
        "never_detected": sum(not r["detected"] for r in results),
        "results": results,
    }
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True))
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

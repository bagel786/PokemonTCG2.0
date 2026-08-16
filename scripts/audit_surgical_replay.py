#!/usr/bin/env python3
"""Real-replay semantic audit of surgical rules.

Replays raw target-vs-Grim episodes through EXP-23 and the surgical package.
At each step where the surgical overlay fires, records the recorded teacher
action, EXP-23 action, and surgical action (semantic keys).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
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
    return tuple(sorted(option_key(options[i]) for i in action if i < len(options)))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--base-package", default="/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/final_sprint/exp23_identity_trained")
    parser.add_argument("--surg-package", required=True)
    parser.add_argument("--surg-env", default="dip_a,dip_b")
    parser.add_argument("--teams-filter", default="", help="comma-separated target teams to include")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    teams_filter = {t.strip() for t in args.teams_filter.split(",") if t.strip()}

    fires = []
    stats = Counter()
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
        info = episode.get("info", {}) or {}
        target_team = (info.get("TeamNames") or ["", ""])[1 - grim_seat]
        if teams_filter and target_team not in teams_filter:
            continue
        base_agent = ExternalSubmissionAgent(args.base_package, {})
        surg_agent = ExternalSubmissionAgent(
            args.surg_package,
            {"PTCG_TARGET_ROUTE": "force_" + args.target, "PTCG_SURGICAL": args.surg_env},
        )
        for step_index in range(len(steps)):
            if grim_seat >= len(steps[step_index]):
                continue
            cell = steps[step_index][grim_seat]
            obs = cell.get("observation") or {}
            if not obs or obs.get("select") is None:
                if step_index == 0:
                    base_agent(obs)
                    surg_agent(obs)
                continue
            select = obs.get("select") or {}
            recorded = cell.get("action") or []
            try:
                base_action = base_agent(obs)
            except Exception:
                base_action = None
            try:
                surg_action = surg_agent(obs)
            except Exception:
                surg_action = None
            router_state = getattr(surg_agent.module, "_AGENT", None)
            fire_log = None
            if router_state is not None:
                overlay = getattr(router_state, "surgical", None)
                if overlay is not None and getattr(overlay, "fires", []):
                    fire_log = list(overlay.fires)
                    overlay.fires.clear()
            if fire_log:
                options = select.get("option") or []
                stats["fires_total"] += len(fire_log)
                for fire in fire_log:
                    rule = fire["rule"]
                    stats[f"fires_{rule}"] += 1
                    rec_key = semantic(recorded, options)
                    base_key = semantic(base_action or [], options)
                    surg_key = semantic(surg_action or [], options)
                    side = None
                    if surg_key == rec_key:
                        side = "teacher_agrees_surgical"
                        stats[f"{rule}_teacher_agrees_surgical"] += 1
                    elif base_key == rec_key:
                        side = "teacher_agrees_base"
                        stats[f"{rule}_teacher_agrees_base"] += 1
                    else:
                        side = "teacher_neither"
                        stats[f"{rule}_teacher_neither"] += 1
                    fires.append({
                        "episode_id": str(info.get("EpisodeId", path.stem)),
                        "target_team": target_team,
                        "archetype": target_cls,
                        "rule": rule,
                        "side": side,
                        "turn": (obs.get("current") or {}).get("turn"),
                        "recorded": list(rec_key[:2]) if rec_key else None,
                        "base_semantic_len": len(base_key),
                        "surg_semantic_len": len(surg_key),
                    })

    report = {"stats": dict(stats), "fires": fires}
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True))
    print(json.dumps(dict(stats), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

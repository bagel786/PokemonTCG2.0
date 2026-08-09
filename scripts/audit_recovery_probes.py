#!/usr/bin/env python3
"""Replay every stored exact-Grim decision and classify all probe changes."""

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
from training.lucario_data import canonical_deck, load_deck

ALLOWED = {"setup_bench_basic", "nullified_attack", "end_with_productive_attack"}


def legal(observation: dict, action: list[int]) -> bool:
    select = observation.get("select") or {}
    count = len(select.get("option") or [])
    return (
        isinstance(action, list)
        and int(select.get("minCount", 0)) <= len(action) <= int(select.get("maxCount", 0))
        and len(set(action)) == len(action)
        and all(isinstance(index, int) and 0 <= index < count for index in action)
    )


def audit(probe_dir: Path, control_dir: Path, replay_root: Path, exact: tuple[int, ...]) -> dict:
    probe = ExternalSubmissionAgent(probe_dir)
    control = ExternalSubmissionAgent(control_dir)
    counts = Counter()
    examples = []
    try:
        for path in sorted(replay_root.rglob("*.json")):
            if not (
                (path.name.startswith("episode-") and path.name.endswith("-replay.json"))
                or path.stem.isdigit()
            ):
                continue
            try:
                episode = load_episode(path)
                steps = episode.get("steps") or []
                if len(steps) < 2:
                    continue
                seats = [
                    seat for seat in (0, 1)
                    if seat < len(steps[1]) and canonical_deck(steps[1][seat].get("action") or []) == exact
                ]
                if not seats:
                    continue
                counts["episodes"] += 1
                for seat in seats:
                    for step_index in range(len(steps) - 1):
                        if seat >= len(steps[step_index]):
                            continue
                        obs = steps[step_index][seat].get("observation") or {}
                        if obs.get("select") is None or obs.get("current") is None:
                            continue
                        before_probe_errors = probe.errors
                        before_control_errors = control.errors
                        control_action = control(obs)
                        probe_action = probe(obs)
                        counts["decisions"] += 1
                        if probe.errors != before_probe_errors or control.errors != before_control_errors:
                            counts["exceptions"] += 1
                        if not legal(obs, probe_action):
                            counts["invalid_actions"] += 1
                        reason = getattr(
                            getattr(getattr(probe.module, "_AGENT", None), "policy", None),
                            "shield_telemetry", None,
                        )
                        reason = getattr(reason, "last_intervention", None)
                        if probe_action != control_action:
                            counts["changed_actions"] += 1
                            if reason not in ALLOWED:
                                counts["unclassified_changes"] += 1
                                if len(examples) < 20:
                                    examples.append({
                                        "replay": str(path), "seat": seat, "step": step_index,
                                        "control": control_action, "probe": probe_action, "reason": reason,
                                    })
                            else:
                                counts[f"intervention_{reason}"] += 1
            except Exception as exc:
                counts["replay_parse_failures"] += 1
                if len(examples) < 20:
                    examples.append({"replay": str(path), "error": f"{type(exc).__name__}: {exc}"})
    finally:
        probe.close()
        control.close()
    return {
        "probe": str(probe_dir),
        "counts": dict(counts),
        "examples": examples,
        "passed": all(counts[key] == 0 for key in ("exceptions", "invalid_actions", "unclassified_changes", "replay_parse_failures")),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replays", default="data/replays")
    parser.add_argument("--output", default="artifacts/recovery_probes/replay_audit.json")
    args = parser.parse_args()
    exact = load_deck(ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv")
    extracted = ROOT / "artifacts" / "recovery_probes" / "extracted"
    report = {
        "a1": audit(extracted / "a1", extracted / "control", Path(args.replays), exact),
        "a2": audit(extracted / "a2", extracted / "a2_base", Path(args.replays), exact),
    }
    report["passed"] = all(row["passed"] for row in report.values())
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({name: row.get("counts") for name, row in report.items() if isinstance(row, dict)}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

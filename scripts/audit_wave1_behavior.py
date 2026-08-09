#!/usr/bin/env python3
"""Replay-bank scope and latency audit for a built Wave-1 package."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.external import ExternalSubmissionAgent


CONFIG = {
    "fan": {
        "team": "flg",
        "replays": ROOT / "artifacts" / "flg_grim_corpus_v5_causal" / "replays" / "55290684",
        "candidate": ROOT / "artifacts" / "wave1_push" / "extracted_fan_v2",
        "allowed": {"fan_attach", "fan_retain_no_target", "fan_energy", "fan_sink_known", "fan_sink_unknown"},
    },
    "tempo": {
        "team": "Larps",
        "replays": ROOT / "artifacts" / "recovery_ladder" / "replays" / "55323436",
        "candidate": ROOT / "artifacts" / "wave1_push" / "extracted_tempo_v2",
        "allowed": {
            "tempo_setup_active", "tempo_setup_bench_imp", "tempo_poffin_targets",
            "tempo_gym_search", "tempo_petrel_search", "tempo_candy_target",
            "tempo_play_candy", "tempo_use_gym_for_grim", "tempo_play_gym_for_grim",
            "tempo_petrel_for_gym", "tempo_petrel_for_candy", "tempo_take_morgrem",
            "tempo_play_poffin", "tempo_play_pad_before_draw", "tempo_play_gym",
            "tempo_use_gym", "tempo_bench_basic_before_draw", "tempo_preserve_candy_package",
            "punk_up_activate", "punk_up_energy_count", "punk_up_target",
            "munk_damage_source", "munk_damage_count",
        },
    },
}
BASE = ROOT / "artifacts" / "recovery_probes" / "extracted" / "a2"


def percentile(values: list[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(probability * len(ordered) + 0.999999) - 1))
    return ordered[index]


def rail_reason(agent: ExternalSubmissionAgent):
    inner = getattr(agent.module, "_AGENT", None)
    policy = getattr(inner, "policy", None)
    rail = getattr(policy, "wave1_rail", None)
    return getattr(rail, "last_intervention", None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=sorted(CONFIG), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = CONFIG[args.mode]
    candidate = ExternalSubmissionAgent(config["candidate"], {})
    base = ExternalSubmissionAgent(BASE, {})
    records = []
    reasons: Counter[str] = Counter()
    latencies = []
    changed = unclassified = unchanged = 0
    episodes = decisions = 0
    try:
        for replay_path in sorted(config["replays"].glob("*.json")):
            replay = json.loads(replay_path.read_text(encoding="utf-8"))
            teams = list((replay.get("info") or {}).get("TeamNames") or [])
            if config["team"] not in teams:
                continue
            seat = teams.index(config["team"])
            candidate({"select": None, "current": None, "logs": []})
            base({"select": None, "current": None, "logs": []})
            episode_used = False
            for step_index, step in enumerate(replay.get("steps") or []):
                if seat >= len(step):
                    continue
                observation = (step[seat] or {}).get("observation") or {}
                select = observation.get("select")
                current = observation.get("current")
                if not select or not current or int(current.get("yourIndex", -1)) != seat:
                    continue
                started = time.perf_counter()
                candidate_action = candidate(observation)
                latencies.append((time.perf_counter() - started) * 1000.0)
                base_action = base(observation)
                reason = rail_reason(candidate)
                if reason is not None:
                    reasons[str(reason)] += 1
                if candidate_action != base_action:
                    changed += 1
                    if reason not in config["allowed"]:
                        unclassified += 1
                else:
                    unchanged += 1
                records.append({
                    "episode": int((replay.get("info") or {}).get("EpisodeId", 0) or 0),
                    "step": step_index,
                    "action": list(candidate_action),
                    "base": list(base_action),
                    "reason": reason,
                })
                decisions += 1
                episode_used = True
            episodes += int(episode_used)
    finally:
        candidate_errors = candidate.errors + int(getattr(getattr(candidate.module, "_AGENT", None), "errors", 0) or 0)
        base_errors = base.errors + int(getattr(getattr(base.module, "_AGENT", None), "errors", 0) or 0)
        candidate.close()
        base.close()
    digest = hashlib.sha256(
        json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest().upper()
    result = {
        "mode": args.mode,
        "episodes": episodes,
        "decisions": decisions,
        "changed_actions": changed,
        "unchanged_actions": unchanged,
        "unclassified_changes": unclassified,
        "candidate_errors": candidate_errors,
        "base_errors": base_errors,
        "intervention_counts": dict(sorted(reasons.items())),
        "allowed_reasons": sorted(config["allowed"]),
        "p99_latency_ms": percentile(latencies, 0.99),
        "max_latency_ms": max(latencies, default=0.0),
        "decision_digest": digest,
        "passed": (
            decisions > 0 and changed > 0 and unchanged > 0 and unclassified == 0
            and candidate_errors == 0 and base_errors == 0
            and percentile(latencies, 0.99) <= 100.0 and max(latencies, default=0.0) <= 1000.0
            and set(reasons).issubset(config["allowed"])
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

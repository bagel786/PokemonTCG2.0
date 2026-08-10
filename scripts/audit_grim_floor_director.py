#!/usr/bin/env python3
"""Determinism, scope, coverage, and replay-agreement audit for the 5k director."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.external import ExternalSubmissionAgent

CANDIDATE = ROOT / "artifacts" / "grim_5k_floor_director" / "extracted_v1"
BASE = ROOT / "artifacts" / "recovery_probes" / "extracted" / "control"
LOCAL_GLOB = ROOT / "data" / "replays"
WAVE_LOCAL = ROOT / "artifacts" / "wave1_push" / "live" / "replays"
FLG = ROOT / "artifacts" / "flg_grim_corpus_v5_causal" / "replays" / "55290684"
FAN = 1161


def percentile(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, max(0, int(p * len(values))))] if values else 0.0


def option_card(obs, option):
    current = obs.get("current") or {}
    select = obs.get("select") or {}
    owner = option.get("playerIndex", current.get("yourIndex", 0))
    players = current.get("players") or []
    area = option.get("area")
    index = option.get("index")
    if option.get("type") in (7, "Play"):
        area = 2
    zones = {1: select.get("deck"), 2: "hand", 3: "discard", 4: "active", 5: "bench", 6: "prize", 7: current.get("stadium"), 12: current.get("looking")}
    zone = zones.get(area)
    if isinstance(zone, str) and 0 <= int(owner) < len(players):
        zone = players[int(owner)].get(zone)
    if isinstance(zone, list) and isinstance(index, int) and 0 <= index < len(zone):
        return zone[index]
    return None


def semantic(obs, action):
    select = obs.get("select") or {}
    options = select.get("option") or []
    result = []
    for index in action:
        if not isinstance(index, int) or not 0 <= index < len(options):
            result.append(("INVALID", index))
            continue
        option = options[index]
        source = option_card(obs, option) or {}
        result.append((
            option.get("type"), source.get("id"), option.get("attackId"), option.get("number"),
            option.get("playerIndex"), option.get("area"), option.get("index"),
            option.get("inPlayArea"), option.get("inPlayIndex"),
        ))
    return tuple(result)


def valid(obs, action):
    select = obs.get("select") or {}
    count = len(select.get("option") or [])
    minimum, maximum = int(select.get("minCount", 0)), int(select.get("maxCount", 0))
    return (
        isinstance(action, list) and minimum <= len(action) <= maximum
        and len(action) == len(set(action))
        and all(isinstance(i, int) and 0 <= i < count for i in action)
    )


def fan_only(obs, actual):
    select = obs.get("select") or {}
    for key in ("effect", "contextCard"):
        if int((select.get(key) or {}).get("id", 0) or 0) == FAN:
            return True
    options = select.get("option") or []
    return any(0 <= i < len(options) and int((option_card(obs, options[i]) or {}).get("id", 0) or 0) == FAN for i in actual)


def episode_files():
    # Adjacent metadata/report JSON files are not episodes and must not be
    # counted as replay parse failures.
    sources = [(p, "local", "Larps") for p in LOCAL_GLOB.glob("*/*replay.json")]
    # The local bank continued to grow after the original 205-replay plan was
    # written.  Include the complete current bank, deduplicated by episode.
    sources += [(p, "local", "Larps") for p in WAVE_LOCAL.glob("*/*replay.json")]
    sources += [(p, "top_flg", "flg") for p in FLG.glob("*.json")]
    episodes = {}
    parse_errors = []
    for path, source, team in sources:
        try:
            replay = json.loads(path.read_text(encoding="utf-8"))
            episode = int((replay.get("info") or {}).get("EpisodeId", 0) or replay.get("id", 0) or 0)
            if episode:
                episodes[(source, episode)] = (path, replay, source, team)
        except Exception as exc:
            parse_errors.append({"path": str(path), "error": type(exc).__name__})
    return list(episodes.values()), parse_errors


def lower_bound(rows, order=None, samples=10000):
    grouped = defaultdict(list)
    for row in rows:
        if order is None or row["order"] == order:
            grouped[row["episode"]].append(row)
    clusters = list(grouped.values())
    if not clusters:
        return 0.0
    rng = random.Random(842)
    diffs = []
    for _ in range(samples):
        chosen = [clusters[rng.randrange(len(clusters))] for _ in clusters]
        flat = [row for cluster in chosen for row in cluster]
        diffs.append(sum(r["candidate_match"] - r["base_match"] for r in flat) / len(flat))
    return percentile(diffs, 0.05)


def run_once():
    candidate = ExternalSubmissionAgent(CANDIDATE, {})
    base = ExternalSubmissionAgent(BASE, {})
    rows, records, latencies = [], [], []
    reasons, families, changed_episodes = Counter(), Counter(), set()
    invalid = exceptions = fan_excluded = 0
    files, parse_errors = episode_files()
    source_episodes = Counter()
    try:
        for path, replay, source, team in files:
            teams = list((replay.get("info") or {}).get("TeamNames") or [])
            seats = [i for i, name in enumerate(teams) if name == team]
            if not seats:
                continue
            episode = int((replay.get("info") or {}).get("EpisodeId", 0) or replay.get("id", 0) or 0)
            source_episodes[source] += 1
            for seat in seats:
                candidate({"select": None, "current": None, "logs": []})
                base({"select": None, "current": None, "logs": []})
                for step_index, step in enumerate(replay.get("steps") or []):
                    if seat >= len(step):
                        continue
                    cell = step[seat] or {}
                    obs = cell.get("observation") or {}
                    if not obs.get("select") or not obs.get("current"):
                        continue
                    if int(obs["current"].get("yourIndex", -1)) != seat:
                        continue
                    actual = cell.get("action")
                    if not isinstance(actual, list) or not actual:
                        continue
                    if fan_only(obs, actual):
                        fan_excluded += 1
                        continue
                    try:
                        started = time.perf_counter()
                        choice = candidate(obs)
                        latencies.append((time.perf_counter() - started) * 1000)
                        baseline = base(obs)
                    except Exception:
                        exceptions += 1
                        continue
                    if not valid(obs, choice):
                        invalid += 1
                    ctl = candidate.module._AGENT.policy.floor_controller
                    reason = ctl.last_intervention
                    csem, bsem, asem = semantic(obs, choice), semantic(obs, baseline), semantic(obs, actual)
                    changed = csem != bsem
                    if changed:
                        changed_episodes.add((source, episode, seat))
                        if reason:
                            reasons[reason] += 1
                            families[reason.split(":", 1)[0]] += 1
                    current = obs["current"]
                    order = "first" if int(current.get("firstPlayer", -1)) == seat else "second"
                    holdout = int(hashlib.sha256(f"{source}:{episode}".encode()).hexdigest()[:8], 16) % 5 == 0
                    row = {
                        "episode": f"{source}:{episode}:{seat}", "source": source, "order": order,
                        "holdout": holdout, "changed": changed, "reason": reason,
                        "candidate_match": int(csem == asem), "base_match": int(bsem == asem),
                    }
                    rows.append(row)
                    records.append((row, csem, bsem))
    finally:
        candidate_errors = candidate.errors + int(getattr(candidate.module._AGENT, "errors", 0) or 0)
        base_errors = base.errors + int(getattr(base.module._AGENT, "errors", 0) or 0)
        candidate.close()
        base.close()
    holdout = [r for r in rows if r["holdout"]]
    def stats(part):
        n = len(part)
        return {
            "decisions": n,
            "candidate_agreement": sum(r["candidate_match"] for r in part) / n if n else 0,
            "d842_agreement": sum(r["base_match"] for r in part) / n if n else 0,
            "agreement_lift": sum(r["candidate_match"] - r["base_match"] for r in part) / n if n else 0,
        }
    digest = hashlib.sha256(json.dumps(records, sort_keys=True, default=list, separators=(",", ":")).encode()).hexdigest().upper()
    coverage = {
        "classified_action_changes": sum(reasons.values()),
        "changed_episodes": len(changed_episodes),
        "families": dict(sorted(families.items())),
        "reasons": dict(sorted(reasons.items())),
    }
    holdout_stats = stats(holdout)
    first = [r for r in holdout if r["order"] == "first"]
    second = [r for r in holdout if r["order"] == "second"]
    result = {
        "source_episodes": dict(source_episodes), "parse_errors": parse_errors,
        "fan_only_decisions_excluded": fan_excluded, "rows": len(rows),
        "coverage": coverage, "all": stats(rows), "holdout": holdout_stats,
        "holdout_first": {**stats(first), "clustered_lower_bound": lower_bound(holdout, "first")},
        "holdout_second": {**stats(second), "clustered_lower_bound": lower_bound(holdout, "second")},
        "holdout_clustered_lower_bound": lower_bound(holdout),
        "invalid_actions": invalid, "exceptions": exceptions,
        "candidate_errors": candidate_errors, "base_errors": base_errors,
        "p99_latency_ms": percentile(latencies, .99), "max_latency_ms": max(latencies, default=0),
        "decision_digest": digest,
    }
    result["coverage_gate"] = (
        coverage["classified_action_changes"] >= 200 and coverage["changed_episodes"] >= 30
        and {"setup", "recovery", "resources", "matchups", "prize_conversion"}.issubset(families)
    )
    result["strength_proxy_gate"] = (
        holdout_stats["agreement_lift"] >= .08 and result["holdout_clustered_lower_bound"] >= .04
        and result["holdout_second"]["agreement_lift"] >= .08
        and result["holdout_second"]["clustered_lower_bound"] >= .02
        and result["holdout_first"]["clustered_lower_bound"] >= -.01
    )
    result["safety_gate"] = (
        invalid == exceptions == candidate_errors == base_errors == 0
        and result["p99_latency_ms"] <= 100 and result["max_latency_ms"] <= 1000
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "grim_5k_floor_director" / "replay_audit.json")
    args = parser.parse_args()
    first = run_once()
    second = run_once()
    first["deterministic_second_digest"] = second["decision_digest"]
    first["determinism_gate"] = first["decision_digest"] == second["decision_digest"]
    first["passed"] = first["coverage_gate"] and first["strength_proxy_gate"] and first["safety_gate"] and first["determinism_gate"]
    args.output.write_text(json.dumps(first, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(first, indent=2, sort_keys=True))
    return 0 if first["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

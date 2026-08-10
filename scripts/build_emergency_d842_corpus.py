#!/usr/bin/env python3
"""Build a focused actual-second training corpus and replay analysis.

This intentionally consumes the reconciled ``data/replays/<submission>`` tree
directly.  Exact d842, PPO, modified-PLAY, and search-disabled trajectories are
kept as distinct sources.  The output is a schema-2 decision shard suitable for
a conservative fine-tune initialized from d842.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor"), str(ROOT / "scripts")]

import numpy as np
from cg.api import to_observation_class

from ptcg_ai.features import DecisionFeatures
from ptcg_ai.model import NumpyPolicyModel
from ptcg_ai.replay import episode_order, iter_decisions, load_episode
from ptcg_ai.safety import sanitize_selection
from build_grim_policy_disagreements import semantic_action
from analyze_d842_floor_failures import option_label


REFERENCE = {
    55171235, 55180261, 55189658, 55198075, 55198084, 55222011,
    55246709, 55246712, 55278940, 55278944, 55280574, 55280578,
    55323437, 55358290, 55358291, 55397264, 55397271,
}
ALTERNATE = {55114709: "ppo_5k", 55335500: "modified_play", 55389103: "search_disabled"}


def canonical_deck(cards) -> tuple[int, ...]:
    try:
        return tuple(sorted(int(card) for card in cards)) if len(cards) == 60 else ()
    except (TypeError, ValueError):
        return ()


def replay_deck(replay: dict, seat: int) -> tuple[int, ...]:
    for step in replay.get("steps") or []:
        if seat < len(step):
            action = step[seat].get("action")
            if isinstance(action, list) and len(action) == 60:
                return canonical_deck(action)
    return ()


def metadata_map(directory: Path) -> dict[int, dict]:
    path = directory / "episodes_metadata.json"
    return {int(row["id"]): row for row in json.loads(path.read_text(encoding="utf-8"))}


def agent_for(row: dict, submission_id: int) -> tuple[int, dict, dict] | None:
    agents = row.get("agents") or []
    own = next((agent for agent in agents if int(agent.get("submissionId", -1)) == submission_id), None)
    if own is None or len(agents) != 2:
        return None
    seat = int(own.get("index", 0) or 0)
    return seat, own, agents[1 - seat]


def labels(observation: dict, action: list[int]) -> str:
    semantic = semantic_action(observation, action)
    parts = [option_label(item) for item in semantic.get("options", [])]
    return "+".join(parts) if parts else "EMPTY"


def d842_choice(model: NumpyPolicyModel, decision) -> tuple[list[int], float]:
    features = DecisionFeatures.from_json(decision.features)
    logits, count_logits, _ = model.predict(features)
    if not len(logits):
        return [], 0.0
    ranked = np.argsort(-logits).astype(int).tolist()
    select = to_observation_class(decision.observation).select
    if select.minCount == select.maxCount:
        desired = int(select.maxCount)
    else:
        minimum = int(select.minCount)
        maximum = min(int(select.maxCount), len(count_logits) - 1)
        desired = minimum + int(np.argmax(count_logits[minimum:maximum + 1]))
    ordered = np.sort(logits)[::-1]
    margin = float(ordered[0] - ordered[1]) if len(ordered) > 1 else float("inf")
    return sanitize_selection(select, ranked, desired), margin


def stable_split(episode_id: int) -> str:
    digest = hashlib.sha256(f"emergency-d842-{episode_id}".encode()).digest()
    return "validation" if digest[0] < 26 else "train"


def safe_float(value) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-root", type=Path, default=ROOT / "data" / "replays")
    parser.add_argument("--model", type=Path, default=ROOT / "artifacts" / "recovery_probes" / "extracted" / "control" / "policy_weights.npz")
    parser.add_argument("--deck", type=Path, default=ROOT / "artifacts" / "recovery_probes" / "extracted" / "control" / "deck.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "emergency_d842" / "actual_second.jsonl.gz")
    parser.add_argument("--analysis", type=Path, default=ROOT / "artifacts" / "emergency_d842" / "replay_analysis.json")
    args = parser.parse_args()

    expected = canonical_deck([int(line) for line in args.deck.read_text().splitlines() if line.strip()])
    model = NumpyPolicyModel(args.model)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    seen_trajectories: set[tuple[int, int]] = set()
    lineage_stats: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    divergence_groups: dict[str, dict] = {}
    first_divergences: list[dict] = []
    decisions_written = 0
    episodes_used = collections.Counter()
    source_weights = collections.Counter()

    with gzip.open(args.output, "wt", encoding="utf-8", compresslevel=6) as output:
        for submission_id in sorted(REFERENCE | set(ALTERNATE)):
            directory = args.replay_root / str(submission_id)
            if not directory.is_dir() or not (directory / "episodes_metadata.json").exists():
                continue
            meta = metadata_map(directory)
            lineage = "exact_d842" if submission_id in REFERENCE else ALTERNATE[submission_id]
            for replay_path in sorted(directory.glob("episode-*-replay.json")):
                episode_id = int(replay_path.name.split("-")[1])
                metadata = meta.get(episode_id)
                if metadata is None:
                    continue
                found = agent_for(metadata, submission_id)
                if found is None:
                    continue
                seat, hero, opponent = found
                replay = load_episode(replay_path)
                hero_deck = replay_deck(replay, seat)
                opponent_deck = replay_deck(replay, 1 - seat)
                if hero_deck != expected:
                    continue
                _, _, first_player = episode_order(replay)
                hero_order = "first" if first_player == seat else "second"
                win = float(hero.get("reward", 0) or 0) > 0
                hero_rating = safe_float(hero.get("initialScore"))
                opponent_rating = safe_float(opponent.get("initialScore"))
                rating_gap = (opponent_rating - hero_rating) if hero_rating is not None and opponent_rating is not None else None
                exact_mirror = opponent_deck == expected

                stats = lineage_stats[lineage]
                stats["games"] += 1; stats["wins"] += int(win)
                stats[f"order_{hero_order}"] += 1; stats[f"order_{hero_order}_wins"] += int(win)
                stats["mirrors"] += int(exact_mirror); stats["mirror_wins"] += int(exact_mirror and win)
                stats["opponent_850_plus"] += int(opponent_rating is not None and opponent_rating >= 850)
                stats["opponent_850_plus_wins"] += int(win and opponent_rating is not None and opponent_rating >= 850)
                stats["relative_75_plus"] += int(rating_gap is not None and rating_gap >= 75)
                stats["relative_75_plus_wins"] += int(win and rating_gap is not None and rating_gap >= 75)

                # Candidate training is an actual-second specialist.  Exact d842
                # supplies broad rehearsal, while wins and successful natural
                # perturbations receive the larger weights.
                trajectories: list[tuple[int, str, float, bool]] = []
                if hero_order == "second":
                    if lineage == "exact_d842":
                        weight = 2.0 if win else 0.30
                    else:
                        weight = 2.5 if win else 0.12
                    if win and (opponent_rating or 0) >= 850:
                        weight *= 1.4
                    trajectories.append((seat, lineage, weight, win))

                # A winning same-deck opponent is exact-observation evidence.
                opponent_order = "first" if first_player == 1 - seat else "second"
                if exact_mirror and not win and opponent_order == "second":
                    weight = 4.0 if rating_gap is None or rating_gap >= 0 else 2.5
                    trajectories.append((1 - seat, "winning_mirror_opponent", weight, True))

                for actor_seat, source, weight, actor_win in trajectories:
                    trajectory_key = (episode_id, actor_seat)
                    if trajectory_key in seen_trajectories:
                        continue
                    seen_trajectories.add(trajectory_key)
                    episode_decisions = 0
                    for decision in iter_decisions(replay, feature_version=2, include_observation=False):
                        if decision.seat != actor_seat:
                            continue
                        row = decision.to_json()
                        row["sample_weight"] = weight
                        row["split"] = stable_split(episode_id)
                        row["source_lineage"] = source
                        row["source_submission_id"] = submission_id
                        row["opponent_initial_rating"] = opponent_rating if actor_seat == seat else hero_rating
                        row["relative_rating_gap"] = rating_gap if actor_seat == seat else (-rating_gap if rating_gap is not None else None)
                        row["exact_mirror"] = exact_mirror
                        row["reward"] = float(actor_win)
                        output.write(json.dumps(row, separators=(",", ":")) + "\n")
                        episode_decisions += 1
                    if episode_decisions:
                        decisions_written += episode_decisions
                        episodes_used[source] += 1
                        source_weights[source] += episode_decisions * weight

                # Compare frozen d842 with the winning mirror opponent, recording
                # only the first post-setup semantic disagreement per episode.
                if exact_mirror and not win:
                    first = None
                    for decision in iter_decisions(replay, feature_version=2, include_observation=True):
                        if decision.seat != 1 - seat or decision.turn < 1 or decision.observation is None:
                            continue
                        predicted, margin = d842_choice(model, decision)
                        actual_sem = semantic_action(decision.observation, decision.action)
                        predicted_sem = semantic_action(decision.observation, predicted)
                        if actual_sem == predicted_sem:
                            continue
                        actual_label = labels(decision.observation, decision.action)
                        predicted_label = labels(decision.observation, predicted)
                        key = f"{predicted_label} -> {actual_label}"
                        record = {
                            "episode_id": episode_id,
                            "submission_id": submission_id,
                            "opponent_submission_id": opponent.get("submissionId"),
                            "opponent_team_id": opponent.get("teamId"),
                            "actor_order": opponent_order,
                            "opponent_initial_rating": opponent_rating,
                            "relative_rating_gap": rating_gap,
                            "turn": decision.turn,
                            "own_turn_ordinal": decision.own_turn_ordinal,
                            "d842_margin": margin,
                            "d842_action": predicted_label,
                            "winner_action": actual_label,
                        }
                        first = record
                        group = divergence_groups.setdefault(key, {"count": 0, "episodes": set(), "opponents": set(), "orders": collections.Counter(), "ratings": [], "gaps": [], "margins": [], "turns": []})
                        group["count"] += 1; group["episodes"].add(episode_id)
                        group["opponents"].add(str(opponent.get("submissionId") or opponent.get("teamId")))
                        group["orders"][opponent_order] += 1; group["margins"].append(margin); group["turns"].append(decision.turn)
                        if opponent_rating is not None: group["ratings"].append(opponent_rating)
                        if rating_gap is not None: group["gaps"].append(rating_gap)
                        break
                    if first:
                        first_divergences.append(first)

    ranked = []
    for difference, group in divergence_groups.items():
        finite_margins = [x for x in group["margins"] if math.isfinite(x)]
        ranked.append({
            "difference": difference,
            "episodes": len(group["episodes"]),
            "independent_opponents": len(group["opponents"]),
            "actual_order": dict(group["orders"]),
            "mean_opponent_rating": sum(group["ratings"]) / len(group["ratings"]) if group["ratings"] else None,
            "mean_relative_rating_gap": sum(group["gaps"]) / len(group["gaps"]) if group["gaps"] else None,
            "mean_d842_margin": sum(finite_margins) / len(finite_margins) if finite_margins else None,
            "mean_turn": sum(group["turns"]) / len(group["turns"]),
            "approximate_decision_coverage": len(group["episodes"]) / max(1, len(first_divergences)),
            "causal_assessment": "causal_candidate_first_meaningful_divergence",
        })
    ranked.sort(key=lambda row: (-row["episodes"], -row["independent_opponents"]))
    payload = {
        "schema_version": 1,
        "reference_submission_ids": sorted(REFERENCE),
        "alternate_submission_ids": {str(key): value for key, value in ALTERNATE.items()},
        "lineage_statistics": {key: dict(value) for key, value in sorted(lineage_stats.items())},
        "training_corpus": {
            "path": str(args.output.resolve()), "decisions": decisions_written,
            "episodes_by_source": dict(episodes_used), "weighted_decisions_by_source": dict(source_weights),
            "actual_order": "second_only", "feature_version": 2,
        },
        "mirror_first_divergences": first_divergences,
        "largest_recurring_differences": ranked[:20],
    }
    args.analysis.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"analysis": str(args.analysis), "decisions": decisions_written, "episodes": dict(episodes_used), "top_differences": ranked[:10]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

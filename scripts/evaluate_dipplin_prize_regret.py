#!/usr/bin/env python3
"""Deterministic public complete-turn Prize-route regret for Dipplin."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / "vendor").is_dir():
    sys.path.insert(0, str(ROOT / "vendor"))

from cg.api import OptionType, SelectContext, SelectType, to_observation_class  # noqa: E402
from ptcg_ai.dipplin.cards import (  # noqa: E402
    BASIC_POKEMON,
    BLACK_BELT,
    BOSS,
    BRAVE_BANGLE,
    DIPPLIN,
    DO_THE_WAVE,
    FESTIVAL,
    GRASS_ENERGY,
    THWACKEY,
)
from ptcg_ai.dipplin.resolvers import option_card_id  # noqa: E402
from ptcg_ai.dipplin.search import METRIC_FIELDS  # noqa: E402
from ptcg_ai.replay import episode_order, own_turn_ordinal  # noqa: E402
from scripts.dipplin_eval_common import integer, parse_dataset_args, write_json  # noqa: E402
from scripts.evaluate_dipplin_expert_regret import ChronologicalS1  # noqa: E402
from scripts.evaluate_dipplin_replay_regret import (  # noqa: E402
    _branch_metric,
    _load_json_replay,
    aligned_visualizer_frame,
    rng_or_deck_touch,
    semantic_action_key,
    validate_exact_hidden,
)


SCHEMA = "dipplin-prize-regret-v1"
PRIZE_INDEX = METRIC_FIELDS.index("prizes_taken_this_turn")
PRODUCTIVE_INDEX = METRIC_FIELDS.index("productive_attacks_completed")
CENTRAL_KO_INDEX = METRIC_FIELDS.index("opponent_central_attacker_ko")
SECOND_TARGET_INDEX = METRIC_FIELDS.index("first_attack_ko_unlocked_second_target")
REPLACEMENT_INDEX = METRIC_FIELDS.index("replacement_attacker_ready")


def _dimension(obs: Any, index: int) -> str | None:
    option = obs.select.option[index]
    option_type = integer(option.type)
    card_id = option_card_id(obs, index)
    attack_id = integer(getattr(option, "attackId", None))
    if option_type == int(OptionType.ATTACK) and attack_id == DO_THE_WAVE:
        return "ATTACK_NOW"
    if option_type == int(OptionType.PLAY) and card_id in BASIC_POKEMON:
        return "BENCH_EXPANSION"
    if card_id == BOSS:
        return "BOSS"
    if card_id == BRAVE_BANGLE:
        return "BRAVE_BANGLE"
    if card_id == BLACK_BELT:
        return "BLACK_BELT"
    if card_id == FESTIVAL:
        return "FESTIVAL"
    if option_type == int(OptionType.ATTACH) and card_id == GRASS_ENERGY:
        return "ENERGY"
    if option_type == int(OptionType.EVOLVE) and card_id == DIPPLIN:
        return "EVOLVE_DIPPLIN"
    if option_type == int(OptionType.RETREAT):
        return "RETREAT"
    if option_type == int(OptionType.ABILITY) and card_id == THWACKEY:
        return "BOOM_BOOM_GROOVE"
    return None


def _root_candidates(obs: Any) -> list[tuple[list[int], str]]:
    if integer(obs.select.type) != int(SelectType.MAIN) or integer(obs.select.context) != int(SelectContext.MAIN):
        return []
    result: list[tuple[list[int], str]] = []
    for index in range(len(obs.select.option or [])):
        dimension = _dimension(obs, index)
        if dimension is not None:
            result.append(([index], dimension))
    return result


def _metric(obs: Any, action: Sequence[int], hidden: Mapping[str, Any], memory: Any, planner: Any, category: str) -> tuple[float, ...] | None:
    try:
        if rng_or_deck_touch(obs, action):
            return None
        return _branch_metric(obs, action, hidden, memory, planner, category=category)
    except Exception:
        return None


def _cause(best_dimension: str, best: Sequence[float], selected: Sequence[float] | None) -> str:
    if selected is None:
        return "OTHER"
    if best[PRIZE_INDEX] <= selected[PRIZE_INDEX]:
        return "OTHER"
    if best_dimension == "BOSS":
        return "MISSED_BOSS_ROUTE"
    if best_dimension in {"BRAVE_BANGLE", "BLACK_BELT"}:
        return "MISSED_MODIFIER"
    if best_dimension == "BENCH_EXPANSION":
        return "INSUFFICIENT_BENCH"
    if best_dimension == "ATTACK_NOW":
        if selected[PRODUCTIVE_INDEX] <= 0:
            return "UNNECESSARY_SETUP_BEFORE_ATTACK"
        if best[CENTRAL_KO_INDEX] > selected[CENTRAL_KO_INDEX]:
            return "MISSED_FIRST_HIT_KO"
        if best[SECOND_TARGET_INDEX] > selected[SECOND_TARGET_INDEX]:
            return "MISSED_SECOND_TARGET"
    if best[REPLACEMENT_INDEX] < selected[REPLACEMENT_INDEX]:
        return "CONTINUITY_OVER_CURRENT_PRESSURE"
    if best[PRODUCTIVE_INDEX] <= 0:
        return "NO_ATTACK_PATH"
    return "WRONG_TARGET"


def evaluate_episode(spec: Any, *, cap: int) -> list[dict[str, Any]]:
    replay = _load_json_replay(spec.path)
    steps = replay.get("steps") or []
    seat = spec.hero_seat
    policy = ChronologicalS1()
    _chooser, _choice, first_player = episode_order(replay)
    rows: list[dict[str, Any]] = []
    for step_index in range(max(0, len(steps) - 1)):
        current, following = steps[step_index], steps[step_index + 1]
        if not isinstance(current, list) or not isinstance(following, list) or seat >= len(current) or seat >= len(following):
            continue
        row, next_row = current[seat], following[seat]
        if str(row.get("status") or "").upper() != "ACTIVE":
            continue
        raw = row.get("observation") or {}
        if raw.get("current") is None or raw.get("select") is None or not isinstance(next_row.get("action"), list):
            continue
        obs = to_observation_class(raw)
        expert = list(map(int, next_row["action"]))
        agent, working, proposal, proposal_error = policy.propose(raw, obs)
        candidates = _root_candidates(obs)
        if candidates and len(rows) < cap and proposal_error is None:
            try:
                frame = aligned_visualizer_frame(replay, step_index, obs)
                hidden = validate_exact_hidden(obs, frame)
                planner = policy.planner
                evaluated: list[tuple[list[int], str, tuple[float, ...]]] = []
                for action, dimension in candidates:
                    metric = _metric(obs, action, hidden, working, planner, f"prize_regret_{dimension.lower()}")
                    if metric is not None:
                        evaluated.append((action, dimension, metric))
                # The state is meaningful only when Do the Wave is already
                # available or a deterministic public root enables an attack.
                if evaluated and max(item[2][PRODUCTIVE_INDEX] for item in evaluated) > 0:
                    best_action, best_dimension, best_metric = max(
                        evaluated,
                        key=lambda item: (
                            item[2][PRIZE_INDEX], item[2][PRODUCTIVE_INDEX],
                            item[2][CENTRAL_KO_INDEX], item[2][SECOND_TARGET_INDEX],
                        ),
                    )
                    expert_metric = _metric(obs, expert, hidden, working, planner, "prize_regret_expert")
                    agent_metric = _metric(obs, agent, hidden, working, planner, "prize_regret_s1")
                    for actor, selected_action, selected_metric in (
                        ("expert", expert, expert_metric), ("s1", agent, agent_metric)
                    ):
                        achieved = int(selected_metric[PRIZE_INDEX]) if selected_metric is not None else None
                        available = int(best_metric[PRIZE_INDEX])
                        rows.append({
                            "episode_id": spec.episode_id,
                            "dataset": spec.dataset,
                            "split": spec.split,
                            "step": step_index,
                            "actor": actor,
                            "actual_order": "first" if seat == first_player else "second",
                            "opening_active": spec.metadata.get("opening_active", "unknown"),
                            "opponent_archetype": spec.opponent_archetype,
                            "own_turn_ordinal": own_turn_ordinal(integer(obs.current.turn), seat, first_player),
                            "guaranteed_prizes_available": available,
                            "guaranteed_prizes_achieved": achieved,
                            "prize_regret": (available - achieved) if achieved is not None else None,
                            "best_route_dimension": best_dimension,
                            "likely_cause": _cause(best_dimension, best_metric, selected_metric),
                            "best_semantic": repr(semantic_action_key(obs, best_action)),
                            "selected_semantic": repr(semantic_action_key(obs, selected_action)),
                            "certifiable": selected_metric is not None,
                        })
            except Exception:
                pass
        policy.commit_expert(obs, expert, working)
    return rows


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    certifiable = [row for row in rows if row.get("certifiable")]
    episode_ids = {integer(row["episode_id"]) for row in rows}
    regret_episodes = {integer(row["episode_id"]) for row in certifiable if integer(row.get("prize_regret"), 0) > 0}
    return {
        "episode_count": len(episode_ids),
        "state_actor_rows": len(rows),
        "certifiable_rows": len(certifiable),
        "positive_regret_rows": sum(integer(row.get("prize_regret"), 0) > 0 for row in certifiable),
        "positive_regret_episode_count": len(regret_episodes),
        "mean_prize_regret": (
            sum(integer(row.get("prize_regret"), 0) for row in certifiable) / len(certifiable)
            if certifiable else None
        ),
        "cause_counts": dict(sorted(Counter(str(row.get("likely_cause")) for row in certifiable if integer(row.get("prize_regret"), 0) > 0).items())),
    }


def grouped(rows: Sequence[Mapping[str, Any]], field: str) -> dict[str, Any]:
    groups = defaultdict(list)
    for row in rows:
        groups[str(row.get(field) or "unknown")].append(row)
    return {key: summarize(value) for key, value in sorted(groups.items())}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", action="append", required=True, help="LABEL=manifest.json")
    parser.add_argument("--splits", default="DEV,VALIDATION")
    parser.add_argument("--opponent-archetype", help="optional exact manifest archetype filter")
    parser.add_argument("--cap-per-episode", type=int, default=8)
    parser.add_argument("--include-states", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    splits = {value.strip().upper() for value in args.splits.split(",") if value.strip()}
    if args.include_states and "SEALED" in splits:
        raise SystemExit("per-state SEALED output is forbidden")
    specs = parse_dataset_args(args.dataset, splits=splits)
    if args.opponent_archetype:
        specs = [spec for spec in specs if spec.opponent_archetype == args.opponent_archetype]
    rows = [row for spec in specs for row in evaluate_episode(spec, cap=args.cap_per_episode)]
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "statistical_unit": "episode",
        "method": "relevant deterministic public root actions, identical aligned reconstruction, S1 continuation through hero-turn end",
        "overall": summarize(rows),
        "by_actor": grouped(rows, "actor"),
        "by_actual_order": grouped(rows, "actual_order"),
        "by_opening_active": grouped(rows, "opening_active"),
        "by_opponent_archetype": grouped(rows, "opponent_archetype"),
        "by_cause": grouped(rows, "likely_cause"),
    }
    if args.include_states:
        payload["state_rows"] = rows
    write_json(args.output, payload)
    print(json.dumps({"schema": SCHEMA, "episodes": payload["overall"]["episode_count"], "output": str(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

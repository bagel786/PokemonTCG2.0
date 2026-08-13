#!/usr/bin/env python3
"""Expert-vs-current-S1 completed-turn regret on important replay states.

This evaluator adapts the existing certified regret machinery to the requested
S1 comparison and decision-family vocabulary.  Semantic equivalence is checked
before branching.  Differing actions are advanced through the hero turn from
the same aligned full replay state; RNG/hidden-deck or reconstruction ambiguity
is classified ``UNCERTIFIABLE`` rather than guessed.
"""

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
    BROCK,
    DIPPLIN,
    DO_THE_WAVE,
    FESTIVAL,
    HILDA,
    LILLIE,
    NIGHT_STRETCHER,
    SACRED_ASH,
    THWACKEY,
)
from ptcg_ai.dipplin.policy import FestivalD0Planner, semantic_final_action  # noqa: E402
from ptcg_ai.dipplin.resolvers import PromptResolver, effect_id, option_card_id  # noqa: E402
from ptcg_ai.dipplin.search import D1Config, FestivalD1Search  # noqa: E402
from ptcg_ai.dipplin.snapshot import PlanMemory, PlanSnapshot  # noqa: E402
from ptcg_ai.dipplin.telemetry import Telemetry  # noqa: E402
from ptcg_ai.replay import episode_order, own_turn_ordinal  # noqa: E402
from ptcg_ai.safety import emergency_selection, sanitize_selection  # noqa: E402
from scripts.dipplin_eval_common import integer, parse_dataset_args, write_json  # noqa: E402
from scripts.evaluate_dipplin_replay_regret import (  # noqa: E402
    RegretError,
    _branch_metric,
    _load_json_replay,
    aligned_visualizer_frame,
    componentwise_label,
    rng_or_deck_touch,
    semantic_action_key,
    semantic_actions_equivalent,
    validate_exact_hidden,
)


SCHEMA = "dipplin-expert-regret-v1"
CLASSIFICATIONS = ("EXPERT_DOMINATES", "AGENT_DOMINATES", "EQUIVALENT", "INCOMPARABLE", "UNCERTIFIABLE")


class ChronologicalS1:
    def __init__(self) -> None:
        self.planner = FestivalD0Planner(go_first=True)
        self.planner.second_opening_v2 = True
        self.planner.resolver = PromptResolver(go_first=True, second_opening_v2=True)
        self.planner.route_v2_enabled = False
        self.memory = PlanMemory()
        self.telemetry = Telemetry()
        self.search = FestivalD1Search(self.planner, self.telemetry, D1Config(worlds=2), s2_enabled=False)

    def propose(self, raw: Mapping[str, Any], obs: Any) -> tuple[list[int], PlanMemory, Any, str | None]:
        working = self.memory.clone()
        try:
            snapshot = PlanSnapshot.from_observation(obs, working)
            proposal = self.planner.propose(obs, snapshot, working)
            baseline = sanitize_selection(obs.select, list(proposal.intent.ranked_indices), proposal.intent.desired_count)
            action = self.search.choose(raw, obs, snapshot, working, proposal, baseline)
            return list(action), working, proposal, None
        except Exception as exc:
            return list(emergency_selection(obs.select)), working, None, f"{type(exc).__name__}:{exc}"

    def commit_expert(self, obs: Any, action: Sequence[int], working: PlanMemory) -> None:
        self.memory = working
        self.memory.commit(semantic_final_action(obs, list(action), "recorded_replay", "expert chronological action"))


def _selected_types(obs: Any, *actions: Sequence[int]) -> set[int]:
    return {integer(obs.select.option[index].type) for action in actions for index in action}


def _selected_cards(obs: Any, *actions: Sequence[int]) -> set[int]:
    return {option_card_id(obs, index) for action in actions for index in action}


def decision_family(obs: Any, expert: Sequence[int], agent: Sequence[int]) -> str:
    context = integer(obs.select.context)
    select_type = integer(obs.select.type)
    cards = _selected_cards(obs, expert, agent)
    types = _selected_types(obs, expert, agent)
    parent = effect_id(obs)
    if context in {int(SelectContext.TO_ACTIVE), int(SelectContext.SWITCH)} or int(OptionType.RETREAT) in types:
        return "RETREAT_OR_PROMOTION"
    if parent == THWACKEY:
        return "BOOM_BOOM_GROOVE_TARGET"
    if select_type == int(SelectType.MAIN):
        attacks = {
            integer(getattr(obs.select.option[index], "attackId", None))
            for action in (expert, agent) for index in action
        }
        if DO_THE_WAVE in attacks:
            return "ATTACK_NOW_VS_DEVELOP"
        if BOSS in cards:
            return "BOSS"
        if BRAVE_BANGLE in cards:
            return "BANGLE"
        if BLACK_BELT in cards:
            return "BLACK_BELT"
        if int(OptionType.ATTACH) in types:
            return "ENERGY_TARGET"
        if cards & {HILDA, LILLIE}:
            return "HILDA_VS_LILLIE"
        if cards & {NIGHT_STRETCHER, SACRED_ASH}:
            return "RECOVERY"
        if int(OptionType.EVOLVE) in types:
            return "REPLACEMENT_DEVELOPMENT"
        if int(OptionType.PLAY) in types and bool(cards & (set(BASIC_POKEMON) | {140})):
            return "BENCH_EXPANSION"
    if cards & {NIGHT_STRETCHER, SACRED_ASH, BROCK}:
        return "RECOVERY"
    return "OTHER"


def _important(obs: Any, expert: Sequence[int], agent: Sequence[int]) -> bool:
    family = decision_family(obs, expert, agent)
    if family != "OTHER":
        return True
    return integer(obs.select.context) in {
        int(SelectContext.SETUP_ACTIVE_POKEMON),
        int(SelectContext.SETUP_BENCH_POKEMON),
    }


def evaluate_episode(spec: Any, *, cap: int) -> list[dict[str, Any]]:
    replay = _load_json_replay(spec.path)
    steps = replay.get("steps") or []
    seat = spec.hero_seat
    policy = ChronologicalS1()
    _chooser, _choice, first_player = episode_order(replay)
    rows: list[dict[str, Any]] = []
    for step_index in range(max(0, len(steps) - 1)):
        if len(rows) >= cap:
            break
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
        if not _important(obs, expert, agent):
            policy.commit_expert(obs, expert, working)
            continue
        equivalent = False
        classification = "UNCERTIFIABLE"
        reason: str | None = None
        expert_metric = agent_metric = None
        try:
            equivalent = semantic_actions_equivalent(obs, expert, agent)
            if equivalent:
                classification = "EQUIVALENT"
            elif proposal_error:
                reason = "policy_error"
            elif rng_or_deck_touch(obs, expert) or rng_or_deck_touch(obs, agent):
                reason = "rng_or_hidden_deck_unseeded"
            else:
                frame = aligned_visualizer_frame(replay, step_index, obs)
                hidden = validate_exact_hidden(obs, frame)
                planner = FestivalD0Planner(go_first=True)
                planner.second_opening_v2 = True
                planner.resolver = PromptResolver(go_first=True, second_opening_v2=True)
                planner.route_v2_enabled = False
                expert_metric = _branch_metric(obs, expert, hidden, working, planner, category="expert_regret_expert")
                agent_metric = _branch_metric(obs, agent, hidden, working, planner, category="expert_regret_s1")
                classification = componentwise_label([expert_metric], [agent_metric])
        except Exception as exc:
            reason = f"{type(exc).__name__}:{exc}"[:200]
        family = decision_family(obs, expert, agent)
        rows.append({
            "episode_id": spec.episode_id,
            "dataset": spec.dataset,
            "split": spec.split,
            "step": step_index,
            "own_turn_ordinal": own_turn_ordinal(integer(obs.current.turn), seat, first_player),
            "actual_order": "first" if seat == first_player else "second",
            "opening_active": spec.metadata.get("opening_active", "unknown"),
            "opponent_archetype": spec.opponent_archetype,
            "decision_family": family,
            "classification": classification,
            "semantic_equivalent": equivalent,
            "uncertifiable_reason": reason,
            "expert_semantic": repr(semantic_action_key(obs, expert)),
            "agent_semantic": repr(semantic_action_key(obs, agent)),
            "expert_metric": list(expert_metric) if expert_metric is not None else None,
            "agent_metric": list(agent_metric) if agent_metric is not None else None,
        })
        policy.commit_expert(obs, expert, working)
    return rows


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    episodes = {integer(row["episode_id"]) for row in rows}
    counts = Counter(str(row["classification"]) for row in rows)
    per_episode = defaultdict(Counter)
    for row in rows:
        per_episode[integer(row["episode_id"])][str(row["classification"])] += 1
    return {
        "episode_count": len(episodes),
        "decision_count": len(rows),
        "classification_counts": {name: counts[name] for name in CLASSIFICATIONS},
        "expert_dominates_episode_count": sum(counter["EXPERT_DOMINATES"] > 0 for counter in per_episode.values()),
        "agent_dominates_episode_count": sum(counter["AGENT_DOMINATES"] > 0 for counter in per_episode.values()),
        "expert_dominates_episode_rate": (
            sum(counter["EXPERT_DOMINATES"] > 0 for counter in per_episode.values()) / len(per_episode)
            if per_episode else None
        ),
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
    parser.add_argument("--cap-per-episode", type=int, default=40)
    parser.add_argument("--include-decisions", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    splits = {value.strip().upper() for value in args.splits.split(",") if value.strip()}
    if args.include_decisions and "SEALED" in splits:
        raise SystemExit("per-decision SEALED output is forbidden")
    specs = parse_dataset_args(args.dataset, splits=splits)
    if args.opponent_archetype:
        specs = [spec for spec in specs if spec.opponent_archetype == args.opponent_archetype]
    rows = [row for spec in specs for row in evaluate_episode(spec, cap=args.cap_per_episode)]
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "statistical_unit": "episode",
        "method": "semantic equivalence then identical aligned state, S1 continuation to hero-turn end; ambiguity fails closed",
        "overall": summarize(rows),
        "by_actual_order": grouped(rows, "actual_order"),
        "by_opening_active": grouped(rows, "opening_active"),
        "by_opponent_archetype": grouped(rows, "opponent_archetype"),
        "by_decision_family": grouped(rows, "decision_family"),
    }
    if args.include_decisions:
        payload["decision_rows"] = rows
    write_json(args.output, payload)
    print(json.dumps({"schema": SCHEMA, "episodes": payload["overall"]["episode_count"], "output": str(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

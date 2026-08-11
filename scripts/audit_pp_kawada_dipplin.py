#!/usr/bin/env python3
"""Compare FESTIVAL-D0 with the recorded PP Kawada action at every replay prompt.

The replay format stores the action for observation ``t`` in step ``t + 1``.
Shadow planner memory is reconciled from the replay observation and commits the
recorded action, not D0's proposal, so one disagreement cannot contaminate all
later comparisons.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / "vendor").is_dir():
    sys.path.insert(0, str(ROOT / "vendor"))

from cg.api import AreaType, OptionType, SelectContext, SelectType, to_observation_class  # noqa: E402
from ptcg_ai.dipplin.cards import (  # noqa: E402
    BLACK_BELT,
    BOSS,
    BRAVE_BANGLE,
    DECK_CSV_SHA256,
    DIPPLIN,
    FESTIVAL,
    HILDA,
    LILLIE,
    UNFAIR_STAMP,
)
from ptcg_ai.dipplin.policy import (  # noqa: E402
    FestivalD0Planner,
    semantic_final_action,
)
from ptcg_ai.dipplin.resolvers import (  # noqa: E402
    effect_id,
    option_card_id,
    option_source,
    option_target,
)
from ptcg_ai.dipplin.snapshot import PlanMemory, PlanSnapshot  # noqa: E402
from ptcg_ai.safety import sanitize_selection  # noqa: E402


SCHEMA = "dipplin-pp-kawada-replay-audit-v1"
SUBMISSION_ID = 55408594


def _int(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _card_identity(card: Any) -> tuple[int, int, int] | None:
    if card is None:
        return None
    card_id = _int(getattr(card, "id", None))
    serial = _int(getattr(card, "serial", None))
    player = _int(getattr(card, "playerIndex", None))
    return None if card_id < 0 or serial < 0 else (card_id, serial, player)


def _semantic_option(obs: Any, index: int) -> tuple[Any, ...]:
    option = obs.select.option[index]
    source = option_source(obs, option)
    target = option_target(obs, option)
    option_type = _int(getattr(option, "type", None))
    # Face-down prizes are interchangeable and must not be distinguished by a
    # hidden prompt index.
    opaque_prize = (
        option_type == int(OptionType.CARD)
        and _int(getattr(option, "area", None)) == int(AreaType.PRIZE)
        and source is None
    )
    return (
        option_type,
        "opaque_prize" if opaque_prize else _card_identity(source),
        _card_identity(target),
        _int(getattr(option, "attackId", None)),
        _int(getattr(option, "number", None)),
        _int(getattr(option, "count", None)),
        _int(getattr(option, "playerIndex", None)),
        _int(getattr(option, "specialConditionType", None)),
    )


def _semantic_action(obs: Any, action: Sequence[int]) -> tuple[Any, ...]:
    return tuple(sorted(_semantic_option(obs, int(index)) for index in action))


def _own_turn_ordinal(turn: int, seat: int, first_player: int) -> int:
    first_turn = 1 if seat == first_player else 2
    return 0 if turn < first_turn else ((turn - first_turn) // 2) + 1


def _category(obs: Any, recorded: Sequence[int], proposed: Sequence[int], resolver: str) -> str:
    context = _int(getattr(obs.select, "context", None))
    select_type = _int(getattr(obs.select, "type", None))
    parent = effect_id(obs)
    if context in {int(SelectContext.SETUP_ACTIVE_POKEMON), int(SelectContext.SETUP_BENCH_POKEMON)}:
        return "setup"
    if context == int(SelectContext.TO_ACTIVE):
        return "promotion"
    if select_type != int(SelectType.MAIN):
        if parent in {88, 90, 1086, 1094, 1097, 1129, 1152, 1210, 1225}:
            return "search_target"
        return "sequencing"

    def first(indexes: Sequence[int]) -> tuple[int, int, int]:
        if not indexes:
            return (-1, -1, -1)
        index = int(indexes[0])
        option = obs.select.option[index]
        return (
            _int(getattr(option, "type", None)),
            option_card_id(obs, index),
            _int(getattr(option, "attackId", None)),
        )

    rec_type, rec_card, rec_attack = first(recorded)
    d0_type, d0_card, d0_attack = first(proposed)
    cards = {rec_card, d0_card}
    if FESTIVAL in cards:
        return "festival_timing"
    if rec_type == int(OptionType.ATTACH) or d0_type == int(OptionType.ATTACH):
        return "attachment"
    if rec_type == int(OptionType.EVOLVE) or d0_type == int(OptionType.EVOLVE):
        return "replacement_development"
    if rec_type == int(OptionType.ATTACK) or d0_type == int(OptionType.ATTACK):
        return "attack_threshold"
    if cards & {BOSS, UNFAIR_STAMP}:
        return "disruption"
    if cards & {BLACK_BELT, HILDA, LILLIE}:
        return "supporter_choice"
    if BRAVE_BANGLE in cards:
        return "attack_threshold"
    if rec_attack >= 0 or d0_attack >= 0:
        return "attack_threshold"
    if resolver.startswith(("energy_", "evolve_")):
        return "replacement_development"
    return "sequencing"


def _episode_seats(cache: Mapping[str, Any], episode_id: int) -> list[int]:
    row = (cache.get("episodes") or {}).get(str(episode_id))
    if not isinstance(row, list) or len(row) < 2:
        return []
    agents = row[1]
    return [
        index
        for index, agent in enumerate(agents)
        if _int((agent or {}).get("submissionId")) == SUBMISSION_ID
    ]


def _valid_recorded(obs: Any, action: Sequence[int]) -> bool:
    minimum = _int(getattr(obs.select, "minCount", None), 0)
    maximum = _int(getattr(obs.select, "maxCount", None), 0)
    values = [int(index) for index in action]
    return (
        minimum <= len(values) <= maximum
        and len(values) == len(set(values))
        and all(0 <= index < len(obs.select.option) for index in values)
    )


def audit_episode(path: Path, seats: Iterable[int]) -> list[dict[str, Any]]:
    replay = json.loads(path.read_text(encoding="utf-8"))
    episode_id = _int((replay.get("info") or {}).get("EpisodeId"))
    steps = replay.get("steps") or []
    rows: list[dict[str, Any]] = []
    for seat in seats:
        planner = FestivalD0Planner(go_first=True)
        memory = PlanMemory()
        seat_rows: list[dict[str, Any]] = []
        for step_index in range(max(0, len(steps) - 1)):
            current = steps[step_index][seat]
            following = steps[step_index + 1][seat]
            raw = current.get("observation") or {}
            if current.get("status") != "ACTIVE" or raw.get("select") is None:
                continue
            recorded = list(following.get("action") or [])
            obs = to_observation_class(raw)
            if not _valid_recorded(obs, recorded):
                continue
            snapshot = PlanSnapshot.from_observation(obs, memory)
            proposal = planner.propose(obs, snapshot, memory)
            proposed = sanitize_selection(
                obs.select,
                list(proposal.intent.ranked_indices),
                proposal.intent.desired_count,
            )
            same = _semantic_action(obs, recorded) == _semantic_action(obs, proposed)
            recorded_action = semantic_final_action(
                obs, recorded, "recorded_replay", "PP Kawada"
            )
            d0_action = semantic_final_action(
                obs, proposed, proposal.intent.resolver, proposal.intent.reason
            )
            turn = _int(getattr(obs.current, "turn", None), 0)
            first_player = _int(getattr(obs.current, "firstPlayer", None))
            row = {
                "episode": episode_id,
                "replay_sha256": _sha256(path),
                "seat": seat,
                "step": step_index,
                "turn": turn,
                "own_turn_ordinal": _own_turn_ordinal(turn, seat, first_player),
                "first_player": first_player,
                "actual_order": "first" if first_player == seat else "second",
                "select_type": _int(getattr(obs.select, "type", None)),
                "context": _int(getattr(obs.select, "context", None)),
                "parent_card_id": effect_id(obs),
                "resolver": proposal.intent.resolver,
                "reason": proposal.intent.reason,
                "recorded_action": recorded,
                "d0_action": proposed,
                "recorded_semantic": repr(_semantic_action(obs, recorded)),
                "d0_semantic": repr(_semantic_action(obs, proposed)),
                "recorded_kind": recorded_action.kind,
                "recorded_card_id": recorded_action.card_id,
                "recorded_source_lineage": recorded_action.source_lineage,
                "recorded_target_lineage": recorded_action.target_lineage,
                "recorded_attack_id": recorded_action.attack_id,
                "d0_kind": d0_action.kind,
                "d0_card_id": d0_action.card_id,
                "d0_source_lineage": d0_action.source_lineage,
                "d0_target_lineage": d0_action.target_lineage,
                "d0_attack_id": d0_action.attack_id,
                "agrees": same,
            }
            if not same:
                row["category"] = _category(
                    obs, recorded, proposed, proposal.intent.resolver
                )
            seat_rows.append(row)
            memory.commit(
                recorded_action,
                decision_key=(episode_id, seat, step_index),
            )
        prize_turns = {
            row["turn"]
            for row in seat_rows
            if row["resolver"] == "prize"
        }
        for row in seat_rows:
            row["first_two_hero_turns"] = 0 < row["own_turn_ordinal"] <= 2
            row["prize_turn"] = row["turn"] in prize_turns
        rows.extend(seat_rows)
    return rows


def _summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    disagreements = [row for row in rows if not row["agrees"]]
    by_category = Counter(str(row.get("category", "agree")) for row in disagreements)
    by_resolver = Counter(str(row["resolver"]) for row in disagreements)

    def cell(selected: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        different = sum(not row["agrees"] for row in selected)
        return {
            "decisions": len(selected),
            "disagreements": different,
            "agreement_rate": (len(selected) - different) / len(selected) if selected else 0.0,
        }

    return {
        "overall": cell(rows),
        "first_two_hero_turns": cell([row for row in rows if row["first_two_hero_turns"]]),
        "prize_turns": cell([row for row in rows if row["prize_turn"]]),
        "actual_order": {
            order: cell([row for row in rows if row["actual_order"] == order])
            for order in ("first", "second")
        },
        "disagreement_categories": dict(sorted(by_category.items())),
        "disagreement_d0_resolvers": dict(sorted(by_resolver.items())),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replays", type=Path, required=True)
    parser.add_argument("--crawl-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    cache = json.loads(args.crawl_cache.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    files = sorted(args.replays.glob("episode-*-replay.json"))
    for path in files:
        replay = json.loads(path.read_text(encoding="utf-8"))
        episode_id = _int((replay.get("info") or {}).get("EpisodeId"))
        rows.extend(audit_episode(path, _episode_seats(cache, episode_id)))
    payload = {
        "schema": SCHEMA,
        "submission_id": SUBMISSION_ID,
        "deck_csv_sha256": DECK_CSV_SHA256,
        "replay_files": len(files),
        "audited_episodes": len({row["episode"] for row in rows}),
        "summary": _summary(rows),
        "disagreements": [row for row in rows if not row["agrees"]],
        "all_decisions": rows,
    }
    if not all(math.isfinite(float(value)) for value in (len(files), len(rows))):
        raise RuntimeError("non-finite audit count")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), **payload["summary"]["overall"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

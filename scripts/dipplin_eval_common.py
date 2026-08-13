#!/usr/bin/env python3
"""Shared, read-only replay measurements for the Dipplin expert audit.

The helpers in this file deliberately consume only the hero observation and
the action aligned at replay step ``t + 1``.  Opponent hands, facedown Prize
identities, visualizer full-state frames, and ``search_begin_input`` are never
read by the descriptive opening/engine evaluators.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / "vendor").is_dir():
    sys.path.insert(0, str(ROOT / "vendor"))

from cg.api import AreaType, OptionType, SelectContext, SelectType, to_observation_class  # noqa: E402
from ptcg_ai.dipplin.cards import (  # noqa: E402
    BASIC_POKEMON,
    APPLIN_DRAGON,
    APPLIN_GRASS,
    BLACK_BELT,
    BOSS,
    BRAVE_BANGLE,
    DIPPLIN,
    DO_THE_WAVE,
    FESTIVAL,
    GRASS_ENERGY,
    GROOKEY,
    QUICK_SIGN,
    SHAYMIN,
    THWACKEY,
    VOLBEAT,
)
from ptcg_ai.dipplin.damage import _prize_value, project_do_the_wave  # noqa: E402
from ptcg_ai.dipplin.resolvers import effect_id, option_card_id  # noqa: E402
from ptcg_ai.replay import episode_order, episode_reward, own_turn_ordinal  # noqa: E402
from scripts.dipplin_second_trace import public_board_snapshot  # noqa: E402


OPENING_BUCKETS = (
    "grookey_active",
    "volbeat_active_quick_sign_legal",
    "volbeat_active_quick_sign_unavailable",
    "applin_42_active",
    "applin_92_active",
    "shaymin_active",
    "other",
)


def integer(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_deck_hash(deck: Sequence[int]) -> str:
    return hashlib.sha256(",".join(map(str, sorted(map(int, deck)))).encode()).hexdigest()


def replay_decks(replay: Mapping[str, Any]) -> tuple[tuple[int, ...], tuple[int, ...]]:
    steps = replay.get("steps") or []
    if len(steps) < 2 or not isinstance(steps[1], list) or len(steps[1]) < 2:
        raise ValueError("replay has no two-seat deck handshake")
    decks: list[tuple[int, ...]] = []
    for seat in (0, 1):
        action = steps[1][seat].get("action") if isinstance(steps[1][seat], Mapping) else None
        if not isinstance(action, list) or len(action) != 60:
            raise ValueError("replay deck handshake is absent or malformed")
        decks.append(tuple(map(int, action)))
    return decks[0], decks[1]


def infer_dipplin_seat(replay: Mapping[str, Any]) -> int:
    decks = replay_decks(replay)
    scored: list[tuple[int, int]] = []
    for seat, deck in enumerate(decks):
        counts = Counter(deck)
        score = (
            5 * counts[DIPPLIN]
            + 3 * (counts[APPLIN_DRAGON] + counts[APPLIN_GRASS])
            + 3 * counts[THWACKEY]
            + 2 * counts[FESTIVAL]
        )
        scored.append((score, seat))
    scored.sort(reverse=True)
    if scored[0][0] < 20 or scored[0][0] == scored[1][0]:
        raise ValueError("Dipplin seat is absent or ambiguous")
    return scored[0][1]


@dataclass(frozen=True)
class ReplaySpec:
    dataset: str
    split: str
    episode_id: int
    path: Path
    hero_seat: int
    pilot: str
    submission_id: int | None
    opponent_archetype: str
    opponent_prize_structure: str | None
    exact_deck_hash: str | None
    source_timestamp: str | None
    metadata: Mapping[str, Any]


def _resolve_path(raw: object, manifest_path: Path) -> Path:
    supplied = Path(str(raw)).expanduser()
    candidates = [supplied] if supplied.is_absolute() else [ROOT / supplied, manifest_path.parent / supplied]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(f"replay path does not exist: {raw}")


def load_manifest_specs(
    manifest_path: Path,
    *,
    dataset: str | None = None,
    splits: set[str] | None = None,
) -> list[ReplaySpec]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = payload.get("episodes") or []
    result: list[ReplaySpec] = []
    for row in rows:
        split = str(row.get("split") or payload.get("split") or "UNSPECIFIED").upper()
        if splits is not None and split not in splits:
            continue
        hero = row.get("hero") or {}
        opponent = row.get("opponent") or {}
        result.append(
            ReplaySpec(
                dataset=dataset or str(payload.get("dataset") or manifest_path.stem),
                split=split,
                episode_id=integer(row.get("episode_id")),
                path=_resolve_path(row.get("replay_cache_path"), manifest_path),
                hero_seat=integer(hero.get("seat")),
                pilot=str(hero.get("pilot") or row.get("pilot") or "unknown"),
                submission_id=(integer(hero.get("submission_id")) if hero.get("submission_id") is not None else None),
                opponent_archetype=str(opponent.get("archetype") or row.get("opponent_archetype") or "unknown"),
                opponent_prize_structure=opponent.get("prize_structure"),
                exact_deck_hash=hero.get("deck_sha256") or row.get("exact_deck_hash"),
                source_timestamp=row.get("source_timestamp"),
                metadata=row,
            )
        )
    if not result:
        raise ValueError(f"manifest has no selected episodes: {manifest_path}")
    return result


def load_directory_specs(directory: Path, *, dataset: str, submission_id: int | None = None) -> list[ReplaySpec]:
    metadata_path = directory / "episodes_metadata.json"
    metadata_rows = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else []
    by_id = {integer(row.get("id")): row for row in metadata_rows if isinstance(row, Mapping)}
    if submission_id is None:
        try:
            submission_id = int(directory.name)
        except ValueError:
            submission_id = None
    result: list[ReplaySpec] = []
    for path in sorted(directory.glob("episode-*-replay.json")):
        replay = json.loads(path.read_text(encoding="utf-8"))
        episode_id = integer((replay.get("info") or {}).get("EpisodeId", replay.get("id")))
        meta = by_id.get(episode_id, {})
        agents = meta.get("agents") or []
        seat: int | None = None
        if submission_id is not None:
            seats = [index for index, agent in enumerate(agents) if integer(agent.get("submissionId")) == submission_id]
            if len(seats) == 1:
                seat = seats[0]
            elif len(seats) == 2:
                # Same-submission mirrors do not identify a unique live hero
                # and are outside the rated-sample comparison.
                continue
        if seat is None:
            seat = infer_dipplin_seat(replay)
        opponent = agents[1 - seat] if len(agents) == 2 else {}
        result.append(
            ReplaySpec(
                dataset=dataset,
                split="LIVE",
                episode_id=episode_id,
                path=path.resolve(),
                hero_seat=seat,
                pilot=str((replay.get("info") or {}).get("TeamNames", ["unknown", "unknown"])[seat]),
                submission_id=submission_id,
                opponent_archetype="unknown",
                opponent_prize_structure=None,
                exact_deck_hash=canonical_deck_hash(replay_decks(replay)[seat]),
                source_timestamp=meta.get("createTime"),
                metadata={"opponent": opponent, "api": meta},
            )
        )
    if not result:
        raise ValueError(f"directory contains no replays: {directory}")
    return result


def parse_dataset_args(values: Sequence[str], *, splits: set[str] | None = None) -> list[ReplaySpec]:
    specs: list[ReplaySpec] = []
    for value in values:
        if "=" not in value:
            raise ValueError("--dataset must be LABEL=PATH")
        label, raw_path = value.split("=", 1)
        path = Path(raw_path).expanduser().resolve()
        if path.is_dir():
            specs.extend(load_directory_specs(path, dataset=label))
        else:
            specs.extend(load_manifest_specs(path, dataset=label, splits=splits))
    seen: set[tuple[str, int]] = set()
    for spec in specs:
        key = (spec.dataset, spec.episode_id)
        if key in seen:
            raise ValueError(f"duplicate dataset episode: {key}")
        seen.add(key)
    return specs


def load_local_trace_rows(values: Sequence[str]) -> list[dict[str, Any]]:
    """Normalize existing local S1 second-bucket traces for evaluator reuse.

    The historical trace has exact attack timing/boards but only game-total
    Prize count, so per-engine-turn Prize fields remain ``None`` rather than
    being imputed.
    """

    result: list[dict[str, Any]] = []
    for value in values:
        if "=" not in value:
            raise ValueError("--local-evaluation must be LABEL=PATH")
        label, raw_path = value.split("=", 1)
        path = Path(raw_path).expanduser().resolve()
        payload = json.loads(path.read_text(encoding="utf-8"))
        for game in payload.get("game_rows") or []:
            trace = game.get("second_bucket_trace") or {}
            if not trace or trace.get("collection_complete") is False:
                continue
            turns: list[dict[str, Any]] = []
            engine_turns: list[dict[str, Any]] = []
            for turn in trace.get("turn_records") or []:
                board = turn.get("end_board") or {}
                normalized = {
                    "global_turn": turn.get("global_turn"),
                    "own_turn_ordinal": turn.get("own_turn"),
                    "prizes_taken": None,
                    "do_wave_attacks": turn.get("do_wave_attacks", 0),
                    "first_hit_ko": bool(turn.get("first_hit_kos", 0)),
                    "first_hit_prizes": None,
                    "second_hit_prizes": None,
                    "double_prize_window": None,
                    "engine_online": bool(
                        board.get("active_id") == DIPPLIN
                        and board.get("active_ready")
                        and board.get("festival_active")
                        and int(board.get("thwackey_count") or 0) > 0
                        and int(turn.get("do_wave_attacks") or 0) > 0
                    ),
                    "end_board": board,
                }
                turns.append(normalized)
                if normalized["engine_online"]:
                    engine_turns.append(normalized)
            first_engine = engine_turns[0] if engine_turns else None
            first_attack_board = trace.get("first_attack_board")
            result.append({
                "dataset": label,
                "split": "LOCAL",
                "episode_id": f"{path.stem}:{game.get('game_index')}",
                "pilot": "S1",
                "submission_id": None,
                "actual_order": trace.get("actual_order", game.get("actual_order")),
                "opening_active_id": trace.get("opening_active_id"),
                "opening_bucket": trace.get("opening_bucket", "other"),
                "quick_sign_legal": bool(trace.get("quick_sign_legal")),
                "quick_sign_used": bool((game.get("hero_telemetry") or {}).get("quick_sign_taken", 0)),
                "completed": bool(game.get("completed")),
                "win": game.get("outcome") == "win",
                "opponent_archetype": game.get("opponent_name", payload.get("opponent_name", "unknown")),
                "opponent_prize_structure": "unknown",
                "first_do_wave_own_turn": trace.get("first_productive_attack_own_turn"),
                "first_prize_own_turn": None,
                "first_festival_double_attack_own_turn": trace.get("first_festival_double_attack_own_turn"),
                "first_attack_board": first_attack_board,
                "first_attack_resources": None,
                "first_engine_online_own_turn": first_engine.get("own_turn_ordinal") if first_engine else None,
                "first_engine_turn": first_engine,
                "first_engine_board": first_attack_board if first_engine else None,
                "first_engine_resources": None,
                "engine_turns": engine_turns,
                "turns": turns,
                "boom_boom_targets": [],
                "game_total_prizes_taken": trace.get("prizes_taken"),
                "source_timestamp": None,
                "replay_sha256": None,
                "local_trace_limitations": [
                    "first Prize own-turn unavailable",
                    "per-engine-turn Prize count unavailable",
                    "double-Prize-window timing unavailable",
                ],
            })
    return result


def aligned_actions(replay: Mapping[str, Any], seat: int) -> Iterator[tuple[int, dict[str, Any], Any, list[int]]]:
    steps = replay.get("steps") or []
    for step_index in range(max(0, len(steps) - 1)):
        current, following = steps[step_index], steps[step_index + 1]
        if not isinstance(current, list) or not isinstance(following, list) or seat >= len(current) or seat >= len(following):
            continue
        row = current[seat]
        if str(row.get("status") or "").upper() != "ACTIVE":
            continue
        raw = row.get("observation") or {}
        if raw.get("current") is None or raw.get("select") is None:
            continue
        action = following[seat].get("action")
        if not isinstance(action, list):
            continue
        obs = to_observation_class(raw)
        if integer(obs.current.yourIndex) != seat:
            continue
        options = list(obs.select.option or [])
        if len(action) != len(set(action)) or any(integer(index) < 0 or integer(index) >= len(options) for index in action):
            continue
        yield step_index, raw, obs, list(map(int, action))


def _cards(zone: Any) -> list[Any]:
    return [card for card in (zone or []) if card is not None]


def _card_id(card: Any) -> int:
    return integer(getattr(card, "id", None))


def _selected_attack(obs: Any, action: Sequence[int], attack_id: int) -> bool:
    options = list(obs.select.option or [])
    return any(
        integer(options[index].type) == int(OptionType.ATTACK)
        and integer(getattr(options[index], "attackId", None)) == attack_id
        for index in action
    )


def _target_card_id(obs: Any, seat: int, option: Any) -> int | None:
    player = obs.current.players[seat]
    area = integer(getattr(option, "inPlayArea", None))
    index = integer(getattr(option, "inPlayIndex", None), 0)
    zone = player.active if area == int(AreaType.ACTIVE) else player.bench if area == int(AreaType.BENCH) else []
    cards = _cards(zone)
    return _card_id(cards[index]) if 0 <= index < len(cards) else None


def opening_bucket(active_id: int | None, quick_sign_legal: bool) -> str:
    if active_id == GROOKEY:
        return "grookey_active"
    if active_id == VOLBEAT:
        return "volbeat_active_quick_sign_legal" if quick_sign_legal else "volbeat_active_quick_sign_unavailable"
    if active_id == APPLIN_DRAGON:
        return "applin_42_active"
    if active_id == APPLIN_GRASS:
        return "applin_92_active"
    if active_id == SHAYMIN:
        return "shaymin_active"
    return "other"


def _hand_resources(obs: Any, seat: int) -> dict[str, Any]:
    player = obs.current.players[seat]
    hand_ids = [_card_id(card) for card in _cards(player.hand)]
    discard_ids = [_card_id(card) for card in _cards(player.discard)]
    important = (GRASS_ENERGY, DIPPLIN, THWACKEY, FESTIVAL, BOSS, BRAVE_BANGLE, BLACK_BELT)
    return {
        "hand_count": integer(getattr(player, "handCount", None), len(hand_ids)),
        "deck_count": integer(getattr(player, "deckCount", None), 0),
        "discard_count": len(discard_ids),
        "prizes_remaining": len(player.prize or []),
        "hand_important_counts": {str(card_id): hand_ids.count(card_id) for card_id in important},
        "discard_important_counts": {str(card_id): discard_ids.count(card_id) for card_id in important},
    }


def _prize_structure(obs: Any, seat: int) -> str:
    opponent = obs.current.players[1 - seat]
    cards = _cards(opponent.active) + _cards(opponent.bench)
    values = [_prize_value(card) for card in cards]
    if any(value >= 3 for value in values):
        return "three_prize_mega_or_mixed"
    if any(value == 2 for value in values):
        return "two_prize_ex_or_mixed"
    return "single_prize"


def _engine_online(obs: Any, seat: int) -> bool:
    board = public_board_snapshot(obs, seat)
    if not board or board.get("active_id") != DIPPLIN or not board.get("active_ready") or not board.get("festival_active"):
        return False
    options = list(obs.select.option or [])
    do_wave = any(integer(getattr(option, "attackId", None)) == DO_THE_WAVE for option in options)
    # A Thwackey remains an established usable engine body after its once-per-
    # turn ability has resolved, even though the ABILITY option disappears.
    return do_wave and int(board.get("thwackey_count") or 0) > 0


def _boom_boom_context(obs: Any, seat: int, board: Mapping[str, Any] | None, target: int) -> dict[str, Any]:
    """Describe a Groove target using only information public at the prompt."""

    player = obs.current.players[seat]
    opponent = obs.current.players[1 - seat]
    attacker = next(iter(_cards(player.active)), None)
    defender = next(iter(_cards(opponent.active)), None)
    option_ids = {option_card_id(obs, index) for index in range(len(obs.select.option or []))}
    attack_available = bool(
        board
        and board.get("active_id") == DIPPLIN
        and board.get("active_ready")
        and board.get("festival_active")
        and defender is not None
    )
    projection = None
    modifier_projection = None
    if attack_available:
        projection = project_do_the_wave(
            attacker,
            defender,
            bench_count=integer(board.get("bench_count"), 0),
            festival_active=True,
        )
        modifiers: list[Any] = [projection]
        if BRAVE_BANGLE in option_ids:
            modifiers.append(project_do_the_wave(
                attacker, defender, bench_count=integer(board.get("bench_count"), 0),
                bangle_attached=True, festival_active=True,
            ))
        if BLACK_BELT in option_ids:
            modifiers.append(project_do_the_wave(
                attacker, defender, bench_count=integer(board.get("bench_count"), 0),
                black_belt_used=True, festival_active=True,
            ))
        modifier_projection = max(modifiers, key=lambda value: (value.ko, value.turn_ko, value.final))

    pressure_cards = {BOSS, BRAVE_BANGLE, BLACK_BELT, FESTIVAL}
    continuity_cards = set(BASIC_POKEMON) | {DIPPLIN, THWACKEY, GRASS_ENERGY}
    if target in pressure_cards:
        target_role = "immediate_pressure"
    elif target in continuity_cards:
        target_role = "board_or_replacement_continuity"
    else:
        target_role = "draw_recovery_or_other"
    return {
        "attack_available": attack_available,
        "baseline_first_hit_ko": bool(projection and projection.ko),
        "baseline_two_hit_ko": bool(projection and projection.turn_ko and not projection.ko),
        "first_hit_ko_with_available_modifier": bool(
            projection and modifier_projection and not projection.ko and modifier_projection.ko
        ),
        "baseline_damage": projection.final if projection else None,
        "best_modifier_damage": modifier_projection.final if modifier_projection else None,
        "opponent_prize_value": projection.prize_value if projection else None,
        "replacement_missing": bool(board and board.get("replacement_state") == "none"),
        "two_or_fewer_prizes_remaining": len(player.prize or []) <= 2,
        "target_role": target_role,
    }


def _terminal_result(replay: Mapping[str, Any]) -> int | None:
    for step in reversed(replay.get("steps") or []):
        for row in step[:2] if isinstance(step, list) else []:
            result = integer(((row.get("observation") or {}).get("current") or {}).get("result"), -1)
            if result in (0, 1):
                return result
    return None


def analyze_episode(spec: ReplaySpec) -> dict[str, Any]:
    replay = json.loads(spec.path.read_text(encoding="utf-8"))
    if sha256_file(spec.path) != str(spec.metadata.get("replay_sha256") or sha256_file(spec.path)).lower():
        raise ValueError(f"replay hash mismatch: {spec.path}")
    seat = spec.hero_seat
    _chooser, _choice, first_player = episode_order(replay)
    if first_player not in (0, 1):
        raise ValueError(f"episode {spec.episode_id} has no first player")
    actual_order = "first" if seat == first_player else "second"
    steps = replay.get("steps") or []

    state_at: dict[int, Any] = {}
    prize_at: dict[int, int] = {}
    board_at: dict[int, dict[str, Any]] = {}
    for step_index, step in enumerate(steps):
        if not isinstance(step, list) or seat >= len(step):
            continue
        raw = (step[seat].get("observation") or {}) if isinstance(step[seat], Mapping) else {}
        if raw.get("current") is None:
            continue
        obs = to_observation_class(raw)
        state_at[step_index] = obs
        player = obs.current.players[seat]
        prize_at[step_index] = len(player.prize or [])
        board = public_board_snapshot(obs, seat)
        if board is not None:
            board_at[step_index] = board

    actions = list(aligned_actions(replay, seat))
    opening_active: int | None = None
    quick_sign_legal = False
    quick_sign_used = False
    turn_steps: dict[int, list[int]] = defaultdict(list)
    do_wave_steps: dict[int, list[int]] = defaultdict(list)
    engine_steps: dict[int, list[int]] = defaultdict(list)
    boom_boom_targets: list[dict[str, Any]] = []
    opening_energy_targets: list[dict[str, Any]] = []
    grookey_evolved_before_escape = False
    first_attack_step: int | None = None

    for step_index, _raw, obs, action in actions:
        turn = integer(obs.current.turn, 0)
        ordinal = own_turn_ordinal(turn, seat, first_player)
        if ordinal > 0:
            turn_steps[turn].append(step_index)
        board = board_at.get(step_index) or public_board_snapshot(obs, seat)
        if ordinal == 1 and board is not None:
            if opening_active is None:
                opening_active = board.get("active_id")
            quick_sign_legal = quick_sign_legal or any(
                integer(getattr(option, "attackId", None)) == QUICK_SIGN for option in (obs.select.option or [])
            )
        if _selected_attack(obs, action, QUICK_SIGN):
            quick_sign_used = True
        if _selected_attack(obs, action, DO_THE_WAVE):
            do_wave_steps[turn].append(step_index)
            if first_attack_step is None:
                first_attack_step = step_index
        if opening_active == GROOKEY and board and board.get("active_id") == GROOKEY:
            for index in action:
                option = obs.select.option[index]
                if (
                    integer(option.type) == int(OptionType.EVOLVE)
                    and option_card_id(obs, index) == THWACKEY
                    and integer(getattr(option, "inPlayArea", None)) == int(AreaType.ACTIVE)
                ):
                    grookey_evolved_before_escape = True
        if first_attack_step is None:
            for index in action:
                option = obs.select.option[index]
                if integer(option.type) == int(OptionType.ATTACH) and option_card_id(obs, index) == GRASS_ENERGY:
                    opening_energy_targets.append({
                        "own_turn_ordinal": ordinal,
                        "target_card_id": _target_card_id(obs, seat, option),
                        "target_area": integer(getattr(option, "inPlayArea", None)),
                    })
        if _engine_online(obs, seat):
            engine_steps[turn].append(step_index)
        if effect_id(obs) == THWACKEY and action:
            target = option_card_id(obs, action[0])
            boom_boom_targets.append({
                "turn": turn,
                "own_turn_ordinal": ordinal,
                "target_card_id": target,
                **_boom_boom_context(obs, seat, board, target),
                "board": board,
            })

    # Include passive observations in turn boundaries; actions alone can miss
    # the final post-Prize state when the game ends immediately.
    all_turn_steps: dict[int, list[int]] = defaultdict(list)
    for step_index, obs in state_at.items():
        turn = integer(obs.current.turn, 0)
        if own_turn_ordinal(turn, seat, first_player) > 0:
            all_turn_steps[turn].append(step_index)

    turn_rows: list[dict[str, Any]] = []
    for turn, indices in sorted(all_turn_steps.items()):
        ordinal = own_turn_ordinal(turn, seat, first_player)
        if ordinal <= 0:
            continue
        indices = sorted(indices)
        start_prizes = prize_at.get(indices[0])
        end_prizes = prize_at.get(indices[-1])
        prizes = max(0, (start_prizes or 0) - (end_prizes or 0))
        attacks = sorted(do_wave_steps.get(turn, []))
        first_hit_prizes = 0
        second_hit_prizes = 0
        if attacks:
            before = prize_at.get(attacks[0], start_prizes or 0)
            boundary = attacks[1] if len(attacks) >= 2 else indices[-1]
            after_first = prize_at.get(boundary, end_prizes or before)
            first_hit_prizes = max(0, (before or 0) - (after_first or 0))
            if len(attacks) >= 2:
                second_before = prize_at.get(attacks[1], after_first or 0)
                second_hit_prizes = max(0, (second_before or 0) - (end_prizes or 0))
        turn_rows.append({
            "global_turn": turn,
            "own_turn_ordinal": ordinal,
            "prizes_taken": prizes,
            "do_wave_attacks": len(attacks),
            "first_hit_ko": first_hit_prizes > 0,
            "first_hit_prizes": first_hit_prizes,
            "second_hit_prizes": second_hit_prizes,
            "double_prize_window": first_hit_prizes > 0 and len(attacks) >= 2 and second_hit_prizes > 0,
            "engine_online": bool(engine_steps.get(turn)),
            "engine_first_step": min(engine_steps[turn]) if engine_steps.get(turn) else None,
        })

    first_attack_turn = next((row for row in turn_rows if row["do_wave_attacks"]), None)
    first_prize_turn = next((row for row in turn_rows if row["prizes_taken"]), None)
    first_double_turn = next((row for row in turn_rows if row["do_wave_attacks"] >= 2), None)
    engine_turn_rows = [row for row in turn_rows if row["engine_online"]]
    first_engine = engine_turn_rows[0] if engine_turn_rows else None
    first_attack_board = board_at.get(first_attack_step) if first_attack_step is not None else None
    first_attack_resources = None
    if first_attack_step is not None and first_attack_step in state_at:
        first_attack_resources = _hand_resources(state_at[first_attack_step], seat)
    first_engine_board = None
    first_engine_resources = None
    first_engine_prize_structure = spec.opponent_prize_structure
    if first_engine is not None:
        engine_step = integer(first_engine["engine_first_step"])
        first_engine_board = board_at.get(engine_step)
        if engine_step in state_at:
            first_engine_resources = _hand_resources(state_at[engine_step], seat)
            first_engine_prize_structure = first_engine_prize_structure or _prize_structure(state_at[engine_step], seat)

    result_seat = _terminal_result(replay)
    reward = episode_reward(replay, seat)
    first_non_grookey_active_turn = None
    if opening_active == GROOKEY:
        for step_index, board in sorted(board_at.items()):
            if board.get("active_id") != GROOKEY:
                ordinal = own_turn_ordinal(integer(state_at[step_index].current.turn), seat, first_player)
                if ordinal > 0:
                    first_non_grookey_active_turn = ordinal
                    break
    return {
        "dataset": spec.dataset,
        "split": spec.split,
        "episode_id": spec.episode_id,
        "pilot": spec.pilot,
        "submission_id": spec.submission_id,
        "list_relation": spec.metadata.get("list_relation", "unknown"),
        "exact_pp_kawada_60": bool(spec.metadata.get("exact_pp_kawada_60")),
        "exact_deck_hash": spec.exact_deck_hash,
        "actual_order": actual_order,
        "opening_active_id": opening_active,
        "opening_bucket": opening_bucket(opening_active, quick_sign_legal),
        "quick_sign_legal": quick_sign_legal,
        "quick_sign_used": quick_sign_used,
        "first_non_grookey_active_own_turn": first_non_grookey_active_turn,
        "grookey_evolved_before_escape": grookey_evolved_before_escape,
        "opening_energy_targets": opening_energy_targets,
        "completed": reward is not None or result_seat in (0, 1),
        "win": bool(reward == 1.0) if reward is not None else result_seat == seat,
        "opponent_archetype": spec.opponent_archetype,
        "opponent_prize_structure": first_engine_prize_structure or "unknown",
        "first_do_wave_own_turn": first_attack_turn["own_turn_ordinal"] if first_attack_turn else None,
        "first_prize_own_turn": first_prize_turn["own_turn_ordinal"] if first_prize_turn else None,
        "first_festival_double_attack_own_turn": first_double_turn["own_turn_ordinal"] if first_double_turn else None,
        "first_attack_board": first_attack_board,
        "first_attack_resources": first_attack_resources,
        "first_engine_online_own_turn": first_engine["own_turn_ordinal"] if first_engine else None,
        "first_engine_turn": first_engine,
        "first_engine_board": first_engine_board,
        "first_engine_resources": first_engine_resources,
        "engine_turns": engine_turn_rows,
        "turns": turn_rows,
        "boom_boom_targets": boom_boom_targets,
        "source_timestamp": spec.source_timestamp,
        "replay_sha256": sha256_file(spec.path),
    }


def rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def mean(values: Iterable[int | float | None]) -> float | None:
    selected = [float(value) for value in values if value is not None]
    return statistics.fmean(selected) if selected else None


def percentile(values: Iterable[int | float | None], fraction: float) -> float | None:
    selected = sorted(float(value) for value in values if value is not None)
    if not selected:
        return None
    position = (len(selected) - 1) * fraction
    lower = int(position)
    upper = min(len(selected) - 1, lower + 1)
    weight = position - lower
    return selected[lower] * (1 - weight) + selected[upper] * weight


def aggregate_scalar(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    values = [row.get(key) for row in rows if row.get(key) is not None]
    return {
        "observed": len(values),
        "mean": mean(values),
        "median": percentile(values, 0.5),
        "p90": percentile(values, 0.9),
    }


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


__all__ = [
    "OPENING_BUCKETS",
    "ReplaySpec",
    "aggregate_scalar",
    "aligned_actions",
    "analyze_episode",
    "canonical_deck_hash",
    "infer_dipplin_seat",
    "integer",
    "load_manifest_specs",
    "load_local_trace_rows",
    "mean",
    "opening_bucket",
    "parse_dataset_args",
    "rate",
    "replay_decks",
    "sha256_file",
    "write_json",
]

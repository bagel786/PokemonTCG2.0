#!/usr/bin/env python3
"""Analyze public floor milestones in the development/calibration d842 bank.

The untouched holdout is deliberately impossible to select.  The optional
Kaggle query reads episode metadata only; it never requests replay payloads.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
BANK = ROOT / "artifacts" / "grim_5k_training_bank"
REPLAY_ROOT = ROOT / "artifacts" / "grim_5k_history" / "replays"
DISAGREEMENTS = ROOT / "artifacts" / "grim_policy_disagreements" / "disagreements.jsonl.gz"
OUTPUT = ROOT / "artifacts" / "grim_floor_analysis"

ALLOWED_SPLITS = ("development", "calibration")
D842_LINEAGE = (
    55114709, 55171235, 55180261, 55189658, 55198075,
    55198084, 55222011, 55246709, 55246712, 55278940,
    55280574, 55280578, 55323437, 55358290, 55358291,
)
HASH_PROVEN = frozenset({55323437, 55358290, 55358291})

FROZEN_MODEL_SHA256 = "D842F85ABFC44AF9F41979F91795E22C92C179B62E04D5A0A2F9C734E70AF1C3"
FROZEN_DECK_SHA256 = "C20A8A46F5C635773754F03103652F5C534B13DC622448ED2255A97234C103AF"

FROSLASS = 104
MUNKIDORI = 112
IMPIDIMP = 646
MORGREM = 647
GRIMMSNARL = 648
SNORUNT = 860
DARK_ENERGY = 7
RARE_CANDY = 1079
POFFIN = 1086
NIGHT_STRETCHER = 1097
POKE_PAD = 1152
BOSS = 1182
PETREL = 1219
SPIKEMUTH = 1259
SHADOW_BULLET = 937

PLAY = 7
ATTACH = 8
EVOLVE = 9
ABILITY = 10
RETREAT = 12
ATTACK = 13
END = 14

SETUP_ACTIVE = 1
SETUP_BENCH = 2
TO_ACTIVE = 4
TO_BENCH = 5
TO_FIELD = 6
ATTACH_TO = 22
DAMAGE_CONTEXTS = {13, 14, 15, 16, 17, 39, 40}

ATTACK_REQUIREMENT = {IMPIDIMP: 1, MORGREM: 2, GRIMMSNARL: 2}
LOW_HP_IDS = {FROSLASS, IMPIDIMP, MORGREM, SNORUNT}
CREDIBLE_PROPOSERS = frozenset({"tempo", "master_v1", "replay_refresh", "v2_2", "a2"})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def load_card_names() -> dict[int, str]:
    result: dict[int, str] = {}
    with (ROOT / "freshstart" / "data" / "EN_Card_Data.csv").open(
        encoding="utf-8-sig", errors="ignore", newline=""
    ) as handle:
        for row in csv.DictReader(handle):
            try:
                result[int(row["Card ID"])] = str(row["Card Name"])
            except (KeyError, TypeError, ValueError):
                continue
    return result


CARD_NAMES = load_card_names()


def read_jsonl_gz(path: Path) -> Iterable[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: expected object")
            yield row


def load_units(bank: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for split in ALLOWED_SPLITS:
        path = (bank / f"{split}.jsonl.gz").resolve()
        if "untouched_holdout" in str(path).casefold():
            raise RuntimeError("refusing untouched holdout")
        for row in read_jsonl_gz(path):
            if row.get("split") != split or row.get("split") not in ALLOWED_SPLITS:
                raise ValueError(f"forbidden/mismatched split in {path}")
            if row.get("frozen_model_sha256") != FROZEN_MODEL_SHA256:
                raise ValueError(f"episode {row.get('episode_id')} is not frozen d842")
            if row.get("hero_deck_canonical_sha256") != FROZEN_DECK_SHA256:
                raise ValueError(f"episode {row.get('episode_id')} has the wrong deck")
            rows.append(row)
    return rows


def own_turn_ordinal(current: Mapping[str, Any], seat: int) -> int:
    turn = int(current.get("turn", 0) or 0)
    first = int(current.get("firstPlayer", -1) or 0)
    if turn <= 0 or first not in (0, 1):
        return 0
    return (turn + 1) // 2 if seat == first else turn // 2


def cards_in_play(player: Mapping[str, Any]) -> list[dict[str, Any]]:
    cards = list(player.get("active") or []) + list(player.get("bench") or [])
    return [card for card in cards if isinstance(card, dict)]


def energy_count(card: Mapping[str, Any]) -> int:
    energies = card.get("energies")
    if isinstance(energies, list):
        return len(energies)
    energy_cards = card.get("energyCards")
    return len(energy_cards) if isinstance(energy_cards, list) else 0


def is_ready_attacker(card: Mapping[str, Any]) -> bool:
    try:
        requirement = ATTACK_REQUIREMENT[int(card.get("id", -1))]
    except (KeyError, TypeError, ValueError):
        return False
    return energy_count(card) >= requirement


def board_snapshot(current: Mapping[str, Any], seat: int) -> dict[str, Any]:
    players = current.get("players") or []
    if not isinstance(players, list) or seat >= len(players) or not isinstance(players[seat], dict):
        return {}
    player = players[seat]
    board = cards_in_play(player)
    active = list(player.get("active") or [])
    bench = [card for card in (player.get("bench") or []) if isinstance(card, dict)]
    ids = [int(card.get("id", -1)) for card in board]
    grim_energies = [energy_count(card) for card in board if int(card.get("id", -1)) == GRIMMSNARL]
    total_energy = sum(energy_count(card) for card in board)
    useful_caps = {IMPIDIMP: 1, MORGREM: 2, GRIMMSNARL: 2, MUNKIDORI: 1}
    support_or_excess_energy = sum(
        max(0, energy_count(card) - useful_caps.get(int(card.get("id", -1)), 0)) for card in board
    )
    prizes = player.get("prize") or []
    opponent = players[1 - seat] if len(players) == 2 and isinstance(players[1 - seat], dict) else {}
    opponent_prizes = opponent.get("prize") or []
    return {
        "width": len(board),
        "bench_width": len(bench),
        "active_id": int(active[0].get("id", -1)) if active and isinstance(active[0], dict) else None,
        "impidimp": ids.count(IMPIDIMP),
        "morgrem": ids.count(MORGREM),
        "grimmsnarl": ids.count(GRIMMSNARL),
        "snorunt": ids.count(SNORUNT),
        "froslass": ids.count(FROSLASS),
        "munkidori": ids.count(MUNKIDORI),
        "total_energy": total_energy,
        "grim_energy": sum(grim_energies),
        "max_grim_energy": max(grim_energies, default=0),
        "ready_grim": sum(value >= 2 for value in grim_energies),
        "ready_attackers": sum(is_ready_attacker(card) for card in board),
        "enabled_munkidori": sum(
            int(card.get("id", -1)) == MUNKIDORI and energy_count(card) >= 1 for card in board
        ),
        "low_hp_bench": sum(int(card.get("id", -1)) in LOW_HP_IDS for card in bench),
        "support_or_excess_energy": support_or_excess_energy,
        "hero_prizes_taken": 6 - len(prizes),
        "opponent_prizes_taken": 6 - len(opponent_prizes),
    }


def chosen_options(observation: Mapping[str, Any], action: Any) -> list[dict[str, Any]]:
    select = observation.get("select") or {}
    options = select.get("option") or []
    if not isinstance(action, list):
        return []
    chosen = []
    for index in action:
        if isinstance(index, int) and 0 <= index < len(options) and isinstance(options[index], dict):
            chosen.append(options[index])
    return chosen


def productive_attack_indices(observation: Mapping[str, Any]) -> list[int]:
    options = ((observation.get("select") or {}).get("option") or [])
    attack_indices = [
        index for index, option in enumerate(options)
        if isinstance(option, dict) and int(option.get("type", -1)) == ATTACK
    ]
    if not attack_indices:
        return []
    try:
        engine_root = ROOT / "artifacts" / "recovery_probes" / "extracted" / "control"
        if str(engine_root) not in sys.path:
            sys.path.insert(0, str(engine_root))
        if str(ROOT) not in sys.path:
            sys.path.insert(1, str(ROOT))
        from cg.api import to_observation_class
        from ptcg_ai.prevention import attack_nullified

        typed = to_observation_class(dict(observation))
        return [index for index in attack_indices if not attack_nullified(typed, typed.select.option[index])]
    except Exception:
        # A legal attack is still a useful conservative diagnostic if native
        # card metadata is unavailable.  The report records this fallback.
        return attack_indices


def final_public_current(replay: Mapping[str, Any]) -> Mapping[str, Any] | None:
    last = None
    for step in replay.get("steps") or []:
        if not isinstance(step, list):
            continue
        for row in step:
            if not isinstance(row, dict):
                continue
            current = ((row.get("observation") or {}).get("current"))
            if isinstance(current, dict) and len(current.get("players") or []) == 2:
                last = current
    return last


def analyze_episode(unit: Mapping[str, Any], replay_root: Path) -> dict[str, Any]:
    relative = Path(str(unit["replay_path"]))
    if relative.is_absolute() or "untouched_holdout" in str(relative).casefold():
        raise ValueError("forbidden replay path")
    path = (replay_root / relative).resolve()
    path.relative_to(replay_root.resolve())
    if sha256_file(path) != str(unit["replay_sha256"]).upper():
        raise ValueError(f"replay hash mismatch: {path}")
    replay = json.loads(path.read_text(encoding="utf-8"))
    seat = int(unit["hero_seat"])
    steps = replay.get("steps") or []

    ordinal_last: dict[int, dict[str, Any]] = {}
    ordinal_max_width: Counter[int] = Counter()
    first_grim = first_ready_grim = first_ready_attacker = None
    first_attack = first_shadow = first_prize = None
    pass_with_productive_attack = 0
    pass_with_any_attack = 0
    promotion_misses = 0
    setup_active_id = None
    attachment_targets: Counter[int] = Counter()

    for step_t in range(max(0, len(steps) - 1)):
        current_step, next_step = steps[step_t], steps[step_t + 1]
        if not isinstance(current_step, list) or not isinstance(next_step, list):
            continue
        if seat >= len(current_step) or seat >= len(next_step):
            continue
        row, following = current_step[seat], next_step[seat]
        if not isinstance(row, dict) or str(row.get("status", "")).upper() != "ACTIVE":
            continue
        observation = row.get("observation") or {}
        current = observation.get("current")
        select = observation.get("select")
        action = following.get("action") if isinstance(following, dict) else None
        if not isinstance(current, dict) or not isinstance(select, dict) or not isinstance(action, list):
            continue
        ordinal = own_turn_ordinal(current, seat)
        snapshot = board_snapshot(current, seat)
        if ordinal > 0 and snapshot:
            ordinal_last[ordinal] = snapshot
            ordinal_max_width[ordinal] = max(ordinal_max_width[ordinal], snapshot["width"])
            if first_grim is None and snapshot["grimmsnarl"]:
                first_grim = ordinal
            if first_ready_grim is None and snapshot["ready_grim"]:
                first_ready_grim = ordinal
            if first_ready_attacker is None and snapshot["ready_attackers"]:
                first_ready_attacker = ordinal
            if first_prize is None and snapshot["hero_prizes_taken"] > 0:
                first_prize = ordinal

        chosen = chosen_options(observation, action)
        chosen_types = {int(option.get("type", -1)) for option in chosen}
        context = int(select.get("context", -1))
        if context == SETUP_ACTIVE and chosen:
            player_index = int(chosen[0].get("playerIndex", seat) or seat)
            players = current.get("players") or []
            if player_index < len(players):
                hand = (players[player_index] or {}).get("hand") or []
                index = chosen[0].get("index")
                if isinstance(index, int) and 0 <= index < len(hand) and isinstance(hand[index], dict):
                    setup_active_id = int(hand[index].get("id", -1))
        if ATTACK in chosen_types and ordinal > 0:
            if first_attack is None:
                first_attack = ordinal
            if any(int(option.get("attackId", -1)) == SHADOW_BULLET for option in chosen):
                if first_shadow is None:
                    first_shadow = ordinal
        if END in chosen_types:
            options = select.get("option") or []
            legal_attacks = [option for option in options if isinstance(option, dict) and int(option.get("type", -1)) == ATTACK]
            if legal_attacks:
                pass_with_any_attack += 1
            if productive_attack_indices(observation):
                pass_with_productive_attack += 1
        if context == TO_ACTIVE and chosen:
            chosen_card = None
            ready_alternative = False
            players = current.get("players") or []
            player = players[seat] if seat < len(players) else {}
            for option in select.get("option") or []:
                if not isinstance(option, dict):
                    continue
                area, index = option.get("area"), option.get("index")
                zone = (player.get("bench") or []) if area == 5 else (player.get("active") or []) if area == 4 else []
                if isinstance(index, int) and 0 <= index < len(zone) and isinstance(zone[index], dict):
                    ready_alternative |= is_ready_attacker(zone[index])
            option = chosen[0]
            area, index = option.get("area"), option.get("index")
            zone = (player.get("bench") or []) if area == 5 else (player.get("active") or []) if area == 4 else []
            if isinstance(index, int) and 0 <= index < len(zone) and isinstance(zone[index], dict):
                chosen_card = zone[index]
            if ready_alternative and not is_ready_attacker(chosen_card or {}):
                promotion_misses += 1
        for option in chosen:
            if int(option.get("type", -1)) != ATTACH:
                continue
            area, index = option.get("inPlayArea"), option.get("inPlayIndex")
            players = current.get("players") or []
            player = players[seat] if seat < len(players) else {}
            zone = (player.get("active") or []) if area == 4 else (player.get("bench") or []) if area == 5 else []
            if isinstance(index, int) and 0 <= index < len(zone) and isinstance(zone[index], dict):
                attachment_targets[int(zone[index].get("id", -1))] += 1

    first_turn = ordinal_last.get(1, {})
    turn_three = ordinal_last.get(3, {})
    turn_four = ordinal_last.get(4, {})
    final = final_public_current(replay)
    final_snapshot = board_snapshot(final, seat) if isinstance(final, dict) else {}
    first_width = max(int(ordinal_max_width.get(1, 0)), int(first_turn.get("width", 0) or 0))
    outcome = str(unit["outcome"])
    win = outcome == "win"
    result = {
        "episode_id": str(unit["episode_id"]),
        "split": str(unit["split"]),
        "submission_id": int(unit["submission_id"]),
        "actual_order": str(unit["actual_order"]),
        "outcome": outcome,
        "win": win,
        "opponent_matchup": str(unit.get("opponent_matchup") or "unknown"),
        "setup_active_id": setup_active_id,
        "setup_active_impidimp": setup_active_id == IMPIDIMP,
        "first_turn_max_width": first_width,
        "first_turn_two_impidimp": int(first_turn.get("impidimp", 0) or 0) >= 2,
        "first_turn_has_snorunt": int(first_turn.get("snorunt", 0) or 0) >= 1,
        "first_turn_has_munkidori": int(first_turn.get("munkidori", 0) or 0) >= 1,
        "first_grim_own_turn": first_grim,
        "first_ready_grim_own_turn": first_ready_grim,
        "first_ready_attacker_own_turn": first_ready_attacker,
        "first_attack_own_turn": first_attack,
        "first_shadow_bullet_own_turn": first_shadow,
        "first_prize_own_turn": first_prize,
        "passes_with_any_legal_attack": pass_with_any_attack,
        "passes_with_productive_attack": pass_with_productive_attack,
        "promotion_misses_with_ready_alternative": promotion_misses,
        "attachment_targets": {str(key): value for key, value in sorted(attachment_targets.items())},
        "turn_three": turn_three,
        "turn_four": turn_four,
        "final": final_snapshot,
        "hero_prizes_taken": int(final_snapshot.get("hero_prizes_taken", 0) or 0),
        "opponent_prizes_taken": int(final_snapshot.get("opponent_prizes_taken", 0) or 0),
    }
    result.update({
        "narrow_first_turn": first_width < 3,
        "setup_active_not_impidimp": not result["setup_active_impidimp"],
        "not_two_imp_first_turn": not result["first_turn_two_impidimp"],
        "first_turn_missing_snorunt": not result["first_turn_has_snorunt"],
        "first_turn_missing_munkidori": not result["first_turn_has_munkidori"],
        "no_grim_by_turn_3": first_grim is None or first_grim > 3,
        "no_ready_grim_by_turn_3": first_ready_grim is None or first_ready_grim > 3,
        "no_attack_by_turn_3": first_attack is None or first_attack > 3,
        "no_shadow_by_turn_3": first_shadow is None or first_shadow > 3,
        "zero_prizes": result["hero_prizes_taken"] == 0,
        "one_or_fewer_prizes": result["hero_prizes_taken"] <= 1,
        "close_prize_loss": (not win) and result["hero_prizes_taken"] >= 4,
        "t3_energy_without_ready_grim": bool(turn_three)
            and int(turn_three.get("total_energy", 0)) >= 2
            and int(turn_three.get("ready_grim", 0)) == 0,
        "t3_overcharged_grim": bool(turn_three) and int(turn_three.get("max_grim_energy", 0)) >= 3,
        "t3_support_or_excess_energy": bool(turn_three)
            and int(turn_three.get("support_or_excess_energy", 0)) >= 1,
        "t3_low_hp_bench_ge3": bool(turn_three) and int(turn_three.get("low_hp_bench", 0)) >= 3,
        "t3_enabled_munkidori": bool(turn_three) and int(turn_three.get("enabled_munkidori", 0)) >= 1,
        "no_two_ready_attackers_by_turn_4": not bool(turn_four)
            or int(turn_four.get("ready_attackers", 0)) < 2,
    })
    if win:
        bucket = "win"
    elif result["passes_with_productive_attack"]:
        bucket = "productive_attack_passed"
    elif result["no_grim_by_turn_3"]:
        bucket = "no_grim_by_turn_3"
    elif result["no_ready_grim_by_turn_3"]:
        bucket = "grim_not_ready_by_turn_3"
    elif result["no_shadow_by_turn_3"]:
        bucket = "ready_line_but_no_shadow_by_turn_3"
    elif result["close_prize_loss"]:
        bucket = "close_prize_conversion"
    elif result["one_or_fewer_prizes"]:
        bucket = "on_curve_low_damage_conversion"
    else:
        bucket = "midgame_resource_or_targeting"
    result["exclusive_loss_bucket"] = bucket
    return result


def rate_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    games = len(rows)
    wins = sum(bool(row.get("win")) for row in rows)
    return {
        "games": games,
        "wins": wins,
        "losses": games - wins,
        "win_rate": round(wins / games, 6) if games else None,
    }


def grouped_summary(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get(key))].append(row)
    return {name: rate_summary(group) for name, group in sorted(groups.items())}


def binary_association(rows: Sequence[Mapping[str, Any]], flag: str) -> dict[str, Any]:
    present = [row for row in rows if bool(row.get(flag))]
    absent = [row for row in rows if not bool(row.get(flag))]
    present_loss = sum(not bool(row.get("win")) for row in present)
    absent_loss = sum(not bool(row.get("win")) for row in absent)
    present_rate = present_loss / len(present) if present else None
    absent_rate = absent_loss / len(absent) if absent else None
    return {
        "present": {"games": len(present), "losses": present_loss, "loss_rate": round(present_rate, 6) if present_rate is not None else None},
        "absent": {"games": len(absent), "losses": absent_loss, "loss_rate": round(absent_rate, 6) if absent_rate is not None else None},
        "loss_rate_difference": round(present_rate - absent_rate, 6)
            if present_rate is not None and absent_rate is not None else None,
    }


def prize_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"games": 0}
    hero = [int(row.get("hero_prizes_taken", 0) or 0) for row in rows]
    opponent = [int(row.get("opponent_prizes_taken", 0) or 0) for row in rows]
    margins = [ours - theirs for ours, theirs in zip(hero, opponent)]
    return {
        "games": len(rows),
        "mean_hero_prizes_taken": round(statistics.mean(hero), 4),
        "median_hero_prizes_taken": statistics.median(hero),
        "mean_opponent_prizes_taken": round(statistics.mean(opponent), 4),
        "mean_prize_margin": round(statistics.mean(margins), 4),
        "hero_prize_distribution": {str(key): value for key, value in sorted(Counter(hero).items())},
    }


def timing_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result = {}
    for key in (
        "first_grim_own_turn",
        "first_ready_grim_own_turn",
        "first_ready_attacker_own_turn",
        "first_attack_own_turn",
        "first_shadow_bullet_own_turn",
        "first_prize_own_turn",
    ):
        values = [int(row[key]) for row in rows if row.get(key) is not None]
        result[key] = {
            "observed_games": len(values),
            "missing_games": len(rows) - len(values),
            "median_when_observed": statistics.median(values) if values else None,
            "by_turn_3_rate": round(sum(value <= 3 for value in values) / len(rows), 6) if rows else None,
        }
    return result


def attachment_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: Counter[int] = Counter()
    for row in rows:
        for card_id, count in (row.get("attachment_targets") or {}).items():
            counts[int(card_id)] += int(count)
    return {
        f"{CARD_NAMES.get(card_id, str(card_id))} [{card_id}]": count
        for card_id, count in counts.most_common()
    }


def matchup_loss_buckets(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    result: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        if not row.get("win"):
            result[str(row.get("opponent_matchup"))][str(row.get("exclusive_loss_bucket"))] += 1
    return {key: dict(sorted(value.items())) for key, value in sorted(result.items())}


def semantic_card_ids(semantic: Mapping[str, Any]) -> set[int]:
    result: set[int] = set()
    for option in semantic.get("options") or []:
        if not isinstance(option, dict):
            continue
        for part in (option.get("source"), option.get("target")):
            if isinstance(part, dict) and part.get("card_id") is not None:
                result.add(int(part["card_id"]))
        if option.get("attached_card_id") is not None:
            result.add(int(option["attached_card_id"]))
    for part in (semantic.get("context_card"), semantic.get("effect_card")):
        if isinstance(part, dict) and part.get("card_id") is not None:
            result.add(int(part["card_id"]))
    return result


def semantic_types(semantic: Mapping[str, Any]) -> set[int]:
    return {
        int(option.get("option_type", -1)) for option in semantic.get("options") or []
        if isinstance(option, dict)
    }


def action_family(row: Mapping[str, Any]) -> str:
    candidate = row.get("candidate_semantic") or {}
    baseline = row.get("baseline_semantic") or {}
    types = semantic_types(candidate)
    baseline_types = semantic_types(baseline)
    cards = semantic_card_ids(candidate)
    context = int(candidate.get("context", -1))
    if ATTACK in types and END in baseline_types:
        return "attack_over_end"
    if ATTACK in types:
        return "attack_or_target"
    if EVOLVE in types or cards & {MORGREM, GRIMMSNARL, RARE_CANDY, NIGHT_STRETCHER, POKE_PAD, PETREL, SPIKEMUTH}:
        return "conversion_or_recovery"
    if ATTACH in types or context == ATTACH_TO or DARK_ENERGY in cards:
        return "energy_allocation"
    if context in {SETUP_ACTIVE, SETUP_BENCH, TO_BENCH, TO_FIELD} or (
        PLAY in types and bool(cards & {IMPIDIMP, SNORUNT, MUNKIDORI, POFFIN})
    ):
        return "setup_or_bench"
    if RETREAT in types or context == TO_ACTIVE:
        return "promotion_or_retreat"
    if BOSS in cards or context in DAMAGE_CONTEXTS:
        return "prize_targeting_or_counters"
    if END in types:
        return "end_or_decline"
    return "draw_search_or_other"


def option_label(option: Mapping[str, Any]) -> str:
    option_type = int(option.get("option_type", -1))
    type_name = {
        PLAY: "PLAY", ATTACH: "ATTACH", EVOLVE: "EVOLVE", ABILITY: "ABILITY",
        RETREAT: "RETREAT", ATTACK: "ATTACK", END: "END", 3: "CARD", 6: "ENERGY",
        1: "YES", 2: "NO",
    }.get(option_type, f"TYPE{option_type}")
    source = option.get("source") or {}
    target = option.get("target") or {}
    source_id = source.get("card_id") if isinstance(source, dict) else None
    target_id = target.get("card_id") if isinstance(target, dict) else None
    attack_id = option.get("attack_id")
    if attack_id is not None:
        return f"{type_name}:attack-{attack_id}"
    if source_id is not None:
        source_name = CARD_NAMES.get(int(source_id), str(source_id))
        if target_id is not None:
            target_name = CARD_NAMES.get(int(target_id), str(target_id))
            return f"{type_name}:{source_name}->{target_name}"
        return f"{type_name}:{source_name}"
    if target_id is not None:
        return f"{type_name}:->{CARD_NAMES.get(int(target_id), str(target_id))}"
    return type_name


def action_label(semantic: Mapping[str, Any]) -> str:
    options = semantic.get("options") or []
    labels = [option_label(option) for option in options if isinstance(option, dict)]
    context = int(semantic.get("context", -1))
    return f"ctx{context}/" + "+".join(labels or ["EMPTY"])


def top_counter(counter: Counter[str], limit: int = 12) -> dict[str, int]:
    return dict(counter.most_common(limit))


def analyze_disagreements(
    path: Path,
    episodes: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    rows = []
    for row in read_jsonl_gz(path):
        if row.get("split") not in ALLOWED_SPLITS or row.get("split") == "untouched_holdout":
            raise ValueError("disagreement bank contains forbidden split")
        episode_id = str(row.get("episode_id"))
        if episode_id not in episodes:
            raise ValueError(f"disagreement episode not present in admitted bank: {episode_id}")
        current = ((row.get("observation") or {}).get("current") or {})
        row["_own_turn_ordinal"] = own_turn_ordinal(current, int(row["hero_seat"]))
        row["_family"] = action_family(row)
        row["_candidate_label"] = action_label(row.get("candidate_semantic") or {})
        row["_transition"] = (
            action_label(row.get("baseline_semantic") or {}) + " -> " + row["_candidate_label"]
        )
        rows.append(row)

    def summarize(selected: Sequence[Mapping[str, Any]], relevant_max_turn: int | None = None) -> dict[str, Any]:
        relevant = [
            row for row in selected
            if relevant_max_turn is None or 0 <= int(row["_own_turn_ordinal"]) <= relevant_max_turn
        ]
        credible_relevant = [
            row for row in relevant if set(row.get("proposers") or []) & CREDIBLE_PROPOSERS
        ]
        proposer_counts: Counter[str] = Counter()
        credible_counts: Counter[str] = Counter()
        for row in relevant:
            for proposer in row.get("proposers") or []:
                proposer_counts[str(proposer)] += 1
                if proposer in CREDIBLE_PROPOSERS:
                    credible_counts[str(proposer)] += 1
        return {
            "rows": len(selected),
            "unique_states": len({str(row["observation_sha256"]) for row in selected}),
            "relevant_window_max_own_turn": relevant_max_turn,
            "relevant_rows": len(relevant),
            "relevant_unique_states": len({str(row["observation_sha256"]) for row in relevant}),
            "credible_rows": len(credible_relevant),
            "credible_unique_states": len({str(row["observation_sha256"]) for row in credible_relevant}),
            "floor_director_only_rows": len(relevant) - len(credible_relevant),
            "credible_consensus_rows": sum(
                len(set(row.get("proposers") or []) & CREDIBLE_PROPOSERS) >= 2 for row in credible_relevant
            ),
            "all_proposers": top_counter(proposer_counts),
            "credible_proposers": top_counter(credible_counts),
            "action_families": top_counter(Counter(str(row["_family"]) for row in credible_relevant)),
            "candidate_actions": top_counter(Counter(str(row["_candidate_label"]) for row in credible_relevant)),
            "transitions": top_counter(Counter(str(row["_transition"]) for row in credible_relevant), 15),
        }

    strata = {
        "all": (lambda _: True, None),
        "actual_second_losses": (lambda episode: episode["actual_order"] == "second" and not episode["win"], None),
        "second_loss_narrow_setup": (
            lambda episode: episode["actual_order"] == "second" and not episode["win"] and episode["narrow_first_turn"], 1
        ),
        "second_loss_no_grim_by_turn_3": (
            lambda episode: episode["actual_order"] == "second" and not episode["win"] and episode["no_grim_by_turn_3"], 3
        ),
        "second_loss_no_ready_grim_by_turn_3": (
            lambda episode: episode["actual_order"] == "second" and not episode["win"] and episode["no_ready_grim_by_turn_3"], 3
        ),
        "second_loss_no_shadow_by_turn_3": (
            lambda episode: episode["actual_order"] == "second" and not episode["win"] and episode["no_shadow_by_turn_3"], 3
        ),
        "second_loss_energy_without_ready_grim": (
            lambda episode: episode["actual_order"] == "second" and not episode["win"] and episode["t3_energy_without_ready_grim"], 3
        ),
        "second_loss_low_hp_bench_liability": (
            lambda episode: episode["actual_order"] == "second" and not episode["win"] and episode["t3_low_hp_bench_ge3"], 3
        ),
        "second_close_prize_losses": (
            lambda episode: episode["actual_order"] == "second" and episode["close_prize_loss"], None
        ),
    }
    result = {}
    for name, (predicate, max_turn) in strata.items():
        episode_ids = {episode_id for episode_id, episode in episodes.items() if predicate(episode)}
        selected = [row for row in rows if str(row["episode_id"]) in episode_ids]
        result[name] = {"episodes": len(episode_ids), **summarize(selected, max_turn)}
    result["input_rows"] = len(rows)
    result["input_unique_states"] = len({str(row["observation_sha256"]) for row in rows})
    result["warning"] = "Disagreements are candidate generators, not evidence that the alternative is better."
    return result


def query_history_metadata() -> dict[str, Any]:
    from kaggle.api.kaggle_api_extended import KaggleApi

    api = KaggleApi()
    api.authenticate()
    per_submission = []
    total = wins = losses = score_labels = 0
    for submission_id in D842_LINEAGE:
        episodes = api.competition_list_episodes(submission_id)
        outcomes = []
        first_date = last_date = None
        for episode in episodes:
            own = [agent for agent in episode.agents if int(agent.submission_id) == submission_id]
            if len(own) != 1:
                continue
            reward = float(own[0].reward)
            outcomes.append(reward)
            score_labels += int(getattr(own[0], "initial_score", None) is not None)
            stamp = str(getattr(episode, "create_time", ""))
            first_date = stamp if first_date is None or stamp < first_date else first_date
            last_date = stamp if last_date is None or stamp > last_date else last_date
        row = {
            "submission_id": submission_id,
            "provenance": "hash_proven" if submission_id in HASH_PROVEN else "documented_lineage",
            "games": len(outcomes),
            "wins": sum(value > 0 for value in outcomes),
            "losses": sum(value < 0 for value in outcomes),
            "win_rate": round(sum(value > 0 for value in outcomes) / len(outcomes), 6) if outcomes else None,
            "first_episode_utc": first_date,
            "last_episode_utc": last_date,
        }
        per_submission.append(row)
        total += row["games"]
        wins += row["wins"]
        losses += row["losses"]
    recent = [row for row in per_submission if row["submission_id"] in HASH_PROVEN]
    earlier = [row for row in per_submission if row["submission_id"] not in HASH_PROVEN]

    def combine(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        games = sum(int(row["games"]) for row in rows)
        won = sum(int(row["wins"]) for row in rows)
        return {"games": games, "wins": won, "losses": games - won, "win_rate": round(won / games, 6) if games else None}

    return {
        "all": {"games": total, "wins": wins, "losses": losses, "win_rate": round(wins / total, 6)},
        "documented_earlier_12": combine(earlier),
        "hash_proven_recent_3": combine(recent),
        "per_submission": per_submission,
        "rating_labels_present": score_labels,
        "actual_order_available": False,
        "seat_is_not_order": True,
        "limitations": "Kaggle episode metadata currently omits ratings and actual first player; rating-band and order claims require separate evidence.",
    }


def percent(value: Any) -> str:
    return "n/a" if value is None else f"{100 * float(value):.1f}%"


def write_markdown(report: Mapping[str, Any], path: Path) -> None:
    clean = report["strict_replay_bank"]
    second = clean["by_order"]["second"]
    lines = [
        "# Frozen-d842 floor failure analysis",
        "",
        "This analysis reads only the development and calibration replays. The untouched holdout remained sealed.",
        "",
        "## Bottom line",
        "",
        f"- Strict replay sample: {clean['overall']['games']} games, {clean['overall']['wins']}-{clean['overall']['losses']} ({percent(clean['overall']['win_rate'])}).",
        f"- Actual going second: {second['games']} games, {second['wins']}-{second['losses']} ({percent(second['win_rate'])}).",
        f"- Full d842-lineage metadata: {report['history_metadata']['all']['games']} games, {report['history_metadata']['all']['wins']}-{report['history_metadata']['all']['losses']} ({percent(report['history_metadata']['all']['win_rate'])}).",
        "- The 849-game metadata has no ratings and no actual-order field, so it validates the plateau but cannot identify sub-850 or going-second causes.",
        "",
        "## Actual going-second loss milestones",
        "",
        "| Failure marker | Present games | Present loss rate | Absent loss rate | Difference |",
        "|---|---:|---:|---:|---:|",
    ]
    for flag, value in clean["second_order_associations"].items():
        lines.append(
            f"| {flag} | {value['present']['games']} | {percent(value['present']['loss_rate'])} | "
            f"{percent(value['absent']['loss_rate'])} | {percent(value['loss_rate_difference'])} |"
        )
    lines.extend([
        "",
        "These are associations in a small observational sample, not causal estimates. Overlapping markers should not be added together.",
        "",
        "## Exclusive loss buckets",
        "",
        "| Bucket | All losses | Going-second losses |",
        "|---|---:|---:|",
    ])
    all_buckets = clean["exclusive_loss_buckets"]
    second_buckets = clean["second_exclusive_loss_buckets"]
    for name in sorted(set(all_buckets) | set(second_buckets)):
        lines.append(f"| {name} | {all_buckets.get(name, 0)} | {second_buckets.get(name, 0)} |")
    lines.extend([
        "",
        "## Matchups in the strict bank",
        "",
        "| Matchup | Games | Win rate | Going-second games | Going-second win rate |",
        "|---|---:|---:|---:|---:|",
    ])
    for matchup, values in clean["by_matchup"].items():
        second_values = clean["second_by_matchup"].get(matchup, {})
        lines.append(
            f"| {matchup} | {values['games']} | {percent(values['win_rate'])} | "
            f"{second_values.get('games', 0)} | {percent(second_values.get('win_rate'))} |"
        )
    lines.extend([
        "",
        "## Proposer coverage of the main second-loss strata",
        "",
    ])
    for name, values in report["proposer_disagreements"].items():
        if not isinstance(values, dict) or not name.startswith("second_loss"):
            continue
        lines.extend([
            f"### {name}",
            "",
            f"{values['episodes']} episodes; {values['credible_rows']} credible-proposer rows across {values['credible_unique_states']} states in the relevant window; {values['credible_consensus_rows']} rows have at least two credible proposers. The unqualified floor director contributes {values['floor_director_only_rows']} additional rows alone.",
            "",
            "Top action families: " + ", ".join(f"{key}={count}" for key, count in values["action_families"].items()),
            "",
            "Top credible proposers: " + ", ".join(f"{key}={count}" for key, count in values["credible_proposers"].items()),
            "",
        ])
    lines.extend([
        "## Prioritization",
        "",
        "1. Certify complete-turn alternatives first in actual-second losses that miss a ready Grimmsnarl by own turn three. Prioritize multi-proposer conversion/recovery and energy-allocation disagreements; do not train directly on raw disagreement labels.",
        "2. Split setup from conversion. First-turn width is a useful diagnostic, but only promote setup changes that improve the turn-three ready-Grim milestone under equal-coverage determinizations.",
        "3. Treat on-curve losses separately: certify Shadow Bullet/Boss/bench-target and Munkidori counter-placement choices in games that had a ready Grim by turn three but still took at most one prize.",
        "4. Use wall and spread-damage matchups as route-specific veto strata. Bench-width and low-HP-bench associations are descriptive; require search proof before suppressing a bench play.",
        "5. Do not ship the broad floor director because it dominates raw disagreement volume. Use Tempo, Master, replay-refresh, v2.2-greedy, and A2 consensus only to choose which actions the complete-turn oracle evaluates.",
        "",
        "## Provenance and cautions",
        "",
        f"- Training-bank ID: `{report['provenance']['training_bank_id']}`.",
        f"- Disagreement-bank SHA-256: `{report['provenance']['disagreement_sha256']}`.",
        "- Productive-attack pass detection removes attacks identified as provably nullified when native card metadata is available.",
        "- All outcome associations are episode-level and clustered only descriptively; the untouched holdout is reserved for final gates.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank", type=Path, default=BANK)
    parser.add_argument("--replay-root", type=Path, default=REPLAY_ROOT)
    parser.add_argument("--disagreements", type=Path, default=DISAGREEMENTS)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--skip-history-api", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    units = load_units(args.bank.resolve())
    episodes = [analyze_episode(unit, args.replay_root.resolve()) for unit in units]
    episode_map = {str(row["episode_id"]): row for row in episodes}
    if len(episode_map) != len(episodes):
        raise ValueError("duplicate episode IDs")
    second = [row for row in episodes if row["actual_order"] == "second"]
    flags = (
        "narrow_first_turn",
        "setup_active_not_impidimp",
        "not_two_imp_first_turn",
        "first_turn_missing_snorunt",
        "first_turn_missing_munkidori",
        "no_grim_by_turn_3",
        "no_ready_grim_by_turn_3",
        "no_attack_by_turn_3",
        "no_shadow_by_turn_3",
        "t3_energy_without_ready_grim",
        "t3_overcharged_grim",
        "t3_support_or_excess_energy",
        "t3_low_hp_bench_ge3",
        "t3_enabled_munkidori",
        "no_two_ready_attackers_by_turn_4",
        "passes_with_productive_attack",
        "one_or_fewer_prizes",
    )
    manifest = json.loads((args.bank / "manifest.json").read_text(encoding="utf-8"))
    history = query_history_metadata() if not args.skip_history_api else {
        "all": {"games": 849, "wins": 487, "losses": 362, "win_rate": 487 / 849},
        "limitations": "Static verified aggregate; API refresh skipped.",
    }
    report = {
        "schema_version": 1,
        "method": {
            "allowed_splits": list(ALLOWED_SPLITS),
            "untouched_holdout_read": False,
            "unit": "whole public rated episode",
            "association_warning": "Observational episode associations; not causal estimates.",
            "disagreement_warning": "Proposals require complete-turn equal-coverage certification.",
        },
        "provenance": {
            "training_bank_id": manifest.get("bank_id"),
            "training_bank_status": manifest.get("bank_status"),
            "training_bank_units_used": len(units),
            "disagreement_sha256": sha256_file(args.disagreements.resolve()),
            "frozen_model_sha256": FROZEN_MODEL_SHA256,
            "frozen_deck_canonical_sha256": FROZEN_DECK_SHA256,
        },
        "history_metadata": history,
        "strict_replay_bank": {
            "overall": rate_summary(episodes),
            "by_order": grouped_summary(episodes, "actual_order"),
            "by_matchup": grouped_summary(episodes, "opponent_matchup"),
            "second_by_matchup": grouped_summary(second, "opponent_matchup"),
            "prizes": {
                "overall": prize_summary(episodes),
                "wins": prize_summary([row for row in episodes if row["win"]]),
                "losses": prize_summary([row for row in episodes if not row["win"]]),
                "second": prize_summary(second),
                "second_losses": prize_summary([row for row in second if not row["win"]]),
            },
            "timings": {
                "overall": timing_summary(episodes),
                "wins": timing_summary([row for row in episodes if row["win"]]),
                "losses": timing_summary([row for row in episodes if not row["win"]]),
                "second": timing_summary(second),
                "second_losses": timing_summary([row for row in second if not row["win"]]),
            },
            "attachment_targets": {
                "overall": attachment_summary(episodes),
                "losses": attachment_summary([row for row in episodes if not row["win"]]),
                "second_losses": attachment_summary([row for row in second if not row["win"]]),
            },
            "loss_buckets_by_matchup": matchup_loss_buckets(episodes),
            "second_loss_buckets_by_matchup": matchup_loss_buckets(second),
            "associations": {flag: binary_association(episodes, flag) for flag in flags},
            "second_order_associations": {flag: binary_association(second, flag) for flag in flags},
            "exclusive_loss_buckets": dict(sorted(Counter(
                row["exclusive_loss_bucket"] for row in episodes if not row["win"]
            ).items())),
            "second_exclusive_loss_buckets": dict(sorted(Counter(
                row["exclusive_loss_bucket"] for row in second if not row["win"]
            ).items())),
            "milestone_counts": {
                flag: sum(bool(row.get(flag)) for row in episodes) for flag in flags
            },
            "second_milestone_counts": {
                flag: sum(bool(row.get(flag)) for row in second) for flag in flags
            },
            "loss_episode_details": [row for row in episodes if not row["win"]],
        },
        "proposer_disagreements": analyze_disagreements(args.disagreements.resolve(), episode_map),
    }
    args.output.mkdir(parents=True, exist_ok=True)
    json_path = args.output / "analysis.json"
    md_path = args.output / "REPORT.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(report, md_path)
    print(json.dumps({
        "history": report["history_metadata"]["all"],
        "strict": report["strict_replay_bank"]["overall"],
        "second": report["strict_replay_bank"]["by_order"].get("second"),
        "loss_buckets": report["strict_replay_bank"]["second_exclusive_loss_buckets"],
        "output": str(args.output),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

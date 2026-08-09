#!/usr/bin/env python3
"""Measure the low-rating floor of Grimmsnarl ladder policies from replays."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

from ptcg_ai.replay import iter_decisions
from scripts.crawl_grim_daily import classify, load_archetype_catalog

GRIM = 648
FROSLASS = 104
IMP = 646
MORGREM = 647
SNORUNT = 860
MUNKIDORI = 112
SHADOW_BULLET = 937


def card_names() -> dict[int, str]:
    result = {}
    with (ROOT / "freshstart/data/EN_Card_Data.csv").open(
        encoding="utf-8-sig", errors="ignore", newline=""
    ) as handle:
        for row in csv.DictReader(handle):
            try:
                result[int(row["Card ID"])] = row["Card Name"]
            except (KeyError, TypeError, ValueError):
                continue
    return result


def public_metadata() -> dict[int, dict]:
    rows = {}
    for path in sorted((ROOT / "data/replays").glob("*/episodes_metadata.json")):
        try:
            submission_id = int(path.parent.name)
        except ValueError:
            continue
        for row in json.loads(path.read_text(encoding="utf-8")):
            if "PUBLIC" not in str(row.get("type", "")):
                continue
            normalized = row
            agents = row.get("agents") or []
            if agents:
                heroes = [agent for agent in agents if int(agent.get("submissionId", -1)) == submission_id]
                opponents = [agent for agent in agents if int(agent.get("submissionId", -1)) != submission_id]
                if len(heroes) != 1 or len(opponents) != 1:
                    continue
                hero, opponent = heroes[0], opponents[0]
                normalized = {
                    "id": int(row["id"]),
                    "type": row.get("type"),
                    "hero_seat": int(hero.get("index", 0)),
                    "hero_initialScore": hero.get("initialScore"),
                    "hero_updatedScore": hero.get("updatedScore"),
                    "hero_reward": hero.get("reward"),
                    "opp_submissionId": opponent.get("submissionId"),
                    "opp_initialScore": opponent.get("initialScore"),
                }
            rows[int(row["id"])] = normalized
    live = ROOT / "artifacts/wave1_push/live/latest.json"
    if live.exists():
        payload = json.loads(live.read_text(encoding="utf-8"))
        for report in payload.get("reports", {}).values():
            for game in report.get("games", []):
                rows[int(game["episode_id"])] = {
                    "id": int(game["episode_id"]),
                    "type": "EPISODE_TYPE_PUBLIC",
                    "hero_seat": int(game["seat"]),
                    "hero_initialScore": game.get("our_initial_rating"),
                    "hero_updatedScore": game.get("our_updated_rating"),
                    "hero_reward": game.get("outcome"),
                    "opp_submissionId": game.get("opponent_submission_id"),
                    "opp_initialScore": game.get("opponent_initial_rating"),
                    "wave1_mode": report.get("mode"),
                }
    return rows


def replay_paths() -> dict[int, Path]:
    roots = (ROOT / "data/replays", ROOT / "artifacts/wave1_push/live/replays")
    result = {}
    for root in roots:
        for path in root.rglob("episode-*-replay.json"):
            try:
                episode_id = int(path.name.split("-")[1])
            except (IndexError, ValueError):
                continue
            result.setdefault(episode_id, path)
    return result


def top_grim_rows(catalog: dict[str, tuple[int, ...]]) -> list[dict]:
    """Independent behavioral reference; ratings are intentionally not inferred."""
    root = ROOT / "artifacts/flg_grim_corpus_v5_causal/replays/55290684"
    rows = []
    for path in sorted(root.glob("episode-*-replay.json")):
        replay = json.loads(path.read_text(encoding="utf-8"))
        teams = list((replay.get("info") or {}).get("TeamNames") or [])
        if "flg" not in teams:
            continue
        seat = teams.index("flg")
        rewards = replay.get("rewards") or []
        raw_reward = rewards[seat] if seat < len(rewards) else None
        if raw_reward is None:
            final = final_public_state(replay)
            raw_reward = 1 if final and int(final.get("result", -1)) == seat else -1
        episode_id = int((replay.get("info") or {}).get("EpisodeId") or path.name.split("-")[1])
        meta = {
            "id": episode_id,
            "hero_seat": seat,
            "hero_reward": raw_reward,
            "hero_initialScore": None,
            "hero_updatedScore": None,
            "opp_initialScore": 0.0,
            "opp_submissionId": None,
            "wave1_mode": "top_grim_reference",
        }
        row = analyze_game(path, meta, catalog)
        if row is not None:
            row["opponent_initial_rating"] = None
            rows.append(row)
    return rows


def board_ids(player: dict) -> list[int]:
    return [int(card["id"]) for card in (player.get("active") or []) + (player.get("bench") or []) if card]


def final_public_state(replay: dict) -> dict | None:
    last = None
    for step in replay.get("steps") or []:
        for agent in step:
            current = (agent.get("observation") or {}).get("current")
            if isinstance(current, dict) and len(current.get("players") or []) == 2:
                last = current
    return last


def first_or_none(values: list[int]) -> int | None:
    return min(values) if values else None


def analyze_game(path: Path, meta: dict, catalog: dict[str, tuple[int, ...]]) -> dict | None:
    replay = json.loads(path.read_text(encoding="utf-8"))
    seat = int(meta["hero_seat"])
    steps = replay.get("steps") or []
    if len(steps) < 2 or len(steps[1]) != 2:
        return None
    opponent_deck = steps[1][1 - seat].get("action")
    if not isinstance(opponent_deck, list) or len(opponent_deck) != 60:
        return None
    decisions = list(iter_decisions(replay, None, feature_version=2))
    decisions = [decision for decision in decisions if decision.seat == seat]
    if not decisions:
        return None

    first_turn_width = 0
    initial_width = None
    grim_turns, froslass_turns, shadow_turns, attack_turns = [], [], [], []
    first_prize_turn = None
    passes_with_attack = 0
    attachment_targets: Counter[int] = Counter()
    for decision in decisions:
        current = steps[decision.step][seat]["observation"]["current"]
        player = current["players"][seat]
        board = board_ids(player)
        if decision.turn > 0 and initial_width is None:
            initial_width = len(board)
        if decision.own_turn_ordinal == 1:
            first_turn_width = max(first_turn_width, len(board))
        if GRIM in board:
            grim_turns.append(decision.own_turn_ordinal)
        if FROSLASS in board:
            froslass_turns.append(decision.own_turn_ordinal)
        prizes_taken = 6 - len(player.get("prize") or [])
        if prizes_taken > 0 and first_prize_turn is None:
            first_prize_turn = decision.own_turn_ordinal

        features = decision.features["options"]
        chosen = [features[index] for index in decision.action]
        legal_types = {int(option["option_type"]) for option in features}
        chosen_types = {int(option["option_type"]) for option in chosen}
        if 14 in chosen_types and 13 in legal_types:
            passes_with_attack += 1
        for option in chosen:
            option_type = int(option["option_type"])
            if option_type == 8:
                attachment_targets[int(option["target_card"])] += 1
            if option_type == 9 and int(option["source_card"]) == GRIM:
                grim_turns.append(decision.own_turn_ordinal)
            if option_type == 9 and int(option["source_card"]) == FROSLASS:
                froslass_turns.append(decision.own_turn_ordinal)
            if option_type == 13:
                attack_turns.append(decision.own_turn_ordinal)
                if int(option["attack_id"]) == SHADOW_BULLET:
                    shadow_turns.append(decision.own_turn_ordinal)

    final = final_public_state(replay)
    hero_prizes = opponent_prizes = terminal_turn = None
    hero_board_end = None
    if final is not None:
        hero = final["players"][seat]
        opponent = final["players"][1 - seat]
        hero_prizes = 6 - len(hero.get("prize") or [])
        opponent_prizes = 6 - len(opponent.get("prize") or [])
        terminal_turn = int(final.get("turn", 0))
        hero_board_end = len(board_ids(hero))

    archetype = classify(tuple(sorted(map(int, opponent_deck))), catalog)
    result = {
        "episode_id": int(meta["id"]),
        "source": str(path.relative_to(ROOT)),
        "mode": meta.get("wave1_mode", "historical"),
        "outcome": float(meta["hero_reward"]),
        "hero_initial_rating": meta.get("hero_initialScore"),
        "opponent_initial_rating": meta.get("opp_initialScore"),
        "opponent_submission_id": meta.get("opp_submissionId"),
        "archetype": archetype,
        "order": decisions[0].hero_order,
        "initial_board_width": initial_width,
        "first_turn_max_board_width": first_turn_width,
        "first_grim_own_turn": first_or_none([turn for turn in grim_turns if turn > 0]),
        "first_froslass_own_turn": first_or_none([turn for turn in froslass_turns if turn > 0]),
        "first_attack_own_turn": first_or_none([turn for turn in attack_turns if turn > 0]),
        "first_shadow_bullet_own_turn": first_or_none([turn for turn in shadow_turns if turn > 0]),
        "first_prize_own_turn": first_prize_turn,
        "passes_with_legal_attack": passes_with_attack,
        "attachments": {str(card): count for card, count in sorted(attachment_targets.items())},
        "hero_prizes_taken": hero_prizes,
        "opponent_prizes_taken": opponent_prizes,
        "hero_board_at_end": hero_board_end,
        "terminal_turn": terminal_turn,
        "opponent_deck": sorted(map(int, opponent_deck)),
    }
    result["loss_bucket"] = loss_bucket(result)
    return result


def loss_bucket(row: dict) -> str:
    if row["outcome"] > 0:
        return "win"
    archetype = row["archetype"].lower()
    if row["passes_with_legal_attack"]:
        return "avoidable_pass"
    if (row["hero_prizes_taken"] or 0) >= 4:
        return "close_prize_race"
    if any(name in archetype for name in ("crustle", "ogerpon", "kangaskhan")) and (
        row["first_froslass_own_turn"] is None or row["first_froslass_own_turn"] > 3
    ):
        return "wall_without_early_counterline"
    if row["first_grim_own_turn"] is None or row["first_grim_own_turn"] > 3:
        if (row["first_turn_max_board_width"] or 0) <= 1:
            return "brick_recovery_failure"
        return "late_grim_setup"
    if (row["hero_prizes_taken"] or 0) <= 1:
        return "on_curve_matchup_collapse"
    return "midgame_resource_or_targeting"


def rating_band(value: float | None) -> str:
    if value is None:
        return "unknown"
    value = float(value)
    if value < 650:
        return "under_650"
    if value < 750:
        return "650_749"
    if value < 850:
        return "750_849"
    return "850_plus"


def aggregate(rows: list[dict]) -> dict:
    games = len(rows)
    wins = sum(row["outcome"] > 0 for row in rows)
    numeric = lambda key: [float(row[key]) for row in rows if row.get(key) is not None]
    return {
        "games": games,
        "wins": wins,
        "losses": games - wins,
        "win_rate": wins / games if games else None,
        "grim_by_own_turn_3_rate": (
            sum(row.get("first_grim_own_turn") is not None and row["first_grim_own_turn"] <= 3 for row in rows) / games
            if games else None
        ),
        "shadow_by_own_turn_3_rate": (
            sum(row.get("first_shadow_bullet_own_turn") is not None and row["first_shadow_bullet_own_turn"] <= 3 for row in rows) / games
            if games else None
        ),
        "wide_first_turn_rate": (
            sum((row.get("first_turn_max_board_width") or 0) >= 3 for row in rows) / games if games else None
        ),
        "median_first_grim_own_turn": statistics.median(numeric("first_grim_own_turn")) if numeric("first_grim_own_turn") else None,
        "games_with_avoidable_pass": sum(row["passes_with_legal_attack"] > 0 for row in rows),
        "loss_buckets": dict(sorted(Counter(row["loss_bucket"] for row in rows if row["outcome"] <= 0).items())),
    }


def grouped(rows: list[dict], key) -> dict:
    groups = defaultdict(list)
    for row in rows:
        groups[str(key(row))].append(row)
    return {name: aggregate(group) for name, group in sorted(groups.items())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="artifacts/wave1_push/floor_analysis.json")
    args = parser.parse_args()
    metadata = public_metadata()
    paths = replay_paths()
    catalog = load_archetype_catalog(ROOT / "freshstart/decklists")
    rows = []
    failures = {}
    for episode_id, meta in sorted(metadata.items()):
        path = paths.get(episode_id)
        if path is None or meta.get("opp_initialScore") is None:
            continue
        try:
            row = analyze_game(path, meta, catalog)
            if row is not None:
                rows.append(row)
        except Exception as exc:
            failures[str(episode_id)] = repr(exc)
    sub850 = [row for row in rows if float(row["opponent_initial_rating"]) < 850]
    recent = [row for row in rows if row["mode"] in {"fan", "tempo"}]
    reference = top_grim_rows(catalog)
    result = {
        "method": {
            "unit": "completed public replay with frozen opponent initial rating",
            "loss_attribution": "earliest observable recurring failure bucket; diagnostic, not causal proof",
            "rows": len(rows),
            "parse_failures": failures,
        },
        "overall": aggregate(rows),
        "sub_850": aggregate(sub850),
        "sub_850_by_rating_band": grouped(sub850, lambda row: rating_band(row["opponent_initial_rating"])),
        "sub_850_by_archetype": grouped(sub850, lambda row: row["archetype"]),
        "sub_850_wins": aggregate([row for row in sub850 if row["outcome"] > 0]),
        "sub_850_losses": aggregate([row for row in sub850 if row["outcome"] <= 0]),
        "recent_wave1": aggregate(recent),
        "recent_wave1_games": recent,
        "sub_850_loss_games": [row for row in sub850 if row["outcome"] <= 0],
        "top_grim_reference": aggregate(reference),
        "top_grim_reference_by_archetype": grouped(reference, lambda row: row["archetype"]),
        "top_grim_reference_games": reference,
    }
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "rows": len(rows),
        "sub_850": result["sub_850"],
        "sub_850_by_rating_band": result["sub_850_by_rating_band"],
        "recent_wave1": result["recent_wave1"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

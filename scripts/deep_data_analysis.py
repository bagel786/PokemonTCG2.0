#!/usr/bin/env python3
"""Deep data analysis of Kaggle Pokemon TCG submissions 55171237 and 55171235."""

from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load_card_db() -> dict[int, str]:
    cards = {}
    csv_path = ROOT / "freshstart" / "data" / "EN_Card_Data.csv"
    if csv_path.exists():
        with open(csv_path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                cards[int(row["Card ID"])] = row["Card Name"]
    return cards


def load_known_decks() -> dict[str, set[int]]:
    known = {}
    deck_dir = ROOT / "freshstart" / "decklists"
    if deck_dir.exists():
        for p in sorted(deck_dir.glob("*.deck.csv")):
            cards = [int(line) for line in p.read_text().split() if line.strip()]
            known[p.name.replace(".deck.csv", "")] = set(cards)
    return known


def load_leaderboard() -> dict[int, dict[str, Any]]:
    candidates = list((ROOT / "artifacts" / "ladder").glob("*.csv")) + list(ROOT.glob("*leaderboard*.csv"))
    if not candidates:
        return {}
    newest = max(candidates, key=lambda p: p.stat().st_mtime)
    data = {}
    with open(newest, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for rank, row in enumerate(reader, 1):
            tid = int(row["TeamId"])
            data[tid] = {
                "team_id": tid,
                "team_name": row["TeamName"],
                "score": float(row["Score"]) if row.get("Score") else None,
                "rank": rank,
            }
    return data


def classify_deck(deck_cards: list[int], known_decks: dict[str, set[int]], card_db: dict[int, str]) -> tuple[str, str, float]:
    if not deck_cards or len(deck_cards) != 60:
        return "Invalid/Empty", "invalid", 0.0

    deck_set = set(deck_cards)
    best_name = "Unknown"
    best_jaccard = 0.0
    for name, t_set in known_decks.items():
        j = len(deck_set & t_set) / len(deck_set | t_set)
        if j > best_jaccard:
            best_jaccard = j
            best_name = name

    # Card names present
    card_names = [card_db.get(cid, "") for cid in deck_cards]
    names_str = " ".join(card_names).lower()

    if "grimmsnarl" in names_str or "marnie's impidimp" in names_str or "morgrem" in names_str:
        label = "Marnie's Grimmsnarl ex"
        slug = "grimmsnarl_marnie"
    elif "mewtwo ex" in names_str or "team rocket's mewtwo" in names_str or ("mewtwo" in names_str and "team rocket" in names_str):
        label = "Team Rocket's Mewtwo ex"
        slug = "team_rockets_mewtwo_ex"
    elif "alakazam" in names_str or "kadabra" in names_str or "dudunsparce" in names_str and "alakazam" in names_str:
        label = "Alakazam / Dudunsparce"
        slug = "alakazam_dudunsparce"
    elif "garchomp" in names_str or "cynthia's garchomp" in names_str or "gabite" in names_str:
        label = "Cynthia's Garchomp ex"
        slug = "cynthias_garchomp_ex"
    elif "crustle" in names_str or "dwebble" in names_str:
        label = "Kangaskhan / Crustle Lock"
        slug = "kangaskhan_crustle"
    elif "dragapult" in names_str or "drakloak" in names_str or "dreepy" in names_str:
        label = "Dragapult ex"
        slug = "dragapult_ex"
    elif "dipplin" in names_str or "thwackey" in names_str:
        label = "Dipplin / Thwackey"
        slug = "dipplin_thwackey"
    elif "lopunny" in names_str:
        label = "Mega Lopunny ex"
        slug = "mega_lopunny_ex"
    elif "starmie" in names_str or ("froslass" in names_str and "grimmsnarl" not in names_str):
        label = "Mega Starmie / Froslass"
        slug = "mega_starmie_froslass"
    elif "kangaskhan" in names_str or "ogerpon" in names_str:
        label = "Mega Kangaskhan Toolbox"
        slug = "mega_kangaskhan_toolbox"
    else:
        friendly = {
            "grimmsnarl_marnie": "Marnie's Grimmsnarl ex",
            "team_rockets_mewtwo_ex": "Team Rocket's Mewtwo ex",
            "alakazam_dudunsparce": "Alakazam / Dudunsparce",
            "cynthias_garchomp_ex": "Cynthia's Garchomp ex",
            "kangaskhan_crustle": "Kangaskhan / Crustle Lock",
            "dragapult_ex": "Dragapult ex",
            "dipplin_thwackey": "Dipplin / Thwackey",
            "mega_lopunny_ex": "Mega Lopunny ex",
            "mega_starmie_froslass": "Mega Starmie / Froslass",
            "mega_kangaskhan_toolbox": "Mega Kangaskhan Toolbox",
        }
        if best_jaccard >= 0.35 and best_name in friendly:
            label = friendly[best_name]
            slug = best_name
        else:
            label = f"Rogue/Custom ({best_name})" if best_jaccard >= 0.2 else "Unknown Archetype"
            slug = "unknown"

    return label, slug, best_jaccard


def wilson_score_interval(k: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    z = 1.95996
    p = k / n
    denominator = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def process_submission_data(sub_id: int, card_db: dict[int, str], known_decks: dict[str, set[int]], leaderboard: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    sub_dir = ROOT / "data" / "replays" / str(sub_id)
    meta_path = sub_dir / "episodes_metadata.json"
    if not meta_path.exists():
        print(f"Error: {meta_path} does not exist.")
        return []

    meta_episodes = json.loads(meta_path.read_text())
    meta_by_id = {ep["id"]: ep for ep in meta_episodes}

    replay_files = [f for f in sub_dir.glob("*.json") if f.name != "episodes_metadata.json"]
    records = []

    for r_path in replay_files:
        try:
            r_data = json.loads(r_path.read_text())
        except Exception:
            continue

        ep_id = r_data.get("info", {}).get("EpisodeId")
        if not ep_id:
            digits = "".join(c for c in r_path.stem if c.isdigit())
            ep_id = int(digits) if digits else None

        meta_ep = meta_by_id.get(ep_id, {})
        agents = meta_ep.get("agents", [])

        us_agent = None
        opp_agent = None
        for a in agents:
            if a.get("submissionId") == sub_id:
                us_agent = a
            else:
                opp_agent = a

        if not us_agent:
            continue

        our_seat = us_agent.get("index", 0)
        opp_seat = 1 if our_seat == 0 else 0

        our_initial_score = us_agent.get("initialScore")
        our_updated_score = us_agent.get("updatedScore")
        our_reward = us_agent.get("reward")

        opp_initial_score = opp_agent.get("initialScore") if opp_agent else None
        opp_updated_score = opp_agent.get("updatedScore") if opp_agent else None
        opp_team_id = opp_agent.get("teamId") if opp_agent else None
        opp_sub_id = opp_agent.get("submissionId") if opp_agent else None

        lb_info = leaderboard.get(opp_team_id, {})
        opp_name = lb_info.get("team_name")
        if not opp_name:
            t_names = r_data.get("info", {}).get("TeamNames", [])
            if len(t_names) > opp_seat:
                opp_name = t_names[opp_seat]
            else:
                opp_name = f"Team_{opp_team_id}"
        opp_lb_rank = lb_info.get("rank")
        opp_lb_score = lb_info.get("score")

        steps = r_data.get("steps", [])
        our_deck_cards = []
        opp_deck_cards = []
        if len(steps) > 1:
            if our_seat < len(steps[1]):
                our_deck_cards = steps[1][our_seat].get("action") or []
            if opp_seat < len(steps[1]):
                opp_deck_cards = steps[1][opp_seat].get("action") or []

        our_arch_label, our_arch_slug, our_arch_sim = classify_deck(our_deck_cards, known_decks, card_db)
        opp_arch_label, opp_arch_slug, opp_arch_sim = classify_deck(opp_deck_cards, known_decks, card_db)

        won = our_reward is not None and our_reward > 0
        lost = our_reward is not None and our_reward < 0
        tied = our_reward == 0 or our_reward is None

        our_prizes_left = None
        opp_prizes_left = None
        our_deck_left = None
        opp_deck_left = None
        game_end_reason = "Unknown"

        if steps:
            last_step = steps[-1]
            obs_p0 = last_step[0].get("observation", {})
            curr = obs_p0.get("current")
            if curr and "players" in curr and len(curr["players"]) >= 2:
                p_us = curr["players"][our_seat]
                p_opp = curr["players"][opp_seat]
                our_prizes_left = len(p_us.get("prize", []))
                opp_prizes_left = len(p_opp.get("prize", []))
                our_deck_left = p_us.get("deckCount")
                opp_deck_left = p_opp.get("deckCount")

                if our_prizes_left == 0 and won:
                    game_end_reason = "Prize Clear (6 Prizes Taken by Us)"
                elif opp_prizes_left == 0 and lost:
                    game_end_reason = "Prize Clear (6 Prizes Taken by Opponent)"
                elif (p_opp.get("active") is None or len(p_opp.get("active", [])) == 0) and won:
                    game_end_reason = "Bench Out / Extinction (Us Won)"
                elif (p_us.get("active") is None or len(p_us.get("active", [])) == 0) and lost:
                    game_end_reason = "Bench Out / Extinction (Opponent Won)"
                elif opp_deck_left == 0 and won:
                    game_end_reason = "Deck Out (Opponent Milled)"
                elif our_deck_left == 0 and lost:
                    game_end_reason = "Deck Out (We Milled)"
                elif won:
                    game_end_reason = f"Concession / Turn Limit Win (Prizes: {6-opp_prizes_left} vs {6-our_prizes_left})"
                elif lost:
                    game_end_reason = f"Concession / Turn Limit Loss (Prizes: {6-opp_prizes_left} vs {6-our_prizes_left})"
                else:
                    game_end_reason = "Draw / Incomplete"

        statuses = r_data.get("statuses", [])
        our_status = statuses[our_seat] if our_seat < len(statuses) else "UNKNOWN"
        opp_status = statuses[opp_seat] if opp_seat < len(statuses) else "UNKNOWN"

        record = {
            "episode_id": ep_id,
            "submission_id": sub_id,
            "create_time": meta_ep.get("createTime"),
            "won": won,
            "lost": lost,
            "tied": tied,
            "our_seat": our_seat,
            "our_initial_score": our_initial_score,
            "our_updated_score": our_updated_score,
            "score_delta": (our_updated_score - our_initial_score) if (our_updated_score is not None and our_initial_score is not None) else 0.0,
            "our_reward": our_reward,
            "our_archetype": our_arch_label,
            "our_archetype_slug": our_arch_slug,
            "our_arch_sim": our_arch_sim,
            "opp_archetype": opp_arch_label,
            "opp_archetype_slug": opp_arch_slug,
            "opp_arch_sim": opp_arch_sim,
            "opp_team_id": opp_team_id,
            "opp_name": opp_name,
            "opp_sub_id": opp_sub_id,
            "opp_initial_score": opp_initial_score,
            "opp_updated_score": opp_updated_score,
            "opp_lb_rank": opp_lb_rank,
            "opp_lb_score": opp_lb_score,
            "num_steps": len(steps),
            "our_prizes_left": our_prizes_left,
            "opp_prizes_left": opp_prizes_left,
            "prizes_taken_by_us": (6 - opp_prizes_left) if opp_prizes_left is not None else None,
            "prizes_taken_by_opp": (6 - our_prizes_left) if our_prizes_left is not None else None,
            "end_reason": game_end_reason,
            "our_status": our_status,
            "opp_status": opp_status,
        }
        records.append(record)

    records.sort(key=lambda r: (r["create_time"] or "", r["episode_id"] or 0))
    return records


def analyze_records(records: list[dict[str, Any]], label: str) -> dict[str, Any]:
    if not records:
        return {"label": label, "total_games": 0, "wins": 0, "losses": 0, "ties": 0, "win_rate": 0.0, "ci_95": (0.0, 0.0), "first_score": 0.0, "last_score": 0.0, "peak_score": 0.0, "net_rating_delta": 0.0, "avg_win_delta": 0.0, "avg_loss_delta": 0.0, "seat0": {"games": 0, "wins": 0, "win_rate": 0.0, "ci_95": (0.0, 0.0)}, "seat1": {"games": 0, "wins": 0, "win_rate": 0.0, "ci_95": (0.0, 0.0)}, "our_archetypes": {}, "opp_archetypes": {}, "score_bands": {}, "end_reasons": {}, "steps": {"mean_overall": 0, "mean_win": 0, "mean_loss": 0}, "prizes": {"avg_taken_in_wins": 0, "avg_taken_in_losses": 0, "avg_conceded_in_wins": 0, "avg_conceded_in_losses": 0}, "raw_records": []}

    total_games = len(records)
    wins = sum(1 for r in records if r["won"])
    losses = sum(1 for r in records if r["lost"])
    ties = sum(1 for r in records if r["tied"])
    win_rate = wins / total_games if total_games > 0 else 0.0
    ci_low, ci_high = wilson_score_interval(wins, total_games)

    initial_scores = [r["our_initial_score"] for r in records if r["our_initial_score"] is not None]
    updated_scores = [r["our_updated_score"] for r in records if r["our_updated_score"] is not None]
    score_deltas = [r["score_delta"] for r in records if r["score_delta"] is not None]

    first_score = initial_scores[0] if initial_scores else 0.0
    last_score = updated_scores[-1] if updated_scores else 0.0
    peak_score = max(updated_scores) if updated_scores else 0.0
    min_score = min(initial_scores + updated_scores) if (initial_scores and updated_scores) else 0.0
    net_rating_delta = (last_score - first_score) if (last_score and first_score) else 0.0

    avg_win_delta = sum(r["score_delta"] for r in records if r["won"]) / max(1, wins)
    avg_loss_delta = sum(r["score_delta"] for r in records if r["lost"]) / max(1, losses)

    # Seat Performance
    seat0_records = [r for r in records if r["our_seat"] == 0]
    seat1_records = [r for r in records if r["our_seat"] == 1]

    s0_games = len(seat0_records)
    s0_wins = sum(1 for r in seat0_records if r["won"])
    s0_winrate = s0_wins / s0_games if s0_games > 0 else 0.0
    s0_low, s0_high = wilson_score_interval(s0_wins, s0_games)
    s0_delta = sum(r["score_delta"] for r in seat0_records)

    s1_games = len(seat1_records)
    s1_wins = sum(1 for r in seat1_records if r["won"])
    s1_winrate = s1_wins / s1_games if s1_games > 0 else 0.0
    s1_low, s1_high = wilson_score_interval(s1_wins, s1_games)
    s1_delta = sum(r["score_delta"] for r in seat1_records)

    # Our Archetypes
    our_arch_groups = defaultdict(list)
    for r in records:
        our_arch_groups[r["our_archetype"]].append(r)

    our_arch_stats = {}
    for arch, g_recs in our_arch_groups.items():
        g_n = len(g_recs)
        g_w = sum(1 for r in g_recs if r["won"])
        g_s0 = [r for r in g_recs if r["our_seat"] == 0]
        g_s1 = [r for r in g_recs if r["our_seat"] == 1]
        g_s0_w = sum(1 for r in g_s0 if r["won"])
        g_s1_w = sum(1 for r in g_s1 if r["won"])
        g_init_scores = [r["our_initial_score"] for r in g_recs if r["our_initial_score"] is not None]
        g_opp_scores = [r["opp_initial_score"] for r in g_recs if r["opp_initial_score"] is not None]
        g_deltas = [r["score_delta"] for r in g_recs]
        ci_l, ci_h = wilson_score_interval(g_w, g_n)

        our_arch_stats[arch] = {
            "games": g_n,
            "wins": g_w,
            "losses": g_n - g_w,
            "win_rate": g_w / g_n,
            "ci_95": (ci_l, ci_h),
            "seat0_games": len(g_s0),
            "seat0_winrate": g_s0_w / len(g_s0) if g_s0 else 0.0,
            "seat1_games": len(g_s1),
            "seat1_winrate": g_s1_w / len(g_s1) if g_s1 else 0.0,
            "mean_our_rating": sum(g_init_scores) / len(g_init_scores) if g_init_scores else 0.0,
            "mean_opp_rating": sum(g_opp_scores) / len(g_opp_scores) if g_opp_scores else 0.0,
            "total_delta": sum(g_deltas),
            "mean_delta_per_game": sum(g_deltas) / g_n if g_n > 0 else 0.0,
        }

    # Opponent Archetypes
    opp_arch_groups = defaultdict(list)
    for r in records:
        opp_arch_groups[r["opp_archetype"]].append(r)

    opp_arch_stats = {}
    for arch, g_recs in opp_arch_groups.items():
        g_n = len(g_recs)
        g_w = sum(1 for r in g_recs if r["won"])
        g_s0 = [r for r in g_recs if r["our_seat"] == 0]
        g_s1 = [r for r in g_recs if r["our_seat"] == 1]
        g_s0_w = sum(1 for r in g_s0 if r["won"])
        g_s1_w = sum(1 for r in g_s1 if r["won"])
        g_deltas = [r["score_delta"] for r in g_recs]
        g_opp_scores = [r["opp_initial_score"] for r in g_recs if r["opp_initial_score"] is not None]
        ci_l, ci_h = wilson_score_interval(g_w, g_n)

        rate = g_w / g_n
        cost = (1.0 - rate) * g_n

        opp_arch_stats[arch] = {
            "games": g_n,
            "share": g_n / total_games,
            "wins": g_w,
            "losses": g_n - g_w,
            "win_rate": rate,
            "ci_95": (ci_l, ci_h),
            "cost": cost,
            "seat0_games": len(g_s0),
            "seat0_winrate": g_s0_w / len(g_s0) if g_s0 else 0.0,
            "seat1_games": len(g_s1),
            "seat1_winrate": g_s1_w / len(g_s1) if g_s1 else 0.0,
            "mean_opp_rating": sum(g_opp_scores) / len(g_opp_scores) if g_opp_scores else 0.0,
            "net_elo_delta": sum(g_deltas),
        }

    # Score Bands
    score_bands = [
        ("< 900 (Entry / Sub-900)", lambda s: s < 900),
        ("900 - 949 (Low Ladder)", lambda s: 900 <= s < 950),
        ("950 - 999 (Mid Ladder)", lambda s: 950 <= s < 1000),
        ("1000 - 1099 (High Ladder)", lambda s: 1000 <= s < 1100),
        ("1100+ (Elite / Top 50)", lambda s: s >= 1100),
    ]

    band_stats = {}
    for band_name, fn in score_bands:
        b_recs = [r for r in records if r["opp_initial_score"] is not None and fn(r["opp_initial_score"])]
        b_n = len(b_recs)
        b_w = sum(1 for r in b_recs if r["won"])
        b_deltas = [r["score_delta"] for r in b_recs]
        ci_l, ci_h = wilson_score_interval(b_w, b_n) if b_n > 0 else (0.0, 0.0)

        band_stats[band_name] = {
            "games": b_n,
            "wins": b_w,
            "losses": b_n - b_w,
            "win_rate": (b_w / b_n) if b_n > 0 else 0.0,
            "ci_95": (ci_l, ci_h),
            "net_delta": sum(b_deltas),
            "avg_delta": sum(b_deltas) / b_n if b_n > 0 else 0.0,
        }

    end_reasons = Counter(r["end_reason"] for r in records)
    step_counts = [r["num_steps"] for r in records]
    step_counts_win = [r["num_steps"] for r in records if r["won"]]
    step_counts_loss = [r["num_steps"] for r in records if r["lost"]]

    prizes_taken_win = [r["prizes_taken_by_us"] for r in records if r["won"] and r["prizes_taken_by_us"] is not None]
    prizes_taken_loss = [r["prizes_taken_by_us"] for r in records if r["lost"] and r["prizes_taken_by_us"] is not None]
    prizes_conceded_win = [r["prizes_taken_by_opp"] for r in records if r["won"] and r["prizes_taken_by_opp"] is not None]
    prizes_conceded_loss = [r["prizes_taken_by_opp"] for r in records if r["lost"] and r["prizes_taken_by_opp"] is not None]

    return {
        "label": label,
        "submission_id": records[0]["submission_id"] if records else None,
        "total_games": total_games,
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "win_rate": win_rate,
        "ci_95": (ci_low, ci_high),
        "first_score": first_score,
        "last_score": last_score,
        "peak_score": peak_score,
        "min_score": min_score,
        "net_rating_delta": net_rating_delta,
        "avg_win_delta": avg_win_delta,
        "avg_loss_delta": avg_loss_delta,
        "seat0": {
            "games": s0_games,
            "wins": s0_wins,
            "win_rate": s0_winrate,
            "ci_95": (s0_low, s0_high),
            "net_delta": s0_delta,
        },
        "seat1": {
            "games": s1_games,
            "wins": s1_wins,
            "win_rate": s1_winrate,
            "ci_95": (s1_low, s1_high),
            "net_delta": s1_delta,
        },
        "our_archetypes": our_arch_stats,
        "opp_archetypes": opp_arch_stats,
        "score_bands": band_stats,
        "end_reasons": dict(end_reasons),
        "steps": {
            "mean_overall": sum(step_counts) / len(step_counts) if step_counts else 0,
            "mean_win": sum(step_counts_win) / len(step_counts_win) if step_counts_win else 0,
            "mean_loss": sum(step_counts_loss) / len(step_counts_loss) if step_counts_loss else 0,
        },
        "prizes": {
            "avg_taken_in_wins": sum(prizes_taken_win) / len(prizes_taken_win) if prizes_taken_win else 0,
            "avg_taken_in_losses": sum(prizes_taken_loss) / len(prizes_taken_loss) if prizes_taken_loss else 0,
            "avg_conceded_in_wins": sum(prizes_conceded_win) / len(prizes_conceded_win) if prizes_conceded_win else 0,
            "avg_conceded_in_losses": sum(prizes_conceded_loss) / len(prizes_conceded_loss) if prizes_conceded_loss else 0,
        },
        "raw_records": records,
    }


def generate_markdown_report(stats_37: dict[str, Any], stats_35: dict[str, Any], stats_combined: dict[str, Any]) -> str:
    lines = []
    lines.append("# Deep Replay & Ladder Performance Analysis")
    lines.append("### Submissions 55171237 vs 55171235")
    lines.append("")
    lines.append("> [!NOTE]")
    lines.append("> Comprehensive statistical breakdown across 129 live Kaggle ladder replays: **Submission 55171237** (64 games) and **Submission 55171235** (65 games).")
    lines.append("")

    # Section 1: Executive Overview
    lines.append("## 1. Overall Performance Summary")
    lines.append("")
    lines.append("| Metric | Submission 55171237 | Submission 55171235 | Combined Total |")
    lines.append("| :--- | :---: | :---: | :---: |")
    lines.append(f"| **Total Games** | {stats_37['total_games']} | {stats_35['total_games']} | {stats_combined['total_games']} |")
    lines.append(f"| **Record (W - L - T)** | {stats_37['wins']}W - {stats_37['losses']}L - {stats_37['ties']}T | {stats_35['wins']}W - {stats_35['losses']}L - {stats_35['ties']}T | {stats_combined['wins']}W - {stats_combined['losses']}L - {stats_combined['ties']}T |")
    lines.append(f"| **Win Rate (95% CI)** | **{stats_37['win_rate']:.1%}** ({stats_37['ci_95'][0]:.1%} - {stats_37['ci_95'][1]:.1%}) | **{stats_35['win_rate']:.1%}** ({stats_35['ci_95'][0]:.1%} - {stats_35['ci_95'][1]:.1%}) | **{stats_combined['win_rate']:.1%}** ({stats_combined['ci_95'][0]:.1%} - {stats_combined['ci_95'][1]:.1%}) |")
    lines.append(f"| **Initial Score** | {stats_37['first_score']:.1f} | {stats_35['first_score']:.1f} | - |")
    lines.append(f"| **Peak Score** | {stats_37['peak_score']:.1f} | {stats_35['peak_score']:.1f} | {max(stats_37['peak_score'], stats_35['peak_score']):.1f} |")
    lines.append(f"| **Final Score** | **{stats_37['last_score']:.1f}** | **{stats_35['last_score']:.1f}** | - |")
    lines.append(f"| **Net Rating Delta** | **{stats_37['net_rating_delta']:+.1f}** | **{stats_35['net_rating_delta']:+.1f}** | **{stats_37['net_rating_delta'] + stats_35['net_rating_delta']:+.1f}** |")
    lines.append(f"| **Avg Gain on Win** | +{stats_37['avg_win_delta']:.2f} | +{stats_35['avg_win_delta']:.2f} | +{stats_combined['avg_win_delta']:.2f} |")
    lines.append(f"| **Avg Loss on Defeat** | {stats_37['avg_loss_delta']:.2f} | {stats_35['avg_loss_delta']:.2f} | {stats_combined['avg_loss_delta']:.2f} |")
    lines.append(f"| **Our Primary Archetype** | {list(stats_37['our_archetypes'].keys())[0] if stats_37['our_archetypes'] else 'N/A'} | {list(stats_35['our_archetypes'].keys())[0] if stats_35['our_archetypes'] else 'N/A'} | - |")
    lines.append("")

    # Section 2: Seat Performance
    lines.append("## 2. Win Rate by Seat Number (Going 1st vs Going 2nd)")
    lines.append("")
    lines.append("| Submission | Seat 0 (Going 1st) | Seat 1 (Going 2nd) | First-Turn Advantage $\\Delta$ |")
    lines.append("| :--- | :---: | :---: | :---: |")
    lines.append(f"| **Sub 55171237** | **{stats_37['seat0']['win_rate']:.1%}** ({stats_37['seat0']['wins']}/{stats_37['seat0']['games']}) | **{stats_37['seat1']['win_rate']:.1%}** ({stats_37['seat1']['wins']}/{stats_37['seat1']['games']}) | {stats_37['seat0']['win_rate'] - stats_37['seat1']['win_rate']:+.1%} |")
    lines.append(f"| **Sub 55171235** | **{stats_35['seat0']['win_rate']:.1%}** ({stats_35['seat0']['wins']}/{stats_35['seat0']['games']}) | **{stats_35['seat1']['win_rate']:.1%}** ({stats_35['seat1']['wins']}/{stats_35['seat1']['games']}) | {stats_35['seat0']['win_rate'] - stats_35['seat1']['win_rate']:+.1%} |")
    lines.append(f"| **Combined Total** | **{stats_combined['seat0']['win_rate']:.1%}** ({stats_combined['seat0']['wins']}/{stats_combined['seat0']['games']}) | **{stats_combined['seat1']['win_rate']:.1%}** ({stats_combined['seat1']['wins']}/{stats_combined['seat1']['games']}) | {stats_combined['seat0']['win_rate'] - stats_combined['seat1']['win_rate']:+.1%} |")
    lines.append("")

    # Section 3: Performance Per Archetype We Played
    lines.append("## 3. Mean Rating & Win Rate Per Archetype That WE Played")
    lines.append("")
    lines.append("| Archetype We Piloted | Sub ID | Games | Record (W-L) | Win Rate | Mean Rating | Opp Rating | Net Delta |")
    lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for sub_stat in [stats_37, stats_35]:
        for arch, a_data in sub_stat["our_archetypes"].items():
            lines.append(f"| **{arch}** | {sub_stat['submission_id']} | {a_data['games']} | {a_data['wins']}W - {a_data['losses']}L | **{a_data['win_rate']:.1%}** | {a_data['mean_our_rating']:.1f} | {a_data['mean_opp_rating']:.1f} | {a_data['total_delta']:+.1f} |")
    lines.append("")

    # Section 4: Matchups Against Opponent Archetypes
    lines.append("## 4. Win Rates Against Opponent Archetypes")
    lines.append("")
    lines.append("Ranked by **Ladder Cost** = $(1 - \\text{WinRate}) \\times \\text{Games}$ (measuring where the most losses were conceded):")
    lines.append("")
    lines.append("| Opponent Archetype | Share | Games | Won | Lost | Win Rate (95% CI) | Going 1st | Going 2nd | Net Elo $\\Delta$ | Ladder Cost |")
    lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    sorted_opps = sorted(stats_combined["opp_archetypes"].items(), key=lambda x: x[1]["cost"], reverse=True)
    for arch, a_data in sorted_opps:
        lines.append(
            f"| **{arch}** | {a_data['share']:.1%} | {a_data['games']} | {a_data['wins']} | {a_data['losses']} | "
            f"**{a_data['win_rate']:.1%}** ({a_data['ci_95'][0]:.0%}–{a_data['ci_95'][1]:.0%}) | "
            f"{a_data['seat0_winrate']:.0%} ({a_data['seat0_games']}g) | {a_data['seat1_winrate']:.0%} ({a_data['seat1_games']}g) | "
            f"{a_data['net_elo_delta']:+.1f} | **{a_data['cost']:.1f}** |"
        )
    lines.append("")

    # Section 5: Score Bands
    lines.append("## 5. Win Rate by Opponent Score Band")
    lines.append("")
    lines.append("| Opponent Score Band | Games | Wins | Losses | Win Rate (95% CI) | Net Elo $\\Delta$ | Avg $\\Delta$ / Game |")
    lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: |")
    for band, b_data in stats_combined["score_bands"].items():
        ci_str = f"({b_data['ci_95'][0]:.0%}–{b_data['ci_95'][1]:.0%})" if b_data['games'] > 0 else "-"
        lines.append(f"| **{band}** | {b_data['games']} | {b_data['wins']} | {b_data['losses']} | **{b_data['win_rate']:.1%}** {ci_str} | {b_data['net_delta']:+.1f} | {b_data['avg_delta']:+.2f} |")
    lines.append("")

    # Section 6: Game Dynamics & End Conditions
    lines.append("## 6. Match Dynamics & Failure Mode Analysis")
    lines.append("")
    lines.append("### Match End Causes")
    lines.append("")
    lines.append("| End Condition / Cause | Sub 55171237 | Sub 55171235 | Combined Total | % of Total Games |")
    lines.append("| :--- | :---: | :---: | :---: | :---: |")
    all_reasons = sorted(set(stats_37["end_reasons"].keys()) | set(stats_35["end_reasons"].keys()))
    for reason in all_reasons:
        c37 = stats_37["end_reasons"].get(reason, 0)
        c35 = stats_35["end_reasons"].get(reason, 0)
        c_tot = c37 + c35
        lines.append(f"| {reason} | {c37} | {c35} | **{c_tot}** | {c_tot / stats_combined['total_games']:.1%} |")
    lines.append("")

    lines.append("### Prize Differential & Step Counts")
    lines.append("")
    lines.append("| Dimension | Wins | Losses | Differential |")
    lines.append("| :--- | :---: | :---: | :---: |")
    lines.append(f"| **Avg Prizes Taken by Us** | **{stats_combined['prizes']['avg_taken_in_wins']:.2f} / 6** | {stats_combined['prizes']['avg_taken_in_losses']:.2f} / 6 | {stats_combined['prizes']['avg_taken_in_wins'] - stats_combined['prizes']['avg_taken_in_losses']:+.2f} |")
    lines.append(f"| **Avg Prizes Conceded** | {stats_combined['prizes']['avg_conceded_in_wins']:.2f} / 6 | **{stats_combined['prizes']['avg_conceded_in_losses']:.2f} / 6** | {stats_combined['prizes']['avg_conceded_in_wins'] - stats_combined['prizes']['avg_conceded_in_losses']:+.2f} |")
    lines.append(f"| **Avg Steps per Match** | {stats_combined['steps']['mean_win']:.1f} steps | {stats_combined['steps']['mean_loss']:.1f} steps | {stats_combined['steps']['mean_win'] - stats_combined['steps']['mean_loss']:+.1f} steps |")
    lines.append("")

    # Section 7: Notable Elite Matchups
    lines.append("## 7. Matches vs Top Ladder Teams (Opponent Rating $\\ge 1000$)")
    lines.append("")
    elite_games = [r for r in stats_combined["raw_records"] if (r["opp_initial_score"] and r["opp_initial_score"] >= 1000) or (r["opp_lb_rank"] and r["opp_lb_rank"] <= 100)]
    if elite_games:
        lines.append("| Episode | Sub ID | Opponent Team | Opp Rating/Rank | Opp Archetype | Seat | Outcome | Elo $\\Delta$ | Game End Reason |")
        lines.append("| :--- | :---: | :--- | :---: | :--- | :---: | :---: | :---: | :--- |")
        for r in elite_games:
            outcome = "✅ **WIN**" if r["won"] else "❌ **LOSS**"
            rank_str = f"#{r['opp_lb_rank']} ({r['opp_initial_score']:.1f})" if r['opp_lb_rank'] else f"{r['opp_initial_score']:.1f}"
            lines.append(f"| [{r['episode_id']}](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle/leaderboard?dialog=episodes-episode-{r['episode_id']}) | {r['submission_id']} | **{r['opp_name']}** | {rank_str} | {r['opp_archetype']} | Seat {r['our_seat']} | {outcome} | {r['score_delta']:+.1f} | {r['end_reason']} |")
    lines.append("")

    return "\n".join(lines)


def main():
    card_db = load_card_db()
    known_decks = load_known_decks()
    leaderboard = load_leaderboard()

    records_37 = process_submission_data(55171237, card_db, known_decks, leaderboard)
    records_35 = process_submission_data(55171235, card_db, known_decks, leaderboard)

    print(f"Loaded {len(records_37)} records for 55171237 and {len(records_35)} records for 55171235.")

    stats_37 = analyze_records(records_37, "Submission 55171237")
    stats_35 = analyze_records(records_35, "Submission 55171235")
    stats_combined = analyze_records(records_37 + records_35, "Combined Submissions")

    md_report = generate_markdown_report(stats_37, stats_35, stats_combined)

    out_path = ROOT / "artifacts" / "ladder" / "deep_analysis_55171237_55171235.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md_report)

    json_path = ROOT / "artifacts" / "ladder" / "deep_analysis_55171237_55171235.json"
    clean_stats = {
        "submission_55171237": {k: v for k, v in stats_37.items() if k != "raw_records"},
        "submission_55171235": {k: v for k, v in stats_35.items() if k != "raw_records"},
        "combined": {k: v for k, v in stats_combined.items() if k != "raw_records"},
    }
    json_path.write_text(json.dumps(clean_stats, indent=2))

    print("=== ANALYSIS COMPLETE ===")
    print(f"Report written to: {out_path}")
    print(f"JSON data written to: {json_path}")
    print(f"Sub 55171237: {stats_37['wins']}W / {stats_37['losses']}L ({stats_37['win_rate']:.1%}) | Rating: {stats_37['first_score']:.1f} -> {stats_37['last_score']:.1f} (Net {stats_37['net_rating_delta']:+.1f})")
    print(f"Sub 55171235: {stats_35['wins']}W / {stats_35['losses']}L ({stats_35['win_rate']:.1%}) | Rating: {stats_35['first_score']:.1f} -> {stats_35['last_score']:.1f} (Net {stats_35['net_rating_delta']:+.1f})")
    print(f"Combined: {stats_combined['wins']}W / {stats_combined['losses']}L ({stats_combined['win_rate']:.1%})")


if __name__ == "__main__":
    main()

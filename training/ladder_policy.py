"""Conservative ladder rollout decisions from chronological snapshots."""

from __future__ import annotations

import time
from typing import Iterable


def assess_ladder(
    games: Iterable[dict],
    snapshots: Iterable[dict],
    *,
    now: float | None = None,
) -> dict:
    games = list(games)
    snapshots = sorted(snapshots, key=lambda row: float(row["timestamp"]))
    now = time.time() if now is None else now
    defects = sum(
        int(bool(game.get("crash") or game.get("invalid_action") or game.get("packaging_defect")))
        for game in games
    )
    wins = sum(float(game.get("outcome", 0)) > 0 for game in games)
    seat1 = [game for game in games if int(game.get("seat", -1)) == 1]
    seat1_rate = sum(float(game.get("outcome", 0)) > 0 for game in seat1) / len(seat1) if seat1 else None
    current = float(snapshots[-1]["rating"]) if snapshots else None
    max_observed = max((float(row["rating"]) for row in snapshots), default=None)
    count = len(games)
    chronological = sorted(games, key=lambda game: (float(game.get("created_unix", 0)), int(game.get("episode_id", 0))))
    first_loss = next(
        (index + 1 for index, game in enumerate(chronological) if float(game.get("outcome", 0)) <= 0),
        None,
    )
    checkpoints = {}
    for size in (10, 15, 20, 40):
        window_games = chronological[:size]
        window_wins = sum(float(game.get("outcome", 0)) > 0 for game in window_games)
        checkpoints[str(size)] = {
            "games": len(window_games),
            "wins": window_wins,
            "losses": len(window_games) - window_wins,
            "win_rate": window_wins / len(window_games) if window_games else None,
        }
    recent = chronological[-10:]
    recent_wins = sum(float(game.get("outcome", 0)) > 0 for game in recent)
    latest_game_unix = max((float(game.get("created_unix", 0)) for game in games), default=None)
    idle_hours = (now - latest_game_unix) / 3600 if latest_game_unix else None
    flags = []
    action = "observe"
    if defects:
        action = "replace_immediately"
        flags.append("runtime_or_packaging_defect")
    elif count >= 40 and current is not None and current < 850 and wins / count < 0.5:
        flags.append("40_game_low_rating_and_sub_50_win_rate")
    if count >= 40 and len(recent) == 10 and recent_wins <= 3:
        flags.append("recent_10_game_collapse")
        if action == "observe":
            action = "review"
    if 40 <= count < 75 and idle_hours is not None and idle_hours >= 6:
        flags.append("matchmaking_saturated_below_75")
        if action == "observe":
            action = "failed_convergence_review"
    if count >= 75:
        if current is not None and current < 900 and (max_observed or current) < 950:
            flags.append("75_game_progress_review")
        if seat1_rate is not None and len(seat1) >= 25 and seat1_rate < 0.40:
            flags.append("persistent_seat1_collapse")

    cutoff = now - 48 * 3600
    window = [row for row in snapshots if float(row["timestamp"]) >= cutoff]
    has_full_window = bool(window) and float(window[0]["timestamp"]) <= cutoff + 300
    continuously_above = has_full_window and all(float(row["rating"]) > 1000 for row in window)
    success = count >= 75 and max_observed is not None and max_observed >= 1025 and continuously_above
    return {
        "games": count,
        "wins": wins,
        "win_rate": wins / count if count else None,
        "seat_1_games": len(seat1),
        "seat_1_win_rate": seat1_rate,
        "current_rating": current,
        "max_observed_rating": max_observed,
        "rating_observation_count": len(snapshots),
        "first_loss_game": first_loss,
        "checkpoints": checkpoints,
        "recent_10": {
            "games": len(recent),
            "wins": recent_wins,
            "losses": len(recent) - recent_wins,
            "win_rate": recent_wins / len(recent) if recent else None,
        },
        "latest_game_unix": latest_game_unix,
        "matchmaking_idle_hours": idle_hours,
        "flags": flags,
        "action": action,
        "success": success,
        "success_requirements": {
            "at_least_75_games": count >= 75,
            "observed_1025_checkpoint": max_observed is not None and max_observed >= 1025,
            "continuous_48h_above_1000": continuously_above,
        },
    }

from training.ladder_policy import assess_ladder


def games(count, wins=None, seat=0):
    wins = count if wins is None else wins
    return [
        {"outcome": index < wins, "seat": seat, "created_unix": index + 1, "episode_id": index + 1}
        for index in range(count)
    ]


def test_ordinary_early_loss_does_not_trigger_replacement():
    result = assess_ladder(games(10, 4), [{"timestamp": 1, "rating": 700}], now=2)
    assert result["action"] == "observe"


def test_runtime_defect_replaces_immediately():
    rows = games(2)
    rows[1]["invalid_action"] = True
    assert assess_ladder(rows, [], now=2)["action"] == "replace_immediately"


def test_success_requires_checkpoint_and_full_48_hour_hold():
    now = 200_000
    snapshots = [
        {"timestamp": now - 48 * 3600, "rating": 1025},
        {"timestamp": now - 24 * 3600, "rating": 1001},
        {"timestamp": now, "rating": 1004},
    ]
    assert assess_ladder(games(75), snapshots, now=now)["success"] is True
    snapshots[1]["rating"] = 999
    assert assess_ladder(games(75), snapshots, now=now)["success"] is False


def test_sparse_rating_max_is_labeled_observed_not_peak():
    result = assess_ladder(games(2), [{"timestamp": 1, "rating": 907.5}], now=2)
    assert result["max_observed_rating"] == 907.5
    assert "peak_rating" not in result


def test_recent_collapse_and_saturation_are_reported_before_75_games():
    rows = games(50, 28)
    # Make the last ten 2-8 while preserving 28 total wins.
    for index, row in enumerate(rows):
        row["outcome"] = index < 26 or index in (40, 41)
        row["created_unix"] = index + 1
    result = assess_ladder(rows, [{"timestamp": 1, "rating": 860}], now=50 + 6 * 3600 + 1)
    assert "recent_10_game_collapse" in result["flags"]
    assert "matchmaking_saturated_below_75" in result["flags"]
    assert result["success"] is False

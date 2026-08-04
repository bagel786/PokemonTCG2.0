import math

from training.collect_selfplay import assign_terminal_gae


def test_terminal_gae_matches_hand_calculation():
    trajectory = [{"old_value": 0.0}, {"old_value": 0.0}]
    assign_terminal_gae(trajectory, 1.0, 0.95)
    assert math.isclose(trajectory[1]["advantage"], 0.5)
    assert math.isclose(trajectory[0]["advantage"], 0.475)
    assert trajectory[0]["return"] == trajectory[1]["return"] == 1.0


def test_terminal_gae_discounts_across_turn_boundaries():
    trajectory = [{"old_value": 0.0, "turn": 1}, {"old_value": 0.0, "turn": 2}]
    assign_terminal_gae(trajectory, 1.0, 0.95)
    assert math.isclose(trajectory[1]["advantage"], 0.5)
    assert math.isclose(trajectory[0]["advantage"], 0.46525)

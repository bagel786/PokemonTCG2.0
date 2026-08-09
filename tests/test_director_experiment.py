import pytest

from training.director_experiment import MacroTrialRow, analyze


def row(game_id, arm, win, order="first", errors=0):
    return MacroTrialRow(
        game_id=game_id, arm=arm, propensity=0.5, selected_turn=3,
        actual_order=order, opponent_lineage="owned", opponent_sha256="A" * 64,
        worker="worker", shard=game_id % 8, complied=arm == "treatment",
        routed=True, terminal_outcome=win, policy_errors=errors,
        fallback_reason=None,
    )


def test_macro_trial_is_fail_closed_before_kill_screen():
    rows = [row(i, "treatment" if i % 2 else "control", i % 3 == 0, "first" if i % 4 < 2 else "second") for i in range(200)]
    result = analyze(rows)
    assert result["stage"] == "incomplete"
    assert not result["passed"]


def test_treatment_errors_fail_even_large_uplift():
    rows = []
    for i in range(4_000):
        arm = "treatment" if i % 2 else "control"
        order = "first" if i % 4 < 2 else "second"
        win = arm == "treatment" or i % 5 == 0
        rows.append(row(i, arm, win, order, errors=1 if i == 1 else 0))
    result = analyze(rows)
    assert result["overall"]["uplift"] > 0.03
    assert not result["passed"]


def test_missing_order_arm_aborts_analysis():
    rows = [row(i, "treatment" if i % 2 else "control", 1, "first") for i in range(20)]
    with pytest.raises(ValueError, match="order=second"):
        analyze(rows)

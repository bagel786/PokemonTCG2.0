from training.order_promotion import confirmation_gate, direct_gate, fast_screen, select_checkpoints


def cell(wins, games=1000, order="first", errors=0):
    return {
        "wins": wins, "games": games, "win_rate": wins / games,
        "actual_order": order, "hero_policy_errors": errors,
        "opponent_policy_errors": 0, "actual_order_accounting_complete": True,
    }


def test_fast_screen_rejects_any_three_point_regression_and_selects_strongest_second():
    control = {"a": cell(500), "b": cell(500)}
    good = fast_screen({"a": cell(550), "b": cell(540)}, control)
    weak = fast_screen({"a": cell(540), "b": cell(469)}, control)
    assert good["passed"]
    assert not weak["passed"]
    selected = select_checkpoints(good, {"second_a": good, "second_b": weak})
    assert selected["policy_first"] == "trained"
    assert selected["policy_second"] == "second_a"


def test_fast_screen_accepts_exact_three_point_boundary_despite_float_roundoff():
    control = {"a": cell(500, games=1000)}
    exact_boundary = fast_screen({"a": cell(470, games=1000)}, control)
    over_boundary = fast_screen({"a": cell(469, games=1000)}, control)
    assert exact_boundary["opponents"]["a"]["uplift"] < -0.03
    assert exact_boundary["non_regression_passed"]
    assert not exact_boundary["passed"]
    assert not over_boundary["non_regression_passed"]


def test_fast_screen_requires_credible_positive_aggregate_strength():
    control = {name: cell(500) for name in ("a", "b", "c", "d", "e")}
    noisy = fast_screen({name: cell(508) for name in control}, control)
    strong = fast_screen({name: cell(525) for name in control}, control)
    assert noisy["non_regression_passed"]
    assert not noisy["strength_evidence_passed"]
    assert not noisy["passed"]
    assert strong["passed"]


def test_direct_gate_can_short_circuit_expensive_confirmation():
    assert direct_gate(cell(2200, games=4000))["passed"]
    assert not direct_gate(cell(1970, games=4000))["passed"]


def test_confirmation_is_fail_closed_on_validation_and_safety_alarm():
    heldout = {}
    for opponent in ("replay_refresh", "v2_2", "alakazam_2_7"):
        heldout[opponent] = {}
        for order in ("first", "second"):
            heldout[opponent][order] = {
                "candidate": cell(550, order=order), "control": cell(500, order=order),
            }
    payload = {
        "heldout": heldout,
        "direct": cell(2200, games=4000),
        "safety": {name: {"candidate": cell(520), "control": cell(500)} for name in
                   ("lucario", "crustle", "ogerpon", "bellibolt", "starmie_froslass")},
        "trained_first": True,
        "sterile_ubuntu": True, "deterministic_replay": True,
        "archive_hash_verified": True, "latency_passed": True, "kaggle_self_play_passed": True,
    }
    assert confirmation_gate(payload)["passed"]
    payload["latency_passed"] = False
    assert not confirmation_gate(payload)["passed"]
    payload["latency_passed"] = True
    payload["safety"]["lucario"]["candidate"] = cell(440)
    assert not confirmation_gate(payload)["passed"]

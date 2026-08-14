from training.evaluate_a2_err_offline import decide_gate_a, decide_gate_b, gate_a_subsets


def metric(delta, top3_delta=0.0):
    return {"single_semantic_decisions": 100, "top1_delta_pp": delta, "top3_delta_pp": top3_delta}


def test_gate_a_uses_frozen_thresholds_exactly():
    result = decide_gate_a({
        "strict_loss": metric(3.0),
        "strict_win": metric(1.0),
        "strict_first": metric(-0.5),
        "strict_second": metric(-0.5),
        "strict_all": metric(0.0, -0.25),
    })
    assert result["status"] == "PASS"
    failing = decide_gate_a({
        "strict_loss": metric(2.999),
        "strict_win": metric(1.0),
        "strict_first": metric(-0.5),
        "strict_second": metric(-0.5),
        "strict_all": metric(0.0, -0.25),
    })
    assert failing["status"] == "FAIL"


def test_gate_b_uses_frozen_thresholds_exactly():
    overall = {
        "top1_delta_pp": -0.5,
        "top3_delta_pp": -0.1,
        "semantic_greedy_change_rate": 0.03,
        "mean_per_state_kl": 0.02,
    }
    integrity = {
        "count_output_mismatches": 0,
        "value_output_mismatches": 0,
        "non_finite_values": 0,
        "policy_runtime_errors": 0,
        "frozen_array_audit": {"all_frozen_arrays_byte_identical": True},
    }
    assert decide_gate_b(overall, integrity)["status"] == "PASS"
    overall["semantic_greedy_change_rate"] = 0.030001
    assert decide_gate_b(overall, integrity)["status"] == "FAIL"


def test_strict_holdout_is_independent_of_top70_teacher_filter():
    row = {
        "teacher_source_date_rank": 143,
        "teacher_qualified_top70": False,
        "strict_both_ge_1050": True,
        "outcome": "loss",
        "actual_order": "second",
    }
    assert gate_a_subsets(row) == ["strict_all", "strict_loss", "strict_second"]

import numpy as np

from scripts.build_a2_err_corpus import (
    ORDER_OUTCOME_BUCKETS,
    action_category,
    balance_corrections,
    infer_daily_strength,
    input_fingerprint,
    episode_outcomes,
    rank_band,
)
from ptcg_ai.features import DecisionFeatures


def feature(option_type=7, context=0):
    return DecisionFeatures.from_json({
        "feature_version": 2,
        "global": [],
        "tokens": [],
        "options": [{
            "option_type": option_type,
            "context": context,
            "source_card": 0,
            "target_card": 0,
            "attack_id": 0,
            "area": 0,
            "in_play_area": 0,
            "numeric": [],
        }],
    })


def test_rank_bands_are_frozen():
    assert [rank_band(value) for value in (1, 20, 21, 40, 41, 70, 71, None)] == [
        "1-20", "1-20", "21-40", "21-40", "41-70", "41-70", "71+", "unranked"
    ]


def test_action_categories_include_switch_before_generic_target():
    assert action_category(feature(7, 0), 0) == "PLAY"
    assert action_category(feature(3, 3), 0) == "SWITCH / promotion"
    assert action_category(feature(3, 13), 0) == "target selection"


def test_fingerprint_is_order_stable():
    assert input_fingerprint({"b": 2, "a": 1}) == input_fingerprint({"a": 1, "b": 2})


def test_strength_inference_uses_anchor_to_orient_unordered_scores():
    matches = [
        {"teams": ["strong", "weak"], "low_score": 900.0, "high_score": 1200.0},
        {"teams": ["strong", "middle"], "low_score": 1000.0, "high_score": 1210.0},
        {"teams": ["middle", "weak"], "low_score": 890.0, "high_score": 1010.0},
    ]
    result = infer_daily_strength(matches, {"strong": 1220.0, "middle": 1010.0, "weak": 880.0})
    assert result["strong"]["rank"] == 1
    assert result["weak"]["rank"] == 3


def test_balancing_hits_four_strata_and_caps_without_duplication():
    rows = []
    dates = ["2026-08-08", "2026-08-09", "2026-08-10", "2026-08-11"]
    pilots = [f"pilot-{index}" for index in range(8)]
    for bucket_index, bucket in enumerate(ORDER_OUTCOME_BUCKETS):
        outcome, order = bucket.split("-")
        for index in range(20 + bucket_index):
            rows.append({
                "source_date": dates[index % len(dates)],
                "episode_id": f"{bucket}-{index}",
                "seat": index % 2,
                "teacher_identity": pilots[index % len(pilots)],
                "outcome": outcome,
                "actual_order": order,
                "base_rank_weight": (1.0, 0.75, 0.5)[index % 3],
            })
    result = balance_corrections(rows)
    assert result["status"] == "balanced"
    assert all(np.isclose(value, 0.25) for value in result["bucket_fraction"].values())
    assert result["max_pilot_fraction"] <= 0.15 + 1e-9
    assert result["max_date_fraction"] <= 0.30 + 1e-9
    assert all(row["final_training_weight"] > 0 for row in rows)


def test_draws_are_not_complete_win_loss_games():
    assert episode_outcomes({"rewards": [0, 0]}) is None
    assert episode_outcomes({"rewards": [1, -1]}) == (1.0, 0.0)

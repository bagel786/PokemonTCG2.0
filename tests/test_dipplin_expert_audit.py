from __future__ import annotations

from collections import Counter

from ptcg_ai.dipplin.cards import APPLIN_DRAGON, GROOKEY, VOLBEAT
from scripts.build_dipplin_expert_fresh import _assign_splits
from scripts.dipplin_eval_common import canonical_deck_hash, opening_bucket
from scripts.evaluate_dipplin_prize_regret import summarize


def test_fresh_split_is_capacity_exact_and_balances_major_marginals() -> None:
    rows = [
        {
            "episode_id": 90_000_000 + index,
            "actual_order": "first" if index % 2 else "second",
            "opening_active": ("grookey_active", "applin_92_active", "other")[index % 3],
            "opponent_archetype": ("grimmsnarl_marnie", "alakazam_dudunsparce")[index % 2],
            "expert_result": "win" if index % 5 else "loss",
            "list_relation": "exact_60" if index % 7 == 0 else "similar_thwackey_dipplin",
        }
        for index in range(120)
    ]

    _assign_splits(rows)

    assert Counter(row["split"] for row in rows) == {"DEV": 72, "VALIDATION": 30, "SEALED": 18}
    for split, expected_first in (("DEV", 36), ("VALIDATION", 15), ("SEALED", 9)):
        selected = [row for row in rows if row["split"] == split]
        assert abs(sum(row["actual_order"] == "first" for row in selected) - expected_first) <= 2


def test_public_helpers_are_deterministic() -> None:
    assert canonical_deck_hash([3, 1, 2, 2]) == canonical_deck_hash([2, 3, 2, 1])
    assert opening_bucket(GROOKEY, False) == "grookey_active"
    assert opening_bucket(VOLBEAT, True) == "volbeat_active_quick_sign_legal"
    assert opening_bucket(APPLIN_DRAGON, False) == "applin_42_active"


def test_prize_regret_summary_uses_episode_as_unit() -> None:
    rows = [
        {"episode_id": 1, "certifiable": True, "prize_regret": 1, "likely_cause": "MISSED_MODIFIER"},
        {"episode_id": 1, "certifiable": True, "prize_regret": 1, "likely_cause": "MISSED_MODIFIER"},
        {"episode_id": 2, "certifiable": True, "prize_regret": 0, "likely_cause": "OTHER"},
        {"episode_id": 3, "certifiable": False, "prize_regret": None, "likely_cause": "OTHER"},
    ]

    result = summarize(rows)

    assert result["episode_count"] == 3
    assert result["positive_regret_episode_count"] == 1
    assert result["positive_regret_rows"] == 2
    assert result["cause_counts"] == {"MISSED_MODIFIER": 2}

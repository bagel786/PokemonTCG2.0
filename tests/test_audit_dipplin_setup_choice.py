from scripts.audit_dipplin_setup_choice import summarize_setup_choices


def test_setup_choice_summary_bounds_the_elective_grookey_scope():
    rows = [
        {
            "selected_active_id": 89,
            "candidate_basic_ids": (88, 89),
            "known_quick_sign_energy_path": False,
        },
        {
            "selected_active_id": 89,
            "candidate_basic_ids": (89,),
            "known_quick_sign_energy_path": True,
        },
        {
            "selected_active_id": 88,
            "candidate_basic_ids": (88, 89),
            "known_quick_sign_energy_path": True,
        },
    ]
    result = summarize_setup_choices(rows)
    assert result["games"] == 3
    assert result["selected_active_counts"] == {"88": 1, "89": 2}
    assert result["grookey_selected"] == 2
    assert result["grookey_with_selectable_volbeat"] == 1
    assert result["grookey_with_selectable_volbeat_rate_all_openings"] == 1 / 3
    assert result["grookey_with_selectable_volbeat_rate_within_grookey"] == 1 / 2
    assert result["selected_choice_scope"]["89"] == {
        "selected": 2,
        "only_distinct_candidate": 1,
        "with_any_alternative": 1,
        "with_known_quick_sign_energy_path": 1,
        "alternative_basic_presence": {"88": 1},
    }

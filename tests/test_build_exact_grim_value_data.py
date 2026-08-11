from scripts.build_exact_grim_value_data import split_for_date


def test_value_date_split_is_strictly_temporal():
    assert split_for_date("2026-08-07", "2026-08-08", "2026-08-09") == "train"
    assert split_for_date("2026-08-08", "2026-08-08", "2026-08-09") == "validation"
    assert split_for_date("2026-08-09", "2026-08-08", "2026-08-09") == "holdout"

from paper.scripts.audit_seed_namespace import engine_seed, schedule, summarize


def test_engine_seed_matches_uint32_narrowing():
    assert engine_seed(0) == 0
    assert engine_seed(2**32 - 1) == 2**32 - 1
    assert engine_seed(2**32) == 0
    assert engine_seed(202608230000) == 744767088


def test_summary_distinguishes_exact_repeats_from_namespace_collisions():
    clean = summarize([7, 8, 9])
    assert clean["passed_no_collision"] is True
    assert clean["conversion_changed"] == 0

    collision = summarize([7, 7 + 2**32])
    assert collision["passed_no_collision"] is False
    assert collision["collision_groups"] == {"7": [7, 7 + 2**32]}


def test_prospective_schedule_is_disjoint_between_orders():
    values = schedule(2026082700, 200)
    assert len(values) == 400
    assert len(set(values)) == 400
    assert values[0] == 2026082700
    assert values[199] == 2026082899
    assert values[200] == 2027082700

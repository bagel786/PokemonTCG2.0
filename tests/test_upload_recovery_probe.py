import datetime as dt

import pytest

from scripts.upload_recovery_probe import planned_upload_window_open


def test_upload_window_uses_fixed_august_cdt_boundary_without_tzdata():
    utc = dt.timezone.utc
    assert planned_upload_window_open(dt.datetime(2026, 8, 12, 4, 59, tzinfo=utc))
    assert not planned_upload_window_open(dt.datetime(2026, 8, 12, 5, 0, tzinfo=utc))
    with pytest.raises(ValueError):
        planned_upload_window_open(dt.datetime(2026, 8, 11, 23, 59))

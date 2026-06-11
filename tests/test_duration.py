from dfyb.breaks.duration import to_seconds


def test_seconds_pass_through():
    assert to_seconds(45, "sec") == 45


def test_minutes_to_seconds():
    assert to_seconds(25, "min") == 25 * 60


def test_hours_to_seconds():
    assert to_seconds(2, "hour") == 2 * 3600


def test_unknown_unit_matches_legacy_hour_behavior():
    # Legacy code's final `else` branch multiplied by 3600 for any non-sec/min unit.
    assert to_seconds(1, "fortnight") == 3600

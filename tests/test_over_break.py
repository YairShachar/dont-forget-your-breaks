from dfyb.insights.over_break import format_over_time


def test_zero():
    assert format_over_time(0) == "+00:00"


def test_one_second():
    assert format_over_time(1) == "+00:01"


def test_under_a_minute():
    assert format_over_time(59) == "+00:59"


def test_exactly_a_minute():
    assert format_over_time(60) == "+01:00"


def test_minutes_and_seconds():
    assert format_over_time(134) == "+02:14"


def test_negative_clamps_to_zero():
    assert format_over_time(-5) == "+00:00"

from dfyb.snooze import (
    snooze_delay_ms, format_snooze_short, format_snooze_long, custom_snooze_seconds)

MAX = 24 * 60 * 60


def test_delay_ms_five_minutes():
    assert snooze_delay_ms(300) == 300000


def test_delay_ms_thirty_seconds():
    assert snooze_delay_ms(30) == 30000


def test_delay_ms_is_int():
    result = snooze_delay_ms(1.5)
    assert result == 1500
    assert isinstance(result, int)


def test_short_seconds():
    assert format_snooze_short(30) == "30s"


def test_short_whole_minute():
    assert format_snooze_short(60) == "1m"


def test_short_minutes_and_seconds():
    assert format_snooze_short(90) == "1m30s"


def test_short_five_minutes():
    assert format_snooze_short(300) == "5m"


def test_long_seconds():
    assert format_snooze_long(30) == "30 sec"


def test_long_whole_minute():
    assert format_snooze_long(60) == "1 min"


def test_long_minutes_and_seconds():
    assert format_snooze_long(90) == "1 min 30 sec"


def test_long_five_minutes():
    assert format_snooze_long(300) == "5 min"


def test_custom_seconds_unit():
    assert custom_snooze_seconds("45", "sec", MAX) == 45


def test_custom_minutes_unit():
    assert custom_snooze_seconds("2", "min", MAX) == 120


def test_custom_zero_is_none():
    assert custom_snooze_seconds("0", "sec", MAX) is None


def test_custom_negative_is_none():
    assert custom_snooze_seconds("-3", "sec", MAX) is None


def test_custom_non_numeric_is_none():
    assert custom_snooze_seconds("abc", "sec", MAX) is None


def test_custom_empty_is_none():
    assert custom_snooze_seconds("", "sec", MAX) is None


def test_custom_over_cap_is_none():
    assert custom_snooze_seconds("99999999", "min", 86400) is None

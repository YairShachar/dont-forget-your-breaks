from dfyb.snooze import (
    snooze_delay_ms, format_snooze_short, format_snooze_long, custom_snooze_seconds,
    should_hold_snooze)

MAX = 24 * 60 * 60


# --- should_hold_snooze: running/stopped is deliberately NOT a factor ---

def test_hold_when_paused():
    assert should_hold_snooze(True, False) is True


def test_hold_when_context_defers():
    assert should_hold_snooze(False, True) is True


def test_fire_when_active_and_clear():
    # not paused, not deferred -> fire (regardless of Start/Stop, which isn't an input)
    assert should_hold_snooze(False, False) is False


def test_hold_when_both():
    assert should_hold_snooze(True, True) is True


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


from dfyb.snooze import snooze_remaining


def test_remaining_counts_down():
    assert snooze_remaining(1000, 970) == 30


def test_remaining_zero_at_fire():
    assert snooze_remaining(1000, 1000) == 0


def test_remaining_clamps_past_due():
    assert snooze_remaining(1000, 1010) == 0


def test_remaining_ten_seconds():
    assert snooze_remaining(1010, 1000) == 10


# --- next_clear_streak: debounce a snooze return over transient dropouts (#84) ---
from dfyb.snooze import next_clear_streak


def test_clear_streak_defer_resets_and_holds():
    # a DEFER (context_defers=True) always resets the streak and holds
    assert next_clear_streak(1, True, 2) == (0, False)
    assert next_clear_streak(0, True, 2) == (0, False)


def test_clear_streak_needs_consecutive_clears():
    # one clear poll is not enough when 2 are required
    assert next_clear_streak(0, False, 2) == (1, False)
    # the second consecutive clear returns the break
    assert next_clear_streak(1, False, 2) == (2, True)


def test_clear_streak_bridges_a_single_dropout():
    # clear, then a one-poll DEFER (mic blip) resets, so it does NOT return early
    streak, ret = next_clear_streak(0, False, 2)   # clear
    assert (streak, ret) == (1, False)
    streak, ret = next_clear_streak(streak, True, 2)  # dropout -> reset
    assert (streak, ret) == (0, False)
    streak, ret = next_clear_streak(streak, False, 2)  # clear again
    assert (streak, ret) == (1, False)
    streak, ret = next_clear_streak(streak, False, 2)  # second consecutive clear
    assert (streak, ret) == (2, True)


def test_clear_streak_required_one_returns_immediately():
    # required=1 means no debounce (legacy behaviour)
    assert next_clear_streak(0, False, 1) == (1, True)

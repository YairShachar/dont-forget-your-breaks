from dfyb.snooze import snooze_delay_ms


def test_five_minutes():
    assert snooze_delay_ms(5) == 300000


def test_ten_minutes():
    assert snooze_delay_ms(10) == 600000


def test_one_minute():
    assert snooze_delay_ms(1) == 60000


def test_fractional_is_int():
    result = snooze_delay_ms(0.5)
    assert result == 30000
    assert isinstance(result, int)

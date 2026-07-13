"""Snooze timing helpers. Pure (no Tk, no I/O) — unit-tested."""

MS_PER_MINUTE = 60 * 1000


def snooze_delay_ms(minutes):
    """Snooze duration in whole milliseconds for Tk's `after` (which needs an int).

    int() also guards the historic float-crash (0.5 -> 30000, not 30000.0).
    """
    return int(minutes * MS_PER_MINUTE)

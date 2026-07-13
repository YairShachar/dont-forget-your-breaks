"""Snooze timing + formatting helpers. Pure (no Tk, no I/O) — unit-tested."""

MS_PER_SECOND = 1000
SECONDS_PER_MINUTE = 60


def snooze_delay_ms(seconds):
    """Snooze duration in whole milliseconds for Tk's `after` (needs an int)."""
    return int(seconds * MS_PER_SECOND)


def format_snooze_short(seconds):
    """Compact label for the Snooze button: 45s / 1m / 5m / 1m30s."""
    if seconds < SECONDS_PER_MINUTE:
        return f"{seconds}s"
    minutes, rem = divmod(seconds, SECONDS_PER_MINUTE)
    return f"{minutes}m" if rem == 0 else f"{minutes}m{rem}s"


def format_snooze_long(seconds):
    """Readable label for the ▾ menu: 30 sec / 1 min / 2 min / 1 min 30 sec."""
    if seconds < SECONDS_PER_MINUTE:
        return f"{seconds} sec"
    minutes, rem = divmod(seconds, SECONDS_PER_MINUTE)
    return f"{minutes} min" if rem == 0 else f"{minutes} min {rem} sec"


def custom_snooze_seconds(raw_text, unit, max_seconds):
    """Parse the custom dialog (a number + 'sec'/'min') to seconds, or None if
    not a positive integer within `max_seconds`."""
    try:
        value = int(str(raw_text).strip())
    except (ValueError, TypeError):
        return None
    if value <= 0:
        return None
    seconds = value if unit == "sec" else value * SECONDS_PER_MINUTE
    if seconds > max_seconds:
        return None
    return seconds

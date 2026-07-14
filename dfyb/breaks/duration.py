"""Pure time-unit conversion (no Tk)."""


def to_seconds(value, unit):
    """Convert an integer value + unit ('sec'/'min'/'hour') to seconds.

    Any unit other than 'sec'/'min' is treated as hours, preserving the
    original behavior in launch.py.
    """
    if unit == "sec":
        return value
    if unit == "min":
        return value * 60
    return value * 3600


def humanize_seconds(seconds):
    """Compact label for a duration, picking the largest whole unit.

    e.g. 20 -> '20 sec', 1500 -> '25 min', 3600 -> '1 hr'.
    """
    if seconds and seconds % 3600 == 0:
        return f"{seconds // 3600} hr"
    if seconds and seconds % 60 == 0:
        return f"{seconds // 60} min"
    return f"{seconds} sec"

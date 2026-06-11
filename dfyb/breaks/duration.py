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

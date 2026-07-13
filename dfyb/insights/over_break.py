"""Format the 'over your break' count-up. Pure (no Tk, no I/O) — unit-tested."""


def format_over_time(seconds):
    """Seconds past the break's duration as a signed MM:SS string.

    Always MM:SS (unlike the popup's mixed Xs / MM:SS countdown), e.g.
    1 -> '+00:01', 134 -> '+02:14'. Negative inputs are clamped to 0.
    """
    seconds = max(0, seconds)
    m, s = divmod(seconds, 60)
    return f"+{m:02d}:{s:02d}"

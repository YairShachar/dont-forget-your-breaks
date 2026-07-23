"""Pure logic for the one-time 'nudge the next break' reschedule. No Tk, no I/O."""

RESCHEDULE_STEP_FRACTION = 0.25
RESCHEDULE_MAX_FACTOR = 2.0


def reschedule_step(interval_seconds, fraction=RESCHEDULE_STEP_FRACTION):
    """Nudge step for a break — a fraction of its interval, at least 1 second."""
    return max(1, int(interval_seconds * fraction))


def reschedule_bounds(interval_seconds, max_factor=RESCHEDULE_MAX_FACTOR):
    """(floor, ceiling) for the rescheduled remaining: one step .. max_factor×interval."""
    step = reschedule_step(interval_seconds)
    return step, int(interval_seconds * max_factor)


def nudged_remaining(current, delta, floor, ceiling):
    """Clamp current+delta into [floor, ceiling]."""
    return max(floor, min(ceiling, current + delta))

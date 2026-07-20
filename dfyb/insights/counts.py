"""Snooze insight counts derived from the event log. Pure — unit-tested."""
from dfyb.activity.event_log import (
    BREAK_SNOOZED, BREAK_TAKEN, NATURAL_BREAK, SESSION_STARTED)

SECONDS_PER_MINUTE = 60


def _cycle_start_index(events, break_name):
    """Index where this break's current pending cycle begins — after the latest
    of: a NATURAL_BREAK, a SESSION_STARTED (a fresh Start resets every break), or
    a BREAK_TAKEN for this break."""
    start = 0
    for i, e in enumerate(events):
        etype = e["type"]
        if etype == NATURAL_BREAK or etype == SESSION_STARTED:
            start = i + 1
        elif etype == BREAK_TAKEN and e["data"].get("name") == break_name:
            start = i + 1
    return start


def snooze_count_since_taken(events, break_name):
    """How many times `break_name` was snoozed in its current cycle."""
    start = _cycle_start_index(events, break_name)
    return sum(1 for e in events[start:]
               if e["type"] == BREAK_SNOOZED and e["data"].get("name") == break_name)


def first_snooze_seconds_ago(events, break_name, now):
    """Seconds since the first snooze of `break_name` in its current cycle, or
    None if it hasn't been snoozed this cycle."""
    start = _cycle_start_index(events, break_name)
    for e in events[start:]:
        if e["type"] == BREAK_SNOOZED and e["data"].get("name") == break_name:
            return now - e["ts"]
    return None


def _format_minutes_ago(seconds):
    minutes = int(round(seconds / SECONDS_PER_MINUTE))
    if minutes < 1:
        return "less than a minute ago"
    return f"{minutes} min ago"


def snooze_summary_label(count, seconds_ago):
    """The popup line for the snooze count, or None when there's nothing to show."""
    if count <= 0:
        return None
    times = "once" if count == 1 else f"{count}×"
    if seconds_ago is None:
        return f"Snoozed {times} already"
    return f"Snoozed {times} already (originally due {_format_minutes_ago(seconds_ago)})"

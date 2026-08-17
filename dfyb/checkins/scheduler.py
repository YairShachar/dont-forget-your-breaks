"""Pure scheduling for break-coupled check-ins: which "with a break" question (if any)
is due to ask when a break finishes. Deterministic given inputs.

The break itself is the safe, non-work moment, so there is NO deferral / active-window /
probability gate here — only the per-question cadence interval and a global spacing floor.
"""
from dfyb.checkins.model import cadence_interval_seconds, TRIGGER_BREAK


def _overdue(question, now, last_prompted, active_window_seconds):
    interval = cadence_interval_seconds(question.cadence, active_window_seconds)
    return (now - last_prompted.get(question.id, 0.0)) - interval


def due_break_check_in(questions, now, last_prompted, last_prompt_ts,
                       active_window_seconds, min_gap, answered_today=()):
    """Return the break-coupled check-in to ask now (a break just finished), or None.
    Only enabled `trigger == "break"` questions whose cadence interval has elapsed are
    eligible; a `once_per_day` question already in `answered_today` (a set of question ids
    answered today) is skipped; never within `min_gap` of the last check-in. Most overdue wins."""
    if now - last_prompt_ts < min_gap:
        return None
    answered_today = set(answered_today)
    eligible = [q for q in questions if q.enabled and q.trigger == TRIGGER_BREAK
                and not (q.once_per_day and q.id in answered_today)
                and _overdue(q, now, last_prompted, active_window_seconds) >= 0]
    if not eligible:
        return None
    return max(eligible, key=lambda q: _overdue(q, now, last_prompted, active_window_seconds))

"""Pure scheduling: decide which check-in (if any) may surface right now.

Deterministic given inputs + an injected rng, so it is fully unit-testable. The
caller supplies the smoothed deferral flag and the active-window flag; this module
never reads sensors or the clock itself.
"""
from dfyb.checkins.model import cadence_interval_seconds

# Once a question is eligible, surface it only with this probability per eligible
# tick, so prompts feel spread out / intermittent rather than firing the instant
# they come due. Tunable.
CHECK_IN_SURFACE_PROB = 0.15


def _overdue(question, now, last_prompted, active_window_seconds):
    interval = cadence_interval_seconds(question.cadence, active_window_seconds)
    return (now - last_prompted.get(question.id, 0.0)) - interval


def due_question(questions, now, last_prompted, last_prompt_ts, active_window_seconds,
                 in_active_window, deferring, min_gap, rng):
    """Return the check-in to surface now, or None. Guardrails: never while deferring
    or outside active hours; never within `min_gap` of the last prompt; a question is
    eligible only once its cadence interval has elapsed; among eligible ones the most
    overdue wins, surfaced with CHECK_IN_SURFACE_PROB so it feels intermittent."""
    if deferring or not in_active_window:
        return None
    if now - last_prompt_ts < min_gap:
        return None
    eligible = [q for q in questions if q.enabled
                and _overdue(q, now, last_prompted, active_window_seconds) >= 0]
    if not eligible:
        return None
    if rng.random() >= CHECK_IN_SURFACE_PROB:
        return None
    return max(eligible, key=lambda q: _overdue(q, now, last_prompted, active_window_seconds))

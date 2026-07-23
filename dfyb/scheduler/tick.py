"""Per-tick composition: run the engine and decide which events to log.

Pure (no Tk, no I/O). The timer loop calls `advance` once per tick and applies
the returned new_remaining / fire_index / events.
"""
from dfyb.activity.event_log import BREAK_DEFERRED, NATURAL_BREAK
from dfyb.scheduler.engine import (step, AWAY_IDLE_THRESHOLD_SECONDS,
                                   NATURAL_BREAK_IDLE_THRESHOLD_SECONDS)

# Episode markers used to dedup sustained idle/defer logging.
IDLE_EPISODE = "idle"
DEFERRED_EPISODE = "deferred"


def events_for_tick(result, ctx, episode):
    """Given a StepResult, the Context, and the previous episode marker, return
    (events_to_log, new_episode). Logs a sustained idle/defer only once.

    events_to_log is a list of (event_type, data_dict) tuples.
    """
    if result.natural_break:
        if episode != IDLE_EPISODE:
            return [(NATURAL_BREAK, {"idle_seconds": ctx.idle_seconds})], IDLE_EPISODE
        return [], IDLE_EPISODE
    if result.defer_reason is not None:
        if episode != DEFERRED_EPISODE:
            return [(BREAK_DEFERRED, {"reason": result.defer_reason})], DEFERRED_EPISODE
        return [], DEFERRED_EPISODE
    # fire, or nothing due -> episode ends; BREAK_TAKEN is logged on popup close.
    return [], None


def advance(states, ctx, episode, pause_threshold=0,
            away_threshold=AWAY_IDLE_THRESHOLD_SECONDS,
            natural_threshold=NATURAL_BREAK_IDLE_THRESHOLD_SECONDS):
    """Run one tick. Returns (new_remaining, fire_index, events, new_episode)."""
    result = step(states, ctx, natural_threshold=natural_threshold,
                  away_threshold=away_threshold, pause_threshold=pause_threshold)
    events, new_episode = events_for_tick(result, ctx, episode)
    return result.new_remaining, result.fire_index, events, new_episode

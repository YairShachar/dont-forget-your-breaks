"""Per-tick composition: run the engine and decide which events to log.

Pure (no Tk, no I/O). The timer loop calls `advance` once per tick and applies
the returned new_remaining / fire_index / events.
"""
from dataclasses import dataclass, field

from dfyb.activity.event_log import BREAK_DEFERRED, NATURAL_BREAK
from dfyb.scheduler.engine import (step, AWAY_IDLE_THRESHOLD_SECONDS,
                                   NATURAL_BREAK_IDLE_THRESHOLD_SECONDS)

# Episode markers used to dedup sustained idle/defer logging.
IDLE_EPISODE = "idle"
DEFERRED_EPISODE = "deferred"


@dataclass(frozen=True)
class TickOutcome:
    """Everything one tick produced, for the caller to apply.

    `defer_reason`/`defer_app` are THIS tick's evaluation, surfaced even when
    no event was logged for them: `BREAK_DEFERRED` is deduped to once per
    sustained episode, but the UI must re-derive the reason it displays (and
    the app it offers to excuse) every single tick, or the two drift apart
    inside one episode.
    """
    new_remaining: list[int]
    fire_index: int | None
    events: list = field(default_factory=list)
    episode: str | None = None
    defer_reason: str | None = None
    defer_app: dict | None = None


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
            data = {"reason": result.defer_reason}
            if result.defer_app:
                # Attribute the push-back so the dashboard can total deferred time
                # per app ("Zoom pushed back 47 min of breaks this week").
                data["app"] = result.defer_app.get("id")
                data["app_name"] = result.defer_app.get("name")
                data["holder_count"] = result.defer_app.get("count")
            return [(BREAK_DEFERRED, data)], DEFERRED_EPISODE
        return [], DEFERRED_EPISODE
    # fire, or nothing due -> episode ends; BREAK_TAKEN is logged on popup close.
    return [], None


def track_due_since(due_since, names, prev_remaining, now, due_threshold=1):
    """Per-break 'first became due' timestamps, for measuring how long a break was
    held before it fired (#85). A break is due when its PRE-tick remaining is
    <= due_threshold (it hits 0 this tick, or is already held at 0). `setdefault`
    keeps the FIRST due tick's timestamp; a break above the threshold (reset /
    rescheduled / counting down) is cleared. Pure — returns a NEW dict."""
    updated = dict(due_since)
    for name, prev in zip(names, prev_remaining):
        if prev <= due_threshold:
            updated.setdefault(name, now)
        else:
            updated.pop(name, None)
    return updated


def deferral_at_fire(due_since, name, now):
    """(scheduled_ts, deferred_seconds) for a firing break: `scheduled_ts` is when
    it first became due, `deferred_seconds` how long it was then held (never
    negative). Falls back to `now` (deferred 0) if it was never recorded."""
    scheduled_ts = due_since.get(name, now)
    return scheduled_ts, max(0.0, now - scheduled_ts)


def apply_snooze_freeze(new_remaining, fire_index, prev_remaining,
                        names, pending_names):
    """Freeze breaks that have a pending snooze — the snooze IS their next
    occurrence (#84). A frozen break neither counts down nor fires:

    - restore each pending break's pre-tick `remaining` (undo this tick's decrement),
    - drop a `fire_index` that points at a pending break (it must not pop while snoozed).

    Pure; returns a NEW (new_remaining, fire_index) and never mutates the input list.
    """
    frozen = [prev if names[i] in pending_names else cur
              for i, (cur, prev) in enumerate(zip(new_remaining, prev_remaining))]
    if fire_index is not None and names[fire_index] in pending_names:
        fire_index = None
    return frozen, fire_index


def advance(states, ctx, episode, pause_threshold=0,
            away_threshold=AWAY_IDLE_THRESHOLD_SECONDS,
            natural_threshold=NATURAL_BREAK_IDLE_THRESHOLD_SECONDS):
    """Run one tick. Returns a TickOutcome.

    The event dedup lives entirely in `events_for_tick`; the outcome always
    carries this tick's raw `defer_reason`/`defer_app` so the caller never has to
    infer the current hold from whether an event happened to be emitted.
    """
    result = step(states, ctx, natural_threshold=natural_threshold,
                  away_threshold=away_threshold, pause_threshold=pause_threshold)
    events, new_episode = events_for_tick(result, ctx, episode)
    return TickOutcome(new_remaining=result.new_remaining,
                       fire_index=result.fire_index,
                       events=events, episode=new_episode,
                       defer_reason=result.defer_reason,
                       defer_app=result.defer_app)

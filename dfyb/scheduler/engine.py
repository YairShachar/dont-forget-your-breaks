"""Pure scheduling brain: decide fire/defer/natural-break from a Context. No Tk, no I/O."""
from dataclasses import dataclass

# Configurable thresholds (can surface to a settings UI in a later phase).
NATURAL_BREAK_IDLE_THRESHOLD_SECONDS = 300  # idle >= this => natural break (reset all timers)
AWAY_IDLE_THRESHOLD_SECONDS = 60            # idle >= this at fire time => defer (briefly away)
MIN_LADDER_GAP_SECONDS = 5                  # strict-ordering floor between pause < away < natural

FIRE = "fire"
DEFER = "defer"


@dataclass(frozen=True)
class Context:
    """What the sensors observed this tick."""
    idle_seconds: float
    is_fullscreen: bool
    is_meeting: bool = False
    active_idle_seconds: float | None = None  # typing/clicks idle; None -> use idle_seconds
    # Which app caused the signal, as {"id", "name", "count"} — for the UI and the
    # event log only; `decide()` never reads them. None when not deferring or when
    # attribution was unavailable.
    meeting_app: dict | None = None
    fullscreen_app: dict | None = None


@dataclass(frozen=True)
class BreakState:
    """Plain, Tk-free snapshot of one break, parallel to the configs."""
    remaining: int          # seconds left on this break's countdown
    interval_seconds: int   # reset value (BreakConfig.get_interval_seconds())
    duration_seconds: int   # how long the break lasts (used for "longest wins")


@dataclass(frozen=True)
class StepResult:
    """What the loop should do this tick."""
    new_remaining: list[int]        # updated `remaining` per break (write back to configs)
    natural_break: bool = False
    fire_index: int | None = None   # which break to pop
    defer_reason: str | None = None  # "fullscreen" | "meeting" | "away"


def is_natural_break(idle_seconds, threshold=NATURAL_BREAK_IDLE_THRESHOLD_SECONDS):
    """True if the user has been idle long enough to count as having taken a break."""
    return idle_seconds >= threshold


def coordinate_thresholds(pause, away, natural, gap=MIN_LADDER_GAP_SECONDS):
    """Return (pause, away, natural) guaranteed strictly ordered pause < away <
    natural, anchored on `pause` (the user's explicit wait-until-you-pause value);
    the upper rungs are floored up by `gap` as needed. Idempotent — coordinating an
    already-ordered triple is a no-op. Pure; the safety net that makes the
    'set pause >= away => break never fires' edge bug impossible for ANY config."""
    away = max(away, pause + gap)
    natural = max(natural, away + gap)
    return pause, away, natural


def decide(ctx, away_threshold=AWAY_IDLE_THRESHOLD_SECONDS, pause_threshold=0):
    """Decide whether a due break should FIRE or DEFER given the current context."""
    if ctx.is_fullscreen:
        return DEFER          # don't interrupt fullscreen
    if ctx.is_meeting:
        return DEFER          # don't interrupt a call (mic in use)
    if ctx.idle_seconds >= away_threshold:
        return DEFER          # briefly away — any input counts as present
    active_idle = (ctx.idle_seconds if ctx.active_idle_seconds is None
                   else ctx.active_idle_seconds)
    if active_idle < pause_threshold:
        return DEFER          # mid-activity — typing/clicks (not bare mouse-move)
    return FIRE


def step(states, ctx,
         natural_threshold=NATURAL_BREAK_IDLE_THRESHOLD_SECONDS,
         away_threshold=AWAY_IDLE_THRESHOLD_SECONDS,
         pause_threshold=0):
    """Advance one 1-second tick. Returns a StepResult describing what to do.

    `states` is a list[BreakState] parallel to the app's break configs. Thresholds
    are coordinated (pause < away < natural) up front, so the decision is coherent
    for ANY caller-supplied values (incl. legacy / hand-edited prefs).
    """
    pause_threshold, away_threshold, natural_threshold = coordinate_thresholds(
        pause_threshold, away_threshold, natural_threshold)
    # 1. Natural break: idle long enough -> reset all timers, do not decrement.
    if is_natural_break(ctx.idle_seconds, natural_threshold):
        return StepResult(new_remaining=[s.interval_seconds for s in states],
                          natural_break=True)

    # 2. Decrement; collect breaks that are now due.
    new_remaining = [s.remaining - 1 for s in states]
    due = [i for i, r in enumerate(new_remaining) if r <= 0]

    # 3. If any are due, decide fire vs defer.
    if due:
        if decide(ctx, away_threshold, pause_threshold) == DEFER:
            if ctx.is_fullscreen:
                reason = "fullscreen"
            elif ctx.is_meeting:
                reason = "meeting"
            elif ctx.idle_seconds >= away_threshold:
                reason = "away"
            else:
                reason = "active"             # idle < pause_threshold
            for i in due:
                new_remaining[i] = 0          # clamp — stays due, no negative drift
            return StepResult(new_remaining=new_remaining, defer_reason=reason)
        # FIRE: pop the longest-duration due break; reset all due breaks.
        fire_index = max(due, key=lambda i: states[i].duration_seconds)
        for i in due:
            new_remaining[i] = states[i].interval_seconds
        return StepResult(new_remaining=new_remaining, fire_index=fire_index)

    # 4. Nothing due — just the decremented counters.
    return StepResult(new_remaining=new_remaining)

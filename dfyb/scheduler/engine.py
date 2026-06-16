"""Pure scheduling brain: decide fire/defer/natural-break from a Context. No Tk, no I/O."""
from dataclasses import dataclass

# Configurable thresholds (can surface to a settings UI in a later phase).
NATURAL_BREAK_IDLE_THRESHOLD_SECONDS = 300  # idle >= this => natural break (reset all timers)
AWAY_IDLE_THRESHOLD_SECONDS = 60            # idle >= this at fire time => defer (briefly away)

FIRE = "fire"
DEFER = "defer"


@dataclass(frozen=True)
class Context:
    """What the sensors observed this tick."""
    idle_seconds: float
    is_fullscreen: bool


@dataclass(frozen=True)
class BreakState:
    """Plain, Tk-free snapshot of one break, parallel to the configs."""
    remaining: int          # seconds left on this break's countdown
    interval_seconds: int   # reset value (BreakConfig.get_interval_seconds())
    duration_seconds: int   # how long the break lasts (used for "longest wins")


@dataclass(frozen=True)
class StepResult:
    """What the loop should do this tick."""
    new_remaining: list             # updated `remaining` per break (write back to configs)
    natural_break: bool = False
    fire_index: int | None = None   # which break to pop
    defer_reason: str | None = None  # "fullscreen" | "away"


def is_natural_break(idle_seconds, threshold=NATURAL_BREAK_IDLE_THRESHOLD_SECONDS):
    """True if the user has been idle long enough to count as having taken a break."""
    return idle_seconds >= threshold


def decide(ctx, away_threshold=AWAY_IDLE_THRESHOLD_SECONDS):
    """Decide whether a due break should FIRE or DEFER given the current context."""
    if ctx.is_fullscreen:
        return DEFER          # don't interrupt fullscreen
    if ctx.idle_seconds >= away_threshold:
        return DEFER          # briefly away — wait until back and active
    return FIRE


def step(states, ctx,
         natural_threshold=NATURAL_BREAK_IDLE_THRESHOLD_SECONDS,
         away_threshold=AWAY_IDLE_THRESHOLD_SECONDS):
    """Advance one 1-second tick. Returns a StepResult describing what to do.

    `states` is a list[BreakState] parallel to the app's break configs.
    """
    # 1. Natural break: idle long enough -> reset all timers, do not decrement.
    if is_natural_break(ctx.idle_seconds, natural_threshold):
        return StepResult(new_remaining=[s.interval_seconds for s in states],
                          natural_break=True)

    # 2. Decrement; collect breaks that are now due.
    new_remaining = [s.remaining - 1 for s in states]
    due = [i for i, r in enumerate(new_remaining) if r <= 0]

    # 3. If any are due, decide fire vs defer.
    if due:
        if decide(ctx, away_threshold) == DEFER:
            reason = "fullscreen" if ctx.is_fullscreen else "away"
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

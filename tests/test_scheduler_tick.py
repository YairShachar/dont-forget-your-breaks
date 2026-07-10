from dfyb.scheduler.engine import Context, BreakState
from dfyb.activity.event_log import BREAK_DEFERRED, NATURAL_BREAK
from dfyb.scheduler.tick import (
    events_for_tick, advance, IDLE_EPISODE, DEFERRED_EPISODE,
)


def ctx(idle=0.0, fullscreen=False):
    return Context(idle_seconds=idle, is_fullscreen=fullscreen)


# --- events_for_tick (operates on a StepResult-like object) ---

class R:
    """Minimal StepResult stand-in for events_for_tick tests."""
    def __init__(self, natural_break=False, fire_index=None, defer_reason=None):
        self.natural_break = natural_break
        self.fire_index = fire_index
        self.defer_reason = defer_reason


def test_natural_break_logs_once_then_dedups():
    events, ep = events_for_tick(R(natural_break=True), ctx(idle=400), None)
    assert events == [(NATURAL_BREAK, {"idle_seconds": 400})]
    assert ep == IDLE_EPISODE
    # same episode -> no repeat
    events2, ep2 = events_for_tick(R(natural_break=True), ctx(idle=410), IDLE_EPISODE)
    assert events2 == [] and ep2 == IDLE_EPISODE


def test_defer_logs_once_then_dedups():
    events, ep = events_for_tick(R(defer_reason="fullscreen"), ctx(), None)
    assert events == [(BREAK_DEFERRED, {"reason": "fullscreen"})]
    assert ep == DEFERRED_EPISODE
    events2, ep2 = events_for_tick(R(defer_reason="fullscreen"), ctx(), DEFERRED_EPISODE)
    assert events2 == [] and ep2 == DEFERRED_EPISODE


def test_fire_clears_episode_and_logs_nothing():
    events, ep = events_for_tick(R(fire_index=0), ctx(), DEFERRED_EPISODE)
    assert events == [] and ep is None


def test_nothing_due_clears_episode():
    events, ep = events_for_tick(R(), ctx(), IDLE_EPISODE)
    assert events == [] and ep is None


def test_episode_transition_idle_to_deferred_relogs():
    # was idle, now deferring -> different episode, logs the defer
    events, ep = events_for_tick(R(defer_reason="away"), ctx(), IDLE_EPISODE)
    assert events == [(BREAK_DEFERRED, {"reason": "away"})]
    assert ep == DEFERRED_EPISODE


def test_episode_transition_deferred_to_idle_relogs():
    # was deferring, now idle -> different episode, logs the natural break
    events, ep = events_for_tick(R(natural_break=True), ctx(idle=400), DEFERRED_EPISODE)
    assert events == [(NATURAL_BREAK, {"idle_seconds": 400})]
    assert ep == IDLE_EPISODE


# --- advance (composes step + events_for_tick) ---

def test_advance_natural_break():
    states = [BreakState(remaining=5, interval_seconds=100, duration_seconds=5)]
    new_remaining, fire_index, events, ep = advance(states, ctx(idle=400), None)
    assert new_remaining == [100]
    assert fire_index is None
    assert events == [(NATURAL_BREAK, {"idle_seconds": 400})]
    assert ep == IDLE_EPISODE


def test_advance_fires_when_due_and_active():
    states = [BreakState(remaining=1, interval_seconds=100, duration_seconds=5)]
    new_remaining, fire_index, events, ep = advance(states, ctx(idle=0), None)
    assert fire_index == 0
    assert new_remaining == [100]
    assert events == []          # BREAK_TAKEN is logged on popup close, not here
    assert ep is None


def test_advance_defers_on_fullscreen():
    states = [BreakState(remaining=1, interval_seconds=100, duration_seconds=5)]
    new_remaining, fire_index, events, ep = advance(states, ctx(fullscreen=True), None)
    assert fire_index is None
    assert new_remaining == [0]  # clamped
    assert events == [(BREAK_DEFERRED, {"reason": "fullscreen"})]
    assert ep == DEFERRED_EPISODE


def test_advance_decrements_when_not_due():
    states = [BreakState(remaining=5, interval_seconds=100, duration_seconds=5)]
    new_remaining, fire_index, events, ep = advance(states, ctx(idle=0), None)
    assert new_remaining == [4]
    assert fire_index is None and events == [] and ep is None


def test_advance_defers_active():
    states = [BreakState(remaining=1, interval_seconds=100, duration_seconds=5)]
    new_remaining, fire_index, events, ep = advance(states, ctx(idle=2), None, pause_threshold=5)
    assert fire_index is None
    assert events == [(BREAK_DEFERRED, {"reason": "active"})]
    assert ep == DEFERRED_EPISODE

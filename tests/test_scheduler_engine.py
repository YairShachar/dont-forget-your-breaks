from dfyb.scheduler.engine import (
    Context, BreakState, step, decide, is_natural_break, FIRE, DEFER,
)


def ctx(idle=0.0, fullscreen=False):
    return Context(idle_seconds=idle, is_fullscreen=fullscreen)


def test_is_natural_break_threshold():
    assert is_natural_break(300) is True
    assert is_natural_break(299) is False
    assert is_natural_break(10, threshold=5) is True


def test_decide_fire_when_active():
    assert decide(ctx(idle=0, fullscreen=False)) == FIRE


def test_decide_defer_when_fullscreen():
    assert decide(ctx(idle=0, fullscreen=True)) == DEFER


def test_decide_defer_when_away():
    assert decide(ctx(idle=120, fullscreen=False)) == DEFER


def test_step_natural_break_resets_all():
    states = [BreakState(remaining=5, interval_seconds=100, duration_seconds=5),
              BreakState(remaining=8, interval_seconds=200, duration_seconds=600)]
    r = step(states, ctx(idle=300))
    assert r.natural_break is True
    assert r.new_remaining == [100, 200]
    assert r.fire_index is None and r.defer_reason is None


def test_step_decrements_when_not_due():
    states = [BreakState(remaining=5, interval_seconds=100, duration_seconds=5)]
    r = step(states, ctx(idle=0))
    assert r.new_remaining == [4]
    assert r.natural_break is False and r.fire_index is None and r.defer_reason is None


def test_step_fires_when_due_and_active():
    states = [BreakState(remaining=1, interval_seconds=100, duration_seconds=5)]
    r = step(states, ctx(idle=0))
    assert r.fire_index == 0
    assert r.new_remaining == [100]  # reset to interval


def test_step_fire_picks_longest_duration():
    states = [BreakState(remaining=1, interval_seconds=100, duration_seconds=5),
              BreakState(remaining=1, interval_seconds=200, duration_seconds=600)]
    r = step(states, ctx(idle=0))
    assert r.fire_index == 1               # longer duration wins
    assert r.new_remaining == [100, 200]   # both due breaks reset


def test_step_defers_on_fullscreen_and_clamps():
    states = [BreakState(remaining=1, interval_seconds=100, duration_seconds=5)]
    r = step(states, ctx(idle=0, fullscreen=True))
    assert r.defer_reason == "fullscreen"
    assert r.fire_index is None
    assert r.new_remaining == [0]          # clamped, stays due


def test_step_defers_when_away_and_clamps():
    states = [BreakState(remaining=1, interval_seconds=100, duration_seconds=5)]
    r = step(states, ctx(idle=120, fullscreen=False))
    assert r.defer_reason == "away"
    assert r.new_remaining == [0]


def test_step_deferred_break_stays_due_next_tick():
    states = [BreakState(remaining=0, interval_seconds=100, duration_seconds=5)]
    r = step(states, ctx(idle=0, fullscreen=True))
    assert r.defer_reason == "fullscreen"
    assert r.new_remaining == [0]          # -1 then clamped back to 0


def test_step_thresholds_are_parameterizable():
    states = [BreakState(remaining=1, interval_seconds=100, duration_seconds=5)]
    # idle 10 with away_threshold 5 -> defer; natural_threshold high so not natural
    r = step(states, ctx(idle=10), natural_threshold=300, away_threshold=5)
    assert r.defer_reason == "away"


def test_step_empty_states_is_safe():
    # No breaks configured (startup race / all breaks removed) must not crash.
    r = step([], ctx(idle=0))
    assert r.new_remaining == []
    assert r.natural_break is False
    assert r.fire_index is None and r.defer_reason is None


def test_step_defer_prefers_fullscreen_over_away():
    # When both fullscreen AND away apply, fullscreen wins the defer reason.
    states = [BreakState(remaining=1, interval_seconds=100, duration_seconds=5)]
    r = step(states, ctx(idle=120, fullscreen=True))
    assert r.defer_reason == "fullscreen"


def test_decide_defers_during_meeting():
    assert decide(Context(idle_seconds=0.0, is_fullscreen=False, is_meeting=True)) == DEFER


def test_decide_fires_when_not_meeting_fullscreen_or_away():
    assert decide(Context(idle_seconds=0.0, is_fullscreen=False, is_meeting=False)) == FIRE


def test_step_defer_reason_meeting():
    states = [BreakState(remaining=1, interval_seconds=100, duration_seconds=5)]
    result = step(states, Context(idle_seconds=0.0, is_fullscreen=False, is_meeting=True))
    assert result.defer_reason == "meeting"
    assert result.fire_index is None
    assert result.new_remaining == [0]


def test_step_fullscreen_takes_precedence_over_meeting():
    states = [BreakState(remaining=1, interval_seconds=100, duration_seconds=5)]
    result = step(states, Context(idle_seconds=0.0, is_fullscreen=True, is_meeting=True))
    assert result.defer_reason == "fullscreen"


def test_context_is_meeting_defaults_false():
    assert Context(idle_seconds=0.0, is_fullscreen=False).is_meeting is False

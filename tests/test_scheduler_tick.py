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
    def __init__(self, natural_break=False, fire_index=None, defer_reason=None,
                 defer_app=None):
        self.natural_break = natural_break
        self.fire_index = fire_index
        self.defer_reason = defer_reason
        self.defer_app = defer_app


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


# --- advance forwards away/natural thresholds (Task 3) ---------------------

def _due_states():
    return [BreakState(remaining=1, interval_seconds=1500, duration_seconds=300)]


def test_advance_forwards_away_threshold():
    c = Context(idle_seconds=40, is_fullscreen=False, active_idle_seconds=40)
    # pause off (0): a due break fires when present (idle < away), defers when away.
    _, fire_lo, _, _ = advance(_due_states(), c, None, pause_threshold=0, away_threshold=30)
    _, fire_hi, _, _ = advance(_due_states(), c, None, pause_threshold=0, away_threshold=60)
    assert fire_lo is None      # idle 40 >= away 30 -> defer away
    assert fire_hi == 0         # idle 40 < away 60 -> fire


def test_advance_forwards_natural_threshold():
    c = Context(idle_seconds=200, is_fullscreen=False, active_idle_seconds=200)
    _, _, _, ep = advance(_due_states(), c, None, natural_threshold=180)
    assert ep == IDLE_EPISODE    # 200 >= 180 -> natural break episode


# --- apply_snooze_freeze: a pending-snoozed break is frozen, never fires (#84) ---
from dfyb.scheduler.tick import apply_snooze_freeze


def test_freeze_restores_pending_break_remaining():
    # Micro decremented 100->99, Normal (snoozed) 3000->2999; Normal freezes back to 3000.
    new_rem, fire = apply_snooze_freeze(
        new_remaining=[99, 2999], fire_index=None, prev_remaining=[100, 3000],
        names=["Micro", "Normal"], pending_names={"Normal"})
    assert new_rem == [99, 3000]
    assert fire is None


def test_freeze_drops_a_fire_that_points_at_a_snoozed_break():
    # Normal is due (fire_index=1) but it's pending-snoozed -> drop the fire, freeze it.
    new_rem, fire = apply_snooze_freeze(
        new_remaining=[99, 0], fire_index=1, prev_remaining=[100, 3000],
        names=["Micro", "Normal"], pending_names={"Normal"})
    assert new_rem == [99, 3000]
    assert fire is None


def test_freeze_keeps_a_fire_for_a_non_snoozed_break():
    # Micro is due and NOT snoozed -> fire stands; Normal still frozen.
    new_rem, fire = apply_snooze_freeze(
        new_remaining=[0, 2999], fire_index=0, prev_remaining=[1, 3000],
        names=["Micro", "Normal"], pending_names={"Normal"})
    assert new_rem == [0, 3000]
    assert fire == 0


def test_freeze_noop_without_pending():
    new_rem, fire = apply_snooze_freeze(
        new_remaining=[99, 2999], fire_index=1, prev_remaining=[100, 3000],
        names=["Micro", "Normal"], pending_names=set())
    assert new_rem == [99, 2999]
    assert fire == 1


def test_freeze_does_not_mutate_inputs():
    new_remaining = [99, 2999]
    apply_snooze_freeze(new_remaining, None, [100, 3000], ["Micro", "Normal"], {"Normal"})
    assert new_remaining == [99, 2999]   # caller's list untouched


# --- #85: due-since tracking + deferral-at-fire (how long a break was held) ---
from dfyb.scheduler.tick import track_due_since, deferral_at_fire


def test_track_due_since_sets_on_first_due_tick():
    # prev remaining 1 -> hits 0 this tick -> stamped at `now`
    assert track_due_since({}, ["Micro"], [1], now=100.0) == {"Micro": 100.0}


def test_track_due_since_keeps_first_timestamp_while_held():
    # still held (prev 0) later -> timestamp NOT re-stamped
    assert track_due_since({"Micro": 100.0}, ["Micro"], [0], now=105.0) == {"Micro": 100.0}


def test_track_due_since_clears_when_not_due():
    # break got reset (prev remaining large) -> cleared
    assert track_due_since({"Micro": 100.0}, ["Micro"], [1500], now=110.0) == {}


def test_track_due_since_is_pure():
    d = {"Micro": 100.0}
    track_due_since(d, ["Micro"], [1500], now=110.0)
    assert d == {"Micro": 100.0}   # input untouched


def test_track_due_since_only_the_due_break():
    assert track_due_since({}, ["Micro", "Normal"], [1, 900], now=50.0) == {"Micro": 50.0}


def test_deferral_at_fire_zero_when_just_due():
    assert deferral_at_fire({"Micro": 200.0}, "Micro", now=200.0) == (200.0, 0.0)


def test_deferral_at_fire_measures_hold():
    assert deferral_at_fire({"Normal": 200.0}, "Normal", now=260.0) == (200.0, 60.0)


def test_deferral_at_fire_falls_back_to_now_if_unrecorded():
    assert deferral_at_fire({}, "Ghost", now=300.0) == (300.0, 0.0)


def test_deferral_at_fire_never_negative():
    _, deferred = deferral_at_fire({"X": 400.0}, "X", now=390.0)   # clock skew
    assert deferred == 0.0


def test_deferred_duration_end_to_end():
    # A due break held by a meeting for 3 ticks then fires -> deferred == 3s (#85).
    name = "Normal"

    def tick(remaining, due_since, now, meeting):
        states = [BreakState(remaining=remaining, interval_seconds=3000, duration_seconds=600)]
        c = Context(idle_seconds=0.0, is_fullscreen=False, is_meeting=meeting,
                    active_idle_seconds=0.0)
        prev = [remaining]
        new_remaining, fire_index, _, _ = advance(states, c, None)
        due_since = track_due_since(due_since, [name], prev, now)
        return new_remaining[0], fire_index, due_since

    remaining, due = 1, {}
    remaining, fire, due = tick(remaining, due, 1000.0, meeting=True)    # becomes due, held
    assert fire is None and due == {name: 1000.0}
    remaining, fire, due = tick(remaining, due, 1001.0, meeting=True)    # held
    assert fire is None and due == {name: 1000.0}
    remaining, fire, due = tick(remaining, due, 1002.0, meeting=True)    # held
    assert fire is None
    remaining, fire, due = tick(remaining, due, 1003.0, meeting=False)   # good moment -> fire
    assert fire == 0
    scheduled_ts, deferred = deferral_at_fire(due, name, 1003.0)
    assert scheduled_ts == 1000.0 and deferred == 3.0


def test_deferred_duration_zero_when_fires_immediately():
    # due and fires the same tick (no hold) -> deferred 0.
    states = [BreakState(remaining=1, interval_seconds=3000, duration_seconds=600)]
    c = Context(idle_seconds=0.0, is_fullscreen=False, is_meeting=False, active_idle_seconds=0.0)
    _, fire_index, _, _ = advance(states, c, None)
    due = track_due_since({}, ["Normal"], [1], now=500.0)
    assert fire_index == 0
    assert deferral_at_fire(due, "Normal", 500.0) == (500.0, 0.0)


def test_deferred_event_records_which_app_caused_it():
    from dfyb.scheduler.engine import StepResult
    result = StepResult(new_remaining=[0], defer_reason="meeting",
                        defer_app={"id": "us.zoom.xos", "name": "Zoom", "count": 2})
    ctx = Context(idle_seconds=0.0, is_fullscreen=False, is_meeting=True)
    events, episode = events_for_tick(result, ctx, None)
    assert events == [("break_deferred", {"reason": "meeting", "app": "us.zoom.xos",
                                          "app_name": "Zoom", "holder_count": 2})]
    assert episode == "deferred"


def test_deferred_event_without_attribution_keeps_todays_payload():
    from dfyb.scheduler.engine import StepResult
    result = StepResult(new_remaining=[0], defer_reason="away")
    ctx = Context(idle_seconds=120.0, is_fullscreen=False)
    events, _episode = events_for_tick(result, ctx, None)
    assert events == [("break_deferred", {"reason": "away"})]

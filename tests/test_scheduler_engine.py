from dfyb.scheduler.engine import (
    Context, BreakState, step, decide, is_natural_break, FIRE, DEFER,
    coordinate_thresholds, MIN_LADDER_GAP_SECONDS, defer_reason_and_app,
    resolve_held_app,
)

GAP = MIN_LADDER_GAP_SECONDS


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


def test_step_meeting_takes_precedence_over_away():
    # meeting + idle past the away threshold -> reason is "meeting", not "away"
    states = [BreakState(remaining=1, interval_seconds=100, duration_seconds=5)]
    result = step(states, Context(idle_seconds=120.0, is_fullscreen=False, is_meeting=True))
    assert result.defer_reason == "meeting"


def test_step_defers_micro_and_normal_together():
    # Micro (short) + Normal (long) both due, in a meeting -> BOTH held, neither
    # fires. Deferral is context-based, not per-break-type.
    micro = BreakState(remaining=1, interval_seconds=1200, duration_seconds=20)
    normal = BreakState(remaining=1, interval_seconds=3600, duration_seconds=300)
    r = step([micro, normal], Context(idle_seconds=0.0, is_fullscreen=False, is_meeting=True))
    assert r.defer_reason == "meeting"
    assert r.fire_index is None
    assert r.new_remaining == [0, 0]   # both held


def test_step_defers_the_normal_break_when_it_is_the_only_one_due():
    # Only the Normal (long) break is due (Micro still counting), in fullscreen
    # -> the Normal break defers exactly like the Micro would.
    micro = BreakState(remaining=500, interval_seconds=1200, duration_seconds=20)
    normal = BreakState(remaining=1, interval_seconds=3600, duration_seconds=300)
    r = step([micro, normal], Context(idle_seconds=0.0, is_fullscreen=True))
    assert r.defer_reason == "fullscreen"
    assert r.fire_index is None
    assert r.new_remaining[1] == 0     # Normal held
    assert r.new_remaining[0] == 499   # Micro just decrements


def test_decide_defers_when_active():
    assert decide(ctx(idle=2), pause_threshold=5) == DEFER


def test_decide_fires_in_the_pause_window():
    # past the pause threshold, before away -> fire
    assert decide(ctx(idle=10), pause_threshold=5) == FIRE


def test_decide_pause_threshold_zero_disables():
    # default 0 -> active idle still fires (feature off)
    assert decide(ctx(idle=0)) == FIRE


def test_step_defer_reason_active():
    states = [BreakState(remaining=1, interval_seconds=100, duration_seconds=5)]
    r = step(states, ctx(idle=2), pause_threshold=5)
    assert r.defer_reason == "active"
    assert r.fire_index is None
    assert r.new_remaining == [0]


def test_step_fires_in_pause_window():
    states = [BreakState(remaining=1, interval_seconds=100, duration_seconds=5)]
    r = step(states, ctx(idle=10), pause_threshold=5)
    assert r.fire_index == 0


def test_step_away_beats_active():
    # idle >= away threshold -> "away" (can't be both < pause and >= away)
    states = [BreakState(remaining=1, interval_seconds=100, duration_seconds=5)]
    r = step(states, ctx(idle=120), pause_threshold=5)
    assert r.defer_reason == "away"


def test_step_meeting_beats_active():
    states = [BreakState(remaining=1, interval_seconds=100, duration_seconds=5)]
    r = step(states, Context(idle_seconds=1.0, is_fullscreen=False, is_meeting=True),
             pause_threshold=5)
    assert r.defer_reason == "meeting"


# --- active_idle_seconds: keyboard-primary pause (#41) ---

def test_decide_fire_when_mouse_moved_but_not_typing():
    # moved mouse (idle low) but no typing (active_idle high) -> not "active" -> FIRE
    ctx = Context(idle_seconds=1, is_fullscreen=False, active_idle_seconds=30)
    assert decide(ctx, pause_threshold=2) == FIRE


def test_decide_defer_active_when_typing():
    ctx = Context(idle_seconds=1, is_fullscreen=False, active_idle_seconds=1)
    assert decide(ctx, pause_threshold=2) == DEFER


def test_decide_active_falls_back_to_idle_when_unset():
    # active_idle_seconds=None -> uses idle_seconds for the pause check (old behavior)
    ctx = Context(idle_seconds=1, is_fullscreen=False)
    assert decide(ctx, pause_threshold=2) == DEFER


def test_decide_away_ignores_active_idle():
    # away keys off idle_seconds (any input) regardless of active_idle
    ctx = Context(idle_seconds=100, is_fullscreen=False, active_idle_seconds=0)
    assert decide(ctx, pause_threshold=2) == DEFER


# --- coordinate_thresholds (Task 1) ---------------------------------------

def test_coordinate_keeps_already_ordered_values():
    assert coordinate_thresholds(2, 60, 300) == (2, 60, 300)
    assert coordinate_thresholds(0, 60, 300) == (0, 60, 300)


def test_coordinate_floors_away_above_pause():
    assert coordinate_thresholds(90, 60, 300) == (90, 90 + GAP, 300)


def test_coordinate_floors_natural_above_away():
    # away floored above pause, then natural floored above that
    assert coordinate_thresholds(90, 60, 90) == (90, 90 + GAP, 90 + 2 * GAP)


def test_coordinate_all_equal_gets_gapped():
    assert coordinate_thresholds(50, 50, 50) == (50, 50 + GAP, 50 + 2 * GAP)


def test_coordinate_is_idempotent():
    once = coordinate_thresholds(90, 60, 90)
    assert coordinate_thresholds(*once) == once


# --- step() honors coordinated thresholds (Task 2) -------------------------

def _due_states():
    # one break that becomes due this tick (remaining 1 -> 0)
    return [BreakState(remaining=1, interval_seconds=1500, duration_seconds=300)]


def test_regression_pause_ge_away_still_fires_when_present():
    # pause 90 >= away 60: previously "away" defers at 60 before active_idle hits
    # 90, so a still pause could NEVER fire. Coordination floors away to 95, so a
    # present-and-paused user (idle 92 in [90,95)) fires.
    ctx = Context(idle_seconds=92, is_fullscreen=False, active_idle_seconds=92)
    res = step(_due_states(), ctx, natural_threshold=300,
               away_threshold=60, pause_threshold=90)
    assert res.fire_index == 0
    assert res.defer_reason is None


def test_gone_past_configured_away_defers_away():
    ctx = Context(idle_seconds=96, is_fullscreen=False, active_idle_seconds=96)
    res = step(_due_states(), ctx, natural_threshold=300,
               away_threshold=60, pause_threshold=90)  # coordinated away = 95
    assert res.fire_index is None
    assert res.defer_reason == "away"


def test_present_pause_never_labelled_away():
    # stopped typing but moving the mouse: present (idle low) + paused -> FIRE
    ctx = Context(idle_seconds=1, is_fullscreen=False, active_idle_seconds=10)
    res = step(_due_states(), ctx, away_threshold=60, pause_threshold=3)
    assert res.fire_index == 0


def test_configured_natural_threshold_resets_timers():
    ctx = Context(idle_seconds=200, is_fullscreen=False, active_idle_seconds=200)
    res = step(_due_states(), ctx, natural_threshold=180)  # 200 >= 180
    assert res.natural_break is True
    assert res.new_remaining == [1500]


def test_context_app_fields_default_to_none():
    c = Context(idle_seconds=0.0, is_fullscreen=False)
    assert c.meeting_app is None and c.fullscreen_app is None


ZOOM_REF = {"id": "us.zoom.xos", "name": "Zoom", "count": 1}


def test_defer_reason_and_app_names_the_mic_holder():
    c = Context(idle_seconds=0.0, is_fullscreen=False, is_meeting=True,
                meeting_app=ZOOM_REF)
    assert defer_reason_and_app(c, 60, 0) == ("meeting", ZOOM_REF)


def test_defer_reason_and_app_prefers_fullscreen_like_decide_does():
    # decide() checks fullscreen first; the reason must agree with it.
    keynote = {"id": "com.apple.iWork.Keynote", "name": "Keynote", "count": 1}
    c = Context(idle_seconds=0.0, is_fullscreen=True, is_meeting=True,
                fullscreen_app=keynote, meeting_app=ZOOM_REF)
    assert defer_reason_and_app(c, 60, 0) == ("fullscreen", keynote)


def test_defer_reason_and_app_has_no_app_for_away():
    c = Context(idle_seconds=120.0, is_fullscreen=False)
    assert defer_reason_and_app(c, 60, 0) == ("away", None)


def test_step_carries_the_deferring_app_through():
    states = [BreakState(remaining=1, interval_seconds=600, duration_seconds=15)]
    c = Context(idle_seconds=0.0, is_fullscreen=False, is_meeting=True,
                meeting_app=ZOOM_REF)
    r = step(states, c)
    assert r.defer_reason == "meeting" and r.defer_app == ZOOM_REF


# --- resolve_held_app: WHO to name for a deferral (#40) ---------------------

KEYNOTE_REF = {"id": "com.apple.iWork.Keynote", "name": "Keynote", "count": 1}


def test_resolve_held_app_fullscreen_wins_over_meeting_when_both_effective():
    # Mirrors decide()'s priority (fullscreen before meeting) so the hero can
    # never name the mic app under the "is in full screen" template.
    resolved = resolve_held_app(True, True, KEYNOTE_REF, ZOOM_REF, previous=None)
    assert resolved == KEYNOTE_REF


def test_resolve_held_app_meeting_only_names_the_meeting_app():
    resolved = resolve_held_app(False, True, None, ZOOM_REF, previous=None)
    assert resolved == ZOOM_REF


def test_resolve_held_app_carries_the_previous_app_across_a_blip():
    # The effective signal is still bridged by smooth_signal, but this tick's
    # raw ctx app is None (the blip) — the previously-known app must survive.
    resolved = resolve_held_app(False, True, None, None, previous=ZOOM_REF)
    assert resolved == ZOOM_REF


def test_resolve_held_app_no_stale_carry_once_the_signal_is_off():
    resolved = resolve_held_app(False, False, None, None, previous=ZOOM_REF)
    assert resolved is None


TEAMS_REF = {"id": "com.microsoft.teams2", "name": "Teams", "count": 1}


def test_resolve_held_app_a_new_app_wins_immediately_over_the_carried_one():
    # The signal went off and came back on with a DIFFERENT app — the new app
    # must win immediately; a stale carry would wrongly keep naming the old one.
    resolved = resolve_held_app(False, True, None, TEAMS_REF, previous=ZOOM_REF)
    assert resolved == TEAMS_REF

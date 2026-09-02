"""Integration-level tests for the #84 deferral debounce.

These compose the exact pipeline the timer loop runs — smooth_signal() over each
interrupt signal, then advance() — WITHOUT Tk, so they prove that a one-tick sensor
dropout (a mic per-utterance blip, a brief typing pause) no longer fires a due break
mid-activity. They would FAIL against the pre-#84 code (no hysteresis on mic/active).
"""
from dataclasses import replace

from dfyb.activity.sensors import smooth_signal, DEFER_GRACE_TICKS
from dfyb.scheduler.engine import Context, BreakState
from dfyb.scheduler.tick import advance


def _due_state():
    # remaining=1 so a single advance() tick makes it due (remaining -> 0).
    return [BreakState(remaining=1, interval_seconds=1500, duration_seconds=300)]


class Grace:
    """Carries the three per-signal grace counters across ticks, like BreakApp."""
    def __init__(self):
        self.fs = self.mtg = self.act = 0


def _smoothed(raw_ctx, grace, pause):
    """Mirror launch.py's timer-loop smoothing exactly."""
    eff_fs, grace.fs = smooth_signal(raw_ctx.is_fullscreen, grace.fs)
    eff_mtg, grace.mtg = smooth_signal(raw_ctx.is_meeting, grace.mtg)
    raw_active_idle = (raw_ctx.idle_seconds if raw_ctx.active_idle_seconds is None
                       else raw_ctx.active_idle_seconds)
    raw_active = pause > 0 and raw_active_idle < pause
    eff_active, grace.act = smooth_signal(raw_active, grace.act)
    return replace(raw_ctx, is_fullscreen=eff_fs, is_meeting=eff_mtg,
                   active_idle_seconds=(0.0 if eff_active else raw_ctx.active_idle_seconds))


def _fire(raw_ctx, grace, pause=3):
    """Run one smoothed tick against a freshly-due break; return fire_index."""
    ctx = _smoothed(raw_ctx, grace, pause)
    return advance(_due_state(), ctx, None, pause_threshold=pause).fire_index


# --- microphone: a per-utterance blip must NOT fire the break mid-call ---

def test_mic_blip_does_not_fire_break():
    grace = Grace()
    on_call = Context(idle_seconds=0.0, is_fullscreen=False, is_meeting=True, active_idle_seconds=10.0)
    # user talking -> mic on -> deferred, meeting grace armed
    assert _fire(on_call, grace) is None
    # ONE tick where CoreAudio reports the device briefly stopped (between words)
    blip = Context(idle_seconds=0.0, is_fullscreen=False, is_meeting=False, active_idle_seconds=10.0)
    assert _fire(blip, grace) is None      # bridged by hysteresis — the bug is fixed
    # talking again -> stays deferred
    assert _fire(on_call, grace) is None


def test_mic_truly_ended_fires_after_grace_expires():
    grace = Grace()
    on_call = Context(idle_seconds=0.0, is_fullscreen=False, is_meeting=True, active_idle_seconds=10.0)
    _fire(on_call, grace)                                   # arm grace
    off = Context(idle_seconds=0.0, is_fullscreen=False, is_meeting=False, active_idle_seconds=10.0)
    fired = [ _fire(off, grace) for _ in range(DEFER_GRACE_TICKS + 1) ]
    # held through the grace window, then fires once the mic is really idle
    assert fired[-1] == 0
    assert fired[:DEFER_GRACE_TICKS] == [None] * DEFER_GRACE_TICKS


# --- active input: a brief typing pause must NOT fire mid-work ---

def test_brief_typing_pause_does_not_fire():
    grace = Grace()
    pause = 3
    typing = Context(idle_seconds=0.0, is_fullscreen=False, is_meeting=False, active_idle_seconds=0.0)
    assert _fire(typing, grace, pause) is None             # actively typing -> deferred
    # a >pause still gap (thinking mid-sentence): raw would fire pre-#84
    gap = Context(idle_seconds=4.0, is_fullscreen=False, is_meeting=False, active_idle_seconds=4.0)
    assert _fire(gap, grace, pause) is None                # bridged by hysteresis

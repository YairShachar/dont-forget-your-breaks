from dfyb.insights.status import (format_countdown, progress_fraction, compute_status,
                                  RESTED_HEADLINE, RESTED_SUBTEXT)


class TestFormat:
    def test_mmss(self):
        assert format_countdown(272) == "4:32"

    def test_floor_zero(self):
        assert format_countdown(-5) == "0:00"

    def test_hours(self):
        assert format_countdown(3723) == "1:02:03"


class TestProgress:
    def test_mid(self):
        assert progress_fraction(300, 600) == 0.5

    def test_clamped(self):
        assert progress_fraction(-10, 600) == 1.0

    def test_zero_interval(self):
        assert progress_fraction(5, 0) == 0.0


class TestCompute:
    def base(self, **kw):
        d = dict(running=True, paused=False, held_reason=None, next_name="Micro Break",
                 next_remaining=272, next_interval=900, break_active=False)
        d.update(kw)
        return d

    def test_idle(self):
        v = compute_status(**self.base(running=False))
        assert v.state == "idle" and v.dot == "idle" and v.progress == 0
        assert v.headline == "Ready when you are"       # no redundant big "Idle"
        assert v.progress_style == "none"

    def test_paused_shows_frozen_time_left(self):
        v = compute_status(**self.base(paused=True))
        assert v.state == "paused" and v.dot == "warning"
        # time-left stays visible when paused; the pill (not the headline) says "Paused"
        assert v.headline == "Next break in 4:32" and v.subtext == "Micro Break"
        assert v.progress_style == "frozen"
        assert abs(v.progress - (1 - 272 / 900)) < 1e-9   # frozen where it was

    def test_on_track(self):
        v = compute_status(**self.base())
        assert v.state == "on_track" and v.dot == "good"
        assert v.headline == "Next break in 4:32" and v.subtext == "Micro Break"
        assert abs(v.progress - (1 - 272 / 900)) < 1e-9 and v.chip is None
        assert v.progress_style == "live"

    def test_holding_progress_is_live(self):
        v = compute_status(**self.base(held_reason="meeting"))
        assert v.progress_style == "live"

    def test_holding_meeting(self):
        v = compute_status(**self.base(held_reason="meeting"))
        assert v.state == "holding" and v.dot == "warning"
        assert v.headline == "Waiting — you're in a call"
        assert v.chip == "Breaks pause during meetings"
        assert v.subtext == "Micro Break is due; it'll wait"

    def test_holding_fullscreen(self):
        v = compute_status(**self.base(held_reason="fullscreen"))
        assert v.headline == "Waiting — you're in full screen"
        assert v.chip == "Breaks pause in full screen"

    def test_holding_unknown_reason_falls_back(self):
        v = compute_status(**self.base(held_reason="thing"))
        assert v.headline == "Waiting — thing" and v.chip == "Breaks pause during thing"


# --- welcome-back cue (Task 4) ---------------------------------------------

_BASE = dict(next_name="Micro Break", next_remaining=100, next_interval=200)


def test_just_rested_shows_welcome_back_on_track():
    v = compute_status(running=True, paused=False, held_reason=None,
                       break_active=False, just_rested=True, **_BASE)
    assert v.headline == RESTED_HEADLINE
    assert v.subtext == RESTED_SUBTEXT
    assert v.state == "on_track" and v.dot == "good"


def test_just_rested_ignored_when_paused():
    v = compute_status(running=True, paused=True, held_reason=None,
                       break_active=False, just_rested=True, **_BASE)
    assert v.state == "paused"


def test_just_rested_ignored_when_holding_or_break():
    held = compute_status(running=True, paused=False, held_reason="away",
                          break_active=False, just_rested=True, **_BASE)
    brk = compute_status(running=True, paused=False, held_reason=None,
                         break_active=True, just_rested=True, **_BASE)
    assert held.state == "holding"
    assert brk.state == "break"


def test_default_just_rested_is_backward_compatible():
    v = compute_status(running=True, paused=False, held_reason=None,
                       break_active=False, **_BASE)
    assert v.state == "on_track" and v.headline.startswith("Next break")


# --- #74: anticipated-deferral chip (proactive, before a break is due) ---
from dfyb.insights.status import compute_status as _cs, ANTICIPATED_CHIPS


def _ontrack(**kw):
    base = dict(running=True, paused=False, held_reason=None, next_name="Micro",
                next_remaining=500, next_interval=1500, break_active=False)
    base.update(kw)
    return _cs(**base)


def test_anticipated_chip_shows_on_track():
    v = _ontrack(anticipated_reason="meeting")
    assert v.state == "on_track"
    assert v.chip == ANTICIPATED_CHIPS["meeting"]
    assert "call" in v.chip.lower()


def test_anticipated_none_has_no_chip():
    assert _ontrack(anticipated_reason=None).chip is None


def test_held_wins_over_anticipated():
    # a due+held break (reactive #44) takes precedence over the anticipatory chip
    v = _ontrack(held_reason="meeting", anticipated_reason="fullscreen")
    assert v.state == "holding"
    assert "Breaks pause" in v.chip


def test_paused_ignores_anticipated():
    v = _ontrack(paused=True, anticipated_reason="meeting")
    assert v.state == "paused"


# --- #40: name the app holding the mic / covering the screen -------------
from dfyb.insights.status import held_label, anticipated_chip


def test_held_label_names_the_mic_holder():
    assert held_label("meeting", "Zoom")[0] == "Zoom is using your microphone"


def test_held_label_names_the_fullscreen_app():
    assert held_label("fullscreen", "Keynote")[0] == "Keynote is in full screen"


def test_held_label_without_an_app_keeps_todays_wording():
    assert held_label("meeting")[0] == "you're in a call"
    assert held_label("fullscreen")[0] == "you're in full screen"


def test_held_label_unknown_reason_falls_back():
    assert held_label("wat") == ("wat", "during wat")


def test_status_headline_uses_the_app_name():
    view = compute_status(running=True, paused=False, held_reason="meeting",
                          next_name="Micro Break", next_remaining=0,
                          next_interval=600, break_active=False,
                          held_app_name="Zoom")
    assert view.headline == "Waiting — Zoom is using your microphone"


def test_status_exposes_the_ignore_action_when_attributed():
    view = compute_status(running=True, paused=False, held_reason="meeting",
                          next_name="Micro Break", next_remaining=0,
                          next_interval=600, break_active=False,
                          held_app_name="Zoom")
    assert view.chip_action_label == "Ignore Zoom"


def test_status_has_no_ignore_action_without_attribution():
    view = compute_status(running=True, paused=False, held_reason="meeting",
                          next_name="Micro Break", next_remaining=0,
                          next_interval=600, break_active=False)
    assert view.chip_action_label is None


def test_anticipated_chip_names_the_app():
    assert anticipated_chip("meeting", "Zoom") == "Zoom is using your microphone — your break will wait"


def test_anticipated_chip_without_an_app_keeps_todays_wording():
    assert anticipated_chip("meeting") == "In a call — your break will wait"

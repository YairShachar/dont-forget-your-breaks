from dfyb.insights.status import format_countdown, progress_fraction, compute_status


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

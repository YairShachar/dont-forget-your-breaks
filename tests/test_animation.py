import dfyb.animation as animation
from dfyb.animation import ease_out_quad, ease_in_quad, prefers_reduced_motion, lerp_color


class FakeProc:
    def __init__(self, stdout):
        self.stdout = stdout


def test_ease_out_quad_endpoints():
    assert ease_out_quad(0) == 0
    assert ease_out_quad(1) == 1


def test_ease_out_quad_midpoint():
    assert ease_out_quad(0.5) == 0.75


def test_ease_in_quad():
    assert ease_in_quad(0) == 0
    assert ease_in_quad(0.5) == 0.25
    assert ease_in_quad(1) == 1


def test_prefers_reduced_motion_non_darwin(monkeypatch):
    monkeypatch.setattr(animation.sys, "platform", "linux")
    assert prefers_reduced_motion() is False


def test_prefers_reduced_motion_darwin_enabled(monkeypatch):
    monkeypatch.setattr(animation.sys, "platform", "darwin")
    monkeypatch.setattr(animation.subprocess, "run", lambda *a, **k: FakeProc("1\n"))
    assert prefers_reduced_motion() is True


def test_prefers_reduced_motion_darwin_disabled(monkeypatch):
    monkeypatch.setattr(animation.sys, "platform", "darwin")
    monkeypatch.setattr(animation.subprocess, "run", lambda *a, **k: FakeProc("0\n"))
    assert prefers_reduced_motion() is False


def test_lerp_color_endpoints_midpoint_and_clamp():
    assert lerp_color("#000000", "#ffffff", 0) == "#000000"
    assert lerp_color("#000000", "#ffffff", 1) == "#ffffff"
    assert lerp_color("#000000", "#ffffff", 0.5) == "#808080"
    assert lerp_color("#000000", "#ffffff", 2) == "#ffffff"    # clamps high
    assert lerp_color("#ffffff", "#000000", -1) == "#ffffff"   # clamps low

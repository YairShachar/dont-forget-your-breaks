import sys
import types

import dfyb.activity.sensors as sensors


def _fake_quartz_idle(value):
    fake = types.ModuleType("Quartz")
    fake.kCGEventSourceStateHIDSystemState = 1
    fake.kCGAnyInputEventType = 0xFFFFFFFF
    fake.CGEventSourceSecondsSinceLastEventType = lambda state, evtype: value
    return fake


def _fake_quartz_windows(windows, screen=(1920, 1080)):
    fake = types.ModuleType("Quartz")
    fake.kCGWindowListOptionOnScreenOnly = 1
    fake.kCGWindowListExcludeDesktopElements = 16
    fake.kCGNullWindowID = 0
    fake.CGMainDisplayID = lambda: 1
    fake.CGDisplayPixelsWide = lambda d: screen[0]
    fake.CGDisplayPixelsHigh = lambda d: screen[1]
    fake.CGWindowListCopyWindowInfo = lambda opts, wid: windows
    return fake


def test_idle_seconds_non_darwin_is_zero(monkeypatch):
    monkeypatch.setattr(sensors.sys, "platform", "linux")
    assert sensors.idle_seconds() == 0.0


def test_idle_seconds_darwin_success(monkeypatch):
    monkeypatch.setitem(sys.modules, "Quartz", _fake_quartz_idle(42.5))
    monkeypatch.setattr(sensors.sys, "platform", "darwin")
    assert sensors.idle_seconds() == 42.5


def test_idle_seconds_failure_returns_zero(monkeypatch):
    fake = _fake_quartz_idle(0)
    def boom(*a, **k):
        raise RuntimeError("quartz boom")
    fake.CGEventSourceSecondsSinceLastEventType = boom
    monkeypatch.setitem(sys.modules, "Quartz", fake)
    monkeypatch.setattr(sensors.sys, "platform", "darwin")
    assert sensors.idle_seconds() == 0.0


def test_fullscreen_non_darwin_is_false(monkeypatch):
    monkeypatch.setattr(sensors.sys, "platform", "linux")
    assert sensors.frontmost_is_fullscreen() is False


def test_fullscreen_true_when_window_covers_screen(monkeypatch):
    win = {"kCGWindowLayer": 0, "kCGWindowBounds": {"Width": 1920, "Height": 1080}}
    monkeypatch.setitem(sys.modules, "Quartz", _fake_quartz_windows([win]))
    monkeypatch.setattr(sensors.sys, "platform", "darwin")
    assert sensors.frontmost_is_fullscreen() is True


def test_fullscreen_false_for_small_window(monkeypatch):
    win = {"kCGWindowLayer": 0, "kCGWindowBounds": {"Width": 800, "Height": 600}}
    monkeypatch.setitem(sys.modules, "Quartz", _fake_quartz_windows([win]))
    monkeypatch.setattr(sensors.sys, "platform", "darwin")
    assert sensors.frontmost_is_fullscreen() is False


def test_read_context_combines_sensors(monkeypatch):
    monkeypatch.setattr(sensors, "idle_seconds", lambda: 12.0)
    monkeypatch.setattr(sensors, "frontmost_is_fullscreen", lambda: True)
    c = sensors.read_context()
    assert c.idle_seconds == 12.0 and c.is_fullscreen is True

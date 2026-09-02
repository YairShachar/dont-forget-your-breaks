import struct
import sys
import types

import dfyb.activity.sensors as sensors


def _fake_quartz_idle(value):
    fake = types.ModuleType("Quartz")
    fake.kCGEventSourceStateHIDSystemState = 1
    fake.kCGAnyInputEventType = 0xFFFFFFFF
    fake.CGEventSourceSecondsSinceLastEventType = lambda state, evtype: value
    return fake


class _FakeBounds:
    """Stand-in for a Quartz CGRect: .origin.x/.y and .size.width/.height."""
    def __init__(self, x, y, w, h):
        self.origin = types.SimpleNamespace(x=x, y=y)
        self.size = types.SimpleNamespace(width=w, height=h)


def _fake_quartz_windows(windows, displays=((0, 0, 1920, 1080),)):
    fake = types.ModuleType("Quartz")
    fake.kCGWindowListOptionOnScreenOnly = 1
    fake.kCGWindowListExcludeDesktopElements = 16
    fake.kCGNullWindowID = 0
    fake.CGWindowListCopyWindowInfo = lambda opts, wid: windows
    display_ids = list(range(1, len(displays) + 1))
    fake.CGGetActiveDisplayList = lambda maxd, a, b: (0, display_ids, len(displays))
    fake.CGDisplayBounds = lambda did: _FakeBounds(*displays[did - 1])
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


def test_fullscreen_failure_returns_false(monkeypatch):
    fake = _fake_quartz_windows([])
    def boom(*a, **k):
        raise RuntimeError("quartz boom")
    fake.CGGetActiveDisplayList = boom
    monkeypatch.setitem(sys.modules, "Quartz", fake)
    monkeypatch.setattr(sensors.sys, "platform", "darwin")
    assert sensors.frontmost_is_fullscreen() is False


def test_read_context_combines_sensors(monkeypatch):
    monkeypatch.setattr(sensors, "idle_seconds", lambda: 12.0)
    monkeypatch.setattr(sensors, "frontmost_is_fullscreen", lambda: True)
    monkeypatch.setattr(sensors, "microphone_in_use", lambda: False)
    c = sensors.read_context()
    assert c.idle_seconds == 12.0 and c.is_fullscreen is True


def test_microphone_in_use_non_darwin_is_false(monkeypatch):
    monkeypatch.setattr(sensors.sys, "platform", "linux")
    assert sensors.microphone_in_use() is False


# --- any_input_device_running: mic-in-use across ALL devices, not just default (#40) ---

def test_no_devices_means_mic_free():
    assert sensors.any_input_device_running([]) is False


def test_input_device_running_means_mic_in_use():
    # (has_input, is_running) — a non-default input device is the one running.
    assert sensors.any_input_device_running([(False, False), (True, True)]) is True


def test_only_output_running_is_not_mic_in_use():
    # playing music (an OUTPUT device running) must NOT read as a mic in use.
    assert sensors.any_input_device_running([(False, True), (True, False)]) is False


def test_input_devices_idle_means_mic_free():
    assert sensors.any_input_device_running([(True, False), (True, False)]) is False


def test_read_context_meeting_gated_off(monkeypatch):
    monkeypatch.setattr(sensors, "idle_seconds", lambda: 0.0)
    monkeypatch.setattr(sensors, "frontmost_is_fullscreen", lambda: False)
    monkeypatch.setattr(sensors, "microphone_in_use", lambda: True)
    c = sensors.read_context(check_meeting=False)
    assert c.is_meeting is False


def test_read_context_meeting_on(monkeypatch):
    monkeypatch.setattr(sensors, "idle_seconds", lambda: 0.0)
    monkeypatch.setattr(sensors, "frontmost_is_fullscreen", lambda: False)
    monkeypatch.setattr(sensors, "microphone_in_use", lambda: True)
    c = sensors.read_context(check_meeting=True)
    assert c.is_meeting is True


# --- covers_any_display: pure multi-monitor fullscreen logic ---
# Real geometry captured from a dual-monitor Mac (main + smaller offset second).
MAIN_DISPLAY = (0, 0, 1920, 1080)
SECOND_DISPLAY = (1920, 64, 1512, 982)
DISPLAYS = [MAIN_DISPLAY, SECOND_DISPLAY]


def test_covers_fullscreen_on_main_display():
    windows = [(0, 0, 1920, 1080), (2302, 97, 1130, 949)]
    assert sensors.covers_any_display(windows, DISPLAYS) is True


def test_covers_fullscreen_on_secondary_display():
    # Regression: native fullscreen on the smaller, offset second monitor used
    # to be missed because only the main display was checked.
    windows = [(1920, 64, 1512, 982), (0, 122, 1920, 958)]
    assert sensors.covers_any_display(windows, DISPLAYS) is True


def test_windowed_chrome_is_not_fullscreen():
    # Menu-bar-visible windowed content sits below y=0, so it covers nothing.
    windows = [(0, 0, 1920, 41), (0, 122, 1920, 958), (2302, 97, 1130, 949)]
    assert sensors.covers_any_display(windows, DISPLAYS) is False


def test_thin_bar_in_front_of_fullscreen_window_still_detected():
    # A thin auto-hide bar is frontmost; the real full window is later in the
    # list. Scanning all windows (not just the first) still detects fullscreen.
    windows = [(0, 0, 1920, 41), (0, 0, 1920, 1080)]
    assert sensors.covers_any_display(windows, DISPLAYS) is True


def test_covers_within_rounding_tolerance():
    assert sensors.covers_any_display([(0, 0, 1919, 1079)], [MAIN_DISPLAY]) is True


def test_no_windows_or_no_displays_is_false():
    assert sensors.covers_any_display([], DISPLAYS) is False
    assert sensors.covers_any_display([MAIN_DISPLAY], []) is False


def test_covers_multiwindow_fullscreen():
    # Real capture (#23): Chrome native fullscreen presents as several windows
    # — thin top strips at y=0 plus a content pane at y=122 — so NO single
    # window covers the display, but their full-width vertical extents union to
    # the full height. Must be detected as fullscreen.
    windows = [
        (0, 0, 1920, 41),       # top strip
        (0, 41, 1920, 81),      # strip filling 41..122
        (0, 0, 1920, 158),      # overlapping strip
        (0, 122, 1920, 958),    # content pane, reaches the bottom (1080)
        (2099, 97, 1333, 943),  # iTerm on the 2nd monitor (non-covering)
    ]
    assert sensors.covers_any_display(windows, DISPLAYS) is True


def test_maximized_window_with_top_gap_is_not_fullscreen():
    # A single maximized content window starting below the menu bar (y=122) with
    # NO top strip leaves the top uncovered -> not fullscreen.
    windows = [(0, 122, 1920, 958)]
    assert sensors.covers_any_display(windows, DISPLAYS) is False


def test_fullscreen_logic_is_resolution_independent():
    # Different hardware than the capture (a Retina main + a portrait, offset
    # second monitor) proves the detection is pure geometry, not tied to any
    # specific resolution or the machine it was diagnosed on.
    main = (0, 0, 2880, 1800)
    second = (2880, 0, 1080, 1920)  # portrait, different size + offset
    displays = [main, second]

    # split-window fullscreen on `main` (top strip 0..220 + content 200..1800)
    assert sensors.covers_any_display(
        [(0, 0, 2880, 220), (0, 200, 2880, 1600)], displays) is True
    # single-window fullscreen on the portrait second monitor
    assert sensors.covers_any_display([(2880, 0, 1080, 1920)], displays) is True
    # a maximized window on `main` (content only, top gap) is NOT fullscreen
    assert sensors.covers_any_display([(0, 200, 2880, 1600)], displays) is False


# --- active_idle_seconds: keyboard-primary pause (#41) ---

def _fake_quartz_per_type(values):
    fake = types.ModuleType("Quartz")
    fake.kCGEventSourceStateHIDSystemState = 1
    fake.kCGEventKeyDown = 10
    fake.kCGEventFlagsChanged = 12
    fake.kCGEventLeftMouseDown = 1
    fake.kCGEventRightMouseDown = 3
    fake.kCGEventScrollWheel = 22
    fake.kCGEventMouseMoved = 5
    fake.CGEventSourceSecondsSinceLastEventType = (
        lambda state, evtype: values.get(evtype, 999.0))
    return fake


def test_active_idle_excludes_mouse_move_by_default(monkeypatch):
    values = {10: 30, 12: 30, 1: 30, 3: 30, 22: 30, 5: 0.5}
    monkeypatch.setitem(sys.modules, "Quartz", _fake_quartz_per_type(values))
    monkeypatch.setattr(sensors.sys, "platform", "darwin")
    assert sensors.active_idle_seconds() == 30


def test_active_idle_includes_mouse_move_when_asked(monkeypatch):
    values = {10: 30, 12: 30, 1: 30, 3: 30, 22: 30, 5: 0.5}
    monkeypatch.setitem(sys.modules, "Quartz", _fake_quartz_per_type(values))
    monkeypatch.setattr(sensors.sys, "platform", "darwin")
    assert sensors.active_idle_seconds(include_mouse_move=True) == 0.5


def test_active_idle_is_min_over_meaningful_types(monkeypatch):
    values = {10: 30, 12: 40, 1: 5, 3: 50, 22: 20, 5: 1}
    monkeypatch.setitem(sys.modules, "Quartz", _fake_quartz_per_type(values))
    monkeypatch.setattr(sensors.sys, "platform", "darwin")
    assert sensors.active_idle_seconds() == 5  # the click


def test_active_idle_non_darwin_falls_back(monkeypatch):
    monkeypatch.setattr(sensors.sys, "platform", "linux")
    assert sensors.active_idle_seconds() == 0.0  # idle_seconds() on non-darwin


# --- smooth_signal: hysteresis over transient dropouts of any defer signal (#46/#84) ---

def test_smooth_signal_true_arms_full_grace():
    # a real observation resets the grace to the full window
    assert sensors.smooth_signal(True, 0, 3) == (True, 3)
    assert sensors.smooth_signal(True, 1, 3) == (True, 3)


def test_smooth_signal_false_within_grace_holds_true():
    # transient False (e.g. a Space-to-Space swipe, a mic-device blip) stays on
    assert sensors.smooth_signal(False, 3, 3) == (True, 2)
    assert sensors.smooth_signal(False, 1, 3) == (True, 0)


def test_smooth_signal_false_after_grace_is_false():
    assert sensors.smooth_signal(False, 0, 3) == (False, 0)


def test_smooth_signal_bridges_a_one_tick_gap():
    # sequence: on, then one transient dropout, then on again
    eff, grace = sensors.smooth_signal(True, 0, 3)
    assert eff is True
    eff, grace = sensors.smooth_signal(False, grace, 3)   # the dropout tick
    assert eff is True                                    # bridged, not fired
    eff, grace = sensors.smooth_signal(True, grace, 3)    # signal back
    assert eff is True and grace == 3


def test_smooth_signal_expires_after_grace_ticks():
    # after the last True, exactly grace_ticks of False stay True, then False
    _, grace = sensors.smooth_signal(True, 0, 2)
    eff, grace = sensors.smooth_signal(False, grace, 2)
    assert eff is True and grace == 1
    eff, grace = sensors.smooth_signal(False, grace, 2)
    assert eff is True and grace == 0
    eff, grace = sensors.smooth_signal(False, grace, 2)
    assert eff is False and grace == 0


def test_smooth_signal_default_grace_is_defer_grace_ticks():
    # default grace_ticks comes from the shared DEFER_GRACE_TICKS constant
    assert sensors.smooth_signal(True, 0) == (True, sensors.DEFER_GRACE_TICKS)


def test_read_context_fullscreen_gated_off(monkeypatch):
    monkeypatch.setattr(sensors, "idle_seconds", lambda: 0.0)
    monkeypatch.setattr(sensors, "frontmost_is_fullscreen", lambda: True)
    monkeypatch.setattr(sensors, "microphone_in_use", lambda: False)
    c = sensors.read_context(check_fullscreen=False)
    assert c.is_fullscreen is False


def test_read_context_fullscreen_on(monkeypatch):
    monkeypatch.setattr(sensors, "idle_seconds", lambda: 0.0)
    monkeypatch.setattr(sensors, "frontmost_is_fullscreen", lambda: True)
    monkeypatch.setattr(sensors, "microphone_in_use", lambda: False)
    c = sensors.read_context(check_fullscreen=True)
    assert c.is_fullscreen is True


# --- mic attribution: WHO is holding the microphone (#40) ---

def _fake_coreaudio_processes(process_objects, running_input, pids, list_ok=True):
    """Fake CoreAudio exposing the macOS 14+ process-object properties.
    `running_input` / `pids` map a process object id -> its property value."""
    fake = types.ModuleType("CoreAudio")
    fake.kAudioObjectSystemObject = 1
    fake.kAudioObjectPropertyScopeGlobal = 0x676C6F62
    fake.kAudioObjectPropertyScopeInput = 0x696E7074
    fake.kAudioObjectPropertyElementMain = 0
    fake.AudioObjectPropertyAddress = lambda sel, scope, elem: (sel, scope, elem)

    def get_size(obj, addr, qsize, qdata, out):
        if not list_ok:
            return (-1, 0)
        return (0, len(process_objects) * 4)

    def get_data(obj, addr, qsize, qdata, size, out):
        sel = addr[0]
        if obj == fake.kAudioObjectSystemObject:
            return (0, size, struct.pack("%dI" % len(process_objects), *process_objects))
        table = running_input if sel == sensors.PROCESS_IS_RUNNING_INPUT else pids
        return (0, 4, struct.pack("I", table.get(obj, 0)))

    fake.AudioObjectGetPropertyDataSize = get_size
    fake.AudioObjectGetPropertyData = get_data
    return fake


def _install_mic_process_fakes(monkeypatch, fake_ca, identities):
    monkeypatch.setattr(sensors.sys, "platform", "darwin")
    monkeypatch.setitem(sys.modules, "CoreAudio", fake_ca)
    monkeypatch.setitem(sys.modules, "objc", types.SimpleNamespace(NULL=None))
    monkeypatch.setattr(sensors, "_app_identity", lambda pid: identities[pid])


def test_mic_input_processes_names_the_holder(monkeypatch):
    fake = _fake_coreaudio_processes(
        process_objects=[10, 11], running_input={10: 1, 11: 0}, pids={10: 700, 11: 800})
    _install_mic_process_fakes(monkeypatch, fake, {700: ("us.zoom.xos", "zoom.us")})
    assert sensors.mic_input_processes() == [(700, "us.zoom.xos", "zoom.us")]


def test_mic_input_processes_empty_when_nobody_holds_input(monkeypatch):
    fake = _fake_coreaudio_processes(
        process_objects=[10], running_input={10: 0}, pids={10: 700})
    _install_mic_process_fakes(monkeypatch, fake, {})
    # [] (asked, nobody there) — NOT None, which would mean "couldn't ask".
    assert sensors.mic_input_processes() == []


def test_mic_input_processes_none_when_api_unavailable(monkeypatch):
    fake = _fake_coreaudio_processes([], {}, {}, list_ok=False)
    _install_mic_process_fakes(monkeypatch, fake, {})
    assert sensors.mic_input_processes() is None


def test_mic_input_processes_none_on_exception(monkeypatch):
    fake = _fake_coreaudio_processes([10], {10: 1}, {10: 700})
    def boom(*a, **k):
        raise RuntimeError("coreaudio boom")
    fake.AudioObjectGetPropertyDataSize = boom
    _install_mic_process_fakes(monkeypatch, fake, {})
    assert sensors.mic_input_processes() is None


def test_mic_input_processes_none_off_macos(monkeypatch):
    monkeypatch.setattr(sensors.sys, "platform", "linux")
    assert sensors.mic_input_processes() is None

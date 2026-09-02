import plistlib
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
    monkeypatch.setattr(sensors, "fullscreen_state", lambda: (True, None))
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
    monkeypatch.setattr(sensors, "fullscreen_state", lambda: (False, None))
    monkeypatch.setattr(sensors, "microphone_in_use", lambda: True)
    c = sensors.read_context(check_meeting=False)
    assert c.is_meeting is False


def test_read_context_meeting_on(monkeypatch):
    monkeypatch.setattr(sensors, "idle_seconds", lambda: 0.0)
    monkeypatch.setattr(sensors, "fullscreen_state", lambda: (False, None))
    monkeypatch.setattr(sensors, "microphone_in_use", lambda: True)
    monkeypatch.setattr(sensors, "mic_input_processes", lambda: None)
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
    monkeypatch.setattr(sensors, "fullscreen_state", lambda: (True, None))
    monkeypatch.setattr(sensors, "microphone_in_use", lambda: False)
    c = sensors.read_context(check_fullscreen=False)
    assert c.is_fullscreen is False


def test_read_context_fullscreen_on(monkeypatch):
    monkeypatch.setattr(sensors, "idle_seconds", lambda: 0.0)
    monkeypatch.setattr(sensors, "fullscreen_state", lambda: (True, None))
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


# --- _bundle_identity_from_path: the bundle walk that turns a bare pid into a
# name (#40) — this is the novel, risky part of mic attribution: it is what
# turned "pid 12345" into "Sound" during the 2026-09-01 incident. ---

def _write_plist(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        plistlib.dump(data, f)


def test_bundle_identity_from_appex_info_plist(tmp_path):
    # Real values captured from this machine's actual Sound.appex — pins the
    # exact case that caused the 18-hour false-positive incident (#40).
    bundle = tmp_path / "Sound.appex"
    _write_plist(bundle / "Contents" / "Info.plist", {
        "CFBundleIdentifier": "com.apple.Sound-Settings.extension",
        "CFBundleName": "Sound",
    })
    exe = bundle / "Contents" / "MacOS" / "Sound"
    assert sensors._bundle_identity_from_path(str(exe)) == (
        "com.apple.Sound-Settings.extension", "Sound")


def test_bundle_identity_from_app_info_plist(tmp_path):
    # The .app suffix branch, not just .appex.
    bundle = tmp_path / "Zoom.app"
    _write_plist(bundle / "Contents" / "Info.plist", {
        "CFBundleIdentifier": "us.zoom.xos", "CFBundleName": "zoom.us"})
    exe = bundle / "Contents" / "MacOS" / "zoom.us"
    assert sensors._bundle_identity_from_path(str(exe)) == ("us.zoom.xos", "zoom.us")


def test_bundle_identity_no_enclosing_bundle_is_bare_daemon():
    # A path with no .app/.appex ancestor at all — a bare daemon.
    assert sensors._bundle_identity_from_path("/usr/sbin/corespeechd") == (
        None, "corespeechd")


def test_bundle_identity_missing_info_plist_falls_back(tmp_path):
    # Bundle directory exists but Info.plist does not -> the except branch,
    # not a raise. Falls back to the basename of the ORIGINAL exe path.
    bundle = tmp_path / "Broken.app"
    (bundle / "Contents").mkdir(parents=True)
    exe = bundle / "Contents" / "MacOS" / "Broken"
    assert sensors._bundle_identity_from_path(str(exe)) == (None, "Broken")


def test_bundle_identity_missing_bundle_name_uses_dir_basename(tmp_path):
    bundle = tmp_path / "NoName.appex"
    _write_plist(bundle / "Contents" / "Info.plist", {
        "CFBundleIdentifier": "com.example.noname"})  # no CFBundleName
    exe = bundle / "Contents" / "MacOS" / "NoName"
    assert sensors._bundle_identity_from_path(str(exe)) == (
        "com.example.noname", "NoName.appex")


# --- fullscreen attribution: WHO covers the display (#40/#28) ---
# owned windows are (rect, pid, owner_name)

def test_covering_owners_names_a_single_window_fullscreen():
    owned = [((0, 0, 1920, 1080), 700, "Google Chrome")]
    assert sensors.covering_owners(owned, [MAIN_DISPLAY]) == [(700, "Google Chrome")]


def test_covering_owners_names_the_largest_area_for_multiwindow_fullscreen():
    # The real #23 capture: strips + a content pane, all Chrome.
    owned = [((0, 0, 1920, 41), 700, "Google Chrome"),
             ((0, 41, 1920, 81), 700, "Google Chrome"),
             ((0, 122, 1920, 958), 700, "Google Chrome")]
    assert sensors.covering_owners(owned, [MAIN_DISPLAY]) == [(700, "Google Chrome")]


def test_covering_owners_does_not_let_a_thin_overlay_steal_the_name():
    # A menu-bar utility's full-width strip sits in front of the fullscreen app;
    # the content pane owns far more area, so the app is still named.
    owned = [((0, 0, 1920, 41), 999, "Bartender"),
             ((0, 0, 1920, 1080), 700, "Google Chrome")]
    assert sensors.covering_owners(owned, [MAIN_DISPLAY]) == [(700, "Google Chrome")]


def test_covering_owners_is_empty_when_nothing_covers():
    owned = [((0, 122, 1920, 958), 700, "Google Chrome")]
    assert sensors.covering_owners(owned, [MAIN_DISPLAY]) == []


def test_covering_owners_reports_one_entry_per_covered_display():
    owned = [((0, 0, 1920, 1080), 700, "Google Chrome"),
             ((1920, 64, 1512, 982), 800, "Keynote")]
    assert sensors.covering_owners(owned, DISPLAYS) == [
        (700, "Google Chrome"), (800, "Keynote")]


def test_fullscreen_state_off_macos_is_not_fullscreen_and_unattributable(monkeypatch):
    monkeypatch.setattr(sensors.sys, "platform", "linux")
    assert sensors.fullscreen_state() == (False, None)


# --- read_context with attribution + ignore lists ---

SOUND_HOLDER = (45648, "com.apple.Sound-Settings.extension", "Sound")
ZOOM_HOLDER = (700, "us.zoom.xos", "Zoom")


def _stub_context_sensors(monkeypatch, *, mic_on=False, holders=None,
                          covered=False, owners=None):
    monkeypatch.setattr(sensors, "idle_seconds", lambda: 0.0)
    monkeypatch.setattr(sensors, "active_idle_seconds",
                        lambda include_mouse_move=False: 0.0)
    monkeypatch.setattr(sensors, "microphone_in_use", lambda: mic_on)
    monkeypatch.setattr(sensors, "mic_input_processes", lambda: holders)
    monkeypatch.setattr(sensors, "fullscreen_state", lambda: (covered, owners))


def test_ignored_sound_pane_alone_is_not_a_meeting(monkeypatch):
    # REGRESSION for the 2026-09-01 incident: the System Settings Sound pane held
    # the input for 18h and every break was deferred as "you're in a call".
    from dfyb.activity import app_rules
    _stub_context_sensors(monkeypatch, mic_on=True, holders=[SOUND_HOLDER])
    ignores = app_rules.effective_ignores(app_rules.DEFAULT_MIC_IGNORED_APPS, [], [])
    ctx = sensors.read_context(mic_ignores=ignores)
    assert ctx.is_meeting is False and ctx.meeting_app is None


def test_a_real_call_alongside_an_ignored_holder_still_defers(monkeypatch):
    from dfyb.activity import app_rules
    _stub_context_sensors(monkeypatch, mic_on=True,
                          holders=[SOUND_HOLDER, ZOOM_HOLDER])
    ignores = app_rules.effective_ignores(app_rules.DEFAULT_MIC_IGNORED_APPS, [], [])
    ctx = sensors.read_context(mic_ignores=ignores)
    assert ctx.is_meeting is True
    assert ctx.meeting_app == {"id": "us.zoom.xos", "name": "Zoom", "count": 1}


def test_unattributable_mic_falls_back_to_the_device_signal(monkeypatch):
    # macOS 13 / CoreAudio failure: holders is None -> trust the device gate,
    # defer as before, just without a name.
    _stub_context_sensors(monkeypatch, mic_on=True, holders=None)
    ctx = sensors.read_context(mic_ignores=frozenset({"us.zoom.xos"}))
    assert ctx.is_meeting is True and ctx.meeting_app is None


def test_device_gate_off_means_no_enumeration(monkeypatch):
    calls = []
    _stub_context_sensors(monkeypatch, mic_on=False)
    monkeypatch.setattr(sensors, "mic_input_processes",
                        lambda: calls.append(1) or [])
    ctx = sensors.read_context()
    assert ctx.is_meeting is False and calls == []


def test_ignored_fullscreen_app_does_not_defer(monkeypatch):
    _stub_context_sensors(monkeypatch, covered=True,
                          owners=[(900, "com.apple.Terminal", "Terminal")])
    ctx = sensors.read_context(fullscreen_ignores=frozenset({"com.apple.terminal"}))
    assert ctx.is_fullscreen is False and ctx.fullscreen_app is None


def test_second_display_covered_by_another_app_still_defers(monkeypatch):
    _stub_context_sensors(monkeypatch, covered=True,
                          owners=[(900, "com.apple.Terminal", "Terminal"),
                                  (800, "com.apple.iWork.Keynote", "Keynote")])
    ctx = sensors.read_context(fullscreen_ignores=frozenset({"com.apple.terminal"}))
    assert ctx.is_fullscreen is True
    assert ctx.fullscreen_app == {"id": "com.apple.iWork.Keynote",
                                  "name": "Keynote", "count": 1}


def test_unattributable_fullscreen_falls_back_to_the_boolean(monkeypatch):
    _stub_context_sensors(monkeypatch, covered=True, owners=None)
    ctx = sensors.read_context(fullscreen_ignores=frozenset({"com.apple.terminal"}))
    assert ctx.is_fullscreen is True and ctx.fullscreen_app is None


def test_gates_still_win_over_attribution(monkeypatch):
    _stub_context_sensors(monkeypatch, mic_on=True, holders=[ZOOM_HOLDER],
                          covered=True, owners=[(800, "x", "Keynote")])
    ctx = sensors.read_context(check_meeting=False, check_fullscreen=False)
    assert (ctx.is_meeting, ctx.meeting_app) == (False, None)
    assert (ctx.is_fullscreen, ctx.fullscreen_app) == (False, None)


def test_running_gui_apps_off_macos_is_empty(monkeypatch):
    monkeypatch.setattr(sensors.sys, "platform", "linux")
    assert sensors.running_gui_apps() == []


def test_running_gui_apps_sorted_and_regular_only(monkeypatch):
    class _App:
        def __init__(self, policy, bundle, name):
            self._p, self._b, self._n = policy, bundle, name
        def activationPolicy(self):
            return self._p
        def bundleIdentifier(self):
            return self._b
        def localizedName(self):
            return self._n

    fake_workspace = types.SimpleNamespace(
        sharedWorkspace=lambda: types.SimpleNamespace(
            runningApplications=lambda: [
                _App(0, "us.zoom.xos", "Zoom"),
                _App(1, "com.apple.dock", "Dock"),        # accessory -> filtered out
                _App(0, "com.apple.Safari", "Safari"),
            ]))
    monkeypatch.setattr(sensors.sys, "platform", "darwin")
    monkeypatch.setitem(sys.modules, "AppKit",
                        types.SimpleNamespace(NSWorkspace=fake_workspace,
                                              NSApplicationActivationPolicyRegular=0))
    assert sensors.running_gui_apps() == [("com.apple.Safari", "Safari"),
                                          ("us.zoom.xos", "Zoom")]

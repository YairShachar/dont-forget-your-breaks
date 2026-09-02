"""macOS context sensors (idle time, fullscreen) for the scheduler.

Best-effort: on non-macOS or any failure, returns safe defaults (idle=0.0,
fullscreen=False) so the scheduler falls back to today's 'always fire' behavior.
`Quartz` is imported lazily inside each function so this module imports cleanly
on non-macOS CI (where Quartz is absent).
"""
import logging
import struct
import sys

from dfyb.scheduler.engine import Context

# Max active displays to enumerate (well above any real Mac's monitor count).
MAX_DISPLAYS = 16
# Byte size of a CoreAudio UInt32 property value (matches the struct "I" format).
UINT32_SIZE = 4
# A window counts as covering a display if it reaches each edge within this many
# points — absorbs rounding between window bounds and display bounds.
FULLSCREEN_COVER_TOLERANCE_PX = 2
# Once a defer signal (fullscreen / mic-in-use / active-input) is really observed,
# keep treating it as present for this many subsequent ticks even if the raw signal
# drops out for a sample. Bridges brief dropouts — a Space-to-Space swipe hiding the
# covering window (#46), a per-utterance mic-device stop, a momentary typing pause —
# so a due break doesn't fire into the gap (#84).
DEFER_GRACE_TICKS = 3


def _fourcc(code):
    """CoreAudio selectors are four-character codes packed big-endian."""
    return struct.unpack(">I", code.encode())[0]


# Per-process CoreAudio selectors (macOS 14+). pyobjc's CoreAudio module does not
# export these as named constants, so they are built from the four-character codes
# exactly as AudioHardware.h defines them.
PROCESS_OBJECT_LIST = _fourcc("prs#")        # kAudioHardwarePropertyProcessObjectList
PROCESS_PID = _fourcc("ppid")                # kAudioProcessPropertyPID
PROCESS_IS_RUNNING_INPUT = _fourcc("piri")   # kAudioProcessPropertyIsRunningInput
# Max bytes for libproc's executable-path buffer (PROC_PIDPATHINFO_MAXSIZE).
PROC_PATH_MAX = 4096


def idle_seconds():
    """Seconds since the last user input event (macOS). 0.0 elsewhere / on failure."""
    if sys.platform != "darwin":
        return 0.0
    try:
        import Quartz
        return float(Quartz.CGEventSourceSecondsSinceLastEventType(
            Quartz.kCGEventSourceStateHIDSystemState,
            Quartz.kCGAnyInputEventType,
        ))
    except Exception:
        return 0.0


def _event_idle_seconds(Quartz, event_type):
    return float(Quartz.CGEventSourceSecondsSinceLastEventType(
        Quartz.kCGEventSourceStateHIDSystemState, event_type))


def active_idle_seconds(include_mouse_move=False):
    """Seconds since the last MEANINGFUL input for wait-until-you-pause:
    keyboard + clicks + scroll (+ mouse-move only if include_mouse_move). Bare
    cursor movement is excluded by default — it's noise, not 'busy working'.
    Falls back to idle_seconds() on non-macOS / failure (never worse than today).
    """
    if sys.platform != "darwin":
        return idle_seconds()
    try:
        import Quartz
        types = [Quartz.kCGEventKeyDown, Quartz.kCGEventFlagsChanged,
                 Quartz.kCGEventLeftMouseDown, Quartz.kCGEventRightMouseDown,
                 Quartz.kCGEventScrollWheel]
        if include_mouse_move:
            types.append(Quartz.kCGEventMouseMoved)
        return min(_event_idle_seconds(Quartz, t) for t in types)
    except Exception:
        return idle_seconds()


def _covers_interval(intervals, lo, hi, tol=FULLSCREEN_COVER_TOLERANCE_PX):
    """Do the (start, end) intervals union-cover [lo, hi]? Pure 1D coverage."""
    cursor = lo
    for start, end in sorted(intervals):
        if start > cursor + tol:
            return False  # gap before this interval -> not fully covered
        cursor = max(cursor, end)
        if cursor >= hi - tol:
            return True
    return cursor >= hi - tol


def _display_is_covered(windows, display, tol=FULLSCREEN_COVER_TOLERANCE_PX):
    """True if `windows` together cover `display` top to bottom.

    A native-fullscreen app can present as SEVERAL windows (e.g. thin auto-hide
    top strips at y=0 plus a content pane below them), so no single window fills
    the display — but the full-width windows' vertical extents union to the full
    height. This checks exactly that. A plain maximized window (content starting
    below the menu bar, with no top strip) leaves a top gap and is NOT counted.
    Each rect is (x, y, w, h) in global points.
    """
    dx, dy, dw, dh = display
    intervals = []
    for wx, wy, ww, wh in windows:
        spans_width = wx <= dx + tol and wx + ww >= dx + dw - tol
        if not spans_width:
            continue
        top = max(wy, dy)
        bottom = min(wy + wh, dy + dh)
        if bottom > top:
            intervals.append((top, bottom))
    return _covers_interval(intervals, dy, dy + dh, tol)


def covers_any_display(windows, displays, tol=FULLSCREEN_COVER_TOLERANCE_PX):
    """True if any display is fully covered (native fullscreen) by the windows.

    Handles fullscreen apps that split into a top strip + content pane, not just
    single-window fullscreen. Pure (no Quartz), so it is unit-tested off macOS."""
    return any(_display_is_covered(windows, d, tol) for d in displays)


def _active_display_rects(Quartz):
    """(x, y, w, h) in points for every active display."""
    _err, ids, count = Quartz.CGGetActiveDisplayList(MAX_DISPLAYS, None, None)
    rects = []
    for display_id in list(ids)[:count]:
        bounds = Quartz.CGDisplayBounds(display_id)
        rects.append((bounds.origin.x, bounds.origin.y,
                      bounds.size.width, bounds.size.height))
    return rects


def _layer0_window_rects(Quartz):
    """(x, y, w, h) in points for each on-screen normal (layer-0) window."""
    windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly
        | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID,
    )
    rects = []
    for window in windows:
        if window.get("kCGWindowLayer", 1) != 0:
            continue  # skip menu bar, dock, overlays — only normal app windows
        bounds = window.get("kCGWindowBounds", {})
        rects.append((bounds.get("X", 0.0), bounds.get("Y", 0.0),
                      bounds.get("Width", 0.0), bounds.get("Height", 0.0)))
    return rects


def frontmost_is_fullscreen():
    """Best-effort: is any app in native fullscreen on ANY display?

    True when a normal (layer-0) on-screen window fully covers one of the active
    displays — handles multiple monitors of different sizes and offsets, and a
    thin auto-hide bar sitting in front of the fullscreen window. False on
    non-macOS or any failure (fails safe — 'not fullscreen' => fire).
    """
    if sys.platform != "darwin":
        return False
    try:
        import Quartz
        displays = _active_display_rects(Quartz)
        windows = _layer0_window_rects(Quartz)
        return covers_any_display(windows, displays)
    except Exception:
        return False


def smooth_signal(raw_on, grace_left, grace_ticks=DEFER_GRACE_TICKS):
    """Hysteresis over transient dropouts of any boolean defer signal (fullscreen,
    mic-in-use, active-input).

    Pure and tick-based (no clock) so it is unit-tested off macOS. Once the signal
    is really observed, it 'sticks' for up to `grace_ticks` subsequent ticks even
    if the raw reading drops out. Returns (effective_on, new_grace_left); the caller
    carries `new_grace_left` into the next tick.
    """
    if raw_on:
        return True, grace_ticks
    if grace_left > 0:
        return True, grace_left - 1
    return False, 0


def any_input_device_running(device_states):
    """Given `(has_input, is_running)` per audio device, True if any INPUT-capable
    device is running — i.e. the mic is in use by some app, on ANY device (not
    just the system default). Pure; the CoreAudio enumeration builds the list.
    Output devices (music/speakers) must not count, hence the `has_input` gate."""
    return any(has_input and is_running for has_input, is_running in device_states)


def microphone_in_use():
    """True if any INPUT-capable audio device is running somewhere (~ a mic in a
    call/recording). Enumerates ALL devices, not just the system default input —
    a call routed through AirPods/a headset/another device was missed before (#40).
    False on non-macOS or any failure (fails safe)."""
    if sys.platform != "darwin":
        return False
    try:
        import CoreAudio as CA
        import objc

        def _addr(selector, scope=CA.kAudioObjectPropertyScopeGlobal):
            return CA.AudioObjectPropertyAddress(
                selector, scope, CA.kAudioObjectPropertyElementMain)

        def _is_running(device):
            # qualifier MUST be objc.NULL; out-param MUST be None (pyobjc allocates it).
            status, _size, data = CA.AudioObjectGetPropertyData(
                device, _addr(CA.kAudioDevicePropertyDeviceIsRunningSomewhere),
                0, objc.NULL, UINT32_SIZE, None)
            return status == 0 and struct.unpack("I", bytes(data))[0] != 0

        def _has_input(device):
            # An input-capable device has ≥1 input stream (bytes > 0 in input scope).
            status, size = CA.AudioObjectGetPropertyDataSize(
                device, _addr(CA.kAudioDevicePropertyStreams,
                              CA.kAudioObjectPropertyScopeInput),
                0, objc.NULL, None)
            return status == 0 and size > 0

        status, size = CA.AudioObjectGetPropertyDataSize(
            CA.kAudioObjectSystemObject,
            _addr(CA.kAudioHardwarePropertyDevices), 0, objc.NULL, None)
        count = size // UINT32_SIZE
        if status != 0 or count <= 0:
            return False
        status, _size, raw = CA.AudioObjectGetPropertyData(
            CA.kAudioObjectSystemObject, _addr(CA.kAudioHardwarePropertyDevices),
            0, objc.NULL, size, None)
        if status != 0:
            return False
        device_ids = struct.unpack("%dI" % count, bytes(raw)[:count * UINT32_SIZE])

        return any_input_device_running(
            [(_has_input(d), _is_running(d)) for d in device_ids])
    except Exception as e:
        # Was failing SILENTLY to "no mic" — log so this class of miss is visible.
        logging.debug("microphone_in_use() failed, assuming mic free: %s", e)
        return False


def _bundle_identity_from_path(exe_path):
    """(bundle_id, name) for the .app/.appex enclosing `exe_path`, else (None, basename).

    NSRunningApplication returns None for non-GUI processes (daemons, app
    extensions), which is exactly the class of process that causes false
    'in a call' readings — so the enclosing bundle's Info.plist is read directly.
    """
    import os
    import plistlib
    part = exe_path
    while part and part != "/":
        if part.endswith(".app") or part.endswith(".appex"):
            try:
                with open(os.path.join(part, "Contents", "Info.plist"), "rb") as f:
                    info = plistlib.load(f)
                return (info.get("CFBundleIdentifier"),
                        info.get("CFBundleName") or os.path.basename(part))
            except Exception:
                break
        part = os.path.dirname(part)
    return None, os.path.basename(exe_path)


def _app_identity(pid):
    """(bundle_id | None, display_name) for a pid. Never raises.

    GUI apps resolve through NSRunningApplication; everything else falls back to
    libproc's executable path and the enclosing bundle, so an .appex still gets a
    real name ('Sound') instead of a bare pid.
    """
    import os
    try:
        from AppKit import NSRunningApplication
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is not None:
            return app.bundleIdentifier(), (app.localizedName() or str(pid))
    except Exception:
        pass
    try:
        import ctypes
        libc = ctypes.CDLL("/usr/lib/libSystem.dylib")
        buf = ctypes.create_string_buffer(PROC_PATH_MAX)
        if libc.proc_pidpath(pid, buf, PROC_PATH_MAX) > 0:
            return _bundle_identity_from_path(buf.value.decode("utf-8", "replace"))
    except Exception:
        pass
    return None, "pid %d" % pid


def mic_input_processes():
    """Which processes are running audio INPUT right now.

    Returns [(pid, bundle_id, name), …], or **None when attribution is
    unavailable** (non-macOS, macOS < 14, or any failure). The None/[] distinction
    is load-bearing: [] means 'asked, nobody holds the mic'; None means 'could not
    ask', and the caller must then fall back to the device-level boolean.

    Named seam for other platforms: a Windows/Linux implementation would return
    the same shape from its own audio stack; today they get None.
    """
    if sys.platform != "darwin":
        return None
    try:
        import CoreAudio as CA
        import objc

        def addr(selector):
            return CA.AudioObjectPropertyAddress(
                selector, CA.kAudioObjectPropertyScopeGlobal,
                CA.kAudioObjectPropertyElementMain)

        def u32(obj, selector):
            status, _size, data = CA.AudioObjectGetPropertyData(
                obj, addr(selector), 0, objc.NULL, UINT32_SIZE, None)
            if status != 0:
                return None
            return struct.unpack("I", bytes(data))[0]

        status, size = CA.AudioObjectGetPropertyDataSize(
            CA.kAudioObjectSystemObject, addr(PROCESS_OBJECT_LIST), 0, objc.NULL, None)
        if status != 0:
            return None            # macOS < 14 — the property does not exist
        count = size // UINT32_SIZE
        if count <= 0:
            return []
        status, _size, raw = CA.AudioObjectGetPropertyData(
            CA.kAudioObjectSystemObject, addr(PROCESS_OBJECT_LIST),
            0, objc.NULL, size, None)
        if status != 0:
            return None
        holders = []
        for obj in struct.unpack("%dI" % count, bytes(raw)[:count * UINT32_SIZE]):
            if not u32(obj, PROCESS_IS_RUNNING_INPUT):
                continue
            pid = u32(obj, PROCESS_PID)
            if pid is None:
                continue
            bundle_id, name = _app_identity(pid)
            holders.append((pid, bundle_id, name))
        return holders
    except Exception as e:
        logging.debug("mic_input_processes() failed, attribution unavailable: %s", e)
        return None


def frontmost_window_rect():
    """(x, y, w, h) of the frontmost APPLICATION's frontmost on-screen layer-0
    window, in global top-left points. None on non-macOS / failure / none.

    Uses NSWorkspace.frontmostApplication() (the app you're working in — never
    Stage Manager / WindowManager) and matches its PID in the on-screen window
    list, so system overlays don't pollute the result. Only the resulting
    screen is used, so picking a minor window of that app is fine.
    """
    if sys.platform != "darwin":
        return None
    try:
        import Quartz
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return None
        pid = app.processIdentifier()
        windows = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID,
        )
        for window in windows:
            if window.get("kCGWindowLayer", 1) != 0:
                continue
            if window.get("kCGWindowOwnerPID") != pid:
                continue
            bounds = window.get("kCGWindowBounds", {})
            return (bounds.get("X", 0.0), bounds.get("Y", 0.0),
                    bounds.get("Width", 0.0), bounds.get("Height", 0.0))
        return None
    except Exception:
        return None


def read_context(check_meeting=True, check_fullscreen=True, count_mouse_move=False):
    """Snapshot the current context for the scheduler.

    `check_meeting` / `check_fullscreen` gate their signals (the app's
    `defer_during_meetings` / `defer_during_fullscreen` prefs): when False, that
    flag is always False regardless of the real state.
    """
    return Context(
        idle_seconds=idle_seconds(),
        is_fullscreen=check_fullscreen and frontmost_is_fullscreen(),
        is_meeting=check_meeting and microphone_in_use(),
        active_idle_seconds=active_idle_seconds(include_mouse_move=count_mouse_move),
    )

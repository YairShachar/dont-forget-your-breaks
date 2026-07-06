"""macOS context sensors (idle time, fullscreen) for the scheduler.

Best-effort: on non-macOS or any failure, returns safe defaults (idle=0.0,
fullscreen=False) so the scheduler falls back to today's 'always fire' behavior.
`Quartz` is imported lazily inside each function so this module imports cleanly
on non-macOS CI (where Quartz is absent).
"""
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


def microphone_in_use():
    """True if the default input device is running somewhere (~ mic in a call,
    incl. browser calls). False on non-macOS or any failure (fails safe)."""
    if sys.platform != "darwin":
        return False
    try:
        import CoreAudio as CA
        import objc

        def _get_u32(objid, selector):
            addr = CA.AudioObjectPropertyAddress(
                selector,
                CA.kAudioObjectPropertyScopeGlobal,
                CA.kAudioObjectPropertyElementMain,
            )
            # qualifier MUST be objc.NULL; out-param MUST be None (pyobjc allocates + returns it)
            status, _size, data = CA.AudioObjectGetPropertyData(
                objid, addr, 0, objc.NULL, UINT32_SIZE, None)
            if status != 0:
                return None
            return struct.unpack("I", bytes(data))[0]

        device = _get_u32(CA.kAudioObjectSystemObject,
                          CA.kAudioHardwarePropertyDefaultInputDevice)
        if not device:
            return False
        return bool(_get_u32(device, CA.kAudioDevicePropertyDeviceIsRunningSomewhere))
    except Exception:
        return False


def read_context(check_meeting=True):
    """Snapshot the current context for the scheduler.

    `check_meeting` gates the meeting signal (the app's `defer_during_meetings`
    pref): when False, is_meeting is always False regardless of the mic.
    """
    return Context(
        idle_seconds=idle_seconds(),
        is_fullscreen=frontmost_is_fullscreen(),
        is_meeting=check_meeting and microphone_in_use(),
    )

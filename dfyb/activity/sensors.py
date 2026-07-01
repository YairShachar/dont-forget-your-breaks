"""macOS context sensors (idle time, fullscreen) for the scheduler.

Best-effort: on non-macOS or any failure, returns safe defaults (idle=0.0,
fullscreen=False) so the scheduler falls back to today's 'always fire' behavior.
`Quartz` is imported lazily inside each function so this module imports cleanly
on non-macOS CI (where Quartz is absent).
"""
import sys

from dfyb.scheduler.engine import Context

# Max active displays to enumerate (well above any real Mac's monitor count).
MAX_DISPLAYS = 16
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


def _window_covers_display(window, display, tol=FULLSCREEN_COVER_TOLERANCE_PX):
    """True if `window` fully covers `display`. Each is an (x, y, w, h) rect in
    global points (top-left origin), so a fullscreen window sits exactly on the
    display it fills — this works for a smaller/offset second monitor too."""
    wx, wy, ww, wh = window
    dx, dy, dw, dh = display
    return (
        wx <= dx + tol
        and wy <= dy + tol
        and wx + ww >= dx + dw - tol
        and wy + wh >= dy + dh - tol
    )


def covers_any_display(windows, displays, tol=FULLSCREEN_COVER_TOLERANCE_PX):
    """True if any window fully covers any display — the multi-monitor native
    fullscreen heuristic. Pure (no Quartz), so it is unit-tested off macOS."""
    return any(
        _window_covers_display(window, display, tol)
        for window in windows
        for display in displays
    )


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


def read_context():
    """Snapshot the current context for the scheduler."""
    return Context(idle_seconds=idle_seconds(), is_fullscreen=frontmost_is_fullscreen())

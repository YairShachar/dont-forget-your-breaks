"""macOS context sensors (idle time, fullscreen) for the scheduler.

Best-effort: on non-macOS or any failure, returns safe defaults (idle=0.0,
fullscreen=False) so the scheduler falls back to today's 'always fire' behavior.
`Quartz` is imported lazily inside each function so this module imports cleanly
on non-macOS CI (where Quartz is absent).
"""
import sys

from dfyb.scheduler.engine import Context


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


def frontmost_is_fullscreen():
    """Best-effort: is the frontmost on-screen window covering the full display?

    False on non-macOS or any failure (fails safe — 'not fullscreen' => fire).
    Heuristic: the first layer-0 (normal app) window in front-to-back order whose
    bounds cover the main display is treated as fullscreen.
    """
    if sys.platform != "darwin":
        return False
    try:
        import Quartz
        display = Quartz.CGMainDisplayID()
        screen_w = Quartz.CGDisplayPixelsWide(display)
        screen_h = Quartz.CGDisplayPixelsHigh(display)
        windows = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID,
        )
        for window in windows:
            if window.get("kCGWindowLayer", 1) != 0:
                continue  # skip menu bar, dock, overlays — only normal app windows
            bounds = window.get("kCGWindowBounds", {})
            return (bounds.get("Width", 0) >= screen_w
                    and bounds.get("Height", 0) >= screen_h)
        return False
    except Exception:
        return False


def read_context():
    """Snapshot the current context for the scheduler."""
    return Context(idle_seconds=idle_seconds(), is_fullscreen=frontmost_is_fullscreen())

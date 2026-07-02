"""Make a Tk window non-intrusive on macOS: appear on the currently active
Space and float on top WITHOUT activating the app (which is what makes macOS
switch Spaces / steal focus).

Best-effort and platform-guarded, like dfyb/activity/sensors.py: a documented
no-op on non-macOS or on any failure, so callers never need to guard.
"""
import logging
import sys

# NSFloatingWindowLevel — above normal windows, no focus required. Hardcoding
# the numeric value avoids importing AppKit just to read the constant.
FLOATING_WINDOW_LEVEL = 3


def make_nonintrusive(window):
    """Float `window` (a Tk Toplevel) on the active Space without activating
    the app. macOS-only; a documented no-op on other platforms.

    Not implemented on Windows/Linux yet. A future implementation would:
      * Windows: SetWindowPos(HWND_TOPMOST) + WS_EX_NOACTIVATE extended style.
      * Linux/X11: _NET_WM_STATE_ABOVE + _NET_WM_STATE_SKIP_TASKBAR, no focus grab.
    """
    if sys.platform == "darwin":
        _make_nonintrusive_macos(window)


def _make_nonintrusive_macos(window):
    """Set the popup's NSWindow to join all Spaces + float, and order it front
    without activating. Any failure is swallowed (best-effort)."""
    try:
        from AppKit import (
            NSApplication,
            NSWindowCollectionBehaviorCanJoinAllSpaces,
        )

        app = NSApplication.sharedApplication()
        ns_window = _find_nswindow(window, app)
        if ns_window is None:
            return
        ns_window.setCollectionBehavior_(
            ns_window.collectionBehavior() | NSWindowCollectionBehaviorCanJoinAllSpaces
        )
        ns_window.setLevel_(FLOATING_WINDOW_LEVEL)
        ns_window.orderFrontRegardless()  # show on top WITHOUT activating the app
    except Exception:
        logging.debug("make_nonintrusive: no-op (macOS tweak failed)", exc_info=True)


def _find_nswindow(window, app):
    """Locate the NSWindow backing a Tk Toplevel by matching its title.

    Isolated so the (fragile) lookup strategy can be swapped without touching
    callers. Returns None if not found.
    """
    title = window.title()
    for ns_window in app.windows():
        if ns_window.title() == title:
            return ns_window
    return None

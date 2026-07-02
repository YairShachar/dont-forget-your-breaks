"""Pin a break popup to the active Space on macOS so it shows where the user is
looking WITHOUT switching Spaces (the multi-monitor #21 fix).

The caller handles visibility/focus (lift + focus_force); this module only makes
the window join the active Space and float above other windows, so activating it
doesn't drag the user to a different Space.

Best-effort and platform-guarded, like dfyb/activity/sensors.py: a no-op on
non-macOS or on any failure, so callers never need to guard.

Runs from a <Map> binding, not inline: Tk maps the window asynchronously on a
Cocoa VisibilityNotify, so the NSWindow isn't ready (or found) until then. The
<Map> handler runs before Tk's own activation, so the Space membership is set
before the window activates.
"""
import logging
import sys


def pin_to_active_space(window):
    """Make a Tk Toplevel appear on the active Space and float on top, without
    switching Spaces. Call once, right after creating the window. macOS-only.

    Not implemented on Windows/Linux yet. A future implementation would keep the
    window above others without a workspace switch:
      * Windows: SetWindowPos(HWND_TOPMOST).
      * Linux/X11: _NET_WM_STATE_ABOVE, no workspace change.
    """
    if sys.platform != "darwin":
        return
    try:
        window.bind("<Map>", _on_map_handler(window), add="+")
    except Exception:
        logging.debug("pin_to_active_space: setup failed", exc_info=True)


def _on_map_handler(window):
    """Build a <Map> handler that configures the NSWindow when the toplevel maps.
    Guards on the widget so child-widget Map events don't re-run it."""
    def _handle(event):
        if str(event.widget) == str(window):
            _configure_nswindow(window)
    return _handle


def _configure_nswindow(window):
    """Set the popup's NSWindow to join the active Space and float high, so
    activating it does not switch Spaces. Runs from <Map>. Best-effort."""
    try:
        from AppKit import (
            NSApplication,
            NSStatusWindowLevel,
            NSWindowCollectionBehaviorCanJoinAllSpaces,
            NSWindowCollectionBehaviorFullScreenAuxiliary,
            NSWindowCollectionBehaviorStationary,
        )

        app = NSApplication.sharedApplication()
        ns_window = _find_nswindow(window, app)
        if ns_window is None:
            return
        ns_window.setLevel_(NSStatusWindowLevel)
        ns_window.setCollectionBehavior_(
            ns_window.collectionBehavior()
            | NSWindowCollectionBehaviorCanJoinAllSpaces  # show on active Space, don't switch
            | NSWindowCollectionBehaviorFullScreenAuxiliary
            | NSWindowCollectionBehaviorStationary
        )
    except Exception:
        logging.debug("pin_to_active_space: NSWindow config failed", exc_info=True)


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

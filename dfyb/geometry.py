"""Pure screen-geometry helpers (no Tk dependency, so unit-testable)."""


def point_in_rect(px, py, x, y, w, h):
    """True if point (px, py) lies inside the rect at (x, y) of size w x h.

    Left/top edges are inclusive, right/bottom edges exclusive — matching how a
    widget occupies pixels [x, x+w). Used to tell whether the mouse pointer is
    still over a widget from raw screen coords, without relying on <Leave>
    events (which macOS drops when the pointer exits the window entirely).
    """
    return x <= px < x + w and y <= py < y + h

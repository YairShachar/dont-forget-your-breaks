"""Pure geometry for placing the break popup on a chosen screen.

No Tk, no macOS — every rect is (x, y, w, h) in global top-left points, so this
is unit-tested off-macOS (mirrors dfyb.activity.sensors.covers_any_display)."""
import re

# A Tk '+x+y' position, allowing the '+-100' form Tk uses for negative coordinates.
_POSITION_RE = re.compile(r"\+(-?\d+)\+(-?\d+)")


def screen_for_point(point, screens):
    """The screen rect containing `point=(px, py)`, or None if none does."""
    px, py = point
    for (sx, sy, sw, sh) in screens:
        if sx <= px < sx + sw and sy <= py < sy + sh:
            return (sx, sy, sw, sh)
    return None


def center_on_screen(screen_rect, w, h):
    """Top-left (x, y) that centers a `w`x`h` popup on `screen_rect`."""
    sx, sy, sw, sh = screen_rect
    return (sx + (sw - w) // 2, sy + (sh - h) // 2)


def main_window_geometry(w, h, mode, saved_position, screen, place=True):
    """Tk geometry string 'WxH[+x+y]' for the MAIN window at launch (#67).

    `mode` 'active' centers on `screen` (an (x, y, w, h) rect), overriding any saved
    position; when `screen` is None (non-macOS / detection failed) it falls back to
    the saved position, then to size-only. `mode` 'remembered' restores
    `saved_position` (e.g. '+100+200'), or size-only when there is none. Pure.

    Placement is a LAUNCH-time decision: pass `place=False` on a later refit (a
    snooze row or the update banner grew the window) to get size only, so Tk
    resizes in place instead of yanking a window the user has since moved.
    """
    if not place:
        return f"{w}x{h}"
    if mode == "active" and screen is not None:
        x, y = center_on_screen(screen, w, h)
        return f"{w}x{h}+{int(x)}+{int(y)}"
    if saved_position:
        return f"{w}x{h}{saved_position}"
    return f"{w}x{h}"


def clamp_onscreen(x, y, w, h, screen_rect):
    """Nudge (x, y) so the `w`x`h` popup stays fully within `screen_rect`."""
    sx, sy, sw, sh = screen_rect
    return (max(sx, min(x, sx + sw - w)), max(sy, min(y, sy + sh - h)))


def clamp_saved_position(w, h, position, screens):
    """A remembered '+x+y' main-window position, clamped fully onto a live screen.

    Keeps the window on whichever screen its top-left is on; when no screen holds
    it any more (monitor unplugged, resolution changed) it lands on the first
    screen — the primary, which `CGGetActiveDisplayList` returns first. Returns
    `position` untouched when it is unparseable or `screens` is empty (off-macOS
    or detection failed), so those paths behave exactly as before.
    """
    match = _POSITION_RE.fullmatch(position or "")
    if not match or not screens:
        return position
    x, y = int(match.group(1)), int(match.group(2))
    screen = screen_for_point((x, y), screens) or screens[0]
    cx, cy = clamp_onscreen(x, y, w, h, screen)
    return f"+{int(cx)}+{int(cy)}"

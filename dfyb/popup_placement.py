"""Pure geometry for placing the break popup on a chosen screen.

No Tk, no macOS — every rect is (x, y, w, h) in global top-left points, so this
is unit-tested off-macOS (mirrors dfyb.activity.sensors.covers_any_display)."""


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


def main_window_geometry(w, h, mode, saved_position, screen):
    """Tk geometry string 'WxH[+x+y]' for the MAIN window at launch (#67).

    `mode` 'active' centers on `screen` (an (x, y, w, h) rect), overriding any saved
    position; when `screen` is None (non-macOS / detection failed) it falls back to
    the saved position, then to size-only. `mode` 'remembered' restores
    `saved_position` (e.g. '+100+200'), or size-only when there is none. Pure.
    """
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

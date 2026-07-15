"""Anti-aliased circular progress ring for the break popup.

Tkinter's native Canvas arcs aren't anti-aliased (they look jagged), so the ring
is drawn with PIL at supersampled resolution and downscaled. Pure (no tk/ctk) —
returns a PIL image the caller wraps in a CTkImage.
"""
import math

from PIL import Image, ImageDraw


def ring_image(frac, size, ring_w, track_rgba, prog_rgba, ss=4):
    """A ring: full `track` circle with a `prog` arc from the top (12 o'clock)
    clockwise covering `frac` of the circle, with rounded end caps.

    frac is clamped to [0, 1]. `size`/`ring_w` are final (pre-supersample) px.
    """
    frac = max(0.0, min(1.0, frac))
    s = size * ss
    w = ring_w * ss
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    box = [w // 2, w // 2, s - w // 2, s - w // 2]
    d.arc(box, 0, 360, fill=track_rgba, width=w)
    if frac > 0:
        sweep = 360 * frac
        d.arc(box, -90, -90 + sweep, fill=prog_rgba, width=w)
        cx = cy = s / 2
        r = (s - w) / 2
        for ang in (-90, -90 + sweep):    # rounded end caps
            a = math.radians(ang)
            px, py = cx + r * math.cos(a), cy + r * math.sin(a)
            d.ellipse([px - w / 2, py - w / 2, px + w / 2, py + w / 2], fill=prog_rgba)
    return img.resize((size, size), Image.LANCZOS)

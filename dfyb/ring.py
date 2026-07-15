"""Anti-aliased circular progress ring for the break popup.

Tkinter's native Canvas arcs aren't anti-aliased (they look jagged), so the ring
is drawn with PIL at supersampled resolution and downscaled. Pure (no tk/ctk) —
returns a PIL image the caller wraps in a CTkImage.
"""
from PIL import Image, ImageDraw


def ring_image(frac, size, ring_w, track_rgba, prog_rgba, ss=4):
    """A ring: full `track` circle with a `prog` arc from the top (12 o'clock)
    clockwise covering `frac` of the circle. Flat arc ends (no end-cap dots).

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
        d.arc(box, -90, -90 + 360 * frac, fill=prog_rgba, width=w)
    return img.resize((size, size), Image.LANCZOS)

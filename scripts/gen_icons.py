"""Generate the bundled line-icon PNGs (light/dark) for the main-window rows.

Draws each icon supersampled, then downsamples with LANCZOS for clean anti-
aliasing. Icons are NEUTRAL ink (blue is reserved for actions), bold enough and
simple enough to read at the real ~20px chip size. The preview renders them at
that true size on a chip so legibility is judged honestly, not blown up.
Run: .venv/bin/python scripts/gen_icons.py
"""
import os
from PIL import Image, ImageDraw

RENDER = 480          # supersample resolution
OUT = 60              # final asset size (3x of the 20px display)
STROKE = 52           # bold stroke at RENDER res (~2.2px at 20px display)
LIGHT_INK = "#3A3A3C"  # icon color in LIGHT mode (dark ink on a light chip)
DARK_INK = "#C7C7CC"   # icon color in DARK mode (light ink on a dark chip)
CHIP_LIGHT = (236, 236, 238, 255)
CHIP_DARK = (58, 58, 60, 255)
ICON_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "icons")


def draw_eye(d, S, c, w):
    cx = cy = 0.5 * S
    R = 0.52 * S
    up = (cx, cy + 0.30 * S)   # upper lid: top arc of a circle centered below
    d.arc([up[0] - R, up[1] - R, up[0] + R, up[1] + R], 232, 308, fill=c, width=w)
    lo = (cx, cy - 0.30 * S)   # lower lid: bottom arc of a circle centered above
    d.arc([lo[0] - R, lo[1] - R, lo[0] + R, lo[1] + R], 52, 128, fill=c, width=w)
    pr = 0.12 * S              # bold filled pupil (simpler than a ring at small size)
    d.ellipse([cx - pr, cy - pr, cx + pr, cy + pr], fill=c)


def draw_mug(d, S, c, w):
    # Tapered cup body (trapezoid) + rim line -> unmistakably a cup, not a "D"
    body = [(0.26 * S, 0.28 * S), (0.56 * S, 0.28 * S),
            (0.51 * S, 0.72 * S), (0.31 * S, 0.72 * S)]
    d.polygon(body, outline=c, width=w)
    d.line([0.30 * S, 0.37 * S, 0.52 * S, 0.37 * S], fill=c, width=int(w * 0.8))  # rim
    hc, hr = (0.545 * S, 0.5 * S), 0.15 * S   # C-handle attached at the right edge
    d.arc([hc[0] - hr, hc[1] - hr, hc[0] + hr, hc[1] + hr], 305, 55, fill=c, width=w)


def draw_break(d, S, c, w):
    m = 0.16 * S
    d.ellipse([m, m, S - m, S - m], outline=c, width=w)
    for bx in (0.43 * S, 0.57 * S):
        d.line([bx, 0.39 * S, bx, 0.61 * S], fill=c, width=w)


ICONS = {"eye": draw_eye, "mug": draw_mug, "break": draw_break}


def render(fn, color):
    img = Image.new("RGBA", (RENDER, RENDER), (0, 0, 0, 0))
    fn(ImageDraw.Draw(img), RENDER, color, STROKE)
    return img.resize((OUT, OUT), Image.LANCZOS)


def rounded_chip(size, bg):
    chip = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(chip).rounded_rectangle([0, 0, size - 1, size - 1], radius=8, fill=bg)
    return chip


def main():
    os.makedirs(ICON_DIR, exist_ok=True)
    for name, fn in ICONS.items():
        render(fn, LIGHT_INK).save(os.path.join(ICON_DIR, f"{name}-light.png"))
        render(fn, DARK_INK).save(os.path.join(ICON_DIR, f"{name}-dark.png"))

    # Legibility preview: TRUE size (20px glyph on a 34px chip) + a zoom, one
    # theme-accurate band per row (light band on top, dark band below).
    chip_px, glyph_px, cell, cols = 34, 20, 150, len(ICONS)
    band_w, band_h = cell * cols, 120
    prev = Image.new("RGBA", (band_w, band_h * 2), (0, 0, 0, 0))
    bands = ((LIGHT_INK, CHIP_LIGHT, (245, 245, 247, 255)),
             (DARK_INK, CHIP_DARK, (28, 28, 30, 255)))
    for row, (ink, chip_bg, band_bg) in enumerate(bands):
        prev.paste(Image.new("RGBA", (band_w, band_h), band_bg), (0, row * band_h))
        for col, name in enumerate(ICONS):
            glyph = render(ICONS[name], ink)
            chip = rounded_chip(chip_px, chip_bg)
            chip.alpha_composite(glyph.resize((glyph_px, glyph_px), Image.LANCZOS),
                                 ((chip_px - glyph_px) // 2, (chip_px - glyph_px) // 2))
            x0, y0 = col * cell + 28, row * band_h + (band_h - chip_px) // 2
            prev.alpha_composite(chip, (x0, y0))                                  # true size
            prev.alpha_composite(glyph.resize((72, 72), Image.LANCZOS), (x0 + 48, y0 - 20))  # zoom
    preview = os.path.join(os.path.dirname(__file__), "_icon_preview.png")
    prev.convert("RGB").save(preview)
    print("wrote", len(ICONS) * 2, "icons to", os.path.abspath(ICON_DIR))
    print("preview:", os.path.abspath(preview))


if __name__ == "__main__":
    main()

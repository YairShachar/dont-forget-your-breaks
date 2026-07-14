"""Generate the bundled line-icon PNGs (light/dark) for the main-window rows.

Draws each icon supersampled, then downsamples with LANCZOS for clean anti-
aliasing. Two color variants per icon: light-mode accent and dark-mode accent.
Run: .venv/bin/python scripts/gen_icons.py
"""
import os
from PIL import Image, ImageDraw

RENDER = 480          # supersample resolution
OUT = 60              # final asset size (3x of the 20px display)
STROKE = 38           # stroke width at RENDER res
ACCENT_LIGHT = "#007AFF"
ACCENT_DARK = "#0A84FF"
ICON_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "icons")


def draw_eye(d, S, c, w):
    cx = cy = 0.5 * S
    R = 0.62 * S
    # upper lid: arc across the top of a circle centered below the eye
    up = (cx, cy + 0.44 * S)
    d.arc([up[0] - R, up[1] - R, up[0] + R, up[1] + R], 234, 306, fill=c, width=w)
    # lower lid: arc across the bottom of a circle centered above the eye
    lo = (cx, cy - 0.44 * S)
    d.arc([lo[0] - R, lo[1] - R, lo[0] + R, lo[1] + R], 54, 126, fill=c, width=w)
    ir = 0.15 * S
    d.ellipse([cx - ir, cy - ir, cx + ir, cy + ir], outline=c, width=w)
    pr = 0.055 * S
    d.ellipse([cx - pr, cy - pr, cx + pr, cy + pr], fill=c)


def draw_mug(d, S, c, w):
    left, right, top, bot = 0.24 * S, 0.56 * S, 0.30 * S, 0.74 * S
    d.rounded_rectangle([left, top, right, bot], radius=0.05 * S, outline=c, width=w)
    # inner rim line -> reads as a cup you look into
    d.line([left + 0.04 * S, top + 0.10 * S, right - 0.04 * S, top + 0.10 * S],
           fill=c, width=int(w * 0.7))
    # prominent C-handle attached at the body's right edge
    hc, hr = (0.48 * S, 0.52 * S), 0.17 * S
    d.arc([hc[0] - hr, hc[1] - hr, hc[0] + hr, hc[1] + hr], 302, 58, fill=c, width=w)


def draw_break(d, S, c, w):
    m = 0.15 * S
    d.ellipse([m, m, S - m, S - m], outline=c, width=w)
    for bx in (0.42 * S, 0.58 * S):
        d.line([bx, 0.38 * S, bx, 0.62 * S], fill=c, width=w)


ICONS = {"eye": draw_eye, "mug": draw_mug, "break": draw_break}


def render(fn, color):
    img = Image.new("RGBA", (RENDER, RENDER), (0, 0, 0, 0))
    fn(ImageDraw.Draw(img), RENDER, color, STROKE)
    return img.resize((OUT, OUT), Image.LANCZOS)


def main():
    os.makedirs(ICON_DIR, exist_ok=True)
    for name, fn in ICONS.items():
        render(fn, ACCENT_LIGHT).save(os.path.join(ICON_DIR, f"{name}-light.png"))
        render(fn, ACCENT_DARK).save(os.path.join(ICON_DIR, f"{name}-dark.png"))
    # inspection preview: icons enlarged on light + dark swatches
    pad, cell = 24, 140
    prev = Image.new("RGBA", (cell * 3 + pad * 2, cell * 2), (255, 255, 255, 255))
    dark = Image.new("RGBA", (prev.width, cell), (28, 28, 30, 255))
    prev.paste(dark, (0, cell))
    for col, name in enumerate(ICONS):
        for row, color in enumerate((ACCENT_LIGHT, ACCENT_DARK)):
            big = render(ICONS[name], color).resize((96, 96), Image.LANCZOS)
            prev.alpha_composite(big, (pad + col * cell + 22, row * cell + 22))
    # dev-only inspection image lives OUTSIDE the bundled asset dir
    preview = os.path.join(os.path.dirname(__file__), "_icon_preview.png")
    prev.convert("RGB").save(preview)
    print("wrote", len(ICONS) * 2, "icons to", os.path.abspath(ICON_DIR))
    print("preview:", os.path.abspath(preview))


if __name__ == "__main__":
    main()

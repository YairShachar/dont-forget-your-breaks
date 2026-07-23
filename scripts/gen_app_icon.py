"""Generate the macOS app icon (AppIcon.icns) — a white coffee cup on a warm
gradient squircle, matching the app's SF-Symbol aesthetic. macOS-only build step.

Run: .venv/bin/python scripts/gen_app_icon.py
Produces assets/AppIcon.icns (referenced by the PyInstaller spec) + a 1024 preview.
"""
import io
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
from gen_icons import render_symbol  # reuse the SF-Symbol renderer
from PIL import Image, ImageDraw

HERE = os.path.dirname(__file__)
ASSETS = os.path.join(HERE, "..", "assets")
ICNS_OUT = os.path.join(ASSETS, "AppIcon.icns")
PREVIEW = os.path.join(HERE, "_app_icon_preview.png")

CANVAS = 1024                 # full icon canvas
SQUIRCLE = 824                # Apple's Big Sur grid: art fills 824 of 1024
MARGIN = (CANVAS - SQUIRCLE) // 2
RADIUS = 185                  # ~Apple continuous-corner radius at this size
GLYPH_PX = 560                # white cup box (glyph ~80% of this after render pad)
SYMBOL = "cup.and.saucer.fill"
GRAD_TOP = (255, 183, 77)     # warm amber (top-left)
GRAD_BOTTOM = (245, 124, 0)   # deep orange (bottom-right)
ICONSET_SIZES = [16, 32, 128, 256, 512]   # each also emitted @2x


def diag_gradient(size, c1, c2, steps=160):
    """Smooth top-left→bottom-right gradient (rendered small, scaled up)."""
    small = Image.new("RGB", (steps, steps))
    px = small.load()
    for yy in range(steps):
        for xx in range(steps):
            t = (xx + yy) / (2 * (steps - 1))
            px[xx, yy] = tuple(int(c1[i] * (1 - t) + c2[i] * t) for i in range(3))
    return small.resize((size, size), Image.BILINEAR)


def build_1024():
    grad = diag_gradient(SQUIRCLE, GRAD_TOP, GRAD_BOTTOM)
    mask = Image.new("L", (SQUIRCLE, SQUIRCLE), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, SQUIRCLE - 1, SQUIRCLE - 1],
                                           radius=RADIUS, fill=255)
    squircle = Image.new("RGBA", (SQUIRCLE, SQUIRCLE), (0, 0, 0, 0))
    squircle.paste(grad, (0, 0), mask)

    glyph_png = render_symbol(SYMBOL, "#FFFFFF", px=GLYPH_PX)
    glyph = Image.open(io.BytesIO(bytes(glyph_png))).convert("RGBA")

    canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    canvas.alpha_composite(squircle, (MARGIN, MARGIN))
    canvas.alpha_composite(glyph, ((CANVAS - GLYPH_PX) // 2, (CANVAS - GLYPH_PX) // 2))
    return canvas


def main():
    os.makedirs(ASSETS, exist_ok=True)
    canvas = build_1024()
    canvas.convert("RGB").save(PREVIEW)

    iconset = os.path.join(ASSETS, "AppIcon.iconset")
    os.makedirs(iconset, exist_ok=True)
    for s in ICONSET_SIZES:
        canvas.resize((s, s), Image.LANCZOS).save(
            os.path.join(iconset, f"icon_{s}x{s}.png"))
        canvas.resize((s * 2, s * 2), Image.LANCZOS).save(
            os.path.join(iconset, f"icon_{s}x{s}@2x.png"))
    subprocess.run(["iconutil", "-c", "icns", iconset, "-o", ICNS_OUT], check=True)
    # tidy the intermediate iconset dir
    for f in os.listdir(iconset):
        os.remove(os.path.join(iconset, f))
    os.rmdir(iconset)
    print("wrote", os.path.abspath(ICNS_OUT))
    print("preview:", os.path.abspath(PREVIEW))


if __name__ == "__main__":
    main()

"""Generate the bundled row icons from Apple's SF Symbols (macOS-only build step).

Renders real SF Symbols tinted to neutral ink (blue is reserved for actions) into
portable PNGs the app loads via CTkImage at runtime — so runtime needs no pyobjc
for icons. The preview shows them at the TRUE chip size so legibility is honest.
Run on macOS: .venv/bin/python scripts/gen_icons.py
"""
import os

from AppKit import (NSImage, NSColor, NSImageSymbolConfiguration, NSBitmapImageRep,
                    NSGraphicsContext, NSCalibratedRGBColorSpace, NSBitmapImageFileTypePNG,
                    NSCompositingOperationSourceOver, NSCompositingOperationSourceAtop,
                    NSMakeRect, NSZeroRect, NSRectFillUsingOperation, NSFontWeightMedium)
from PIL import Image, ImageDraw

# file stem -> SF Symbol name
SYMBOLS = {"eye": "eye", "cup": "cup.and.saucer", "timer": "timer",
           "chevron": "chevron.down",
           "gear": "gearshape"}
LIGHT_INK = "#3A3A3C"   # dark ink for light mode
DARK_INK = "#C7C7CC"    # light ink for dark mode
CHIP_LIGHT = (236, 236, 238, 255)
CHIP_DARK = (58, 58, 60, 255)
OUT = 72                # 3x of the 24px display icon
POINT_SIZE = 40
ICON_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "icons")


def _rgb(hexcolor):
    h = hexcolor.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def render_symbol(symbol, hexcolor, px=OUT):
    base = NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol, None)
    if base is None:
        raise SystemExit(f"SF Symbol not found: {symbol}")
    cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_scale_(
        POINT_SIZE, NSFontWeightMedium, 3)
    img = base.imageWithSymbolConfiguration_(cfg)
    img.setTemplate_(True)

    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, px, px, 8, 4, True, False, NSCalibratedRGBColorSpace, 0, 0)
    ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(ctx)

    isz = img.size()
    pad = px * 0.1
    avail = px - 2 * pad
    scale = min(avail / isz.width, avail / isz.height)
    w, h = isz.width * scale, isz.height * scale
    img.drawInRect_fromRect_operation_fraction_(
        NSMakeRect((px - w) / 2, (px - h) / 2, w, h), NSZeroRect,
        NSCompositingOperationSourceOver, 1.0)
    r, g, b = _rgb(hexcolor)
    NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, 1.0).set()
    NSRectFillUsingOperation(NSMakeRect(0, 0, px, px), NSCompositingOperationSourceAtop)

    NSGraphicsContext.restoreGraphicsState()
    return rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})


def rounded_chip(size, bg):
    chip = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(chip).rounded_rectangle([0, 0, size - 1, size - 1], radius=9, fill=bg)
    return chip


def main():
    os.makedirs(ICON_DIR, exist_ok=True)
    for stem, symbol in SYMBOLS.items():
        for mode, ink in (("light", LIGHT_INK), ("dark", DARK_INK)):
            path = os.path.join(ICON_DIR, f"{stem}-{mode}.png")
            render_symbol(symbol, ink).writeToFile_atomically_(path, True)

    # Legibility preview: TRUE size (24px glyph on a 40px chip) + zoom, per theme band.
    chip_px, glyph_px, cell = 40, 24, 150
    band_w, band_h = cell * len(SYMBOLS), 130
    prev = Image.new("RGBA", (band_w, band_h * 2), (0, 0, 0, 0))
    for row, (mode, chip_bg, band_bg) in enumerate((
            ("light", CHIP_LIGHT, (245, 245, 247, 255)),
            ("dark", CHIP_DARK, (28, 28, 30, 255)))):
        prev.paste(Image.new("RGBA", (band_w, band_h), band_bg), (0, row * band_h))
        for col, stem in enumerate(SYMBOLS):
            glyph = Image.open(os.path.join(ICON_DIR, f"{stem}-{mode}.png")).convert("RGBA")
            chip = rounded_chip(chip_px, chip_bg)
            chip.alpha_composite(glyph.resize((glyph_px, glyph_px), Image.LANCZOS),
                                 ((chip_px - glyph_px) // 2, (chip_px - glyph_px) // 2))
            x0, y0 = col * cell + 28, row * band_h + (band_h - chip_px) // 2
            prev.alpha_composite(chip, (x0, y0))
            prev.alpha_composite(glyph.resize((72, 72), Image.LANCZOS), (x0 + 52, y0 - 16))
    preview = os.path.join(os.path.dirname(__file__), "_icon_preview.png")
    prev.convert("RGB").save(preview)
    print("wrote", len(SYMBOLS) * 2, "SF-Symbol icons to", os.path.abspath(ICON_DIR))
    print("preview:", os.path.abspath(preview))


if __name__ == "__main__":
    main()

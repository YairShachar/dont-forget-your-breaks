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

LIGHT_INK = "#3A3A3C"   # neutral dark ink for light mode
DARK_INK = "#C7C7CC"    # neutral light ink for dark mode
# stem -> (SF Symbol, light color, dark color). Break tiles use FILLED symbols in
# their accent color (blue/green/orange); UI glyphs (chevron/gear) stay neutral.
ICON_SPECS = {
    "eye":     ("eye.fill",            "#007AFF", "#0A84FF"),  # Micro tile — blue
    "cup":     ("cup.and.saucer.fill", "#34C759", "#30D158"),  # Normal tile — green
    "timer":   ("timer",               "#FF9500", "#FF9F0A"),  # fallback tile — orange
    "chevron": ("chevron.down",        LIGHT_INK, DARK_INK),   # UI glyph
    "gear":    ("gearshape.fill",      LIGHT_INK, DARK_INK),   # UI glyph
}
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
    for stem, (symbol, light, dark) in ICON_SPECS.items():
        for mode, color in (("light", light), ("dark", dark)):
            path = os.path.join(ICON_DIR, f"{stem}-{mode}.png")
            render_symbol(symbol, color).writeToFile_atomically_(path, True)

    # Preview: each icon at ~44px on a light + dark band so colors read honestly.
    stems = list(ICON_SPECS)
    cell, band_h = 96, 110
    band_w = cell * len(stems)
    prev = Image.new("RGBA", (band_w, band_h * 2), (0, 0, 0, 0))
    for row, (mode, band_bg) in enumerate((("light", (245, 245, 247, 255)),
                                           ("dark", (28, 28, 30, 255)))):
        prev.paste(Image.new("RGBA", (band_w, band_h), band_bg), (0, row * band_h))
        for col, stem in enumerate(stems):
            glyph = Image.open(os.path.join(ICON_DIR, f"{stem}-{mode}.png")).convert("RGBA")
            prev.alpha_composite(glyph.resize((44, 44), Image.LANCZOS),
                                 (col * cell + 26, row * band_h + (band_h - 44) // 2))
    preview = os.path.join(os.path.dirname(__file__), "_icon_preview.png")
    prev.convert("RGB").save(preview)
    print("wrote", len(ICON_SPECS) * 2, "SF-Symbol icons to", os.path.abspath(ICON_DIR))
    print("preview:", os.path.abspath(preview))


if __name__ == "__main__":
    main()

from pathlib import Path

from PIL import Image

ICON_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons"


def test_all_icon_variants_exist_and_open_rgba():
    for name in ("eye", "cup", "timer", "chevron", "gear"):
        for mode in ("light", "dark"):
            path = ICON_DIR / f"{name}-{mode}.png"
            assert path.exists(), f"missing icon {path}"
            with Image.open(path) as im:
                assert im.mode == "RGBA"
                assert im.size == (72, 72)

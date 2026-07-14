"""Pure design-token resolvers (no tk/ctk import — headless-testable).

Font optical split: SF Pro ships two optical sizes; the real crossover is 20pt
(<20 = Text, >=20 = Display). Colors may be a (light, dark) tuple; resolve_color
returns the concrete hex for code paths that compute on color (e.g. lerp_color).
"""
import sys

_TEXT_FAMILY_MAC = "SF Pro Text"
_DISPLAY_FAMILY_MAC = "SF Pro Display"
_FALLBACK_FAMILY = "Segoe UI"
FONT_DISPLAY_THRESHOLD = 20
_IS_DARWIN = sys.platform == "darwin"

# Host-resolved convenience constants: the families THIS machine actually uses.
FONT_FAMILY_TEXT = _TEXT_FAMILY_MAC if _IS_DARWIN else _FALLBACK_FAMILY
FONT_FAMILY_DISPLAY = _DISPLAY_FAMILY_MAC if _IS_DARWIN else _FALLBACK_FAMILY


def resolve_font_family(size, is_darwin=_IS_DARWIN):
    """Optical family for a point size: Display at/above the threshold, else Text.

    Selects family names from `is_darwin` (not a host-baked constant) so the
    non-darwin fallback is correct regardless of the machine running this.
    """
    if not is_darwin:
        return _FALLBACK_FAMILY
    return _DISPLAY_FAMILY_MAC if size >= FONT_DISPLAY_THRESHOLD else _TEXT_FAMILY_MAC


def resolve_color(value, appearance_mode):
    """Concrete hex for a token value.

    Tuples/lists are (light, dark); plain strings pass through. `appearance_mode`
    is ctk.get_appearance_mode() ('Light'/'Dark'); anything not 'light' resolves
    to the dark half.
    """
    if isinstance(value, (tuple, list)):
        return value[0] if str(appearance_mode).lower() == "light" else value[1]
    return value

from dfyb import theme
from dfyb.theme import resolve_font_family, resolve_color
from dfyb.animation import lerp_color


class TestResolveFontFamily:
    def test_display_size_on_mac_uses_display_family(self):
        assert resolve_font_family(48, is_darwin=True) == "SF Pro Display"

    def test_boundary_20_on_mac_uses_display_family(self):
        assert resolve_font_family(theme.FONT_DISPLAY_THRESHOLD, is_darwin=True) == "SF Pro Display"

    def test_below_threshold_on_mac_uses_text_family(self):
        assert resolve_font_family(19, is_darwin=True) == "SF Pro Text"
        assert resolve_font_family(13, is_darwin=True) == "SF Pro Text"

    def test_non_mac_always_segoe(self):
        assert resolve_font_family(48, is_darwin=False) == "Segoe UI"
        assert resolve_font_family(10, is_darwin=False) == "Segoe UI"


class TestResolveColor:
    def test_plain_string_passes_through(self):
        assert resolve_color("#0A84FF", "Dark") == "#0A84FF"

    def test_tuple_light_mode_returns_first(self):
        assert resolve_color(("#007AFF", "#0A84FF"), "Light") == "#007AFF"

    def test_tuple_light_mode_is_case_insensitive(self):
        assert resolve_color(("#007AFF", "#0A84FF"), "light") == "#007AFF"

    def test_tuple_dark_mode_returns_second(self):
        assert resolve_color(("#007AFF", "#0A84FF"), "Dark") == "#0A84FF"

    def test_tuple_non_light_defaults_to_dark(self):
        # ctk.get_appearance_mode() only ever returns "Light"/"Dark", but be defensive
        assert resolve_color(("#007AFF", "#0A84FF"), "System") == "#0A84FF"

    def test_list_treated_like_tuple(self):
        assert resolve_color(["#007AFF", "#0A84FF"], "Light") == "#007AFF"


class TestResolveColorFeedsLerp:
    """Guards the tuple-vs-string trap on the progress-bar blend (launch.py L498)."""

    def test_resolved_endpoints_lerp_in_both_modes(self):
        blue = ("#007AFF", "#0A84FF")
        green = ("#34C759", "#30D158")
        for mode in ("Light", "Dark"):
            a, b = resolve_color(blue, mode), resolve_color(green, mode)
            assert lerp_color(a, b, 0.0) == a.lower()
            assert lerp_color(a, b, 1.0) == b.lower()
            assert lerp_color(a, b, 0.5).startswith("#")  # no crash on tuple

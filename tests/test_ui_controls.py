from dfyb.ui_controls import reset_button_style

# Fake token map so the test needs no real COLORS / Tk.
COLORS = {"surface_hover": "H", "surface_card": "C",
          "text_secondary": "T2", "text_tertiary": "T3", "border": "B"}


def test_enabled_and_disabled_have_distinct_fill_and_text():
    en = reset_button_style(True, COLORS)
    dis = reset_button_style(False, COLORS)
    assert en["state"] == "normal" and dis["state"] == "disabled"
    assert en["fg_color"] != dis["fg_color"]      # visibly different fill
    assert en["text_color"] != dis["text_color"]  # and text contrast


def test_enabled_is_raised_readable_disabled_recedes():
    en = reset_button_style(True, COLORS)
    dis = reset_button_style(False, COLORS)
    assert en["fg_color"] == "H" and en["text_color"] == "T2"   # raised, readable
    assert dis["fg_color"] == "C" and dis["text_color"] == "T3"  # sunk into card, faded


def test_only_known_ctk_kwargs_returned():
    keys = set(reset_button_style(True, COLORS))
    assert keys == {"state", "fg_color", "text_color", "hover_color",
                    "border_width", "border_color"}


def test_enabled_is_outlined_disabled_is_flat():
    # the enabled button gets a visible border; disabled has none — a strong,
    # theme-independent affordance cue on top of the fill/text contrast (#70)
    assert reset_button_style(True, COLORS)["border_width"] > 0
    assert reset_button_style(False, COLORS)["border_width"] == 0

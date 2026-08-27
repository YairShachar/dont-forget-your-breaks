"""A wide scale (0–10) must wrap instead of running off the fixed-width popup.

Regression: the check-in popup is a fixed CHECK_IN_POPUP_W wide, but _build_scale
packed every value in ONE row. A 0–10 question wanted 604px in a 340px window, so
Tk squeezed buttons 6–10 down to 1px — the question rendered as "0–5".
"""
import json
import pytest

import launch


# ---- pure: how the values are split into rows ------------------------------

def test_a_short_scale_stays_on_one_row():
    assert launch.scale_button_rows(range(1, 6), 5) == [[1, 2, 3, 4, 5]]


def test_a_wide_scale_wraps_into_balanced_rows():
    # 11 values, at most 5 per row -> 3 rows, balanced 4/4/3 (not 5/5/1)
    assert launch.scale_button_rows(range(0, 11), 5) == [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10]]


def test_rows_never_exceed_the_maximum():
    for n in range(1, 40):
        rows = launch.scale_button_rows(range(n), 5)
        assert all(len(r) <= 5 for r in rows)
        assert [v for r in rows for v in r] == list(range(n))   # nothing lost or reordered


def test_no_values_means_no_rows():
    assert launch.scale_button_rows([], 5) == []


def test_the_row_limit_fits_the_popup_width():
    span = launch.CHECK_IN_SCALE_BTN_WIDTH + 2 * launch.SPACE_XXS
    usable = launch.CHECK_IN_POPUP_W - 2 * launch.PADDING_PANEL_X
    assert launch.CHECK_IN_SCALE_MAX_PER_ROW * span <= usable


# ---- the real popup: every value is actually visible ------------------------

tk = pytest.importorskip("tkinter")

WIDE_SCALE = {"id": "hours", "text": "How many hours did you sleep last night?",
              "enabled": True,
              "answer": {"type": "scale", "min": 0, "max": 10, "min_label": "",
                         "max_label": "", "allow_note": True},
              "cadence": {"type": "times_per_day", "count": 1}, "trigger": "break"}


def _popup(tmp_path, question):
    ctk = pytest.importorskip("customtkinter")
    from dfyb.checkins.model import parse_questions
    launch.CONFIG_FILE = tmp_path / "prefs.json"
    launch.EVENTS_FILE = tmp_path / "events.jsonl"
    launch.CONFIG_FILE.write_text(json.dumps(
        {"check_for_updates": False,
         "check_ins": {"enabled": True, "questions": [question]}}))
    try:
        root = ctk.CTk()
    except tk.TclError:
        pytest.skip("no display available")
    app = launch.BreakApp(root)
    root.update_idletasks(); root.update()
    app._show_check_in(parse_questions(app.check_in_questions)[0])
    root.update_idletasks(); root.update()
    popup = [c for c in root.winfo_children() if isinstance(c, ctk.CTkToplevel)][-1]
    return ctk, root, popup


def _value_buttons(ctk, popup):
    def walk(w):
        for c in w.winfo_children():
            yield c
            yield from walk(c)
    return [b for b in walk(popup)
            if isinstance(b, ctk.CTkButton) and str(b.cget("text")).lstrip("-").isdigit()]


def test_a_wide_scale_fits_inside_the_popup(tmp_path):
    ctk, root, popup = _popup(tmp_path, WIDE_SCALE)
    try:
        assert popup.winfo_reqwidth() <= launch.CHECK_IN_POPUP_W
    finally:
        root.destroy()


def test_every_value_button_is_rendered_at_full_size(tmp_path):
    ctk, root, popup = _popup(tmp_path, WIDE_SCALE)
    try:
        buttons = _value_buttons(ctk, popup)
        assert len(buttons) == 11
        squeezed = [b.cget("text") for b in buttons
                    if b.winfo_width() < launch.CHECK_IN_SCALE_BTN_WIDTH // 2]
        assert not squeezed, f"clipped off the popup: {squeezed}"
    finally:
        root.destroy()

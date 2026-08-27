"""A wide scale (0–10) stays on ONE row, as a compact strip.

Regression: the check-in popup is a fixed CHECK_IN_POPUP_W wide, but _build_scale
packed every value at full size in one row. A 0–10 question wanted 604px in a
340px window, so Tk squeezed buttons 6–10 down to 1px — it rendered as "0–5".

Wrapping onto rows fixed the clipping but read as a bingo card, so instead the
buttons tighten to fit a single row; wrapping remains only as a last resort for
a range too wide to fit even at the minimum legible size.
"""
import json
import pytest

import launch

USABLE = launch.CHECK_IN_SCALE_USABLE_W
DENSE_USABLE = launch.CHECK_IN_SCALE_DENSE_USABLE_W


def _size(count):
    return launch.scale_button_size(count, USABLE, DENSE_USABLE)


def _fits(count, width, gap, dense):
    return count * (width + 2 * gap) <= (DENSE_USABLE if dense else USABLE)


# ---- pure: how big each button is ------------------------------------------

def test_a_short_scale_keeps_the_comfortable_default_size():
    assert _size(5) == (launch.CHECK_IN_SCALE_BTN_WIDTH, launch.SPACE_XXS, False)


def test_a_wide_scale_tightens_so_it_still_fits_one_row():
    width, gap, dense = _size(11)
    assert dense and width < launch.CHECK_IN_SCALE_BTN_WIDTH
    assert _fits(11, width, gap, dense)


def test_buttons_never_shrink_below_the_legible_minimum():
    width, _, _ = _size(60)                             # absurd range
    assert width == launch.CHECK_IN_SCALE_MIN_BTN_WIDTH


def test_every_reasonable_range_fits_one_row():
    for count in range(1, 13):
        width, gap, dense = _size(count)
        assert _fits(count, width, gap, dense), f"{count} values overflow the popup"


# ---- pure: wrapping, the last resort for an absurd range -------------------

def test_a_short_scale_stays_on_one_row():
    assert launch.scale_button_rows(range(1, 6), 5) == [[1, 2, 3, 4, 5]]


def test_rows_are_balanced_and_lose_nothing():
    rows = launch.scale_button_rows(range(0, 11), 5)
    assert rows == [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10]]     # 4/4/3, not 5/5/1
    for n in range(1, 40):
        rows = launch.scale_button_rows(range(n), 5)
        assert all(len(r) <= 5 for r in rows)
        assert [v for r in rows for v in r] == list(range(n))


def test_no_values_means_no_rows():
    assert launch.scale_button_rows([], 5) == []


# ---- the real popup --------------------------------------------------------

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


def test_every_value_is_rendered_on_a_single_row(tmp_path):
    ctk, root, popup = _popup(tmp_path, WIDE_SCALE)
    try:
        buttons = _value_buttons(ctk, popup)
        assert len(buttons) == 11
        assert len({b.winfo_rooty() for b in buttons}) == 1, "the strip wrapped"
        squeezed = [b.cget("text") for b in buttons
                    if b.winfo_width() < launch.CHECK_IN_SCALE_MIN_BTN_WIDTH]
        assert not squeezed, f"clipped off the popup: {squeezed}"
    finally:
        root.destroy()

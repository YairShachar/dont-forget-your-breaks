"""The check-in edit modal: building a stored `answer` from the form's fields.

Regression: touching the answer-type menu rebuilt the type-specific fields from
the STORED answer, silently throwing away what you had just typed — a 0–10 scale
came back as 1–5, and that is what got saved.

The per-type builders are pure; the last test drives the real modal (Tk-gated).
"""
import json
import pytest

import launch
from dfyb.checkins.model import (SCALE, CHOICES, DEFAULT_SCALE_MIN, DEFAULT_SCALE_MAX,
                                 parse_questions)


# ---- pure: form fields -> stored answer ------------------------------------

def test_scale_answer_from_fields():
    assert launch.check_in_scale_answer("0", "10", "none", "loads", True) == {
        "type": SCALE, "min": 0, "max": 10,
        "min_label": "none", "max_label": "loads", "allow_note": True}


def test_scale_answer_swaps_a_reversed_range():
    answer = launch.check_in_scale_answer("10", "0", "", "", False)
    assert (answer["min"], answer["max"]) == (0, 10)
    assert answer["allow_note"] is False


def test_scale_answer_falls_back_on_blank_fields():
    answer = launch.check_in_scale_answer("", "", "", "", True)
    assert (answer["min"], answer["max"]) == (DEFAULT_SCALE_MIN, DEFAULT_SCALE_MAX)


def test_choices_answer_from_fields():
    answer = launch.check_in_choices_answer("Great, OK\nRough", True)
    assert answer == {"type": CHOICES, "options": ["Great", "OK", "Rough"],
                      "allow_note": True}


def test_choices_answer_falls_back_when_empty():
    assert launch.check_in_choices_answer("   ", True)["options"] == \
        list(launch.CHECK_IN_DEFAULT_CHOICES)


# ---- the real modal: your edits survive a trip through the type menu --------

tk = pytest.importorskip("tkinter")

QUESTION = "How many hours did you sleep?"


def _modal(tmp_path):
    ctk = pytest.importorskip("customtkinter")
    launch.CONFIG_FILE = tmp_path / "prefs.json"
    launch.EVENTS_FILE = tmp_path / "events.jsonl"
    launch.CONFIG_FILE.write_text(json.dumps({"check_for_updates": False}))
    try:
        root = ctk.CTk()
    except tk.TclError:
        pytest.skip("no display available")
    app = launch.BreakApp(root)

    def pump():
        root.update_idletasks()
        root.update()

    def walk(w):
        for c in w.winfo_children():
            yield c
            yield from walk(c)

    def text_of(w):
        try:
            return str(w.cget("text") or "")
        except Exception:
            return ""

    pump()
    question = launch.new_check_in_question("hours")
    app._edit_check_in_question(question, parent=root, on_saved=lambda: None)
    pump()
    modal = [c for c in root.winfo_children() if isinstance(c, ctk.CTkToplevel)][-1]
    return ctk, app, root, question, modal, pump, walk, text_of


def test_typed_range_survives_touching_the_answer_type_menu(tmp_path):
    ctk, app, root, question, modal, pump, walk, text_of = _modal(tmp_path)
    try:
        entries = [c for c in walk(modal) if isinstance(c, ctk.CTkEntry)]
        entries[0].delete(0, "end"); entries[0].insert(0, QUESTION)
        entries[1].delete(0, "end"); entries[1].insert(0, "0")     # Min
        entries[2].delete(0, "end"); entries[2].insert(0, "10")    # Max

        menu = next(c for c in walk(modal) if isinstance(c, ctk.CTkOptionMenu))
        menu.set("Scale"); menu._command("Scale")                  # re-pick the SAME type
        pump()

        next(c for c in walk(modal)
             if text_of(c) == launch.CHECK_IN_EDIT_SAVE_LABEL).invoke()
        pump()
        assert (question["answer"]["min"], question["answer"]["max"]) == (0, 10)
    finally:
        root.destroy()


def test_switching_type_and_back_keeps_the_range(tmp_path):
    ctk, app, root, question, modal, pump, walk, text_of = _modal(tmp_path)
    try:
        entries = [c for c in walk(modal) if isinstance(c, ctk.CTkEntry)]
        entries[1].delete(0, "end"); entries[1].insert(0, "0")
        entries[2].delete(0, "end"); entries[2].insert(0, "10")

        menu = next(c for c in walk(modal) if isinstance(c, ctk.CTkOptionMenu))
        menu.set("Note"); menu._command("Note"); pump()            # detour
        menu.set("Scale"); menu._command("Scale"); pump()          # and back

        next(c for c in walk(modal)
             if text_of(c) == launch.CHECK_IN_EDIT_SAVE_LABEL).invoke()
        pump()
        assert (question["answer"]["min"], question["answer"]["max"]) == (0, 10)
        assert parse_questions([question])[0].answer.max == 10
    finally:
        root.destroy()

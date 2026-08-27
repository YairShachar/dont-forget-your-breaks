"""Adding a check-in question from the chooser (not just from Settings).

Thinking of a question mid-check-in shouldn't mean a detour through Settings, so
the chooser carries a "＋ Add a question" row that opens the same edit modal.
Save keeps the question (and persists it); Cancel leaves nothing behind.

Tk-gated (self-skips headless) — the flow is chooser → modal → chooser.
"""
import json
import pytest

tk = pytest.importorskip("tkinter")

NEW_QUESTION = "Did I step outside?"


def _app(tmp_path):
    ctk = pytest.importorskip("customtkinter")
    import launch
    launch.CONFIG_FILE = tmp_path / "prefs.json"
    launch.EVENTS_FILE = tmp_path / "events.jsonl"
    launch.CONFIG_FILE.write_text(json.dumps({"check_for_updates": False}))
    try:
        root = ctk.CTk()
    except tk.TclError:
        pytest.skip("no display available")
    return ctk, launch, launch.BreakApp(root), root


def _walk(widget):
    for child in widget.winfo_children():
        yield child
        yield from _walk(child)


def _text_of(widget):
    try:
        return str(widget.cget("text") or "")
    except Exception:               # frames and canvases have no -text option
        return ""


def _find(widget, text):
    return next((c for c in _walk(widget) if _text_of(c) == text), None)


def _add_a_question(ctk, launch, app, root, name, save):
    """Drive the real flow: open the chooser, tap the add row, name it, Save/Cancel."""
    def pump():
        root.update_idletasks()
        root.update()

    def newest_toplevel():
        tops = [c for c in root.winfo_children() if isinstance(c, ctk.CTkToplevel)]
        return tops[-1] if tops else None

    app._open_check_in_chooser()
    pump()
    chooser = newest_toplevel()
    link = _find(chooser, launch.CHECK_IN_ADD_QUESTION_LABEL)
    assert link is not None, "the chooser has no add row"
    link._label.event_generate("<Button-1>", when="now")   # CTkLabel binds its inner widget
    pump()

    modal = newest_toplevel()
    assert modal is not chooser, "tapping the add row did not open the edit modal"
    entry = next(c for c in _walk(modal) if isinstance(c, ctk.CTkEntry))
    entry.delete(0, "end")
    entry.insert(0, name)
    _find(modal, launch.CHECK_IN_EDIT_SAVE_LABEL if save
          else launch.CHECK_IN_EDIT_CANCEL_LABEL).invoke()
    pump()
    return chooser


def test_saving_adds_the_question_and_refreshes_the_chooser(tmp_path):
    ctk, launch, app, root = _app(tmp_path)
    try:
        before = len(app.check_in_questions)
        chooser = _add_a_question(ctk, launch, app, root, NEW_QUESTION, save=True)
        assert len(app.check_in_questions) == before + 1
        added = app.check_in_questions[-1]
        assert added["text"] == NEW_QUESTION
        # the id groups this question's answers in the event log — slug the real name
        assert added["id"] == "did-i-step-outside"
        assert _find(chooser, NEW_QUESTION) is not None, "the chooser did not refresh"
    finally:
        root.destroy()


def test_the_new_question_is_persisted(tmp_path):
    ctk, launch, app, root = _app(tmp_path)
    try:
        _add_a_question(ctk, launch, app, root, NEW_QUESTION, save=True)
        saved = json.loads(launch.CONFIG_FILE.read_text())["check_ins"]["questions"]
        assert [q["text"] for q in saved][-1] == NEW_QUESTION
    finally:
        root.destroy()


def test_cancelling_leaves_no_half_made_question(tmp_path):
    ctk, launch, app, root = _app(tmp_path)
    try:
        before = len(app.check_in_questions)
        chooser = _add_a_question(ctk, launch, app, root, "Throwaway", save=False)
        assert len(app.check_in_questions) == before
        assert _find(chooser, "Throwaway") is None
        assert _find(chooser, launch.CHECK_IN_NEW_QUESTION_TEXT) is None
    finally:
        root.destroy()


def test_the_add_row_is_there_when_there_is_nothing_to_check_in_on(tmp_path):
    ctk, launch, app, root = _app(tmp_path)
    try:
        app.check_in_questions.clear()            # the dead-end this fixes
        app._open_check_in_chooser()
        root.update_idletasks(); root.update()
        chooser = [c for c in root.winfo_children() if isinstance(c, ctk.CTkToplevel)][-1]
        assert _find(chooser, launch.CHECK_IN_NONE_CONFIGURED_TEXT) is not None
        assert _find(chooser, launch.CHECK_IN_ADD_QUESTION_LABEL) is not None
    finally:
        root.destroy()


def test_the_edit_modal_is_not_stacked_under_the_chooser(tmp_path):
    """macOS: pin_to_active_space raises windows to NSStatusWindowLevel from <Map>,
    so a '-topmost' applied AFTER mapping drops the modal below the chooser.

    NSApplication.windows() is process-global and keeps torn-down windows around,
    so both windows get a title unique to this test — otherwise the lookup can
    match a leftover window from an earlier test and the check means nothing.
    """
    AppKit = pytest.importorskip("AppKit")
    ctk, launch, app, root = _app(tmp_path)
    chooser_title, modal_title = "Chooser stack probe", "Modal stack probe"
    original = (launch.CHECK_IN_CHOOSER_TITLE, launch.CHECK_IN_EDIT_TITLE)
    launch.CHECK_IN_CHOOSER_TITLE, launch.CHECK_IN_EDIT_TITLE = chooser_title, modal_title
    try:
        def level_of(title):
            return next((int(w.level()) for w in AppKit.NSApplication.sharedApplication()
                         .windows() if w.title() == title), None)

        app._open_check_in_chooser()
        root.update_idletasks(); root.update()
        chooser = [c for c in root.winfo_children() if isinstance(c, ctk.CTkToplevel)][-1]
        _find(chooser, launch.CHECK_IN_ADD_QUESTION_LABEL)._label.event_generate(
            "<Button-1>", when="now")
        root.update_idletasks(); root.update()      # measure while the modal is OPEN

        chooser_level, modal_level = level_of(chooser_title), level_of(modal_title)
        if chooser_level is None or modal_level is None:
            pytest.skip("NSWindow lookup unavailable")
        assert modal_level >= chooser_level
    finally:
        launch.CHECK_IN_CHOOSER_TITLE, launch.CHECK_IN_EDIT_TITLE = original
        root.destroy()

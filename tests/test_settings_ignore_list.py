"""Settings > Smart pausing: review and remove ignored apps (#28, Task 9).

Covers `BreakApp._build_ignore_list` and `_remove_ignore_row` — the sub-block
under each defer toggle that lists exactly what `_ignores()` applies (built-ins
the user hasn't removed, plus their own additions) and lets a row's ✕ un-excuse
it. Tk-gated (self-skips headless); prefs/events isolated to tmp_path — same
pattern as tests/test_chip_ignore.py.
"""
import json

import pytest

tk = pytest.importorskip("tkinter")

ZOOM = {"id": "us.zoom.xos", "name": "Zoom"}


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
    import dfyb.activity.app_rules as app_rules
    return app_rules, launch.BreakApp(root), root


def _relaunch(tmp_path):
    """A second BreakApp reading the SAME prefs file already on disk — unlike
    `_app`, this must not truncate it back to the fresh-install default."""
    ctk = pytest.importorskip("customtkinter")
    import launch
    try:
        root = ctk.CTk()
    except tk.TclError:
        pytest.skip("no display available")
    import dfyb.activity.app_rules as app_rules
    return app_rules, launch.BreakApp(root), root


def _block(parent):
    """The inner list block: parent -> subwrap -> [hairline, block]."""
    subwrap = parent.winfo_children()[0]
    return subwrap.winfo_children()[1]


def _rows(block):
    """The per-app row frames — distinguished by type from the heading label,
    the empty-state label, and the "+ Add app" button, all direct siblings."""
    import customtkinter as ctk
    return [c for c in block.winfo_children() if isinstance(c, ctk.CTkFrame)]


def _row_label(row):
    return row.winfo_children()[0].cget("text")


def _row_remove_button(row):
    return row.winfo_children()[1]


def _events(launch):
    return [json.loads(line) for line in launch.EVENTS_FILE.read_text().splitlines()]


# --- rendering: the row set matches _ignores() exactly ---

def test_mic_rows_match_ignores_on_fresh_install(tmp_path):
    app_rules, app, root = _app(tmp_path)
    try:
        ctk = pytest.importorskip("customtkinter")
        parent = ctk.CTkFrame(root)
        app._build_ignore_list(parent, app_rules.MIC)
        block = _block(parent)
        rows = _rows(block)

        ignored = app._ignores(app_rules.MIC)
        assert len(rows) == len(ignored) == len(app_rules.DEFAULT_MIC_IGNORED_APPS)
        labels = {_row_label(r) for r in rows}
        expected = {a["name"] + " (built-in)" for a in app_rules.DEFAULT_MIC_IGNORED_APPS}
        assert labels == expected
    finally:
        root.destroy()


def test_fullscreen_empty_state_renders(tmp_path):
    """DEFAULT_FULLSCREEN_IGNORED_APPS is empty and nothing was added, so the
    block must show the empty-state line, not a bare list with zero rows."""
    app_rules, app, root = _app(tmp_path)
    try:
        ctk = pytest.importorskip("customtkinter")
        parent = ctk.CTkFrame(root)
        app._build_ignore_list(parent, app_rules.FULLSCREEN)
        block = _block(parent)

        assert app._ignores(app_rules.FULLSCREEN) == set()
        assert _rows(block) == []
        texts = [c.cget("text") for c in block.winfo_children()
                 if isinstance(c, ctk.CTkLabel)]
        assert "None — every app defers your breaks" in texts
    finally:
        root.destroy()


def test_user_addition_appears_without_builtin_tag_and_no_duplicate(tmp_path):
    app_rules, app, root = _app(tmp_path)
    try:
        ctk = pytest.importorskip("customtkinter")
        app.mic_ignored_apps.append(dict(ZOOM))
        parent = ctk.CTkFrame(root)
        app._build_ignore_list(parent, app_rules.MIC)
        block = _block(parent)
        rows = _rows(block)

        assert len(rows) == len(app_rules.DEFAULT_MIC_IGNORED_APPS) + 1
        labels = [_row_label(r) for r in rows]
        assert "Zoom" in labels
        assert labels.count("Zoom") == 1   # not also duplicated as a built-in row
    finally:
        root.destroy()


def test_builtin_with_no_bundle_id_renders_by_name(tmp_path):
    """corespeechd ships with id=None; normalize_app falls back to its name —
    the row must still render (and use the name, not crash on a None key)."""
    app_rules, app, root = _app(tmp_path)
    try:
        ctk = pytest.importorskip("customtkinter")
        parent = ctk.CTkFrame(root)
        app._build_ignore_list(parent, app_rules.MIC)
        block = _block(parent)
        labels = [_row_label(r) for r in _rows(block)]
        assert "corespeechd (built-in)" in labels
    finally:
        root.destroy()


# --- removing a row: prefs update, re-render, event, and no crash ---

def test_removing_builtin_row_updates_prefs_and_rerendered_rows(tmp_path):
    app_rules, app, root = _app(tmp_path)
    try:
        ctk = pytest.importorskip("customtkinter")
        parent = ctk.CTkFrame(root)
        app._build_ignore_list(parent, app_rules.MIC)
        block = _block(parent)
        rows = _rows(block)
        target_row = next(r for r in rows if _row_label(r) == "Control Center (built-in)")
        _row_remove_button(target_row).cget("command")()   # the ✕ click
        root.update()   # flush the after(0, ...) rebuild

        key = app_rules.normalize_app("com.apple.controlcenter", "Control Center")
        assert key not in app._ignores(app_rules.MIC)
        assert key in {k.strip().lower() for k in app.mic_unignored_builtins}

        block = _block(parent)   # re-fetched: render() destroyed the old children
        remaining_labels = {_row_label(r) for r in _rows(block)}
        assert "Control Center (built-in)" not in remaining_labels
        assert len(_rows(block)) == len(app_rules.DEFAULT_MIC_IGNORED_APPS) - 1
    finally:
        root.destroy()


def test_removing_no_bundle_id_builtin_row_works(tmp_path):
    """The ✕ on the id=None built-in (corespeechd) must not assume "id" is a
    string — it should un-ignore by name and persist correctly."""
    app_rules, app, root = _app(tmp_path)
    try:
        ctk = pytest.importorskip("customtkinter")
        parent = ctk.CTkFrame(root)
        app._build_ignore_list(parent, app_rules.MIC)
        block = _block(parent)
        target_row = next(r for r in _rows(block) if _row_label(r) == "corespeechd (built-in)")
        _row_remove_button(target_row).cget("command")()
        root.update()

        key = app_rules.normalize_app(None, "corespeechd")
        assert key not in app._ignores(app_rules.MIC)
        block = _block(parent)
        remaining_labels = {_row_label(r) for r in _rows(block)}
        assert "corespeechd (built-in)" not in remaining_labels
    finally:
        root.destroy()


def test_removing_row_records_app_ignore_removed_with_source_settings(tmp_path):
    """The instrumentation is `_toggle_ignore`'s (no second event) — this just
    confirms the row's ✕ is wired to it with the right source."""
    import launch
    app_rules, app, root = _app(tmp_path)
    try:
        ctk = pytest.importorskip("customtkinter")
        parent = ctk.CTkFrame(root)
        app._build_ignore_list(parent, app_rules.MIC)
        block = _block(parent)
        target_row = next(r for r in _rows(block) if _row_label(r) == "Control Center (built-in)")
        _row_remove_button(target_row).cget("command")()
        root.update()

        last = _events(launch)[-1]
        assert last["type"] == "app_ignore_removed"
        assert last["data"]["source"] == "settings"
        assert last["data"]["signal"] == app_rules.MIC
        assert last["data"]["builtin"] is True
    finally:
        root.destroy()


def test_removing_persists_across_a_fresh_ignores_read(tmp_path):
    """The removal survives a relaunch: a brand-new BreakApp reading the same
    prefs file must not re-show the removed built-in."""
    app_rules, app, root = _app(tmp_path)
    try:
        ctk = pytest.importorskip("customtkinter")
        parent = ctk.CTkFrame(root)
        app._build_ignore_list(parent, app_rules.MIC)
        block = _block(parent)
        target_row = next(r for r in _rows(block) if _row_label(r) == "Control Center (built-in)")
        _row_remove_button(target_row).cget("command")()
        root.update()
    finally:
        root.destroy()

    app_rules, app2, root2 = _relaunch(tmp_path)
    try:
        key = app_rules.normalize_app("com.apple.controlcenter", "Control Center")
        assert key not in app2._ignores(app_rules.MIC)
    finally:
        root2.destroy()

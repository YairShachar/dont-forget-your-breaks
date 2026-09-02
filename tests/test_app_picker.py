"""Settings > Smart pausing > + Add app: `BreakApp._open_app_picker` (#28, Task 10).

Covers the picker's candidate list — running apps minus whatever `_ignores()`
already covers (built-ins AND user additions) — and that choosing one persists
through `_toggle_ignore(..., source="settings")`, rebuilds the ignore-list rows
via the `render` callback from `_build_ignore_list`, and refits the settings
window, matching `_set_ignore_row`'s rebuild-after-destroy pattern.

Tk-gated (self-skips headless); prefs/events isolated to tmp_path — same
pattern as tests/test_settings_ignore_list.py and tests/test_app_ignore_toggle.py.
"""
import json

import pytest

tk = pytest.importorskip("tkinter")

ZOOM = {"id": "us.zoom.xos", "name": "Zoom"}
SAFARI = {"id": "com.apple.Safari", "name": "Safari"}


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


def _stub_running_apps(monkeypatch, apps):
    import launch
    monkeypatch.setattr(launch, "sensors_running_gui_apps", lambda: apps)


def _picker_buttons(picker):
    """The per-app CTkButtons, found by walking the whole subtree: a
    CTkScrollableFrame's own widgets don't live directly under the Toplevel —
    they're nested under its internal parent-frame/canvas — so children added
    to it (our app buttons) are found by recursive search, not a fixed depth."""
    import customtkinter as ctk
    found = []
    stack = list(picker.winfo_children())
    while stack:
        widget = stack.pop()
        if isinstance(widget, ctk.CTkButton):
            found.append(widget)
        else:
            stack.extend(widget.winfo_children())
    return found


def _events(launch):
    return [json.loads(line) for line in launch.EVENTS_FILE.read_text().splitlines()]


# --- candidate filtering ---

def test_running_apps_filtered_and_offered(tmp_path, monkeypatch):
    """Control Center (a default mic built-in) and Zoom (a user addition) are
    both already ignored — offering either again would do nothing, so only
    Safari, which is neither, must appear as a candidate."""
    app_rules, app, root = _app(tmp_path)
    try:
        control_center = {"id": "com.apple.controlcenter", "name": "Control Center"}
        app.mic_ignored_apps.append(dict(ZOOM))   # a user addition, also to be excluded
        _stub_running_apps(monkeypatch, [
            (control_center["id"], control_center["name"]),  # already-ignored builtin
            (ZOOM["id"], ZOOM["name"]),                       # already-ignored user addition
            (SAFARI["id"], SAFARI["name"]),                   # not ignored -> offered
        ])
        rendered = []
        app._open_app_picker(app_rules.MIC, lambda: rendered.append(True))
        picker = root.winfo_children()[-1]
        try:
            labels = {b.cget("text") for b in _picker_buttons(picker)}
            assert labels == {"Safari"}
        finally:
            picker.destroy()
    finally:
        root.destroy()


def test_empty_running_apps_offers_no_rows(tmp_path, monkeypatch):
    app_rules, app, root = _app(tmp_path)
    try:
        _stub_running_apps(monkeypatch, [])
        app._open_app_picker(app_rules.MIC, lambda: None)
        picker = root.winfo_children()[-1]
        try:
            assert _picker_buttons(picker) == []
        finally:
            picker.destroy()
    finally:
        root.destroy()


# --- choosing an app ---

def test_choosing_an_app_persists_rebuilds_and_records_event(tmp_path, monkeypatch):
    import launch
    app_rules, app, root = _app(tmp_path)
    try:
        _stub_running_apps(monkeypatch, [(SAFARI["id"], SAFARI["name"])])
        resized = []
        monkeypatch.setattr(app, "_resize_settings_to_content",
                            lambda: resized.append(True))
        rebuilt = []
        app._open_app_picker(app_rules.MIC, lambda: rebuilt.append(True))
        picker = root.winfo_children()[-1]
        button = _picker_buttons(picker)[0]
        assert button.cget("text") == "Safari"

        button.cget("command")()   # the click

        # The picker is destroyed synchronously by the click...
        assert not picker.winfo_exists()
        # ...and the rebuild + resize are deferred to the next event-loop turn.
        assert rebuilt == [] and resized == []
        root.update()
        assert rebuilt == [True] and resized == [True]

        key = app_rules.normalize_app(SAFARI["id"], SAFARI["name"])
        assert key in app._ignores(app_rules.MIC)
        assert app.mic_ignored_apps == [{"id": SAFARI["id"], "name": SAFARI["name"]}]

        last = _events(launch)[-1]
        assert last["type"] == "app_ignore_added"
        assert last["data"]["source"] == "settings"
        assert last["data"]["signal"] == app_rules.MIC
        assert last["data"]["app"] == key
    finally:
        root.destroy()


def test_choosing_an_app_persists_across_a_fresh_ignores_read(tmp_path, monkeypatch):
    app_rules, app, root = _app(tmp_path)
    try:
        _stub_running_apps(monkeypatch, [(SAFARI["id"], SAFARI["name"])])
        monkeypatch.setattr(app, "_resize_settings_to_content", lambda: None)
        app._open_app_picker(app_rules.MIC, lambda: None)
        picker = root.winfo_children()[-1]
        _picker_buttons(picker)[0].cget("command")()
        root.update()
    finally:
        root.destroy()

    ctk = pytest.importorskip("customtkinter")
    import launch
    try:
        root2 = ctk.CTk()
    except tk.TclError:
        pytest.skip("no display available")
    try:
        app2 = launch.BreakApp(root2)
        key = app_rules.normalize_app(SAFARI["id"], SAFARI["name"])
        assert key in app2._ignores(app_rules.MIC)
    finally:
        root2.destroy()


# --- closing without choosing ---

def test_closing_without_choosing_does_not_toggle_or_rebuild(tmp_path, monkeypatch):
    app_rules, app, root = _app(tmp_path)
    try:
        _stub_running_apps(monkeypatch, [(SAFARI["id"], SAFARI["name"])])
        rebuilt = []
        before = app._ignores(app_rules.MIC)
        app._open_app_picker(app_rules.MIC, lambda: rebuilt.append(True))
        picker = root.winfo_children()[-1]

        # A close handler is registered (WM_DELETE_WINDOW) rather than left to
        # whatever Tk's platform default happens to be; invoke it exactly as
        # the window manager's close box would.
        close_cmd = picker.protocol("WM_DELETE_WINDOW")
        assert close_cmd
        root.tk.call(close_cmd)
        root.update()

        assert not picker.winfo_exists()
        assert rebuilt == []
        assert app._ignores(app_rules.MIC) == before
    finally:
        root.destroy()

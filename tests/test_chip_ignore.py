"""The holding chip's one-click "Ignore <app>" (#40/#28, Task 8).

Covers the seam `_render_status` <-> `_handle_chip_ignore`: the button's
label and its eventual action must always agree, even though the action is
performed against state stashed at render time (`self._chip_action`), not
re-derived from `self._held`/`self._held_app` at click time.

Tk-gated (self-skips headless); prefs/events isolated to tmp_path — same
pattern as tests/test_app_ignore_toggle.py.
"""
import json
import pytest

tk = pytest.importorskip("tkinter")

ZOOM = {"id": "us.zoom.xos", "name": "Zoom", "count": 3}


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


def _hold_on_zoom(app):
    """Put the app into the same state a mic-holding tick would leave it in."""
    app.running = True
    app._held = "meeting"
    app._held_app = dict(ZOOM)


# --- rendering: button appears/disappears with the label it's promised ---

def test_chip_action_button_shown_and_wired_when_app_attributed(tmp_path):
    app_rules, app, root = _app(tmp_path)
    try:
        _hold_on_zoom(app)
        app._render_status()

        assert app.hero_chip_action.cget("text") == "Ignore Zoom"
        assert app.hero_chip_action.winfo_manager() == "pack"
        assert app.hero_chip_row.winfo_manager() == "pack"
        # Wired to the real handler, not a copy or a lambda that could drift.
        assert app.hero_chip_action.cget("command") == app._handle_chip_ignore
        # What the render promised is exactly what the click will act on.
        assert app._chip_action == (
            app_rules.MIC, {"id": ZOOM["id"], "name": ZOOM["name"], "count": ZOOM["count"]})
    finally:
        root.destroy()


def test_chip_action_button_hidden_when_app_unattributed(tmp_path):
    """Held for a known reason, but the causing app couldn't be named — the
    chip text still appears, but no button (nothing to excuse by name)."""
    app_rules, app, root = _app(tmp_path)
    try:
        app.running = True
        app._held = "meeting"
        app._held_app = None
        app._render_status()

        assert app.hero_chip_row.winfo_manager() == "pack"   # chip text itself shows
        assert app.hero_chip_action.winfo_manager() != "pack"
        assert app._chip_action is None
    finally:
        root.destroy()


def test_chip_row_hidden_entirely_when_nothing_held(tmp_path):
    app_rules, app, root = _app(tmp_path)
    try:
        app.running = True
        app._held = None
        app._held_app = None
        app._render_status()

        assert app.hero_chip_row.winfo_manager() != "pack"
        assert app._chip_action is None
    finally:
        root.destroy()


def test_chip_action_button_cleared_when_hold_fully_ends(tmp_path):
    """A leftover button from a previous held-app render must not survive a
    render where the hold has cleared and there's no chip at all."""
    app_rules, app, root = _app(tmp_path)
    try:
        _hold_on_zoom(app)
        app._render_status()
        assert app.hero_chip_action.winfo_manager() == "pack"

        app._held, app._held_app = None, None
        app._render_status()
        assert app.hero_chip_row.winfo_manager() != "pack"   # whole row hidden
        assert app._chip_action is None
    finally:
        root.destroy()


def test_chip_action_button_removed_while_chip_stays_anticipated(tmp_path):
    """The stricter case: the hold ends but the row keeps showing (an
    anticipated chip takes over) — the leftover action button must still be
    removed even though its parent row stays packed."""
    app_rules, app, root = _app(tmp_path)
    try:
        _hold_on_zoom(app)
        app._render_status()
        assert app.hero_chip_action.winfo_manager() == "pack"

        app._held, app._held_app = None, None
        app._anticipated, app._anticipated_app = "meeting", None
        app._render_status()

        assert app.hero_chip_row.winfo_manager() == "pack"    # chip text still shows
        assert app.hero_chip_action.winfo_manager() != "pack"  # but no button
        assert app._chip_action is None
    finally:
        root.destroy()


# --- clicking: acts on the stashed render, persists, logs, and clears the hold ---

def test_handle_chip_ignore_persists_clears_hold_and_rerenders(tmp_path):
    app_rules, app, root = _app(tmp_path)
    try:
        _hold_on_zoom(app)
        app._render_status()

        app._handle_chip_ignore()

        assert app.mic_ignored_apps == [{"id": ZOOM["id"], "name": ZOOM["name"]}]
        key = app_rules.normalize_app(ZOOM["id"], ZOOM["name"])
        assert key in app._ignores(app_rules.MIC)
        assert app._held is None
        assert app._held_app is None
        # Re-rendered immediately: the chip is gone without waiting for a tick.
        assert app.hero_chip_row.winfo_manager() != "pack"
    finally:
        root.destroy()


def test_handle_chip_ignore_records_app_ignore_added_with_source_chip(tmp_path):
    import launch
    app_rules, app, root = _app(tmp_path)
    try:
        _hold_on_zoom(app)
        app._render_status()
        app._handle_chip_ignore()

        last = _events(launch)[-1]
        assert last["type"] == "app_ignore_added"
        assert last["data"]["source"] == "chip"
        assert last["data"]["signal"] == app_rules.MIC
        assert last["data"]["app_name"] == "Zoom"
    finally:
        root.destroy()


def _events(launch):
    return [json.loads(line) for line in launch.EVENTS_FILE.read_text().splitlines()]


def test_handle_chip_ignore_is_a_noop_without_a_rendered_action(tmp_path):
    """No render happened (or the last render showed no button) — clicking
    must not be possible in the UI, but defensively the handler no-ops."""
    import launch
    app_rules, app, root = _app(tmp_path)
    try:
        assert app._chip_action is None   # fresh app, nothing rendered yet
        before = _events(launch) if launch.EVENTS_FILE.exists() else []

        app._handle_chip_ignore()

        assert app.mic_ignored_apps == []
        after = _events(launch) if launch.EVENTS_FILE.exists() else []
        assert after == before   # no event appended by the no-op
    finally:
        root.destroy()

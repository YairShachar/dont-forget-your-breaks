"""`BreakApp._toggle_ignore` — the state-mutation seam Tasks 8-10 build on.

`tests/test_app_rules.py` covers the pure `effective_ignores` algebra; this
file covers the OTHER half — that toggling actually leaves the three list
prefs in the right shape, and stays idempotent under repeated add/remove
(the review that found this: re-adding a previously-removed built-in must
not grow `mic_ignored_apps`, and repeated removes must not grow
`mic_unignored_builtins`).

Tk-gated (self-skips headless); prefs/events isolated to tmp_path.
"""
import json
import pytest

tk = pytest.importorskip("tkinter")

CONTROL_CENTER = {"id": "com.apple.controlcenter", "name": "Control Center"}  # built-in
ZOOM = {"id": "us.zoom.xos", "name": "Zoom"}                                  # user app
SLIDES = {"id": "com.apple.iWork.Keynote", "name": "Keynote"}                 # fullscreen user app


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


# --- adding/removing a plain user app ---

def test_add_user_app_appears_once_and_is_not_duplicated(tmp_path):
    app_rules, app, root = _app(tmp_path)
    try:
        app._toggle_ignore(app_rules.MIC, ZOOM, True, "chip")
        app._toggle_ignore(app_rules.MIC, ZOOM, True, "chip")   # repeat: no dup
        assert app.mic_ignored_apps == [{"id": ZOOM["id"], "name": ZOOM["name"]}]
        assert app_rules.normalize_app(ZOOM["id"], ZOOM["name"]) in app._ignores(app_rules.MIC)
    finally:
        root.destroy()


def test_remove_user_app_clears_it_and_leaves_unignored_builtins_untouched(tmp_path):
    app_rules, app, root = _app(tmp_path)
    try:
        app._toggle_ignore(app_rules.MIC, ZOOM, True, "chip")
        app._toggle_ignore(app_rules.MIC, ZOOM, False, "settings")
        assert app.mic_ignored_apps == []
        assert app.mic_unignored_builtins == []
        key = app_rules.normalize_app(ZOOM["id"], ZOOM["name"])
        assert key not in app._ignores(app_rules.MIC)
    finally:
        root.destroy()


# --- removing / re-adding a built-in ---

def test_remove_builtin_records_it_without_growing_user_added_list(tmp_path):
    app_rules, app, root = _app(tmp_path)
    try:
        app._toggle_ignore(app_rules.MIC, CONTROL_CENTER, False, "settings")
        key = app_rules.normalize_app(CONTROL_CENTER["id"], CONTROL_CENTER["name"])
        assert app.mic_unignored_builtins == [CONTROL_CENTER["id"]]
        assert app.mic_ignored_apps == []          # not treated as a user addition
        assert key not in app._ignores(app_rules.MIC)
    finally:
        root.destroy()


def test_removing_an_already_removed_builtin_does_not_duplicate_it(tmp_path):
    app_rules, app, root = _app(tmp_path)
    try:
        app._toggle_ignore(app_rules.MIC, CONTROL_CENTER, False, "settings")
        app._toggle_ignore(app_rules.MIC, CONTROL_CENTER, False, "settings")   # repeat
        assert app.mic_unignored_builtins == [CONTROL_CENTER["id"]]
    finally:
        root.destroy()


def test_readding_a_removed_builtin_clears_the_unignore_without_a_redundant_entry(tmp_path):
    app_rules, app, root = _app(tmp_path)
    try:
        app._toggle_ignore(app_rules.MIC, CONTROL_CENTER, False, "settings")
        app._toggle_ignore(app_rules.MIC, CONTROL_CENTER, True, "settings")
        key = app_rules.normalize_app(CONTROL_CENTER["id"], CONTROL_CENTER["name"])
        assert app.mic_unignored_builtins == []
        assert app.mic_ignored_apps == []           # still not a user addition
        assert key in app._ignores(app_rules.MIC)    # back to ignored, via the builtins set
    finally:
        root.destroy()


# --- fullscreen signal never touches mic_unignored_builtins ---

def test_fullscreen_add_and_remove_leave_mic_unignored_builtins_untouched(tmp_path):
    app_rules, app, root = _app(tmp_path)
    try:
        app._toggle_ignore(app_rules.FULLSCREEN, SLIDES, True, "chip")
        assert app.fullscreen_ignored_apps == [{"id": SLIDES["id"], "name": SLIDES["name"]}]
        assert app.mic_unignored_builtins == []
        key = app_rules.normalize_app(SLIDES["id"], SLIDES["name"])
        assert key in app._ignores(app_rules.FULLSCREEN)

        app._toggle_ignore(app_rules.FULLSCREEN, SLIDES, False, "chip")
        assert app.fullscreen_ignored_apps == []
        assert app.mic_unignored_builtins == []
        assert key not in app._ignores(app_rules.FULLSCREEN)
    finally:
        root.destroy()

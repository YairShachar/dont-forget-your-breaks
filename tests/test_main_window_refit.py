"""The main window is PLACED once, at launch; a later refit only resizes it.

Regression: growing the window (update banner, snooze rows) re-applied the
remembered launch position, so a window the user had dragged jumped back.

Tk-gated (self-skips headless) — it needs a real window to read x/y back.
"""
import json
import pytest

tk = pytest.importorskip("tkinter")

SAVED_GEOMETRY = "300x200+300+200"          # what prefs remember from last time
SAVED_POSITION = (300, 200)
MOVED_TO = (700, 400)                       # where the user drags it


def _app(tmp_path):
    """A real BreakApp on isolated prefs/events, with the network update check off."""
    ctk = pytest.importorskip("customtkinter")
    import launch
    launch.CONFIG_FILE = tmp_path / "prefs.json"
    launch.EVENTS_FILE = tmp_path / "events.jsonl"
    launch.CONFIG_FILE.write_text(json.dumps(
        {"window_geometry": SAVED_GEOMETRY, "check_for_updates": False}))
    try:
        root = ctk.CTk()
    except tk.TclError:
        pytest.skip("no display available")
    app = launch.BreakApp(root)
    root.update_idletasks()
    root.update()
    return app, root


def _position(root):
    root.update_idletasks()
    root.update()
    return (root.winfo_x(), root.winfo_y())


def test_launch_restores_the_remembered_position(tmp_path):
    app, root = _app(tmp_path)
    try:
        assert _position(root) == SAVED_POSITION
    finally:
        root.destroy()


def test_a_refit_leaves_a_moved_window_where_the_user_put_it(tmp_path):
    app, root = _app(tmp_path)
    try:
        root.geometry("+{}+{}".format(*MOVED_TO))
        assert _position(root) == MOVED_TO
        app._show_update_banner("9.9.9")          # grows the window -> refit
        assert _position(root) == MOVED_TO
    finally:
        root.destroy()

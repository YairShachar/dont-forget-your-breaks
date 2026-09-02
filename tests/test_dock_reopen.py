"""Clicking the Dock icon must bring the window back when it's minimized.

macOS delivers a Dock reopen as the Tcl proc ``::tk::mac::ReopenApplication``,
which Tk leaves undefined — so nothing happened at all. Tk-gated + macOS-gated.
"""
import json
import sys
import pytest

tk = pytest.importorskip("tkinter")

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS Dock behavior")

REOPEN = "::tk::mac::ReopenApplication"


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
    return launch.BreakApp(root), root


def _pump(root):
    root.update_idletasks()
    root.update()


def test_the_reopen_handler_is_registered(tmp_path):
    app, root = _app(tmp_path)
    try:
        assert REOPEN in root.tk.call("info", "commands", REOPEN)
    finally:
        root.destroy()


def test_a_dock_reopen_restores_a_minimized_window(tmp_path):
    app, root = _app(tmp_path)
    try:
        root.iconify()
        _pump(root)
        assert root.state() == "iconic"
        root.tk.call(REOPEN)                # what a Dock click delivers
        _pump(root)
        assert root.state() == "normal"
    finally:
        root.destroy()

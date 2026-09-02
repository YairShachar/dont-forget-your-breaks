"""`BreakApp._resolve_held_app` resolves WHO to name for the currently-active
defer signal from the EFFECTIVE (post-hysteresis) signals, in `decide()`'s
priority order (fullscreen before meeting) — and carries the last-known app
across a `smooth_signal` blip, where the raw ctx app drops to None but the
effective signal is still bridged. Regression for #40 review finding 1: naming
the wrong app when both signals are true, and reverting to generic wording
mid-hold on a blip.
"""
import json
import pytest

tk = pytest.importorskip("tkinter")

from dfyb.scheduler.engine import Context

ZOOM = {"id": "us.zoom.xos", "name": "Zoom", "count": 1}
KEYNOTE = {"id": "com.apple.keynote", "name": "Keynote", "count": 1}


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


def _ctx(meeting_app=None, fullscreen_app=None):
    return Context(idle_seconds=0, is_fullscreen=False, is_meeting=False,
                  meeting_app=meeting_app, fullscreen_app=fullscreen_app)


def test_fullscreen_wins_over_meeting_when_both_effective(tmp_path):
    # Mirrors decide()'s priority (fullscreen before meeting, engine.py) so the
    # hero can never name the mic app under the "is in full screen" template.
    app, root = _app(tmp_path)
    try:
        ctx = _ctx(meeting_app=ZOOM, fullscreen_app=KEYNOTE)
        resolved = app._resolve_held_app(True, True, ctx, previous=None)
        assert resolved == KEYNOTE
    finally:
        root.destroy()


def test_carries_the_previous_app_across_a_blip(tmp_path):
    # The effective signal is still bridged by smooth_signal, but this tick's
    # raw ctx app is None (the blip) — the previously-known app must survive.
    app, root = _app(tmp_path)
    try:
        ctx = _ctx(meeting_app=None, fullscreen_app=None)
        resolved = app._resolve_held_app(False, True, ctx, previous=ZOOM)
        assert resolved == ZOOM
    finally:
        root.destroy()


def test_no_stale_carry_once_the_signal_is_off(tmp_path):
    app, root = _app(tmp_path)
    try:
        ctx = _ctx(meeting_app=None, fullscreen_app=None)
        resolved = app._resolve_held_app(False, False, ctx, previous=ZOOM)
        assert resolved is None
    finally:
        root.destroy()


def test_meeting_only_names_the_meeting_app(tmp_path):
    app, root = _app(tmp_path)
    try:
        ctx = _ctx(meeting_app=ZOOM, fullscreen_app=None)
        resolved = app._resolve_held_app(False, True, ctx, previous=None)
        assert resolved == ZOOM
    finally:
        root.destroy()

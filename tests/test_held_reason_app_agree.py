"""Finding 1: the displayed reason, the named app and the chip's signal must all
come from ONE tick's evaluation (#40 final review).

`break_deferred` is deduped to once per sustained deferral episode. The hero's
held-reason used to be driven by that dedup while the named app was re-resolved
every tick, so inside one episode the two drifted: still on a call (reason stuck
at "meeting") while a newly-fullscreen app was named, giving
"Waiting — Keynote is using your microphone" and an Ignore button that wrote
Keynote into the MICROPHONE ignore list.

Two layers: the pure composition (no Tk) and the real timer-loop body.
"""
import json

import pytest

from dfyb.activity.event_log import BREAK_DEFERRED
from dfyb.scheduler.engine import BreakState, Context
from dfyb.scheduler.tick import advance

ZOOM = {"id": "us.zoom.xos", "name": "Zoom", "count": 1}
KEYNOTE = {"id": "com.apple.iWork.Keynote", "name": "Keynote", "count": 1}


def _due():
    return [BreakState(remaining=1, interval_seconds=600, duration_seconds=15)]


def _held():
    """A break already clamped at 0 — held, mid-episode."""
    return [BreakState(remaining=0, interval_seconds=600, duration_seconds=15)]


# --- pure: the dedup no longer decides what the UI may display ---------------

def test_reason_stays_fresh_inside_a_deduped_episode():
    on_call = Context(idle_seconds=0.0, is_fullscreen=False, is_meeting=True,
                      active_idle_seconds=0.0, meeting_app=ZOOM)
    first = advance(_due(), on_call, None)
    assert first.events == [(BREAK_DEFERRED, {"reason": "meeting",
                                              "app": ZOOM["id"],
                                              "app_name": ZOOM["name"],
                                              "holder_count": ZOOM["count"]})]
    assert (first.defer_reason, first.defer_app) == ("meeting", ZOOM)

    # Still on the call, and now Keynote goes fullscreen. SAME episode.
    also_fullscreen = Context(idle_seconds=0.0, is_fullscreen=True, is_meeting=True,
                              active_idle_seconds=0.0,
                              meeting_app=ZOOM, fullscreen_app=KEYNOTE)
    second = advance(_held(), also_fullscreen, first.episode)
    assert second.events == []              # the once-per-episode dedup is intact...
    assert second.defer_reason == "fullscreen"   # ...and the reason is still fresh
    assert second.defer_app == KEYNOTE


# --- wired: one real pass through BreakApp.timer_loop ------------------------

tk = pytest.importorskip("tkinter")


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
    return launch, launch.BreakApp(root), root


def _run_ticks(monkeypatch, launch, app, contexts):
    """Drive `timer_loop` for exactly len(contexts) ticks with scripted sensors."""
    monkeypatch.setattr(launch.time, "sleep", lambda _s: None)
    queue = list(contexts)
    monkeypatch.setattr(launch, "read_context", lambda **_kw: queue.pop(0))
    monkeypatch.setattr(launch, "timer_should_continue",
                        lambda *_a, **_kw: bool(queue))
    app.running = True
    app.timer_loop(app._timer_generation)


def test_timer_loop_reason_and_named_app_cannot_disagree(tmp_path, monkeypatch):
    launch, app, root = _app(tmp_path)
    try:
        for config in app.breaks:
            config.remaining = 1          # every break due on the first tick
        on_call = Context(idle_seconds=0.0, is_fullscreen=False,
                                 is_meeting=True, active_idle_seconds=0.0,
                                 meeting_app=ZOOM)
        call_plus_fullscreen = Context(
            idle_seconds=0.0, is_fullscreen=True, is_meeting=True,
            active_idle_seconds=0.0, meeting_app=ZOOM, fullscreen_app=KEYNOTE)

        _run_ticks(monkeypatch, launch, app, [on_call, call_plus_fullscreen])

        # Tick 2 emitted no new break_deferred (same episode) — yet the reason
        # moved with the app instead of staying stuck on "meeting".
        deferred = [json.loads(l) for l in launch.EVENTS_FILE.read_text().splitlines()
                    if json.loads(l)["type"] == BREAK_DEFERRED]
        assert len(deferred) == 1 and deferred[0]["data"]["reason"] == "meeting"
        assert app._held == "fullscreen"
        assert app._held_app == KEYNOTE

        # ...and the chip acts on the SAME evaluation: fullscreen, not mic.
        app._render_status()
        assert app._chip_action == ("fullscreen", KEYNOTE)
        assert "full screen" in app.hero_headline.cget("text")
    finally:
        root.destroy()


def test_timer_loop_names_no_app_once_the_carry_budget_runs_out(tmp_path, monkeypatch):
    """Attribution goes permanently unavailable mid-hold: the name must fade out
    after the carry budget, not stay pinned to a stale app forever."""
    from dfyb.scheduler.engine import HELD_APP_CARRY_TICKS
    launch, app, root = _app(tmp_path)
    try:
        for config in app.breaks:
            config.remaining = 1
        named = Context(idle_seconds=0.0, is_fullscreen=False, is_meeting=True,
                               active_idle_seconds=0.0, meeting_app=ZOOM)
        blind = Context(idle_seconds=0.0, is_fullscreen=False, is_meeting=True,
                               active_idle_seconds=0.0, meeting_app=None)

        _run_ticks(monkeypatch, launch, app,
                   [named] + [blind] * (HELD_APP_CARRY_TICKS + 1))

        assert app._held == "meeting"      # still held...
        assert app._held_app is None       # ...but no longer naming a stale app
    finally:
        root.destroy()


def test_ignoring_from_the_chip_does_not_freeze_the_hero_out_of_holding(tmp_path,
                                                                       monkeypatch):
    """The aggravating half of Finding 1: `_handle_chip_ignore` blanked `_held`
    but left the episode marker at DEFERRED, so a still-deferring context emitted
    no fresh break_deferred and the hero sat on a frozen 0:00 instead of Holding.
    """
    launch, app, root = _app(tmp_path)
    try:
        for config in app.breaks:
            config.remaining = 1
        on_call = Context(idle_seconds=0.0, is_fullscreen=False, is_meeting=True,
                          active_idle_seconds=0.0, meeting_app=ZOOM)
        _run_ticks(monkeypatch, launch, app, [on_call])
        app._render_status()
        assert app._chip_action == ("mic", ZOOM)

        app._handle_chip_ignore()
        assert app._held is None and app._episode is None   # nothing stale left over

        # Zoom is excused now, but Keynote still covers the screen: the very next
        # tick must put the hero back into Holding and log the new deferral.
        still_held = Context(idle_seconds=0.0, is_fullscreen=True, is_meeting=False,
                             active_idle_seconds=0.0, fullscreen_app=KEYNOTE)
        _run_ticks(monkeypatch, launch, app, [still_held])
        assert app._held == "fullscreen" and app._held_app == KEYNOTE
        reasons = [json.loads(l)["data"]["reason"]
                   for l in launch.EVENTS_FILE.read_text().splitlines()
                   if json.loads(l)["type"] == BREAK_DEFERRED]
        assert reasons == ["meeting", "fullscreen"]
    finally:
        root.destroy()

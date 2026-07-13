from dfyb.insights.transparency import track_held, held_message
from dfyb.activity.event_log import BREAK_DEFERRED, NATURAL_BREAK

DEFER = [(BREAK_DEFERRED, {"reason": "meeting"})]
NATURAL = [(NATURAL_BREAK, {"idle_seconds": 400})]


def test_track_held_defer_carries_reason():
    # a defer this tick -> nothing to show, carry the reason forward
    assert track_held(DEFER, fired=False, prev_held=None) == (None, "meeting")


def test_track_held_dedup_tick_keeps_prev():
    # deduped defer tick (no events) while held -> keep carrying the reason
    assert track_held([], fired=False, prev_held="meeting") == (None, "meeting")


def test_track_held_fire_after_held_shows_and_clears():
    # break fires after being held -> show the carried reason, then clear
    assert track_held([], fired=True, prev_held="fullscreen") == ("fullscreen", None)


def test_track_held_normal_fire_shows_nothing():
    assert track_held([], fired=True, prev_held=None) == (None, None)


def test_track_held_natural_break_clears():
    assert track_held(NATURAL, fired=False, prev_held="away") == (None, None)


def test_held_message_maps_each_reason():
    assert held_message("meeting") == "Waited while your microphone was in use."
    assert held_message("fullscreen") == "Waited while you were in full screen."
    assert held_message("away") == "Waited until you were back."
    assert held_message("nonsense") is None
    assert held_message(None) is None


def test_held_message_active():
    assert held_message("active") == "Waited for a pause in your activity."


from dfyb.insights.transparency import holding_message, holding_cue


def test_holding_message_maps_each_reason():
    assert holding_message("meeting") == "waiting until your mic is free…"
    assert holding_message("fullscreen") == "waiting for full screen to end…"
    assert holding_message("away") == "waiting until you're back…"
    assert holding_message("active") == "waiting for a pause…"


def test_holding_message_unknown_or_none():
    assert holding_message("nonsense") is None
    assert holding_message(None) is None


def test_holding_cue_shows_when_due_and_held():
    assert holding_cue(0, "active") == "waiting for a pause…"
    assert holding_cue(0, "meeting") == "waiting until your mic is free…"


def test_holding_cue_none_when_not_due():
    assert holding_cue(5, "active") is None


def test_holding_cue_none_when_not_held():
    assert holding_cue(0, None) is None


def test_holding_cue_none_for_unknown_reason():
    assert holding_cue(0, "nonsense") is None

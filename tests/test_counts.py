from dfyb.insights.counts import (
    snooze_count_since_taken, first_snooze_seconds_ago, snooze_summary_label)
from dfyb.activity.event_log import (
    BREAK_SNOOZED, BREAK_TAKEN, NATURAL_BREAK, SESSION_STARTED)


def ev(etype, ts=0, **data):
    return {"ts": ts, "type": etype, "data": data, "v": 1}


# --- a Start begins a fresh cycle: stale snoozes must not carry over (#69) ---

def test_count_resets_on_session_started():
    events = [ev(BREAK_SNOOZED, name="Micro"), ev(BREAK_SNOOZED, name="Micro"),
              ev(SESSION_STARTED),
              ev(BREAK_SNOOZED, name="Micro")]
    assert snooze_count_since_taken(events, "Micro") == 1


def test_first_snooze_ago_resets_on_session_started():
    events = [ev(BREAK_SNOOZED, name="Micro", ts=0),
              ev(SESSION_STARTED, ts=100),
              ev(BREAK_SNOOZED, name="Micro", ts=200)]
    assert first_snooze_seconds_ago(events, "Micro", now=250) == 50


# --- snooze_count_since_taken ---

def test_count_no_events():
    assert snooze_count_since_taken([], "Micro") == 0


def test_count_snoozes_no_reset():
    events = [ev(BREAK_SNOOZED, name="Micro"), ev(BREAK_SNOOZED, name="Micro"),
              ev(BREAK_SNOOZED, name="Micro")]
    assert snooze_count_since_taken(events, "Micro") == 3


def test_count_resets_on_taken_same_break():
    events = [ev(BREAK_SNOOZED, name="Micro"),
              ev(BREAK_TAKEN, name="Micro"),
              ev(BREAK_SNOOZED, name="Micro")]
    assert snooze_count_since_taken(events, "Micro") == 1


def test_count_not_reset_by_other_breaks_take():
    events = [ev(BREAK_SNOOZED, name="Micro"),
              ev(BREAK_TAKEN, name="Normal"),
              ev(BREAK_SNOOZED, name="Micro")]
    assert snooze_count_since_taken(events, "Micro") == 2


def test_count_resets_on_natural_break():
    events = [ev(BREAK_SNOOZED, name="Micro"),
              ev(NATURAL_BREAK, idle_seconds=400),
              ev(BREAK_SNOOZED, name="Micro")]
    assert snooze_count_since_taken(events, "Micro") == 1


def test_count_ignores_other_break_snoozes():
    events = [ev(BREAK_SNOOZED, name="Normal"), ev(BREAK_SNOOZED, name="Micro")]
    assert snooze_count_since_taken(events, "Micro") == 1


# --- first_snooze_seconds_ago ---

def test_first_snooze_none_when_no_snooze():
    assert first_snooze_seconds_ago([], "Micro", now=1000) is None


def test_first_snooze_uses_first_in_cycle():
    events = [ev(BREAK_SNOOZED, ts=100, name="Micro"),
              ev(BREAK_SNOOZED, ts=400, name="Micro")]
    assert first_snooze_seconds_ago(events, "Micro", now=1000) == 900


def test_first_snooze_anchors_after_taken():
    events = [ev(BREAK_SNOOZED, ts=100, name="Micro"),
              ev(BREAK_TAKEN, ts=200, name="Micro"),
              ev(BREAK_SNOOZED, ts=700, name="Micro")]
    assert first_snooze_seconds_ago(events, "Micro", now=1000) == 300


# --- snooze_summary_label ---

def test_label_zero_is_none():
    assert snooze_summary_label(0, None) is None


def test_label_once():
    assert snooze_summary_label(1, 180) == "Snoozed once already (originally due 3 min ago)"


def test_label_plural():
    assert snooze_summary_label(2, 900) == "Snoozed 2× already (originally due 15 min ago)"


def test_label_sub_minute():
    assert snooze_summary_label(2, 30) == "Snoozed 2× already (originally due less than a minute ago)"


def test_label_no_time():
    assert snooze_summary_label(2, None) == "Snoozed 2× already"

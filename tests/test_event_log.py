from dfyb.activity.event_log import EventLog, BREAK_TAKEN, BREAK_SKIPPED


class FakeClock:
    """Deterministic monotonically-increasing clock for tests."""
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        self.t += 1
        return self.t


def test_append_returns_event(tmp_path):
    log = EventLog(tmp_path / "events.jsonl", clock=FakeClock())
    event = log.append(BREAK_TAKEN, break_name="Micro Break")
    assert event["type"] == BREAK_TAKEN
    assert event["data"] == {"break_name": "Micro Break"}
    assert event["ts"] == 1001.0


def test_read_empty_when_no_file(tmp_path):
    log = EventLog(tmp_path / "missing.jsonl")
    assert log.read() == []


def test_append_then_read_roundtrip(tmp_path):
    log = EventLog(tmp_path / "events.jsonl", clock=FakeClock())
    log.append(BREAK_TAKEN, break_name="A")
    log.append(BREAK_SKIPPED, break_name="B")
    events = log.read()
    assert [e["type"] for e in events] == [BREAK_TAKEN, BREAK_SKIPPED]
    assert events[1]["data"]["break_name"] == "B"


def test_persists_across_instances(tmp_path):
    path = tmp_path / "events.jsonl"
    EventLog(path, clock=FakeClock()).append(BREAK_TAKEN)
    reopened = EventLog(path)
    assert reopened.count() == 1


def test_count_by_type(tmp_path):
    log = EventLog(tmp_path / "events.jsonl", clock=FakeClock())
    log.append(BREAK_TAKEN)
    log.append(BREAK_TAKEN)
    log.append(BREAK_SKIPPED)
    assert log.count(BREAK_TAKEN) == 2
    assert log.count() == 3


def test_phase1_event_constants_exist():
    from dfyb.activity.event_log import BREAK_DEFERRED, NATURAL_BREAK
    assert BREAK_DEFERRED == "break_deferred"
    assert NATURAL_BREAK == "natural_break"


def test_break_fired_constant_exists():
    from dfyb.activity.event_log import BREAK_FIRED
    assert BREAK_FIRED == "break_fired"


def test_append_stamps_schema_version(tmp_path):
    from dfyb.activity.event_log import EventLog, SCHEMA_VERSION
    log = EventLog(tmp_path / "e.jsonl", clock=lambda: 1.0)
    event = log.append("break_taken", name="Micro")
    assert event["v"] == SCHEMA_VERSION
    assert log.read()[0]["v"] == SCHEMA_VERSION


def test_read_tolerates_unversioned_events(tmp_path):
    from dfyb.activity.event_log import EventLog
    p = tmp_path / "e.jsonl"
    p.write_text('{"ts": 1.0, "type": "break_taken", "data": {}}\n')  # old, no "v"
    events = EventLog(p).read()
    assert events == [{"ts": 1.0, "type": "break_taken", "data": {}}]


def test_new_analyzable_events_defined():
    from dfyb.activity import event_log as el
    assert el.BREAK_RESCHEDULED == "break_rescheduled"
    assert el.SESSION_RESUMED == "session_resumed"
    assert el.APP_UPDATED == "app_updated"


def test_resume_prompt_constants_exist():
    from dfyb.activity.event_log import (
        RESUME_PROMPTED, RESUME_ACCEPTED, RESUME_DISMISSED)
    assert RESUME_PROMPTED == "resume_prompted"
    assert RESUME_ACCEPTED == "resume_accepted"
    assert RESUME_DISMISSED == "resume_dismissed"


def test_mic_detection_fallback_constant_exists():
    from dfyb.activity import event_log
    assert event_log.MIC_DETECTION_FALLBACK == "mic_detection_fallback"


def test_app_ignore_event_constants_exist():
    from dfyb.activity import event_log
    assert event_log.APP_IGNORE_ADDED == "app_ignore_added"
    assert event_log.APP_IGNORE_REMOVED == "app_ignore_removed"

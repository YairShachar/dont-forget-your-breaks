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

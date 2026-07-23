from dfyb.session import (build_snapshot, parse_snapshot, should_resume,
                          remaining_by_name, snoozes_to_restore, SESSION_SCHEMA_VERSION)


def _snap(**over):
    s = dict(saved_at=1000.0, resumable=True, running=True, paused=False,
             breaks=[("Micro", 12), ("Normal", 3000)],
             snoozes=[{"name": "Micro", "fire_time": 1200.0, "break_data": {"name": "Micro"}}])
    s.update(over)
    return build_snapshot(**s)


def test_build_parse_round_trip():
    snap = _snap()
    assert parse_snapshot(snap) == snap
    assert snap["schema_version"] == SESSION_SCHEMA_VERSION
    assert snap["breaks"] == [{"name": "Micro", "remaining": 12},
                              {"name": "Normal", "remaining": 3000}]


def test_parse_rejects_malformed():
    assert parse_snapshot(None) is None
    assert parse_snapshot("nope") is None
    assert parse_snapshot({"schema_version": 999}) is None          # wrong version
    bad = _snap(); del bad["running"]
    assert parse_snapshot(bad) is None                              # missing key
    bad2 = _snap(); bad2["saved_at"] = "x"
    assert parse_snapshot(bad2) is None                             # bad saved_at


def test_should_resume_gates():
    assert should_resume(_snap(saved_at=1000.0), now=1300.0, window_seconds=600) is True
    assert should_resume(_snap(resumable=False), now=1300.0, window_seconds=600) is False
    assert should_resume(_snap(saved_at=1000.0), now=2000.0, window_seconds=600) is False  # too old
    assert should_resume(None, now=1300.0, window_seconds=600) is False
    assert should_resume(_snap(saved_at=1000.0), now=900.0, window_seconds=600) is False   # clock back


def test_remaining_by_name_matches_and_skips():
    snap = _snap()
    assert remaining_by_name(snap, ["Micro", "Normal"]) == {"Micro": 12, "Normal": 3000}
    assert remaining_by_name(snap, ["Micro"]) == {"Micro": 12}          # skip absent config
    assert remaining_by_name(snap, ["Ghost"]) == {}                     # no overlap


def test_snoozes_to_restore_computes_remaining_and_fire_now():
    snap = _snap()  # snooze fire_time 1200
    [pending] = snoozes_to_restore(snap, now=1100.0)
    assert pending["remaining"] == 100.0 and pending["fire_now"] is False
    [lapsed] = snoozes_to_restore(snap, now=1500.0)
    assert lapsed["remaining"] == 0.0 and lapsed["fire_now"] is True
    assert lapsed["break_data"] == {"name": "Micro"}

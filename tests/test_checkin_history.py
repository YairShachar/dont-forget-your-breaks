from dfyb.checkins.history import todays_check_ins, format_check_in_value
from dfyb.activity.event_log import CHECK_IN

DAY = 86400
def ev(ts, **data): return {"ts": ts, "type": CHECK_IN, "data": data}


def test_todays_filters_and_sorts():
    now = 1_000_000.0
    evs = [ev(now, question="A", value=3),
           ev(now - 10, question="B", value=1),
           ev(now - 2 * DAY, question="Old", value=5),          # not today
           {"ts": now, "type": "break_taken", "data": {}}]      # not a check-in
    rows = todays_check_ins(evs, now)
    assert [r["question"] for r in rows] == ["B", "A"]          # today only, oldest->newest


def test_format_value():
    assert format_check_in_value({"value": 4, "note": "tired"}) == "4 · tired"
    assert format_check_in_value({"value": "OK", "note": None}) == "OK"
    assert format_check_in_value({"value": None, "note": None}) == "—"


def test_rows_include_question_id():
    now = 1_000_000.0
    rows = todays_check_ins([ev(now, question_id="sleep", question="Sleep?", value="OK")], now)
    assert rows[0]["question_id"] == "sleep"


def test_dedupe_once_per_day_keeps_latest_only_for_flagged():
    from dfyb.checkins.history import dedupe_once_per_day
    now = 1_000_000.0
    evs = [ev(now - 100, question_id="sleep", question="Sleep?", value="Rough"),
           ev(now - 10, question_id="sleep", question="Sleep?", value="Great"),
           ev(now - 50, question_id="refreshed", question="Refreshed?", value=2),
           ev(now - 5, question_id="refreshed", question="Refreshed?", value=4)]
    out = dedupe_once_per_day(todays_check_ins(evs, now), {"sleep"})
    sleeps = [r for r in out if r["question_id"] == "sleep"]
    refresh = [r for r in out if r["question_id"] == "refreshed"]
    assert len(sleeps) == 1 and sleeps[0]["value"] == "Great"   # latest sleep only
    assert len(refresh) == 2                                     # both refreshed kept


def test_rows_expose_id_fallback_to_ts():
    now = 1_000_000.0
    rows = todays_check_ins([ev(now, question_id="a", value=1)], now)
    assert rows[0]["id"] == str(now)          # legacy event: id falls back to str(ts)


def test_fold_applies_edits_latest_wins():
    now = 1_000_000.0
    evs = [ev(now - 100, id="x", question_id="a", value=1),
           ev(now - 50, edits="x", value=2),
           ev(now - 10, edits="x", value=5)]     # latest edit wins
    rows = todays_check_ins(evs, now)
    assert len(rows) == 1 and rows[0]["value"] == 5 and rows[0]["ts"] == now - 100  # ts preserved


def test_fold_applies_removes():
    now = 1_000_000.0
    evs = [ev(now - 100, id="x", question_id="a", value=1),
           ev(now - 40, id="y", question_id="a", value=2),
           ev(now - 10, removes="x")]
    rows = todays_check_ins(evs, now)
    assert [r["id"] for r in rows] == ["y"]      # x removed, y stays

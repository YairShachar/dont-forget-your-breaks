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

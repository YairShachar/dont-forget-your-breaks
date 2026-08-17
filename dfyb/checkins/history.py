"""Pure read helpers over CHECK_IN events (no tk/ctk)."""
from datetime import date
from dfyb.activity.event_log import CHECK_IN


def todays_check_ins(events, now):
    """Answered check-ins from today (local tz), oldest->newest. Each row is a dict:
    ts, question, value, note, answer_type."""
    today = date.fromtimestamp(now)
    rows = []
    for e in events:
        if e.get("type") != CHECK_IN:
            continue
        ts = e.get("ts", 0)
        if date.fromtimestamp(ts) != today:
            continue
        d = e.get("data", {})
        rows.append({"ts": ts, "question": d.get("question", ""),
                     "value": d.get("value"), "note": d.get("note"),
                     "answer_type": d.get("answer_type")})
    rows.sort(key=lambda r: r["ts"])
    return rows


def format_check_in_value(row):
    """Short 'value · note' summary of an answer; '—' if both empty."""
    parts = []
    if row.get("value") is not None:
        parts.append(str(row["value"]))
    if row.get("note"):
        parts.append(str(row["note"]))
    return " · ".join(parts) if parts else "—"

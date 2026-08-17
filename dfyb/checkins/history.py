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
        rows.append({"ts": ts, "question_id": d.get("question_id", ""),
                     "question": d.get("question", ""),
                     "value": d.get("value"), "note": d.get("note"),
                     "answer_type": d.get("answer_type")})
    rows.sort(key=lambda r: r["ts"])
    return rows


def dedupe_once_per_day(rows, once_per_day_ids):
    """Collapse once-per-day questions to their latest answer today; keep every answer
    for other questions. `rows` is oldest->newest; the result preserves that order."""
    once = set(once_per_day_ids)
    latest = {}
    for r in rows:
        qid = r.get("question_id")
        if qid in once:
            latest[qid] = max(latest.get(qid, 0), r["ts"])
    out = []
    for r in rows:
        qid = r.get("question_id")
        if qid in once and r["ts"] != latest.get(qid):
            continue
        out.append(r)
    return out


def format_check_in_value(row):
    """Short 'value · note' summary of an answer; '—' if both empty."""
    parts = []
    if row.get("value") is not None:
        parts.append(str(row["value"]))
    if row.get("note"):
        parts.append(str(row["note"]))
    return " · ".join(parts) if parts else "—"

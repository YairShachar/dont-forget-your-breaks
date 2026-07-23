"""Pure session-snapshot logic for crash/update resume. No Tk, no I/O."""

SESSION_SCHEMA_VERSION = 1
_REQUIRED = ("saved_at", "resumable", "running", "paused", "breaks", "snoozes")


def build_snapshot(*, saved_at, resumable, running, paused, breaks, snoozes):
    """`breaks`: list of (name, remaining). `snoozes`: list of {name, fire_time, break_data}."""
    return {
        "schema_version": SESSION_SCHEMA_VERSION,
        "saved_at": saved_at,
        "resumable": bool(resumable),
        "running": bool(running),
        "paused": bool(paused),
        "breaks": [{"name": n, "remaining": r} for n, r in breaks],
        "snoozes": list(snoozes),
    }


def parse_snapshot(raw):
    """A validated snapshot dict, or None if malformed / wrong schema (fail safe)."""
    if not isinstance(raw, dict):
        return None
    if raw.get("schema_version") != SESSION_SCHEMA_VERSION:
        return None
    if not all(k in raw for k in _REQUIRED):
        return None
    if not isinstance(raw["saved_at"], (int, float)):
        return None
    return raw


def should_resume(snapshot, now, window_seconds):
    """Resume iff the snapshot exists, is marked resumable, and the downtime is recent
    (0 <= now - saved_at <= window). A purposeful quit clears `resumable`."""
    if not snapshot or not snapshot.get("resumable"):
        return False
    downtime = now - snapshot["saved_at"]
    return 0 <= downtime <= window_seconds


def remaining_by_name(snapshot, config_names):
    """{name: remaining} for breaks present in BOTH the snapshot and config_names."""
    names = set(config_names)
    return {b["name"]: b["remaining"] for b in snapshot.get("breaks", [])
            if b.get("name") in names}


def snoozes_to_restore(snapshot, now):
    """Each snooze as {name, break_data, fire_time, remaining, fire_now}."""
    out = []
    for s in snapshot.get("snoozes", []):
        remaining = max(0.0, s["fire_time"] - now)
        out.append({"name": s["name"], "break_data": s["break_data"],
                    "fire_time": s["fire_time"], "remaining": remaining,
                    "fire_now": remaining <= 0})
    return out

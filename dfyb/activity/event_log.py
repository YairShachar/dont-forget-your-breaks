"""Append-only, persisted activity/break event log (JSON Lines).

The shared spine of the app: the scheduler (Phase 1) reads it to decide when
to nudge, and insights (Phase 3) read it to build dashboards. Pass a custom
`clock` for deterministic tests.
"""
import json
import time
from pathlib import Path

# Event type constants (extended as later phases need them).
BREAK_DUE = "break_due"
BREAK_TAKEN = "break_taken"
BREAK_SKIPPED = "break_skipped"
BREAK_SNOOZED = "break_snoozed"
BREAK_SNOOZE_CANCELLED = "break_snooze_cancelled"
BREAK_SNOOZE_RETURNED = "break_snooze_returned"
IDLE_DETECTED = "idle_detected"
BREAK_DEFERRED = "break_deferred"
NATURAL_BREAK = "natural_break"
SESSION_STARTED = "session_started"   # user pressed Start — begins a fresh break cycle
BREAK_RESCHEDULED = "break_rescheduled"   # one-time nudge of the next break sooner/later
SESSION_RESUMED = "session_resumed"       # timers/snoozes restored after a crash/update relaunch
APP_UPDATED = "app_updated"               # a self-update applied a new version

# Event record schema version. Bump when the event shape changes; readers may
# branch on it. Old records lacking "v" are treated as unversioned.
SCHEMA_VERSION = 1


class EventLog:
    """Append-only JSON Lines event store."""

    def __init__(self, path, clock=time.time):
        self.path = Path(path)
        self._clock = clock

    def append(self, event_type, **data):
        """Append an event and return it. Each event: {ts, type, data, v}."""
        event = {"ts": self._clock(), "type": event_type,
                 "data": data, "v": SCHEMA_VERSION}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
        return event

    def read(self):
        """Return all events as a list of dicts (empty if the file is absent)."""
        if not self.path.exists():
            return []
        events = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events

    def count(self, event_type=None):
        """Count all events, or only those of `event_type`."""
        if event_type is None:
            return len(self.read())
        return sum(1 for e in self.read() if e["type"] == event_type)

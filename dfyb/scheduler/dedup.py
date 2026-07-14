"""Break dedup predicate. Pure (no Tk, no I/O) — unit-tested."""


def break_in_play(name, active_name, queued_names, pending_names):
    """True if a break named `name` is already showing (active_name), queued, or
    pending-snoozed — so a new trigger would stack a duplicate."""
    return name == active_name or name in queued_names or name in pending_names

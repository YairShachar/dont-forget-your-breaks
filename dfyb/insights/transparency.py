"""Make the invisible timing intelligence visible: track WHY a break was held
(deferred) so the popup can say so. Pure (no Tk, no I/O) — unit-tested."""
from dfyb.activity.event_log import BREAK_DEFERRED, NATURAL_BREAK

# reason -> the calm line shown under the break title when it was held.
HELD_MESSAGES = {
    "meeting": "Waited while you were in a meeting.",
    "fullscreen": "Waited while you were in full screen.",
    "away": "Waited until you were back.",
}


def track_held(events, fired, prev_held):
    """Fold this tick's events into a carried held-reason.

    Returns (held_to_show, new_held): `held_to_show` is the reason to display on
    THIS fire (None if not firing / not held); `new_held` is carried to the next
    tick. A defer records its reason; a natural break clears it; a fire surfaces
    then clears it.
    """
    held = prev_held
    for event_type, data in events:
        if event_type == BREAK_DEFERRED:
            held = data.get("reason")
        elif event_type == NATURAL_BREAK:
            held = None
    if fired:
        return held, None
    return None, held


def held_message(reason):
    """The calm line for a held break, or None for no/unknown reason."""
    return HELD_MESSAGES.get(reason)

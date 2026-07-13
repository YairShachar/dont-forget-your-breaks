"""Make the invisible timing intelligence visible: track WHY a break was held
(deferred) so the popup can say so. Pure (no Tk, no I/O) — unit-tested."""
from dfyb.activity.event_log import BREAK_DEFERRED, NATURAL_BREAK

# reason -> the calm line shown under the break title when it was held.
HELD_MESSAGES = {
    "meeting": "Waited while your microphone was in use.",
    "fullscreen": "Waited while you were in full screen.",
    "away": "Waited until you were back.",
    "active": "Waited for a pause in your activity.",
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


# reason -> the calm live line shown while a due break is still being held.
# Present-tense counterpart to HELD_MESSAGES (which is shown after it fires).
HOLDING_MESSAGES = {
    "meeting": "waiting until your mic is free…",
    "fullscreen": "waiting for full screen to end…",
    "away": "waiting until you're back…",
    "active": "waiting for a pause…",
}


def holding_message(reason):
    """Present-tense live cue for a currently-held break (or None)."""
    return HOLDING_MESSAGES.get(reason)


def holding_cue(remaining, held_reason):
    """Live cue text for a break card, or None when it isn't being held.

    A break is 'held' when it is due (remaining clamped to 0) and a defer
    reason is active.
    """
    if remaining == 0 and held_reason:
        return holding_message(held_reason)
    return None

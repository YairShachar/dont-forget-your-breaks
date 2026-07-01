"""Adapt the app's (Tk-bound) BreakConfig objects to plain BreakState snapshots."""
from dfyb.scheduler.engine import BreakState


def states_from_configs(configs):
    """Map an iterable of BreakConfig-like objects to a list[BreakState].

    Each config must expose `.remaining`, `.get_interval_seconds()`,
    `.get_duration_seconds()`. This is the single place BreakConfig is read into
    the pure engine's value type — the engine never sees a BreakConfig.
    """
    return [
        BreakState(
            remaining=c.remaining,
            interval_seconds=c.get_interval_seconds(),
            duration_seconds=c.get_duration_seconds(),
        )
        for c in configs
    ]

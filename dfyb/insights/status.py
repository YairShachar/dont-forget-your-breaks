"""Pure status model for the main-window cockpit hero.

Turns raw app state into a StatusView the widget layer renders verbatim. No
tk/ctk import — headless-testable. `dot` is a semantic key ('good'/'warning'/
'idle') mapped to a color token by the caller.
"""
from dataclasses import dataclass


def format_countdown(seconds):
    """'M:SS', or 'H:MM:SS' past an hour. Negatives floor to '0:00'."""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02}:{s:02}"
    return f"{m}:{s:02}"


def progress_fraction(remaining, interval):
    """How far through the current interval, clamped [0, 1]. 0 if interval<=0."""
    if interval <= 0:
        return 0.0
    return max(0.0, min(1.0, 1 - remaining / interval))


@dataclass
class StatusView:
    state: str
    dot: str
    headline: str
    subtext: str
    progress: float
    chip: str | None = None


def compute_status(*, running, paused, held_reason, next_name,
                   next_remaining, next_interval, break_active):
    """Derive the hero view from app state. Order matters: idle → paused →
    holding → break → on-track."""
    if not running:
        return StatusView("idle", "idle", "Idle", "Start when you're ready", 0.0)
    if paused:
        return StatusView("paused", "warning", "Paused", "Breaks are on hold", 0.0)
    if held_reason:
        return StatusView(
            "holding", "warning", f"Waiting — {held_reason}",
            f"{next_name} is due; it'll wait",
            progress_fraction(next_remaining, next_interval),
            chip=f"Breaks pause during {held_reason}")
    if break_active:
        return StatusView("break", "warning", "Break time", next_name, 1.0)
    return StatusView(
        "on_track", "good", f"Next break in {format_countdown(next_remaining)}",
        next_name, progress_fraction(next_remaining, next_interval))

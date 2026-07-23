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


# held-reason key -> (friendly phrase for the headline, tail for the chip)
HELD_LABELS = {
    "meeting": ("you're in a call", "during meetings"),
    "fullscreen": ("you're in full screen", "in full screen"),
    "away": ("you're away", "while you're away"),
    "active": ("you're busy", "during activity"),
}

RESTED_HEADLINE = "Welcome back"
RESTED_SUBTEXT = "That counted as a break — timers reset"


@dataclass
class StatusView:
    state: str
    dot: str
    headline: str
    subtext: str
    progress: float
    chip: str | None = None
    progress_style: str = "none"  # 'none' (flat rail) | 'live' (blue) | 'frozen' (grey)


def compute_status(*, running, paused, held_reason, next_name,
                   next_remaining, next_interval, break_active, just_rested=False):
    """Derive the hero view from app state. Order matters: idle → paused →
    holding → break → on-track. Paused keeps the countdown visible (the pill
    carries the 'Paused' state) and freezes the bar in grey; on-track/holding
    show it live."""
    if not running:
        return StatusView("idle", "idle", "Ready when you are",
                          "Start whenever you like", 0.0)
    if paused:
        return StatusView("paused", "warning",
                          f"Next break in {format_countdown(next_remaining)}",
                          next_name, progress_fraction(next_remaining, next_interval),
                          progress_style="frozen")
    if held_reason:
        label, tail = HELD_LABELS.get(held_reason, (held_reason, f"during {held_reason}"))
        return StatusView(
            "holding", "warning", f"Waiting — {label}",
            f"{next_name} is due; it'll wait",
            progress_fraction(next_remaining, next_interval),
            chip=f"Breaks pause {tail}", progress_style="live")
    if break_active:
        return StatusView("break", "warning", "Break time", next_name, 1.0)
    if just_rested:
        return StatusView(
            "on_track", "good", RESTED_HEADLINE, RESTED_SUBTEXT,
            progress_fraction(next_remaining, next_interval), progress_style="live")
    return StatusView(
        "on_track", "good", f"Next break in {format_countdown(next_remaining)}",
        next_name, progress_fraction(next_remaining, next_interval),
        progress_style="live")

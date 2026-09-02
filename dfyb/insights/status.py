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


# held-reason key -> (friendly phrase for the headline, tail for the chip) when we
# could NOT name the app. Attributed phrasings are built by `held_label` below.
HELD_LABELS = {
    "meeting": ("you're in a call", "during meetings"),
    "fullscreen": ("you're in full screen", "in full screen"),
    "away": ("you're away", "while you're away"),
    "active": ("you're busy", "during activity"),
}

# reason -> "{app} …" headline used when the causing app IS known. Naming the app
# replaces the old assumption that mic-in-use means a call (#40).
ATTRIBUTED_HELD_HEADLINES = {
    "meeting": "{app} is using your microphone",
    "fullscreen": "{app} is in full screen",
}

RESTED_HEADLINE = "Welcome back"
RESTED_SUBTEXT = "That counted as a break — timers reset"

# Proactive chip shown while a deferral context is active but nothing is due yet,
# so you know the upcoming break is being held and why (#74). Reactive holding
# (#44) takes precedence once a break is actually due.
ANTICIPATED_CHIPS = {
    "meeting": "In a call — your break will wait",
    "fullscreen": "Full screen — your break will wait",
    "active": "You're busy — your break will wait",
}


def held_label(reason, app_name=None):
    """(headline phrase, chip tail) for a held break — naming the app when known,
    falling back to today's generic wording when it is not."""
    generic, tail = HELD_LABELS.get(reason, (reason, f"during {reason}"))
    template = ATTRIBUTED_HELD_HEADLINES.get(reason)
    if app_name and template:
        return template.format(app=app_name), tail
    return generic, tail


def anticipated_chip(reason, app_name=None):
    """The proactive 'your break will wait' chip (#74), naming the app when known."""
    template = ATTRIBUTED_HELD_HEADLINES.get(reason)
    if app_name and template:
        return f"{template.format(app=app_name)} — your break will wait"
    return ANTICIPATED_CHIPS.get(reason)


@dataclass
class StatusView:
    state: str
    dot: str
    headline: str
    subtext: str
    progress: float
    chip: str | None = None
    progress_style: str = "none"  # 'none' (flat rail) | 'live' (blue) | 'frozen' (grey)
    # One-click "excuse this app" offered on the chip while attributed (#40/#28).
    # The pure layer never holds a callback — launch.py renders and wires it.
    chip_action_label: str | None = None
    chip_action_signal: str | None = None   # 'mic' | 'fullscreen'


def compute_status(*, running, paused, held_reason, next_name,
                   next_remaining, next_interval, break_active, just_rested=False,
                   anticipated_reason=None, held_app_name=None, anticipated_app_name=None):
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
        label, tail = held_label(held_reason, held_app_name)
        signal = {"meeting": "mic", "fullscreen": "fullscreen"}.get(held_reason)
        return StatusView(
            "holding", "warning", f"Waiting — {label}",
            f"{next_name} is due; it'll wait",
            progress_fraction(next_remaining, next_interval),
            chip=f"Breaks pause {tail}", progress_style="live",
            chip_action_label=(f"Ignore {held_app_name}"
                               if held_app_name and signal else None),
            chip_action_signal=signal if held_app_name else None)
    if break_active:
        return StatusView("break", "warning", "Break time", next_name, 1.0)
    if just_rested:
        return StatusView(
            "on_track", "good", RESTED_HEADLINE, RESTED_SUBTEXT,
            progress_fraction(next_remaining, next_interval), progress_style="live")
    return StatusView(
        "on_track", "good", f"Next break in {format_countdown(next_remaining)}",
        next_name, progress_fraction(next_remaining, next_interval),
        chip=(anticipated_chip(anticipated_reason, anticipated_app_name)
              if anticipated_reason else None),
        progress_style="live")

"""Per-app exceptions to the deferral signals (mic in use, fullscreen).

Pure policy — no Tk, no CoreAudio, no I/O — so it is unit-tested headlessly.
Two flat lists (one per signal) share this one helper deliberately: it is the
seam that issue #28's richer per-app rules table can grow from later without a
preferences migration.

A *holder* is the tuple `(pid, bundle_id, name)` and is the single shape used
for both mic holders and fullscreen window owners, so both signals filter
through the same code.
"""

# Signal names — used as the `signal` dimension on the ignore-change events.
MIC = "mic"
FULLSCREEN = "fullscreen"

# Processes that hold the audio INPUT without implying a call, so they must never
# defer a break. Shipped as code rather than copied into prefs, so a release can
# correct or extend the list without stomping the user's edits; the user can
# still un-ignore any of them (see `effective_ignores`).
DEFAULT_MIC_IGNORED_APPS = [
    # The System Settings > Sound pane opens the input to drive its level meter,
    # and its .appex can outlive the closed window (confirmed 2026-09-01: 18h of
    # false "in a call"). Verified bundle id from the .appex Info.plist.
    {"id": "com.apple.Sound-Settings.extension", "name": "Sound (System Settings)"},
    # Holds the input while the Sound module in Control Center is open.
    {"id": "com.apple.controlcenter", "name": "Control Center"},
    # Siri / dictation daemon — speech, but never a meeting. No bundle id.
    {"id": None, "name": "corespeechd"},
    # Never defer on our own audio (break sounds, future features).
    {"id": "com.yairs.dontforgetyourbreaks", "name": "Dont Forget Your Breaks"},
]

# Empty on purpose: today's behavior is that ANY fullscreen app defers.
DEFAULT_FULLSCREEN_IGNORED_APPS = []


def normalize_app(bundle_id, name):
    """Canonical match key for an app: its bundle id lowercased when present,
    else its display name lowercased. Stable across launches and PID changes."""
    return (bundle_id or name or "").strip().lower()


def effective_ignores(builtins, user_added, user_removed):
    """The set of keys actually ignored for one signal.

    `builtins` and `user_added` are lists of `{"id", "name"}` refs; `user_removed`
    is a list of keys the user un-ignored. Built-ins minus removals, plus the
    user's own additions — so a user addition WINS over a removal of the same key.
    """
    removed = {key.strip().lower() for key in user_removed if key}
    keys = {normalize_app(app.get("id"), app.get("name")) for app in builtins}
    keys -= removed
    keys |= {normalize_app(app.get("id"), app.get("name")) for app in user_added}
    return {key for key in keys if key}


def surviving_holders(holders, ignored):
    """The holders whose key is NOT ignored — the ones that still mean 'busy'."""
    return [h for h in holders if normalize_app(h[1], h[2]) not in ignored]


def primary_holder(holders):
    """Which holder to name in the UI when several qualify: one carrying a bundle
    id (a real app) before a bare daemon, then the lowest pid. Deterministic so
    the chip never flickers between two names. None for an empty list."""
    if not holders:
        return None
    return sorted(holders, key=lambda h: (h[1] is None, h[0]))[0]


def holder_ref(holder):
    """The `{"id", "name"}` JSON shape stored in prefs and logged on events."""
    _pid, bundle_id, name = holder
    return {"id": bundle_id, "name": name}

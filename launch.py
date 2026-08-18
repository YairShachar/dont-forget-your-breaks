import customtkinter as ctk
import tkinter as tk
from PIL import Image
from tkinter import messagebox
import threading
import time
import sys
import subprocess
import json
import os
import atexit
import random
import re
import uuid
import webbrowser
import platform
from dataclasses import replace as dataclass_replace
from urllib.parse import quote as url_quote
import logging
from pathlib import Path
from dfyb.version import parse_version, is_newer_version
from dfyb.breaks.duration import to_seconds, humanize_seconds
from dfyb.sound import play_sound, looping_sound, SOUNDS
from dfyb.updater import (
    get_current_version,
    fetch_latest_version,
    is_installed_via_homebrew,
    should_check_for_updates,
    find_brew,
    app_bundle_from_executable,
    relaunch_command,
    VERSION_FILE,
    HOMEBREW_CASK_NAME,
    BASE_DIR,
)
from dfyb.animation import ease_out_quad, prefers_reduced_motion, lerp_color
from dfyb.geometry import point_in_rect
from dfyb.settings_logic import suboption_state
from dfyb.session import (build_snapshot, parse_snapshot, should_resume,
                          remaining_by_name, snoozes_to_restore)
from dfyb.theme import resolve_font_family, resolve_color
from dfyb.ring import ring_image
from dfyb.activity.event_log import (
    EventLog, BREAK_TAKEN, BREAK_FIRED, BREAK_SNOOZED, BREAK_SKIPPED,
    BREAK_SNOOZE_CANCELLED, BREAK_SNOOZE_RETURNED, SESSION_STARTED,
    BREAK_RESCHEDULED, SESSION_RESUMED, APP_UPDATED,
    RESUME_PROMPTED, RESUME_ACCEPTED, RESUME_DISMISSED, CHECK_IN)
from dfyb.activity.sensors import read_context, frontmost_window_rect, smooth_signal
from dfyb.popup_placement import (screen_for_point, center_on_screen, clamp_onscreen,
                                  main_window_geometry)
from dfyb.scheduler.adapter import states_from_configs
from dfyb.scheduler.tick import (advance, apply_snooze_freeze,
                                 track_due_since, deferral_at_fire, IDLE_EPISODE)
from dfyb.scheduler.reschedule import reschedule_step, reschedule_bounds, nudged_remaining
from dfyb.scheduler.engine import (decide, DEFER, coordinate_thresholds,
                                   AWAY_IDLE_THRESHOLD_SECONDS,
                                   NATURAL_BREAK_IDLE_THRESHOLD_SECONDS)
from dfyb.scheduler.dedup import break_in_play
from dfyb.ui_controls import reset_button_style
from dfyb.timer_lifecycle import timer_should_continue
from dfyb.macos_window import pin_to_active_space
from dfyb.checkins.model import (
    SCALE, NUMBER, CHOICES, NOTE, TIMES_PER_DAY, PER_DAY, PER_WEEK,
    DEFAULT_SCALE_MIN, DEFAULT_SCALE_MAX,
    TRIGGER_BREAK, TRIGGER_ON_DEMAND, answer_is_valid,
)
from dfyb.checkins.history import format_check_in_value
from dfyb.insights.transparency import track_held, held_message, holding_cue
from dfyb.insights.status import compute_status
from dfyb.insights.over_break import format_over_time
from dfyb.snooze import (
    snooze_delay_ms, format_snooze_short, format_snooze_long, custom_snooze_seconds,
    should_hold_snooze, snooze_remaining, next_clear_streak)
from dfyb.resume import resume_prompt_step
from dfyb.insights.counts import (
    snooze_count_since_taken, first_snooze_seconds_ago, snooze_summary_label)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logging.getLogger("PIL").setLevel(logging.WARNING)  # silence PNG-decode debug spam

# ------------------ CUSTOMTKINTER SETUP ------------------

ctk.set_appearance_mode("system")  # Follow system dark/light mode
ctk.set_default_color_theme("blue")  # macOS-style blue accent

APP_NAME = "Don't Forget Your Breaks"
# DFYB_DEV=1 runs a parallel dev instance: its own lock/prefs/events (so it runs
# alongside the real app without clashing or clobbering) + a visible DEV marker.
IS_DEV = os.environ.get("DFYB_DEV") == "1"
MENUBAR_NAME = APP_NAME + " (DEV)" if IS_DEV else APP_NAME

# Set macOS menu bar app name (instead of "Python")
if sys.platform == "darwin":
    try:
        import ctypes
        import ctypes.util
        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library('objc'))

        # Setup objc runtime function signatures
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.objc_msgSend.restype = ctypes.c_void_p
        objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

        NSBundle = objc.objc_getClass(b'NSBundle')
        sel_mainBundle = objc.sel_registerName(b'mainBundle')
        bundle = objc.objc_msgSend(NSBundle, sel_mainBundle)

        sel_info = objc.sel_registerName(b'localizedInfoDictionary')
        info = objc.objc_msgSend(bundle, sel_info)
        if not info:
            sel_info = objc.sel_registerName(b'infoDictionary')
            info = objc.objc_msgSend(bundle, sel_info)

        # Set CFBundleName
        CFStr = ctypes.cdll.LoadLibrary(ctypes.util.find_library('CoreFoundation'))
        CFStr.CFStringCreateWithCString.restype = ctypes.c_void_p
        CFStr.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]

        key = CFStr.CFStringCreateWithCString(None, b'CFBundleName', 0)
        val = CFStr.CFStringCreateWithCString(None, MENUBAR_NAME.encode('utf-8'), 0)

        objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        sel_setObject = objc.sel_registerName(b'setObject:forKey:')
        objc.objc_msgSend(info, sel_setObject, val, key)
    except Exception:
        pass

# ------------------ CONFIGURATION ------------------

TIME_UNITS = ["sec", "min", "hour"]
CONFIG_FILE = Path.home() / "Library" / "Preferences" / "com.yairs.dontforgetyourbreaks.json"
LOCK_FILE = Path.home() / "Library" / "Application Support" / "DontForgetYourBreaks" / ".lock"
EVENTS_FILE = Path.home() / "Library" / "Application Support" / "DontForgetYourBreaks" / "events.jsonl"
SESSION_FILE = Path.home() / "Library" / "Application Support" / "DontForgetYourBreaks" / "session.json"
if IS_DEV:
    # Isolate all mutable state so the dev instance runs alongside the real app
    # (its own lock → no single-instance clash) and never touches real prefs/events.
    CONFIG_FILE = CONFIG_FILE.with_name("com.yairs.dontforgetyourbreaks.dev.json")
    LOCK_FILE = LOCK_FILE.with_name(".lock.dev")
    EVENTS_FILE = EVENTS_FILE.with_name("events.dev.jsonl")
    SESSION_FILE = SESSION_FILE.with_name("session.dev.json")

SESSION_SAVE_INTERVAL_SECONDS = 5      # how often to snapshot the live session
SESSION_RESUME_WINDOW_SECONDS = 600    # resume only if the crash/relaunch was within this
GITHUB_NEW_ISSUE_URL = "https://github.com/YairShachar/dont-forget-your-breaks/issues/new"
UPDATE_CHECK_INTERVAL_HOURS = 24
UPDATE_TOAST_MS = 3000    # how long the "up to date" / "check failed" note lingers
BREW_UPGRADE_TIMEOUT_S = 300   # brew upgrade download+install headroom (seconds)
BREW_UPDATE_TIMEOUT_S = 120    # brew update (tap refresh) headroom (seconds)

# Typography sizes (role-based; family auto-picked by the 20pt optical split)
FONT_SIZES = {
    'display': 48,        # (reserved) large numerals
    'ring_countdown': 52, # popup countdown inside the progress ring
    'status_hero': 28,    # main-window cockpit headline
    'heading': 17,        # panel header, window title
    'body_emphasis': 16,  # popup primary message
    'subheading': 14,     # main control buttons, gear icon
    'row_countdown': 16,  # break-row time-remaining — paired in weight with the ▶
    'body': 13,           # status, entries, timers
    'label': 12,          # field labels, chevron/▾ glyphs
    'caption': 10,        # helper/hint text
}


def make_font(role, weight=None):
    """CTkFont for a type-scale role; family auto-picked by the 20pt optical split."""
    size = FONT_SIZES[role]
    family = resolve_font_family(size)
    return ctk.CTkFont(family=family, size=size, **({"weight": weight} if weight else {}))


# Bundled line icons (light/dark), loaded via CTkImage.
ICON_SIZE = 24
ICON_DIR = BASE_DIR / "assets" / "icons"


def load_icon(name, size=ICON_SIZE):
    """CTkImage for a bundled line icon; adapts to appearance mode."""
    return ctk.CTkImage(
        light_image=Image.open(ICON_DIR / f"{name}-light.png"),
        dark_image=Image.open(ICON_DIR / f"{name}-dark.png"),
        size=(size, size))


# Break-popup progress ring
RING_SIZE = 170
RING_WIDTH = 9


def _hex_to_rgba(hexstr):
    """'#rrggbb' -> (r, g, b, 255) for PIL ring drawing."""
    h = hexstr.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)

# Semantic colors as (light, dark) tuples — CTk picks by appearance mode.
# Dark halves are the prior known-good values; light halves are starting points.
COLORS = {
    'surface_card':         ("#FFFFFF", "#2C2C2E"),
    'surface_hover':        ("#ECECEE", "#3A3A3C"),
    'border':               ("#D1D1D6", "#3A3A3C"),
    'text_primary':         ("#1C1C1E", "#F2F2F7"),   # high-contrast label (iOS label)
    'text_secondary':       ("#8E8E93", "#999999"),   # dark ≡ old gray60
    'text_tertiary':        ("#AEAEB2", "#808080"),   # dark ≡ old gray50
    'accent_primary':       ("#007AFF", "#0A84FF"),   # systemBlue
    'accent_primary_hover': ("#0068D6", "#0077ED"),
    'text_on_accent':       ("#FFFFFF", "#FFFFFF"),   # label atop a filled accent button
    'accent_success':       ("#34C759", "#30D158"),   # systemGreen
    'accent_warning':       ("#FF9500", "#FF9F0A"),   # systemOrange
    'accent_warning_hover': ("#E68600", "#E8900A"),
}

# Spacing scale (primitive)
SPACE_XXS = 4
SPACE_XS = 6
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24
SPACE_2XL = 32
# Semantic aliases (purpose-named, layered over the scale)
PADDING_WINDOW = SPACE_LG
PADDING_PANEL_X = SPACE_LG
PADDING_PANEL_Y = SPACE_LG
ROW_SPACING = SPACE_SM   # 10 → 8 (tighter rhythm, per proposal)
ROW_META_LINE_PAD = 2    # breathing inside each meta line box (added to font linespace)
ROW_META_LINE_GAP = 1    # gap between a break's title and its subtitle (group them tightly)
SETTINGS_SUBOPTION_INDENT = 12   # left inset for a nested sub-option block
SETTINGS_SUBOPTION_RULE_W = 2    # width of the hairline marking a nested sub-block
# Which settings categories open on first ever launch (persisted thereafter).
SECTION_DEFAULT_EXPANDED = {"breaks": True, "smart_pausing": True,
                            "break_popup": False, "app": False,
                            "check_ins": True}

# Corner radii
CORNER_RADIUS_PANEL = 10
CORNER_RADIUS_BUTTON = 8
CORNER_RADIUS_INPUT = 6

# Button dimensions
BUTTON_HEIGHT_LARGE = 38    # Control buttons (Start/Reset/Pause)
BUTTON_HEIGHT_SMALL = 28    # Test, play buttons
BUTTON_HEIGHT_XLARGE = 40   # Popup actions (Snooze / ▾ / Done / Set)
BUTTON_HEIGHT_BOTTOM_BAR = 22   # modest bottom-bar text buttons (Feedback / Check in / version)

# Cockpit status hero
DOT_SIZE = 11            # status dot diameter
ICON_CHIP = 40          # break-row icon chip (rounded square)
PLAY_GLYPH_SIZE = 15    # "break now" ▶ — optically matched to the (airy) gear glyph
PLAY_BTN_WIDTH = 24     # tight footprint so the ▶ hugs the countdown, not adrift
STATUS_DOT_NUDGE_Y = 2  # top-pad the dot down onto the text's OPTICAL centre; the label
                        # box-centre sits above the rendered glyphs, so plain centring reads high
TOOLTIP_DELAY_MS = 450   # gentle delay before a hover hint appears
TOOLTIP_FADE_FRAMES = 8  # ~128ms fade in/out at ANIMATION_FRAME_INTERVAL
TOOLTIP_POLL_MS = 120    # watchdog: re-check the pointer is still over the button
TOOLTIP_MISS_LIMIT = 2   # consecutive off-target polls before hiding (edge-jitter guard)
PROGRESS_HEIGHT = 6     # slim progress-to-next-break bar
HERO_PAD = SPACE_LG     # inner padding of the hero card
DOT_PULSE_MS = 3200     # full breathe cycle of the on-track status dot
HERO_HEADLINE_HEIGHT = 38  # fixed slot so the big<->medium font swap doesn't resize the window
STATUS_DOT_COLORS = {
    'good': COLORS['accent_success'],
    'warning': COLORS['accent_warning'],
    'idle': COLORS['text_tertiary'],
}
# state key -> the short word next to the status dot
STATUS_STATE_LABELS = {
    'idle': "Idle", 'paused': "Paused", 'holding': "Holding",
    'break': "Break", 'on_track': "On track",
}
# break-row icon by index; falls back to "timer" for any extra breaks
ROW_ICON_NAMES = ["eye", "cup"]
# Colored-tile chip tint (light, dark) per icon — matches the icon's accent
TILE_CHIP_COLORS = {
    "eye": ("#DEECFF", "#24405C"),    # blue
    "cup": ("#E0F6E6", "#2D5037"),    # green
    "timer": ("#FFF0DC", "#4A3A1C"),  # orange
}
BUTTON_MIN_WIDTH = 80      # Minimum touch target

# Collapsible panel settings
PANEL_COLLAPSED_HEIGHT = 48      # Height of collapsed panel header

# Settings window
SETTINGS_WINDOW_WIDTH = 600             # px; height auto-fits the content
SETTINGS_WINDOW_MAX_HEIGHT_RATIO = 0.9  # cap auto-height at 90% of screen height
SETTINGS_WINDOW_MIN_HEIGHT_RATIO = 0.15  # floor as a fraction of screen height
SETTINGS_WINDOW_OPACITY = 0.95          # slight translucency (0..1)
SETTINGS_WINDOW_HEIGHT_SLACK = SPACE_LG  # margin below the last card so it never sits flush/cut
SETTINGS_WINDOW_Y_OFFSET = 80           # px the window sits above the main window

# Break popup
POPUP_WIDTH = 380  # height fits content (see CountdownPopup._position_popup)
# Activity-pause deferral (#34) slider bounds
ACTIVITY_PAUSE_MIN = 2
ACTIVITY_PAUSE_MAX = 15
ACTIVITY_PAUSE_DEFAULT = 2   # seconds of stillness before a due break fires
# Away / natural-rest idle lines (sliders; ranges deliberately non-overlapping with
# the pause range so the three can never fall out of order — pause<=15 < away 30..120
# < natural 180..1800). Defaults reuse the engine's ladder constants.
AWAY_IDLE_MIN_SECONDS = 30
AWAY_IDLE_MAX_SECONDS = 120
AWAY_IDLE_STEP_SECONDS = 5
NATURAL_BREAK_MIN_SECONDS = 180
NATURAL_BREAK_MAX_SECONDS = 1800
NATURAL_BREAK_STEP_SECONDS = 60
NATURAL_BREAK_ACK_SECONDS = 6   # how long the "welcome back" cue lingers
SNOOZE_RECHECK_MS = 5000     # while a snoozed break is context-deferred, re-check this often
SNOOZE_CLEAR_POLLS_REQUIRED = 2  # consecutive clear polls before a snooze returns (debounces a mic/activity blip, #84)
ROW_SNOOZED_SUBTITLE = "Snoozed"  # break-row subtitle while a snooze is pending (its countdown shows the return time)
# Resume-prompt while paused (#77): nudge to resume when you clearly return.
RESUME_ACTIVE_THRESHOLD_SECONDS = 2   # active-idle below this = recently typing/clicking
RESUME_PROMPT_DEFAULT_SAMPLES = 3     # consecutive ~1s "back" samples before prompting (adjustable)
RESUME_PROMPT_MIN_SAMPLES = 2         # sensitivity slider bounds
RESUME_PROMPT_MAX_SAMPLES = 10
RESUME_CARD_TIMEOUT_MS = 30000        # auto-dismiss the resume card (treated as "stay paused")
RESUME_CARD_HEADLINE = "Breaks are paused"       # leads with what you forgot
RESUME_CARD_SUBTEXT = "Welcome back — resume them?"
CONFIG_COMMIT_DEBOUNCE_MS = 800  # wait this long after the last keystroke before applying a typed interval/duration
OVER_BREAK_SUFFIX = "over your break"  # trails the +MM:SS over-breaking count-up
SNOOZE_OPTIONS_SECONDS = [30, 60, 120, 300, 600, 900, 1800]  # ▾ menu presets
DEFAULT_SNOOZE_SECONDS = 300                                  # default snooze (5 min)
MAX_SNOOZE_SECONDS = 24 * 60 * 60                             # cap for a custom value
CUSTOM_SNOOZE_UNITS = ["sec", "min"]                          # segmented-control options
CUSTOM_SNOOZE_DEFAULT_UNIT = "sec"                            # unit selected first in the dialog
POPUP_FADE_FRAMES = 16   # ~256ms entrance fade at ANIMATION_FRAME_INTERVAL
# Settings dropdown label -> stored popup_placement value
POPUP_PLACEMENT_LABELS = {
    "Active screen": "active",
    "Primary screen": "primary",
    "Cursor's screen": "cursor",
}
# Where the MAIN window opens (#67): remember the last position, or center on the
# screen you're currently using (multi-monitor). Default remembers (no surprise).
MAIN_WINDOW_PLACEMENT_LABELS = {
    "Remember last position": "remembered",
    "Center on current screen": "active",
}
MAIN_WINDOW_PLACEMENT_DEFAULT = "remembered"

# Gentle rotating messages for the break popup (generic for now; per-break-kind
# copy comes with the break-kind model, #30).
BREAK_MESSAGES = [
    "Time for a break.",
    "Rest for a moment — you've earned it.",
    "Ease off the screen for a bit.",
    "Take a breath and unwind.",
    "A gentle pause.",
]

# --- Check-ins (user-configurable periodic questions; #9 habits foundation) ---
MIN_CHECK_IN_GAP_SECONDS = 20 * 60          # never two check-in prompts closer than this
SECONDS_PER_HOUR = 3600                      # waking-window hours → seconds (check-ins)
CHECK_IN_WAKING_WINDOW_HOURS = 14                                  # assumed waking span
CHECK_IN_WAKING_WINDOW_SECONDS = CHECK_IN_WAKING_WINDOW_HOURS * SECONDS_PER_HOUR
CHECK_IN_POPUP_W, CHECK_IN_POPUP_H = 340, 200
CHECK_IN_SCALE_BTN_WIDTH = 44               # compact square-ish button per scale value
CHECK_IN_NOTE_PLACEHOLDER = "Add a note (optional)"   # optional note entry (scale/choices/number)
CHECK_IN_ANSWER_PLACEHOLDER = "Write a note…"         # note-type question's primary entry
CHECK_IN_SAVE_LABEL = "Save"
CHECK_IN_SKIP_LABEL = "Skip"
# Detail-popup (select → optional note → Save) widgets, all token-sized.
CHECK_IN_NUMBER_ENTRY_WIDTH = 100           # px; numeric entry field (number type)
CHECK_IN_NUMBER_PLACEHOLDER = "Number"      # numeric entry hint
CHECK_IN_SELECT_BORDER_WIDTH = 1            # outline on an UNselected scale/choice button
CHECK_IN_ICON_BTN_WIDTH = 28                # px; square ✕ remove control in a Today row
CHECK_IN_REMOVE_ICON = "✕"                  # remove a past answer
CHECK_IN_REMOVE_CONFIRM_LABEL = "Remove?"   # inline confirm shown after tapping ✕ once
CHECK_IN_REMOVE_CONFIRM_WIDTH = 72          # px; wider so "Remove?" fits
CHECK_IN_NEW_ANSWER_LABEL = "＋ New answer"  # link to leave edit mode and add a fresh answer
CHECK_IN_TODAY_HEADER = "Today"             # header above today's answers list
CHECK_IN_TODAY_ROW_FMT = "{time} · {summary}"    # value line: <time> · <value>
CHECK_IN_TODAY_ROW_TEXT_WRAP = 210          # px; wrap a long today-row summary
CHECK_IN_UPDATE_CONTEXT = "Update today's answer"        # once-a-day, already answered
CHECK_IN_ADD_CONTEXT_FMT = "Add another · {n} today"     # recurring, already answered
CHECK_IN_EDITING_CONTEXT = "Editing"        # context line while editing a past answer
CHECK_IN_ANSWERING_NOW_FMT = "Answering now: {value}"    # status line while composing a new answer

# --- On-demand "Check in" (main-window affordance + question chooser) ---
CHECK_IN_NOW_LABEL = "Check in"                      # modest main-window button
CHECK_IN_NOW_TOOLTIP = "Answer a check-in now"
CHECK_IN_CHOOSER_TITLE = "Check in"                  # chooser window title
CHECK_IN_CHOOSER_PROMPT = "What would you like to check in on?"
CHECK_IN_ROW_CHEVRON = "›"                           # tappable affordance on every row
CHECK_IN_ROW_TEXT_WRAP = 210                         # px; question text wrap in a compact row
CHECK_IN_ROW_NOTE_MAX = 18                           # truncate a note shown as the row's value
CHECK_IN_ANSWER_WORD, CHECK_IN_ANSWERS_WORD = "answer", "answers"
CHECK_IN_COUNT_FMT = "{n} {word}"                    # recurring row count, e.g. "3 answers"
CHECK_IN_NONE_CONFIGURED_TEXT = "Nothing to check in on right now"   # calm empty-state note (also covers "all answered today")
CHECK_IN_CHOOSER_CLOSE_LABEL = "Close"
CHECK_IN_CHOOSER_BTN_WIDTH = 300                     # px; per-question chooser buttons
CHECK_IN_TIME_FMT = "%-I:%M %p"        # e.g. "10:35 AM"

# --- Settings > Check-ins section (card list + add/edit/delete question form) ---
# All labels/sizes are tokens here; the widget code never inlines literals.
CHECK_IN_SECTION_TITLE = "Check-ins"
CHECK_IN_ENABLE_LABEL = "Enable check-ins"
CHECK_IN_ADD_LABEL = "+ Add question"
CHECK_IN_EDIT_LABEL = "Edit"
CHECK_IN_DELETE_LABEL = "Delete"
CHECK_IN_NEW_QUESTION_TEXT = "New question"       # default text for a freshly added card
CHECK_IN_ID_FALLBACK = "question"                 # slug base when the text has no word chars
CHECK_IN_ID_SEP = "-"                             # joins slug + a disambiguating counter
CHECK_IN_DEFAULT_CHOICES = ["Yes", "No"]          # fallback if a Choices question has no options
CHECK_IN_OPTIONS_SPLIT = ","                      # options may be comma- OR newline-separated
# Card layout
CHECK_IN_CARD_BORDER_WIDTH = 1
CHECK_IN_CARD_TEXT_WRAP = 360                     # px; wrap long question text inside a card
CHECK_IN_TOGGLE_WIDTH = 28                        # bare per-question enable checkbox
CHECK_IN_ACTION_BTN_WIDTH = 62                    # Edit / Delete buttons
CHECK_IN_SUMMARY_INDENT = 28                      # align the summary caption under the text
# One-line answer + cadence summary (e.g. "Scale 1–5 · 2×/day")
CHECK_IN_SUMMARY_SEP = " · "                 # " · " between the answer + cadence parts
CHECK_IN_ANSWER_TYPE_LABELS = {SCALE: "Scale", CHOICES: "Choices", NOTE: "Note"}
CHECK_IN_SCALE_RANGE_FMT = "{label} {min}–{max}"   # e.g. "Scale 1–5"
CHECK_IN_CHOICES_FMT = "{label}: {opts}"
CHECK_IN_CHOICES_JOIN = "/"
CHECK_IN_CADENCE_DAILY_LABEL = "daily"
CHECK_IN_CADENCE_WEEKLY_LABEL = "weekly"
CHECK_IN_CADENCE_PER_DAY_FMT = "{count}×/day"      # e.g. "2×/day"
CHECK_IN_CADENCE_PER_WEEK_FMT = "{count}×/week"
# Trigger ("When") summary suffixes appended to a card caption (e.g. "… · on demand")
CHECK_IN_TRIGGER_BREAK_SUFFIX = "with a break"
CHECK_IN_TRIGGER_ON_DEMAND_SUFFIX = "on demand"
# Repeat summary suffix appended to a card caption when a question is once-per-day
CHECK_IN_ONCE_A_DAY_SUFFIX = " · once a day"
# Edit modal
CHECK_IN_EDIT_TITLE = "Edit check-in"
CHECK_IN_EDIT_TEXT_LABEL = "Question"
CHECK_IN_EDIT_TYPE_LABEL = "Answer type"
CHECK_IN_EDIT_MIN_LABEL = "Min"
CHECK_IN_EDIT_MAX_LABEL = "Max"
CHECK_IN_EDIT_LOW_LABEL = "Low label"
CHECK_IN_EDIT_HIGH_LABEL = "High label"
CHECK_IN_EDIT_OPTIONS_LABEL = "Options (one per line or comma-separated)"
CHECK_IN_EDIT_NOTE_HINT = "A free-text note is the answer — nothing else to set."
CHECK_IN_EDIT_ALLOW_NOTE_LABEL = "Allow an optional note"
CHECK_IN_EDIT_CADENCE_LABEL = "How often"
CHECK_IN_EDIT_COUNT_LABEL = "Count"
CHECK_IN_EDIT_TRIGGER_LABEL = "When"
CHECK_IN_EDIT_REPEAT_LABEL = "Repeat"
CHECK_IN_EDIT_SAVE_LABEL = "Save"
CHECK_IN_EDIT_CANCEL_LABEL = "Cancel"
CHECK_IN_CADENCE_LABELS = {TIMES_PER_DAY: "Times per day",
                           PER_DAY: "Per day", PER_WEEK: "Per week"}
CHECK_IN_TRIGGER_LABELS = {TRIGGER_BREAK: "With a break",
                           TRIGGER_ON_DEMAND: "On demand only"}
CHECK_IN_REPEAT_LABELS = {"A few times a day": False, "Once a day": True}
CHECK_IN_EDIT_TEXT_WIDTH = 340                    # question / options field width
CHECK_IN_EDIT_INT_WIDTH = 64                      # min / max / count entries
CHECK_IN_EDIT_LABEL_WIDTH = 150                   # scale end-label entries
CHECK_IN_EDIT_OPTIONS_HEIGHT = 96                 # options textbox height

DEFAULT_CHECK_INS = {
    "enabled": True,
    "questions": [
        {"id": "refreshed", "text": "How refreshed do you feel?", "enabled": True,
         "answer": {"type": "scale", "min": 1, "max": 5,
                    "min_label": "groggy", "max_label": "refreshed", "allow_note": True},
         "cadence": {"type": "times_per_day", "count": 2}, "trigger": "break"},
        {"id": "sleep", "text": "How did you sleep?", "enabled": True,
         "answer": {"type": "choices", "options": ["Great", "OK", "Rough"], "allow_note": True},
         "cadence": {"type": "per_day", "count": 1}, "trigger": "on_demand",
         "once_per_day": True},
    ],
}


def merge_check_ins(saved_prefs):
    """(enabled, questions) from saved prefs, falling back to DEFAULT_CHECK_INS so
    older config files (no 'check_ins' key) load unchanged."""
    block = saved_prefs.get("check_ins") or {}
    enabled = block.get("enabled", DEFAULT_CHECK_INS["enabled"])
    questions = block.get("questions", DEFAULT_CHECK_INS["questions"])
    return enabled, questions


def check_in_event_payload(question, value, note, event_id):
    """The data dict for a CHECK_IN answer event. `event_id` is a stable id (uuid hex) so
    the entry can later be edited/removed via correction events."""
    return {"id": event_id, "question_id": question.id, "question": question.text,
            "answer_type": question.answer.type, "value": value, "note": (note or None)}


def check_in_edit_payload(event_id, target_id, value, note):
    """A CHECK_IN correction that overrides the value/note of the entry `target_id`."""
    return {"id": event_id, "edits": target_id, "value": value, "note": (note or None)}


def check_in_remove_payload(event_id, target_id):
    """A CHECK_IN correction that removes the entry `target_id` from views."""
    return {"id": event_id, "removes": target_id}


def _ci_int(value, default):
    """Parse an int, falling back to `default` for blank/garbage entry text."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _check_in_cadence_summary(cad_type, count):
    """Human phrase for a cadence: 'daily', 'weekly', '2×/day', '3×/week'."""
    if cad_type == PER_WEEK:
        return (CHECK_IN_CADENCE_WEEKLY_LABEL if count == 1
                else CHECK_IN_CADENCE_PER_WEEK_FMT.format(count=count))
    if cad_type == PER_DAY and count == 1:
        return CHECK_IN_CADENCE_DAILY_LABEL
    return CHECK_IN_CADENCE_PER_DAY_FMT.format(count=count)


def _check_in_trigger_summary(trigger):
    """Human 'When' suffix for a trigger: 'with a break' or 'on demand'."""
    return (CHECK_IN_TRIGGER_ON_DEMAND_SUFFIX if trigger == TRIGGER_ON_DEMAND
            else CHECK_IN_TRIGGER_BREAK_SUFFIX)


def check_in_summary(question):
    """A one-line 'answer-type + range/options · cadence · when' summary for a raw
    question dict (e.g. 'Scale 1–5 · 2×/day · with a break')."""
    answer = question.get("answer") or {}
    atype = answer.get("type")
    label = CHECK_IN_ANSWER_TYPE_LABELS.get(atype, CHECK_IN_ANSWER_TYPE_LABELS[NOTE])
    if atype == SCALE:
        answer_part = CHECK_IN_SCALE_RANGE_FMT.format(
            label=label, min=answer.get("min", DEFAULT_SCALE_MIN),
            max=answer.get("max", DEFAULT_SCALE_MAX))
    elif atype == CHOICES:
        opts = CHECK_IN_CHOICES_JOIN.join(str(o) for o in (answer.get("options") or ()))
        answer_part = CHECK_IN_CHOICES_FMT.format(label=label, opts=opts)
    else:
        answer_part = label
    cadence = question.get("cadence") or {}
    cadence_part = _check_in_cadence_summary(
        cadence.get("type", PER_DAY), _ci_int(cadence.get("count", 1), 1))
    trigger_part = _check_in_trigger_summary(question.get("trigger"))
    summary = CHECK_IN_SUMMARY_SEP.join((answer_part, cadence_part, trigger_part))
    if question.get("once_per_day"):
        summary += CHECK_IN_ONCE_A_DAY_SUFFIX
    return summary


def _slugify_check_in(text):
    """A lowercase hyphen slug from question text (word chars only)."""
    return re.sub(r"[^a-z0-9]+", CHECK_IN_ID_SEP, str(text).lower()).strip(CHECK_IN_ID_SEP)


def _parse_options_text(text):
    """Options entered one-per-line or comma-separated → a clean list (no blanks)."""
    normalized = (text or "").replace(CHECK_IN_OPTIONS_SPLIT, "\n")
    return [line.strip() for line in normalized.splitlines() if line.strip()]


def _options_to_text(options):
    """Options list → newline-joined text for the edit box."""
    return "\n".join(str(o) for o in (options or ()))


def _display_rects():
    """Active display rects (x, y, w, h) in global top-left points; [] off-macOS
    or on any failure (so callers degrade to the Tk screen)."""
    if sys.platform != "darwin":
        return []
    try:
        import Quartz
        from dfyb.activity.sensors import _active_display_rects
        return _active_display_rects(Quartz)
    except Exception:
        return []

# Animation timing
ANIMATION_FRAME_INTERVAL = 16      # ms (60fps)
ANIMATION_EXPAND_DURATION = 250    # ms
ANIMATION_COLLAPSE_DURATION = 200  # ms


# ------------------ BREAK CONFIG ------------------

class BreakConfig:
    """Configuration for a single break type."""

    def __init__(self, name, interval_val, interval_unit,
                 duration_val, duration_unit, start_sound, end_sound,
                 loop_end_sound=False, auto_dismiss=True, snoozable=True):
        self.name = ctk.StringVar(value=name)
        self.interval_value = ctk.StringVar(value=str(interval_val))
        self.interval_unit = ctk.StringVar(value=interval_unit)
        self.duration_value = ctk.StringVar(value=str(duration_val))
        self.duration_unit = ctk.StringVar(value=duration_unit)
        self.start_sound = ctk.StringVar(value=start_sound)
        self.end_sound = ctk.StringVar(value=end_sound)
        self.loop_end_sound = ctk.BooleanVar(value=loop_end_sound)
        self.auto_dismiss = ctk.BooleanVar(value=auto_dismiss)
        self.snoozable = ctk.BooleanVar(value=snoozable)
        self.remaining = self.get_interval_seconds()
        self.timer_label = None  # Will be set by UI

    @staticmethod
    def _safe_int(var, fallback=1):
        """Safely parse a StringVar to int, returning fallback for empty/invalid values."""
        try:
            return int(var.get())
        except (ValueError, TypeError):
            return fallback

    def get_interval_seconds(self):
        """Convert interval to seconds."""
        return to_seconds(self._safe_int(self.interval_value), self.interval_unit.get())

    def get_duration_seconds(self):
        """Convert duration to seconds."""
        return to_seconds(self._safe_int(self.duration_value), self.duration_unit.get())

    def reset_timer(self):
        """Reset remaining time to interval."""
        self.remaining = self.get_interval_seconds()


# ------------------ COUNTDOWN POPUP ------------------

class CountdownPopup:
    """A modern popup with countdown timer, progress bar, glassmorphism effect."""

    def __init__(self, parent, title, message, duration,
                 auto_dismiss=True, snoozable=True, on_close=None, on_snooze=None,
                 end_sound=None, loop_end_sound=False, placement="active",
                 target_screen=None, held_reason=None,
                 snooze_seconds=DEFAULT_SNOOZE_SECONDS,
                 snooze_count=0, first_snooze_ago=None):
        self.parent = parent
        self.placement = placement
        self.target_screen = target_screen
        self.held_reason = held_reason
        self.snooze_seconds = snooze_seconds
        self.snooze_count = snooze_count
        self.first_snooze_ago = first_snooze_ago
        self.duration = duration
        self.remaining = duration
        self.auto_dismiss = auto_dismiss
        self.snoozable = snoozable
        self.on_close = on_close
        self.on_snooze = on_snooze
        self.end_sound = end_sound
        self.loop_end_sound = loop_end_sound
        self.closed = False
        self.snoozed = False
        self.sound_stop_event = threading.Event()
        self._start_time = time.time()  # For smooth progress bar
        # Create popup window
        self.window = ctk.CTkToplevel(parent)
        self.window.title(title)
        self.window.resizable(False, False)
        # Pin the popup to the active Space (multi-monitor #21 fix): it appears
        # on the Space you're on instead of switching to another.
        pin_to_active_space(self.window)

        # Make window always on top
        self.window.attributes('-topmost', True)

        # A gentle entrance fade on macOS (respects reduced-motion).
        if sys.platform == "darwin":
            if prefers_reduced_motion():
                self.window.attributes('-alpha', 0.95)
            else:
                self.window.attributes('-alpha', 0.0)
                self._fade_in()

        # Reliably raise the popup and take focus (like a normal alert); it is
        # pinned to the active Space above, so activating it won't switch Spaces.
        self.window.lift()
        self.window.focus_force()

        # Main container with padding
        container = ctk.CTkFrame(
            self.window,
            corner_radius=CORNER_RADIUS_PANEL,
            fg_color=COLORS['surface_card']
        )
        container.pack(fill="both", expand=True, padx=0, pady=0)

        # Title
        title_label = ctk.CTkLabel(
            container,
            text=title,
            font=make_font('heading', weight="bold")
        )
        title_label.pack(pady=(PADDING_PANEL_Y, SPACE_XXS))

        # "Waited while you were …" line when the break was held (transparency).
        if self.held_reason:
            held_text = held_message(self.held_reason)
            if held_text:
                ctk.CTkLabel(
                    container, text=held_text,
                    font=make_font('caption'),
                    text_color=COLORS['text_secondary']
                ).pack(pady=(0, SPACE_XS))

        # Snooze insight line (#37): "Snoozed 2× already (originally due 15 min ago)".
        summary = snooze_summary_label(self.snooze_count, self.first_snooze_ago)
        if summary:
            ctk.CTkLabel(
                container, text=summary,
                font=make_font('caption'),
                text_color=COLORS['text_secondary']
            ).pack(pady=(0, SPACE_XS))

        # Message
        msg_label = ctk.CTkLabel(
            container,
            text=message,
            font=make_font('body_emphasis')
        )
        msg_label.pack(pady=(0, ROW_SPACING))

        # Circular progress ring with the countdown centered inside it.
        self._ring_wrap = ctk.CTkFrame(
            container, fg_color="transparent", width=RING_SIZE, height=RING_SIZE)
        self._ring_wrap.pack(pady=ROW_SPACING)
        self._ring_wrap.pack_propagate(False)
        self.ring_label = ctk.CTkLabel(self._ring_wrap, text="")
        self.ring_label.place(relx=0.5, rely=0.5, anchor="center")
        self.countdown_label = ctk.CTkLabel(
            self._ring_wrap, text=self._format_time(self.remaining),
            font=make_font('ring_countdown', weight="bold"))
        self.countdown_label.place(relx=0.5, rely=0.5, anchor="center")
        self._last_ring_deg = -1
        self._render_ring(1.0)

        # Amber count-up shown once a break runs past its duration (#33). Packed
        # empty at build so its line is reserved — the window won't resize when it
        # fills in; update_countdown just sets the text.
        self.over_label = ctk.CTkLabel(
            container, text="",
            font=make_font('caption'),
            text_color=COLORS['accent_warning']
        )
        self.over_label.pack(pady=(0, SPACE_XS))

        # Button frame
        btn_frame = ctk.CTkFrame(container, fg_color="transparent")
        btn_frame.pack(pady=ROW_SPACING)

        # Snooze split control (only if the break is snoozable): main = snooze for
        # the current default, ▾ = pick another duration (which becomes the default).
        if self.snoozable:
            # Unified split button: one rounded grey enclosure with two flat
            # clickable zones (Snooze | chevron) divided by a 1px seam.
            snooze_group = ctk.CTkFrame(
                btn_frame, fg_color=COLORS['surface_hover'],
                corner_radius=CORNER_RADIUS_BUTTON,
                width=104 + 1 + 32, height=BUTTON_HEIGHT_XLARGE)  # snooze | seam | chevron
            snooze_group.pack(side="left", padx=SPACE_SM)
            snooze_group.pack_propagate(False)

            self.snooze_btn = ctk.CTkButton(
                snooze_group,
                text=f"Snooze {format_snooze_short(self.snooze_seconds)}",
                command=self.snooze, width=104, height=BUTTON_HEIGHT_XLARGE,
                corner_radius=0, fg_color="transparent",
                hover_color=COLORS['border'], text_color=COLORS['text_secondary'],
                font=make_font('body'))
            self.snooze_btn.pack(side="left", fill="y")

            seam = ctk.CTkFrame(snooze_group, width=1, fg_color=COLORS['border'])
            seam.pack(side="left", fill="y", pady=SPACE_XS)

            self.snooze_menu_btn = ctk.CTkButton(
                snooze_group, text="", image=load_icon('chevron', size=12),
                command=self._open_snooze_menu, width=32, height=BUTTON_HEIGHT_XLARGE,
                corner_radius=0, fg_color="transparent", hover_color=COLORS['border'])
            self.snooze_menu_btn.pack(side="left", fill="y")

        # Done button - primary style
        self.ok_btn = ctk.CTkButton(
            btn_frame,
            text="Done",
            command=self.close,
            width=130,
            height=BUTTON_HEIGHT_XLARGE,
            corner_radius=CORNER_RADIUS_BUTTON,
            fg_color=COLORS['accent_primary'],
            hover_color=COLORS['accent_primary_hover'],
            font=make_font('body', weight="bold")
        )
        self.ok_btn.pack(side="left", padx=SPACE_SM)

        # Size the window to its content, then place it on the chosen screen.
        self._position_popup()

        # Handle window close
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        # Start countdown and keep-on-top mechanism
        self.update_countdown()
        self._update_progress_smooth()
        self._keep_on_top()

    def _format_time(self, seconds):
        """Format seconds as M:SS (e.g. 0:05, 10:00)."""
        m, s = divmod(max(0, seconds), 60)
        return f"{m}:{s:02}"

    def update_countdown(self):
        if self.closed:
            return

        self.remaining -= 1

        if self.remaining > 0:
            self.countdown_label.configure(text=self._format_time(self.remaining))
            self.window.after(1000, self.update_countdown)
            return

        if self.remaining == 0:
            # Duration just elapsed — fire the end sound + attention once.
            if self.end_sound and self.end_sound != "None":
                if self.loop_end_sound:
                    threading.Thread(
                        target=looping_sound,
                        args=(self.sound_stop_event, self.end_sound),
                        daemon=True
                    ).start()
                else:
                    play_sound(self.end_sound)

            if self.auto_dismiss:
                self.close()
                return
            self.countdown_label.configure(
                text=self._format_time(0), text_color=COLORS['accent_warning'])
            self._render_ring(0.0)   # full amber ring conveys the over-state
            self._bring_to_attention()

        # auto-dismiss off: count up the time spent over the break (#33).
        over_seconds = -self.remaining
        if over_seconds >= 1:
            self.over_label.configure(
                text=f"{format_over_time(over_seconds)} {OVER_BREAK_SUFFIX}")
        self.window.after(1000, self.update_countdown)

    def _render_ring(self, frac):
        """Redraw the progress ring for `frac` and the current appearance mode."""
        mode = ctk.get_appearance_mode()
        track = _hex_to_rgba(resolve_color(COLORS['border'], mode))
        if self.remaining <= 0:                       # over: a full amber ring
            prog = _hex_to_rgba(resolve_color(COLORS['accent_warning'], mode))
            frac = 1.0
        else:                                         # one calm accent throughout
            prog = _hex_to_rgba(resolve_color(COLORS['accent_primary'], mode))
        img = ring_image(frac, RING_SIZE, RING_WIDTH, track, prog)
        self._ring_img = ctk.CTkImage(light_image=img, dark_image=img,
                                      size=(RING_SIZE, RING_SIZE))
        self.ring_label.configure(image=self._ring_img)

    def _update_progress_smooth(self):
        """Advance the ring smoothly (every 50ms), re-rendering only when the
        visible arc moves by >=1 degree so PIL isn't redrawn needlessly."""
        if self.closed:
            return
        try:
            elapsed = time.time() - self._start_time
            frac = max(0, 1 - (elapsed / self.duration)) if self.duration > 0 else 0
            deg = round(frac * 360)
            if deg != self._last_ring_deg:
                self._last_ring_deg = deg
                self._render_ring(frac)
        except Exception:
            pass

        if self.remaining > 0:
            self.window.after(50, self._update_progress_smooth)

    def snooze(self, seconds=None):
        """Snooze the break; `seconds` defaults to the current default."""
        if self.closed or self.snoozed:
            return
        chosen = self.snooze_seconds if seconds is None else seconds
        self.snoozed = True
        self.sound_stop_event.set()
        if self.on_snooze:
            self.on_snooze(chosen)
        self.closed = True
        self._dismiss()

    def _open_snooze_menu(self):
        """Pop a menu of snooze durations (+ Custom…) under the ▾ button."""
        menu = tk.Menu(self.window, tearoff=0)
        selected = tk.IntVar(value=self.snooze_seconds)
        for seconds in SNOOZE_OPTIONS_SECONDS:
            menu.add_radiobutton(
                label=format_snooze_long(seconds), value=seconds, variable=selected,
                command=lambda s=seconds: self.snooze(s))
        menu.add_separator()
        menu.add_command(label="Custom…", command=self._open_custom_snooze)
        menu.tk_popup(
            self.snooze_menu_btn.winfo_rootx(),
            self.snooze_menu_btn.winfo_rooty() + self.snooze_menu_btn.winfo_height())

    def _open_custom_snooze(self):
        """Small styled dialog to snooze for an arbitrary duration."""
        dialog = ctk.CTkToplevel(self.window)
        dialog.title("Custom snooze")
        dialog.resizable(False, False)
        dialog.attributes('-topmost', True)

        frame = ctk.CTkFrame(dialog, fg_color="transparent")
        frame.pack(padx=PADDING_WINDOW, pady=PADDING_WINDOW)

        ctk.CTkLabel(
            frame, text="Snooze for",
            font=make_font('label')
        ).pack(anchor="w", pady=(0, SPACE_XS))

        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x")

        entry = ctk.CTkEntry(
            row, width=80, height=36, corner_radius=CORNER_RADIUS_INPUT,
            font=make_font('body')
        )
        entry.pack(side="left")
        entry.focus_set()

        unit = ctk.StringVar(value=CUSTOM_SNOOZE_DEFAULT_UNIT)
        unit_btn = ctk.CTkSegmentedButton(
            row, values=CUSTOM_SNOOZE_UNITS, variable=unit,
            font=make_font('label')
        )
        unit_btn.set(CUSTOM_SNOOZE_DEFAULT_UNIT)
        unit_btn.pack(side="left", padx=(SPACE_SM, 0))

        hint = ctk.CTkLabel(
            frame, text="", text_color=COLORS['accent_warning'],
            font=make_font('caption')
        )
        hint.pack(anchor="w", pady=(SPACE_XS, 0))

        def do_set(*_):
            secs = custom_snooze_seconds(entry.get(), unit.get(), MAX_SNOOZE_SECONDS)
            if secs is None:
                hint.configure(text="Enter a positive number")
                return
            dialog.destroy()
            self.snooze(secs)

        ctk.CTkButton(
            frame, text="Set", command=do_set, height=BUTTON_HEIGHT_XLARGE,
            corner_radius=CORNER_RADIUS_BUTTON,
            fg_color=COLORS['accent_primary'], hover_color=COLORS['accent_primary_hover'],
            font=make_font('body', weight="bold")
        ).pack(fill="x", pady=(SPACE_SM, 0))

        entry.bind("<Return>", do_set)
        dialog.bind("<Escape>", lambda e: dialog.destroy())
        dialog.update_idletasks()
        px = self.window.winfo_rootx() + (self.window.winfo_width() - dialog.winfo_reqwidth()) // 2
        py = self.window.winfo_rooty() + (self.window.winfo_height() - dialog.winfo_reqheight()) // 2
        dialog.geometry(f"+{px}+{py}")

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.sound_stop_event.set()
        if self.on_close:
            self.on_close()
        self._dismiss()

    def _fade_in(self, frame=0, frames=POPUP_FADE_FRAMES):
        """Fade the popup in (macOS alpha) with a gentle, visible linear ramp."""
        if self.closed or sys.platform != "darwin":
            return
        try:
            self.window.attributes('-alpha', 0.95 * (frame / frames))
        except Exception:
            return
        if frame < frames:
            self.window.after(ANIMATION_FRAME_INTERVAL,
                              lambda: self._fade_in(frame + 1, frames))

    def _fade_out(self, frame=0, frames=POPUP_FADE_FRAMES, then=None):
        """Fade the popup out (macOS alpha), then run `then` (e.g. destroy)."""
        try:
            self.window.attributes('-alpha', 0.95 * (1 - frame / frames))
        except Exception:
            if then:
                then()
            return
        if frame < frames:
            self.window.after(ANIMATION_FRAME_INTERVAL,
                              lambda: self._fade_out(frame + 1, frames, then))
        elif then:
            then()

    def _dismiss(self):
        """Fade the popup out (macOS, unless reduced-motion), then destroy it."""
        def _destroy():
            try:
                self.window.withdraw()
            except Exception:
                pass
            try:
                self.window.destroy()
            except Exception:
                pass
        if sys.platform == "darwin" and not prefers_reduced_motion():
            self._fade_out(then=_destroy)
        else:
            _destroy()

    def _keep_on_top(self):
        """Periodically ensure popup stays on top and visible."""
        if self.closed:
            return
        try:
            self.window.lift()
            self.window.attributes('-topmost', True)
        except Exception:
            return
        self.window.after(2000, self._keep_on_top)

    def _target_screen(self, screens):
        """Pick the screen rect (x, y, w, h) to place the popup on, per mode."""
        if self.placement == "cursor":
            point = (self.window.winfo_pointerx(), self.window.winfo_pointery())
            return screen_for_point(point, screens) or (screens[0] if screens else None)
        if self.placement == "active":
            # target_screen was captured BEFORE the popup stole focus.
            return self.target_screen or (screens[0] if screens else None)
        return screens[0] if screens else None      # "primary"

    def _position_popup(self):
        """Center the popup on the chosen screen (per placement mode)."""
        screens = _display_rects()
        screen = self._target_screen(screens)
        if screen is None:  # non-macOS / no Quartz: use the Tk screen
            screen = (0, 0, self.window.winfo_screenwidth(),
                      self.window.winfo_screenheight())
        self.window.update_idletasks()
        w, h = POPUP_WIDTH, self.window.winfo_reqheight()   # fixed width, fit height
        x, y = center_on_screen(screen, w, h)
        x, y = clamp_onscreen(x, y, w, h, screen)
        # CustomTkinter's .geometry() override mislocates cross-monitor +x+y
        # (it recomputes the position for the window's current monitor). Set the
        # raw Tk geometry with integer coords so the popup lands on the target
        # screen we chose.
        self.window.tk.call("wm", "geometry", self.window,
                            f"{w}x{h}+{int(x)}+{int(y)}")

    def bring_to_user(self):
        """Bring popup to user's current location."""
        if self.closed:
            return
        try:
            self._position_popup()
            self.window.lift()
            self.window.attributes('-topmost', True)
        except Exception:
            pass

    def _bring_to_attention(self):
        """Bring popup to user's attention when countdown ends."""
        try:
            self.window.lift()
            self.window.attributes('-topmost', True)
            self._flash_button()
        except Exception:
            pass

    def _flash_button(self, count=6):
        """Flash Done button to draw attention."""
        if self.closed or count <= 0:
            return
        try:
            current_color = self.ok_btn.cget('fg_color')
            flash_color = COLORS['accent_warning']
            new_color = flash_color if current_color != flash_color else None
            self.ok_btn.configure(fg_color=new_color)
            self.window.after(200, lambda: self._flash_button(count - 1))
        except Exception:
            pass


# ------------------ CHECK-IN POPUP ------------------

class CheckInPopup:
    """A small, gentle popup that surfaces one user-configurable check-in question
    and reports the answer (or a skip) back via callbacks.

    Mirrors CountdownPopup's window setup (a ``CTkToplevel`` pinned to the active
    Space per #21, kept on top, styled purely from design tokens) but carries no
    countdown/snooze machinery: answering or skipping simply closes it. It exposes
    ``closed`` / ``bring_to_user`` / ``close`` so it can stand in as the app's
    ``active_popup`` interchangeably with CountdownPopup.

    The detail popup is a deliberate select → optional note → Save flow (never
    tap-and-go): a scale/choice/number value is SELECTED (highlighted) first, an
    optional note can ride along, and Save logs value+note together. It also shows
    today's answers for this question; the WHOLE row is the edit affordance
    (hover-tints, click enters edit; click again or "＋ New answer" leaves edit),
    with a per-row ✕ remove (dismissible "Remove?" confirm), and a context title
    ("Update today's answer" / "Add another · N today").

    Callbacks fire at most once total: exactly one of ``on_answer(value, note)``,
    ``on_edit(target_id, value, note)``, ``on_remove(target_id)`` or ``on_skip()``
    — closing the window via its OS control counts as a skip.
    """

    def __init__(self, root, question, entries, on_answer, on_edit, on_remove,
                 on_skip, screen=None):
        self.root = root
        self.question = question
        self.entries = entries or []
        self.on_answer = on_answer
        self.on_edit = on_edit
        self.on_remove = on_remove
        self.on_skip = on_skip
        self.closed = False
        # Answer state. ``selected_value`` holds the chosen scale int / choice str
        # (number is read live from its entry; note is read from the note field).
        self.selected_value = None
        self.value_buttons = {}      # value -> CTkButton (scale/choices highlight)
        self.number_entry = None
        self.note_entry = None
        self.save_button = None
        self.context_label = None
        self.edit_target_id = None   # non-None => Save logs an edit for this entry
        # entry id -> {"row", "value" label, "note" label, "time" str, "note_shown"}:
        # tracked so edit mode can highlight a row and live-preview edits into it.
        self.today_widgets = {}
        self._armed_remove = None    # (button, entry) of a pending "Remove?" confirm, or None
        self.new_answer_btn = None   # "＋ New answer"/"Answering now" status line (recurring only)
        self.actions_row = None      # Skip/Save row (anchor for placing the new-answer link)
        self.screen = screen         # placement screen rect (re-clamp on-screen when re-fitting)

        # Window: pinned to the active Space (multi-monitor #21), topmost, fixed size.
        # No AppleScript activate/focus-restore here — that switched Spaces (#21).
        self.window = ctk.CTkToplevel(root)
        self.window.title(question.text)
        self.window.resizable(False, False)
        pin_to_active_space(self.window)
        self.window.attributes('-topmost', True)
        self.window.geometry(f"{CHECK_IN_POPUP_W}x{CHECK_IN_POPUP_H}")
        # Closing via the OS window control counts as a skip (nothing logged).
        self.window.protocol("WM_DELETE_WINDOW", self._skip)

        container = ctk.CTkFrame(
            self.window, corner_radius=CORNER_RADIUS_PANEL,
            fg_color=COLORS['surface_card'])
        container.pack(fill="both", expand=True)

        ctk.CTkLabel(
            container, text=question.text,
            font=make_font('heading', weight="bold"),
            text_color=COLORS['text_primary'],
            wraplength=CHECK_IN_POPUP_W - 2 * PADDING_PANEL_X
        ).pack(padx=PADDING_PANEL_X, pady=(PADDING_PANEL_Y, SPACE_XXS))

        # Context line (only when re-answering): once-a-day => "Update today's
        # answer"; recurring => "Add another · N today". No line for the first answer.
        if self.entries:
            ctx = (CHECK_IN_UPDATE_CONTEXT if question.once_per_day
                   else CHECK_IN_ADD_CONTEXT_FMT.format(n=len(self.entries)))
            self.context_label = ctk.CTkLabel(
                container, text=ctx, font=make_font('caption'),
                text_color=COLORS['text_secondary'])
            self.context_label.pack(padx=PADDING_PANEL_X, pady=(0, ROW_SPACING))

        self._build_answer(container, question.answer)

        # An optional, always-visible note field for scale/choices/number answers.
        # (A note-type question already built its own entry as the answer control.)
        if self.note_entry is None and question.answer.allow_note:
            self._build_note_entry(container, CHECK_IN_NOTE_PLACEHOLDER)

        # Today's answers for this question; the whole row edits, ✕ removes.
        if self.entries:
            self._build_today_list(container, self.entries)

        # Recurring + already answered: a "＋ New answer" link (hidden until editing)
        # to leave edit mode and add a fresh answer. Once-a-day has one answer, so no link.
        if self.entries and not question.once_per_day:
            self._build_new_answer_affordance(container)

        self._build_actions(container)

        # Center over the main window so it lands on the SAME screen the app is on
        # (multi-monitor #1): a bare CTkToplevel would otherwise open on the primary
        # display. Raw Tk `wm geometry` — CTk's .geometry() mislocates cross-monitor.
        self.window.update_idletasks()
        # Grow to fit the content (min = the design height) so descenders on the
        # scale end-labels ("groggy") aren't clipped by a too-short fixed window.
        w = CHECK_IN_POPUP_W
        h = max(CHECK_IN_POPUP_H, self.window.winfo_reqheight())
        # Center on the active screen and CLAMP fully on-screen. Centering over the
        # (possibly small / edge) main window could push a tall popup off the top, so it
        # flashed and vanished. Mirrors the break popup's placement.
        if screen is not None:
            x, y = center_on_screen(screen, w, h)
            x, y = clamp_onscreen(x, y, w, h, screen)
        elif root is not None and root.winfo_exists():
            x = root.winfo_x() + (root.winfo_width() - w) // 2
            y = root.winfo_y() + (root.winfo_height() - h) // 2
        else:
            x = (self.window.winfo_screenwidth() - w) // 2
            y = (self.window.winfo_screenheight() - h) // 2
        self.window.tk.call("wm", "geometry", self.window, f"{w}x{h}+{int(x)}+{int(y)}")
        if os.environ.get("DFYB_CHECKIN_DEBUG"):
            logging.debug("checkin popup q=%s w=%s h=%s x=%s y=%s reqh=%s "
                          "root=(x%s y%s w%s h%s) screen=(%s x %s)",
                          question.id, w, h, int(x), int(y), self.window.winfo_reqheight(),
                          root.winfo_x(), root.winfo_y(), root.winfo_width(), root.winfo_height(),
                          self.window.winfo_screenwidth(), self.window.winfo_screenheight())

        self.window.lift()

        # Once-a-day + already answered: open directly on its single answer in edit mode
        # (Save then UPDATES it rather than appending). Restore the context to
        # "Update today's answer" — the daily flow reads as an update, not "Editing".
        if question.once_per_day and self.entries:
            self._enter_edit(self.entries[-1])
            if self.context_label is not None:
                self.context_label.configure(text=CHECK_IN_UPDATE_CONTEXT)

    def _refit_height(self):
        """Re-fit the window height to the current content in place, keeping x/y (the
        window is sized ONCE in ``__init__`` while the status line is hidden; entering
        edit / showing "Answering now" grows the content, so without this the bottom
        Skip/Save row and the "Editing" descender get squeezed off). Re-clamps on the
        placement screen so a taller window can't push off the top edge."""
        if self.closed:
            return
        self.window.update_idletasks()
        w = CHECK_IN_POPUP_W
        h = max(CHECK_IN_POPUP_H, self.window.winfo_reqheight())
        x, y = self.window.winfo_x(), self.window.winfo_y()
        if self.screen is not None:
            _x, y = clamp_onscreen(x, y, w, h, self.screen)
        self.window.tk.call("wm", "geometry", self.window, f"{w}x{h}+{int(x)}+{int(y)}")

    # ---- answer controls -------------------------------------------------

    def _build_answer(self, parent, answer):
        """Render the answer control appropriate to the question's answer type.
        Scale/choices/number all SELECT (no auto-submit); Save logs the selection."""
        if answer.type == SCALE:
            self._build_scale(parent, answer)
        elif answer.type == NUMBER:
            self._build_number(parent, answer)
        elif answer.type == CHOICES:
            self._build_choices(parent, answer)
        else:                                    # NOTE: the free text IS the answer
            self._build_note_entry(parent, CHECK_IN_ANSWER_PLACEHOLDER, primary=True)

    def _style_select_button(self, btn, selected):
        """Toggle a scale/choice button between the selected (filled accent) and the
        unselected (transparent + outline) look."""
        if selected:
            btn.configure(
                fg_color=COLORS['accent_primary'],
                hover_color=COLORS['accent_primary_hover'],
                border_width=0, text_color=COLORS['text_on_accent'])
        else:
            btn.configure(
                fg_color="transparent", hover_color=COLORS['surface_hover'],
                border_width=CHECK_IN_SELECT_BORDER_WIDTH,
                border_color=COLORS['border'], text_color=COLORS['text_primary'])

    def _select(self, value):
        """Select a scale/choice value: highlight it, remember it, re-evaluate Save."""
        self._disarm_remove()        # selecting a value cancels a pending "Remove?"
        self.selected_value = value
        for v, btn in self.value_buttons.items():
            self._style_select_button(btn, v == value)
        self._refresh_save_state()
        self._preview_edit()         # live-preview the new value into the edited row
        self._update_status()        # composing: reflect the chosen value in the status line
        self._refit_height()         # the status line may have appeared → re-fit height

    def _build_scale(self, parent, answer):
        """A button per integer in ``[min, max]``; ends labelled with min/max labels.
        Clicking SELECTS (highlights) — Save logs it."""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(padx=PADDING_PANEL_X, pady=SPACE_XS)
        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack()
        for value in range(answer.min, answer.max + 1):
            btn = ctk.CTkButton(
                row, text=str(value), width=CHECK_IN_SCALE_BTN_WIDTH,
                height=BUTTON_HEIGHT_LARGE, corner_radius=CORNER_RADIUS_BUTTON,
                font=make_font('body', weight="bold"),
                command=lambda v=value: self._select(v))
            btn.pack(side="left", padx=SPACE_XXS)
            self.value_buttons[value] = btn
            self._style_select_button(btn, False)
        if answer.min_label or answer.max_label:
            labels = ctk.CTkFrame(frame, fg_color="transparent")
            labels.pack(fill="x", pady=(SPACE_XXS, 0))
            ctk.CTkLabel(
                labels, text=answer.min_label, font=make_font('caption'),
                text_color=COLORS['text_secondary']).pack(side="left")
            ctk.CTkLabel(
                labels, text=answer.max_label, font=make_font('caption'),
                text_color=COLORS['text_secondary']).pack(side="right")

    def _build_choices(self, parent, answer):
        """One full-width button per fixed option, STACKED vertically so any number or
        length of options fits the popup width (laid out side-by-side they overflow and
        clip off the right edge). Clicking SELECTS (highlights) — Save logs it."""
        col = ctk.CTkFrame(parent, fg_color="transparent")
        col.pack(fill="x", padx=PADDING_PANEL_X, pady=SPACE_XS)
        for option in answer.options:
            btn = ctk.CTkButton(
                col, text=str(option), height=BUTTON_HEIGHT_LARGE,
                corner_radius=CORNER_RADIUS_BUTTON, font=make_font('body'),
                command=lambda o=option: self._select(o))
            btn.pack(fill="x", pady=SPACE_XXS)
            self.value_buttons[option] = btn
            self._style_select_button(btn, False)

    def _build_number(self, parent, answer):
        """A single-line numeric entry (int/decimal) with the unit shown beside it.
        The value is read live from the field; Save validates it against min/max."""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(padx=PADDING_PANEL_X, pady=SPACE_XS)
        self.number_entry = ctk.CTkEntry(
            frame, width=CHECK_IN_NUMBER_ENTRY_WIDTH, height=BUTTON_HEIGHT_LARGE,
            corner_radius=CORNER_RADIUS_INPUT, font=make_font('body'),
            placeholder_text=CHECK_IN_NUMBER_PLACEHOLDER)
        self.number_entry.pack(side="left")
        self.number_entry.bind("<KeyRelease>", self._on_input_changed)
        self.number_entry.bind("<Return>", lambda e: self._save())
        if answer.unit:
            ctk.CTkLabel(
                frame, text=answer.unit, font=make_font('body'),
                text_color=COLORS['text_secondary']).pack(side="left", padx=(SPACE_XS, 0))

    def _build_note_entry(self, parent, placeholder, primary=False):
        """A single-line note entry. For a note-type question (``primary``) the text IS
        the answer, so typing gates Save; otherwise it's an optional note that rides along.
        Typing always re-evaluates Save and live-previews into the edited row (both no-ops
        when they don't apply)."""
        self.note_entry = ctk.CTkEntry(
            parent, placeholder_text=placeholder, height=BUTTON_HEIGHT_SMALL,
            corner_radius=CORNER_RADIUS_INPUT, font=make_font('body'))
        self.note_entry.pack(fill="x", padx=PADDING_PANEL_X, pady=SPACE_XS)
        self.note_entry.bind("<Return>", lambda e: self._save())
        self.note_entry.bind("<KeyRelease>", self._on_input_changed)

    def _on_input_changed(self, _event=None):
        """Number/note keystroke: re-evaluate Save, live-preview into the edited row, and
        keep the "Answering now" status line (and window height) in step with the input."""
        self._refresh_save_state()
        self._preview_edit()
        self._update_status()        # composing: reflect the typed value in the status line
        self._refit_height()         # the status line may have appeared/cleared → re-fit

    # ---- Today list (row-as-edit / remove past answers) ------------------

    def _build_today_list(self, parent, entries):
        """Header + one row per today's answer. The WHOLE row is the edit affordance
        (hover-tint + click-to-edit); each row also carries a ✕ remove."""
        ctk.CTkLabel(
            parent, text=CHECK_IN_TODAY_HEADER, font=make_font('caption', weight="bold"),
            text_color=COLORS['text_secondary'], anchor="w"
        ).pack(fill="x", padx=PADDING_PANEL_X, pady=(SPACE_SM, SPACE_XXS))
        for entry in entries:
            self._build_today_row(parent, entry)

    def _build_today_row(self, parent, entry):
        """One answer row: a value line (``<time> · <value>``, primary) and, when the
        entry has a note, a note subtext line (tertiary) beneath it. The whole row
        hover-tints and click-toggles edit mode; a ✕ on the right removes (dismissible
        confirm). Value + note labels are tracked so edit mode can highlight/preview."""
        eid = entry["id"]
        row = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=CORNER_RADIUS_BUTTON)
        row.pack(fill="x", padx=SPACE_XS, pady=SPACE_XXS)
        remove_btn = ctk.CTkButton(
            row, text=CHECK_IN_REMOVE_ICON, width=CHECK_IN_ICON_BTN_WIDTH,
            height=BUTTON_HEIGHT_SMALL, corner_radius=CORNER_RADIUS_BUTTON,
            fg_color="transparent", hover_color=COLORS['surface_hover'],
            text_color=COLORS['text_secondary'], font=make_font('body'))
        remove_btn.configure(command=lambda b=remove_btn, e=entry: self._arm_remove(b, e))
        remove_btn.pack(side="right", padx=(SPACE_XXS, 0))
        # Left text column, with comfortable LEFT padding so it doesn't hug the edge.
        text_col = ctk.CTkFrame(row, fg_color="transparent")
        text_col.pack(side="left", fill="x", expand=True, padx=(SPACE_MD, SPACE_XS))
        value_lbl = ctk.CTkLabel(
            text_col, text="", font=make_font('caption'), text_color=COLORS['text_primary'],
            anchor="w", justify="left", wraplength=CHECK_IN_TODAY_ROW_TEXT_WRAP)
        value_lbl.pack(fill="x", anchor="w")
        note_lbl = ctk.CTkLabel(
            text_col, text="", font=make_font('caption'), text_color=COLORS['text_tertiary'],
            anchor="w", justify="left", wraplength=CHECK_IN_TODAY_ROW_TEXT_WRAP)
        self.today_widgets[eid] = {
            "row": row, "value": value_lbl, "note": note_lbl, "note_shown": False,
            "time": time.strftime(CHECK_IN_TIME_FMT, time.localtime(entry["ts"]))}
        self._set_row_text(eid, entry.get("value"), entry.get("note"))
        # Whole row is one hover target; the text column (not the ✕) is the click target.
        self._bind_recursive(row, on_enter=lambda e, r=row: self._hover_enter(r),
                             on_leave=lambda e, r=row: self._hover_leave(r))
        self._bind_recursive(text_col, on_click=lambda e, en=entry: self._on_row_click(en),
                             cursor="pointinghand")
        row.bind("<Button-1>", lambda e, en=entry: self._on_row_click(en), add="+")
        try:
            row.configure(cursor="pointinghand")
        except Exception:
            pass

    def _bind_recursive(self, widget, on_click=None, on_enter=None, on_leave=None, cursor=None):
        """Bind the given handlers on ``widget`` and every descendant so a composite CTk
        row reacts uniformly (a click/hover on the inner text label counts as one on the
        row). Handlers are additive (``add="+"``) so CTk's own bindings still fire."""
        if on_click is not None:
            widget.bind("<Button-1>", on_click, add="+")
        if on_enter is not None:
            widget.bind("<Enter>", on_enter, add="+")
        if on_leave is not None:
            widget.bind("<Leave>", on_leave, add="+")
        if cursor is not None:
            try:
                widget.configure(cursor=cursor)
            except Exception:
                pass
        for child in widget.winfo_children():
            self._bind_recursive(child, on_click, on_enter, on_leave, cursor)

    # ---- row text (value line + note subtext) ---------------------------

    def _value_summary(self, value, note):
        """The value-line summary (after the time). For a note-type question the note IS
        the answer, so it shows here; otherwise the answer value shows here."""
        if self.question.answer.type == NOTE:
            return format_check_in_value({"value": None, "note": note})
        return format_check_in_value({"value": value, "note": None})

    def _note_subtext(self, note):
        """The note subtext beneath the value line, or None (note-type keeps its note on
        the value line; a blank note shows no subtext)."""
        if self.question.answer.type == NOTE:
            return None
        return str(note) if note else None

    def _set_row_text(self, eid, value, note):
        """Render a Today row's value line + note subtext from a value/note pair — the
        stored entry (build / revert) or the live control state (preview). Shows/hides
        the note subtext line as the note appears/clears."""
        w = self.today_widgets.get(eid)
        if w is None:
            return
        w["value"].configure(text=CHECK_IN_TODAY_ROW_FMT.format(
            time=w["time"], summary=self._value_summary(value, note)))
        subtext = self._note_subtext(note)
        if subtext:
            w["note"].configure(text=subtext)
            if not w["note_shown"]:
                w["note"].pack(fill="x", anchor="w")
                w["note_shown"] = True
        elif w["note_shown"]:
            w["note"].pack_forget()
            w["note_shown"] = False

    # ---- hover highlight -------------------------------------------------

    def _is_edited_row(self, row):
        """True if ``row`` is the Today row currently in edit mode — it keeps its stronger
        edit highlight, so hover must not override it."""
        if self.edit_target_id is None:
            return False
        w = self.today_widgets.get(self.edit_target_id)
        return bool(w) and w["row"] is row

    def _hover_enter(self, row):
        """Pointer over a Today row → subtle tint (unless it's the edited row)."""
        if self._is_edited_row(row):
            return
        row.configure(fg_color=COLORS['surface_hover'])

    def _hover_leave(self, row):
        """Pointer left a Today row → drop the tint, but only if it TRULY left: crossing
        into a child fires a spurious <Leave> on the row/its widgets, so walk up from the
        widget under the pointer and keep the tint while still inside the row."""
        if self._is_edited_row(row):
            return
        try:
            under = row.winfo_containing(*row.winfo_pointerxy())
        except Exception:
            under = None
        w = under
        while w is not None:
            if w is row:
                return                       # still within the row → keep the tint
            w = getattr(w, "master", None)
        row.configure(fg_color="transparent")

    # ---- remove (dismissible confirm) -----------------------------------

    def _arm_remove(self, btn, entry):
        """First ✕ tap arms an inline "Remove?" confirm; a second tap actually removes.
        Arming first dismisses any other pending confirm."""
        self._disarm_remove()
        btn.configure(
            text=CHECK_IN_REMOVE_CONFIRM_LABEL, width=CHECK_IN_REMOVE_CONFIRM_WIDTH,
            fg_color=COLORS['accent_warning'], hover_color=COLORS['accent_warning_hover'],
            text_color=COLORS['text_on_accent'],
            command=lambda e=entry: self._remove(e))
        self._armed_remove = (btn, entry)

    def _disarm_remove(self):
        """Revert an armed "Remove?" button back to its idle ✕ (cancelling the pending
        removal). Called at the start of any other interaction, so clicking elsewhere
        dismisses the confirm."""
        if self._armed_remove is None:
            return
        btn, entry = self._armed_remove
        self._armed_remove = None
        try:
            btn.configure(
                text=CHECK_IN_REMOVE_ICON, width=CHECK_IN_ICON_BTN_WIDTH,
                fg_color="transparent", hover_color=COLORS['surface_hover'],
                text_color=COLORS['text_secondary'],
                command=lambda b=btn, e=entry: self._arm_remove(b, e))
        except Exception:
            pass

    def _remove(self, entry):
        target = entry["id"]
        self._finish(lambda: self.on_remove(target))

    # ---- edit mode (enter / exit / preview / highlight) -----------------

    def _on_row_click(self, entry):
        """Click a Today row → edit that entry. Always ENTERS edit (never toggles): a click
        on a CTk composite row can be delivered twice, and a toggle would cancel itself, so
        re-entering the same entry is a harmless no-op. Leave edit via "＋ New answer" / Skip."""
        self._enter_edit(entry)

    def _build_new_answer_affordance(self, parent):
        """Create (hidden) the mode-aware status line (recurring-answered only). ``_update_status``
        drives it: while EDITING it is the clickable "＋ New answer" link (leaves edit to compose
        a fresh answer); while COMPOSING a new answer it becomes a passive "Answering now: <value>"
        readout, or hides when nothing is chosen. Packs before the actions row / hides itself."""
        self.new_answer_btn = ctk.CTkLabel(
            parent, text=CHECK_IN_NEW_ANSWER_LABEL, font=make_font('caption', weight="bold"),
            text_color=COLORS['accent_primary'], anchor="w", cursor="pointinghand")
        self.new_answer_btn.bind("<Button-1>", lambda e: self._new_answer())

    def _new_answer(self):
        """Leave edit mode to compose a FRESH answer while KEEPING the current control
        selection so it seeds the new answer (unlike ``_exit_edit``, which clears it).
        Recurring-answered only; the status line flips to "Answering now: <value>"."""
        self._disarm_remove()
        target = self.edit_target_id
        self.edit_target_id = None
        # Restore the row we were previewing back to its saved value — we're no longer
        # editing it; the kept selection now seeds a NEW answer, not an edit of that row.
        if target is not None:
            entry = next((e for e in self.entries if e["id"] == target), None)
            if entry is not None:
                self._set_row_text(target, entry.get("value"), entry.get("note"))
        self._highlight_edit_row(None)
        if self.context_label is not None:
            self.context_label.configure(
                text=CHECK_IN_ADD_CONTEXT_FMT.format(n=len(self.entries)))
        self._update_status()
        self._refresh_save_state()
        self._refit_height()

    def _update_status(self):
        """Drive the mode-aware status line (recurring-answered only). Editing an existing
        entry → the clickable "＋ New answer" link (click leaves edit to compose fresh);
        composing a new answer with a value chosen → a passive "Answering now: <value>";
        composing with nothing chosen yet → hidden. Cheap no-op when there is no line."""
        if self.new_answer_btn is None:
            return
        if self.edit_target_id is not None:
            self.new_answer_btn.unbind("<Button-1>")
            self.new_answer_btn.bind("<Button-1>", lambda e: self._new_answer())
            self.new_answer_btn.configure(
                text=CHECK_IN_NEW_ANSWER_LABEL, text_color=COLORS['accent_primary'],
                cursor="pointinghand")
            self.new_answer_btn.pack(before=self.actions_row, fill="x",
                                     padx=PADDING_PANEL_X, pady=(0, SPACE_XS))
        elif self._has_valid_answer():
            summary = self._value_summary(self._current_value(), self._read_note())
            self.new_answer_btn.unbind("<Button-1>")
            self.new_answer_btn.configure(
                text=CHECK_IN_ANSWERING_NOW_FMT.format(value=summary),
                text_color=COLORS['text_secondary'], cursor="")
            self.new_answer_btn.pack(before=self.actions_row, fill="x",
                                     padx=PADDING_PANEL_X, pady=(0, SPACE_XS))
        else:
            self.new_answer_btn.pack_forget()

    def _enter_edit(self, entry):
        """Enter EDIT MODE for a past answer: pre-fill the control + note with its value,
        flip the context line to "Editing", strong-highlight its row, reveal the
        "＋ New answer" link (recurring), and route Save to ``on_edit``."""
        self._disarm_remove()
        self.edit_target_id = entry["id"]
        atype = self.question.answer.type
        value = entry.get("value")
        if atype in (SCALE, CHOICES):
            if value in self.value_buttons:
                self._select(value)
        elif atype == NUMBER and self.number_entry is not None:
            self.number_entry.delete(0, "end")
            if value is not None:
                self.number_entry.insert(0, str(value))
        if self.note_entry is not None:
            self.note_entry.delete(0, "end")
            if entry.get("note"):
                self.note_entry.insert(0, str(entry["note"]))
        if self.context_label is not None:
            self.context_label.configure(text=CHECK_IN_EDITING_CONTEXT)
        self._highlight_edit_row(entry["id"])
        self._preview_edit()         # reconcile the row with the fully pre-filled controls
        self._refresh_save_state()
        self._update_status()        # editing → show the clickable "＋ New answer" link
        self._refit_height()         # the status line grew the content → re-fit height

    def _exit_edit(self):
        """Leave edit mode: clear the target, deselect the answer control + note, restore
        the previewed row to its stored value, drop all row highlights, hide the
        "＋ New answer" link, and reset the context line to its default."""
        self._disarm_remove()
        target = self.edit_target_id
        self.edit_target_id = None
        self.selected_value = None
        for btn in self.value_buttons.values():
            self._style_select_button(btn, False)
        if self.number_entry is not None:
            self.number_entry.delete(0, "end")
        if self.note_entry is not None:
            self.note_entry.delete(0, "end")
        # Restore the row we were previewing back to its saved value, then un-highlight.
        if target is not None:
            entry = next((e for e in self.entries if e["id"] == target), None)
            if entry is not None:
                self._set_row_text(target, entry.get("value"), entry.get("note"))
        self._highlight_edit_row(None)
        if self.context_label is not None:
            if self.question.once_per_day:
                self.context_label.configure(text=CHECK_IN_UPDATE_CONTEXT)
            elif self.entries:
                self.context_label.configure(
                    text=CHECK_IN_ADD_CONTEXT_FMT.format(n=len(self.entries)))
        self._refresh_save_state()
        self._update_status()        # cleared controls → status line hides (nothing chosen)
        self._refit_height()         # content shrank → re-fit height

    def _preview_edit(self):
        """While editing, mirror the current control state (value + note) into the edited
        row's text so it previews the pending answer. No-op when not editing."""
        if self.edit_target_id is None:
            return
        self._set_row_text(self.edit_target_id, self._current_value(), self._read_note())

    def _highlight_edit_row(self, target_id):
        """Mark the Today row being edited — a filled tint + accent-coloured value text
        (no border, which read as stray blue lines). ``target_id`` None clears all."""
        for eid, w in self.today_widgets.items():
            editing = eid == target_id
            w["row"].configure(fg_color=COLORS['surface_hover'] if editing else "transparent")
            w["value"].configure(
                text_color=COLORS['accent_primary'] if editing else COLORS['text_primary'])

    # ---- actions (Skip / Save) ------------------------------------------

    def _build_actions(self, parent):
        """The bottom Skip (transparent) + Save (accent) row. Save is disabled until
        there is a valid value; ``_refresh_save_state`` toggles it."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=PADDING_PANEL_X, pady=(SPACE_XS, PADDING_PANEL_Y))
        self.actions_row = row       # anchor: the "＋ New answer" link packs before this
        ctk.CTkButton(
            row, text=CHECK_IN_SKIP_LABEL, command=self._skip,
            height=BUTTON_HEIGHT_LARGE, corner_radius=CORNER_RADIUS_BUTTON,
            fg_color="transparent", hover_color=COLORS['surface_hover'],
            text_color=COLORS['text_secondary'], font=make_font('body')
        ).pack(side="left")
        self.save_button = ctk.CTkButton(
            row, text=CHECK_IN_SAVE_LABEL, command=self._save,
            height=BUTTON_HEIGHT_LARGE, corner_radius=CORNER_RADIUS_BUTTON,
            fg_color=COLORS['accent_primary'], hover_color=COLORS['accent_primary_hover'],
            font=make_font('body', weight="bold"))
        self.save_button.pack(side="right")
        self._refresh_save_state()

    def _refresh_save_state(self):
        """Enable Save only when the current input is a valid answer."""
        if self.save_button is None:
            return
        self.save_button.configure(
            state="normal" if self._has_valid_answer() else "disabled")

    # ---- value reading / validity ---------------------------------------

    def _parse_number(self):
        """The number-entry value as int (when whole) / float, or None if unparseable
        or outside the answer's min..max."""
        if self.number_entry is None:
            return None
        raw = self.number_entry.get().strip()
        if not raw:
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        if value.is_integer():
            value = int(value)
        return value if answer_is_valid(self.question.answer, value) else None

    def _current_value(self):
        """The value to log for the current answer type (None for a note-type answer)."""
        atype = self.question.answer.type
        if atype == NUMBER:
            return self._parse_number()
        if atype == NOTE:
            return None
        return self.selected_value

    def _has_valid_answer(self):
        """Whether there is enough to Save: a selected scale/choice, a parseable number,
        or (note-type) a non-empty note."""
        atype = self.question.answer.type
        if atype == NOTE:
            return self._read_note() is not None
        if atype == NUMBER:
            return self._parse_number() is not None
        return self.selected_value is not None

    # ---- lifecycle -------------------------------------------------------

    def _read_note(self):
        """The trimmed note text, or None when there is no note field / it's blank."""
        if self.note_entry is None:
            return None
        try:
            return self.note_entry.get().strip() or None
        except Exception:
            return None

    def _save(self):
        """Log the current value + note — as an edit when in edit mode, else a new answer."""
        if not self._has_valid_answer():
            return
        value = self._current_value()
        note = self._read_note()
        if self.edit_target_id is not None:
            target = self.edit_target_id
            self._finish(lambda: self.on_edit(target, value, note))
        elif self.question.once_per_day and self.entries:
            # once-a-day: replace today's single answer instead of appending a duplicate
            target = self.entries[-1]["id"]
            self._finish(lambda: self.on_edit(target, value, note))
        else:
            self._finish(lambda: self.on_answer(value, note))

    def _skip(self):
        self._finish(self.on_skip)

    def _finish(self, callback):
        """Fire exactly one of on_answer/on_edit/on_remove/on_skip (guarded once), then tear down."""
        if self.closed:
            return
        if os.environ.get("DFYB_CHECKIN_DEBUG"):
            logging.debug("checkin _finish (already closed=%s)", self.closed)
        self.closed = True
        try:
            callback()
        except Exception:
            logging.exception("check-in callback failed")
        self._destroy()

    def _destroy(self):
        try:
            self.window.destroy()
        except Exception:
            pass

    def close(self):
        """Force-close the popup (e.g. app reset); treated as a skip — nothing logged."""
        self._skip()

    def bring_to_user(self):
        """Raise / keep the popup on top — interface parity with CountdownPopup so a
        CheckInPopup can serve as the app's ``active_popup``."""
        if self.closed:
            return
        try:
            self.window.lift()
            self.window.attributes('-topmost', True)
        except Exception:
            pass


# ------------------ BREAK CONFIG PANEL ------------------

class CollapsibleSection(ctk.CTkFrame):
    """A card with a clickable header (title + chevron) that expands/collapses a
    body frame with a height animation. Callers/subclasses fill ``self.body`` and
    then call ``finalize()``. Shared by the break-config panels and the settings
    sections so both use one animation and one visual grammar."""

    def __init__(self, parent, title, *, expanded=True, on_toggle=None,
                 on_resize=None, title_font=None):
        super().__init__(parent, corner_radius=CORNER_RADIUS_PANEL,
                         fg_color=COLORS['surface_card'])
        self._initial_expanded = expanded
        self._expanded = True            # built expanded; finalize() collapses if asked
        self._on_toggle = on_toggle
        self._on_resize = on_resize      # fired after a user toggle (to resize the window)
        self._animating = False
        self._animation_id = None
        self._expanded_height = None
        self._collapsed_height = PANEL_COLLAPSED_HEIGHT
        self._build_header(title, title_font or make_font('body', weight="bold"))
        self.body = ctk.CTkFrame(self, fg_color="transparent")

    def _build_header(self, title, font):
        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.pack(fill="x", padx=PADDING_PANEL_X,
                               pady=(PADDING_PANEL_Y // 2, 0))
        self.header_label = ctk.CTkLabel(self.header_frame, text=title,
                                         font=font, cursor="pointinghand")
        self.header_label.pack(side="left")
        self.header_right = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        self.header_right.pack(side="right")
        self.chevron = ctk.CTkLabel(
            self.header_right, text="\u25B2", font=make_font('label'),
            text_color=COLORS['text_secondary'], cursor="pointinghand")
        self.chevron.pack(side="right")
        for widget in (self.header_frame, self.header_label, self.chevron):
            widget.bind("<Button-1>", lambda e: self.toggle_expand())
        self.header_frame.bind("<Return>", lambda e: self.toggle_expand())
        self.header_frame.bind("<space>", lambda e: self.toggle_expand())

    def finalize(self):
        """Call after filling ``self.body``: measure the expanded height, then
        apply the requested initial expand/collapse state (no animation)."""
        self.body.pack(fill="x", padx=0, pady=0)
        self.update_idletasks()
        self._expanded_height = self.winfo_reqheight()
        if not self._initial_expanded:
            self.collapse(animate=False)

    def is_expanded(self):
        return self._expanded

    def _on_expand_visual(self):
        """Hook: subclass header tweak when expanding (e.g. hide a summary)."""

    def _on_collapse_visual(self):
        """Hook: subclass header tweak when collapsing (e.g. show a summary)."""

    def toggle_expand(self):
        # Instant snap. Tk re-lays-out and repaints the whole window on every
        # resize step, so animating the reveal jitters the text and can flash
        # neighbours — instant is the crisp choice (macOS System Settings does
        # the same). expand() still grows the window BEFORE showing the body, so
        # content and window appear together in one frame (no pop-before).
        # NOTE: a genuinely smooth accordion is deferred to the native rewrite.
        if self._expanded:
            self.collapse(animate=False)
        else:
            self.expand(animate=False)
        if self._on_toggle is not None:
            self._on_toggle(self._expanded)

    def expand(self, animate=True):
        if self._expanded:
            return
        if self._animation_id:
            self.after_cancel(self._animation_id)
            self._animation_id = None
        self._expanded = True
        self.body.pack(fill="x", padx=0, pady=0)
        self._on_expand_visual()
        self.chevron.configure(text="\u25B2")
        self.header_frame.pack_configure(pady=(PADDING_PANEL_Y // 2, 0))
        target = self._expanded_height or self.winfo_reqheight()
        # Grow the window ONCE up-front (by the height this section will add) so
        # the reveal has room; the section then animates inside it — no per-frame
        # window resize (which reflows and jitters the whole window).
        if self._on_resize is not None:
            self._on_resize(target - self._collapsed_height)

        def on_complete():
            self._animating = False
            self.pack_propagate(True)
            # Correct the up-front estimate once the reveal has settled (one
            # resize — the delta from _expanded_height can be a few px off).
            if self._on_resize is not None:
                self._on_resize(0)

        if not animate:
            on_complete()
            return
        self._animating = True
        self._animate_height(self._collapsed_height, target,
                             ANIMATION_EXPAND_DURATION, on_complete)

    def collapse(self, animate=True):
        if not self._expanded:
            return
        if self._animation_id:
            self.after_cancel(self._animation_id)
            self._animation_id = None
        self._expanded = False
        current = self.winfo_height()
        if current <= 1:
            current = self._expanded_height or self._collapsed_height

        def on_complete():
            self._animating = False
            self.body.pack_forget()
            self._on_collapse_visual()
            self.chevron.configure(text="\u25BC")
            self.header_frame.pack_configure(
                pady=(PADDING_PANEL_Y // 2, PADDING_PANEL_Y // 2))
            # Shrink the window ONCE, after the body has fully collapsed.
            if self._on_resize is not None:
                self._on_resize(0)

        if not animate:
            self.pack_propagate(False)
            self.configure(height=self._collapsed_height)
            on_complete()
            return
        self._animating = True
        self._animate_height(current, self._collapsed_height,
                             ANIMATION_COLLAPSE_DURATION, on_complete)

    def _animate_height(self, start_height, end_height, duration, on_complete):
        """Frame-by-frame height animation with easing."""
        if prefers_reduced_motion():
            self.configure(height=end_height)
            self.pack_propagate(False)
            on_complete()
            return
        total_frames = max(1, duration // ANIMATION_FRAME_INTERVAL)
        frame = [0]

        def step():
            if frame[0] >= total_frames:
                self.configure(height=end_height)
                self._animation_id = None
                on_complete()
                return
            eased = ease_out_quad(frame[0] / total_frames)
            height = int(start_height + (end_height - start_height) * eased)
            self.configure(height=height)
            frame[0] += 1
            self._animation_id = self.after(ANIMATION_FRAME_INTERVAL, step)

        self.pack_propagate(False)
        step()


class BreakConfigPanel(CollapsibleSection):
    """Collapsible panel for configuring a single break."""

    def __init__(self, parent, config, on_test, on_resize=None):
        super().__init__(parent, title=config.name.get(), on_resize=on_resize)
        self.config = config
        self.on_test = on_test
        # Break-specific header summary: the timer, shown only when collapsed.
        self.header_timer = ctk.CTkLabel(
            self.header_right, text="--:--", font=make_font('body', weight="bold"))
        self._build_body()
        self.finalize()

    def _on_expand_visual(self):
        self.header_timer.pack_forget()

    def _on_collapse_visual(self):
        self.header_timer.pack(side="left", padx=(0, SPACE_MD))

    def _build_body(self):
        # Row 1: Interval and Duration
        row1 = ctk.CTkFrame(self.body, fg_color="transparent")
        row1.pack(fill="x", padx=PADDING_PANEL_X, pady=(ROW_SPACING // 2, ROW_SPACING))

        ctk.CTkLabel(
            row1, text="Every:",
            font=make_font('label')
        ).pack(side="left")
        self.interval_entry = ctk.CTkEntry(
            row1, width=70, height=36,
            textvariable=self.config.interval_value,
            font=make_font('body'),
            corner_radius=CORNER_RADIUS_INPUT
        )
        self.interval_entry.pack(side="left", padx=(SPACE_SM, SPACE_XXS))
        interval_unit = ctk.CTkComboBox(
            row1, variable=self.config.interval_unit,
            values=TIME_UNITS, width=80, height=36, state="readonly",
            font=make_font('body'),
            corner_radius=CORNER_RADIUS_INPUT
        )
        interval_unit.pack(side="left")

        ctk.CTkLabel(
            row1, text="Duration:",
            font=make_font('label')
        ).pack(side="left", padx=(SPACE_XL, 0))
        duration_entry = ctk.CTkEntry(
            row1, width=70, height=36,
            textvariable=self.config.duration_value,
            font=make_font('body'),
            corner_radius=CORNER_RADIUS_INPUT
        )
        duration_entry.pack(side="left", padx=(SPACE_SM, SPACE_XXS))
        duration_unit = ctk.CTkComboBox(
            row1, variable=self.config.duration_unit,
            values=TIME_UNITS, width=80, height=36, state="readonly",
            font=make_font('body'),
            corner_radius=CORNER_RADIUS_INPUT
        )
        duration_unit.pack(side="left")

        # Row 2: Sounds
        row2 = ctk.CTkFrame(self.body, fg_color="transparent")
        row2.pack(fill="x", padx=PADDING_PANEL_X, pady=(0, ROW_SPACING))

        ctk.CTkLabel(
            row2, text="Start:",
            font=make_font('label')
        ).pack(side="left")
        start_sound = ctk.CTkComboBox(
            row2, variable=self.config.start_sound,
            values=list(SOUNDS.keys()), width=130, height=36, state="readonly",
            font=make_font('body'),
            corner_radius=CORNER_RADIUS_INPUT
        )
        start_sound.pack(side="left", padx=(SPACE_SM, SPACE_XXS))
        ctk.CTkButton(
            row2, text="Play", width=40, height=BUTTON_HEIGHT_SMALL,
            corner_radius=CORNER_RADIUS_INPUT,
            fg_color=COLORS['surface_hover'],
            hover_color=COLORS['border'],
            font=make_font('caption'),
            command=lambda: play_sound(self.config.start_sound.get())
        ).pack(side="left", padx=(0, SPACE_LG))

        ctk.CTkLabel(
            row2, text="End:",
            font=make_font('label')
        ).pack(side="left")
        end_sound = ctk.CTkComboBox(
            row2, variable=self.config.end_sound,
            values=list(SOUNDS.keys()), width=130, height=36, state="readonly",
            font=make_font('body'),
            corner_radius=CORNER_RADIUS_INPUT
        )
        end_sound.pack(side="left", padx=(SPACE_SM, SPACE_XXS))
        ctk.CTkButton(
            row2, text="Play", width=40, height=BUTTON_HEIGHT_SMALL,
            corner_radius=CORNER_RADIUS_INPUT,
            fg_color=COLORS['surface_hover'],
            hover_color=COLORS['border'],
            font=make_font('caption'),
            command=lambda: play_sound(self.config.end_sound.get())
        ).pack(side="left")

        # Row 3: Options and Timer
        row3 = ctk.CTkFrame(self.body, fg_color="transparent")
        row3.pack(fill="x", padx=PADDING_PANEL_X, pady=(0, PADDING_PANEL_Y))

        ctk.CTkCheckBox(
            row3, text="Loop end sound",
            variable=self.config.loop_end_sound,
            font=make_font('label')
        ).pack(side="left")

        ctk.CTkCheckBox(
            row3, text="Auto-dismiss",
            variable=self.config.auto_dismiss,
            font=make_font('label')
        ).pack(side="left", padx=(SPACE_LG, 0))

        ctk.CTkCheckBox(
            row3, text="Snoozable",
            variable=self.config.snoozable,
            font=make_font('label')
        ).pack(side="left", padx=(SPACE_LG, 0))

        # Test button on right
        ctk.CTkButton(
            row3, text="Test",
            command=lambda: self.on_test(self.config),
            width=60, height=BUTTON_HEIGHT_SMALL,
            corner_radius=CORNER_RADIUS_INPUT,
            fg_color="transparent",
            border_width=1,
            border_color=COLORS['border'],
            hover_color=COLORS['surface_hover'],
            text_color=COLORS['text_secondary'],
            font=make_font('label')
        ).pack(side="right")

        self.config.timer_label = ctk.CTkLabel(
            row3, text="--:--",
            font=make_font('body', weight="bold")
        )
        self.config.timer_label.pack(side="right", padx=(0, SPACE_LG))

        ctk.CTkLabel(
            row3, text="Next:",
            font=make_font('label'),
            text_color=COLORS['text_secondary']
        ).pack(side="right")

    def focus_config(self):
        """Expand (if collapsed) and put keyboard focus in the interval field."""
        if not self._expanded:
            self.expand()
        self.interval_entry.focus_set()

    def update_header_timer(self, time_text):
        """Update the header timer display (shown when collapsed)."""
        self.header_timer.configure(text=time_text)


# ------------------ MAIN APP ------------------

class BreakApp:
    def __init__(self, root):
        self.root = root
        root.title(f"{APP_NAME}  ✦ DEV" if IS_DEV else APP_NAME)
        root.resizable(False, False)

        self.running = False
        self.paused = False
        self.stop_event = threading.Event()
        self.break_queue = []
        self._pending_snoozes = []   # entries: {name, fire_time, after_id}
        self._snooze_rows = {}       # id(entry) -> {"frame", "status"}
        self.active_popup = None
        self._active_break_name = None  # name of the break the popup is showing (dedup, #50)
        self.break_start_time = None
        self.event_log = EventLog(EVENTS_FILE)
        self._episode = None  # idle/deferred dedup marker for the smart-timing loop
        self._due_since = {}   # break name -> ts it first became due (deferred-duration, #85)
        self._resume_streak = 0       # consecutive "user is back" samples while paused (#77)
        self._resume_prompted = False # already offered to resume this pause episode (#77)
        self._resume_card = None      # the floating "resume?" card, or None
        self._resume_card_after = None  # auto-dismiss timer id for the resume card
        self._held = None      # reason the due break is currently held (transparency)
        self._anticipated = None  # deferral context active but nothing due yet (#74)
        self._rested_ack_until = None  # time.time() until which to show "welcome back"
        self._fullscreen_grace = 0  # ticks of fullscreen hysteresis left (#46)
        self._meeting_grace = 0     # ticks of mic-in-use hysteresis left (#84)
        self._active_grace = 0      # ticks of active-input hysteresis left (#84)
        self._countdown_color = None  # cached default row-countdown color (for un-greying, #84)
        self._debounce_after = {}   # key -> pending after-id for debounced commits (#47)
        self._timer_generation = 0  # bumped each start(); stale threads exit

        # Default break configurations
        self.default_breaks = [
            {"name": "Micro Break", "interval_val": 25, "interval_unit": "min",
             "duration_val": 5, "duration_unit": "sec", "start_sound": "Ping",
             "end_sound": "Glass", "loop_end_sound": False, "auto_dismiss": True,
             "snoozable": False},
            {"name": "Normal Break", "interval_val": 50, "interval_unit": "min",
             "duration_val": 10, "duration_unit": "min", "start_sound": "Glass",
             "end_sound": "Submarine", "loop_end_sound": True, "auto_dismiss": False,
             "snoozable": True}
        ]

        # Load saved preferences or use defaults
        self.saved_prefs = self._load_preferences()
        # Per-section open/closed state for the settings window (persisted).
        self._sections_expanded = dict(self.saved_prefs.get("sections_expanded", {}))

        # Restore saved window position (size is derived from content after UI build)
        self._saved_position = None
        if "window_geometry" in self.saved_prefs:
            saved = self.saved_prefs["window_geometry"]
            if "+" in saved:
                self._saved_position = "+" + saved.split("+", 1)[1]

        # Always-on-top preference (default True)
        self.always_on_top = ctk.BooleanVar(
            value=self.saved_prefs.get("always_on_top", True)
        )
        self.always_on_top.trace_add('write', self._apply_always_on_top)
        root.attributes('-topmost', self.always_on_top.get())

        self.defer_during_meetings = ctk.BooleanVar(
            value=self.saved_prefs.get("defer_during_meetings", True)
        )
        self.defer_during_meetings.trace_add('write', self._save_preferences)

        self.defer_during_fullscreen = ctk.BooleanVar(
            value=self.saved_prefs.get("defer_during_fullscreen", True)
        )
        self.defer_during_fullscreen.trace_add('write', self._save_preferences)

        self.defer_while_active = ctk.BooleanVar(
            value=self.saved_prefs.get("defer_while_active", False)
        )
        self.defer_while_active.trace_add('write', self._save_preferences)
        self.activity_pause_seconds = ctk.IntVar(
            value=self.saved_prefs.get("activity_pause_seconds", ACTIVITY_PAUSE_DEFAULT)
        )
        self.activity_pause_seconds.trace_add('write', self._save_preferences)
        self.away_idle_seconds = ctk.IntVar(
            value=self.saved_prefs.get("away_idle_seconds", AWAY_IDLE_THRESHOLD_SECONDS))
        self.away_idle_seconds.trace_add('write', self._save_preferences)
        self.natural_break_seconds = ctk.IntVar(
            value=self.saved_prefs.get("natural_break_seconds",
                                       NATURAL_BREAK_IDLE_THRESHOLD_SECONDS))
        self.natural_break_seconds.trace_add('write', self._save_preferences)
        # Whether bare mouse movement counts as activity for wait-until-you-pause
        # (default off — typing/clicks/scroll count, cursor nudges don't) (#41).
        self.count_mouse_move = ctk.BooleanVar(
            value=self.saved_prefs.get("count_mouse_move", False))
        self.count_mouse_move.trace_add('write', self._save_preferences)
        # While paused, offer to resume when you clearly return (#77). Toggle +
        # adjustable sensitivity (consecutive ~1s "back" samples before prompting).
        self.prompt_resume_when_back = ctk.BooleanVar(
            value=self.saved_prefs.get("prompt_resume_when_back", True))
        self.prompt_resume_when_back.trace_add('write', self._save_preferences)
        self.resume_prompt_samples = ctk.IntVar(
            value=self.saved_prefs.get("resume_prompt_samples", RESUME_PROMPT_DEFAULT_SAMPLES))
        self.resume_prompt_samples.trace_add('write', self._save_preferences)
        # Proactively show "your break will wait" while in a call / fullscreen (#74).
        self.show_anticipated_defer = ctk.BooleanVar(
            value=self.saved_prefs.get("show_anticipated_defer", True))
        self.show_anticipated_defer.trace_add('write', self._save_preferences)

        # Default snooze length (seconds), remembered from the ▾ picker.
        # Migrates an old minutes-based pref (×60) so existing configs still load.
        self.snooze_seconds = ctk.IntVar(
            value=self.saved_prefs.get(
                "snooze_seconds",
                self.saved_prefs.get("snooze_minutes", DEFAULT_SNOOZE_SECONDS // 60) * 60)
        )

        # Check-ins (#9 habits): master toggle + editable question list + prompt-timing
        # state cache. Merged from saved prefs so older configs load unchanged.
        _ci_enabled, _ci_questions = merge_check_ins(self.saved_prefs)
        self.check_ins_enabled = ctk.BooleanVar(value=_ci_enabled)
        self.check_ins_enabled.trace_add('write', self._save_preferences)
        self.check_in_questions = [dict(q) for q in _ci_questions]     # editable working copy
        self.check_in_state = self.saved_prefs.get(
            "check_in_state", {"last_prompted": {}, "last_prompt_ts": 0.0})

        self.popup_placement = ctk.StringVar(
            value=self.saved_prefs.get("popup_placement", "active")
        )
        self.popup_placement.trace_add('write', self._save_preferences)

        self.main_window_placement = ctk.StringVar(
            value=self.saved_prefs.get("main_window_placement", MAIN_WINDOW_PLACEMENT_DEFAULT)
        )
        self.main_window_placement.trace_add('write', self._save_preferences)

        # Update check preference (default True)
        self.check_for_updates = ctk.BooleanVar(
            value=self.saved_prefs.get("check_for_updates", True)
        )
        self.available_update = None  # (version, url) when update found

        # Create break configurations from saved or default values
        self.breaks = []
        for i, default in enumerate(self.default_breaks):
            prefs = self.saved_prefs.get("breaks", [{}] * len(self.default_breaks))
            break_prefs = prefs[i] if i < len(prefs) else {}
            self.breaks.append(BreakConfig(
                name=break_prefs.get("name", default["name"]),
                interval_val=break_prefs.get("interval_val", default["interval_val"]),
                interval_unit=break_prefs.get("interval_unit", default["interval_unit"]),
                duration_val=break_prefs.get("duration_val", default["duration_val"]),
                duration_unit=break_prefs.get("duration_unit", default["duration_unit"]),
                start_sound=break_prefs.get("start_sound", default["start_sound"]),
                end_sound=break_prefs.get("end_sound", default["end_sound"]),
                loop_end_sound=break_prefs.get("loop_end_sound", default["loop_end_sound"]),
                auto_dismiss=break_prefs.get("auto_dismiss", default["auto_dismiss"]),
                snoozable=break_prefs.get("snoozable", default["snoozable"])
            ))

        self._build_ui()
        self._fit_window_to_content()
        self._setup_auto_save()
        self._restore_session()      # resume timers/snoozes if the last exit was an involuntary, recent one
        self._session_save_tick()    # begin the periodic snapshot heartbeat
        self._schedule_update_check(force=True)   # check on every launch/reload

        # Save window geometry on close
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Bring popup to user when main window is focused
        root.bind("<FocusIn>", self._on_main_focus)

    def _build_ui(self):
        # Main container
        main_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=PADDING_WINDOW, pady=PADDING_WINDOW)

        # ---- Status hero (the cockpit) ----
        # A subtle border marks the hero as the primary instrument (rows are borderless).
        hero = ctk.CTkFrame(main_frame, fg_color=COLORS['surface_card'],
                            corner_radius=CORNER_RADIUS_PANEL,
                            border_width=1, border_color=COLORS['border'])
        hero.pack(fill="x", pady=(0, SPACE_XS))

        hero_top = ctk.CTkFrame(hero, fg_color="transparent")
        # Small right padding: far right, but clear of the hero card's 1px border.
        hero_top.pack(fill="x", padx=(HERO_PAD, SPACE_XXS), pady=(HERO_PAD, SPACE_XS))

        # Breathing status dot (centered in a fixed-size wrap for baseline align)
        dot_wrap = ctk.CTkFrame(hero_top, fg_color="transparent",
                                width=DOT_SIZE, height=DOT_SIZE)
        dot_wrap.pack(side="left", pady=(STATUS_DOT_NUDGE_Y, 0))
        dot_wrap.pack_propagate(False)
        self.status_dot = ctk.CTkFrame(
            dot_wrap, width=DOT_SIZE, height=DOT_SIZE,
            corner_radius=DOT_SIZE // 2, fg_color=STATUS_DOT_COLORS['idle'])
        self.status_dot.pack(expand=True)

        self.status = ctk.CTkLabel(
            hero_top, text="Idle", font=make_font('label', weight="bold"),
            text_color=COLORS['text_secondary'])
        self.status.pack(side="left", padx=(SPACE_XS, 0))

        # Settings gear (top-right of the hero)
        self.settings_btn = ctk.CTkButton(
            hero_top, text="", image=load_icon('gear', size=18),
            command=self._open_settings,
            width=18, height=28, corner_radius=CORNER_RADIUS_INPUT,
            fg_color="transparent", hover_color=COLORS['surface_hover'])
        self.settings_btn.pack(side="right")

        # Headline (the one number that matters) + subtext
        # One consistent headline size across states (no resizing between
        # on-track/paused/idle); fixed-height slot keeps the window stable.
        self.hero_headline = ctk.CTkLabel(
            hero, text="Idle", anchor="w",
            font=make_font('status_hero', weight="bold"),
            height=HERO_HEADLINE_HEIGHT)
        self.hero_headline.pack(fill="x", padx=HERO_PAD)

        self.hero_sub = ctk.CTkLabel(
            hero, text="Start when you're ready", anchor="w",
            font=make_font('caption'), text_color=COLORS['text_secondary'])
        self.hero_sub.pack(fill="x", padx=HERO_PAD, pady=(SPACE_XXS, SPACE_SM))

        # Progress toward the next break
        self.hero_progress = ctk.CTkProgressBar(
            hero, height=PROGRESS_HEIGHT, corner_radius=PROGRESS_HEIGHT // 2,
            progress_color=COLORS['accent_primary'], fg_color=COLORS['surface_hover'])
        self.hero_progress.set(0)
        self.hero_progress.pack(fill="x", padx=HERO_PAD)

        # Holding chip \u2014 revealed by _render_status only while a break is deferred
        self.hero_chip = ctk.CTkLabel(
            hero, text="", anchor="w", font=make_font('caption', weight="bold"),
            text_color=COLORS['accent_warning'])

        # Global controls
        controls = ctk.CTkFrame(hero, fg_color="transparent")
        controls.pack(fill="x", padx=HERO_PAD, pady=(SPACE_SM, HERO_PAD))

        self.toggle_btn = ctk.CTkButton(
            controls, text="Start", command=self._handle_toggle,
            height=BUTTON_HEIGHT_LARGE, corner_radius=CORNER_RADIUS_BUTTON,
            fg_color=COLORS['accent_primary'], hover_color=COLORS['accent_primary_hover'],
            font=make_font('subheading', weight="bold"))
        self.toggle_btn.pack(side="left", padx=(0, SPACE_XXS), expand=True, fill="x")

        # Secondary to the primary Start/Pause. Its enabled vs disabled look is
        # driven by reset_button_style() so the affordance visibly changes with
        # state instead of reading "always grey" (#70).
        self.reset_btn = ctk.CTkButton(
            controls, text="Reset", command=self.reset,
            height=BUTTON_HEIGHT_LARGE, corner_radius=CORNER_RADIUS_BUTTON,
            font=make_font('subheading'))
        self._set_reset_enabled(False)   # idle → nothing to reset yet
        self.reset_btn.pack(side="left", padx=(SPACE_XXS, 0), expand=True, fill="x")

        # ---- Break rows: icon · name/interval · countdown/Break now ----
        self._timer_labels = []
        self._reschedule = None   # active reschedule popover state, or None
        self._cue_labels = []
        self._interval_labels = []
        self._tip_lbl = None    # shared hover-hint label
        self._tip_after = None  # pending show timer
        self._tip_fade = None   # pending fade frame
        self._tip_watch = None  # pointer watchdog (hides even if <Leave> never fires)
        self._tip_target = None  # widget the hint is tracking (authoritative)
        self._tip_miss = 0       # consecutive off-target polls (edge-jitter hysteresis)
        for i, config in enumerate(self.breaks):
            card = ctk.CTkFrame(main_frame, corner_radius=CORNER_RADIUS_PANEL,
                                fg_color=COLORS['surface_card'])
            card.pack(fill="x", pady=(0, SPACE_XS))

            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=PADDING_PANEL_X, pady=SPACE_SM)

            # Icon chip (left)
            icon_name = ROW_ICON_NAMES[i] if i < len(ROW_ICON_NAMES) else "timer"
            icon_chip = ctk.CTkLabel(
                row, text="", image=load_icon(icon_name),
                width=ICON_CHIP, height=ICON_CHIP, corner_radius=CORNER_RADIUS_INPUT,
                fg_color=TILE_CHIP_COLORS.get(icon_name, COLORS['surface_hover']))
            icon_chip.pack(side="left")

            # Right cluster: countdown is the rightmost value. The action pair — Break-now
            # (▶, primary, leads) then Skip (⏭) — hugs together and sits a clear gap to the
            # LEFT of the time, so actions and value read as two distinct groups (#5).
            timer_label = ctk.CTkLabel(row, text="--:--", font=make_font('row_countdown'), anchor="e")
            timer_label.pack(side="right")
            # Tap the countdown to reschedule this cycle sooner/later (one-time).
            timer_label.configure(cursor="pointinghand")
            timer_label.bind("<Button-1>",
                             lambda e, c=config, w=timer_label: self._open_reschedule(c, w))
            self._register_tooltip(timer_label, "Reschedule next break")
            play_btn = ctk.CTkButton(
                row, text="", image=load_icon('play', size=PLAY_GLYPH_SIZE),
                command=lambda c=config: self.break_now(c), anchor="e",
                width=PLAY_BTN_WIDTH, height=26, corner_radius=CORNER_RADIUS_INPUT,
                fg_color="transparent", hover_color=COLORS['surface_hover'])
            skip_btn = ctk.CTkButton(
                row, text="", image=load_icon('skip', size=PLAY_GLYPH_SIZE),
                command=lambda c=config: self.skip_break(c), anchor="e",
                width=PLAY_BTN_WIDTH, height=26, corner_radius=CORNER_RADIUS_INPUT,
                fg_color="transparent", hover_color=COLORS['surface_hover'])
            skip_btn.pack(side="right", padx=(0, SPACE_LG))   # ⏭ nearest the time, clear gap before it
            play_btn.pack(side="right", padx=(0, 0))          # ▶ leads, hugging ⏭
            self._register_tooltip(play_btn, "Break now")
            self._register_tooltip(skip_btn, "Skip this one")

            # Meta (middle): name + interval subtitle
            meta = ctk.CTkFrame(row, fg_color="transparent")
            meta.pack(side="left", fill="x", expand=True, padx=(SPACE_SM, SPACE_XS))
            # Tight title+subtitle pair: size each line to its font (not CTk's
            # default 28px box, which left a big gap and inflated the whole row).
            title_font = make_font('body', weight="bold")
            name_label = ctk.CTkLabel(
                meta, text=config.name.get(), anchor="w", font=title_font,
                height=title_font.metrics('linespace') + ROW_META_LINE_PAD)
            name_label.pack(fill="x")
            sub_font = make_font('caption')
            interval_label = ctk.CTkLabel(
                meta, text=self._row_subtitle(config), anchor="w", font=sub_font,
                height=sub_font.metrics('linespace') + ROW_META_LINE_PAD,
                text_color=COLORS['text_secondary'])
            interval_label.pack(fill="x", pady=(ROW_META_LINE_GAP, 0))

            self._timer_labels.append(timer_label)
            self._interval_labels.append(interval_label)

            # Gentle "holding" cue (#44): explains why a due break is waiting.
            cue_label = ctk.CTkLabel(
                card, text="", anchor="w",
                text_color=COLORS['text_secondary'], font=make_font('caption'))
            self._cue_labels.append(cue_label)

            # Double-click a row → configure this break (#43). The countdown is
            # excluded — it's a single-click reschedule target instead.
            for widget in (card, row, meta, name_label, interval_label):
                widget.bind("<Double-Button-1>",
                            lambda e, c=config: self._edit_break_config(c))

        # Snoozed-break section (dynamic rows appear while a snooze is pending).
        # height=0 so the empty container doesn't reserve CTkFrame's default 200px
        # (the old main-window "void"); it grows to fit snooze rows when present.
        self._snoozed_container = ctk.CTkFrame(main_frame, fg_color="transparent", height=0)
        self._snoozed_container.pack(fill="x")
        self._snooze_header = ctk.CTkLabel(
            self._snoozed_container, text="Snoozed",
            font=make_font('caption'),
            text_color=COLORS['text_secondary'])
        # header + rows packed/cleared by _render_snooze_rows

        # Bottom bar: feedback + update banner
        bottom_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        bottom_frame.pack(fill="x", side="bottom")

        self.update_label = ctk.CTkButton(
            bottom_frame,
            text="",
            command=self._handle_update,
            width=0,
            height=22,
            corner_radius=6,
            fg_color="transparent",
            hover_color=COLORS['surface_hover'],
            text_color=COLORS['accent_success'],
            font=make_font('caption')
        )
        # Hidden by default, shown when update is available

        self.feedback_btn = ctk.CTkButton(
            bottom_frame,
            text="Feedback",
            command=self._open_feedback,
            width=65,
            height=22,
            corner_radius=CORNER_RADIUS_INPUT,
            fg_color="transparent",
            hover_color=COLORS['surface_hover'],
            text_color=COLORS['text_tertiary'],
            font=make_font('caption')
        )
        self.feedback_btn.pack(side="right")
        self._register_tooltip(self.feedback_btn,
                               "We'd love your feedback or feature requests")

        # The version doubles as "check for updates now": clicking forces a check
        # (bypassing the 24h interval); hovering shows the hint. Width is measured
        # from the text so the hover chip hugs it regardless of version length.
        version_font = make_font('caption')
        version_text = f"v{get_current_version()}"
        self.version_btn = ctk.CTkButton(
            bottom_frame, text=version_text, command=self._check_updates_now,
            width=version_font.measure(version_text) + 2 * SPACE_SM, height=22,
            corner_radius=CORNER_RADIUS_INPUT, fg_color="transparent",
            hover_color=COLORS['surface_hover'], text_color=COLORS['text_tertiary'],
            font=version_font)
        self.version_btn.pack(side="right", padx=(0, SPACE_XXS))
        self._register_tooltip(self.version_btn, "Check for updates")

        # On-demand "Check in": answer any configured question now (either trigger).
        # Modest bottom-bar text button, matching the Feedback/version affordances.
        check_in_font = make_font('caption')
        self.check_in_now_btn = ctk.CTkButton(
            bottom_frame, text=CHECK_IN_NOW_LABEL, command=self._open_check_in_now,
            width=check_in_font.measure(CHECK_IN_NOW_LABEL) + 2 * SPACE_SM,
            height=BUTTON_HEIGHT_BOTTOM_BAR, corner_radius=CORNER_RADIUS_INPUT,
            fg_color="transparent", hover_color=COLORS['surface_hover'],
            text_color=COLORS['text_tertiary'], font=check_in_font)
        self.check_in_now_btn.pack(side="left")
        self._register_tooltip(self.check_in_now_btn, CHECK_IN_NOW_TOOLTIP)

        # Bind keyboard shortcuts
        self.root.bind('<Command-s>', lambda e: self._handle_toggle())
        self.root.bind('<Command-comma>', lambda e: self._open_settings())
        self.root.bind('<Command-period>', lambda e: self.reset() if self.running else None)
        # Dismiss the reschedule popover on click-away / Escape (guarded no-op otherwise).
        self.root.bind("<Button-1>", self._reschedule_click_away, add="+")
        self.root.bind("<Escape>", lambda e: self._close_reschedule(), add="+")

        # Start UI update loop
        self.update_ui()

    def _fit_window_to_content(self):
        """Size the window to fit its content, then lock the size."""
        self.root.update_idletasks()
        w = self.root.winfo_reqwidth()
        h = self.root.winfo_reqheight()
        mode = self.main_window_placement.get()
        if mode == "active":
            # Center on the screen you're using (#67). Raw Tk `wm geometry` — CTk's
            # .geometry() mislocates cross-monitor +x+y (same reason as the popup).
            geo = main_window_geometry(w, h, mode, self._saved_position,
                                       self._capture_active_screen())
            self.root.tk.call("wm", "geometry", self.root, geo)
        else:   # "remembered" (default): restore the saved position, unchanged
            self.root.geometry(main_window_geometry(w, h, mode, self._saved_position, None))

    def _refit_window(self):
        """Re-grow/shrink the (otherwise size-locked) window to fit content when
        rows are added/removed (snooze rows, update banner). Toggles resizable so
        the geometry actually changes."""
        self.root.resizable(True, True)
        self._fit_window_to_content()
        self.root.resizable(False, False)

    # ------------------ PREFERENCES ------------------

    def _load_preferences(self):
        """Load preferences from config file."""
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, 'r') as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load preferences: {e}")
        return {}

    def _save_preferences(self, *args, include_geometry=False):
        """Save current preferences to config file."""
        prefs = {
            "breaks": [],
            "always_on_top": self.always_on_top.get(),
            "check_for_updates": self.check_for_updates.get(),
            "defer_during_meetings": self.defer_during_meetings.get(),
            "defer_during_fullscreen": self.defer_during_fullscreen.get(),
            "popup_placement": self.popup_placement.get(),
            "main_window_placement": self.main_window_placement.get(),
            "defer_while_active": self.defer_while_active.get(),
            "activity_pause_seconds": self.activity_pause_seconds.get(),
            "away_idle_seconds": self.away_idle_seconds.get(),
            "natural_break_seconds": self.natural_break_seconds.get(),
            "count_mouse_move": self.count_mouse_move.get(),
            "prompt_resume_when_back": self.prompt_resume_when_back.get(),
            "resume_prompt_samples": self.resume_prompt_samples.get(),
            "show_anticipated_defer": self.show_anticipated_defer.get(),
            "snooze_seconds": self.snooze_seconds.get(),
            "check_ins": {"enabled": self.check_ins_enabled.get(),
                          "questions": self.check_in_questions},
            "check_in_state": self.check_in_state,
            "last_update_check": self.saved_prefs.get("last_update_check", 0),
            "sections_expanded": self._sections_expanded,
        }
        for config in self.breaks:
            prefs["breaks"].append({
                "name": config.name.get(),
                "interval_val": BreakConfig._safe_int(config.interval_value),
                "interval_unit": config.interval_unit.get(),
                "duration_val": BreakConfig._safe_int(config.duration_value),
                "duration_unit": config.duration_unit.get(),
                "start_sound": config.start_sound.get(),
                "end_sound": config.end_sound.get(),
                "loop_end_sound": config.loop_end_sound.get(),
                "auto_dismiss": config.auto_dismiss.get(),
                "snoozable": config.snoozable.get()
            })
        if include_geometry:
            prefs["window_geometry"] = self.root.geometry()
        elif hasattr(self, 'saved_prefs') and "window_geometry" in self.saved_prefs:
            prefs["window_geometry"] = self.saved_prefs["window_geometry"]
        try:
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_FILE, 'w') as f:
                json.dump(prefs, f, indent=2)
        except IOError as e:
            print(f"Warning: Could not save preferences: {e}")

    def _save_session(self, resumable=True):
        """Persist the live runtime snapshot (atomic temp+replace) for crash/update
        resume. `resumable=False` on a purposeful quit so the next launch starts fresh."""
        try:
            snapshot = build_snapshot(
                saved_at=time.time(), resumable=resumable,
                running=self.running, paused=self.paused,
                breaks=[(c.name.get(), c.remaining) for c in self.breaks],
                snoozes=[{"name": e["name"], "fire_time": e["fire_time"],
                          "break_data": e["break_data"]} for e in self._pending_snoozes])
            SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = SESSION_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(snapshot))
            os.replace(tmp, SESSION_FILE)
        except Exception as e:
            logging.debug("session save failed: %s", e)

    def _session_save_tick(self):
        """Heartbeat: snapshot the live session, then reschedule."""
        self._save_session(resumable=True)
        self.root.after(SESSION_SAVE_INTERVAL_SECONDS * 1000, self._session_save_tick)

    def _restore_session(self):
        """If the last exit was involuntary (crash / future self-update) and recent,
        resume timers + snoozes exactly. A purposeful quit or a stale snapshot is ignored
        (fresh). Never resets timers / clears snoozes / logs SESSION_STARTED (that's Start)."""
        try:
            raw = json.loads(SESSION_FILE.read_text()) if SESSION_FILE.exists() else None
        except Exception:
            raw = None
        snapshot = parse_snapshot(raw)
        now = time.time()
        if not should_resume(snapshot, now, SESSION_RESUME_WINDOW_SECONDS):
            return

        remaining = remaining_by_name(snapshot, [c.name.get() for c in self.breaks])
        for config in self.breaks:
            if config.name.get() in remaining:
                config.remaining = remaining[config.name.get()]

        for s in snoozes_to_restore(snapshot, now):
            entry = {"name": s["name"], "break_data": s["break_data"],
                     "fire_time": s["fire_time"], "after_id": None}
            entry["after_id"] = self.root.after(
                max(0, int(s["remaining"] * 1000)),
                lambda bd=s["break_data"], e=entry: self._requeue_break(bd, e))
            self._pending_snoozes.append(entry)
        self._render_snooze_rows(now)
        self._record_event(SESSION_RESUMED, running=snapshot["running"],
                           resumed_breaks=len(remaining),
                           resumed_snoozes=len(self._pending_snoozes))

        if snapshot["running"]:
            self.running = True
            self.paused = False
            self.stop_event.clear()
            self._episode = None
            self._due_since = {}
            self._held = None
            self._reset_defer_grace()
            self._render_status()
            self.toggle_btn.configure(text="Pause", fg_color=COLORS['accent_warning'],
                                      hover_color=COLORS['accent_warning_hover'])
            self._set_reset_enabled(True)
            self._spin_timer_loop()
            if snapshot["paused"]:
                self.toggle_pause()   # flip to paused (Resume button + paused visual)

    def _on_close(self):
        """Handle window close."""
        self._save_preferences(include_geometry=True)
        self._save_session(resumable=False)   # purposeful quit -> next launch starts fresh
        self.root.destroy()

    # ------------------ UPDATE CHECKER ------------------

    def _should_check_for_updates(self, force=False):
        """Whether an update check is due now — delegates the decision to the pure,
        unit-tested updater.should_check_for_updates. `force` bypasses the interval."""
        last_check = self.saved_prefs.get("last_update_check", 0)
        hours_since = (time.time() - last_check) / 3600
        decision = should_check_for_updates(
            self.check_for_updates.get(), hours_since,
            UPDATE_CHECK_INTERVAL_HOURS, force)
        logging.debug("Update check due? pref=%s hours_since=%.1f force=%s -> %s",
                      self.check_for_updates.get(), hours_since, force, decision)
        return decision

    def _schedule_update_check(self, force=False):
        """Start a background update check. `force` bypasses the 24h interval so
        every launch/reload checks (subject only to the user's pref); the hourly
        re-schedule stays interval-gated for long-running sessions."""
        if self._should_check_for_updates(force=force):
            logging.debug("Starting background update check thread (force=%s)", force)
            thread = threading.Thread(target=self._check_for_updates_bg, daemon=True)
            thread.start()
        # Re-check eligibility every hour for long-running sessions
        self.root.after(3600 * 1000, self._schedule_update_check)

    def _check_for_updates_bg(self, manual=False):
        """Background thread: fetch latest version and notify UI. When `manual`
        (the user clicked the version number), also give explicit feedback if the
        app is already current or the check failed — an auto check stays silent."""
        try:
            result = fetch_latest_version()
            current_version = get_current_version()
            logging.debug(f"Update check: current={current_version}, latest={result}")
            # Update last check timestamp regardless of result
            self.saved_prefs["last_update_check"] = time.time()
            self.root.after(0, lambda: self._save_preferences())
            newer = False
            if result:
                latest_version, release_url = result
                newer = is_newer_version(latest_version, current_version)
                logging.debug(f"Is newer: {newer} ({latest_version} > {current_version})")
                if newer:
                    self.available_update = (latest_version, release_url)
                    self.root.after(0, lambda: self._show_update_banner(latest_version))
            if manual:
                if result is None:              # fetch failed (no network / API error)
                    self.root.after(0, self._show_update_check_failed)
                elif not newer:
                    self.root.after(0, self._show_up_to_date)
        except Exception as e:
            logging.error(f"Update check failed: {e}", exc_info=True)
            if manual:
                self.root.after(0, self._show_update_check_failed)

    def _show_update_banner(self, version):
        """Show the update available label in the main UI."""
        self.update_label.configure(text=f"v{version} available — Update")
        self.update_label.pack(side="left")
        self._refit_window()   # grow to fit the new banner label

    def _check_updates_now(self):
        """Manual check triggered by clicking the version number — bypasses the
        24h interval and gives explicit feedback for every outcome."""
        self.update_label.configure(text="Checking…", text_color=COLORS['text_tertiary'])
        self.update_label.pack(side="left", padx=(SPACE_SM, 0))
        threading.Thread(
            target=lambda: self._check_for_updates_bg(manual=True), daemon=True).start()

    def _show_up_to_date(self):
        """Transient 'already current' note (manual check found no newer release)."""
        self.update_label.configure(text="✓ Up to date",
                                    text_color=COLORS['accent_success'])
        self.update_label.pack(side="left", padx=(SPACE_SM, 0))
        self.root.after(UPDATE_TOAST_MS, self.update_label.pack_forget)

    def _show_update_check_failed(self):
        """Transient note when a manual check couldn't reach GitHub."""
        self.update_label.configure(text="Couldn't check — try later",
                                    text_color=COLORS['text_tertiary'])
        self.update_label.pack(side="left", padx=(SPACE_SM, 0))
        self.root.after(UPDATE_TOAST_MS, self.update_label.pack_forget)

    def _handle_update(self):
        """Handle click on the update banner."""
        if not self.available_update:
            return
        version, release_url = self.available_update

        if is_installed_via_homebrew():
            self._update_via_homebrew()
        else:
            webbrowser.open(release_url)

    def _update_via_homebrew(self):
        """Seamless Homebrew update: silently `brew upgrade`, then relaunch into the new
        version with timers restored. Falls back to the releases page when we can't do it
        safely (source run, brew missing, or no resolvable .app bundle)."""
        brew = find_brew()
        app_path = app_bundle_from_executable(sys.executable, getattr(sys, "frozen", False))
        if not brew or not app_path:
            webbrowser.open(self.available_update[1])   # manual fallback
            return
        self._show_updating()
        threading.Thread(target=self._run_brew_upgrade, args=(brew, app_path),
                         daemon=True).start()

    def _run_brew_upgrade(self, brew, app_path):
        """Background: brew upgrade, then confirm the installed cask version advanced."""
        target = self.available_update[0]
        ok = False
        try:
            # brew's local tap can lag, so `brew upgrade` alone reports "already installed"
            # on a stale tap (the version never advances). Refresh first — best-effort, so a
            # failed refresh still lets the upgrade run if the tap happens to be current.
            try:
                subprocess.run([brew, "update"], capture_output=True, text=True,
                               timeout=BREW_UPDATE_TIMEOUT_S)
            except Exception as e:
                logging.warning("brew update failed (continuing to upgrade): %s", e)
            up = subprocess.run([brew, "upgrade", "--cask", HOMEBREW_CASK_NAME],
                                capture_output=True, text=True,
                                timeout=BREW_UPGRADE_TIMEOUT_S)
            if up.returncode == 0:
                ver = subprocess.run(
                    [brew, "list", "--cask", "--versions", HOMEBREW_CASK_NAME],
                    capture_output=True, text=True, timeout=30)
                tokens = ver.stdout.split()
                installed = tokens[-1] if tokens else ""
                ok = bool(installed) and (installed == target
                                          or is_newer_version(installed, target))
        except Exception as e:
            logging.error("brew upgrade failed: %s", e)
        self.root.after(0, lambda: self._finish_brew_upgrade(ok, app_path))

    def _finish_brew_upgrade(self, ok, app_path):
        if ok:
            self._relaunch_after_update(app_path)
        else:
            self._update_failed()

    def _relaunch_after_update(self, app_path):
        """Save a resumable snapshot + prefs, spawn a detached relauncher, then hard-exit
        (os._exit skips _on_close, which would mark the snapshot non-resumable)."""
        self._record_event(APP_UPDATED, to_version=self.available_update[0])
        self._save_preferences(include_geometry=True)
        self._save_session(resumable=True)
        subprocess.Popen(relaunch_command(os.getpid(), app_path))
        os._exit(0)

    def _show_updating(self):
        """Banner → 'Updating…' (disabled) while the upgrade runs."""
        self.update_label.configure(text="Updating…", state="disabled",
                                    text_color=COLORS['text_tertiary'])

    def _update_failed(self):
        """Upgrade failed / didn't advance: revert to a clickable retry state."""
        self.update_label.configure(text="Update failed — try again", state="normal",
                                    text_color=COLORS['accent_warning'])

    def _on_main_focus(self, event=None):
        """When main window is focused, bring popup to user if active."""
        if self.active_popup and not self.active_popup.closed:
            self.active_popup.bring_to_user()

    def _open_feedback(self):
        """Open GitHub new issue page with pre-filled system info."""
        try:
            app_version = VERSION_FILE.read_text().strip()
        except (FileNotFoundError, IOError):
            app_version = "unknown"

        system_info = (
            f"**App version:** {app_version}\n"
            f"**OS:** {platform.system()} {platform.release()}\n"
            f"**Python:** {platform.python_version()}\n"
        )
        body = (
            f"{system_info}\n"
            "---\n\n"
            "## Description\n"
            "<!-- What happened? -->\n\n"
            "## Steps to reproduce\n"
            "<!-- How can we reproduce this? -->\n"
        )
        url = f"{GITHUB_NEW_ISSUE_URL}?body={url_quote(body)}"
        webbrowser.open(url)

    def _setup_auto_save(self):
        """Setup auto-save when any preference changes.

        Free-text entries (interval / duration) are debounced so a value typed
        digit-by-digit is only applied once the user stops typing — typing "10"
        never commits the interim "1" and fires a break (#47). Discrete controls
        (unit menus, sound menus, checkboxes) save immediately.
        """
        for config in self.breaks:
            config.interval_value.trace_add(
                'write', lambda *a, c=config: self._debounce(
                    ('interval', id(c)), lambda: self._commit_interval(c)))
            config.interval_unit.trace_add(
                'write', lambda *a, c=config: self._commit_interval(c))
            config.duration_value.trace_add(
                'write', lambda *a: self._debounce(('duration',), self._save_preferences))
            config.duration_unit.trace_add('write', self._save_preferences)
            config.start_sound.trace_add('write', self._save_preferences)
            config.end_sound.trace_add('write', self._save_preferences)
            config.loop_end_sound.trace_add('write', self._save_preferences)
            config.auto_dismiss.trace_add('write', self._save_preferences)
            config.snoozable.trace_add('write', self._save_preferences)

    def _debounce(self, key, callback):
        """Run `callback` once `CONFIG_COMMIT_DEBOUNCE_MS` passes with no newer
        call for the same `key` (a rapid burst of keystrokes commits once)."""
        pending = self._debounce_after.get(key)
        if pending is not None:
            self.root.after_cancel(pending)
        self._debounce_after[key] = self.root.after(
            CONFIG_COMMIT_DEBOUNCE_MS, lambda: self._run_debounced(key, callback))

    def _run_debounced(self, key, callback):
        self._debounce_after.pop(key, None)
        callback()

    def _commit_interval(self, config):
        """Apply a settled interval change — reset the countdown and save."""
        config.reset_timer()
        self._save_preferences()

    # ------------------ CONTROLS ------------------

    def start(self):
        if self.running:
            return
        self.running = True
        self.paused = False
        self.stop_event.clear()
        self._episode = None  # fresh idle/deferred dedup marker each session
        self._due_since = {}   # fresh deferred-duration tracking each session (#85)
        self._held = None      # reset the held-reason each session
        self._reset_defer_grace()  # reset fullscreen/mic/active hysteresis each session (#46/#84)

        # A fresh Start wipes stale pending state (#69): cancel any snoozes left
        # over from a previous session so they can't fire now, and log a session
        # boundary so snooze counts / "originally due" reset to this cycle.
        for entry in list(self._pending_snoozes):
            if entry.get("after_id") is not None:
                try:
                    self.root.after_cancel(entry["after_id"])
                except Exception:
                    pass
        self._pending_snoozes.clear()
        self._render_snooze_rows(time.time())
        self._record_event(SESSION_STARTED)

        for config in self.breaks:
            config.reset_timer()

        self._render_status()
        self.toggle_btn.configure(
            text="Pause",
            fg_color=COLORS['accent_warning'],
            hover_color=COLORS['accent_warning_hover']
        )
        self._set_reset_enabled(True)
        self._spin_timer_loop()

    def _spin_timer_loop(self):
        """Launch the per-tick timer thread for the current running session — shared by
        start() (fresh) and _restore_session() (resume). A new generation stops any
        left-over thread from a prior session."""
        self._timer_generation += 1
        threading.Thread(
            target=self.timer_loop, args=(self._timer_generation,), daemon=True
        ).start()

    def toggle_pause(self):
        if not self.running:
            return
        if self.paused:
            self.paused = False
            self._reset_resume_prompt()   # pause episode ended (#77)
            self.toggle_btn.configure(
                text="Pause",
                fg_color=COLORS['accent_warning'],
                hover_color=COLORS['accent_warning_hover']
            )
            self._render_status()
        else:
            self.paused = True
            self._reset_resume_prompt()   # fresh pause episode → eligible for one prompt (#77)
            self.toggle_btn.configure(
                text="Resume",
                fg_color=COLORS['accent_primary'],
                hover_color=COLORS['accent_primary_hover']
            )
            self._render_status()

    def reset(self):
        self.running = False
        self.paused = False
        self.stop_event.set()

        self.break_queue.clear()
        if self.active_popup:
            try:
                self.active_popup.close()
            except Exception:
                pass
            self.active_popup = None

        for config in self.breaks:
            config.reset_timer()

        self._render_status()
        self.toggle_btn.configure(
            text="Start",
            fg_color=COLORS['accent_primary'],
            hover_color=COLORS['accent_primary_hover']
        )
        self._set_reset_enabled(False)

    def _apply_always_on_top(self, *args):
        """Apply the always-on-top setting and save preferences."""
        self.root.attributes('-topmost', self.always_on_top.get())
        self._save_preferences()

    def _handle_toggle(self):
        """Unified Start/Pause toggle handler."""
        if not self.running:
            self.start()
        else:
            self.toggle_pause()

    def _edit_break_config(self, config):
        """Open settings focused on the given break (double-click a card)."""
        self._open_settings(focus_config=config)

    def _open_settings(self, focus_config=None):
        """Open the settings window, or bring it to front if already open.

        If focus_config is a BreakConfig, focus that break's settings panel
        (expanding it and landing keyboard focus in its interval field).
        """
        if hasattr(self, '_settings_window') and self._settings_window and self._settings_window.winfo_exists():
            self._settings_window.deiconify()
            self._settings_window.lift()
            self._settings_window.focus_force()
            self._focus_settings_panel(focus_config)
            return

        self._settings_window = ctk.CTkToplevel(self.root)
        self._settings_window.title("Break Settings")
        self._settings_window.resizable(False, True)
        self._settings_window.attributes('-topmost', self.always_on_top.get())
        self._settings_window.attributes('-alpha', SETTINGS_WINDOW_OPACITY)  # slight translucency
        # Build hidden, then size to content and show — avoids a flash at the
        # wrong size and guarantees added settings are never clipped.
        self._settings_window.withdraw()

        def on_settings_close():
            self._settings_window.withdraw()

        self._settings_window.protocol("WM_DELETE_WINDOW", on_settings_close)
        self._settings_window.bind('<Escape>', lambda e: on_settings_close())

        # Scrollable container so a fully-expanded settings window can scroll.
        container = ctk.CTkScrollableFrame(self._settings_window, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=PADDING_WINDOW, pady=PADDING_WINDOW)
        self._settings_container = container

        # Everything is a collapsible category (Breaks / Smart pausing / Break
        # popup / App); each remembers its own open/closed state (persisted).
        self._settings_sections = []

        def _add_section(key, title):
            section = CollapsibleSection(
                container, title,
                expanded=self._sections_expanded.get(key, SECTION_DEFAULT_EXPANDED[key]),
                on_toggle=lambda is_open, k=key: self._set_section_expanded(k, is_open),
                on_resize=self._resize_settings_to_content)
            section.pack(fill="x", pady=(ROW_SPACING, 0))
            self._settings_sections.append(section)
            return section

        # -- Breaks: each break is its own collapsible panel inside the category --
        self._breaks_section = _add_section("breaks", "Breaks")
        self._settings_panels = []
        for config in self.breaks:
            panel = BreakConfigPanel(self._breaks_section.body, config, self.test_break,
                                     on_resize=self._resize_settings_to_content)
            panel.pack(fill="x", pady=(0, ROW_SPACING))
            self._settings_panels.append(panel)
        self._breaks_section.finalize()

        def _checkbox(parent, text, variable):
            ctk.CTkCheckBox(parent, text=text, variable=variable,
                            font=make_font('label')).pack(
                padx=PADDING_PANEL_X, pady=(SPACE_XXS, SPACE_XXS), anchor="w")

        # -- Smart pausing --
        smart = _add_section("smart_pausing", "Smart pausing")
        _checkbox(smart.body, "Pause breaks while microphone is in use",
                  self.defer_during_meetings)
        _checkbox(smart.body, "Pause breaks during fullscreen",
                  self.defer_during_fullscreen)
        _checkbox(smart.body, "Wait until you pause (typing or clicking)",
                  self.defer_while_active)

        # Nested sub-block under "Wait until you pause": indent + left hairline.
        subwrap = ctk.CTkFrame(smart.body, fg_color="transparent")
        subwrap.pack(fill="x", anchor="w",
                     padx=(PADDING_PANEL_X + SETTINGS_SUBOPTION_INDENT, PADDING_PANEL_X),
                     pady=(0, PADDING_PANEL_Y))
        # height=1 + fill="y": a bare CTkFrame defaults to 200px tall (no children
        # to shrink it), which would inflate the sub-block; fill stretches it to
        # the actual content height instead.
        ctk.CTkFrame(subwrap, width=SETTINGS_SUBOPTION_RULE_W, height=1,
                     fg_color=COLORS['border']).pack(side="left", fill="y")
        subblock = ctk.CTkFrame(subwrap, fg_color="transparent")
        subblock.pack(side="left", fill="x", expand=True, padx=(SPACE_SM, 0))

        self._mouse_move_check = ctk.CTkCheckBox(
            subblock, text="also count mouse movement",
            variable=self.count_mouse_move, font=make_font('label'))
        self._mouse_move_check.pack(pady=(0, SPACE_XXS), anchor="w")

        pause_row = ctk.CTkFrame(subblock, fg_color="transparent")
        pause_row.pack(anchor="w", fill="x")
        self._pause_value_label = ctk.CTkLabel(
            pause_row, text=f"Pause length: {self.activity_pause_seconds.get()} sec",
            font=make_font('label'))
        self._pause_value_label.pack(side="left")

        def _on_pause(value):
            secs = int(round(value))
            self.activity_pause_seconds.set(secs)
            self._pause_value_label.configure(text=f"Pause length: {secs} sec")

        self._pause_slider = ctk.CTkSlider(
            pause_row, from_=ACTIVITY_PAUSE_MIN, to=ACTIVITY_PAUSE_MAX,
            number_of_steps=ACTIVITY_PAUSE_MAX - ACTIVITY_PAUSE_MIN, command=_on_pause)
        self._pause_slider.set(self.activity_pause_seconds.get())
        self._pause_slider.pack(side="right")

        # Away & rest timing — always-on lines (independent of wait-until-you-pause).
        ctk.CTkLabel(smart.body, text="Away & rest timing", font=make_font('caption'),
                     text_color=COLORS['text_tertiary']).pack(
            anchor="w", padx=PADDING_PANEL_X, pady=(SPACE_SM, SPACE_XXS))
        timing = ctk.CTkFrame(smart.body, fg_color="transparent")
        timing.pack(fill="x", anchor="w", padx=PADDING_PANEL_X, pady=(0, PADDING_PANEL_Y))
        self._build_timing_slider(
            timing, self.away_idle_seconds,
            lambda v: f"Consider you away after: {v} sec",
            AWAY_IDLE_MIN_SECONDS, AWAY_IDLE_MAX_SECONDS, AWAY_IDLE_STEP_SECONDS)
        self._build_timing_slider(
            timing, self.natural_break_seconds,
            lambda v: f"Count as a rest after: {v // 60} min",
            NATURAL_BREAK_MIN_SECONDS, NATURAL_BREAK_MAX_SECONDS, NATURAL_BREAK_STEP_SECONDS)

        _checkbox(smart.body, "Show “your break will wait” while in a call / full screen",
                  self.show_anticipated_defer)

        # Resume prompt while paused (#77): toggle + adjustable sensitivity.
        _checkbox(smart.body, "When paused, offer to resume when you return",
                  self.prompt_resume_when_back)
        resume_timing = ctk.CTkFrame(smart.body, fg_color="transparent")
        resume_timing.pack(fill="x", anchor="w", padx=PADDING_PANEL_X, pady=(0, PADDING_PANEL_Y))
        self._build_timing_slider(
            resume_timing, self.resume_prompt_samples,
            lambda v: f"Prompt after you're back for: {v} sec",
            RESUME_PROMPT_MIN_SAMPLES, RESUME_PROMPT_MAX_SAMPLES, 1)
        smart.finalize()

        # Grey out the sub-options live when "Wait until you pause" is off.
        self._sync_activity_suboptions()
        self.defer_while_active.trace_add(
            'write', lambda *a: self._sync_activity_suboptions())

        # -- Break popup --
        popup = _add_section("break_popup", "Break popup")
        placement_row = ctk.CTkFrame(popup.body, fg_color="transparent")
        placement_row.pack(padx=PADDING_PANEL_X, pady=(SPACE_XXS, PADDING_PANEL_Y),
                           anchor="w", fill="x")
        ctk.CTkLabel(placement_row, text="Appears on",
                     font=make_font('label')).pack(side="left")
        value_to_label = {v: k for k, v in POPUP_PLACEMENT_LABELS.items()}

        def _on_placement(label):
            self.popup_placement.set(POPUP_PLACEMENT_LABELS[label])

        placement_menu = ctk.CTkOptionMenu(
            placement_row, values=list(POPUP_PLACEMENT_LABELS.keys()),
            command=_on_placement, font=make_font('label'))
        placement_menu.set(value_to_label.get(self.popup_placement.get(), "Active screen"))
        placement_menu.pack(side="right")
        popup.finalize()

        # -- App --
        appsec = _add_section("app", "App")
        _checkbox(appsec.body, "Always on top", self.always_on_top)
        _checkbox(appsec.body, "Check for updates automatically", self.check_for_updates)

        # Main-window placement on launch (#67): remember position vs center on the
        # current screen (multi-monitor). Mirrors the break-popup "Appears on" row.
        mw_row = ctk.CTkFrame(appsec.body, fg_color="transparent")
        mw_row.pack(padx=PADDING_PANEL_X, pady=(SPACE_XXS, PADDING_PANEL_Y),
                    anchor="w", fill="x")
        ctk.CTkLabel(mw_row, text="Main window",
                     font=make_font('label')).pack(side="left")
        mw_value_to_label = {v: k for k, v in MAIN_WINDOW_PLACEMENT_LABELS.items()}

        def _on_main_placement(label):
            self.main_window_placement.set(MAIN_WINDOW_PLACEMENT_LABELS[label])

        mw_menu = ctk.CTkOptionMenu(
            mw_row, values=list(MAIN_WINDOW_PLACEMENT_LABELS.keys()),
            command=_on_main_placement, font=make_font('label'))
        mw_menu.set(mw_value_to_label.get(self.main_window_placement.get(),
                                          "Remember last position"))
        mw_menu.pack(side="right")
        appsec.finalize()

        # -- Check-ins: master toggle + one card per configurable question --
        cisec = _add_section("check_ins", CHECK_IN_SECTION_TITLE)
        _checkbox(cisec.body, CHECK_IN_ENABLE_LABEL, self.check_ins_enabled)
        self._check_in_cards_frame = ctk.CTkFrame(cisec.body, fg_color="transparent")
        self._check_in_cards_frame.pack(fill="x")
        self._render_check_in_cards()
        ctk.CTkButton(
            cisec.body, text=CHECK_IN_ADD_LABEL, command=self._add_check_in_question,
            height=BUTTON_HEIGHT_SMALL, corner_radius=CORNER_RADIUS_BUTTON,
            fg_color="transparent", border_width=1, border_color=COLORS['border'],
            hover_color=COLORS['surface_hover'], text_color=COLORS['text_secondary'],
            font=make_font('label')).pack(
                anchor="w", padx=PADDING_PANEL_X, pady=(SPACE_XS, PADDING_PANEL_Y))
        cisec.finalize()

        # Trackpad/wheel scrolling over the whole content (not just the scrollbar).
        self._enable_trackpad_scroll(container)

        # Size the window to its content (screen-relative min/max); beyond the
        # cap the container scrolls. Placed centered over the main window, then
        # clamped fully on-screen.
        self._settings_window.update_idletasks()
        content_height = self._settings_content_height()
        height = self._settings_target_height(content_height)
        self._show_settings_scrollbar(content_height > height)
        main_x = self.root.winfo_x()
        main_w = self.root.winfo_width()
        x = main_x + (main_w - SETTINGS_WINDOW_WIDTH) // 2
        y = max(0, min(self.root.winfo_y() - SETTINGS_WINDOW_Y_OFFSET,
                       self._settings_window.winfo_screenheight() - height))
        self._settings_window.geometry(f"{SETTINGS_WINDOW_WIDTH}x{height}+{x}+{y}")
        self._settings_window.deiconify()
        self._settings_window.lift()
        self._settings_window.focus_force()
        self._focus_settings_panel(focus_config)

    def _focus_settings_panel(self, config):
        """Focus the settings panel that edits the given break (by identity)."""
        if config is None:
            return
        breaks = getattr(self, '_breaks_section', None)
        if breaks is not None and not breaks.is_expanded():
            breaks.expand(animate=False)   # the break panels live inside this category
            self._resize_settings_to_content()
        for panel in self._settings_panels:
            if panel.config is config:
                panel.focus_config()
                break

    # ------------------ CHECK-INS SETTINGS ------------------

    def _render_check_in_cards(self):
        """Clear + rebuild the per-question card list so add/edit/delete refresh
        live. Safe to call whenever `self.check_in_questions` changes."""
        frame = getattr(self, '_check_in_cards_frame', None)
        if frame is None or not frame.winfo_exists():
            return
        for child in frame.winfo_children():
            child.destroy()
        for question in self.check_in_questions:
            self._build_check_in_card(frame, question)

    def _build_check_in_card(self, parent, question):
        """One card: enable toggle + question text + summary + Edit/Delete."""
        card = ctk.CTkFrame(
            parent, corner_radius=CORNER_RADIUS_PANEL, fg_color=COLORS['surface_card'],
            border_width=CHECK_IN_CARD_BORDER_WIDTH, border_color=COLORS['border'])
        card.pack(fill="x", padx=PADDING_PANEL_X, pady=(0, ROW_SPACING))

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=PADDING_PANEL_X, pady=(PADDING_PANEL_Y // 2, 0))

        enabled_var = ctk.BooleanVar(value=bool(question.get("enabled", True)))

        def _on_toggle(*_a, q=question, var=enabled_var):
            q["enabled"] = var.get()
            self._save_preferences()

        enabled_var.trace_add('write', _on_toggle)
        ctk.CTkCheckBox(top, text="", width=CHECK_IN_TOGGLE_WIDTH,
                        variable=enabled_var).pack(side="left")

        ctk.CTkButton(
            top, text=CHECK_IN_DELETE_LABEL, width=CHECK_IN_ACTION_BTN_WIDTH,
            height=BUTTON_HEIGHT_SMALL, corner_radius=CORNER_RADIUS_INPUT,
            fg_color="transparent", border_width=1, border_color=COLORS['border'],
            hover_color=COLORS['surface_hover'], text_color=COLORS['text_secondary'],
            font=make_font('label'),
            command=lambda q=question: self._delete_check_in_question(q)).pack(
                side="right", padx=(SPACE_XS, 0))
        ctk.CTkButton(
            top, text=CHECK_IN_EDIT_LABEL, width=CHECK_IN_ACTION_BTN_WIDTH,
            height=BUTTON_HEIGHT_SMALL, corner_radius=CORNER_RADIUS_INPUT,
            fg_color="transparent", border_width=1, border_color=COLORS['border'],
            hover_color=COLORS['surface_hover'], text_color=COLORS['text_secondary'],
            font=make_font('label'),
            command=lambda q=question: self._edit_check_in_question(q)).pack(side="right")

        ctk.CTkLabel(
            top, text=question.get("text", ""), font=make_font('body', weight="bold"),
            text_color=COLORS['text_primary'],
            anchor="w", justify="left", wraplength=CHECK_IN_CARD_TEXT_WRAP).pack(
                side="left", padx=(SPACE_XS, SPACE_SM), fill="x", expand=True)

        ctk.CTkLabel(
            card, text=check_in_summary(question), font=make_font('caption'),
            text_color=COLORS['text_secondary'], anchor="w", justify="left").pack(
                anchor="w", padx=(PADDING_PANEL_X + CHECK_IN_SUMMARY_INDENT, PADDING_PANEL_X),
                pady=(0, PADDING_PANEL_Y // 2))

    def _refresh_check_in_section(self):
        """Persist, rebuild the cards, and resize the settings window to fit."""
        self._save_preferences()
        self._render_check_in_cards()
        self._resize_settings_to_content()

    def _add_check_in_question(self):
        """Append a blank question (unique stable id) and open its edit form."""
        question = {
            "id": self._unique_check_in_id(CHECK_IN_NEW_QUESTION_TEXT),
            "text": CHECK_IN_NEW_QUESTION_TEXT, "enabled": True,
            "answer": {"type": SCALE, "min": DEFAULT_SCALE_MIN, "max": DEFAULT_SCALE_MAX,
                       "min_label": "", "max_label": "", "allow_note": True},
            "cadence": {"type": TIMES_PER_DAY, "count": 1},
            "trigger": TRIGGER_BREAK,
        }
        self.check_in_questions.append(question)
        self._refresh_check_in_section()
        self._edit_check_in_question(question)   # let the user name it right away

    def _delete_check_in_question(self, question):
        """Remove a question (by identity, so duplicate-valued dicts are safe)."""
        self.check_in_questions[:] = [
            q for q in self.check_in_questions if q is not question]
        self._refresh_check_in_section()

    def _unique_check_in_id(self, text):
        """A stable slug id from `text`, disambiguated so it never collides."""
        existing = {q.get("id") for q in self.check_in_questions}
        base = _slugify_check_in(text) or CHECK_IN_ID_FALLBACK
        candidate, n = base, 2
        while candidate in existing:
            candidate = f"{base}{CHECK_IN_ID_SEP}{n}"
            n += 1
        return candidate

    def _edit_check_in_question(self, question):
        """Modal form editing one question in place: text, answer type + type-specific
        fields (scale range/labels, choices options, note), and cadence + count."""
        answer = question.get("answer") or {}
        cadence = question.get("cadence") or {}
        type_by_label = {v: k for k, v in CHECK_IN_ANSWER_TYPE_LABELS.items()}
        cadence_by_label = {v: k for k, v in CHECK_IN_CADENCE_LABELS.items()}
        trigger_by_label = {v: k for k, v in CHECK_IN_TRIGGER_LABELS.items()}
        repeat_label_by_value = {v: k for k, v in CHECK_IN_REPEAT_LABELS.items()}

        modal = ctk.CTkToplevel(self.root)
        modal.title(CHECK_IN_EDIT_TITLE)
        modal.resizable(False, False)
        modal.configure(fg_color=COLORS['surface_card'])
        pin_to_active_space(modal)
        modal.transient(self._settings_window)
        body = ctk.CTkFrame(modal, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=PADDING_PANEL_X, pady=PADDING_PANEL_Y)

        def _caption(text):
            ctk.CTkLabel(body, text=text, font=make_font('label'),
                         text_color=COLORS['text_secondary']).pack(
                             anchor="w", pady=(SPACE_SM, SPACE_XXS))

        # Question text
        _caption(CHECK_IN_EDIT_TEXT_LABEL)
        text_entry = ctk.CTkEntry(body, width=CHECK_IN_EDIT_TEXT_WIDTH,
                                  font=make_font('body'), corner_radius=CORNER_RADIUS_INPUT)
        text_entry.insert(0, question.get("text", ""))
        text_entry.pack(fill="x")

        # Answer type
        _caption(CHECK_IN_EDIT_TYPE_LABEL)
        type_var = ctk.StringVar(value=CHECK_IN_ANSWER_TYPE_LABELS.get(
            answer.get("type"), CHECK_IN_ANSWER_TYPE_LABELS[SCALE]))
        type_fields = ctk.CTkFrame(body, fg_color="transparent")
        widgets = {}

        def _on_type_change(label):
            self._build_check_in_type_fields(type_fields, type_by_label[label],
                                             answer, widgets)
            self._place_check_in_modal(modal)

        ctk.CTkOptionMenu(
            body, values=list(CHECK_IN_ANSWER_TYPE_LABELS.values()), variable=type_var,
            command=_on_type_change, font=make_font('body'),
            corner_radius=CORNER_RADIUS_INPUT).pack(anchor="w")
        type_fields.pack(fill="x")
        self._build_check_in_type_fields(
            type_fields, type_by_label[type_var.get()], answer, widgets)

        # Cadence + count
        _caption(CHECK_IN_EDIT_CADENCE_LABEL)
        cadence_row = ctk.CTkFrame(body, fg_color="transparent")
        cadence_row.pack(fill="x")
        cadence_var = ctk.StringVar(value=CHECK_IN_CADENCE_LABELS.get(
            cadence.get("type"), CHECK_IN_CADENCE_LABELS[TIMES_PER_DAY]))
        ctk.CTkOptionMenu(
            cadence_row, values=list(CHECK_IN_CADENCE_LABELS.values()),
            variable=cadence_var, font=make_font('body'),
            corner_radius=CORNER_RADIUS_INPUT).pack(side="left")
        ctk.CTkLabel(cadence_row, text=CHECK_IN_EDIT_COUNT_LABEL,
                     font=make_font('label')).pack(side="left", padx=(SPACE_MD, SPACE_XS))
        count_entry = ctk.CTkEntry(cadence_row, width=CHECK_IN_EDIT_INT_WIDTH,
                                   font=make_font('body'), corner_radius=CORNER_RADIUS_INPUT)
        count_entry.insert(0, str(_ci_int(cadence.get("count", 1), 1)))
        count_entry.pack(side="left")

        # When: a break-coupled question is offered after a break (cadence-gated);
        # an on-demand one only surfaces via the "Check in" button.
        _caption(CHECK_IN_EDIT_TRIGGER_LABEL)
        trigger_var = ctk.StringVar(value=CHECK_IN_TRIGGER_LABELS.get(
            question.get("trigger"), CHECK_IN_TRIGGER_LABELS[TRIGGER_BREAK]))
        ctk.CTkOptionMenu(
            body, values=list(CHECK_IN_TRIGGER_LABELS.values()), variable=trigger_var,
            font=make_font('body'), corner_radius=CORNER_RADIUS_INPUT).pack(anchor="w")

        # Repeat: a once-a-day question, once answered today, isn't offered again after
        # later breaks; a few-times-a-day one can recur (still cadence-gated).
        _caption(CHECK_IN_EDIT_REPEAT_LABEL)
        repeat_var = ctk.StringVar(
            value=repeat_label_by_value[bool(question.get("once_per_day", False))])
        ctk.CTkOptionMenu(
            body, values=list(CHECK_IN_REPEAT_LABELS), variable=repeat_var,
            font=make_font('body'), corner_radius=CORNER_RADIUS_INPUT).pack(anchor="w")

        def _close():
            modal.destroy()

        def _save():
            atype = type_by_label[type_var.get()]
            new_answer = {"type": atype}
            if atype == SCALE:
                low = _ci_int(widgets['min'].get(), DEFAULT_SCALE_MIN)
                high = _ci_int(widgets['max'].get(), DEFAULT_SCALE_MAX)
                if high < low:
                    low, high = high, low
                new_answer.update(
                    min=low, max=high,
                    min_label=widgets['min_label'].get().strip(),
                    max_label=widgets['max_label'].get().strip(),
                    allow_note=bool(widgets['allow_note'].get()))
            elif atype == CHOICES:
                options = _parse_options_text(widgets['options'].get("1.0", "end"))
                new_answer.update(
                    options=options or list(CHECK_IN_DEFAULT_CHOICES),
                    allow_note=bool(widgets['allow_note'].get()))
            else:                                    # NOTE: the free text IS the answer
                new_answer.update(allow_note=True)
            question["text"] = text_entry.get().strip() or CHECK_IN_NEW_QUESTION_TEXT
            question["answer"] = new_answer
            question["cadence"] = {"type": cadence_by_label[cadence_var.get()],
                                   "count": max(1, _ci_int(count_entry.get(), 1))}
            question["trigger"] = trigger_by_label[trigger_var.get()]
            question["once_per_day"] = CHECK_IN_REPEAT_LABELS[repeat_var.get()]
            _close()
            self._refresh_check_in_section()

        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.pack(fill="x", pady=(PADDING_PANEL_Y, 0))
        ctk.CTkButton(
            buttons, text=CHECK_IN_EDIT_SAVE_LABEL, command=_save,
            height=BUTTON_HEIGHT_SMALL, corner_radius=CORNER_RADIUS_BUTTON,
            fg_color=COLORS['accent_primary'], hover_color=COLORS['accent_primary_hover'],
            font=make_font('label', weight="bold")).pack(
                side="right", padx=(SPACE_XS, 0))
        ctk.CTkButton(
            buttons, text=CHECK_IN_EDIT_CANCEL_LABEL, command=_close,
            height=BUTTON_HEIGHT_SMALL, corner_radius=CORNER_RADIUS_BUTTON,
            fg_color="transparent", border_width=1, border_color=COLORS['border'],
            hover_color=COLORS['surface_hover'], text_color=COLORS['text_secondary'],
            font=make_font('label')).pack(side="right")

        modal.protocol("WM_DELETE_WINDOW", _close)
        # Topmost so it doesn't hide behind the settings window; NO grab_set — an
        # app-modal grab orphans on macOS after close and locks the settings window
        # (the popup "appears then can't reopen"). See the chooser for the same fix.
        modal.attributes('-topmost', True)
        self._place_check_in_modal(modal)
        modal.lift()
        modal.focus_force()

    def _build_check_in_type_fields(self, container, atype, answer, widgets):
        """(Re)build the answer-type-specific fields inside the edit modal. Prefills
        from `answer` when it matches the type, else uses sensible defaults."""
        for child in container.winfo_children():
            child.destroy()
        widgets.clear()
        src = answer if answer.get("type") == atype else {}

        def _labeled_entry(parent, label, value, width):
            ctk.CTkLabel(parent, text=label, font=make_font('label')).pack(
                side="left", padx=(0, SPACE_XS))
            entry = ctk.CTkEntry(parent, width=width, font=make_font('body'),
                                 corner_radius=CORNER_RADIUS_INPUT)
            entry.insert(0, str(value))
            entry.pack(side="left", padx=(0, SPACE_MD))
            return entry

        if atype == SCALE:
            row = ctk.CTkFrame(container, fg_color="transparent")
            row.pack(fill="x", pady=(SPACE_XS, 0))
            widgets['min'] = _labeled_entry(
                row, CHECK_IN_EDIT_MIN_LABEL,
                src.get("min", DEFAULT_SCALE_MIN), CHECK_IN_EDIT_INT_WIDTH)
            widgets['max'] = _labeled_entry(
                row, CHECK_IN_EDIT_MAX_LABEL,
                src.get("max", DEFAULT_SCALE_MAX), CHECK_IN_EDIT_INT_WIDTH)
            labels_row = ctk.CTkFrame(container, fg_color="transparent")
            labels_row.pack(fill="x", pady=(SPACE_XS, 0))
            widgets['min_label'] = _labeled_entry(
                labels_row, CHECK_IN_EDIT_LOW_LABEL,
                src.get("min_label", ""), CHECK_IN_EDIT_LABEL_WIDTH)
            widgets['max_label'] = _labeled_entry(
                labels_row, CHECK_IN_EDIT_HIGH_LABEL,
                src.get("max_label", ""), CHECK_IN_EDIT_LABEL_WIDTH)
            self._build_check_in_allow_note(container, src, widgets)
        elif atype == CHOICES:
            ctk.CTkLabel(container, text=CHECK_IN_EDIT_OPTIONS_LABEL,
                         font=make_font('label')).pack(anchor="w", pady=(SPACE_XS, SPACE_XXS))
            box = ctk.CTkTextbox(container, width=CHECK_IN_EDIT_TEXT_WIDTH,
                                 height=CHECK_IN_EDIT_OPTIONS_HEIGHT, font=make_font('body'),
                                 corner_radius=CORNER_RADIUS_INPUT)
            box.insert("1.0", _options_to_text(src.get("options", CHECK_IN_DEFAULT_CHOICES)))
            box.pack(fill="x")
            widgets['options'] = box
            self._build_check_in_allow_note(container, src, widgets)
        else:                                        # NOTE
            ctk.CTkLabel(container, text=CHECK_IN_EDIT_NOTE_HINT, font=make_font('caption'),
                         text_color=COLORS['text_secondary']).pack(
                             anchor="w", pady=(SPACE_XS, 0))

    def _build_check_in_allow_note(self, container, src, widgets):
        """The 'allow an optional note' checkbox shared by scale/choices editors."""
        allow_note = ctk.BooleanVar(value=bool(src.get("allow_note", True)))
        ctk.CTkCheckBox(container, text=CHECK_IN_EDIT_ALLOW_NOTE_LABEL,
                        variable=allow_note, font=make_font('label')).pack(
                            anchor="w", pady=(SPACE_SM, 0))
        widgets['allow_note'] = allow_note

    def _place_check_in_modal(self, modal):
        """Center the edit modal over the settings window (re-run after it resizes)."""
        self._center_toplevel(modal, getattr(self, '_settings_window', None))

    def _center_toplevel(self, top, over):
        """Center a toplevel over the `over` window — or the screen when it's gone."""
        top.update_idletasks()
        w, h = top.winfo_reqwidth(), top.winfo_reqheight()
        if over is not None and over.winfo_exists():
            x = over.winfo_x() + (over.winfo_width() - w) // 2
            y = over.winfo_y() + (over.winfo_height() - h) // 2
        else:
            x = (top.winfo_screenwidth() - w) // 2
            y = (top.winfo_screenheight() - h) // 2
        top.tk.call("wm", "geometry", top, f"{w}x{h}+{int(x)}+{int(y)}")

    def _build_timing_slider(self, parent, var, label_fn, lo, hi, step):
        """A labeled slider row (label left, slider right) that writes `var` and
        updates its label live via label_fn(value). Mirrors the Pause-length control
        for the always-on away/rest lines."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(anchor="w", fill="x", pady=(SPACE_XS, 0))
        var.set(max(lo, min(hi, var.get())))   # heal an out-of-range stored value
        label = ctk.CTkLabel(row, text=label_fn(var.get()), font=make_font('label'))
        label.pack(side="left")

        def _on(value):
            v = int(round(value / step) * step)
            var.set(v)
            label.configure(text=label_fn(v))

        slider = ctk.CTkSlider(row, from_=lo, to=hi,
                               number_of_steps=(hi - lo) // step, command=_on)
        slider.set(var.get())
        slider.pack(side="right")

    def _sync_activity_suboptions(self, *args):
        """Enable/grey the 'wait until you pause' sub-options to match the parent."""
        on = self.defer_while_active.get()
        state = suboption_state(on)
        for widget in (self._mouse_move_check, self._pause_slider):
            if widget.winfo_exists():
                widget.configure(state=state)
        if self._pause_value_label.winfo_exists():
            normal = ctk.ThemeManager.theme["CTkLabel"]["text_color"]
            self._pause_value_label.configure(
                text_color=normal if on else COLORS['text_secondary'])

    def _set_section_expanded(self, key, is_open):
        """Remember a settings section's open/closed state across reopens/restarts."""
        self._sections_expanded[key] = is_open
        self._save_preferences()

    def _enable_trackpad_scroll(self, scroll_frame):
        """Make trackpad/wheel scrolling work ANYWHERE over the settings window.

        On macOS with Tk 9 there are TWO scroll events: a mouse wheel fires
        <MouseWheel> (whole ±120 deltas), while a trackpad two-finger scroll fires
        <TouchpadScroll> (precise sub-pixel deltas decoded via tk::PreciseScrollDeltas).
        The old handler bound only <MouseWheel>, so the trackpad silently did nothing.
        We bind BOTH on every widget in the window and forward to the canvas; 'break'
        stops CTk's own bind_all handler from also firing (double speed)."""
        canvas = scroll_frame._parent_canvas

        def _has_overflow():
            return canvas.yview() != (0.0, 1.0)

        def _on_wheel(event):                      # mouse wheel (whole ±120 deltas)
            if _has_overflow():
                step = -event.delta
                canvas.yview_scroll(
                    int(step) if abs(step) >= 1 else (1 if step > 0 else -1), "units")
            return "break"

        def _on_touchpad(event):                   # trackpad two-finger (Tk 9 precise)
            try:
                _dx, dy = canvas.tk.call("tk::PreciseScrollDeltas", event.delta)
            except Exception:
                return "break"
            if dy and _has_overflow():
                canvas.yview_scroll(-int(dy), "units")
            return "break"

        def _bind(widget):
            widget.bind("<MouseWheel>", _on_wheel, add="+")
            widget.bind("<TouchpadScroll>", _on_touchpad, add="+")
            for child in widget.winfo_children():
                _bind(child)

        _bind(self._settings_window)

    def _settings_content_height(self):
        """Height the content needs. Use reqheight only (fresh after
        update_idletasks); the canvas bbox can lag a toggle and over-measure,
        which made the window overshoot then clip back."""
        container = self._settings_container
        container.update_idletasks()
        return container.winfo_reqheight() + 2 * PADDING_WINDOW

    def _settings_target_height(self, content):
        """Clamp the content height to a screen-relative [min, max], plus a slack
        margin so the last card is never flush against the window edge."""
        screen_h = self._settings_window.winfo_screenheight()
        min_h = int(screen_h * SETTINGS_WINDOW_MIN_HEIGHT_RATIO)
        max_h = int(screen_h * SETTINGS_WINDOW_MAX_HEIGHT_RATIO)
        return max(min_h, min(content + SETTINGS_WINDOW_HEIGHT_SLACK, max_h))

    def _resize_settings_to_content(self, delta=0):
        """Resize the window to fit its content in ONE step (no per-frame window
        animation — that reflows and jitters the text). `delta` lets an expanding
        section pre-grow the window by the height it's about to reveal, so the
        section can then animate inside a stable window. Scrollbar shows only
        when content still overflows."""
        win = getattr(self, '_settings_window', None)
        if win is None or not win.winfo_exists():
            return
        content = self._settings_content_height() + delta
        target = self._settings_target_height(content)
        self._show_settings_scrollbar(content > target)
        self._apply_settings_height(target)

    def _apply_settings_height(self, height):
        """Set the window height, keeping it fully on-screen (clamp the top)."""
        win = self._settings_window
        if not win.winfo_exists():
            return
        y = max(0, min(win.winfo_y(), win.winfo_screenheight() - height))
        win.geometry(f"{SETTINGS_WINDOW_WIDTH}x{height}+{win.winfo_x()}+{y}")

    def _show_settings_scrollbar(self, needed):
        """Show the scrollbar only when the content overflows the window."""
        scrollbar = self._settings_container._scrollbar
        if needed:
            scrollbar.grid()
        else:
            scrollbar.grid_remove()

    # ------------------ TIMER ------------------

    def _record_event(self, event_type, **data):
        """Persist a break event to the log and surface it on the console."""
        self.event_log.append(event_type, **data)
        logging.info("event: %s %s", event_type, data)

    def timer_loop(self, generation):
        """Single timer loop managing all breaks (context-aware via the scheduler).

        Only the thread owning the current generation keeps running; a thread
        left over from a previous session exits as soon as start() bumps it.
        """
        while timer_should_continue(
            self.running, self.stop_event.is_set(),
            self._timer_generation, generation,
        ):
            time.sleep(1)
            if self.active_popup:
                continue
            if self.paused:
                self._anticipated = None      # no anticipatory chip while paused (#74)
                self._maybe_prompt_resume()   # #77: offer to resume if you're clearly back
                continue

            try:
                ctx = read_context(
                    check_meeting=self.defer_during_meetings.get(),
                    check_fullscreen=self.defer_during_fullscreen.get(),
                    count_mouse_move=self.count_mouse_move.get(),
                )
                pause, away, natural = self._scheduler_thresholds()
                # Raw sensor readings (pre-hysteresis), kept verbatim to log at fire
                # time so an intermittent mid-activity fire is diagnosable (#84).
                raw_meeting, raw_fullscreen = ctx.is_meeting, ctx.is_fullscreen
                raw_active_idle = (ctx.idle_seconds if ctx.active_idle_seconds is None
                                   else ctx.active_idle_seconds)
                # Bridge transient dropouts of each interrupt signal so a due break
                # doesn't fire into a one-sample gap: #46 (fullscreen, Space swipes),
                # #84 (mic per-utterance blips, brief typing pauses).
                eff_fullscreen, self._fullscreen_grace = smooth_signal(
                    raw_fullscreen, self._fullscreen_grace)
                eff_meeting, self._meeting_grace = smooth_signal(
                    raw_meeting, self._meeting_grace)
                raw_active = pause > 0 and raw_active_idle < pause
                eff_active, self._active_grace = smooth_signal(
                    raw_active, self._active_grace)
                ctx = dataclass_replace(
                    ctx, is_fullscreen=eff_fullscreen, is_meeting=eff_meeting,
                    active_idle_seconds=(0.0 if eff_active else ctx.active_idle_seconds))
                # Proactively note a sustained deferral context (call / fullscreen) so
                # the hero can say "your break will wait" before anything is due (#74).
                # Active-typing is excluded — it's transient and would flicker.
                self._anticipated = None
                if self.show_anticipated_defer.get():
                    self._anticipated = ("meeting" if eff_meeting else
                                         "fullscreen" if eff_fullscreen else None)
                states = states_from_configs(self.breaks)
                names = [c.name.get() for c in self.breaks]
                prev_remaining = [c.remaining for c in self.breaks]
                now = time.time()
                prev_episode = self._episode
                new_remaining, fire_index, events, self._episode = advance(
                    states, ctx, self._episode, pause_threshold=pause,
                    away_threshold=away, natural_threshold=natural)
                # A break with a pending snooze is frozen — the snooze IS its next
                # occurrence, so it neither counts down nor fires from the loop (#84).
                pending_names = {e['name'] for e in self._pending_snoozes}
                if pending_names:
                    new_remaining, fire_index = apply_snooze_freeze(
                        new_remaining, fire_index, prev_remaining,
                        names, pending_names)
                # Stamp when each break first became due, to log how long a held
                # break waited before it fired (#85).
                self._due_since = track_due_since(
                    self._due_since, names, prev_remaining, now)
                if prev_episode == IDLE_EPISODE and self._episode != IDLE_EPISODE:
                    # user just returned from a rest that reset the timers
                    self._rested_ack_until = time.time() + NATURAL_BREAK_ACK_SECONDS
                for config, remaining in zip(self.breaks, new_remaining):
                    config.remaining = remaining
                for event_type, data in events:
                    self._record_event(event_type, **data)
                held_reason, self._held = track_held(
                    events, fire_index is not None, self._held)
                if fire_index is not None:
                    name = self.breaks[fire_index].name.get()
                    scheduled_ts, deferred_seconds = deferral_at_fire(
                        self._due_since, name, now)
                    self._due_since.pop(name, None)   # cycle done — restart next time it's due
                    self._log_break_fired(
                        name, "scheduled", raw_idle=ctx.idle_seconds,
                        raw_active_idle=raw_active_idle, raw_meeting=raw_meeting,
                        raw_fullscreen=raw_fullscreen, pause=pause, away=away,
                        held_reason=held_reason, scheduled_ts=scheduled_ts,
                        deferred_seconds=deferred_seconds)
                    logging.info(
                        "break due, firing: %s (idle=%.0fs raw_meeting=%s raw_fs=%s held=%s)",
                        name, ctx.idle_seconds, raw_meeting, raw_fullscreen, held_reason)
                    self.trigger_break(self.breaks[fire_index], held_reason=held_reason)
            except Exception as e:
                logging.error(f"timer_loop tick failed: {e}", exc_info=True)

    def _maybe_check_in_after_break(self):
        """After a real break finishes, maybe surface a break-coupled check-in — cadence-
        gated, and only when nothing else is queued/snoozed/showing so it never stacks (#9)."""
        if self.active_popup or self.break_queue or self._pending_snoozes:
            return
        if not self.check_ins_enabled.get():
            return
        from dfyb.checkins.model import parse_questions
        from dfyb.checkins.scheduler import due_break_check_in
        from dfyb.checkins.history import todays_check_ins
        questions = parse_questions(self.check_in_questions)
        state = self.check_in_state
        answered_today = {r["question_id"]
                          for r in todays_check_ins(self.event_log.read(), time.time())}
        q = due_break_check_in(
            questions, time.time(), state.get("last_prompted", {}),
            state.get("last_prompt_ts", 0.0),
            CHECK_IN_WAKING_WINDOW_SECONDS, MIN_CHECK_IN_GAP_SECONDS,
            answered_today=answered_today)
        if q is not None:
            self._show_check_in(q)

    def _open_check_in_now(self):
        """On-demand entry point (the "Check in" button): open the chooser listing every
        enabled question as a card. Answering stays in the chooser (it refreshes in place)."""
        self._open_check_in_chooser()

    def _open_check_in_chooser(self):
        """A small window of question cards. Pinned to the active Space (no Space switch)."""
        chooser = ctk.CTkToplevel(self.root)
        chooser.title(CHECK_IN_CHOOSER_TITLE)
        chooser.resizable(False, False)
        chooser.configure(fg_color=COLORS['surface_card'])
        pin_to_active_space(chooser)
        chooser.transient(self.root)
        body = ctk.CTkFrame(chooser, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=PADDING_PANEL_X, pady=PADDING_PANEL_Y)
        chooser.protocol("WM_DELETE_WINDOW", chooser.destroy)
        self._render_check_in_chooser(chooser, body)
        self._center_toplevel(chooser, self.root)
        chooser.lift()
        chooser.focus_force()
        # No grab_set: an app-modal grab orphans on macOS after we open the answer popup,
        # leaving the window unclickable. The picker doesn't need modality.

    def _render_check_in_chooser(self, chooser, body):
        """(Re)build the chooser's cards — on open and after each answer, so they reflect
        the newest state — then resize the window to fit."""
        for child in body.winfo_children():
            child.destroy()
        from dfyb.checkins.model import parse_questions
        from dfyb.checkins.history import todays_check_ins
        questions = ([q for q in parse_questions(self.check_in_questions) if q.enabled]
                     if self.check_ins_enabled.get() else [])
        by_q = {}
        for r in todays_check_ins(self.event_log.read(), time.time()):
            by_q.setdefault(r["question_id"], []).append(r)   # oldest -> newest
        if questions:
            ctk.CTkLabel(
                body, text=CHECK_IN_CHOOSER_PROMPT, font=make_font('body', weight="bold"),
                anchor="w", justify="left", wraplength=CHECK_IN_CHOOSER_BTN_WIDTH).pack(
                    anchor="w", pady=(0, SPACE_SM))
            for question in questions:
                self._add_check_in_row(chooser, body, question, by_q.get(question.id, []))
        else:
            ctk.CTkLabel(
                body, text=CHECK_IN_NONE_CONFIGURED_TEXT, font=make_font('body'),
                text_color=COLORS['text_secondary'], anchor="w", justify="left",
                wraplength=CHECK_IN_CHOOSER_BTN_WIDTH).pack(anchor="w", pady=(0, SPACE_SM))
        ctk.CTkButton(
            body, text=CHECK_IN_CHOOSER_CLOSE_LABEL, command=chooser.destroy,
            height=BUTTON_HEIGHT_SMALL, corner_radius=CORNER_RADIUS_BUTTON,
            fg_color="transparent", border_width=CHECK_IN_CARD_BORDER_WIDTH,
            border_color=COLORS['border'], hover_color=COLORS['surface_hover'],
            text_color=COLORS['text_secondary'], font=make_font('label')).pack(
                anchor="e", pady=(SPACE_SM, 0))
        self._refit_toplevel(chooser)

    def _add_check_in_row(self, chooser, body, question, entries):
        """One compact settings-style row: the question on the left; on the right a chevron
        and — when answered today — either the value (once-a-day) or an "N answers" count
        (recurring). Value/count present = answered. Tapping opens the detail popup (answer /
        change / edit) and refreshes the chooser in place. `entries` oldest→newest."""
        answered = bool(entries)
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x", pady=(0, SPACE_XXS))

        def _pick(_e=None):
            self._show_check_in(question, after=lambda: self._reopen_chooser(chooser, body))

        # Right side, packed right-to-left: chevron, then (value | count) when answered.
        ctk.CTkLabel(row, text=CHECK_IN_ROW_CHEVRON, font=make_font('body'),
                     text_color=COLORS['text_tertiary']).pack(side="right", padx=(SPACE_XS, SPACE_SM))
        if answered:
            if question.once_per_day:              # once-a-day → the single value
                latest = entries[-1]
                value = latest.get("value")
                if value is None and latest.get("note"):
                    note = latest["note"]
                    value = (note[:CHECK_IN_ROW_NOTE_MAX] + "…"
                             if len(note) > CHECK_IN_ROW_NOTE_MAX else note)
                text = str(value) if value is not None else ""
                color = COLORS['text_secondary']
            else:                                  # recurring → an "N answers" count, not a value
                n = len(entries)
                word = CHECK_IN_ANSWER_WORD if n == 1 else CHECK_IN_ANSWERS_WORD
                text = CHECK_IN_COUNT_FMT.format(n=n, word=word)
                color = COLORS['text_tertiary']
            if text:
                ctk.CTkLabel(row, text=text, font=make_font('body'),
                             text_color=color).pack(side="right", padx=(0, SPACE_XS))

        ctk.CTkLabel(row, text=question.text, font=make_font('body'),
                     text_color=COLORS['text_primary'], anchor="w", justify="left",
                     wraplength=CHECK_IN_ROW_TEXT_WRAP).pack(
                         side="left", padx=(SPACE_SM, SPACE_XS), pady=SPACE_SM, fill="x", expand=True)

        # The whole row (and all its children) is one click target.
        def _bind_click(widget):
            widget.bind("<Button-1>", _pick)
            try:
                widget.configure(cursor="pointinghand")
            except Exception:
                pass
            for child in widget.winfo_children():
                _bind_click(child)
        _bind_click(row)

    def _reopen_chooser(self, chooser, body):
        """After answering from the chooser, refresh its cards and bring it back (the
        chooser stayed open behind the answer popup — answering never dumps you to the
        main window)."""
        if not chooser.winfo_exists():
            return
        self._render_check_in_chooser(chooser, body)
        chooser.lift()
        chooser.focus_force()

    def _refit_toplevel(self, top):
        """Resize a toplevel to its content in place (keeps its position) — e.g. after an
        expander toggle or a card re-render grows/shrinks the content."""
        if top is None or not top.winfo_exists():
            return
        top.update_idletasks()
        w, h = top.winfo_reqwidth(), top.winfo_reqheight()
        top.tk.call("wm", "geometry", top, f"{w}x{h}+{top.winfo_x()}+{top.winfo_y()}")

    def _show_check_in(self, question, after=None):
        if self.active_popup:                 # something else is showing — skip
            return
        from dfyb.checkins.history import todays_check_ins
        screen = self._capture_active_screen()   # capture before the popup steals focus
        now = time.time()
        entries = [r for r in todays_check_ins(self.event_log.read(), now)
                   if r["question_id"] == question.id]
        if question.once_per_day and entries:
            entries = [entries[-1]]      # once-a-day: one answer for the day (latest wins)
        state = self.check_in_state
        state.setdefault("last_prompted", {})[question.id] = now
        state["last_prompt_ts"] = now
        self._save_preferences()
        self.active_popup = CheckInPopup(
            self.root, question, entries,
            on_answer=lambda v, n: self._on_check_in_done(question, v, n, after),
            on_edit=lambda tid, v, n: self._on_check_in_edited(tid, v, n, after),
            on_remove=lambda tid: self._on_check_in_removed(tid, after),
            on_skip=lambda: self._on_check_in_skipped(after), screen=screen)

    def _on_check_in_done(self, question, value, note, after=None):
        try:
            self._record_event(CHECK_IN,
                               **check_in_event_payload(question, value, note, uuid.uuid4().hex))
        finally:
            self.active_popup = None      # always clear, even if logging fails
        if after is not None:
            after()

    def _on_check_in_edited(self, target_id, value, note, after=None):
        try:
            self._record_check_in_edit(target_id, value, note)
        finally:
            self.active_popup = None      # always clear, even if logging fails
        if after is not None:
            after()

    def _on_check_in_removed(self, target_id, after=None):
        try:
            self._record_check_in_remove(target_id)
        finally:
            self.active_popup = None      # always clear, even if logging fails
        if after is not None:
            after()

    def _record_check_in_edit(self, target_id, value, note):
        self._record_event(CHECK_IN,
                           **check_in_edit_payload(uuid.uuid4().hex, target_id, value, note))

    def _record_check_in_remove(self, target_id):
        self._record_event(CHECK_IN, **check_in_remove_payload(uuid.uuid4().hex, target_id))

    def _on_check_in_skipped(self, after=None):
        self.active_popup = None               # nothing logged
        if after is not None:
            after()

    def _reset_defer_grace(self):
        """Clear the fullscreen/mic/active hysteresis counters (#46/#84) — done on
        Start and on session restore so a new session starts with no carried grace."""
        self._fullscreen_grace = 0
        self._meeting_grace = 0
        self._active_grace = 0

    # --- Resume-while-paused prompt (#77) ---
    def _maybe_prompt_resume(self):
        """Runs each tick WHILE PAUSED (on the timer thread). Samples activity and,
        once you've clearly returned (sustained typing/clicks, or a meeting), offers to
        resume — once per pause episode. Shows the card on the main thread."""
        if not self.prompt_resume_when_back.get():
            return
        if self._resume_card is not None or self._resume_prompted:
            return
        ctx = read_context(
            check_meeting=self.defer_during_meetings.get(),
            check_fullscreen=False,   # fullscreen isn't a "you're back" signal
            count_mouse_move=self.count_mouse_move.get(),
        )
        active_idle = (ctx.idle_seconds if ctx.active_idle_seconds is None
                       else ctx.active_idle_seconds)
        self._resume_streak, should_prompt = resume_prompt_step(
            self._resume_streak, active_idle, ctx.is_meeting,
            RESUME_ACTIVE_THRESHOLD_SECONDS, self.resume_prompt_samples.get(),
            self._resume_prompted)
        if should_prompt:
            self._resume_prompted = True
            self.root.after(0, self._show_resume_card)

    def _reset_resume_prompt(self):
        """Start a fresh pause episode (or end one): clear the streak/flag and close
        any open card so each pause gets at most one resume prompt (#77)."""
        self._resume_streak = 0
        self._resume_prompted = False
        self._close_resume_card()

    def _close_resume_card(self):
        if self._resume_card_after is not None:
            try:
                self.root.after_cancel(self._resume_card_after)
            except Exception:
                pass
            self._resume_card_after = None
        if self._resume_card is not None:
            self._resume_card.destroy()
            self._resume_card = None

    def _accept_resume(self):
        self._record_event(RESUME_ACCEPTED)
        self._close_resume_card()
        if self.paused:
            self.toggle_pause()   # un-pause (also resets the resume state)

    def _dismiss_resume(self):
        # "Stay paused" (or auto-dismissed): leave _resume_prompted=True so we don't re-nag.
        self._record_event(RESUME_DISMISSED)
        self._close_resume_card()

    def _show_resume_card(self):
        """Small non-intrusive floating card offering to resume (#77). Main thread."""
        if self._resume_card is not None or not self.paused:
            return   # already showing, or un-paused before this fired
        self._record_event(RESUME_PROMPTED)
        card = ctk.CTkToplevel(self.root)
        card.title(APP_NAME)
        card.resizable(False, False)
        card.configure(fg_color=COLORS['surface_card'])
        pin_to_active_space(card)
        card.attributes('-topmost', True)
        self._resume_card = card

        wrap = ctk.CTkFrame(card, fg_color="transparent")
        wrap.pack(padx=SPACE_LG, pady=SPACE_LG)
        ctk.CTkLabel(wrap, text=RESUME_CARD_HEADLINE,
                     font=make_font('subheading', weight="bold")).pack(anchor="w")
        ctk.CTkLabel(wrap, text=RESUME_CARD_SUBTEXT, font=make_font('label'),
                     text_color=COLORS['text_secondary']).pack(anchor="w", pady=(0, SPACE_MD))
        btns = ctk.CTkFrame(wrap, fg_color="transparent")
        btns.pack(fill="x")
        ctk.CTkButton(
            btns, text="Resume", command=self._accept_resume,
            height=BUTTON_HEIGHT_SMALL, corner_radius=CORNER_RADIUS_BUTTON,
            fg_color=COLORS['accent_primary'], hover_color=COLORS['accent_primary_hover'],
            font=make_font('label', weight="bold")).pack(
                side="left", expand=True, fill="x", padx=(0, SPACE_XXS))
        ctk.CTkButton(
            btns, text="Stay paused", command=self._dismiss_resume,
            height=BUTTON_HEIGHT_SMALL, corner_radius=CORNER_RADIUS_BUTTON,
            fg_color=COLORS['surface_hover'], hover_color=COLORS['border'],
            text_color=COLORS['text_secondary'], font=make_font('label')).pack(
                side="left", expand=True, fill="x", padx=(SPACE_XXS, 0))

        # Center on the active screen. Mirror the popup: use the REQUESTED size
        # (winfo_width is 1 before the window maps) and set raw Tk `wm geometry`
        # (CTk's .geometry() mislocates cross-monitor +x+y).
        card.update_idletasks()
        w, h = card.winfo_reqwidth(), card.winfo_reqheight()
        screen = self._capture_active_screen() or (
            0, 0, card.winfo_screenwidth(), card.winfo_screenheight())
        x, y = center_on_screen(screen, w, h)
        x, y = clamp_onscreen(x, y, w, h, screen)
        card.tk.call("wm", "geometry", card, f"{w}x{h}+{int(x)}+{int(y)}")
        card.protocol("WM_DELETE_WINDOW", self._dismiss_resume)
        self._resume_card_after = self.root.after(
            RESUME_CARD_TIMEOUT_MS, self._dismiss_resume)

    def _set_reset_enabled(self, enabled):
        """Enable/disable the Reset button with a visibly distinct look (#70) —
        raised & readable when usable, recessed & faded when there's nothing to reset."""
        self.reset_btn.configure(**reset_button_style(enabled, COLORS))

    def _log_break_fired(self, name, source, *, raw_idle, raw_active_idle,
                         raw_meeting, raw_fullscreen, pause, away, held_reason,
                         scheduled_ts, deferred_seconds):
        """Record the fire-time context (#52/#84) so an intermittent mid-activity
        fire is diagnosable — the RAW (pre-hysteresis) sensor values plus the
        thresholds in force, tagged by which path fired it (scheduled/snooze_return).
        Also records when the break first became due (`scheduled_ts`) and how long it
        was then held (`deferred_seconds`), so the dashboard can see push-back (#85)."""
        self._record_event(
            BREAK_FIRED, name=name, source=source,
            idle_seconds=round(raw_idle, 1),
            active_idle_seconds=(None if raw_active_idle is None
                                 else round(raw_active_idle, 1)),
            is_meeting=raw_meeting, is_fullscreen=raw_fullscreen,
            pause_threshold=pause, away_threshold=away, held_reason=held_reason,
            scheduled_ts=round(scheduled_ts, 1),
            deferred_seconds=round(deferred_seconds, 1))

    def _scheduler_thresholds(self):
        """Coordinated (pause, away, natural) idle thresholds from prefs — the one
        source of truth for both the timer loop and the snooze-hold check."""
        pause = (self.activity_pause_seconds.get()
                 if self.defer_while_active.get() else 0)
        return coordinate_thresholds(pause, self.away_idle_seconds.get(),
                                     self.natural_break_seconds.get())

    def _capture_active_screen(self):
        """Screen (x, y, w, h) the user is working on, captured BEFORE the popup
        is built (while their app is still frontmost). Falls back to dfyb's own
        window's screen, then the primary; None off-macOS."""
        screens = _display_rects()
        if not screens:
            return None
        rect = frontmost_window_rect()
        if rect:
            hit = screen_for_point((rect[0] + rect[2] / 2, rect[1] + rect[3] / 2), screens)
            if hit:
                return hit
        try:  # fallback: the screen dfyb's own window sits on
            hit = screen_for_point((self.root.winfo_rootx(), self.root.winfo_rooty()), screens)
            if hit:
                return hit
        except Exception:
            pass
        return screens[0]

    def trigger_break(self, config, held_reason=None, preview=False):
        """Queue a break with the given configuration (skips a duplicate that's
        already showing / queued / pending-snoozed) (#50). `preview=True` shows the
        popup without touching the schedule (Test) — see #54."""
        name = config.name.get()
        queued = [b['name'] for b in self.break_queue]
        pending = [e['name'] for e in self._pending_snoozes]
        if break_in_play(name, self._active_break_name, queued, pending):
            logging.info("skip duplicate break '%s' (already in play)", name)
            return
        break_data = {
            'name': config.name.get(),
            'duration': config.get_duration_seconds(),
            'auto_dismiss': config.auto_dismiss.get(),
            'snoozable': config.snoozable.get(),
            'start_sound': config.start_sound.get(),
            'end_sound': config.end_sound.get(),
            'loop_end_sound': config.loop_end_sound.get(),
            'held_reason': held_reason,
            'preview': preview,
        }
        self.break_queue.append(break_data)
        self.root.after(0, self._process_break_queue)

    def _process_break_queue(self):
        """Process the next break in the queue if no popup is active."""
        if self.active_popup or not self.break_queue:
            return

        break_data = self.break_queue.pop(0)

        if break_data['duration'] <= 0:
            self.root.after(0, self._process_break_queue)
            return

        play_sound(break_data['start_sound'])
        self.break_start_time = time.time()

        def on_popup_close():
            elapsed = int(time.time() - self.break_start_time) if self.break_start_time else 0
            # A preview (Test) must not touch the schedule: no BREAK_TAKEN event, no
            # timer reset, no charging elapsed time to other queued breaks (#54).
            if not break_data.get('preview'):
                # Runs on the main thread. EventLog.append has no internal lock, but the
                # timer thread skips all event-log writes while self.active_popup is set
                # (cleared further down), so this call never interleaves with the loop's appends.
                self._record_event(
                    BREAK_TAKEN,
                    name=break_data['name'],
                    duration=break_data['duration'],
                    used_seconds=elapsed,
                )
                for queued_break in self.break_queue:
                    queued_break['duration'] -= elapsed

                # Taking a break restarts its own scheduler timer so it can't be
                # re-fired immediately (e.g. after a snooze / short interval) (#45).
                for config in self.breaks:
                    if config.name.get() == break_data['name']:
                        config.reset_timer()
                        break

            self.active_popup = None
            self._active_break_name = None
            self.break_start_time = None
            if self.running and not self.paused:
                self._render_status()
            elif not self.running:
                self._render_status()
            if not break_data.get('preview'):
                self.root.after(0, self._maybe_check_in_after_break)
            self.root.after(0, self._process_break_queue)

        def on_snooze(snooze_seconds):
            self._record_event(BREAK_SNOOZED, name=break_data['name'], seconds=snooze_seconds)
            self.snooze_seconds.set(snooze_seconds)   # remember as the new default
            self._save_preferences()
            self.active_popup = None
            self._active_break_name = None
            self.break_start_time = None
            if self.running and not self.paused:
                self._render_status()
            # An explicit snooze always comes back after its delay, regardless of
            # Start/Stop; _requeue_break holds it while paused or context-deferred.
            entry = {"name": break_data['name'], "break_data": break_data,
                     "fire_time": time.time() + snooze_seconds, "after_id": None}
            entry["after_id"] = self.root.after(
                snooze_delay_ms(snooze_seconds),
                lambda: self._requeue_break(break_data, entry))
            self._pending_snoozes.append(entry)

        # How many times this break was snoozed / when it was first due (#37).
        events = self.event_log.read()
        snooze_count = snooze_count_since_taken(events, break_data['name'])
        first_snooze_ago = first_snooze_seconds_ago(
            events, break_data['name'], time.time())
        # Capture the active screen NOW, before the popup's window steals focus.
        target_screen = (self._capture_active_screen()
                         if self.popup_placement.get() == "active" else None)
        self._active_break_name = break_data['name']   # for dedup while showing (#50)
        self.active_popup = CountdownPopup(
            self.root,
            break_data['name'],
            random.choice(BREAK_MESSAGES),
            break_data['duration'],
            auto_dismiss=break_data['auto_dismiss'],
            snoozable=break_data['snoozable'],
            on_close=on_popup_close,
            on_snooze=on_snooze,
            end_sound=break_data['end_sound'],
            loop_end_sound=break_data['loop_end_sound'],
            placement=self.popup_placement.get(),
            target_screen=target_screen,
            held_reason=break_data.get('held_reason'),
            snooze_seconds=self.snooze_seconds.get(),
            snooze_count=snooze_count,
            first_snooze_ago=first_snooze_ago,
        )
        self._render_status()

    def _requeue_break(self, break_data, entry=None):
        """Re-show a snoozed break. An explicit snooze always returns regardless of
        Start/Stop; a Pause holds it, and context (meeting/fullscreen/away/
        mid-activity) defers it like a scheduled break (#42), re-checking later."""
        ctx = read_context(
            check_meeting=self.defer_during_meetings.get(),
            check_fullscreen=self.defer_during_fullscreen.get(),
            count_mouse_move=self.count_mouse_move.get(),
        )
        pause, away, _natural = self._scheduler_thresholds()
        context_defers = should_hold_snooze(
            self.paused,
            decide(ctx, away_threshold=away, pause_threshold=pause) == DEFER)
        # Require consecutive clear polls before returning, so a single mic/activity
        # blip at the return moment doesn't pop the break mid-work (#84).
        prev_streak = entry.get("clear_polls", 0) if entry is not None else 0
        streak, should_return = next_clear_streak(
            prev_streak, context_defers, SNOOZE_CLEAR_POLLS_REQUIRED)
        if entry is not None:
            entry["clear_polls"] = streak
        if not should_return:
            # Paused, context-deferred, or not yet enough clear polls — wait & re-check.
            logging.info("snoozed break held (paused=%s fs=%s meeting=%s clear=%d/%d), re-checking",
                         self.paused, ctx.is_fullscreen, ctx.is_meeting,
                         streak, SNOOZE_CLEAR_POLLS_REQUIRED)
            after_id = self.root.after(SNOOZE_RECHECK_MS,
                                       lambda: self._requeue_break(break_data, entry))
            if entry is not None:
                entry["after_id"] = after_id
            return
        if entry is not None and entry in self._pending_snoozes:
            self._pending_snoozes.remove(entry)
        self._record_event(BREAK_SNOOZE_RETURNED, name=break_data['name'])
        # A snoozed break's "scheduled" moment is its snooze fire_time; held time is
        # how far past that it waited for a good moment to return (#85).
        now = time.time()
        scheduled_ts = entry['fire_time'] if entry is not None else now
        self._log_break_fired(
            break_data['name'], "snooze_return", raw_idle=ctx.idle_seconds,
            raw_active_idle=(ctx.idle_seconds if ctx.active_idle_seconds is None
                             else ctx.active_idle_seconds),
            raw_meeting=ctx.is_meeting, raw_fullscreen=ctx.is_fullscreen,
            pause=pause, away=away, held_reason=None,
            scheduled_ts=scheduled_ts,
            deferred_seconds=max(0.0, now - scheduled_ts))
        name = break_data['name']
        queued = [b['name'] for b in self.break_queue]
        if break_in_play(name, self._active_break_name, queued, []):
            logging.info("snoozed break '%s' returned but already in play — coalescing", name)
            return
        self.break_queue.append(break_data)
        self.root.after(0, self._process_break_queue)

    def _cancel_snooze(self, entry):
        """Cancel a pending snooze (✕ on its row): drop the scheduled re-fire."""
        if entry.get("after_id") is not None:
            try:
                self.root.after_cancel(entry["after_id"])
            except Exception:
                pass
        if entry in self._pending_snoozes:
            self._pending_snoozes.remove(entry)
        self._record_event(
            BREAK_SNOOZE_CANCELLED, name=entry["name"],
            remaining_seconds=snooze_remaining(entry["fire_time"], time.time()))

    def _fire_snooze_now(self, entry):
        """▶ on a snooze row: bring the snoozed break back right now — skip the
        remaining wait and the context-hold (explicit action, like Break now)."""
        if entry.get("after_id") is not None:
            try:
                self.root.after_cancel(entry["after_id"])
            except Exception:
                pass
        if entry in self._pending_snoozes:
            self._pending_snoozes.remove(entry)
        break_data = entry["break_data"]
        self._record_event(BREAK_SNOOZE_RETURNED, name=break_data['name'], early=True)
        self._render_snooze_rows(time.time())
        if break_in_play(break_data['name'], self._active_break_name,
                         [b['name'] for b in self.break_queue], []):
            return
        self.break_queue.append(break_data)
        self.root.after(0, self._process_break_queue)

    def test_break(self, config):
        """Preview a break configuration without affecting its schedule (#54)."""
        self.trigger_break(config, preview=True)

    def break_now(self, config):
        """Take this break immediately: reset its countdown and show the popup.

        Manual/explicit action — bypasses the scheduler's fullscreen/away
        deferral (trigger_break shows the popup directly, not via the timer loop).
        Cancels any pending snooze for this break first, so Break now overrides a
        snooze and shows it right away instead of being coalesced away (#50).
        """
        name = config.name.get()
        for entry in [e for e in self._pending_snoozes if e['name'] == name]:
            self._cancel_snooze(entry)
        config.reset_timer()
        self.trigger_break(config)
        self.update_ui()

    def skip_break(self, config):
        """⏭ on a break row: skip this cycle — reset the countdown to a full
        interval so it won't fire now (it returns on its normal schedule), and log
        it as skipped (not taken)."""
        config.reset_timer()
        self._record_event(BREAK_SKIPPED, name=config.name.get())
        self.update_ui()

    def _open_reschedule(self, config, anchor):
        """In-window popover to nudge THIS cycle's countdown sooner/later (one-time)."""
        self._close_reschedule()   # one at a time
        interval = config.get_interval_seconds()
        floor, ceiling = reschedule_bounds(interval)
        r = self._reschedule = {"config": config, "floor": floor, "ceiling": ceiling,
                                "step": reschedule_step(interval),
                                "open_remaining": config.remaining, "just_opened": True}
        ov = ctk.CTkFrame(self.root, corner_radius=CORNER_RADIUS_PANEL,
                          fg_color=COLORS['surface_card'], border_width=1,
                          border_color=COLORS['border'])
        ctk.CTkLabel(ov, text=f"Next {config.name.get()}", font=make_font('caption'),
                     text_color=COLORS['text_tertiary']).pack(padx=SPACE_MD, pady=(SPACE_SM, 0))
        rowf = ctk.CTkFrame(ov, fg_color="transparent")
        rowf.pack(padx=SPACE_MD, pady=SPACE_SM)
        r["sooner"] = ctk.CTkButton(
            rowf, text="◀ Sooner", width=76, command=lambda: self._reschedule_nudge(-1),
            fg_color="transparent", hover_color=COLORS['surface_hover'],
            text_color=COLORS['accent_primary'], font=make_font('label'))
        r["sooner"].pack(side="left")
        r["time"] = ctk.CTkLabel(rowf, text=self._format_time(config.remaining),
                                 font=make_font('subheading'), width=72)
        r["time"].pack(side="left", padx=SPACE_SM)
        r["later"] = ctk.CTkButton(
            rowf, text="Later ▶", width=76, command=lambda: self._reschedule_nudge(1),
            fg_color="transparent", hover_color=COLORS['surface_hover'],
            text_color=COLORS['accent_primary'], font=make_font('label'))
        r["later"].pack(side="left")
        ov.update_idletasks()
        ow, oh = ov.winfo_reqwidth(), ov.winfo_reqheight()
        ax = anchor.winfo_rootx() - self.root.winfo_rootx()
        ay = anchor.winfo_rooty() - self.root.winfo_rooty()
        # right-align under the countdown, clamped to both window edges
        x = min(max(SPACE_XXS, ax + anchor.winfo_width() - ow),
                self.root.winfo_width() - ow - SPACE_XXS)
        below = ay + anchor.winfo_height() + SPACE_XXS
        # drop below the countdown, or flip above it when there's no room (bottom rows)
        y = below if below + oh <= self.root.winfo_height() else max(SPACE_XXS, ay - oh - SPACE_XXS)
        ov.place(x=x, y=y)
        ov.lift()
        r["overlay"] = ov
        r["sooner"].configure(state="normal" if config.remaining > floor else "disabled")
        r["later"].configure(state="normal" if config.remaining < ceiling else "disabled")

    def _reschedule_nudge(self, direction):
        r = self._reschedule
        cfg = r["config"]
        cfg.remaining = nudged_remaining(cfg.remaining, direction * r["step"],
                                         r["floor"], r["ceiling"])
        r["time"].configure(text=self._format_time(cfg.remaining))
        r["sooner"].configure(state="normal" if cfg.remaining > r["floor"] else "disabled")
        r["later"].configure(state="normal" if cfg.remaining < r["ceiling"] else "disabled")
        self.update_ui()

    def _reschedule_click_away(self, event):
        r = self._reschedule
        if not r:
            return
        if r.get("just_opened"):
            r["just_opened"] = False   # ignore the very click that opened the popover
            return
        ov = r["overlay"]
        if not point_in_rect(event.x_root, event.y_root, ov.winfo_rootx(),
                             ov.winfo_rooty(), ov.winfo_width(), ov.winfo_height()):
            self._close_reschedule()

    def _close_reschedule(self):
        r = self._reschedule
        if not r:
            return
        cfg = r["config"]
        if cfg.remaining != r["open_remaining"]:
            self._record_event(BREAK_RESCHEDULED, name=cfg.name.get(),
                               from_seconds=r["open_remaining"], to_seconds=cfg.remaining,
                               delta_seconds=cfg.remaining - r["open_remaining"])
        r["overlay"].destroy()   # destroy, not place_forget (Tk 9 Aqua ghost)
        self._reschedule = None

    # ------------------ UI UPDATE ------------------

    def _build_snooze_row(self, entry, status):
        row = ctk.CTkFrame(self._snoozed_container, corner_radius=CORNER_RADIUS_PANEL,
                           fg_color=COLORS['surface_card'])
        row.pack(fill="x", pady=(0, SPACE_XS))
        ctk.CTkLabel(
            row, text=entry['name'],
            font=make_font('label')
        ).pack(side="left", padx=(PADDING_PANEL_X, 0), pady=SPACE_SM)
        ctk.CTkButton(
            row, text="✕", width=28, height=BUTTON_HEIGHT_SMALL,
            corner_radius=CORNER_RADIUS_INPUT, fg_color="transparent",
            border_width=1, border_color=COLORS['border'], hover_color=COLORS['surface_hover'],
            font=make_font('caption'),
            command=lambda: self._cancel_snooze(entry)
        ).pack(side="right", padx=(0, PADDING_PANEL_X), pady=SPACE_SM)
        take_now = ctk.CTkButton(
            row, text="", image=load_icon('play', size=PLAY_GLYPH_SIZE),
            width=28, height=BUTTON_HEIGHT_SMALL, corner_radius=CORNER_RADIUS_INPUT,
            fg_color="transparent", hover_color=COLORS['surface_hover'],
            command=lambda: self._fire_snooze_now(entry))
        take_now.pack(side="right", padx=(0, SPACE_XS), pady=SPACE_SM)
        self._register_tooltip(take_now, "Take now")
        status_label = ctk.CTkLabel(
            row, text=status,
            font=make_font('caption'),
            text_color=COLORS['text_secondary'])
        status_label.pack(side="right", padx=(0, SPACE_SM), pady=SPACE_SM)
        return {"frame": row, "status": status_label}

    def _render_snooze_rows(self, now):
        entries = self._pending_snoozes
        rows_before = len(self._snooze_rows)
        if entries and self._snooze_header.winfo_manager() != "pack":
            self._snooze_header.pack(anchor="w", padx=PADDING_PANEL_X, pady=(SPACE_XXS, SPACE_XXS))
        elif not entries and self._snooze_header.winfo_manager() == "pack":
            self._snooze_header.pack_forget()
        current = set()
        for entry in entries:
            eid = id(entry)
            current.add(eid)
            remaining = snooze_remaining(entry["fire_time"], now)
            status = (f"returns in {self._format_time(remaining)}"
                      if remaining > 0 else "returning…")
            if eid in self._snooze_rows:
                self._snooze_rows[eid]["status"].configure(text=status)
            else:
                self._snooze_rows[eid] = self._build_snooze_row(entry, status)
        for eid in list(self._snooze_rows):
            if eid not in current:
                self._snooze_rows[eid]["frame"].destroy()
                del self._snooze_rows[eid]
        if len(self._snooze_rows) != rows_before:
            self._refit_window()   # grow/shrink so snooze rows are never clipped

    def _register_tooltip(self, widget, text):
        """Bind a gentle hover hint. The button's internal canvas fires <Enter>
        (the wrapper doesn't), so we schedule the hint there. We do NOT trust
        <Leave>: on macOS it silently fails to fire when the pointer exits the
        window (e.g. onto another app), which strands the chip. Instead a timer
        watches the pointer's real screen position and hides when it leaves."""
        canvas = getattr(widget, "_canvas", widget)
        canvas.bind("<Enter>", lambda _e: self._tip_schedule(widget, text), add="+")

    def _tip_schedule(self, widget, text):
        # Ignore a redundant <Enter> for the button we're already handling. macOS
        # refires <Enter> on the canvas when we place()/lift() the chip; without
        # this guard each refire restarted the fade from 0, flashing the chip.
        if widget is self._tip_target:
            return
        self._tip_target = widget           # authoritative "what we're tracking"
        self._tip_miss = 0
        if self._tip_after is not None:
            self.root.after_cancel(self._tip_after)
            self._tip_after = None
        if self._tip_fade is not None:
            self.root.after_cancel(self._tip_fade)
            self._tip_fade = None
        if self._tip_lbl is not None:
            # A chip is still on screen (switching from a sibling ▶, or reviving a
            # fade-out): reposition and SNAP to full — no re-fade, so no pop/flash.
            self._tip_place(widget, text)
            self._tip_paint(1.0)
        else:
            self._tip_after = self.root.after(
                TOOLTIP_DELAY_MS, lambda: self._tip_show(widget, text))
        self._tip_watch_start()             # guard the whole delay→show→shown lifetime

    def _pointer_over(self, widget):
        """True if the mouse's screen coords fall inside the widget's rectangle.
        Geometry-based (not event/hit-test based) so it stays correct even when
        the pointer has left the app window without emitting a <Leave>."""
        px, py = self.root.winfo_pointerxy()
        return point_in_rect(px, py, widget.winfo_rootx(), widget.winfo_rooty(),
                             widget.winfo_width(), widget.winfo_height())

    def _tip_watch_start(self):
        if self._tip_watch is not None:
            self.root.after_cancel(self._tip_watch)
        self._tip_watch = self.root.after(TOOLTIP_POLL_MS, self._tip_watch_tick)

    def _tip_watch_tick(self):
        # Reschedule purely on target + pointer position — no dependency on the
        # label's mapped-state timing (which raced and could kill the watchdog).
        # Require TOOLTIP_MISS_LIMIT consecutive off-target polls before hiding so
        # a single edge-jitter sample can't flicker the chip out and back.
        self._tip_watch = None
        if self._tip_target is None:
            return
        if self._pointer_over(self._tip_target):
            self._tip_miss = 0
            self._tip_watch_start()
        else:
            self._tip_miss += 1
            if self._tip_miss >= TOOLTIP_MISS_LIMIT:
                self._tip_dismiss()
            else:
                self._tip_watch_start()

    def _tip_dismiss(self):
        """Pointer left: stop tracking and fade the chip out (fade end → destroy)."""
        self._tip_target = None
        for attr in ("_tip_after", "_tip_watch"):
            handle = getattr(self, attr)
            if handle is not None:
                self.root.after_cancel(handle)
                setattr(self, attr, None)
        if self._tip_lbl is not None:
            self._tip_fade_start(out=True)

    def _tip_hide(self):
        self._tip_target = None
        for attr in ("_tip_after", "_tip_watch", "_tip_fade"):
            handle = getattr(self, attr)
            if handle is not None:
                self.root.after_cancel(handle)
                setattr(self, attr, None)
        if self._tip_lbl is not None:
            # DESTROY, not place_forget(): on Tk 9 Aqua place_forget() unmaps the
            # overlay logically (winfo_ismapped→0) but never repaints the vacated
            # pixels, so the chip ghosts on screen forever. destroy() tears down
            # the NSView and forces the region to redraw. _tip_show recreates it.
            self._tip_lbl.destroy()
            self._tip_lbl = None

    def _tip_show(self, widget, text):
        """Fresh appearance after the hover delay: place the chip and fade it in."""
        self._tip_after = None
        self._tip_miss = 0
        self._tip_watch_start()   # re-arm the guard for the shown phase
        self._tip_place(widget, text)
        self._tip_fade_start(out=False)

    def _tip_place(self, widget, text):
        """Create (if needed), label, and position the chip above `widget`."""
        if self._tip_lbl is None:
            # bg_color matches the card so the label's bounding box doesn't show a
            # dark ring at the rounded corners (the default bg is the darker window
            # background, which read as an accidental stroke against the card).
            self._tip_lbl = ctk.CTkLabel(
                self.root, text="", font=make_font('caption'), height=22,
                corner_radius=CORNER_RADIUS_INPUT, bg_color=COLORS['surface_card'])
        self._tip_lbl.configure(text=f"  {text}  ")   # breathing room around the text
        self._tip_lbl.update_idletasks()
        w, h = self._tip_lbl.winfo_reqwidth(), self._tip_lbl.winfo_reqheight()
        bx = widget.winfo_rootx() - self.root.winfo_rootx() + widget.winfo_width() // 2
        by = widget.winfo_rooty() - self.root.winfo_rooty()
        # Centre over the widget, but clamp to BOTH window edges so a wide hint on
        # a right-aligned control (e.g. Feedback) shifts left instead of clipping.
        x = min(max(SPACE_XXS, bx - w // 2), self.root.winfo_width() - w - SPACE_XXS)
        self._tip_lbl.place(x=x, y=by - h - SPACE_XXS)
        self._tip_lbl.lift()

    def _tip_fade_start(self, out=False):
        # Fade in (out=False) or out (out=True). A fade-OUT ends by destroying the
        # chip — never place_forget(), which ghosts on Tk 9 Aqua (see _tip_hide).
        if self._tip_fade is not None:
            self.root.after_cancel(self._tip_fade)
            self._tip_fade = None
        if prefers_reduced_motion():
            self._tip_paint(0.0 if out else 1.0)
            if out:
                self._tip_hide()
            return
        self._tip_fade_step(0, out)

    def _tip_fade_step(self, frame, out):
        if self._tip_lbl is None:
            return
        t = ease_out_quad(min(1.0, frame / TOOLTIP_FADE_FRAMES))
        self._tip_paint(1.0 - t if out else t)
        if frame < TOOLTIP_FADE_FRAMES:
            self._tip_fade = self.root.after(
                ANIMATION_FRAME_INTERVAL, lambda: self._tip_fade_step(frame + 1, out))
        else:
            self._tip_fade = None
            if out:
                self._tip_hide()   # destroy only after fully faded — no ghost

    def _tip_paint(self, alpha):
        """Fade the chip from the card background (alpha 0, invisible) to full.
        bg_color tracks fg_color so the rounded-corner background matches the
        fill — no dark ring at the anti-aliased edge."""
        mode = ctk.get_appearance_mode()
        base = resolve_color(COLORS['surface_card'], mode)
        fill = lerp_color(base, resolve_color(COLORS['surface_hover'], mode), alpha)
        self._tip_lbl.configure(
            fg_color=fill, bg_color=fill,
            text_color=lerp_color(base, resolve_color(COLORS['text_secondary'], mode), alpha))

    def _row_subtitle(self, config):
        """Interval · duration label for a break row, e.g. 'every 15 min · 20 sec'."""
        return (f"every {humanize_seconds(config.get_interval_seconds())}"
                f" · {humanize_seconds(config.get_duration_seconds())}")

    def _render_status(self):
        """Render the cockpit hero from current state — the single source of truth
        for the status area, called both on state changes and every tick."""
        next_name, next_remaining, next_interval = "", 0, 0
        if self.running and self.breaks:   # gather even when paused (frozen progress)
            nxt = min(self.breaks, key=lambda c: c.remaining)
            next_name = nxt.name.get()
            next_remaining = max(0, nxt.remaining)
            next_interval = nxt.get_interval_seconds()
        just_rested = (self._rested_ack_until is not None
                       and time.time() < self._rested_ack_until)
        view = compute_status(
            running=self.running, paused=self.paused, held_reason=self._held,
            next_name=next_name, next_remaining=next_remaining,
            next_interval=next_interval, break_active=self.active_popup is not None,
            just_rested=just_rested, anticipated_reason=self._anticipated)
        self.status_dot.configure(fg_color=STATUS_DOT_COLORS[view.dot])
        self.status.configure(text=STATUS_STATE_LABELS[view.state],
                              text_color=COLORS['text_secondary'])
        self.hero_headline.configure(text=view.headline)
        self.hero_sub.configure(text=view.subtext)
        if view.progress_style == "live":       # blue, moving
            self.hero_progress.configure(progress_color=COLORS['accent_primary'])
            self.hero_progress.set(view.progress)
        elif view.progress_style == "frozen":   # paused: grey, held where it was
            self.hero_progress.configure(progress_color=COLORS['text_secondary'])
            self.hero_progress.set(view.progress)
        else:                                   # idle: flat neutral rail, no nub
            self.hero_progress.configure(progress_color=COLORS['surface_hover'])
            self.hero_progress.set(0)
        if view.chip:
            self.hero_chip.configure(text=f"⏸ {view.chip}")
            if self.hero_chip.winfo_manager() != "pack":
                self.hero_chip.pack(fill="x", padx=HERO_PAD, pady=(0, SPACE_SM),
                                    after=self.hero_progress)
        elif self.hero_chip.winfo_manager() == "pack":
            self.hero_chip.pack_forget()

    def update_ui(self):
        """Refresh the cockpit hero, per-break timers, holding cues, and snooze rows."""
        now = time.time()
        if self._countdown_color is None and self._timer_labels:
            self._countdown_color = self._timer_labels[0].cget("text_color")  # theme default
        # Soonest pending snooze per break name — that break is frozen (#84).
        pending_by_name = {}
        for e in self._pending_snoozes:
            cur = pending_by_name.get(e['name'])
            if cur is None or e['fire_time'] < cur['fire_time']:
                pending_by_name[e['name']] = e
        for i, config in enumerate(self.breaks):
            snooze_entry = pending_by_name.get(config.name.get())
            if snooze_entry is not None:
                # Frozen while snoozed: the row shows the RETURN countdown, greyed,
                # instead of a ticking interval — the snooze IS its next occurrence.
                time_text = self._format_time(snooze_remaining(snooze_entry['fire_time'], now))
                timer_color = COLORS['text_tertiary']
                subtitle = ROW_SNOOZED_SUBTITLE
            else:
                time_text = self._format_time(config.remaining)
                timer_color = self._countdown_color or COLORS['text_tertiary']
                subtitle = self._row_subtitle(config)
            if i < len(self._timer_labels):
                self._timer_labels[i].configure(text=time_text, text_color=timer_color)
            if i < len(self._interval_labels):
                self._interval_labels[i].configure(text=subtitle)
            # Update settings panel header timer if settings window is open
            if hasattr(self, '_settings_panels') and i < len(self._settings_panels):
                try:
                    self._settings_panels[i].update_header_timer(time_text)
                except Exception:
                    pass

            # Gentle "holding" cue (#44): show why a due break is waiting.
            cue = holding_cue(config.remaining, self._held) if (
                self.running and not self.paused) else None
            if i < len(self._cue_labels):
                label = self._cue_labels[i]
                if cue:
                    label.configure(text=f"↳ {cue}")
                    if label.winfo_manager() != "pack":   # not already packed
                        label.pack(side="top", anchor="w",
                                   padx=(PADDING_PANEL_X, 0), pady=(0, SPACE_SM))
                elif label.winfo_manager() == "pack":     # currently packed → hide
                    label.pack_forget()

        self._render_status()
        self._render_snooze_rows(now)
        self._maybe_refit()
        self.root.after(1000, self.update_ui)

    def _maybe_refit(self):
        """Re-fit the window height when content grows/shrinks (snooze row or
        holding chip appearing), keeping its CURRENT position."""
        self.root.update_idletasks()
        h = self.root.winfo_reqheight()
        if h == getattr(self, "_last_fit_height", None):
            return
        self._last_fit_height = h
        w = self.root.winfo_reqwidth()
        self.root.geometry(f"{w}x{h}+{self.root.winfo_x()}+{self.root.winfo_y()}")

    @staticmethod
    def _format_time(seconds):
        """Format seconds as MM:SS."""
        m, s = divmod(max(0, seconds), 60)
        return f"{m:02}:{s:02}"


# ------------------ SINGLE INSTANCE ------------------

def is_instance_running():
    """Check if another instance is already running by examining the lock file."""
    if not LOCK_FILE.exists():
        return False

    try:
        with open(LOCK_FILE, 'r') as f:
            pid = int(f.read().strip())
        # Check if process with this PID is still running
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError, PermissionError, FileNotFoundError, OSError):
        # PID invalid, process not running, or file doesn't exist
        return False


def create_lock_file():
    """Create lock file with current PID."""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_FILE, 'w') as f:
        f.write(str(os.getpid()))


def remove_lock_file():
    """Remove lock file on exit."""
    try:
        LOCK_FILE.unlink()
    except FileNotFoundError:
        pass


def check_single_instance():
    """Check for existing instance and prompt user if found.

    Returns True if app should continue, False if it should exit.
    """
    if not is_instance_running():
        return True

    # Show dialog using basic tkinter (before CTk is initialized)
    temp_root = tk.Tk()
    temp_root.withdraw()

    result = messagebox.askyesno(
        "Already Running",
        "Don't Forget Your Breaks is already running.\n\n"
        "Do you want to launch another instance anyway?",
        parent=temp_root
    )

    temp_root.destroy()
    return result


# ------------------ MAIN ------------------

def activate_window(root):
    """macOS-specific: bring window to front when launched from .app bundle."""
    root.deiconify()
    root.lift()
    root.focus_force()


if __name__ == "__main__":
    # Check for existing instance
    if not check_single_instance():
        sys.exit(0)

    # Create lock file and register cleanup
    create_lock_file()
    atexit.register(remove_lock_file)

    root = ctk.CTk()
    app = BreakApp(root)

    if sys.platform == "darwin":
        root.after(100, lambda: activate_window(root))

    root.mainloop()

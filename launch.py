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
    VERSION_FILE,
    HOMEBREW_CASK_NAME,
    BASE_DIR,
)
from dfyb.animation import ease_out_quad, prefers_reduced_motion, lerp_color
from dfyb.geometry import point_in_rect
from dfyb.theme import resolve_font_family, resolve_color
from dfyb.ring import ring_image
from dfyb.activity.event_log import (
    EventLog, BREAK_TAKEN, BREAK_SNOOZED,
    BREAK_SNOOZE_CANCELLED, BREAK_SNOOZE_RETURNED)
from dfyb.activity.sensors import read_context, frontmost_window_rect, smooth_fullscreen
from dfyb.popup_placement import screen_for_point, center_on_screen, clamp_onscreen
from dfyb.scheduler.adapter import states_from_configs
from dfyb.scheduler.tick import advance
from dfyb.scheduler.engine import decide, DEFER
from dfyb.scheduler.dedup import break_in_play
from dfyb.timer_lifecycle import timer_should_continue
from dfyb.macos_window import pin_to_active_space
from dfyb.insights.transparency import track_held, held_message, holding_cue
from dfyb.insights.status import compute_status
from dfyb.insights.over_break import format_over_time
from dfyb.snooze import (
    snooze_delay_ms, format_snooze_short, format_snooze_long, custom_snooze_seconds,
    should_hold_snooze, snooze_remaining)
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
        val = CFStr.CFStringCreateWithCString(None, APP_NAME.encode('utf-8'), 0)

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
GITHUB_NEW_ISSUE_URL = "https://github.com/YairShachar/dont-forget-your-breaks/issues/new"
UPDATE_CHECK_INTERVAL_HOURS = 24

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
    'text_secondary':       ("#8E8E93", "#999999"),   # dark ≡ old gray60
    'text_tertiary':        ("#AEAEB2", "#808080"),   # dark ≡ old gray50
    'accent_primary':       ("#007AFF", "#0A84FF"),   # systemBlue
    'accent_primary_hover': ("#0068D6", "#0077ED"),
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

# Corner radii
CORNER_RADIUS_PANEL = 10
CORNER_RADIUS_BUTTON = 8
CORNER_RADIUS_INPUT = 6

# Button dimensions
BUTTON_HEIGHT_LARGE = 38    # Control buttons (Start/Reset/Pause)
BUTTON_HEIGHT_SMALL = 28    # Test, play buttons
BUTTON_HEIGHT_XLARGE = 40   # Popup actions (Snooze / ▾ / Done / Set)

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
SETTINGS_WINDOW_Y_OFFSET = 80           # px the window sits above the main window

# Break popup
POPUP_WIDTH = 380  # height fits content (see CountdownPopup._position_popup)
# Activity-pause deferral (#34) slider bounds
ACTIVITY_PAUSE_MIN = 2
ACTIVITY_PAUSE_MAX = 15
ACTIVITY_PAUSE_DEFAULT = 2   # seconds of stillness before a due break fires
SNOOZE_RECHECK_MS = 5000     # while a snoozed break is context-deferred, re-check this often
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

# Gentle rotating messages for the break popup (generic for now; per-break-kind
# copy comes with the break-kind model, #30).
BREAK_MESSAGES = [
    "Time for a break.",
    "Rest for a moment — you've earned it.",
    "Ease off the screen for a bit.",
    "Take a breath and unwind.",
    "A gentle pause.",
]


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


# ------------------ BREAK CONFIG PANEL ------------------

class BreakConfigPanel(ctk.CTkFrame):
    """Modern UI panel for configuring a single break with collapsible support."""

    def __init__(self, parent, config, on_test):
        super().__init__(
            parent,
            corner_radius=CORNER_RADIUS_PANEL,
            fg_color=COLORS['surface_card']
        )
        self.config = config
        self.on_test = on_test
        self._expanded = True

        # Animation state
        self._animating = False
        self._animation_id = None
        self._expanded_height = None  # Set after UI is built
        self._collapsed_height = PANEL_COLLAPSED_HEIGHT

        self._build_ui()

    def _build_ui(self):
        # Header (always visible) - clickable to toggle expand/collapse
        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.pack(fill="x", padx=PADDING_PANEL_X, pady=(PADDING_PANEL_Y // 2, 0))

        # Left side: break name
        self.header_label = ctk.CTkLabel(
            self.header_frame,
            text=self.config.name.get(),
            font=make_font('body', weight="bold"),
            cursor="hand2"
        )
        self.header_label.pack(side="left")

        # Right side: timer + chevron (for collapsed view quick info)
        header_right = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        header_right.pack(side="right")

        # Timer in header (visible when collapsed)
        self.header_timer = ctk.CTkLabel(
            header_right, text="--:--",
            font=make_font('body', weight="bold")
        )
        self.header_timer.pack(side="left", padx=(0, SPACE_MD))
        self.header_timer.pack_forget()  # Hidden by default (shown when collapsed)

        # Chevron indicator (always on far right)
        self.chevron = ctk.CTkLabel(
            header_right,
            text="\u25B2",  # Up arrow when expanded
            font=make_font('label'),
            text_color=COLORS['text_secondary'],
            cursor="hand2"
        )
        self.chevron.pack(side="right")

        # Make header clickable (mouse)
        for widget in [self.header_frame, self.header_label, self.chevron]:
            widget.bind("<Button-1>", lambda e: self.toggle_expand())

        # Keyboard accessibility: Space/Enter to toggle
        self.header_frame.bind("<Return>", lambda e: self.toggle_expand())
        self.header_frame.bind("<space>", lambda e: self.toggle_expand())

        # Content frame (hidden when collapsed)
        self.content_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.content_frame.pack(fill="x", padx=0, pady=0)

        # Row 1: Interval and Duration
        row1 = ctk.CTkFrame(self.content_frame, fg_color="transparent")
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
        row2 = ctk.CTkFrame(self.content_frame, fg_color="transparent")
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
        row3 = ctk.CTkFrame(self.content_frame, fg_color="transparent")
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

        # Measure and store expanded height after UI is built
        self.update_idletasks()
        self._expanded_height = self.winfo_reqheight()

    def toggle_expand(self):
        """Toggle between expanded and collapsed states."""
        if self._expanded:
            self.collapse()
        else:
            self.expand()

    def expand(self):
        """Expand the panel to show full configuration."""
        if self._expanded:
            return

        # Cancel any running animation
        if self._animation_id:
            self.after_cancel(self._animation_id)
            self._animation_id = None

        self._expanded = True
        self._animating = True

        # Show content first (needed for height calculation and animation)
        self.content_frame.pack(fill="x", padx=0, pady=0)
        self.header_timer.pack_forget()
        self.chevron.configure(text="\u25B2")  # Up arrow
        self.header_frame.pack_configure(pady=(PADDING_PANEL_Y // 2, 0))

        # Get target height
        target_height = self._expanded_height or self.winfo_reqheight()

        def on_complete():
            self._animating = False
            # Re-enable pack propagation for natural sizing
            self.pack_propagate(True)

        self._animate_height(
            self._collapsed_height,
            target_height,
            ANIMATION_EXPAND_DURATION,
            on_complete
        )

    def focus_config(self):
        """Expand (if collapsed) and put keyboard focus in the interval field."""
        if not self._expanded:
            self.expand()
        self.interval_entry.focus_set()

    def collapse(self):
        """Collapse the panel to show only header with timer and test button."""
        if not self._expanded:
            return

        # Cancel any running animation
        if self._animation_id:
            self.after_cancel(self._animation_id)
            self._animation_id = None

        self._expanded = False
        self._animating = True

        # Get current height for smooth animation
        current_height = self.winfo_height()
        if current_height <= 1:
            current_height = self._expanded_height or 200

        def on_complete():
            self._animating = False
            self.content_frame.pack_forget()
            self.header_timer.pack(side="left", padx=(0, SPACE_MD))
            self.chevron.configure(text="\u25BC")  # Down arrow
            self.header_frame.pack_configure(pady=(PADDING_PANEL_Y // 2, PADDING_PANEL_Y // 2))

        self._animate_height(
            current_height,
            self._collapsed_height,
            ANIMATION_COLLAPSE_DURATION,
            on_complete
        )

    def is_expanded(self):
        """Return whether the panel is currently expanded."""
        return self._expanded

    def update_header_timer(self, time_text):
        """Update the header timer display (for collapsed state)."""
        self.header_timer.configure(text=time_text)

    def _animate_height(self, start_height, end_height, duration, on_complete):
        """Frame-by-frame height animation with easing."""
        if prefers_reduced_motion():
            self.configure(height=end_height)
            self.pack_propagate(False)
            on_complete()
            return

        total_frames = max(1, duration // ANIMATION_FRAME_INTERVAL)
        frame = [0]  # Use list to allow modification in nested function

        def step():
            if frame[0] >= total_frames:
                self.configure(height=end_height)
                self._animation_id = None
                on_complete()
                return

            progress = frame[0] / total_frames
            eased = ease_out_quad(progress)
            height = int(start_height + (end_height - start_height) * eased)
            self.configure(height=height)
            frame[0] += 1
            self._animation_id = self.after(ANIMATION_FRAME_INTERVAL, step)

        self.pack_propagate(False)  # Enable explicit height control
        step()


# ------------------ MAIN APP ------------------

class BreakApp:
    def __init__(self, root):
        self.root = root
        root.title(APP_NAME)
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
        self._held = None      # reason the due break is currently held (transparency)
        self._fullscreen_grace = 0  # ticks of fullscreen hysteresis left (#46)
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
        # Whether bare mouse movement counts as activity for wait-until-you-pause
        # (default off — typing/clicks/scroll count, cursor nudges don't) (#41).
        self.count_mouse_move = ctk.BooleanVar(
            value=self.saved_prefs.get("count_mouse_move", False))
        self.count_mouse_move.trace_add('write', self._save_preferences)

        # Default snooze length (seconds), remembered from the ▾ picker.
        # Migrates an old minutes-based pref (×60) so existing configs still load.
        self.snooze_seconds = ctk.IntVar(
            value=self.saved_prefs.get(
                "snooze_seconds",
                self.saved_prefs.get("snooze_minutes", DEFAULT_SNOOZE_SECONDS // 60) * 60)
        )

        self.popup_placement = ctk.StringVar(
            value=self.saved_prefs.get("popup_placement", "active")
        )
        self.popup_placement.trace_add('write', self._save_preferences)

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
        self._schedule_update_check()

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

        # Filled-grey secondary (not a bordered ghost) so enabled/disabled reads
        # consistently in both themes — the dark border was near-invisible.
        self.reset_btn = ctk.CTkButton(
            controls, text="Reset", command=self.reset,
            height=BUTTON_HEIGHT_LARGE, corner_radius=CORNER_RADIUS_BUTTON,
            fg_color=COLORS['surface_hover'], hover_color=COLORS['border'],
            text_color=COLORS['text_secondary'], font=make_font('subheading'),
            state="disabled")
        self.reset_btn.pack(side="left", padx=(SPACE_XXS, 0), expand=True, fill="x")

        # ---- Break rows: icon · name/interval · countdown/Break now ----
        self._timer_labels = []
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

            # Right cluster: the countdown, with a quiet "take this break now"
            # button grouped immediately to its left (#5). The countdown is the
            # rightmost element; the play button sits tight against it, not adrift
            # in the middle.
            timer_label = ctk.CTkLabel(row, text="--:--", font=make_font('row_countdown'), anchor="e")
            timer_label.pack(side="right")
            play_btn = ctk.CTkButton(
                row, text="", image=load_icon('play', size=PLAY_GLYPH_SIZE),
                command=lambda c=config: self.break_now(c), anchor="e",
                width=PLAY_BTN_WIDTH, height=26, corner_radius=CORNER_RADIUS_INPUT,
                fg_color="transparent", hover_color=COLORS['surface_hover'])
            play_btn.pack(side="right", padx=(0, SPACE_XXS))
            self._register_tooltip(play_btn, "Break now")

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

            # Double-click a row → configure this break (#43)
            for widget in (card, row, meta, name_label, timer_label, interval_label):
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

        ctk.CTkButton(
            bottom_frame,
            text="Feedback",
            command=self._open_feedback,
            width=65,
            height=22,
            corner_radius=6,
            fg_color="transparent",
            hover_color=COLORS['surface_hover'],
            text_color=COLORS['text_tertiary'],
            font=make_font('caption')
        ).pack(side="right")

        # Version label
        ctk.CTkLabel(
            bottom_frame,
            text=f"v{get_current_version()}",
            font=make_font('caption'),
            text_color=COLORS['text_tertiary']
        ).pack(side="right", padx=(0, SPACE_XXS))

        # Bind keyboard shortcuts
        self.root.bind('<Command-s>', lambda e: self._handle_toggle())
        self.root.bind('<Command-comma>', lambda e: self._open_settings())
        self.root.bind('<Command-period>', lambda e: self.reset() if self.running else None)

        # Start UI update loop
        self.update_ui()

    def _fit_window_to_content(self):
        """Size the window to fit its content, then lock the size."""
        self.root.update_idletasks()
        w = self.root.winfo_reqwidth()
        h = self.root.winfo_reqheight()
        if self._saved_position:
            self.root.geometry(f"{w}x{h}{self._saved_position}")
        else:
            self.root.geometry(f"{w}x{h}")

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
            "defer_while_active": self.defer_while_active.get(),
            "activity_pause_seconds": self.activity_pause_seconds.get(),
            "count_mouse_move": self.count_mouse_move.get(),
            "snooze_seconds": self.snooze_seconds.get(),
            "last_update_check": self.saved_prefs.get("last_update_check", 0),
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

    def _on_close(self):
        """Handle window close."""
        self._save_preferences(include_geometry=True)
        self.root.destroy()

    # ------------------ UPDATE CHECKER ------------------

    def _should_check_for_updates(self):
        """Return True if enough time has passed since the last update check."""
        if not self.check_for_updates.get():
            logging.debug("Update check disabled by user preference")
            return False
        last_check = self.saved_prefs.get("last_update_check", 0)
        hours_since = (time.time() - last_check) / 3600
        should_check = hours_since >= UPDATE_CHECK_INTERVAL_HOURS
        logging.debug(f"Update check: last={last_check}, hours_since={hours_since:.1f}, should_check={should_check}")
        return should_check

    def _schedule_update_check(self):
        """Start a background update check if due."""
        if self._should_check_for_updates():
            logging.debug("Starting background update check thread")
            thread = threading.Thread(target=self._check_for_updates_bg, daemon=True)
            thread.start()
        # Re-check eligibility every hour for long-running sessions
        self.root.after(3600 * 1000, self._schedule_update_check)

    def _check_for_updates_bg(self):
        """Background thread: fetch latest version and notify UI."""
        try:
            result = fetch_latest_version()
            current_version = get_current_version()
            logging.debug(f"Update check: current={current_version}, latest={result}")
            # Update last check timestamp regardless of result
            self.saved_prefs["last_update_check"] = time.time()
            self.root.after(0, lambda: self._save_preferences())
            if result:
                latest_version, release_url = result
                newer = is_newer_version(latest_version, current_version)
                logging.debug(f"Is newer: {newer} ({latest_version} > {current_version})")
                if newer:
                    self.available_update = (latest_version, release_url)
                    self.root.after(0, lambda: self._show_update_banner(latest_version))
        except Exception as e:
            logging.error(f"Update check failed: {e}", exc_info=True)

    def _show_update_banner(self, version):
        """Show the update available label in the main UI."""
        self.update_label.configure(text=f"v{version} available — Update")
        self.update_label.pack(side="left")
        # Temporarily allow resize so the window can adjust to fit the new label
        self.root.resizable(True, True)
        self._fit_window_to_content()
        self.root.resizable(False, False)

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
        """Launch Homebrew upgrade in the default terminal."""
        upgrade_cmd = f"brew upgrade --cask {HOMEBREW_CASK_NAME}"
        if sys.platform == "darwin":
            # Open Terminal.app with the upgrade command
            script = (
                f'tell application "Terminal"\n'
                f'    activate\n'
                f'    do script "{upgrade_cmd}"\n'
                f'end tell'
            )
            subprocess.Popen(["osascript", "-e", script])
        else:
            # Fallback: just open the releases page
            webbrowser.open(self.available_update[1])

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
        self._held = None      # reset the held-reason each session
        self._fullscreen_grace = 0  # reset fullscreen hysteresis each session (#46)

        for config in self.breaks:
            config.reset_timer()

        self._render_status()
        self.toggle_btn.configure(
            text="Pause",
            fg_color=COLORS['accent_warning'],
            hover_color=COLORS['accent_warning_hover']
        )
        self.reset_btn.configure(state="normal")

        # New generation so any not-yet-exited thread from a prior session stops.
        self._timer_generation += 1
        threading.Thread(
            target=self.timer_loop, args=(self._timer_generation,), daemon=True
        ).start()

    def toggle_pause(self):
        if not self.running:
            return
        if self.paused:
            self.paused = False
            self.toggle_btn.configure(
                text="Pause",
                fg_color=COLORS['accent_warning'],
                hover_color=COLORS['accent_warning_hover']
            )
            self._render_status()
        else:
            self.paused = True
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
        self.reset_btn.configure(state="disabled")

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
        # Build hidden, then size to content and show — avoids a flash at the
        # wrong size and guarantees added settings are never clipped.
        self._settings_window.withdraw()

        def on_settings_close():
            self._settings_window.withdraw()

        self._settings_window.protocol("WM_DELETE_WINDOW", on_settings_close)
        self._settings_window.bind('<Escape>', lambda e: on_settings_close())

        # Container
        container = ctk.CTkFrame(self._settings_window, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=PADDING_WINDOW, pady=PADDING_WINDOW)

        # Reuse existing BreakConfigPanel class
        self._settings_panels = []
        for config in self.breaks:
            panel = BreakConfigPanel(container, config, self.test_break)
            panel.pack(fill="x", pady=(0, ROW_SPACING))
            self._settings_panels.append(panel)

        # General settings
        general_frame = ctk.CTkFrame(container, corner_radius=CORNER_RADIUS_PANEL, fg_color=COLORS['surface_card'])
        general_frame.pack(fill="x", pady=(ROW_SPACING, 0))

        ctk.CTkCheckBox(
            general_frame, text="Always on top",
            variable=self.always_on_top,
            font=make_font('label')
        ).pack(padx=PADDING_PANEL_X, pady=(PADDING_PANEL_Y, SPACE_XXS), anchor="w")

        ctk.CTkCheckBox(
            general_frame, text="Check for updates automatically",
            variable=self.check_for_updates,
            font=make_font('label')
        ).pack(padx=PADDING_PANEL_X, pady=(SPACE_XXS, SPACE_XXS), anchor="w")

        ctk.CTkCheckBox(
            general_frame, text="Pause breaks while microphone is in use",
            variable=self.defer_during_meetings,
            font=make_font('label')
        ).pack(padx=PADDING_PANEL_X, pady=(SPACE_XXS, SPACE_XXS), anchor="w")

        ctk.CTkCheckBox(
            general_frame, text="Pause breaks during fullscreen",
            variable=self.defer_during_fullscreen,
            font=make_font('label')
        ).pack(padx=PADDING_PANEL_X, pady=(SPACE_XXS, SPACE_XXS), anchor="w")

        ctk.CTkCheckBox(
            general_frame, text="Wait until you pause (typing or clicking)",
            variable=self.defer_while_active,
            font=make_font('label')
        ).pack(padx=PADDING_PANEL_X, pady=(SPACE_XXS, SPACE_XXS), anchor="w")

        ctk.CTkCheckBox(
            general_frame, text="↳ also count mouse movement",
            variable=self.count_mouse_move,
            font=make_font('label'),
            text_color=COLORS['text_secondary']
        ).pack(padx=(PADDING_PANEL_X + ROW_SPACING, PADDING_PANEL_X),
               pady=(0, SPACE_XXS), anchor="w")

        pause_row = ctk.CTkFrame(general_frame, fg_color="transparent")
        pause_row.pack(padx=(PADDING_PANEL_X + ROW_SPACING, PADDING_PANEL_X),
                       pady=(0, SPACE_XXS), anchor="w", fill="x")
        pause_value_label = ctk.CTkLabel(
            pause_row, text=f"↳ Pause length: {self.activity_pause_seconds.get()} sec",
            font=make_font('label'),
            text_color=COLORS['text_secondary']
        )
        pause_value_label.pack(side="left")

        def _on_pause(value):
            secs = int(round(value))
            self.activity_pause_seconds.set(secs)
            pause_value_label.configure(text=f"↳ Pause length: {secs} sec")

        pause_slider = ctk.CTkSlider(
            pause_row, from_=ACTIVITY_PAUSE_MIN, to=ACTIVITY_PAUSE_MAX,
            number_of_steps=ACTIVITY_PAUSE_MAX - ACTIVITY_PAUSE_MIN, command=_on_pause
        )
        pause_slider.set(self.activity_pause_seconds.get())
        pause_slider.pack(side="right")

        placement_row = ctk.CTkFrame(general_frame, fg_color="transparent")
        placement_row.pack(padx=PADDING_PANEL_X, pady=(SPACE_XXS, PADDING_PANEL_Y),
                           anchor="w", fill="x")
        ctk.CTkLabel(
            placement_row, text="Break popup appears on",
            font=make_font('label')
        ).pack(side="left")
        value_to_label = {v: k for k, v in POPUP_PLACEMENT_LABELS.items()}

        def _on_placement(label):
            self.popup_placement.set(POPUP_PLACEMENT_LABELS[label])

        placement_menu = ctk.CTkOptionMenu(
            placement_row, values=list(POPUP_PLACEMENT_LABELS.keys()),
            command=_on_placement,
            font=make_font('label')
        )
        placement_menu.set(value_to_label.get(self.popup_placement.get(), "Active screen"))
        placement_menu.pack(side="right")

        # Size the window to fit its content (so added settings never clip),
        # capped at the screen height; center on the main window, then show.
        self._settings_window.update_idletasks()
        max_height = int(self._settings_window.winfo_screenheight()
                         * SETTINGS_WINDOW_MAX_HEIGHT_RATIO)
        height = min(self._settings_window.winfo_reqheight(), max_height)
        main_x = self.root.winfo_x()
        main_y = self.root.winfo_y()
        main_w = self.root.winfo_width()
        x = main_x + (main_w - SETTINGS_WINDOW_WIDTH) // 2
        y = main_y - SETTINGS_WINDOW_Y_OFFSET
        self._settings_window.geometry(f"{SETTINGS_WINDOW_WIDTH}x{height}+{x}+{y}")
        self._settings_window.deiconify()
        self._settings_window.lift()
        self._settings_window.focus_force()
        self._focus_settings_panel(focus_config)

    def _focus_settings_panel(self, config):
        """Focus the settings panel that edits the given break (by identity)."""
        if config is None:
            return
        for panel in self._settings_panels:
            if panel.config is config:
                panel.focus_config()
                break

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
            if self.paused or self.active_popup:
                continue

            try:
                ctx = read_context(
                    check_meeting=self.defer_during_meetings.get(),
                    check_fullscreen=self.defer_during_fullscreen.get(),
                    count_mouse_move=self.count_mouse_move.get(),
                )
                # Bridge transient fullscreen dropouts (e.g. Space-to-Space
                # swipes) so a due break doesn't fire behind a fullscreen app (#46).
                effective_fullscreen, self._fullscreen_grace = smooth_fullscreen(
                    ctx.is_fullscreen, self._fullscreen_grace)
                ctx = dataclass_replace(ctx, is_fullscreen=effective_fullscreen)
                states = states_from_configs(self.breaks)
                pause = (self.activity_pause_seconds.get()
                         if self.defer_while_active.get() else 0)
                new_remaining, fire_index, events, self._episode = advance(
                    states, ctx, self._episode, pause_threshold=pause
                )
                for config, remaining in zip(self.breaks, new_remaining):
                    config.remaining = remaining
                for event_type, data in events:
                    self._record_event(event_type, **data)
                held_reason, self._held = track_held(
                    events, fire_index is not None, self._held)
                if fire_index is not None:
                    logging.info(
                        "break due, firing: %s (idle=%.0fs fullscreen=%s meeting=%s held=%s)",
                        self.breaks[fire_index].name.get(),
                        ctx.idle_seconds,
                        ctx.is_fullscreen,
                        ctx.is_meeting,
                        held_reason,
                    )
                    self.trigger_break(self.breaks[fire_index], held_reason=held_reason)
            except Exception as e:
                logging.error(f"timer_loop tick failed: {e}", exc_info=True)

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
            entry = {"name": break_data['name'],
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
        pause = (self.activity_pause_seconds.get()
                 if self.defer_while_active.get() else 0)
        if should_hold_snooze(self.paused, decide(ctx, pause_threshold=pause) == DEFER):
            # Not a good moment (paused or context-deferred) — wait and re-check.
            logging.info("snoozed break held (paused=%s fullscreen=%s meeting=%s), re-checking",
                         self.paused, ctx.is_fullscreen, ctx.is_meeting)
            after_id = self.root.after(SNOOZE_RECHECK_MS,
                                       lambda: self._requeue_break(break_data, entry))
            if entry is not None:
                entry["after_id"] = after_id
            return
        if entry is not None and entry in self._pending_snoozes:
            self._pending_snoozes.remove(entry)
        self._record_event(BREAK_SNOOZE_RETURNED, name=break_data['name'])
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
        status_label = ctk.CTkLabel(
            row, text=status,
            font=make_font('caption'),
            text_color=COLORS['text_secondary'])
        status_label.pack(side="right", padx=(0, SPACE_SM), pady=SPACE_SM)
        return {"frame": row, "status": status_label}

    def _render_snooze_rows(self, now):
        entries = self._pending_snoozes
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
            self._tip_lbl = ctk.CTkLabel(
                self.root, text="", font=make_font('caption'), height=22,
                corner_radius=CORNER_RADIUS_INPUT)
        self._tip_lbl.configure(text=f"  {text}  ")   # breathing room around the text
        self._tip_lbl.update_idletasks()
        w, h = self._tip_lbl.winfo_reqwidth(), self._tip_lbl.winfo_reqheight()
        bx = widget.winfo_rootx() - self.root.winfo_rootx() + widget.winfo_width() // 2
        by = widget.winfo_rooty() - self.root.winfo_rooty()
        self._tip_lbl.place(x=max(SPACE_XXS, bx - w // 2), y=by - h - SPACE_XXS)
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
        """Fade the chip from the card background (alpha 0, invisible) to full."""
        mode = ctk.get_appearance_mode()
        base = resolve_color(COLORS['surface_card'], mode)
        self._tip_lbl.configure(
            fg_color=lerp_color(base, resolve_color(COLORS['surface_hover'], mode), alpha),
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
        view = compute_status(
            running=self.running, paused=self.paused, held_reason=self._held,
            next_name=next_name, next_remaining=next_remaining,
            next_interval=next_interval, break_active=self.active_popup is not None)
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
        for i, config in enumerate(self.breaks):
            time_text = self._format_time(config.remaining)
            if i < len(self._timer_labels):
                self._timer_labels[i].configure(text=time_text)
            if i < len(self._interval_labels):
                self._interval_labels[i].configure(text=self._row_subtitle(config))
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

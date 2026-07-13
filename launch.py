import customtkinter as ctk
import tkinter as tk
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
from dfyb.breaks.duration import to_seconds
from dfyb.sound import play_sound, looping_sound, SOUNDS
from dfyb.updater import (
    get_current_version,
    fetch_latest_version,
    is_installed_via_homebrew,
    VERSION_FILE,
    HOMEBREW_CASK_NAME,
)
from dfyb.animation import ease_out_quad, prefers_reduced_motion, lerp_color
from dfyb.activity.event_log import EventLog, BREAK_TAKEN, BREAK_SNOOZED
from dfyb.activity.sensors import read_context, frontmost_window_rect, smooth_fullscreen
from dfyb.popup_placement import screen_for_point, center_on_screen, clamp_onscreen
from dfyb.scheduler.adapter import states_from_configs
from dfyb.scheduler.tick import advance
from dfyb.scheduler.engine import decide, DEFER
from dfyb.timer_lifecycle import timer_should_continue
from dfyb.macos_window import pin_to_active_space
from dfyb.insights.transparency import track_held, held_message, holding_cue
from dfyb.insights.over_break import format_over_time
from dfyb.snooze import snooze_delay_ms

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

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

# Design constants
FONT_FAMILY = "SF Pro Display" if sys.platform == "darwin" else "Segoe UI"

# Typography sizes
FONT_SIZES = {
    'title': 15,
    'status': 13,
    'label': 12,
    'input': 13,
    'timer': 13,
    'helper': 10,
    'control': 14,
    'message': 16,
}

# Colors (dark mode)
COLORS = {
    'bg_panel': "#2C2C2E",
    'bg_hover': "#3A3A3C",
    'border': "#3A3A3C",
    'accent_blue': "#0A84FF",
    'accent_hover': "#0077ED",
    'accent_green': "#30D158",
    'accent_orange': "#FF9F0A",
    'accent_orange_hover': "#E8900A",
    'text_secondary': "gray60",
}

# Spacing
PADDING_WINDOW = 16
PADDING_PANEL_X = 16
PADDING_PANEL_Y = 16
ROW_SPACING = 10

# Corner radii
CORNER_RADIUS_PANEL = 10
CORNER_RADIUS_BUTTON = 8
CORNER_RADIUS_INPUT = 6

# Button dimensions
BUTTON_HEIGHT_LARGE = 38   # Control buttons (Start/Reset/Pause)
BUTTON_HEIGHT_SMALL = 28   # Test, play buttons
BUTTON_MIN_WIDTH = 80      # Minimum touch target

# Collapsible panel settings
PANEL_COLLAPSED_HEIGHT = 48      # Height of collapsed panel header

# Settings window
SETTINGS_WINDOW_WIDTH = 600             # px; height auto-fits the content
SETTINGS_WINDOW_MAX_HEIGHT_RATIO = 0.9  # cap auto-height at 90% of screen height
SETTINGS_WINDOW_Y_OFFSET = 80           # px the window sits above the main window

# Break popup
POPUP_WIDTH = 380
POPUP_HEIGHT = 300
# Activity-pause deferral (#34) slider bounds
ACTIVITY_PAUSE_MIN = 2
ACTIVITY_PAUSE_MAX = 15
ACTIVITY_PAUSE_DEFAULT = 2   # seconds of stillness before a due break fires
SNOOZE_RECHECK_MS = 5000     # while a snoozed break is context-deferred, re-check this often
CONFIG_COMMIT_DEBOUNCE_MS = 800  # wait this long after the last keystroke before applying a typed interval/duration
BREAK_OVER_TEXT = "Break over ✓"       # big popup label once a break's duration elapses
OVER_BREAK_SUFFIX = "over your break"  # trails the +MM:SS over-breaking count-up
SNOOZE_OPTIONS_MINUTES = [5, 10, 15, 30]  # snooze durations offered on the popup ▾ menu
DEFAULT_SNOOZE_MINUTES = 5                 # default snooze length (persisted as snooze_minutes)
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
                 loop_end_sound=False, auto_dismiss=True):
        self.name = ctk.StringVar(value=name)
        self.interval_value = ctk.StringVar(value=str(interval_val))
        self.interval_unit = ctk.StringVar(value=interval_unit)
        self.duration_value = ctk.StringVar(value=str(duration_val))
        self.duration_unit = ctk.StringVar(value=duration_unit)
        self.start_sound = ctk.StringVar(value=start_sound)
        self.end_sound = ctk.StringVar(value=end_sound)
        self.loop_end_sound = ctk.BooleanVar(value=loop_end_sound)
        self.auto_dismiss = ctk.BooleanVar(value=auto_dismiss)
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
                 auto_dismiss=True, on_close=None, on_snooze=None,
                 end_sound=None, loop_end_sound=False, placement="active",
                 target_screen=None, held_reason=None,
                 snooze_minutes=DEFAULT_SNOOZE_MINUTES):
        self.parent = parent
        self.placement = placement
        self.target_screen = target_screen
        self.held_reason = held_reason
        self.snooze_minutes = snooze_minutes
        self.duration = duration
        self.remaining = duration
        self.auto_dismiss = auto_dismiss
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

        # Position the popup on the chosen screen (per the placement pref).
        self.window.update_idletasks()
        self._position_popup()

        # Glassmorphism + a gentle entrance fade on macOS (respects reduced-motion).
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
            fg_color=COLORS['bg_panel']
        )
        container.pack(fill="both", expand=True, padx=0, pady=0)

        # Title
        title_label = ctk.CTkLabel(
            container,
            text=title,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['title'], weight="bold")
        )
        title_label.pack(pady=(PADDING_PANEL_Y, 5))

        # "Waited while you were …" line when the break was held (transparency).
        if self.held_reason:
            held_text = held_message(self.held_reason)
            if held_text:
                ctk.CTkLabel(
                    container, text=held_text,
                    font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['helper']),
                    text_color=COLORS['text_secondary']
                ).pack(pady=(0, 6))

        # Message
        msg_label = ctk.CTkLabel(
            container,
            text=message,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['message'])
        )
        msg_label.pack(pady=(0, ROW_SPACING))

        # Countdown label - large and prominent
        self.countdown_label = ctk.CTkLabel(
            container,
            text=self._format_time(self.remaining),
            font=ctk.CTkFont(family=FONT_FAMILY, size=48, weight="bold")
        )
        self.countdown_label.pack(pady=10)

        # Amber count-up shown only when a break runs past its duration (#33).
        self.over_label = ctk.CTkLabel(
            container, text="",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['helper']),
            text_color=COLORS['accent_orange']
        )
        # not packed yet — revealed by update_countdown once over the duration

        # Progress bar
        self.progress = ctk.CTkProgressBar(
            container,
            height=8,
            corner_radius=4,
            progress_color=COLORS['accent_blue']
        )
        self.progress.pack(fill="x", padx=30, pady=ROW_SPACING)
        self.progress.set(1.0)  # Start full

        # Button frame
        btn_frame = ctk.CTkFrame(container, fg_color="transparent")
        btn_frame.pack(pady=ROW_SPACING)

        # Snooze split control (only if not auto-dismiss): main = snooze for the
        # current default, ▾ = pick another duration (which becomes the default).
        if not auto_dismiss:
            snooze_group = ctk.CTkFrame(btn_frame, fg_color="transparent")
            snooze_group.pack(side="left", padx=8)

            self.snooze_btn = ctk.CTkButton(
                snooze_group,
                text=f"Snooze {self.snooze_minutes}m",
                command=self.snooze,
                width=104,
                height=40,
                corner_radius=CORNER_RADIUS_BUTTON,
                fg_color="transparent",
                border_width=1,
                border_color=COLORS['border'],
                hover_color=COLORS['bg_hover'],
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['input'])
            )
            self.snooze_btn.pack(side="left")

            self.snooze_menu_btn = ctk.CTkButton(
                snooze_group,
                text="▾",
                command=self._open_snooze_menu,
                width=28,
                height=40,
                corner_radius=CORNER_RADIUS_BUTTON,
                fg_color="transparent",
                border_width=1,
                border_color=COLORS['border'],
                hover_color=COLORS['bg_hover'],
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['input'])
            )
            self.snooze_menu_btn.pack(side="left", padx=(4, 0))

        # Done button - primary style
        self.ok_btn = ctk.CTkButton(
            btn_frame,
            text="Done",
            command=self.close,
            width=130,
            height=40,
            corner_radius=CORNER_RADIUS_BUTTON,
            fg_color=COLORS['accent_blue'],
            hover_color=COLORS['accent_hover'],
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['input'], weight="bold")
        )
        self.ok_btn.pack(side="left", padx=8)

        # Handle window close
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        # Start countdown and keep-on-top mechanism
        self.update_countdown()
        self._update_progress_smooth()
        self._keep_on_top()

    def _format_time(self, seconds):
        """Format seconds as MM:SS or just Xs for short durations."""
        if seconds < 60:
            return f"{seconds}s"
        m, s = divmod(seconds, 60)
        return f"{m:02}:{s:02}"

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
            self.countdown_label.configure(text=BREAK_OVER_TEXT)
            self._bring_to_attention()

        # auto-dismiss off: count up the time spent over the break (#33).
        over_seconds = -self.remaining
        if over_seconds >= 1:
            self.over_label.configure(
                text=f"{format_over_time(over_seconds)} {OVER_BREAK_SUFFIX}")
            if self.over_label.winfo_manager() != "pack":
                self.over_label.pack(after=self.countdown_label, pady=(0, ROW_SPACING))
        self.window.after(1000, self.update_countdown)

    def _update_progress_smooth(self):
        """Smooth progress bar update (runs every 50ms for fluid animation)."""
        if self.closed:
            return

        try:
            elapsed = time.time() - self._start_time
            progress_value = max(0, 1 - (elapsed / self.duration)) if self.duration > 0 else 0
            self.progress.set(progress_value)
            self.progress.configure(progress_color=lerp_color(
                COLORS['accent_blue'], COLORS['accent_green'], 1 - progress_value))
        except Exception:
            pass

        if self.remaining > 0:
            self.window.after(50, self._update_progress_smooth)

    def snooze(self, minutes=None):
        """Snooze the break; `minutes` defaults to the current default."""
        if self.closed or self.snoozed:
            return
        chosen = self.snooze_minutes if minutes is None else minutes
        self.snoozed = True
        self.sound_stop_event.set()
        if self.on_snooze:
            self.on_snooze(chosen)
        self.closed = True
        self._dismiss()

    def _open_snooze_menu(self):
        """Pop a small menu of snooze durations under the ▾ button."""
        menu = tk.Menu(self.window, tearoff=0)
        selected = tk.IntVar(value=self.snooze_minutes)
        for minutes in SNOOZE_OPTIONS_MINUTES:
            menu.add_radiobutton(
                label=f"{minutes} min", value=minutes, variable=selected,
                command=lambda m=minutes: self.snooze(m))
        menu.tk_popup(
            self.snooze_menu_btn.winfo_rootx(),
            self.snooze_menu_btn.winfo_rooty() + self.snooze_menu_btn.winfo_height())

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
        x, y = center_on_screen(screen, POPUP_WIDTH, POPUP_HEIGHT)
        x, y = clamp_onscreen(x, y, POPUP_WIDTH, POPUP_HEIGHT, screen)
        # CustomTkinter's .geometry() override mislocates cross-monitor +x+y
        # (it recomputes the position for the window's current monitor). Set the
        # raw Tk geometry with integer coords so the popup lands on the target
        # screen we chose.
        self.window.tk.call("wm", "geometry", self.window,
                            f"{POPUP_WIDTH}x{POPUP_HEIGHT}+{int(x)}+{int(y)}")

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
            flash_color = "#FF6B6B"
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
            fg_color=COLORS['bg_panel']
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
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['status'], weight="bold"),
            cursor="hand2"
        )
        self.header_label.pack(side="left")

        # Right side: timer + chevron (for collapsed view quick info)
        header_right = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        header_right.pack(side="right")

        # Timer in header (visible when collapsed)
        self.header_timer = ctk.CTkLabel(
            header_right, text="--:--",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['timer'], weight="bold")
        )
        self.header_timer.pack(side="left", padx=(0, 12))
        self.header_timer.pack_forget()  # Hidden by default (shown when collapsed)

        # Chevron indicator (always on far right)
        self.chevron = ctk.CTkLabel(
            header_right,
            text="\u25B2",  # Up arrow when expanded
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
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
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
        ).pack(side="left")
        self.interval_entry = ctk.CTkEntry(
            row1, width=70, height=36,
            textvariable=self.config.interval_value,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['input']),
            corner_radius=CORNER_RADIUS_INPUT
        )
        self.interval_entry.pack(side="left", padx=(8, 4))
        interval_unit = ctk.CTkComboBox(
            row1, variable=self.config.interval_unit,
            values=TIME_UNITS, width=80, height=36, state="readonly",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['input']),
            corner_radius=CORNER_RADIUS_INPUT
        )
        interval_unit.pack(side="left")

        ctk.CTkLabel(
            row1, text="Duration:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
        ).pack(side="left", padx=(24, 0))
        duration_entry = ctk.CTkEntry(
            row1, width=70, height=36,
            textvariable=self.config.duration_value,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['input']),
            corner_radius=CORNER_RADIUS_INPUT
        )
        duration_entry.pack(side="left", padx=(8, 4))
        duration_unit = ctk.CTkComboBox(
            row1, variable=self.config.duration_unit,
            values=TIME_UNITS, width=80, height=36, state="readonly",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['input']),
            corner_radius=CORNER_RADIUS_INPUT
        )
        duration_unit.pack(side="left")

        # Row 2: Sounds
        row2 = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        row2.pack(fill="x", padx=PADDING_PANEL_X, pady=(0, ROW_SPACING))

        ctk.CTkLabel(
            row2, text="Start:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
        ).pack(side="left")
        start_sound = ctk.CTkComboBox(
            row2, variable=self.config.start_sound,
            values=list(SOUNDS.keys()), width=130, height=36, state="readonly",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['input']),
            corner_radius=CORNER_RADIUS_INPUT
        )
        start_sound.pack(side="left", padx=(8, 4))
        ctk.CTkButton(
            row2, text="Play", width=40, height=BUTTON_HEIGHT_SMALL,
            corner_radius=CORNER_RADIUS_INPUT,
            fg_color=COLORS['bg_hover'],
            hover_color=COLORS['border'],
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['helper']),
            command=lambda: play_sound(self.config.start_sound.get())
        ).pack(side="left", padx=(0, 16))

        ctk.CTkLabel(
            row2, text="End:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
        ).pack(side="left")
        end_sound = ctk.CTkComboBox(
            row2, variable=self.config.end_sound,
            values=list(SOUNDS.keys()), width=130, height=36, state="readonly",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['input']),
            corner_radius=CORNER_RADIUS_INPUT
        )
        end_sound.pack(side="left", padx=(8, 4))
        ctk.CTkButton(
            row2, text="Play", width=40, height=BUTTON_HEIGHT_SMALL,
            corner_radius=CORNER_RADIUS_INPUT,
            fg_color=COLORS['bg_hover'],
            hover_color=COLORS['border'],
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['helper']),
            command=lambda: play_sound(self.config.end_sound.get())
        ).pack(side="left")

        # Row 3: Options and Timer
        row3 = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        row3.pack(fill="x", padx=PADDING_PANEL_X, pady=(0, PADDING_PANEL_Y))

        ctk.CTkCheckBox(
            row3, text="Loop end sound",
            variable=self.config.loop_end_sound,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
        ).pack(side="left")

        ctk.CTkCheckBox(
            row3, text="Auto-dismiss",
            variable=self.config.auto_dismiss,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
        ).pack(side="left", padx=(16, 0))

        # Test button on right
        ctk.CTkButton(
            row3, text="Test",
            command=lambda: self.on_test(self.config),
            width=60, height=BUTTON_HEIGHT_SMALL,
            corner_radius=CORNER_RADIUS_INPUT,
            fg_color="transparent",
            border_width=1,
            border_color=COLORS['border'],
            hover_color=COLORS['bg_hover'],
            text_color=COLORS['text_secondary'],
            font=ctk.CTkFont(family=FONT_FAMILY, size=12)
        ).pack(side="right")

        self.config.timer_label = ctk.CTkLabel(
            row3, text="--:--",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['timer'], weight="bold")
        )
        self.config.timer_label.pack(side="right", padx=(0, 16))

        ctk.CTkLabel(
            row3, text="Next:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label']),
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
            self.header_timer.pack(side="left", padx=(0, 12))
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
        self.active_popup = None
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
             "end_sound": "Glass", "loop_end_sound": False, "auto_dismiss": True},
            {"name": "Normal Break", "interval_val": 50, "interval_unit": "min",
             "duration_val": 10, "duration_unit": "min", "start_sound": "Glass",
             "end_sound": "Submarine", "loop_end_sound": True, "auto_dismiss": False}
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

        # Default snooze length, remembered from the popup's ▾ picker (#29)
        self.snooze_minutes = ctk.IntVar(
            value=self.saved_prefs.get("snooze_minutes", DEFAULT_SNOOZE_MINUTES)
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
                auto_dismiss=break_prefs.get("auto_dismiss", default["auto_dismiss"])
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

        # Status section
        status_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        status_frame.pack(fill="x", pady=(0, ROW_SPACING))

        self.status = ctk.CTkLabel(
            status_frame,
            text="Idle",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['title'], weight="bold"),
            text_color=COLORS['text_secondary']
        )
        self.status.pack(side="left")

        # Settings button (gear icon, top-right)
        self.settings_btn = ctk.CTkButton(
            status_frame,
            text="\u2699",
            command=self._open_settings,
            width=28, height=28,
            corner_radius=CORNER_RADIUS_INPUT,
            fg_color="transparent",
            hover_color=COLORS['bg_hover'],
            text_color=COLORS['text_secondary'],
            font=ctk.CTkFont(size=15)
        )
        self.settings_btn.pack(side="right", padx=(6, 0))

        self.next_break_label = ctk.CTkLabel(
            status_frame, text="",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['timer'], weight="bold"),
            text_color=COLORS['text_secondary']
        )
        self.next_break_label.pack(side="right")

        # Control buttons
        control_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        control_frame.pack(fill="x", pady=ROW_SPACING)

        # Toggle button (Start / Pause / Resume - primary action)
        self.toggle_btn = ctk.CTkButton(
            control_frame, text="Start",
            command=self._handle_toggle, height=BUTTON_HEIGHT_LARGE,
            corner_radius=CORNER_RADIUS_BUTTON,
            fg_color=COLORS['accent_blue'],
            hover_color=COLORS['accent_hover'],
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['control'], weight="bold")
        )
        self.toggle_btn.pack(side="left", padx=(0, 4), expand=True, fill="x")

        # Reset button (secondary - transparent with border)
        self.reset_btn = ctk.CTkButton(
            control_frame, text="Reset",
            command=self.reset, height=BUTTON_HEIGHT_LARGE,
            corner_radius=CORNER_RADIUS_BUTTON,
            fg_color="transparent",
            border_width=1,
            border_color=COLORS['border'],
            hover_color=COLORS['bg_panel'],
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['control']),
            state="disabled"
        )
        self.reset_btn.pack(side="left", padx=(4, 0), expand=True, fill="x")

        # Compact timer display cards
        self._timer_labels = []
        self._cue_labels = []
        for config in self.breaks:
            card = ctk.CTkFrame(main_frame, corner_radius=CORNER_RADIUS_PANEL, fg_color=COLORS['bg_panel'])
            card.pack(fill="x", pady=(0, 6))

            top_row = ctk.CTkFrame(card, fg_color="transparent")
            top_row.pack(fill="x")

            name_label = ctk.CTkLabel(
                top_row, text=config.name.get(),
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
            )
            name_label.pack(side="left", padx=(PADDING_PANEL_X, 0), pady=8)

            timer_label = ctk.CTkLabel(
                top_row, text="--:--",
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['timer'], weight="bold")
            )
            timer_label.pack(side="right", padx=(0, PADDING_PANEL_X), pady=8)

            # Break now button (quick manual trigger, left of the timer)
            ctk.CTkButton(
                top_row, text="Break now",
                command=lambda c=config: self.break_now(c),
                width=90, height=BUTTON_HEIGHT_SMALL,
                corner_radius=CORNER_RADIUS_INPUT,
                fg_color="transparent",
                border_width=1,
                border_color=COLORS['border'],
                hover_color=COLORS['bg_hover'],
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['helper'])
            ).pack(side="right", padx=(0, 8), pady=8)

            self._timer_labels.append(timer_label)

            # Gentle "holding" cue (#44): explains why a due break is waiting.
            # Hidden until held; shown/hidden by update_ui.
            cue_label = ctk.CTkLabel(
                card, text="", anchor="w",
                text_color=COLORS['text_secondary'],
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['helper'])
            )
            self._cue_labels.append(cue_label)

            # Double-click the card (name or countdown) jumps into this break's
            # configuration (#43). The "Break now" button keeps its own click.
            for widget in (card, top_row, name_label, timer_label):
                widget.bind("<Double-Button-1>",
                            lambda e, c=config: self._edit_break_config(c))

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
            hover_color=COLORS['bg_hover'],
            text_color=COLORS['accent_green'],
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['helper'])
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
            hover_color=COLORS['bg_hover'],
            text_color="gray50",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['helper'])
        ).pack(side="right")

        # Version label
        ctk.CTkLabel(
            bottom_frame,
            text=f"v{get_current_version()}",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['helper']),
            text_color="gray40"
        ).pack(side="right", padx=(0, 4))

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
            "snooze_minutes": self.snooze_minutes.get(),
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
                "auto_dismiss": config.auto_dismiss.get()
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

        self.status.configure(text="Working", text_color=COLORS['accent_green'])
        self.toggle_btn.configure(
            text="Pause",
            fg_color=COLORS['accent_orange'],
            hover_color=COLORS['accent_orange_hover']
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
                fg_color=COLORS['accent_orange'],
                hover_color=COLORS['accent_orange_hover']
            )
            self.status.configure(text="Working", text_color=COLORS['accent_green'])
        else:
            self.paused = True
            self.toggle_btn.configure(
                text="Resume",
                fg_color=COLORS['accent_blue'],
                hover_color=COLORS['accent_hover']
            )
            self.status.configure(text="Paused", text_color=COLORS['accent_orange'])

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

        self.status.configure(text="Idle", text_color=COLORS['text_secondary'])
        self.toggle_btn.configure(
            text="Start",
            fg_color=COLORS['accent_blue'],
            hover_color=COLORS['accent_hover']
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
        general_frame = ctk.CTkFrame(container, corner_radius=CORNER_RADIUS_PANEL, fg_color=COLORS['bg_panel'])
        general_frame.pack(fill="x", pady=(ROW_SPACING, 0))

        ctk.CTkCheckBox(
            general_frame, text="Always on top",
            variable=self.always_on_top,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
        ).pack(padx=PADDING_PANEL_X, pady=(PADDING_PANEL_Y, 4), anchor="w")

        ctk.CTkCheckBox(
            general_frame, text="Check for updates automatically",
            variable=self.check_for_updates,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
        ).pack(padx=PADDING_PANEL_X, pady=(4, 4), anchor="w")

        ctk.CTkCheckBox(
            general_frame, text="Pause breaks while microphone is in use",
            variable=self.defer_during_meetings,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
        ).pack(padx=PADDING_PANEL_X, pady=(4, 4), anchor="w")

        ctk.CTkCheckBox(
            general_frame, text="Pause breaks during fullscreen",
            variable=self.defer_during_fullscreen,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
        ).pack(padx=PADDING_PANEL_X, pady=(4, 4), anchor="w")

        ctk.CTkCheckBox(
            general_frame, text="Wait until you pause (keyboard or mouse)",
            variable=self.defer_while_active,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
        ).pack(padx=PADDING_PANEL_X, pady=(4, 4), anchor="w")

        pause_row = ctk.CTkFrame(general_frame, fg_color="transparent")
        pause_row.pack(padx=(PADDING_PANEL_X + ROW_SPACING, PADDING_PANEL_X),
                       pady=(0, 4), anchor="w", fill="x")
        pause_value_label = ctk.CTkLabel(
            pause_row, text=f"↳ Pause length: {self.activity_pause_seconds.get()} sec",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label']),
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
        placement_row.pack(padx=PADDING_PANEL_X, pady=(4, PADDING_PANEL_Y),
                           anchor="w", fill="x")
        ctk.CTkLabel(
            placement_row, text="Break popup appears on",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
        ).pack(side="left")
        value_to_label = {v: k for k, v in POPUP_PLACEMENT_LABELS.items()}

        def _on_placement(label):
            self.popup_placement.set(POPUP_PLACEMENT_LABELS[label])

        placement_menu = ctk.CTkOptionMenu(
            placement_row, values=list(POPUP_PLACEMENT_LABELS.keys()),
            command=_on_placement,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
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

    def trigger_break(self, config, held_reason=None):
        """Queue a break with the given configuration."""
        break_data = {
            'name': config.name.get(),
            'duration': config.get_duration_seconds(),
            'auto_dismiss': config.auto_dismiss.get(),
            'start_sound': config.start_sound.get(),
            'end_sound': config.end_sound.get(),
            'loop_end_sound': config.loop_end_sound.get(),
            'held_reason': held_reason,
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
            self.break_start_time = None
            if self.running and not self.paused:
                self.status.configure(text="Working", text_color=COLORS['accent_green'])
            elif not self.running:
                self.status.configure(text="Idle", text_color=COLORS['text_secondary'])
            self.root.after(0, self._process_break_queue)

        def on_snooze(snooze_minutes):
            self._record_event(BREAK_SNOOZED, name=break_data['name'], minutes=snooze_minutes)
            self.active_popup = None
            self.break_start_time = None
            if self.running and not self.paused:
                self.status.configure(text="Working", text_color=COLORS['accent_green'])
                snooze_ms = int(snooze_minutes * 60 * 1000)
                self.root.after(snooze_ms, lambda: self._requeue_break(break_data))

        self.status.configure(text=break_data['name'], text_color=COLORS['accent_orange'])
        # Capture the active screen NOW, before the popup's window steals focus.
        target_screen = (self._capture_active_screen()
                         if self.popup_placement.get() == "active" else None)
        self.active_popup = CountdownPopup(
            self.root,
            break_data['name'],
            random.choice(BREAK_MESSAGES),
            break_data['duration'],
            auto_dismiss=break_data['auto_dismiss'],
            on_close=on_popup_close,
            on_snooze=on_snooze,
            end_sound=break_data['end_sound'],
            loop_end_sound=break_data['loop_end_sound'],
            placement=self.popup_placement.get(),
            target_screen=target_screen,
            held_reason=break_data.get('held_reason'),
        )

    def _requeue_break(self, break_data):
        """Re-show a snoozed break — but respect context (defer during a
        meeting/fullscreen/away/mid-activity) like a scheduled break, instead of
        barging in unconditionally (#42)."""
        if not (self.running and not self.paused):
            return
        ctx = read_context(
            check_meeting=self.defer_during_meetings.get(),
            check_fullscreen=self.defer_during_fullscreen.get(),
        )
        pause = (self.activity_pause_seconds.get()
                 if self.defer_while_active.get() else 0)
        if decide(ctx, pause_threshold=pause) == DEFER:
            # Not a good moment — wait and re-check, don't pop over the user.
            logging.info("snoozed break held (context deferred, fullscreen=%s meeting=%s), re-checking",
                         ctx.is_fullscreen, ctx.is_meeting)
            self.root.after(SNOOZE_RECHECK_MS, lambda: self._requeue_break(break_data))
            return
        self.break_queue.append(break_data)
        self.root.after(0, self._process_break_queue)

    def test_break(self, config):
        """Test a specific break configuration."""
        self.trigger_break(config)

    def break_now(self, config):
        """Take this break immediately: reset its countdown and show the popup.

        Manual/explicit action — bypasses the scheduler's fullscreen/away
        deferral (trigger_break shows the popup directly, not via the timer loop).
        """
        config.reset_timer()
        self.trigger_break(config)
        self.update_ui()

    # ------------------ UI UPDATE ------------------

    def update_ui(self):
        """Update timer displays for all breaks."""
        next_break = None
        min_remaining = float('inf')

        for i, config in enumerate(self.breaks):
            time_text = self._format_time(config.remaining)
            if i < len(self._timer_labels):
                self._timer_labels[i].configure(text=time_text)
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
                                   padx=(PADDING_PANEL_X, 0), pady=(0, 8))
                elif label.winfo_manager() == "pack":     # currently packed → hide
                    label.pack_forget()

            if self.running and not self.paused and config.remaining < min_remaining:
                min_remaining = config.remaining
                next_break = config

        if next_break and self.running and not self.active_popup:
            self.next_break_label.configure(
                text=f"Next: {next_break.name.get()} in {self._format_time(min_remaining)}"
            )
        elif not self.running:
            self.next_break_label.configure(text="")

        self.root.after(1000, self.update_ui)

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

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
from pathlib import Path

# ------------------ CUSTOMTKINTER SETUP ------------------

ctk.set_appearance_mode("system")  # Follow system dark/light mode
ctk.set_default_color_theme("blue")  # macOS-style blue accent

# ------------------ CONFIGURATION ------------------

TIME_UNITS = ["sec", "min", "hour"]
SOUND_LOOP_INTERVAL = 1.2
CONFIG_FILE = Path.home() / "Library" / "Preferences" / "com.yairs.dontforgetyourbreaks.json"
LOCK_FILE = Path.home() / "Library" / "Application Support" / "DontForgetYourBreaks" / ".lock"

# Design constants
FONT_FAMILY = "SF Pro Display" if sys.platform == "darwin" else "Segoe UI"

# Typography sizes
FONT_SIZES = {
    'title': 20,
    'status': 16,
    'label': 13,
    'input': 14,
    'timer': 14,
    'helper': 11,
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
    'text_secondary': "gray60",
}

# Spacing
PADDING_WINDOW = 24
PADDING_PANEL_X = 28
PADDING_PANEL_Y = 24
ROW_SPACING = 16

# Corner radii
CORNER_RADIUS_PANEL = 16
CORNER_RADIUS_BUTTON = 10
CORNER_RADIUS_INPUT = 8

# Button dimensions
BUTTON_HEIGHT_LARGE = 44   # Control buttons
BUTTON_HEIGHT_SMALL = 32   # Test, play buttons
BUTTON_MIN_WIDTH = 80      # Minimum touch target

# Collapsible panel settings
PANEL_COLLAPSED_HEIGHT = 48      # Height of collapsed panel header

# Animation timing
ANIMATION_FRAME_INTERVAL = 16      # ms (60fps)
ANIMATION_EXPAND_DURATION = 250    # ms
ANIMATION_COLLAPSE_DURATION = 200  # ms

# Sound options including "None"
SOUNDS = {
    "None": None,
    "Glass": "Glass.aiff",
    "Ping": "Ping.aiff",
    "Pop": "Pop.aiff",
    "Submarine": "Submarine.aiff"
}


# ------------------ SOUND FUNCTIONS ------------------

def play_sound_mac(sound_name):
    sound_file = SOUNDS.get(sound_name)
    if sound_file:
        subprocess.Popen(
            ["afplay", f"/System/Library/Sounds/{sound_file}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )


def play_sound(sound_name="Glass"):
    if sound_name == "None" or sound_name is None:
        return
    if sys.platform == "darwin":
        play_sound_mac(sound_name)
    elif sys.platform == "win32":
        import winsound
        winsound.MessageBeep()
    else:
        print("\a")


def looping_sound(stop_event, sound_name):
    while not stop_event.is_set():
        play_sound(sound_name)
        time.sleep(SOUND_LOOP_INTERVAL)


# ------------------ ANIMATION HELPERS ------------------

def ease_out_quad(t):
    """Quadratic ease-out: fast start, slow end."""
    return t * (2 - t)


def ease_in_quad(t):
    """Quadratic ease-in: slow start, fast end."""
    return t * t


def prefers_reduced_motion():
    """Check if user has enabled reduced motion (macOS)."""
    if sys.platform != "darwin":
        return False
    try:
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleReduceMotion"],
            capture_output=True, text=True
        )
        return result.stdout.strip() == "1"
    except Exception:
        return False


# ------------------ BREAK CONFIG ------------------

class BreakConfig:
    """Configuration for a single break type."""

    def __init__(self, name, interval_val, interval_unit,
                 duration_val, duration_unit, start_sound, end_sound,
                 loop_end_sound=False, auto_dismiss=True):
        self.name = ctk.StringVar(value=name)
        self.interval_value = ctk.IntVar(value=interval_val)
        self.interval_unit = ctk.StringVar(value=interval_unit)
        self.duration_value = ctk.IntVar(value=duration_val)
        self.duration_unit = ctk.StringVar(value=duration_unit)
        self.start_sound = ctk.StringVar(value=start_sound)
        self.end_sound = ctk.StringVar(value=end_sound)
        self.loop_end_sound = ctk.BooleanVar(value=loop_end_sound)
        self.auto_dismiss = ctk.BooleanVar(value=auto_dismiss)
        self.remaining = self.get_interval_seconds()
        self.timer_label = None  # Will be set by UI

    def get_interval_seconds(self):
        """Convert interval to seconds."""
        val = self.interval_value.get()
        unit = self.interval_unit.get()
        if unit == "sec":
            return val
        elif unit == "min":
            return val * 60
        else:  # hour
            return val * 3600

    def get_duration_seconds(self):
        """Convert duration to seconds."""
        val = self.duration_value.get()
        unit = self.duration_unit.get()
        if unit == "sec":
            return val
        elif unit == "min":
            return val * 60
        else:  # hour
            return val * 3600

    def reset_timer(self):
        """Reset remaining time to interval."""
        self.remaining = self.get_interval_seconds()


# ------------------ COUNTDOWN POPUP ------------------

class CountdownPopup:
    """A modern popup with countdown timer, progress bar, glassmorphism effect."""

    SNOOZE_MINUTES = 5

    def __init__(self, parent, title, message, duration,
                 auto_dismiss=True, on_close=None, on_snooze=None,
                 end_sound=None, loop_end_sound=False):
        self.parent = parent
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
        self._previous_app = self._get_frontmost_app()  # Remember active app

        # Create popup window
        self.window = ctk.CTkToplevel(parent)
        self.window.title(title)
        self.window.resizable(False, False)

        # Make window always on top
        self.window.attributes('-topmost', True)

        # Larger popup size with modern styling
        popup_w, popup_h = 380, 300

        # Position popup at mouse cursor location (works across all monitors)
        self.window.update_idletasks()
        mouse_x = self.window.winfo_pointerx()
        mouse_y = self.window.winfo_pointery()
        x = mouse_x - popup_w // 2 + 20
        y = mouse_y - popup_h // 2 + 20
        self.window.geometry(f"{popup_w}x{popup_h}+{x}+{y}")

        # Glassmorphism effect (semi-transparent on macOS)
        if sys.platform == "darwin":
            self.window.attributes('-alpha', 0.95)

        # Force focus and request attention
        self.window.lift()
        self.window.focus_force()
        self._request_attention()

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

        # Message
        msg_label = ctk.CTkLabel(
            container,
            text=message,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['input']),
            text_color=COLORS['text_secondary']
        )
        msg_label.pack(pady=(0, ROW_SPACING))

        # Countdown label - large and prominent
        self.countdown_label = ctk.CTkLabel(
            container,
            text=self._format_time(self.remaining),
            font=ctk.CTkFont(family=FONT_FAMILY, size=48, weight="bold")
        )
        self.countdown_label.pack(pady=10)

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

        # Snooze button (only if not auto-dismiss) - secondary style
        if not auto_dismiss:
            self.snooze_btn = ctk.CTkButton(
                btn_frame,
                text=f"Snooze {self.SNOOZE_MINUTES}m",
                command=self.snooze,
                width=130,
                height=40,
                corner_radius=CORNER_RADIUS_BUTTON,
                fg_color="transparent",
                border_width=1,
                border_color=COLORS['border'],
                hover_color=COLORS['bg_hover'],
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['input'])
            )
            self.snooze_btn.pack(side="left", padx=8)

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
        self.countdown_label.configure(text=self._format_time(self.remaining))

        if self.remaining <= 0:
            # Timer finished - handle end sound
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
            else:
                self.countdown_label.configure(text="Done!")
                self._bring_to_attention()
        else:
            self.window.after(1000, self.update_countdown)

    def _update_progress_smooth(self):
        """Smooth progress bar update (runs every 50ms for fluid animation)."""
        if self.closed:
            return

        try:
            elapsed = time.time() - self._start_time
            progress_value = max(0, 1 - (elapsed / self.duration)) if self.duration > 0 else 0
            self.progress.set(progress_value)
        except Exception:
            pass

        if self.remaining > 0:
            self.window.after(50, self._update_progress_smooth)

    def snooze(self):
        """Snooze the break for a few minutes."""
        if self.closed or self.snoozed:
            return
        self.snoozed = True
        self.sound_stop_event.set()
        if self.on_snooze:
            self.on_snooze(self.SNOOZE_MINUTES)
        try:
            self.window.withdraw()
        except Exception:
            pass
        self._prevent_focus_steal()  # Call before destroy
        self.window.destroy()
        self.closed = True
        self._prevent_focus_steal()  # Call after destroy

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.sound_stop_event.set()
        if self.on_close:
            self.on_close()
        try:
            self.window.withdraw()
        except Exception:
            pass
        self._prevent_focus_steal()  # Call before destroy to prevent focus transfer
        self.window.destroy()
        self._prevent_focus_steal()  # Call again after to ensure app is deactivated

    def _get_frontmost_app(self):
        """Get the name of the currently frontmost application."""
        if sys.platform != "darwin":
            return None
        try:
            result = subprocess.run(
                ['osascript', '-e',
                 'tell application "System Events" to get name of first process whose frontmost is true'],
                capture_output=True, text=True, timeout=2
            )
            return result.stdout.strip() if result.returncode == 0 else None
        except Exception:
            return None

    def _prevent_focus_steal(self):
        """Prevent main window from stealing focus and triggering Space switch on macOS."""
        if sys.platform == "darwin":
            try:
                # Lower the parent window
                self.parent.lower()
                # Reactivate the app that was active before the popup appeared
                if self._previous_app and self._previous_app != "Python":
                    subprocess.run(
                        ['osascript', '-e',
                         f'tell application "{self._previous_app}" to activate'],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=2
                    )
            except Exception:
                pass

    def _request_attention(self):
        """Request user attention."""
        try:
            self.window.bell()
        except Exception:
            pass

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

    def bring_to_user(self):
        """Bring popup to user's current location."""
        if self.closed:
            return
        try:
            mouse_x = self.window.winfo_pointerx()
            mouse_y = self.window.winfo_pointery()
            popup_w, popup_h = 380, 300
            x = mouse_x - popup_w // 2 + 20
            y = mouse_y - popup_h // 2 + 20
            self.window.geometry(f"{popup_w}x{popup_h}+{x}+{y}")
            self.window.lift()
            self.window.focus_force()
            self.window.attributes('-topmost', True)
        except Exception:
            pass

    def _bring_to_attention(self):
        """Bring popup to user's attention when countdown ends."""
        try:
            self.window.lift()
            self.window.focus_force()
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
        interval_entry = ctk.CTkEntry(
            row1, width=70, height=36,
            textvariable=self.config.interval_value,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['input']),
            corner_radius=CORNER_RADIUS_INPUT
        )
        interval_entry.pack(side="left", padx=(8, 4))
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
        root.title("Don't Forget Your Breaks")
        root.minsize(560, 300)  # Minimum width to keep UI readable
        root.resizable(True, True)

        self.running = False
        self.paused = False
        self.stop_event = threading.Event()
        self.break_queue = []
        self.active_popup = None
        self.break_start_time = None

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

        # Restore window geometry if saved
        if "window_geometry" in self.saved_prefs:
            root.geometry(self.saved_prefs["window_geometry"])
        else:
            root.geometry("560x520")

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
        self._setup_auto_save()

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

        self.next_break_label = ctk.CTkLabel(
            status_frame, text="",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['timer'], weight="bold"),
            text_color=COLORS['text_secondary']
        )
        self.next_break_label.pack(side="right")

        # Control buttons
        control_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        control_frame.pack(fill="x", pady=ROW_SPACING)

        # Start button (primary action - blue accent)
        self.start_btn = ctk.CTkButton(
            control_frame, text="Start",
            command=self.start, height=BUTTON_HEIGHT_LARGE,
            corner_radius=CORNER_RADIUS_BUTTON,
            fg_color=COLORS['accent_blue'],
            hover_color=COLORS['accent_hover'],
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['input'], weight="bold")
        )
        self.start_btn.pack(side="left", padx=(0, 6), expand=True, fill="x")

        # Pause button (secondary - transparent with border)
        self.pause_btn = ctk.CTkButton(
            control_frame, text="Pause",
            command=self.toggle_pause, height=BUTTON_HEIGHT_LARGE,
            corner_radius=CORNER_RADIUS_BUTTON,
            fg_color="transparent",
            border_width=1,
            border_color=COLORS['border'],
            hover_color=COLORS['bg_panel'],
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['input']),
            state="disabled"
        )
        self.pause_btn.pack(side="left", padx=6, expand=True, fill="x")

        # Stop button (secondary - transparent with border)
        self.stop_btn = ctk.CTkButton(
            control_frame, text="Stop",
            command=self.stop, height=BUTTON_HEIGHT_LARGE,
            corner_radius=CORNER_RADIUS_BUTTON,
            fg_color="transparent",
            border_width=1,
            border_color=COLORS['border'],
            hover_color=COLORS['bg_panel'],
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['input']),
            state="disabled"
        )
        self.stop_btn.pack(side="left", padx=(6, 0), expand=True, fill="x")

        # Collapse/Expand all toggle
        toggle_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        toggle_frame.pack(fill="x", pady=(ROW_SPACING, 4))

        self._all_collapsed = False
        self.toggle_all_btn = ctk.CTkButton(
            toggle_frame,
            text="▼ Collapse",
            command=self._toggle_all_panels,
            width=85,
            height=24,
            corner_radius=6,
            fg_color="transparent",
            hover_color=COLORS['bg_hover'],
            text_color=COLORS['text_secondary'],
            anchor="e",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11)
        )
        self.toggle_all_btn.pack(side="right")

        # Break configuration panels
        self.panels = []
        for config in self.breaks:
            panel = BreakConfigPanel(main_frame, config, self.test_break)
            panel.pack(fill="x", pady=(0, ROW_SPACING))
            self.panels.append(panel)

        # Keyboard shortcuts hint (de-emphasized)
        shortcut_label = ctk.CTkLabel(
            main_frame,
            text="Cmd+S Start  •  Cmd+P Pause  •  Cmd+. Stop",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['helper']),
            text_color="gray50"
        )
        shortcut_label.pack(pady=(PADDING_WINDOW, 0))

        # Bind keyboard shortcuts
        self.root.bind('<Command-s>', lambda e: self.start() if not self.running else None)
        self.root.bind('<Command-p>', lambda e: self.toggle_pause() if self.running else None)
        self.root.bind('<Command-period>', lambda e: self.stop() if self.running else None)

        # Start UI update loop
        self.update_ui()

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
        prefs = {"breaks": []}
        for config in self.breaks:
            prefs["breaks"].append({
                "name": config.name.get(),
                "interval_val": config.interval_value.get(),
                "interval_unit": config.interval_unit.get(),
                "duration_val": config.duration_value.get(),
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

    def _on_main_focus(self, event=None):
        """When main window is focused, bring popup to user if active."""
        if self.active_popup and not self.active_popup.closed:
            self.active_popup.bring_to_user()

    def _setup_auto_save(self):
        """Setup auto-save when any preference changes."""
        for config in self.breaks:
            config.interval_value.trace_add('write', self._save_preferences)
            config.interval_unit.trace_add('write', self._save_preferences)
            config.duration_value.trace_add('write', self._save_preferences)
            config.duration_unit.trace_add('write', self._save_preferences)
            config.start_sound.trace_add('write', self._save_preferences)
            config.end_sound.trace_add('write', self._save_preferences)
            config.loop_end_sound.trace_add('write', self._save_preferences)
            config.auto_dismiss.trace_add('write', self._save_preferences)

    # ------------------ CONTROLS ------------------

    def start(self):
        if self.running:
            return
        self.running = True
        self.paused = False
        self.stop_event.clear()

        for config in self.breaks:
            config.reset_timer()

        self.status.configure(text="Working", text_color=COLORS['accent_green'])
        self.start_btn.configure(state="disabled")
        self.pause_btn.configure(state="normal")
        self.stop_btn.configure(state="normal")

        threading.Thread(target=self.timer_loop, daemon=True).start()

    def toggle_pause(self):
        if self.paused:
            self.paused = False
            self.pause_btn.configure(text="Pause")
            self.status.configure(text="Working", text_color=COLORS['accent_green'])
        else:
            self.paused = True
            self.pause_btn.configure(text="Resume")
            self.status.configure(text="Paused", text_color=COLORS['accent_orange'])

    def stop(self):
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
        self.start_btn.configure(state="normal")
        self.pause_btn.configure(state="disabled", text="Pause")
        self.stop_btn.configure(state="disabled")

    def _toggle_all_panels(self):
        """Toggle all panels between collapsed and expanded state."""
        if self._all_collapsed:
            for panel in self.panels:
                panel.expand()
            self._all_collapsed = False
            self.toggle_all_btn.configure(text="▼ Collapse")
        else:
            for panel in self.panels:
                panel.collapse()
            self._all_collapsed = True
            self.toggle_all_btn.configure(text="▲ Expand")

    # ------------------ TIMER ------------------

    def timer_loop(self):
        """Single timer loop managing all breaks."""
        while self.running and not self.stop_event.is_set():
            time.sleep(1)
            if self.paused or self.active_popup:
                continue

            for config in self.breaks:
                config.remaining -= 1
                if config.remaining <= 0:
                    self.trigger_break(config)
                    config.reset_timer()

    def trigger_break(self, config):
        """Queue a break with the given configuration."""
        break_data = {
            'name': config.name.get(),
            'duration': config.get_duration_seconds(),
            'auto_dismiss': config.auto_dismiss.get(),
            'start_sound': config.start_sound.get(),
            'end_sound': config.end_sound.get(),
            'loop_end_sound': config.loop_end_sound.get()
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
            for queued_break in self.break_queue:
                queued_break['duration'] -= elapsed

            self.active_popup = None
            self.break_start_time = None
            if self.running and not self.paused:
                self.status.configure(text="Working", text_color=COLORS['accent_green'])
            elif not self.running:
                self.status.configure(text="Idle", text_color=COLORS['text_secondary'])
            self.root.after(0, self._process_break_queue)

        def on_snooze(snooze_minutes):
            self.active_popup = None
            self.break_start_time = None
            if self.running and not self.paused:
                self.status.configure(text="Working", text_color=COLORS['accent_green'])
                snooze_ms = snooze_minutes * 60 * 1000
                self.root.after(snooze_ms, lambda: self._requeue_break(break_data))

        self.status.configure(text=break_data['name'], text_color=COLORS['accent_orange'])
        self.active_popup = CountdownPopup(
            self.root,
            break_data['name'],
            "Take a break!",
            break_data['duration'],
            auto_dismiss=break_data['auto_dismiss'],
            on_close=on_popup_close,
            on_snooze=on_snooze,
            end_sound=break_data['end_sound'],
            loop_end_sound=break_data['loop_end_sound']
        )

    def _requeue_break(self, break_data):
        """Re-queue a snoozed break."""
        if self.running and not self.paused:
            self.break_queue.append(break_data)
            self.root.after(0, self._process_break_queue)

    def test_break(self, config):
        """Test a specific break configuration."""
        self.trigger_break(config)

    # ------------------ UI UPDATE ------------------

    def update_ui(self):
        """Update timer displays for all breaks."""
        next_break = None
        min_remaining = float('inf')

        for i, config in enumerate(self.breaks):
            time_text = self._format_time(config.remaining)
            if config.timer_label:
                config.timer_label.configure(text=time_text)
            # Also update header timer (for collapsed state)
            if i < len(self.panels):
                self.panels[i].update_header_timer(time_text)

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
    root.attributes('-topmost', True)
    root.after(100, lambda: root.attributes('-topmost', False))


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

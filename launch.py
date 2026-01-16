import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
import threading
import time
import sys
import subprocess
import json
from pathlib import Path

# ------------------ CUSTOMTKINTER SETUP ------------------

ctk.set_appearance_mode("system")  # Follow system dark/light mode
ctk.set_default_color_theme("blue")  # macOS-style blue accent

# ------------------ CONFIGURATION ------------------

TIME_UNITS = ["sec", "min", "hour"]
SOUND_LOOP_INTERVAL = 1.2
CONFIG_FILE = Path.home() / "Library" / "Preferences" / "com.yairs.dontforgetyourbreaks.json"

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

        # Create popup window
        self.window = ctk.CTkToplevel(parent)
        self.window.title(title)
        self.window.resizable(False, False)

        # Make window always on top
        self.window.attributes('-topmost', True)

        # Larger popup size with modern styling
        popup_w, popup_h = 380, 260

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

        # Update progress bar
        try:
            progress_value = max(0, self.remaining / self.duration) if self.duration > 0 else 0
            self.progress.set(progress_value)
        except Exception:
            pass

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
        self.window.destroy()
        self.closed = True

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
        self.window.destroy()

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
            popup_w, popup_h = 380, 260
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
    """Modern UI panel for configuring a single break."""

    def __init__(self, parent, config, on_test):
        super().__init__(
            parent,
            corner_radius=CORNER_RADIUS_PANEL,
            fg_color=COLORS['bg_panel']
        )
        self.config = config
        self.on_test = on_test
        self._build_ui()

    def _build_ui(self):
        # Header with break name
        header = ctk.CTkLabel(
            self,
            text=self.config.name.get(),
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['status'], weight="bold")
        )
        header.pack(anchor="w", padx=PADDING_PANEL_X, pady=(PADDING_PANEL_Y, ROW_SPACING // 2))

        # Row 1: Interval and Duration
        row1 = ctk.CTkFrame(self, fg_color="transparent")
        row1.pack(fill="x", padx=PADDING_PANEL_X, pady=(0, ROW_SPACING))

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
        row2 = ctk.CTkFrame(self, fg_color="transparent")
        row2.pack(fill="x", padx=PADDING_PANEL_X, pady=(0, ROW_SPACING))

        ctk.CTkLabel(
            row2, text="Start:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
        ).pack(side="left")
        start_sound = ctk.CTkComboBox(
            row2, variable=self.config.start_sound,
            values=list(SOUNDS.keys()), width=100, height=36, state="readonly",
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
            values=list(SOUNDS.keys()), width=100, height=36, state="readonly",
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
        row3 = ctk.CTkFrame(self, fg_color="transparent")
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

        # Test button on right (smaller, orange accent)
        ctk.CTkButton(
            row3, text="Test",
            command=lambda: self.on_test(self.config),
            width=60, height=BUTTON_HEIGHT_SMALL,
            corner_radius=CORNER_RADIUS_INPUT,
            fg_color=COLORS['bg_hover'],
            hover_color=COLORS['border'],
            text_color=COLORS['accent_orange'],
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


# ------------------ MAIN APP ------------------

class BreakApp:
    def __init__(self, root):
        self.root = root
        root.title("Don't Forget Your Breaks")
        root.minsize(520, 480)
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
        self.start_btn.pack(side="left", padx=8, expand=True, fill="x")

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
        self.pause_btn.pack(side="left", padx=8, expand=True, fill="x")

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
        self.stop_btn.pack(side="left", padx=8, expand=True, fill="x")

        # Break configuration panels
        for config in self.breaks:
            panel = BreakConfigPanel(main_frame, config, self.test_break)
            panel.pack(fill="x", pady=(0, ROW_SPACING))

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

        for config in self.breaks:
            if config.timer_label:
                config.timer_label.configure(text=self._format_time(config.remaining))
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


# ------------------ MAIN ------------------

def activate_window(root):
    """macOS-specific: bring window to front when launched from .app bundle."""
    root.deiconify()
    root.lift()
    root.focus_force()
    root.attributes('-topmost', True)
    root.after(100, lambda: root.attributes('-topmost', False))


if __name__ == "__main__":
    root = ctk.CTk()
    app = BreakApp(root)

    if sys.platform == "darwin":
        root.after(100, lambda: activate_window(root))

    root.mainloop()

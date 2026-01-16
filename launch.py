import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
import threading
import time
import sys
import subprocess
import json
import os
from pathlib import Path

# ------------------ CONFIGURATION ------------------

TIME_UNITS = ["sec", "min", "hour"]
SOUND_LOOP_INTERVAL = 1.2
CONFIG_FILE = Path.home() / "Library" / "Preferences" / "com.yairs.dontforgetyourbreaks.json"

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
        self.name = tk.StringVar(value=name)
        self.interval_value = tk.IntVar(value=interval_val)
        self.interval_unit = tk.StringVar(value=interval_unit)
        self.duration_value = tk.IntVar(value=duration_val)
        self.duration_unit = tk.StringVar(value=duration_unit)
        self.start_sound = tk.StringVar(value=start_sound)
        self.end_sound = tk.StringVar(value=end_sound)
        self.loop_end_sound = tk.BooleanVar(value=loop_end_sound)
        self.auto_dismiss = tk.BooleanVar(value=auto_dismiss)
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
    """A popup with countdown timer, OK button, and optional looping end sound."""

    def __init__(self, parent, title, message, duration,
                 auto_dismiss=True, on_close=None,
                 end_sound=None, loop_end_sound=False):
        self.parent = parent
        self.duration = duration
        self.remaining = duration
        self.auto_dismiss = auto_dismiss
        self.on_close = on_close
        self.end_sound = end_sound
        self.loop_end_sound = loop_end_sound
        self.closed = False
        self.sound_stop_event = threading.Event()

        # Create popup window - independent window that stays on top
        self.window = tk.Toplevel(parent)
        self.window.title(title)
        self.window.resizable(False, False)

        # Make window always on top
        self.window.attributes('-topmost', True)

        # Position popup at mouse cursor location (works across all monitors)
        self.window.update_idletasks()
        mouse_x = self.window.winfo_pointerx()
        mouse_y = self.window.winfo_pointery()
        # Position centered on mouse, with small offset down-right to not cover cursor
        popup_w, popup_h = 300, 150
        x = mouse_x - popup_w // 2 + 20
        y = mouse_y - popup_h // 2 + 20
        self.window.geometry(f"{popup_w}x{popup_h}+{x}+{y}")

        # Force focus and request attention
        self.window.lift()
        self.window.focus_force()
        self._request_attention()

        # Message
        tk.Label(self.window, text=message, font=("Arial", 11)).pack(pady=15)

        # Countdown label
        self.countdown_label = tk.Label(
            self.window,
            text=self._format_time(self.remaining),
            font=("Arial", 24, "bold")
        )
        self.countdown_label.pack(pady=5)

        # OK button
        self.ok_btn = tk.Button(self.window, text="OK", command=self.close, width=10)
        self.ok_btn.pack(pady=10)

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
        self.countdown_label.config(text=self._format_time(self.remaining))

        if self.remaining <= 0:
            # Timer finished - handle end sound
            if self.end_sound and self.end_sound != "None":
                if self.loop_end_sound:
                    # Start looping end sound
                    threading.Thread(
                        target=looping_sound,
                        args=(self.sound_stop_event, self.end_sound),
                        daemon=True
                    ).start()
                else:
                    # Play end sound once
                    play_sound(self.end_sound)

            if self.auto_dismiss:
                self.close()
            else:
                self.countdown_label.config(text="Done!")
                self._bring_to_attention()
        else:
            self.window.after(1000, self.update_countdown)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.sound_stop_event.set()  # Stop any looping sound
        if self.on_close:
            self.on_close()
        self.window.destroy()

    def _request_attention(self):
        """Request user attention - flash in taskbar without switching spaces."""
        # Note: We avoid osascript activation which would switch spaces
        # The -topmost attribute and periodic lift() should keep visibility
        try:
            self.window.bell()  # System beep - may cause dock bounce
        except tk.TclError:
            pass

    def _keep_on_top(self):
        """Periodically ensure popup stays on top and visible."""
        if self.closed:
            return
        try:
            self.window.lift()
            self.window.attributes('-topmost', True)
        except tk.TclError:
            return
        # Check every 2 seconds
        self.window.after(2000, self._keep_on_top)

    def bring_to_user(self):
        """Bring popup to user's current location (works across monitors)."""
        if self.closed:
            return
        try:
            # Move to current mouse position
            mouse_x = self.window.winfo_pointerx()
            mouse_y = self.window.winfo_pointery()
            popup_w, popup_h = 300, 150
            x = mouse_x - popup_w // 2 + 20
            y = mouse_y - popup_h // 2 + 20
            self.window.geometry(f"{popup_w}x{popup_h}+{x}+{y}")
            self.window.lift()
            self.window.focus_force()
            self.window.attributes('-topmost', True)
        except tk.TclError:
            pass

    def _bring_to_attention(self):
        """Bring popup to user's attention when countdown ends."""
        try:
            self.window.lift()
            self.window.focus_force()
            self.window.attributes('-topmost', True)
            self._flash_button()
        except tk.TclError:
            pass

    def _flash_button(self, count=6):
        """Flash OK button to draw attention."""
        if self.closed or count <= 0:
            return
        flash_color = "#FF6B6B"  # Salmon red
        default_color = "SystemButtonFace"
        current_bg = self.ok_btn.cget('bg')
        new_color = flash_color if current_bg != flash_color else default_color
        try:
            self.ok_btn.config(bg=new_color)
            self.window.after(200, lambda: self._flash_button(count - 1))
        except tk.TclError:
            pass


# ------------------ BREAK CONFIG PANEL ------------------

class BreakConfigPanel(ttk.LabelFrame):
    """UI panel for configuring a single break."""

    def __init__(self, parent, config, on_test):
        super().__init__(parent, text=config.name.get(), padding=(10, 5))
        self.config = config
        self.on_test = on_test
        self._build_ui()

    def _build_ui(self):
        # Row 1: Interval
        row1 = ttk.Frame(self)
        row1.pack(fill=tk.X, pady=2)

        ttk.Label(row1, text="Every:").pack(side=tk.LEFT)
        interval_entry = ttk.Entry(row1, width=5, textvariable=self.config.interval_value)
        interval_entry.pack(side=tk.LEFT, padx=2)
        interval_unit = ttk.Combobox(row1, textvariable=self.config.interval_unit,
                                     values=TIME_UNITS, width=6, state="readonly")
        interval_unit.pack(side=tk.LEFT)

        ttk.Label(row1, text="   Duration:").pack(side=tk.LEFT)
        duration_entry = ttk.Entry(row1, width=5, textvariable=self.config.duration_value)
        duration_entry.pack(side=tk.LEFT, padx=2)
        duration_unit = ttk.Combobox(row1, textvariable=self.config.duration_unit,
                                     values=TIME_UNITS, width=6, state="readonly")
        duration_unit.pack(side=tk.LEFT)

        # Row 2: Start and End sounds
        row2 = ttk.Frame(self)
        row2.pack(fill=tk.X, pady=2)

        ttk.Label(row2, text="Start sound:").pack(side=tk.LEFT)
        start_sound = ttk.Combobox(row2, textvariable=self.config.start_sound,
                                   values=list(SOUNDS.keys()), width=10, state="readonly")
        start_sound.pack(side=tk.LEFT, padx=2)
        ttk.Button(row2, text="▶", width=2,
                   command=lambda: play_sound(self.config.start_sound.get())).pack(side=tk.LEFT)

        ttk.Label(row2, text="   End sound:").pack(side=tk.LEFT)
        end_sound = ttk.Combobox(row2, textvariable=self.config.end_sound,
                                 values=list(SOUNDS.keys()), width=10, state="readonly")
        end_sound.pack(side=tk.LEFT, padx=2)
        ttk.Button(row2, text="▶", width=2,
                   command=lambda: play_sound(self.config.end_sound.get())).pack(side=tk.LEFT)

        # Row 3: Options
        row3 = ttk.Frame(self)
        row3.pack(fill=tk.X, pady=2)

        ttk.Checkbutton(row3, text="Loop end sound",
                        variable=self.config.loop_end_sound).pack(side=tk.LEFT)
        ttk.Checkbutton(row3, text="Auto-dismiss",
                        variable=self.config.auto_dismiss).pack(side=tk.LEFT, padx=15)

        # Row 4: Timer and Test button
        row4 = ttk.Frame(self)
        row4.pack(fill=tk.X, pady=2)

        ttk.Label(row4, text="Next in:").pack(side=tk.LEFT)
        self.config.timer_label = ttk.Label(row4, text="--:--", font=("Arial", 11, "bold"))
        self.config.timer_label.pack(side=tk.LEFT, padx=5)

        ttk.Button(row4, text="Test Break",
                   command=lambda: self.on_test(self.config)).pack(side=tk.RIGHT)


# ------------------ MAIN APP ------------------

class BreakApp:
    def __init__(self, root):
        self.root = root
        root.title("DONT FORGET YOUR BREAKS!")
        root.minsize(480, 400)
        root.resizable(True, True)

        self.running = False
        self.paused = False
        self.stop_event = threading.Event()
        self.break_queue = []
        self.active_popup = None
        self.break_start_time = None  # Track when current break started

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
            root.geometry("520x450")  # Default size

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

        # Bring popup to user when main window is focused/clicked
        root.bind("<FocusIn>", self._on_main_focus)
        root.bind("<Button-1>", self._on_main_focus)

    def _build_ui(self):
        # Title
        ttk.Label(self.root, text="DONT FORGET YOUR BREAKS!",
                  font=("Arial", 14, "bold")).pack(pady=10)

        # Status
        self.status = ttk.Label(self.root, text="Status: Idle", font=("Arial", 11))
        self.status.pack()

        # Control buttons
        control_frame = ttk.Frame(self.root)
        control_frame.pack(pady=10)

        self.start_btn = ttk.Button(control_frame, text="Start",
                                    command=self.start, width=10)
        self.start_btn.pack(side=tk.LEFT, padx=4)

        self.pause_btn = ttk.Button(control_frame, text="Pause",
                                    command=self.toggle_pause, width=10,
                                    state=tk.DISABLED)
        self.pause_btn.pack(side=tk.LEFT, padx=4)

        self.stop_btn = ttk.Button(control_frame, text="Stop",
                                   command=self.stop, width=10,
                                   state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=4)

        # Break configuration panels
        for config in self.breaks:
            panel = BreakConfigPanel(self.root, config, self.test_break)
            panel.pack(fill=tk.X, padx=10, pady=5)

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
        prefs = {
            "breaks": []
        }
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
        # Save window geometry if requested
        if include_geometry:
            prefs["window_geometry"] = self.root.geometry()
        elif hasattr(self, 'saved_prefs') and "window_geometry" in self.saved_prefs:
            # Preserve existing geometry when auto-saving other prefs
            prefs["window_geometry"] = self.saved_prefs["window_geometry"]
        try:
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_FILE, 'w') as f:
                json.dump(prefs, f, indent=2)
        except IOError as e:
            print(f"Warning: Could not save preferences: {e}")

    def _on_close(self):
        """Handle window close - save geometry and exit."""
        self._save_preferences(include_geometry=True)
        self.root.destroy()

    def _on_main_focus(self, event=None):
        """When main window is focused, bring popup to user if active."""
        if self.active_popup and not self.active_popup.closed:
            self.active_popup.bring_to_user()

    def _setup_auto_save(self):
        """Setup auto-save when any preference changes."""
        for config in self.breaks:
            # Trace all variables to save on change
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

        # Reset all break timers
        for config in self.breaks:
            config.reset_timer()

        self.status.config(text="Status: Working")
        self.start_btn.config(state=tk.DISABLED)
        self.pause_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.NORMAL)

        # Start single timer thread
        threading.Thread(target=self.timer_loop, daemon=True).start()

    def toggle_pause(self):
        if self.paused:
            self.paused = False
            self.pause_btn.config(text="Pause")
            self.status.config(text="Status: Working")
        else:
            self.paused = True
            self.pause_btn.config(text="Resume")
            self.status.config(text="Status: Paused")

    def stop(self):
        self.running = False
        self.paused = False
        self.stop_event.set()

        # Clear break queue and close active popup
        self.break_queue.clear()
        if self.active_popup:
            try:
                self.active_popup.close()
            except tk.TclError:
                pass
            self.active_popup = None

        # Reset all break timers
        for config in self.breaks:
            config.reset_timer()

        self.status.config(text="Status: Idle")
        self.start_btn.config(state=tk.NORMAL)
        self.pause_btn.config(state=tk.DISABLED, text="Pause")
        self.stop_btn.config(state=tk.DISABLED)

    # ------------------ TIMER ------------------

    def timer_loop(self):
        """Single timer loop managing all breaks."""
        while self.running and not self.stop_event.is_set():
            time.sleep(1)
            # Skip countdown if paused OR if a break popup is active
            if self.paused or self.active_popup:
                continue

            for config in self.breaks:
                config.remaining -= 1
                if config.remaining <= 0:
                    self.trigger_break(config)
                    config.reset_timer()

    def trigger_break(self, config):
        """Queue a break with the given configuration."""
        # Capture config values for the queue (avoid Tkinter threading issues)
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

        # Skip breaks with zero or negative duration (already fulfilled by previous break)
        if break_data['duration'] <= 0:
            self.root.after(0, self._process_break_queue)
            return

        # Play start sound
        play_sound(break_data['start_sound'])

        # Track when this break started
        self.break_start_time = time.time()

        def on_popup_close():
            # Calculate how long this break lasted
            elapsed = int(time.time() - self.break_start_time) if self.break_start_time else 0

            # Adjust durations of queued breaks (they benefit from time already spent)
            for queued_break in self.break_queue:
                queued_break['duration'] -= elapsed

            self.active_popup = None
            self.break_start_time = None
            if self.running and not self.paused:
                self.status.config(text="Status: Working")
            # Process next queued break
            self.root.after(0, self._process_break_queue)

        self.status.config(text=f"Status: {break_data['name']}")
        self.active_popup = CountdownPopup(
            self.root,
            break_data['name'],
            "Take a break!",
            break_data['duration'],
            auto_dismiss=break_data['auto_dismiss'],
            on_close=on_popup_close,
            end_sound=break_data['end_sound'],
            loop_end_sound=break_data['loop_end_sound']
        )

    def test_break(self, config):
        """Test a specific break configuration."""
        self.trigger_break(config)

    # ------------------ UI UPDATE ------------------

    def update_ui(self):
        """Update timer displays for all breaks."""
        for config in self.breaks:
            if config.timer_label:
                config.timer_label.config(text=self._format_time(config.remaining))
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
    # Toggle topmost to ensure window appears on top
    root.attributes('-topmost', True)
    root.after(100, lambda: root.attributes('-topmost', False))


if __name__ == "__main__":
    root = tk.Tk()
    app = BreakApp(root)

    # macOS fix: bring window to front when launched from .app bundle
    if sys.platform == "darwin":
        root.after(100, lambda: activate_window(root))

    root.mainloop()

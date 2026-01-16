import tkinter as tk
from tkinter import messagebox
import threading
import time
import sys
import subprocess

# ------------------ CONFIGURATION ------------------

TIME_UNITS = ["sec", "min", "hour"]
SOUND_LOOP_INTERVAL = 1.2

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

        # Create popup window
        self.window = tk.Toplevel(parent)
        self.window.title(title)
        self.window.geometry("300x150")
        self.window.resizable(False, False)
        self.window.transient(parent)
        self.window.grab_set()

        # Center on screen
        self.window.update_idletasks()
        x = (self.window.winfo_screenwidth() - 300) // 2
        y = (self.window.winfo_screenheight() - 150) // 2
        self.window.geometry(f"300x150+{x}+{y}")

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

        # Start countdown
        self.update_countdown()

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


# ------------------ BREAK CONFIG PANEL ------------------

class BreakConfigPanel(tk.LabelFrame):
    """UI panel for configuring a single break."""

    def __init__(self, parent, config, on_test):
        super().__init__(parent, text=config.name.get(), padx=10, pady=5)
        self.config = config
        self.on_test = on_test
        self._build_ui()

    def _build_ui(self):
        # Row 1: Interval and Duration
        row1 = tk.Frame(self)
        row1.pack(fill=tk.X, pady=2)

        tk.Label(row1, text="Every").pack(side=tk.LEFT)
        tk.Spinbox(row1, from_=1, to=999, width=4,
                   textvariable=self.config.interval_value).pack(side=tk.LEFT, padx=2)
        tk.OptionMenu(row1, self.config.interval_unit, *TIME_UNITS).pack(side=tk.LEFT)

        tk.Label(row1, text="  Duration").pack(side=tk.LEFT)
        tk.Spinbox(row1, from_=1, to=999, width=4,
                   textvariable=self.config.duration_value).pack(side=tk.LEFT, padx=2)
        tk.OptionMenu(row1, self.config.duration_unit, *TIME_UNITS).pack(side=tk.LEFT)

        # Row 2: Start and End sounds
        row2 = tk.Frame(self)
        row2.pack(fill=tk.X, pady=2)

        tk.Label(row2, text="Start:").pack(side=tk.LEFT)
        tk.OptionMenu(row2, self.config.start_sound, *SOUNDS.keys()).pack(side=tk.LEFT)
        tk.Button(row2, text="🔊", width=2,
                  command=lambda: play_sound(self.config.start_sound.get())).pack(side=tk.LEFT, padx=2)

        tk.Label(row2, text=" End:").pack(side=tk.LEFT)
        tk.OptionMenu(row2, self.config.end_sound, *SOUNDS.keys()).pack(side=tk.LEFT)
        tk.Button(row2, text="🔊", width=2,
                  command=lambda: play_sound(self.config.end_sound.get())).pack(side=tk.LEFT, padx=2)

        # Row 3: Options
        row3 = tk.Frame(self)
        row3.pack(fill=tk.X, pady=2)

        tk.Checkbutton(row3, text="Loop end sound",
                       variable=self.config.loop_end_sound).pack(side=tk.LEFT)
        tk.Checkbutton(row3, text="Auto-dismiss",
                       variable=self.config.auto_dismiss).pack(side=tk.LEFT, padx=10)

        # Row 4: Timer and Test button
        row4 = tk.Frame(self)
        row4.pack(fill=tk.X, pady=2)

        tk.Label(row4, text="Next:").pack(side=tk.LEFT)
        self.config.timer_label = tk.Label(row4, text="--:--", font=("Arial", 10, "bold"))
        self.config.timer_label.pack(side=tk.LEFT, padx=5)

        tk.Button(row4, text="Test Break",
                  command=lambda: self.on_test(self.config)).pack(side=tk.RIGHT)


# ------------------ MAIN APP ------------------

class BreakApp:
    def __init__(self, root):
        self.root = root
        root.title("DONT FORGET YOUR BREAKS!")
        root.geometry("400x450")
        root.resizable(False, False)

        self.running = False
        self.paused = False
        self.stop_event = threading.Event()

        # Create break configurations
        self.breaks = [
            BreakConfig(
                name="Micro Break",
                interval_val=25, interval_unit="min",
                duration_val=5, duration_unit="sec",
                start_sound="Ping", end_sound="Glass",
                loop_end_sound=False, auto_dismiss=True
            ),
            BreakConfig(
                name="Normal Break",
                interval_val=50, interval_unit="min",
                duration_val=10, duration_unit="min",
                start_sound="Glass", end_sound="Submarine",
                loop_end_sound=True, auto_dismiss=False
            )
        ]

        self._build_ui()

    def _build_ui(self):
        # Title
        tk.Label(self.root, text="🧠 DONT FORGET YOUR BREAKS!",
                 font=("Arial", 12, "bold")).pack(pady=8)

        # Status
        self.status = tk.Label(self.root, text="Status: Idle")
        self.status.pack()

        # Control buttons
        control_frame = tk.Frame(self.root)
        control_frame.pack(pady=8)

        self.start_btn = tk.Button(control_frame, text="Start",
                                   command=self.start, width=8)
        self.start_btn.pack(side=tk.LEFT, padx=2)

        self.pause_btn = tk.Button(control_frame, text="Pause",
                                   command=self.toggle_pause, width=8,
                                   state=tk.DISABLED)
        self.pause_btn.pack(side=tk.LEFT, padx=2)

        self.stop_btn = tk.Button(control_frame, text="Stop",
                                  command=self.stop, width=8,
                                  state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=2)

        # Break configuration panels
        for config in self.breaks:
            panel = BreakConfigPanel(self.root, config, self.test_break)
            panel.pack(fill=tk.X, padx=10, pady=5)

        # Start UI update loop
        self.update_ui()

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
            if self.paused:
                continue

            for config in self.breaks:
                config.remaining -= 1
                if config.remaining <= 0:
                    self.trigger_break(config)
                    config.reset_timer()

    def trigger_break(self, config):
        """Trigger a break with the given configuration."""
        # Play start sound
        play_sound(config.start_sound.get())

        name = config.name.get()
        duration = config.get_duration_seconds()
        auto_dismiss = config.auto_dismiss.get()
        end_sound = config.end_sound.get()
        loop_end = config.loop_end_sound.get()

        def on_popup_close():
            if self.running and not self.paused:
                self.status.config(text="Status: Working")

        def show_popup():
            self.status.config(text=f"Status: {name}")
            CountdownPopup(
                self.root,
                f"{name}",
                "Take a break!",
                duration,
                auto_dismiss=auto_dismiss,
                on_close=on_popup_close,
                end_sound=end_sound,
                loop_end_sound=loop_end
            )

        self.root.after(0, show_popup)

    def test_break(self, config):
        """Test a specific break configuration."""
        threading.Thread(
            target=lambda: self.trigger_break(config),
            daemon=True
        ).start()

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

if __name__ == "__main__":
    root = tk.Tk()
    BreakApp(root)
    root.mainloop()

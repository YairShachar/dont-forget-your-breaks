"""System sound playback (macOS afplay; beep/bell fallback elsewhere)."""
import subprocess
import sys
import time

SOUND_LOOP_INTERVAL = 1.2

# Sound options including "None". Values are macOS system-sound filenames.
SOUNDS = {
    "None": None,
    "Glass": "Glass.aiff",
    "Ping": "Ping.aiff",
    "Pop": "Pop.aiff",
    "Submarine": "Submarine.aiff",
}


def play_sound_mac(sound_name):
    sound_file = SOUNDS.get(sound_name)
    if sound_file:
        subprocess.Popen(
            ["afplay", f"/System/Library/Sounds/{sound_file}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
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

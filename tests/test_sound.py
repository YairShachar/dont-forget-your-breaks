import threading

import dfyb.sound as sound
from dfyb.sound import play_sound, SOUNDS


class OneShotStop:
    """Stop-event whose is_set() is False once, then True (one loop iteration)."""
    def __init__(self):
        self.checks = 0

    def is_set(self):
        self.checks += 1
        return self.checks > 1


def test_sounds_has_expected_entries():
    assert SOUNDS["None"] is None
    assert SOUNDS["Glass"] == "Glass.aiff"


def test_play_sound_none_is_noop(monkeypatch):
    calls = []
    monkeypatch.setattr(sound.subprocess, "Popen", lambda *a, **k: calls.append(a))
    play_sound("None")
    play_sound(None)
    assert calls == []


def test_play_sound_mac_invokes_afplay(monkeypatch):
    captured = []
    monkeypatch.setattr(sound.sys, "platform", "darwin")
    monkeypatch.setattr(sound.subprocess, "Popen", lambda cmd, **k: captured.append(cmd))
    play_sound("Glass")
    assert captured and captured[0][0] == "afplay"
    assert captured[0][1].endswith("Glass.aiff")


def test_looping_sound_runs_until_stopped(monkeypatch):
    played = []
    monkeypatch.setattr(sound, "play_sound", lambda name: played.append(name))
    monkeypatch.setattr(sound.time, "sleep", lambda s: None)
    sound.looping_sound(OneShotStop(), "Glass")
    assert played == ["Glass"]

"""Finding 2: `_app_identity` must not leak on the once-per-second sensor path.

It used to build a NEW `ctypes.CDLL("/usr/lib/libSystem.dylib")` per call (ctypes
never dlcloses, and each instance grows its own function-pointer cache) and to
re-read the enclosing Info.plist from disk every time. GUI holders return early,
so the cost fell exactly on the `.appex`/daemon holders this branch exists to
handle — the 18-hour `Sound.appex` incident, at ~2.7 MB/hour.

Pure-ish: the CoreAudio/AppKit calls are faked, so these run headless.
"""
import logging
import sys
import types

import pytest

from dfyb.activity import sensors


@pytest.fixture(autouse=True)
def _clean_cache():
    sensors.forget_app_identities()
    yield
    sensors.forget_app_identities()


def _no_appkit(monkeypatch):
    """AppKit present but resolving nothing — the daemon / .appex path."""
    monkeypatch.setitem(sys.modules, "AppKit", types.SimpleNamespace(
        NSRunningApplication=types.SimpleNamespace(
            runningApplicationWithProcessIdentifier_=lambda _pid: None)))


# --- the libSystem handle is opened once, with its signature declared once ---

def test_libsystem_handle_is_a_singleton():
    first, second = sensors._libsystem(), sensors._libsystem()
    assert first is second


def test_libsystem_declares_proc_pidpath_signature():
    lib = sensors._libsystem()
    assert lib.proc_pidpath.argtypes is not None
    assert lib.proc_pidpath.restype is not None


# --- pid -> identity is memoized, so the disk walk happens once ---

def test_identity_is_resolved_once_per_pid(monkeypatch):
    _no_appkit(monkeypatch)
    calls = []

    def proc_pidpath(pid, buf, size):
        calls.append(pid)
        buf.value = b"/Applications/Sound.appex/Contents/MacOS/Sound"
        return len(buf.value)
    monkeypatch.setattr(sensors, "_libsystem",
                        lambda: types.SimpleNamespace(proc_pidpath=proc_pidpath))
    monkeypatch.setattr(sensors, "_bundle_identity_from_path",
                        lambda path: ("com.apple.Sound-Settings.extension", "Sound"))

    first = sensors._app_identity(4242)
    for _ in range(50):
        assert sensors._app_identity(4242) == first
    assert first == ("com.apple.Sound-Settings.extension", "Sound")
    assert calls == [4242]          # one libproc call for 51 asks


def test_unresolvable_pid_is_also_memoized(monkeypatch):
    """The total-miss branch was the most expensive one — it must not repeat."""
    _no_appkit(monkeypatch)
    calls = []
    monkeypatch.setattr(sensors, "_libsystem", lambda: types.SimpleNamespace(
        proc_pidpath=lambda pid, buf, size: (calls.append(pid), 0)[-1]))
    assert sensors._app_identity(999999) == (None, "pid 999999")
    assert sensors._app_identity(999999) == (None, "pid 999999")
    assert calls == [999999]


# --- the cache stays bounded, and empties when nothing holds the mic ---

def test_cache_is_bounded(monkeypatch):
    _no_appkit(monkeypatch)
    monkeypatch.setattr(sensors, "_libsystem", lambda: types.SimpleNamespace(
        proc_pidpath=lambda pid, buf, size: 0))
    for pid in range(sensors.APP_IDENTITY_CACHE_MAX * 3):
        sensors._app_identity(pid)
        assert len(sensors._IDENTITY_CACHE) <= sensors.APP_IDENTITY_CACHE_MAX


def test_forget_app_identities_clears_it(monkeypatch):
    _no_appkit(monkeypatch)
    monkeypatch.setattr(sensors, "_libsystem", lambda: types.SimpleNamespace(
        proc_pidpath=lambda pid, buf, size: 0))
    sensors._app_identity(1234)
    assert sensors._IDENTITY_CACHE
    sensors.forget_app_identities()
    assert sensors._IDENTITY_CACHE == {}


def test_mic_going_idle_drops_every_memoized_pid(monkeypatch):
    """The pid-reuse window is closed at the natural boundary: the moment nobody
    holds the audio input, every cached identity is dropped."""
    from tests.test_sensors import _fake_coreaudio_processes, _install_mic_process_fakes
    sensors._IDENTITY_CACHE[700] = ("us.zoom.xos", "zoom.us")
    fake = _fake_coreaudio_processes(
        process_objects=[10], running_input={10: 0}, pids={10: 700})
    _install_mic_process_fakes(monkeypatch, fake, {})
    assert sensors.mic_input_processes() == []
    assert sensors._IDENTITY_CACHE == {}


# --- the last silent swallows in the sensor layer now log ---

def test_appkit_failure_is_logged(monkeypatch, caplog):
    def boom(_pid):
        raise RuntimeError("appkit boom")
    monkeypatch.setitem(sys.modules, "AppKit", types.SimpleNamespace(
        NSRunningApplication=types.SimpleNamespace(
            runningApplicationWithProcessIdentifier_=boom)))
    monkeypatch.setattr(sensors, "_libsystem", lambda: types.SimpleNamespace(
        proc_pidpath=lambda pid, buf, size: 0))
    with caplog.at_level(logging.DEBUG):
        assert sensors._app_identity(4242) == (None, "pid 4242")
    assert "appkit boom" in caplog.text


def test_proc_pidpath_failure_is_logged(monkeypatch, caplog):
    _no_appkit(monkeypatch)

    def boom():
        raise RuntimeError("libproc boom")
    monkeypatch.setattr(sensors, "_libsystem", boom)
    with caplog.at_level(logging.DEBUG):
        assert sensors._app_identity(4242) == (None, "pid 4242")
    assert "libproc boom" in caplog.text


def test_running_gui_apps_failure_is_logged_not_silently_empty(monkeypatch, caplog):
    """An exception used to make the picker look like 'no apps are running'."""
    monkeypatch.setattr(sensors.sys, "platform", "darwin")

    class _Boom:
        def __getattr__(self, _name):
            raise RuntimeError("workspace boom")
    monkeypatch.setitem(sys.modules, "AppKit", _Boom())
    with caplog.at_level(logging.DEBUG):
        assert sensors.running_gui_apps() == []
    assert "workspace boom" in caplog.text

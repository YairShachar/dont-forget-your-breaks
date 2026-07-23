import json

import dfyb.updater as updater
from dfyb.updater import (
    get_current_version,
    fetch_latest_version,
    is_installed_via_homebrew,
    should_check_for_updates,
)

INTERVAL = 24


class FakeProc:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


def test_get_current_version_reads_file(tmp_path, monkeypatch):
    vf = tmp_path / "VERSION"
    vf.write_text("1.2.3\n")
    monkeypatch.setattr(updater, "VERSION_FILE", vf)
    assert get_current_version() == "1.2.3"


def test_get_current_version_missing_returns_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "VERSION_FILE", tmp_path / "nope")
    assert get_current_version() == "0.0.0"


def test_fetch_latest_version_parses(monkeypatch):
    payload = json.dumps({"tag_name": "v2.0.1", "html_url": "https://x/rel"})
    monkeypatch.setattr(updater.subprocess, "run", lambda *a, **k: FakeProc(0, payload))
    assert fetch_latest_version() == ("2.0.1", "https://x/rel")


def test_fetch_latest_version_nonzero_returns_none(monkeypatch):
    monkeypatch.setattr(updater.subprocess, "run", lambda *a, **k: FakeProc(1, ""))
    assert fetch_latest_version() is None


def test_fetch_latest_version_exception_returns_none(monkeypatch):
    def boom(*a, **k):
        raise OSError("no curl")
    monkeypatch.setattr(updater.subprocess, "run", boom)
    assert fetch_latest_version() is None


def test_is_installed_via_homebrew(monkeypatch):
    monkeypatch.setattr(updater.subprocess, "run", lambda *a, **k: FakeProc(0))
    assert is_installed_via_homebrew() is True
    monkeypatch.setattr(updater.subprocess, "run", lambda *a, **k: FakeProc(1))
    assert is_installed_via_homebrew() is False


def test_disabled_pref_never_checks_even_when_forced():
    # The user's opt-out wins over both the interval and force (launch/manual).
    assert should_check_for_updates(False, 999, INTERVAL) is False
    assert should_check_for_updates(False, 999, INTERVAL, force=True) is False


def test_interval_gates_the_periodic_check():
    assert should_check_for_updates(True, INTERVAL - 0.1, INTERVAL) is False
    assert should_check_for_updates(True, INTERVAL, INTERVAL) is True
    assert should_check_for_updates(True, INTERVAL + 5, INTERVAL) is True


def test_force_bypasses_the_interval_when_enabled():
    # Launch/reload and the manual "check now" icon check even if just checked.
    assert should_check_for_updates(True, 0.0, INTERVAL, force=True) is True


# --- brew / bundle / relaunch helpers (Task 1) ----------------------------

from dfyb.updater import (find_brew, app_bundle_from_executable, relaunch_command,
                          is_installed_via_homebrew)


def test_find_brew_prefers_known_paths(monkeypatch):
    monkeypatch.setattr(updater.os.path, "exists", lambda p: p == "/opt/homebrew/bin/brew")
    assert find_brew() == "/opt/homebrew/bin/brew"


def test_find_brew_falls_back_to_which(monkeypatch):
    monkeypatch.setattr(updater.os.path, "exists", lambda p: False)
    monkeypatch.setattr(updater.shutil, "which", lambda c: "/usr/local/bin/brew")
    assert find_brew() == "/usr/local/bin/brew"


def test_find_brew_none_when_absent(monkeypatch):
    monkeypatch.setattr(updater.os.path, "exists", lambda p: False)
    monkeypatch.setattr(updater.shutil, "which", lambda c: None)
    assert find_brew() is None


def test_app_bundle_from_executable():
    exe = "/Applications/Dont Forget Your Breaks.app/Contents/MacOS/x"
    assert app_bundle_from_executable(exe, True) == "/Applications/Dont Forget Your Breaks.app"
    assert app_bundle_from_executable(exe, False) is None                 # not frozen
    assert app_bundle_from_executable("/usr/bin/python3", True) is None   # no .app ancestor


def test_relaunch_command_shape():
    cmd = relaunch_command(4242, "/Applications/X.app")
    assert cmd[0] == "/bin/sh" and cmd[1] == "-c"
    assert "kill -0 4242" in cmd[2] and 'open "/Applications/X.app"' in cmd[2]


def test_is_installed_via_homebrew_false_without_brew(monkeypatch):
    monkeypatch.setattr(updater, "find_brew", lambda: None)
    assert is_installed_via_homebrew() is False

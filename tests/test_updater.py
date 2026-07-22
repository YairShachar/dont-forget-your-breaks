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

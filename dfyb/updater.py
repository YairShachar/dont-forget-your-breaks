"""App version reporting and GitHub/Homebrew update checks."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Resolve VERSION relative to the repo root (parent of the dfyb/ package),
# or the PyInstaller bundle dir when frozen. parent.parent: dfyb/updater.py -> repo root.
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
VERSION_FILE = BASE_DIR / "VERSION"

GITHUB_REPO = "YairShachar/dont-forget-your-breaks"
GITHUB_RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_PAGE_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"
HOMEBREW_CASK_NAME = "dont-forget-your-breaks"


def should_check_for_updates(pref_enabled, hours_since_last, interval_hours,
                             force=False):
    """Decide whether to run an update check now. Pure (no clock / IO) so it is
    unit-tested. Never runs when the user disabled checks; `force` (a launch /
    reload, or the manual 'check now' icon) bypasses the interval; otherwise the
    interval must have elapsed since the last check."""
    if not pref_enabled:
        return False
    return force or hours_since_last >= interval_hours


def get_current_version():
    """Read the current app version from VERSION file."""
    try:
        return VERSION_FILE.read_text().strip()
    except (FileNotFoundError, IOError):
        return "0.0.0"


def fetch_latest_version():
    """Query GitHub releases API for the latest version. Returns (version, url) or None."""
    try:
        result = subprocess.run(
            ["curl", "-s", "-H", "Accept: application/vnd.github.v3+json",
             "--max-time", "10", GITHUB_RELEASES_API_URL],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        tag = data.get("tag_name", "")
        html_url = data.get("html_url", GITHUB_RELEASES_PAGE_URL)
        return tag.lstrip('v'), html_url
    except Exception:
        return None


BREW_PATHS = ("/opt/homebrew/bin/brew", "/usr/local/bin/brew")


def find_brew():
    """Absolute path to `brew`, or None. GUI apps launched from the Dock lack
    /opt/homebrew/bin on PATH, so probe the known Homebrew locations before which()."""
    for p in BREW_PATHS:
        if os.path.exists(p):
            return p
    return shutil.which("brew")


def app_bundle_from_executable(executable, frozen):
    """The running .app bundle path (…/X.app) for a frozen build, else None."""
    if not frozen:
        return None
    for parent in Path(executable).parents:
        if parent.suffix == ".app":
            return str(parent)
    return None


def relaunch_command(pid, app_path):
    """A detached shell command that waits for `pid` to exit, then reopens `app_path` —
    used to relaunch into the freshly-installed version after we hard-exit."""
    return ["/bin/sh", "-c",
            f'while kill -0 {pid} 2>/dev/null; do sleep 0.2; done; open "{app_path}"']


def is_installed_via_homebrew():
    """Check if the app was installed via Homebrew cask (using an absolute brew path
    so it works from the GUI PATH, not just a shell)."""
    brew = find_brew()
    if not brew:
        return False
    try:
        result = subprocess.run(
            [brew, "list", "--cask", HOMEBREW_CASK_NAME],
            capture_output=True, timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False

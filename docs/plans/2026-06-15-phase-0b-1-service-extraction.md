# Phase 0b-1 Service Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the non-UI service functions (sound, updater, animation) out of `launch.py` into tested `dfyb/` modules, and verify the PyInstaller build still bundles the `dfyb` package.

**Architecture:** Behavior-preserving extraction. Each group of functions (and the constants only they use) moves to a focused module under `dfyb/`. Because the UI classes call these by bare name, `launch.py` just gains imports and loses the original definitions — the class bodies are untouched. Tests use `monkeypatch` to stub `subprocess`/filesystem so they run headless in CI.

**Tech Stack:** Python 3 (stdlib), pytest, PyInstaller, GitHub Actions.

**Scope:** This is **Phase 0b-1**. The risky UI-class extraction (`CountdownPopup`/`BreakConfigPanel`/`BreakApp` → `dfyb/ui/`, `BreakConfig` → `dfyb/breaks/config.py`, design tokens, and the #2 focus-bug regression) is **Phase 0b-2**, a separate plan.

**Repo conventions:**
- Repo is under `~/data/projects/`, so commits auto-use the personal Git identity. No identity flags.
- Use `.venv/bin/python` / `.venv/bin/pip` for everything.
- Conventional-commit messages, summary only, no co-author trailer.
- **Push the branch before opening any PR, and verify the PR diff + CI test count.** (A prior phase merged incompletely because local commits weren't pushed.)
- Branch: create `phase-0b-1-services` off `main` before Task 1.

**Pre-flight (run once before Task 1):**
```bash
cd ~/data/projects/dont_forget_your_breaks
git checkout main && git pull --ff-only origin main
git checkout -b phase-0b-1-services
.venv/bin/python -m pytest -q   # expect: 16 passed (baseline)
```

---

### Task 1: Extract `dfyb/sound.py`

**Files:**
- Create: `dfyb/sound.py`
- Modify: `launch.py` (remove `SOUNDS`, `SOUND_LOOP_INTERVAL`, and the three sound functions; add an import)
- Test: `tests/test_sound.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sound.py`:
```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_sound.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'dfyb.sound'`

- [ ] **Step 3: Create the module**

Create `dfyb/sound.py`:
```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_sound.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Rewire `launch.py`**

Add this import immediately after the existing `from dfyb.breaks.duration import to_seconds` line:
```python
from dfyb.sound import play_sound, looping_sound, SOUNDS
```

Delete the `SOUND_LOOP_INTERVAL` constant line from the CONFIGURATION block:
```python
SOUND_LOOP_INTERVAL = 1.2
```

Delete the entire `SOUNDS` dict definition from the CONFIGURATION block:
```python
# Sound options including "None"
SOUNDS = {
    "None": None,
    "Glass": "Glass.aiff",
    "Ping": "Ping.aiff",
    "Pop": "Pop.aiff",
    "Submarine": "Submarine.aiff"
}
```

Delete the three sound function definitions (the `# ------------------ SOUND FUNCTIONS ------------------` section), i.e. `play_sound_mac`, `play_sound`, and `looping_sound`:
```python
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
```

Do NOT change any call sites — `play_sound(...)`, `looping_sound`, and `list(SOUNDS.keys())` inside the classes resolve to the imported names.

- [ ] **Step 6: Smoke-test the app**

Run: `timeout 5 .venv/bin/python launch.py; echo "exit=$? (124=ran fine)"`
Expected: `exit=124`, no traceback.

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (20 passed)

- [ ] **Step 8: Commit**

```bash
git add dfyb/sound.py tests/test_sound.py launch.py
git commit -m "refactor: extract sound playback into dfyb.sound with tests"
```

---

### Task 2: Extract `dfyb/updater.py`

**Files:**
- Create: `dfyb/updater.py`
- Modify: `launch.py` (remove the version/update constants and the three updater functions; add an import)
- Test: `tests/test_updater.py`

**Critical detail:** `VERSION_FILE` resolves relative to the file it's defined in. In `launch.py` (repo root) it was `Path(__file__).parent`. In `dfyb/updater.py` it must be `Path(__file__).resolve().parent.parent` (go up from `dfyb/` to the repo root) so the source-run path to `VERSION` is unchanged. `_MEIPASS` still wins when bundled.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_updater.py`:
```python
import json

import dfyb.updater as updater
from dfyb.updater import (
    get_current_version,
    fetch_latest_version,
    is_installed_via_homebrew,
)


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_updater.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'dfyb.updater'`

- [ ] **Step 3: Create the module**

Create `dfyb/updater.py`:
```python
"""App version reporting and GitHub/Homebrew update checks."""
import json
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


def is_installed_via_homebrew():
    """Check if the app was installed via Homebrew cask."""
    try:
        result = subprocess.run(
            ["brew", "list", "--cask", HOMEBREW_CASK_NAME],
            capture_output=True, timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_updater.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Rewire `launch.py`**

Add this import immediately after the `from dfyb.sound import ...` line:
```python
from dfyb.updater import (
    get_current_version,
    fetch_latest_version,
    is_installed_via_homebrew,
    VERSION_FILE,
    HOMEBREW_CASK_NAME,
)
```
(`VERSION_FILE` and `HOMEBREW_CASK_NAME` are imported because `launch.py` still references them directly — at the `_update_via_homebrew` method around lines 1259 and 1237.)

Delete these constant lines from the CONFIGURATION block (leave `CONFIG_FILE`, `LOCK_FILE`, `GITHUB_NEW_ISSUE_URL`, and `UPDATE_CHECK_INTERVAL_HOURS` in place — they are still used by `launch.py`):
```python
BASE_DIR = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
VERSION_FILE = BASE_DIR / "VERSION"
```
```python
GITHUB_REPO = "YairShachar/dont-forget-your-breaks"
GITHUB_RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_PAGE_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"
```
```python
HOMEBREW_CASK_NAME = "dont-forget-your-breaks"
```

Delete the three updater function definitions (the `# ------------------ UPDATE CHECKER ------------------` section), i.e. `get_current_version`, `fetch_latest_version`, and `is_installed_via_homebrew`:
```python
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


def is_installed_via_homebrew():
    """Check if the app was installed via Homebrew cask."""
    try:
        result = subprocess.run(
            ["brew", "list", "--cask", HOMEBREW_CASK_NAME],
            capture_output=True, timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False
```
Note: `parse_version`/`is_newer_version` were already extracted to `dfyb.version` in Phase 0a — do not touch that import.

- [ ] **Step 6: Smoke-test the app**

Run: `timeout 5 .venv/bin/python launch.py; echo "exit=$? (124=ran fine)"`
Expected: `exit=124`, no traceback. (This exercises `get_current_version()` at startup, which reads the real `VERSION` file — confirms the `parent.parent` path is correct.)

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (26 passed)

- [ ] **Step 8: Commit**

```bash
git add dfyb/updater.py tests/test_updater.py launch.py
git commit -m "refactor: extract version/update checks into dfyb.updater with tests"
```

---

### Task 3: Extract `dfyb/animation.py`

**Files:**
- Create: `dfyb/animation.py`
- Modify: `launch.py` (remove the three animation helpers; add an import)
- Test: `tests/test_animation.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_animation.py`:
```python
import dfyb.animation as animation
from dfyb.animation import ease_out_quad, ease_in_quad, prefers_reduced_motion


class FakeProc:
    def __init__(self, stdout):
        self.stdout = stdout


def test_ease_out_quad_endpoints():
    assert ease_out_quad(0) == 0
    assert ease_out_quad(1) == 1


def test_ease_out_quad_midpoint():
    assert ease_out_quad(0.5) == 0.75


def test_ease_in_quad():
    assert ease_in_quad(0) == 0
    assert ease_in_quad(0.5) == 0.25
    assert ease_in_quad(1) == 1


def test_prefers_reduced_motion_non_darwin(monkeypatch):
    monkeypatch.setattr(animation.sys, "platform", "linux")
    assert prefers_reduced_motion() is False


def test_prefers_reduced_motion_darwin_enabled(monkeypatch):
    monkeypatch.setattr(animation.sys, "platform", "darwin")
    monkeypatch.setattr(animation.subprocess, "run", lambda *a, **k: FakeProc("1\n"))
    assert prefers_reduced_motion() is True


def test_prefers_reduced_motion_darwin_disabled(monkeypatch):
    monkeypatch.setattr(animation.sys, "platform", "darwin")
    monkeypatch.setattr(animation.subprocess, "run", lambda *a, **k: FakeProc("0\n"))
    assert prefers_reduced_motion() is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_animation.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'dfyb.animation'`

- [ ] **Step 3: Create the module**

Create `dfyb/animation.py`:
```python
"""Easing helpers and the macOS reduced-motion preference check."""
import subprocess
import sys


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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_animation.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Rewire `launch.py`**

Add this import immediately after the `from dfyb.updater import (...)` block:
```python
from dfyb.animation import ease_out_quad, ease_in_quad, prefers_reduced_motion
```

Delete the three function definitions (the `# ------------------ ANIMATION HELPERS ------------------` section):
```python
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
```
Do NOT change the call sites (`prefers_reduced_motion()` and `ease_out_quad(progress)` inside `BreakConfigPanel`).

- [ ] **Step 6: Smoke-test the app**

Run: `timeout 5 .venv/bin/python launch.py; echo "exit=$? (124=ran fine)"`
Expected: `exit=124`, no traceback.

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (32 passed)

- [ ] **Step 8: Commit**

```bash
git add dfyb/animation.py tests/test_animation.py launch.py
git commit -m "refactor: extract easing and reduced-motion check into dfyb.animation with tests"
```

---

### Task 4: Verify the PyInstaller build bundles `dfyb`

**Files:**
- Possibly modify: `Dont Forget Your Breaks.spec` (only if the build fails to find `dfyb`)

This task has no unit test — it is a build verification (the deferred flag from Phase 0a). Build artifacts (`build/`, `dist/`) are gitignored.

- [ ] **Step 1: Build the app from the spec**

Run: `.venv/bin/pyinstaller "Dont Forget Your Breaks.spec" --noconfirm 2>&1 | tail -15`
Expected: build completes, ends with a "Building BUNDLE ... completed successfully" style message and no errors.

- [ ] **Step 2: Confirm the bundle exists**

Run: `ls -d "dist/Dont Forget Your Breaks.app"`
Expected: the path prints (the `.app` exists).

- [ ] **Step 3: Launch the BUILT app and confirm it runs (this is the real test — does `dfyb` import inside the bundle?)**

Run:
```bash
timeout 6 "dist/Dont Forget Your Breaks.app/Contents/MacOS/Dont Forget Your Breaks" > /tmp/dfyb_build.log 2>&1; echo "exit=$? (124=ran fine)"; grep -iE "ModuleNotFoundError|No module named|Traceback" /tmp/dfyb_build.log && echo "BUILD-RUN FAILED" || echo "build runs clean"
```
Expected: `exit=124` and `build runs clean` (no `ModuleNotFoundError: No module named 'dfyb...'`).

- [ ] **Step 4: If — and only if — Step 3 reported a missing `dfyb` module, add hiddenimports and rebuild**

In `Dont Forget Your Breaks.spec`, change:
```python
    hiddenimports=[],
```
to:
```python
    hiddenimports=[
        'dfyb',
        'dfyb.version',
        'dfyb.breaks', 'dfyb.breaks.duration',
        'dfyb.activity', 'dfyb.activity.event_log',
        'dfyb.sound', 'dfyb.updater', 'dfyb.animation',
    ],
```
Then re-run Steps 1–3 and confirm `build runs clean`.

- [ ] **Step 5: Commit (only if the `.spec` changed)**

```bash
# Only if you edited the spec in Step 4:
git add "Dont Forget Your Breaks.spec"
git commit -m "build: bundle dfyb package in PyInstaller spec"
```
If the `.spec` was not changed, there is nothing to commit — report that the build verified clean with no changes needed.

---

## Definition of done (this slice)

- `dfyb/sound.py`, `dfyb/updater.py`, `dfyb/animation.py` exist with tests; `launch.py` imports them and still launches (exit=124, no traceback).
- `pytest -q` passes locally and in CI (expected total: 32 tests).
- The PyInstaller-built `.app` launches without a `dfyb` import error (spec updated only if needed).
- No behavior changes — all extractions are mechanical moves.

## Wrap-up

- Push the branch: `git push -u origin phase-0b-1-services`. Confirm `git log origin/phase-0b-1-services..HEAD` is empty.
- Open a PR (base `main`). Verify `gh pr diff <n> --name-only` lists the expected files and the PR's CI shows the new test count.

## Deferred to Phase 0b-2 (next plan)

- `CountdownPopup` / `BreakConfigPanel` / `BreakApp` → `dfyb/ui/`; `BreakConfig` → `dfyb/breaks/config.py`; design tokens (`COLORS`, `FONT_SIZES`, spacing, radii) → `dfyb/ui/tokens.py`.
- #2 focus-bug verification + regression.
- These are verified by **launching the app** (Tk widgets can't be unit-tested headlessly).

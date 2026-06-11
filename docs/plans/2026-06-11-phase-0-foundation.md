# Phase 0 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the testing/CI foundation, create the event-log spine, and extract the safe pure logic out of `launch.py` — without touching the risky UI classes yet.

**Architecture:** Introduce a `dfyb/` package alongside `launch.py`. Move Tk-free logic (version compare, duration conversion) into importable modules with unit tests. Add a new append-only `EventLog` (JSON Lines) that will later feed both the scheduler (Phase 1) and insights (Phase 3). `launch.py` stays the entry point and imports the extracted functions, so runtime behavior is unchanged.

**Tech Stack:** Python 3 (stdlib), pytest, GitHub Actions, customtkinter (runtime only).

**Scope note:** This is the first slice of Phase 0. The heavier modularization (`CountdownPopup`, `BreakConfigPanel`, `BreakApp` → `ui/`, plus `sound/`/`updater/`/`persistence/` split and the #2 focus-bug regression) is intentionally deferred to a **Phase 0b** plan. This slice delivers green CI, real test coverage, and the event-log spine with minimal risk.

**Repo conventions:**
- This repo is under `~/data/projects/`, so commits auto-use the personal Git identity (`yairshachar@gmail.com`) via the `includeIf` routing. No per-commit identity flags needed.
- Commit messages: concise summary only, conventional-commit prefix (the release script keys off `feat`/`!:` for semver). No co-author trailer.
- Running `python launch.py` from the repo root keeps `import dfyb` working (root is on `sys.path[0]`).

---

### Task 1: Project scaffolding (package, deps, pytest harness)

**Files:**
- Create: `dfyb/__init__.py`
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `pyproject.toml`
- Test: `tests/test_smoke.py`

- [ ] **Step 1: Write the failing smoke test**

Create `tests/test_smoke.py`:
```python
def test_dfyb_package_imports():
    import dfyb  # noqa: F401
```

- [ ] **Step 2: Create the pytest config and dependency manifests**

Create `pyproject.toml`:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```
(`pythonpath = ["."]` puts the repo root on `sys.path` so `import dfyb` resolves under pytest.)

Create `requirements.txt`:
```text
# Runtime dependencies
customtkinter==5.2.2
```

Create `requirements-dev.txt`:
```text
-r requirements.txt
pytest>=8,<9
pyinstaller
```

- [ ] **Step 3: Install dev dependencies into the venv**

Run: `.venv/bin/pip install -r requirements-dev.txt`
Expected: pytest (and the rest) installed without error.

- [ ] **Step 4: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_smoke.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'dfyb'` (pytest now runs; the package doesn't exist yet)

- [ ] **Step 5: Create the package**

Create `dfyb/__init__.py`:
```python
"""Don't Forget Your Breaks — application package."""
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_smoke.py -q`
Expected: PASS (1 passed)

- [ ] **Step 7: Commit**

```bash
git add dfyb/__init__.py requirements.txt requirements-dev.txt pyproject.toml tests/test_smoke.py
git commit -m "chore: add dfyb package, dependency manifests, and pytest harness"
```

---

### Task 2: GitHub Actions CI (headless pytest)

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create the workflow**

Create `.github/workflows/ci.yml`:
```yaml
name: CI

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install dev dependencies
        run: pip install -r requirements-dev.txt
      - name: Run tests (headless)
        run: pytest -q
```
Notes: runs on Linux with no display. The tested modules (`dfyb.version`, `dfyb.breaks.duration`, `dfyb.activity.event_log`) are pure stdlib and never import `customtkinter`/`tkinter`, so they run headless.

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: run pytest on push and pull_request"
```

- [ ] **Step 3: Push and verify the run is green**

```bash
git push origin main
GH_CONFIG_DIR=~/.config/gh-personal gh run list --limit 1
```
Expected: the latest run for `CI` completes with conclusion `success`. (Use `GH_CONFIG_DIR=~/.config/gh-personal gh run watch` to follow it.)

---

### Task 3: Extract pure version logic into `dfyb/version.py`

**Files:**
- Create: `dfyb/version.py`
- Modify: `launch.py` (remove local `parse_version`/`is_newer_version` defs at lines 183-188 and 209-211; add import)
- Test: `tests/test_version.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_version.py`:
```python
from dfyb.version import parse_version, is_newer_version


def test_parse_basic():
    assert parse_version("1.2.3") == (1, 2, 3)


def test_parse_strips_leading_v():
    assert parse_version("v1.0.13") == (1, 0, 13)


def test_parse_invalid_returns_zeros():
    assert parse_version("not-a-version") == (0, 0, 0)
    assert parse_version(None) == (0, 0, 0)


def test_is_newer_true():
    assert is_newer_version("1.0.13", "1.0.12") is True


def test_is_newer_false_when_equal():
    assert is_newer_version("1.0.13", "1.0.13") is False


def test_is_newer_false_when_older():
    assert is_newer_version("1.0.11", "1.0.13") is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_version.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'dfyb.version'`

- [ ] **Step 3: Create the module**

Create `dfyb/version.py`:
```python
"""Pure version-string helpers (no Tk, no I/O)."""


def parse_version(version_str):
    """Parse a version string like '1.0.3' into a tuple of ints for comparison."""
    try:
        return tuple(int(x) for x in version_str.lstrip('v').split('.'))
    except (ValueError, AttributeError):
        return (0, 0, 0)


def is_newer_version(latest, current):
    """Return True if latest version is newer than current."""
    return parse_version(latest) > parse_version(current)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_version.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Rewire `launch.py` to import instead of defining**

In `launch.py`, delete the local function definitions:
```python
def parse_version(version_str):
    """Parse a version string like '1.0.3' into a tuple of ints for comparison."""
    try:
        return tuple(int(x) for x in version_str.lstrip('v').split('.'))
    except (ValueError, AttributeError):
        return (0, 0, 0)
```
and
```python
def is_newer_version(latest, current):
    """Return True if latest version is newer than current."""
    return parse_version(latest) > parse_version(current)
```

Then add an import near the top of `launch.py`, immediately after the existing `from pathlib import Path` line:
```python
from dfyb.version import parse_version, is_newer_version
```
(`get_current_version` and `fetch_latest_version` stay in `launch.py` for now — they depend on module constants and are extracted in Phase 0b.)

- [ ] **Step 6: Smoke-test that the app still imports and runs**

Run: `timeout 5 .venv/bin/python launch.py; echo "exit=$? (124=ran fine until timed out)"`
Expected: `exit=124` with no traceback (window opened, then killed).

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (all tests)

- [ ] **Step 8: Commit**

```bash
git add dfyb/version.py tests/test_version.py launch.py
git commit -m "refactor: extract pure version helpers into dfyb.version with tests"
```

---

### Task 4: Extract pure duration conversion into `dfyb/breaks/duration.py`

**Files:**
- Create: `dfyb/breaks/__init__.py`
- Create: `dfyb/breaks/duration.py`
- Modify: `launch.py` (`BreakConfig.get_interval_seconds` lines 280-289 and `get_duration_seconds` lines 291-300; add import)
- Test: `tests/test_duration.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_duration.py`:
```python
from dfyb.breaks.duration import to_seconds


def test_seconds_pass_through():
    assert to_seconds(45, "sec") == 45


def test_minutes_to_seconds():
    assert to_seconds(25, "min") == 25 * 60


def test_hours_to_seconds():
    assert to_seconds(2, "hour") == 2 * 3600


def test_unknown_unit_matches_legacy_hour_behavior():
    # Legacy code's final `else` branch multiplied by 3600 for any non-sec/min unit.
    assert to_seconds(1, "fortnight") == 3600
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_duration.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'dfyb.breaks'`

- [ ] **Step 3: Create the modules**

Create `dfyb/breaks/__init__.py`:
```python
"""Break domain logic."""
```

Create `dfyb/breaks/duration.py`:
```python
"""Pure time-unit conversion (no Tk)."""


def to_seconds(value, unit):
    """Convert an integer value + unit ('sec'/'min'/'hour') to seconds.

    Any unit other than 'sec'/'min' is treated as hours, preserving the
    original behavior in launch.py.
    """
    if unit == "sec":
        return value
    if unit == "min":
        return value * 60
    return value * 3600
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_duration.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Rewire `BreakConfig` to delegate to `to_seconds`**

In `launch.py`, add the import after the `from dfyb.version import ...` line:
```python
from dfyb.breaks.duration import to_seconds
```

Replace `BreakConfig.get_interval_seconds`:
```python
    def get_interval_seconds(self):
        """Convert interval to seconds."""
        val = self._safe_int(self.interval_value)
        unit = self.interval_unit.get()
        if unit == "sec":
            return val
        elif unit == "min":
            return val * 60
        else:  # hour
            return val * 3600
```
with:
```python
    def get_interval_seconds(self):
        """Convert interval to seconds."""
        return to_seconds(self._safe_int(self.interval_value), self.interval_unit.get())
```

Replace `BreakConfig.get_duration_seconds`:
```python
    def get_duration_seconds(self):
        """Convert duration to seconds."""
        val = self._safe_int(self.duration_value)
        unit = self.duration_unit.get()
        if unit == "sec":
            return val
        elif unit == "min":
            return val * 60
        else:  # hour
            return val * 3600
```
with:
```python
    def get_duration_seconds(self):
        """Convert duration to seconds."""
        return to_seconds(self._safe_int(self.duration_value), self.duration_unit.get())
```

- [ ] **Step 6: Smoke-test the app**

Run: `timeout 5 .venv/bin/python launch.py; echo "exit=$? (124=ran fine)"`
Expected: `exit=124`, no traceback.

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (all tests)

- [ ] **Step 8: Commit**

```bash
git add dfyb/breaks/__init__.py dfyb/breaks/duration.py tests/test_duration.py launch.py
git commit -m "refactor: extract pure duration conversion into dfyb.breaks.duration with tests"
```

---

### Task 5: Create the event-log spine `dfyb/activity/event_log.py`

**Files:**
- Create: `dfyb/activity/__init__.py`
- Create: `dfyb/activity/event_log.py`
- Test: `tests/test_event_log.py`

This module is **additive** — nothing in `launch.py` wires to it yet (the scheduler does that in Phase 1). It is the shared core the spec describes.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_event_log.py`:
```python
from dfyb.activity.event_log import EventLog, BREAK_TAKEN, BREAK_SKIPPED


class FakeClock:
    """Deterministic monotonically-increasing clock for tests."""
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        self.t += 1
        return self.t


def test_append_returns_event(tmp_path):
    log = EventLog(tmp_path / "events.jsonl", clock=FakeClock())
    event = log.append(BREAK_TAKEN, break_name="Micro Break")
    assert event["type"] == BREAK_TAKEN
    assert event["data"] == {"break_name": "Micro Break"}
    assert event["ts"] == 1001.0


def test_read_empty_when_no_file(tmp_path):
    log = EventLog(tmp_path / "missing.jsonl")
    assert log.read() == []


def test_append_then_read_roundtrip(tmp_path):
    log = EventLog(tmp_path / "events.jsonl", clock=FakeClock())
    log.append(BREAK_TAKEN, break_name="A")
    log.append(BREAK_SKIPPED, break_name="B")
    events = log.read()
    assert [e["type"] for e in events] == [BREAK_TAKEN, BREAK_SKIPPED]
    assert events[1]["data"]["break_name"] == "B"


def test_persists_across_instances(tmp_path):
    path = tmp_path / "events.jsonl"
    EventLog(path, clock=FakeClock()).append(BREAK_TAKEN)
    reopened = EventLog(path)
    assert reopened.count() == 1


def test_count_by_type(tmp_path):
    log = EventLog(tmp_path / "events.jsonl", clock=FakeClock())
    log.append(BREAK_TAKEN)
    log.append(BREAK_TAKEN)
    log.append(BREAK_SKIPPED)
    assert log.count(BREAK_TAKEN) == 2
    assert log.count() == 3
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_event_log.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'dfyb.activity'`

- [ ] **Step 3: Create the modules**

Create `dfyb/activity/__init__.py`:
```python
"""Activity Core — sensors and the event log."""
```

Create `dfyb/activity/event_log.py`:
```python
"""Append-only, persisted activity/break event log (JSON Lines).

The shared spine of the app: the scheduler (Phase 1) reads it to decide when
to nudge, and insights (Phase 3) read it to build dashboards. Pass a custom
`clock` for deterministic tests.
"""
import json
import time
from pathlib import Path

# Event type constants (extended as later phases need them).
BREAK_DUE = "break_due"
BREAK_TAKEN = "break_taken"
BREAK_SKIPPED = "break_skipped"
BREAK_SNOOZED = "break_snoozed"
IDLE_DETECTED = "idle_detected"


class EventLog:
    """Append-only JSON Lines event store."""

    def __init__(self, path, clock=time.time):
        self.path = Path(path)
        self._clock = clock

    def append(self, event_type, **data):
        """Append an event and return it. Each event: {ts, type, data}."""
        event = {"ts": self._clock(), "type": event_type, "data": data}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
        return event

    def read(self):
        """Return all events as a list of dicts (empty if the file is absent)."""
        if not self.path.exists():
            return []
        events = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events

    def count(self, event_type=None):
        """Count all events, or only those of `event_type`."""
        if event_type is None:
            return len(self.read())
        return sum(1 for e in self.read() if e["type"] == event_type)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_event_log.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add dfyb/activity/__init__.py dfyb/activity/event_log.py tests/test_event_log.py
git commit -m "feat: add append-only EventLog spine in dfyb.activity with tests"
```

---

### Task 6: Fix the README dependency docs (closes #15)

**Files:**
- Modify: `README.md` (Requirements section and Installation section)

- [ ] **Step 1: Update the Requirements section**

In `README.md`, replace the Requirements block:
```markdown
## Requirements

- Python 3.x
- Tkinter (included with Python on most systems)
```
with:
```markdown
## Requirements

- Python 3.x
- Tkinter (included with Python on most systems)
- [`customtkinter`](https://customtkinter.tomschimansky.com/) — installed via `requirements.txt`
```

- [ ] **Step 2: Update the Installation section**

Replace the Installation step that runs the app:
```markdown
2. Run the application:
   ```bash
   python launch.py
   ```
```
with:
```markdown
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the application:
   ```bash
   python launch.py
   ```
```

- [ ] **Step 3: Verify the docs mention the dependency**

Run: `grep -n customtkinter README.md`
Expected: at least two matches (Requirements + a requirements.txt reference).

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document customtkinter dependency and pip install step (closes #15)"
```

---

## Definition of done (this slice)

- `pytest -q` passes locally and in CI (green check on `main`).
- `dfyb.version`, `dfyb.breaks.duration`, and `dfyb.activity.event_log` exist with tests; `launch.py` imports the first two and still runs.
- `requirements.txt` / `requirements-dev.txt` exist; README documents the dependency (#15 closeable).
- The `EventLog` spine is in place, ready for the Phase 1 scheduler to write to.

## Deferred to Phase 0b (next plan)

- Modularize the Tk classes: `CountdownPopup`, `BreakConfigPanel`, `BreakApp` → `dfyb/ui/`.
- Extract `sound/`, `updater/` (incl. `get_current_version`/`fetch_latest_version` + their constants), `persistence/`.
- #2 focus-bug verification + regression coverage (needs the UI extraction first).
- Confirm the PyInstaller build still bundles the new `dfyb` package (add to `hiddenimports` in the `.spec` only if a build shows it's needed).

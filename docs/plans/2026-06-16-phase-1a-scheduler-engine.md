# Phase 1a — Scheduling Engine + Sensors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pure, fully-tested scheduling brain (`dfyb/scheduler/engine.py`) and the macOS context sensors (`dfyb/activity/sensors.py`) that will drive "earn the interruption" — with no integration into the running app yet.

**Architecture:** A pure `step(states, ctx)` decision function (no Tk, no I/O) decides fire/defer/natural-break from a `Context` snapshot. Sensors read macOS idle time + fullscreen via lazily-imported `pyobjc` (Quartz), returning safe defaults off-macOS or on any failure. Everything here is unit-tested; the timer-loop integration is the separate Phase 1b.

**Tech Stack:** Python 3 (stdlib + dataclasses), pytest, `pyobjc-framework-Quartz` (macOS-only, via env marker).

**Spec:** `docs/specs/2026-06-16-phase-1-perfect-timing-design.md`

**Repo conventions:**
- Repo under `~/data/projects/` → commits auto-use the personal Git identity. No identity flags.
- Use `.venv/bin/python` / `.venv/bin/pip`.
- Conventional-commit messages, summary only, no co-author trailer.
- **Push the branch before opening any PR, and verify the PR diff + CI test count** before claiming done (lesson from PR #16/#18).

**Pre-flight (run once before Task 1):**
```bash
cd ~/data/projects/dont_forget_your_breaks
git checkout main && git pull --ff-only origin main
git checkout -b phase-1a-scheduler
.venv/bin/python -m pytest -q    # baseline: 32 passed
```

---

### Task 1: The pure scheduling engine `dfyb/scheduler/engine.py`

**Files:**
- Create: `dfyb/scheduler/__init__.py`
- Create: `dfyb/scheduler/engine.py`
- Test: `tests/test_scheduler_engine.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scheduler_engine.py`:
```python
from dfyb.scheduler.engine import (
    Context, BreakState, step, decide, is_natural_break, FIRE, DEFER,
)


def ctx(idle=0.0, fullscreen=False):
    return Context(idle_seconds=idle, is_fullscreen=fullscreen)


def test_is_natural_break_threshold():
    assert is_natural_break(300) is True
    assert is_natural_break(299) is False
    assert is_natural_break(10, threshold=5) is True


def test_decide_fire_when_active():
    assert decide(ctx(idle=0, fullscreen=False)) == FIRE


def test_decide_defer_when_fullscreen():
    assert decide(ctx(idle=0, fullscreen=True)) == DEFER


def test_decide_defer_when_away():
    assert decide(ctx(idle=120, fullscreen=False)) == DEFER


def test_step_natural_break_resets_all():
    states = [BreakState(remaining=5, interval_seconds=100, duration_seconds=5),
              BreakState(remaining=8, interval_seconds=200, duration_seconds=600)]
    r = step(states, ctx(idle=300))
    assert r.natural_break is True
    assert r.new_remaining == [100, 200]
    assert r.fire_index is None and r.defer_reason is None


def test_step_decrements_when_not_due():
    states = [BreakState(remaining=5, interval_seconds=100, duration_seconds=5)]
    r = step(states, ctx(idle=0))
    assert r.new_remaining == [4]
    assert r.natural_break is False and r.fire_index is None and r.defer_reason is None


def test_step_fires_when_due_and_active():
    states = [BreakState(remaining=1, interval_seconds=100, duration_seconds=5)]
    r = step(states, ctx(idle=0))
    assert r.fire_index == 0
    assert r.new_remaining == [100]  # reset to interval


def test_step_fire_picks_longest_duration():
    states = [BreakState(remaining=1, interval_seconds=100, duration_seconds=5),
              BreakState(remaining=1, interval_seconds=200, duration_seconds=600)]
    r = step(states, ctx(idle=0))
    assert r.fire_index == 1               # longer duration wins
    assert r.new_remaining == [100, 200]   # both due breaks reset


def test_step_defers_on_fullscreen_and_clamps():
    states = [BreakState(remaining=1, interval_seconds=100, duration_seconds=5)]
    r = step(states, ctx(idle=0, fullscreen=True))
    assert r.defer_reason == "fullscreen"
    assert r.fire_index is None
    assert r.new_remaining == [0]          # clamped, stays due


def test_step_defers_when_away_and_clamps():
    states = [BreakState(remaining=1, interval_seconds=100, duration_seconds=5)]
    r = step(states, ctx(idle=120, fullscreen=False))
    assert r.defer_reason == "away"
    assert r.new_remaining == [0]


def test_step_deferred_break_stays_due_next_tick():
    states = [BreakState(remaining=0, interval_seconds=100, duration_seconds=5)]
    r = step(states, ctx(idle=0, fullscreen=True))
    assert r.defer_reason == "fullscreen"
    assert r.new_remaining == [0]          # -1 then clamped back to 0


def test_step_thresholds_are_parameterizable():
    states = [BreakState(remaining=1, interval_seconds=100, duration_seconds=5)]
    # idle 10 with away_threshold 5 -> defer; natural_threshold high so not natural
    r = step(states, ctx(idle=10), natural_threshold=300, away_threshold=5)
    assert r.defer_reason == "away"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_scheduler_engine.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'dfyb.scheduler'`

- [ ] **Step 3: Create the package + engine**

Create `dfyb/scheduler/__init__.py`:
```python
"""Scheduling brain — the pure 'earn the interruption' decision logic."""
```

Create `dfyb/scheduler/engine.py`:
```python
"""Pure scheduling brain: decide fire/defer/natural-break from a Context. No Tk, no I/O."""
from dataclasses import dataclass

# Configurable thresholds (can surface to a settings UI in a later phase).
NATURAL_BREAK_IDLE_THRESHOLD_SECONDS = 300  # idle >= this => natural break (reset all timers)
AWAY_IDLE_THRESHOLD_SECONDS = 60            # idle >= this at fire time => defer (briefly away)

FIRE = "fire"
DEFER = "defer"


@dataclass(frozen=True)
class Context:
    """What the sensors observed this tick."""
    idle_seconds: float
    is_fullscreen: bool


@dataclass(frozen=True)
class BreakState:
    """Plain, Tk-free snapshot of one break, parallel to the configs."""
    remaining: int          # seconds left on this break's countdown
    interval_seconds: int   # reset value (BreakConfig.get_interval_seconds())
    duration_seconds: int   # how long the break lasts (used for "longest wins")


@dataclass(frozen=True)
class StepResult:
    """What the loop should do this tick."""
    new_remaining: list             # updated `remaining` per break (write back to configs)
    natural_break: bool = False
    fire_index: int | None = None   # which break to pop
    defer_reason: str | None = None  # "fullscreen" | "away"


def is_natural_break(idle_seconds, threshold=NATURAL_BREAK_IDLE_THRESHOLD_SECONDS):
    """True if the user has been idle long enough to count as having taken a break."""
    return idle_seconds >= threshold


def decide(ctx, away_threshold=AWAY_IDLE_THRESHOLD_SECONDS):
    """Decide whether a due break should FIRE or DEFER given the current context."""
    if ctx.is_fullscreen:
        return DEFER          # don't interrupt fullscreen
    if ctx.idle_seconds >= away_threshold:
        return DEFER          # briefly away — wait until back and active
    return FIRE


def step(states, ctx,
         natural_threshold=NATURAL_BREAK_IDLE_THRESHOLD_SECONDS,
         away_threshold=AWAY_IDLE_THRESHOLD_SECONDS):
    """Advance one 1-second tick. Returns a StepResult describing what to do.

    `states` is a list[BreakState] parallel to the app's break configs.
    """
    # 1. Natural break: idle long enough -> reset all timers, do not decrement.
    if is_natural_break(ctx.idle_seconds, natural_threshold):
        return StepResult(new_remaining=[s.interval_seconds for s in states],
                          natural_break=True)

    # 2. Decrement; collect breaks that are now due.
    new_remaining = [s.remaining - 1 for s in states]
    due = [i for i, r in enumerate(new_remaining) if r <= 0]

    # 3. If any are due, decide fire vs defer.
    if due:
        if decide(ctx, away_threshold) == DEFER:
            reason = "fullscreen" if ctx.is_fullscreen else "away"
            for i in due:
                new_remaining[i] = 0          # clamp — stays due, no negative drift
            return StepResult(new_remaining=new_remaining, defer_reason=reason)
        # FIRE: pop the longest-duration due break; reset all due breaks.
        fire_index = max(due, key=lambda i: states[i].duration_seconds)
        for i in due:
            new_remaining[i] = states[i].interval_seconds
        return StepResult(new_remaining=new_remaining, fire_index=fire_index)

    # 4. Nothing due — just the decremented counters.
    return StepResult(new_remaining=new_remaining)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_scheduler_engine.py -q`
Expected: PASS (12 passed)

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (44 passed)

- [ ] **Step 6: Commit**

```bash
git add dfyb/scheduler/__init__.py dfyb/scheduler/engine.py tests/test_scheduler_engine.py
git commit -m "feat: add pure scheduling engine (fire/defer/natural-break) with tests"
```

---

### Task 2: Add the two new event-type constants

**Files:**
- Modify: `dfyb/activity/event_log.py` (add two constants after the existing ones)
- Test: `tests/test_event_log.py` (append one test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_event_log.py`:
```python
def test_phase1_event_constants_exist():
    from dfyb.activity.event_log import BREAK_DEFERRED, NATURAL_BREAK
    assert BREAK_DEFERRED == "break_deferred"
    assert NATURAL_BREAK == "natural_break"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_event_log.py::test_phase1_event_constants_exist -q`
Expected: FAIL — `ImportError: cannot import name 'BREAK_DEFERRED'`

- [ ] **Step 3: Add the constants**

In `dfyb/activity/event_log.py`, find the existing event-type constant block:
```python
BREAK_DUE = "break_due"
BREAK_TAKEN = "break_taken"
BREAK_SKIPPED = "break_skipped"
BREAK_SNOOZED = "break_snoozed"
IDLE_DETECTED = "idle_detected"
```
and add two lines immediately after it:
```python
BREAK_DEFERRED = "break_deferred"
NATURAL_BREAK = "natural_break"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_event_log.py -q`
Expected: PASS (6 passed in this file)

- [ ] **Step 5: Commit**

```bash
git add dfyb/activity/event_log.py tests/test_event_log.py
git commit -m "feat: add BREAK_DEFERRED and NATURAL_BREAK event types"
```

---

### Task 3: macOS context sensors `dfyb/activity/sensors.py`

**Files:**
- Create: `dfyb/activity/sensors.py`
- Modify: `requirements.txt` (add `pyobjc-framework-Quartz` with a macOS marker)
- Test: `tests/test_sensors.py`

**Critical:** `pyobjc-framework-Quartz` is macOS-only — it MUST carry a `sys_platform == "darwin"` env marker or the Linux CI `pip install` will fail. The sensors import `Quartz` *lazily inside each function* so that `import dfyb.activity.sensors` works on CI (no Quartz needed); tests inject a fake `Quartz` module.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sensors.py`:
```python
import sys
import types

import dfyb.activity.sensors as sensors


def _fake_quartz_idle(value):
    fake = types.ModuleType("Quartz")
    fake.kCGEventSourceStateHIDSystemState = 1
    fake.kCGAnyInputEventType = 0xFFFFFFFF
    fake.CGEventSourceSecondsSinceLastEventType = lambda state, evtype: value
    return fake


def _fake_quartz_windows(windows, screen=(1920, 1080)):
    fake = types.ModuleType("Quartz")
    fake.kCGWindowListOptionOnScreenOnly = 1
    fake.kCGWindowListExcludeDesktopElements = 16
    fake.kCGNullWindowID = 0
    fake.CGMainDisplayID = lambda: 1
    fake.CGDisplayPixelsWide = lambda d: screen[0]
    fake.CGDisplayPixelsHigh = lambda d: screen[1]
    fake.CGWindowListCopyWindowInfo = lambda opts, wid: windows
    return fake


def test_idle_seconds_non_darwin_is_zero(monkeypatch):
    monkeypatch.setattr(sensors.sys, "platform", "linux")
    assert sensors.idle_seconds() == 0.0


def test_idle_seconds_darwin_success(monkeypatch):
    monkeypatch.setitem(sys.modules, "Quartz", _fake_quartz_idle(42.5))
    monkeypatch.setattr(sensors.sys, "platform", "darwin")
    assert sensors.idle_seconds() == 42.5


def test_idle_seconds_failure_returns_zero(monkeypatch):
    fake = _fake_quartz_idle(0)
    def boom(*a, **k):
        raise RuntimeError("quartz boom")
    fake.CGEventSourceSecondsSinceLastEventType = boom
    monkeypatch.setitem(sys.modules, "Quartz", fake)
    monkeypatch.setattr(sensors.sys, "platform", "darwin")
    assert sensors.idle_seconds() == 0.0


def test_fullscreen_non_darwin_is_false(monkeypatch):
    monkeypatch.setattr(sensors.sys, "platform", "linux")
    assert sensors.frontmost_is_fullscreen() is False


def test_fullscreen_true_when_window_covers_screen(monkeypatch):
    win = {"kCGWindowLayer": 0, "kCGWindowBounds": {"Width": 1920, "Height": 1080}}
    monkeypatch.setitem(sys.modules, "Quartz", _fake_quartz_windows([win]))
    monkeypatch.setattr(sensors.sys, "platform", "darwin")
    assert sensors.frontmost_is_fullscreen() is True


def test_fullscreen_false_for_small_window(monkeypatch):
    win = {"kCGWindowLayer": 0, "kCGWindowBounds": {"Width": 800, "Height": 600}}
    monkeypatch.setitem(sys.modules, "Quartz", _fake_quartz_windows([win]))
    monkeypatch.setattr(sensors.sys, "platform", "darwin")
    assert sensors.frontmost_is_fullscreen() is False


def test_read_context_combines_sensors(monkeypatch):
    monkeypatch.setattr(sensors, "idle_seconds", lambda: 12.0)
    monkeypatch.setattr(sensors, "frontmost_is_fullscreen", lambda: True)
    c = sensors.read_context()
    assert c.idle_seconds == 12.0 and c.is_fullscreen is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_sensors.py -q`
Expected: FAIL — `AttributeError: module 'dfyb.activity.sensors' has no attribute ...` / `ModuleNotFoundError` (the module doesn't exist yet)

- [ ] **Step 3: Create the sensors module**

Create `dfyb/activity/sensors.py`:
```python
"""macOS context sensors (idle time, fullscreen) for the scheduler.

Best-effort: on non-macOS or any failure, returns safe defaults (idle=0.0,
fullscreen=False) so the scheduler falls back to today's 'always fire' behavior.
`Quartz` is imported lazily inside each function so this module imports cleanly
on non-macOS CI (where Quartz is absent).
"""
import sys

from dfyb.scheduler.engine import Context


def idle_seconds():
    """Seconds since the last user input event (macOS). 0.0 elsewhere / on failure."""
    if sys.platform != "darwin":
        return 0.0
    try:
        import Quartz
        return float(Quartz.CGEventSourceSecondsSinceLastEventType(
            Quartz.kCGEventSourceStateHIDSystemState,
            Quartz.kCGAnyInputEventType,
        ))
    except Exception:
        return 0.0


def frontmost_is_fullscreen():
    """Best-effort: is the frontmost on-screen window covering the full display?

    False on non-macOS or any failure (fails safe — 'not fullscreen' => fire).
    Heuristic: the first layer-0 (normal app) window in front-to-back order whose
    bounds cover the main display is treated as fullscreen.
    """
    if sys.platform != "darwin":
        return False
    try:
        import Quartz
        display = Quartz.CGMainDisplayID()
        screen_w = Quartz.CGDisplayPixelsWide(display)
        screen_h = Quartz.CGDisplayPixelsHigh(display)
        windows = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID,
        )
        for window in windows:
            if window.get("kCGWindowLayer", 1) != 0:
                continue  # skip menu bar, dock, overlays — only normal app windows
            bounds = window.get("kCGWindowBounds", {})
            return (bounds.get("Width", 0) >= screen_w
                    and bounds.get("Height", 0) >= screen_h)
        return False
    except Exception:
        return False


def read_context():
    """Snapshot the current context for the scheduler."""
    return Context(idle_seconds=idle_seconds(), is_fullscreen=frontmost_is_fullscreen())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_sensors.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Add the dependency (with the macOS marker)**

In `requirements.txt`, change:
```text
# Runtime dependencies
customtkinter==5.2.2
```
to:
```text
# Runtime dependencies
customtkinter==5.2.2
# macOS-only: idle/fullscreen sensors. The env marker keeps Linux CI from trying
# to install it (pyobjc wheels are macOS-only).
pyobjc-framework-Quartz; sys_platform == "darwin"
```

- [ ] **Step 6: Install it locally (macOS) so the real sensors work for Phase 1b**

Run: `.venv/bin/pip install -r requirements.txt 2>&1 | tail -3`
Expected: `pyobjc-framework-Quartz` installs without error (on this macOS machine).

- [ ] **Step 7: Sanity-check the real sensors actually return values on this Mac**

Run: `.venv/bin/python -c "from dfyb.activity.sensors import read_context; c = read_context(); print(c)"`
Expected: prints a `Context(idle_seconds=<a small float>, is_fullscreen=<True/False>)` — confirms the real Quartz path works (idle should be a low number right after you run it).

- [ ] **Step 8: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (52 passed)

- [ ] **Step 9: Commit**

```bash
git add dfyb/activity/sensors.py tests/test_sensors.py requirements.txt
git commit -m "feat: add macOS idle/fullscreen sensors with safe fallbacks and tests"
```

---

## Definition of done (Phase 1a)

- `dfyb/scheduler/engine.py` exists with `Context`/`BreakState`/`StepResult`/`is_natural_break`/`decide`/`step`, fully unit-tested.
- `dfyb/activity/sensors.py` exists with `idle_seconds`/`frontmost_is_fullscreen`/`read_context`, tested with a fake Quartz; imports cleanly on CI; returns real values on this Mac.
- `BREAK_DEFERRED` / `NATURAL_BREAK` event constants added.
- `requirements.txt` adds `pyobjc-framework-Quartz` with a `sys_platform == "darwin"` marker (CI install stays green).
- `pytest -q` passes locally and in CI (expected total: **52**).
- No behavior change to the running app yet.

## Wrap-up

- Push: `git push -u origin phase-1a-scheduler`; confirm `git log origin/phase-1a-scheduler..HEAD` is empty.
- Open a PR (base `main`). Verify `gh pr diff <n> --name-only` lists the expected files and the PR's CI shows 51 tests.

## Next (Phase 1b — separate plan)

Wire `read_context()` + `step()` + the `EventLog` into `BreakApp.timer_loop` (translate ctk configs ↔ `BreakState`, apply `StepResult`, dedup episode logging, create the `EventLog` instance, log `BREAK_TAKEN` on popup close with `used_seconds`). Verified by launching the app.

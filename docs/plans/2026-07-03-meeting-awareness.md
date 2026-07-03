# Meeting / Call Awareness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Note:** the risky part (CoreAudio mic-in-use) was already spiked and validated; the exact working call is in Task 2. Task 3 ends with a short human live check.

**Goal:** Breaks defer while the microphone is in use (≈ in a call, including browser calls), user-toggleable via a Settings checkbox.

**Architecture:** Extend the existing sensor → `Context` → scheduler pipeline. A new `microphone_in_use()` sensor feeds a new `Context.is_meeting`; `decide()`/`step()` defer on it with a `"meeting"` reason; a `defer_during_meetings` pref (default on) gates the signal via `read_context(check_meeting=...)`.

**Tech Stack:** Python 3, pyobjc (CoreAudio), CustomTkinter, pytest.

**Spec:** `~/daily/specs/2026-07-03-meeting-awareness-design.md`

## Global Constraints

- **Coverage = any call incl. browser** → the signal is **microphone-in-use** (CoreAudio `kAudioDevicePropertyDeviceIsRunningSomewhere` on the default input device), not meeting-app detection.
- **Defer priority: fullscreen → meeting → away** (the reason logged when multiple apply).
- **Configurable:** `defer_during_meetings` pref, default **True**, read with `.get(key, default)` (backward-compatible); a Settings checkbox toggles it. The pref gates the signal through `read_context(check_meeting=...)` — the sensor stays honest.
- **Platform-guarded:** all CoreAudio access `sys.platform == "darwin"`-gated + `try/except → False` (fails safe: breaks fire normally).
- **No hardcoded values;** reuse existing tokens/patterns (mirror `always_on_top`).
- **Tests:** `pytest`, `.venv/bin/python -m pytest -q`. Baseline: **79 passed**.
- **Commits:** conventional-commit summary only, no body, no co-author trailer.

## Repo conventions

- Use `.venv/bin/python` / `.venv/bin/pip`. Personal git identity is automatic.
- `gh` uses personal config: `GH_CONFIG_DIR="$HOME/.config/gh-personal"`.
- Push before PR; verify PR diff + CI test count.

## Pre-flight (run once before Task 1)

```bash
cd ~/data/projects/dont_forget_your_breaks
git checkout main && git pull --ff-only origin main
.venv/bin/python -m pytest -q            # baseline: 79 passed
.venv/bin/python -c "import CoreAudio; print('CoreAudio present')"   # spike dep already installed
git checkout -b meeting-awareness
```

---

### Task 1: Scheduler — `is_meeting` defer (pure, TDD)

**Files:**
- Modify: `dfyb/scheduler/engine.py` (`Context`, `decide`, `step`)
- Test: `tests/test_scheduler_engine.py`

**Interfaces:**
- Produces: `Context(idle_seconds, is_fullscreen, is_meeting=False)`; `decide()`/`step()` defer when `is_meeting` with `reason="meeting"`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_scheduler_engine.py`:
```python
from dfyb.scheduler.engine import Context, BreakState, decide, step, DEFER, FIRE


def test_decide_defers_during_meeting():
    assert decide(Context(idle_seconds=0.0, is_fullscreen=False, is_meeting=True)) == DEFER


def test_decide_fires_when_not_meeting_fullscreen_or_away():
    assert decide(Context(idle_seconds=0.0, is_fullscreen=False, is_meeting=False)) == FIRE


def test_step_defer_reason_meeting():
    states = [BreakState(remaining=1, interval_seconds=100, duration_seconds=5)]
    result = step(states, Context(idle_seconds=0.0, is_fullscreen=False, is_meeting=True))
    assert result.defer_reason == "meeting"
    assert result.fire_index is None
    assert result.new_remaining == [0]


def test_step_fullscreen_takes_precedence_over_meeting():
    states = [BreakState(remaining=1, interval_seconds=100, duration_seconds=5)]
    result = step(states, Context(idle_seconds=0.0, is_fullscreen=True, is_meeting=True))
    assert result.defer_reason == "fullscreen"


def test_context_is_meeting_defaults_false():
    assert Context(idle_seconds=0.0, is_fullscreen=False).is_meeting is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_scheduler_engine.py -q`
Expected: FAIL — `Context.__init__() got an unexpected keyword argument 'is_meeting'` (and reason assertions).

- [ ] **Step 3: Add `is_meeting` to `Context`**

In `dfyb/scheduler/engine.py`, change:
```python
@dataclass(frozen=True)
class Context:
    """What the sensors observed this tick."""
    idle_seconds: float
    is_fullscreen: bool
```
to:
```python
@dataclass(frozen=True)
class Context:
    """What the sensors observed this tick."""
    idle_seconds: float
    is_fullscreen: bool
    is_meeting: bool = False
```

- [ ] **Step 4: Add the defer rule to `decide`**

In `dfyb/scheduler/engine.py`, change:
```python
    if ctx.is_fullscreen:
        return DEFER          # don't interrupt fullscreen
    if ctx.idle_seconds >= away_threshold:
        return DEFER          # briefly away — wait until back and active
    return FIRE
```
to:
```python
    if ctx.is_fullscreen:
        return DEFER          # don't interrupt fullscreen
    if ctx.is_meeting:
        return DEFER          # don't interrupt a call (mic in use)
    if ctx.idle_seconds >= away_threshold:
        return DEFER          # briefly away — wait until back and active
    return FIRE
```

- [ ] **Step 5: Add the `"meeting"` reason to `step`**

In `dfyb/scheduler/engine.py`, change:
```python
        if decide(ctx, away_threshold) == DEFER:
            reason = "fullscreen" if ctx.is_fullscreen else "away"
```
to:
```python
        if decide(ctx, away_threshold) == DEFER:
            if ctx.is_fullscreen:
                reason = "fullscreen"
            elif ctx.is_meeting:
                reason = "meeting"
            else:
                reason = "away"
```
Also update the `StepResult.defer_reason` comment `# "fullscreen" | "away"` to `# "fullscreen" | "meeting" | "away"`.

- [ ] **Step 6: Run tests + full suite**

Run: `.venv/bin/python -m pytest tests/test_scheduler_engine.py -q` → PASS
Run: `.venv/bin/python -m pytest -q` → PASS (84 passed: 79 + 5 new)

- [ ] **Step 7: Commit**

```bash
git add dfyb/scheduler/engine.py tests/test_scheduler_engine.py
git commit -m "feat: defer breaks during meetings (is_meeting context + meeting defer reason)"
```

---

### Task 2: Sensor — `microphone_in_use()` + `read_context(check_meeting)`

**Files:**
- Modify: `dfyb/activity/sensors.py`, `requirements.txt`
- Test: `tests/test_sensors.py`

**Interfaces:**
- Consumes: `Context.is_meeting` (Task 1).
- Produces: `microphone_in_use() -> bool`; `read_context(check_meeting=True) -> Context` with `is_meeting=(check_meeting and microphone_in_use())`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_sensors.py`:
```python
def test_microphone_in_use_non_darwin_is_false(monkeypatch):
    monkeypatch.setattr(sensors.sys, "platform", "linux")
    assert sensors.microphone_in_use() is False


def test_read_context_meeting_gated_off(monkeypatch):
    monkeypatch.setattr(sensors, "idle_seconds", lambda: 0.0)
    monkeypatch.setattr(sensors, "frontmost_is_fullscreen", lambda: False)
    monkeypatch.setattr(sensors, "microphone_in_use", lambda: True)
    c = sensors.read_context(check_meeting=False)
    assert c.is_meeting is False


def test_read_context_meeting_on(monkeypatch):
    monkeypatch.setattr(sensors, "idle_seconds", lambda: 0.0)
    monkeypatch.setattr(sensors, "frontmost_is_fullscreen", lambda: False)
    monkeypatch.setattr(sensors, "microphone_in_use", lambda: True)
    c = sensors.read_context(check_meeting=True)
    assert c.is_meeting is True
```
And update the existing `test_read_context_combines_sensors` to also stub the mic (so it doesn't touch real CoreAudio):
```python
def test_read_context_combines_sensors(monkeypatch):
    monkeypatch.setattr(sensors, "idle_seconds", lambda: 12.0)
    monkeypatch.setattr(sensors, "frontmost_is_fullscreen", lambda: True)
    monkeypatch.setattr(sensors, "microphone_in_use", lambda: False)
    c = sensors.read_context()
    assert c.idle_seconds == 12.0 and c.is_fullscreen is True
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_sensors.py -q`
Expected: FAIL — `AttributeError: module 'dfyb.activity.sensors' has no attribute 'microphone_in_use'` / `read_context() got an unexpected keyword argument 'check_meeting'`.

- [ ] **Step 3: Add `struct` import + `microphone_in_use()`**

In `dfyb/activity/sensors.py`, add `import struct` at the top (next to `import sys`). Then add this function (validated CoreAudio call — the `objc.NULL` qualifier / `None` out-param convention is required):
```python
def microphone_in_use():
    """True if the default input device is running somewhere (~ mic in a call,
    incl. browser calls). False on non-macOS or any failure (fails safe)."""
    if sys.platform != "darwin":
        return False
    try:
        import CoreAudio as CA
        import objc

        def _get_u32(objid, selector):
            addr = CA.AudioObjectPropertyAddress(
                selector,
                CA.kAudioObjectPropertyScopeGlobal,
                CA.kAudioObjectPropertyElementMain,
            )
            # qualifier MUST be objc.NULL; out-param MUST be None (pyobjc allocates + returns it)
            status, _size, data = CA.AudioObjectGetPropertyData(
                objid, addr, 0, objc.NULL, 4, None)
            if status != 0:
                return None
            return struct.unpack("I", bytes(data))[0]

        device = _get_u32(CA.kAudioObjectSystemObject,
                          CA.kAudioHardwarePropertyDefaultInputDevice)
        if not device:
            return False
        return bool(_get_u32(device, CA.kAudioDevicePropertyDeviceIsRunningSomewhere))
    except Exception:
        return False
```

- [ ] **Step 4: Add `check_meeting` to `read_context`**

In `dfyb/activity/sensors.py`, change:
```python
def read_context():
    """Snapshot the current context for the scheduler."""
    return Context(idle_seconds=idle_seconds(), is_fullscreen=frontmost_is_fullscreen())
```
to:
```python
def read_context(check_meeting=True):
    """Snapshot the current context for the scheduler.

    `check_meeting` gates the meeting signal (the app's `defer_during_meetings`
    pref): when False, is_meeting is always False regardless of the mic.
    """
    return Context(
        idle_seconds=idle_seconds(),
        is_fullscreen=frontmost_is_fullscreen(),
        is_meeting=check_meeting and microphone_in_use(),
    )
```

- [ ] **Step 5: Add the dependency**

In `requirements.txt`, add a line:
```
pyobjc-framework-CoreAudio
```

- [ ] **Step 6: Run tests + full suite**

Run: `.venv/bin/python -m pytest tests/test_sensors.py -q` → PASS
Run: `.venv/bin/python -m pytest -q` → PASS (87 passed: 84 + 3 new)

- [ ] **Step 7: Commit**

```bash
git add dfyb/activity/sensors.py tests/test_sensors.py requirements.txt
git commit -m "feat: add microphone_in_use sensor + meeting-gated read_context"
```

---

### Task 3: Config + Settings toggle + timer wiring (launch-verified)

**Files:**
- Modify: `launch.py` (`__init__` pref, `_save_preferences`, Settings checkbox, `timer_loop`)

**Interfaces:**
- Consumes: `read_context(check_meeting=...)` (Task 2).

- [ ] **Step 1: Add the pref (mirror `always_on_top`)**

In `launch.py`, find:
```python
        self.always_on_top = ctk.BooleanVar(
            value=self.saved_prefs.get("always_on_top", True)
        )
        self.always_on_top.trace_add('write', self._apply_always_on_top)
        root.attributes('-topmost', self.always_on_top.get())
```
and add immediately after it:
```python
        self.defer_during_meetings = ctk.BooleanVar(
            value=self.saved_prefs.get("defer_during_meetings", True)
        )
        self.defer_during_meetings.trace_add('write', self._save_preferences)
```

- [ ] **Step 2: Persist the pref**

In `launch.py`, in `_save_preferences`, find:
```python
            "always_on_top": self.always_on_top.get(),
            "check_for_updates": self.check_for_updates.get(),
```
and add after them:
```python
            "defer_during_meetings": self.defer_during_meetings.get(),
```

- [ ] **Step 3: Add the Settings checkbox**

In `launch.py`, in `_open_settings`'s "General settings" block, find:
```python
        ctk.CTkCheckBox(
            general_frame, text="Check for updates automatically",
            variable=self.check_for_updates,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
        ).pack(padx=PADDING_PANEL_X, pady=(4, PADDING_PANEL_Y), anchor="w")
```
and add another checkbox immediately after it (adjust the preceding checkbox's bottom pad so spacing stays even — change its `pady=(4, PADDING_PANEL_Y)` to `pady=(4, 4)`):
```python
        ctk.CTkCheckBox(
            general_frame, text="Pause breaks during calls",
            variable=self.defer_during_meetings,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
        ).pack(padx=PADDING_PANEL_X, pady=(4, PADDING_PANEL_Y), anchor="w")
```

- [ ] **Step 4: Wire the pref into the timer loop**

In `launch.py`, in `timer_loop`, find:
```python
                ctx = read_context()
```
and change it to:
```python
                ctx = read_context(check_meeting=self.defer_during_meetings.get())
```

- [ ] **Step 5: Full suite + launch-smoke**

Run: `.venv/bin/python -m pytest -q` → PASS (87 passed — no new tests here)
Run: `timeout 6 .venv/bin/python launch.py; echo "exit=$? (124=ran fine)"` → `exit=124`, no traceback.

- [ ] **Step 6: HUMAN LIVE CHECK**

The human runs the app, sets a break's interval short, presses Start, and:
- **Start a call / Photo Booth / audio recording** as a break comes due → the break **does not** pop; the console shows `event: break_deferred {'reason': 'meeting'}`; `events.jsonl` gains a `break_deferred` line with `reason: meeting`.
- **Stop** using the mic → the break pops shortly after.
- Open **Settings → uncheck "Pause breaks during calls"** → with the mic in use, the break now **fires** (deferral disabled); reopening Settings shows the checkbox state persisted after a restart.

**If any fail:** STOP and report.

- [ ] **Step 7: Commit**

```bash
git add launch.py
git commit -m "feat: add 'Pause breaks during calls' setting wired into the timer loop"
```

---

## Definition of done

- `Context.is_meeting` + `decide`/`step` defer with `reason="meeting"` (priority fullscreen→meeting→away); `microphone_in_use()` + `read_context(check_meeting=...)`; `defer_during_meetings` pref + Settings checkbox + `timer_loop` wiring; `pyobjc-framework-CoreAudio` in `requirements.txt`.
- `pytest -q` passes (**87**).
- Human live check passed: break defers with `reason=meeting` while mic in use, fires when free, and the Settings toggle works + persists.

## Wrap-up

- Push: `git push -u origin meeting-awareness`.
- PR (base `main`) via `GH_CONFIG_DIR="$HOME/.config/gh-personal" gh pr create`. Verify CI (87 tests). Note: CI runs headless (non-darwin), so `microphone_in_use()` short-circuits to `False` and never imports CoreAudio — the new tests pass without the framework installed.
```

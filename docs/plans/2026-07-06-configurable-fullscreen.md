# Configurable "Defer During Fullscreen" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Note:** this is a one-for-one mirror of the already-shipped `defer_during_meetings` toggle. Task 2 ends with a short human live check.

**Goal:** A user-toggleable "Pause breaks during fullscreen" preference (default on), so fullscreen deferral is no longer hardcoded (#24).

**Architecture:** Add a `check_fullscreen` gate to `read_context` (mirrors `check_meeting`), a `defer_during_fullscreen` pref + Settings checkbox (mirrors `defer_during_meetings`), and pass the pref through `timer_loop`. The engine is unchanged — it already defers on `ctx.is_fullscreen`; this only gates whether that flag can be True.

**Tech Stack:** Python 3, CustomTkinter, pytest.

**Spec:** `~/daily/specs/2026-07-06-configurable-fullscreen-design.md`

## Global Constraints

- Pref `defer_during_fullscreen`, default **True**, read with `.get("defer_during_fullscreen", True)` (backward-compatible); mirrors `defer_during_meetings` exactly.
- The gate lives in `read_context(check_fullscreen=...)`: `is_fullscreen = check_fullscreen and frontmost_is_fullscreen()`. Default `check_fullscreen=True` keeps existing callers/tests working.
- No hardcoded values; conventional-commit messages (summary only, no body/trailer).
- Full suite baseline: **91 passed**.

## Repo conventions

- Use `.venv/bin/python`. Personal git identity is automatic. `gh` uses `GH_CONFIG_DIR="$HOME/.config/gh-personal"`.

## Pre-flight (run once before Task 1)

```bash
cd ~/data/projects/dont_forget_your_breaks
git checkout main && git pull --ff-only origin main
.venv/bin/python -m pytest -q            # baseline: 91 passed
git checkout -b configurable-fullscreen
```

---

### Task 1: Sensor — `check_fullscreen` gate (pure, TDD)

**Files:**
- Modify: `dfyb/activity/sensors.py` (`read_context`)
- Test: `tests/test_sensors.py`

**Interfaces:**
- Produces: `read_context(check_meeting=True, check_fullscreen=True)` with `is_fullscreen=(check_fullscreen and frontmost_is_fullscreen())`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_sensors.py`:
```python
def test_read_context_fullscreen_gated_off(monkeypatch):
    monkeypatch.setattr(sensors, "idle_seconds", lambda: 0.0)
    monkeypatch.setattr(sensors, "frontmost_is_fullscreen", lambda: True)
    monkeypatch.setattr(sensors, "microphone_in_use", lambda: False)
    c = sensors.read_context(check_fullscreen=False)
    assert c.is_fullscreen is False


def test_read_context_fullscreen_on(monkeypatch):
    monkeypatch.setattr(sensors, "idle_seconds", lambda: 0.0)
    monkeypatch.setattr(sensors, "frontmost_is_fullscreen", lambda: True)
    monkeypatch.setattr(sensors, "microphone_in_use", lambda: False)
    c = sensors.read_context(check_fullscreen=True)
    assert c.is_fullscreen is True
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_sensors.py -q`
Expected: FAIL — `read_context() got an unexpected keyword argument 'check_fullscreen'`.

- [ ] **Step 3: Add the `check_fullscreen` param**

In `dfyb/activity/sensors.py`, find:
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
and replace with:
```python
def read_context(check_meeting=True, check_fullscreen=True):
    """Snapshot the current context for the scheduler.

    `check_meeting` / `check_fullscreen` gate their signals (the app's
    `defer_during_meetings` / `defer_during_fullscreen` prefs): when False, that
    flag is always False regardless of the real state.
    """
    return Context(
        idle_seconds=idle_seconds(),
        is_fullscreen=check_fullscreen and frontmost_is_fullscreen(),
        is_meeting=check_meeting and microphone_in_use(),
    )
```

- [ ] **Step 4: Run tests + full suite**

Run: `.venv/bin/python -m pytest tests/test_sensors.py -q` → PASS
Run: `.venv/bin/python -m pytest -q` → PASS (93 passed: 91 + 2 new)

- [ ] **Step 5: Commit**

```bash
git add dfyb/activity/sensors.py tests/test_sensors.py
git commit -m "feat: gate fullscreen deferral via read_context(check_fullscreen)"
```

---

### Task 2: Pref + Settings toggle + timer wiring (launch-verified)

**Files:**
- Modify: `launch.py` (`__init__` pref, `_save_preferences`, Settings checkbox, `timer_loop`)

**Interfaces:**
- Consumes: `read_context(check_meeting=..., check_fullscreen=...)` (Task 1).

- [ ] **Step 1: Add the pref (next to `defer_during_meetings`)**

In `launch.py`, find:
```python
        self.defer_during_meetings = ctk.BooleanVar(
            value=self.saved_prefs.get("defer_during_meetings", True)
        )
        self.defer_during_meetings.trace_add('write', self._save_preferences)
```
and add immediately after it:
```python
        self.defer_during_fullscreen = ctk.BooleanVar(
            value=self.saved_prefs.get("defer_during_fullscreen", True)
        )
        self.defer_during_fullscreen.trace_add('write', self._save_preferences)
```

- [ ] **Step 2: Persist the pref**

In `launch.py`, in `_save_preferences`, find:
```python
            "defer_during_meetings": self.defer_during_meetings.get(),
```
and add after it:
```python
            "defer_during_fullscreen": self.defer_during_fullscreen.get(),
```

- [ ] **Step 3: Add the Settings checkbox**

In `launch.py`, find the "Pause breaks during calls" checkbox:
```python
        ctk.CTkCheckBox(
            general_frame, text="Pause breaks during calls",
            variable=self.defer_during_meetings,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
        ).pack(padx=PADDING_PANEL_X, pady=(4, PADDING_PANEL_Y), anchor="w")
```
Change its bottom pad to `(4, 4)` and add a new checkbox after it (which takes the trailing `PADDING_PANEL_Y`):
```python
        ctk.CTkCheckBox(
            general_frame, text="Pause breaks during calls",
            variable=self.defer_during_meetings,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
        ).pack(padx=PADDING_PANEL_X, pady=(4, 4), anchor="w")

        ctk.CTkCheckBox(
            general_frame, text="Pause breaks during fullscreen",
            variable=self.defer_during_fullscreen,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
        ).pack(padx=PADDING_PANEL_X, pady=(4, PADDING_PANEL_Y), anchor="w")
```

- [ ] **Step 4: Wire the pref into the timer loop**

In `launch.py`, in `timer_loop`, find:
```python
                ctx = read_context(check_meeting=self.defer_during_meetings.get())
```
and replace with:
```python
                ctx = read_context(
                    check_meeting=self.defer_during_meetings.get(),
                    check_fullscreen=self.defer_during_fullscreen.get(),
                )
```

- [ ] **Step 5: Full suite + launch-smoke**

Run: `.venv/bin/python -m pytest -q` → PASS (93 passed — no new tests here)
Run: `timeout 6 .venv/bin/python launch.py; echo "exit=$? (124=ran fine)"` → `exit=124`, no traceback.

- [ ] **Step 6: HUMAN LIVE CHECK**

The human runs the app, sets a break's interval short, presses Start, and:
- With **"Pause breaks during fullscreen" checked (default)** → a break due while in native fullscreen **defers** (console `event: break_deferred {'reason': 'fullscreen'}`).
- Open Settings → **uncheck "Pause breaks during fullscreen"** → a break due while in native fullscreen now **fires**.
- Reopen Settings (or restart) → the checkbox state **persisted**.

**If any fail:** STOP and report.

- [ ] **Step 7: Commit**

```bash
git add launch.py
git commit -m "feat: add 'Pause breaks during fullscreen' setting wired into the timer loop"
```

---

## Definition of done

- `read_context(check_fullscreen=...)` gates `is_fullscreen`; `defer_during_fullscreen` pref + Settings checkbox + `timer_loop` wiring.
- `pytest -q` passes (**93**).
- Human live check passed: fullscreen defers when on, fires when off, toggle persists.

## Wrap-up

- Push: `git push -u origin configurable-fullscreen`.
- PR (base `main`) via `GH_CONFIG_DIR="$HOME/.config/gh-personal" gh pr create`, "closes #24". Verify CI (93).
```

# Activity-Pause Deferral Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> Task 3 ends with a human live check.

**Goal:** When a break is due but the user has been active (any input) within the last N seconds, defer until they've been still for N seconds — then fire. Adjustable (toggle + 2–15s slider), default on/5s (#34).

**Architecture:** Pure scheduler change — `decide()` gets a `pause_threshold` branch (`idle < pause_threshold` → DEFER, reason `"active"`); `step()`/`advance()` thread it. The timer loop resolves the value from two prefs (a toggle + a slider) and passes it in. Reuses the transparency held-line machinery.

**Tech Stack:** Python 3, CustomTkinter, pytest.

**Spec:** `~/daily/specs/2026-07-10-activity-pause-deferral-design.md`

## Global Constraints

- Everything says **"activity"/"active"**, never "typing" (it fires on keyboard AND mouse).
- `decide(..., pause_threshold=0)`: **0 disables** the branch (backward-compatible; existing callers/tests untouched).
- Reason priority: fullscreen → meeting → away → **active** (away & active are mutually exclusive on idle).
- Prefs: `defer_while_active` (default **True**), `activity_pause_seconds` (default **5**, slider **2–15 s**), both read with `.get(key, default)`.
- Held copy (exact): `active` → `"Waited for a pause in your activity."`
- No hardcoded values (thresholds are named constants); conventional commits.
- Baseline suite: **108 passed**.

## Repo conventions
- `.venv/bin/python`. Personal git identity automatic; `gh` uses `GH_CONFIG_DIR="$HOME/.config/gh-personal"`.

## Pre-flight (run once)
```bash
cd ~/data/projects/dont_forget_your_breaks
git checkout main && git pull --ff-only origin main
.venv/bin/python -m pytest -q            # baseline: 108 passed
git checkout -b activity-pause-deferral
```

---

### Task 1: Scheduler — `pause_threshold` in `decide`/`step` + reason "active" (TDD)

**Files:**
- Modify: `dfyb/scheduler/engine.py`
- Test: `tests/test_scheduler_engine.py`

**Interfaces:**
- Produces: `decide(ctx, away_threshold=..., pause_threshold=0)`; `step(states, ctx, natural_threshold=..., away_threshold=..., pause_threshold=0)` — defers with `defer_reason="active"` when `idle_seconds < pause_threshold`; constant `ACTIVITY_PAUSE_DEFAULT_SECONDS = 5`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_scheduler_engine.py`:
```python
def test_decide_defers_when_active():
    assert decide(ctx(idle=2), pause_threshold=5) == DEFER


def test_decide_fires_in_the_pause_window():
    # past the pause threshold, before away -> fire
    assert decide(ctx(idle=10), pause_threshold=5) == FIRE


def test_decide_pause_threshold_zero_disables():
    # default 0 -> active idle still fires (feature off)
    assert decide(ctx(idle=0)) == FIRE


def test_step_defer_reason_active():
    states = [BreakState(remaining=1, interval_seconds=100, duration_seconds=5)]
    r = step(states, ctx(idle=2), pause_threshold=5)
    assert r.defer_reason == "active"
    assert r.fire_index is None
    assert r.new_remaining == [0]


def test_step_fires_in_pause_window():
    states = [BreakState(remaining=1, interval_seconds=100, duration_seconds=5)]
    r = step(states, ctx(idle=10), pause_threshold=5)
    assert r.fire_index == 0


def test_step_away_beats_active():
    # idle >= away threshold -> "away" (can't be both < pause and >= away)
    states = [BreakState(remaining=1, interval_seconds=100, duration_seconds=5)]
    r = step(states, ctx(idle=120), pause_threshold=5)
    assert r.defer_reason == "away"


def test_step_meeting_beats_active():
    states = [BreakState(remaining=1, interval_seconds=100, duration_seconds=5)]
    r = step(states, Context(idle_seconds=1.0, is_fullscreen=False, is_meeting=True),
             pause_threshold=5)
    assert r.defer_reason == "meeting"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_scheduler_engine.py -q`
Expected: FAIL — `decide()`/`step()` got an unexpected keyword `pause_threshold`.

- [ ] **Step 3: Implement**

In `dfyb/scheduler/engine.py`, add the constant after `AWAY_IDLE_THRESHOLD_SECONDS`:
```python
ACTIVITY_PAUSE_DEFAULT_SECONDS = 5         # idle < this at fire time => defer (mid-activity)
```
Replace `decide` with:
```python
def decide(ctx, away_threshold=AWAY_IDLE_THRESHOLD_SECONDS, pause_threshold=0):
    """Decide whether a due break should FIRE or DEFER given the current context."""
    if ctx.is_fullscreen:
        return DEFER          # don't interrupt fullscreen
    if ctx.is_meeting:
        return DEFER          # don't interrupt a call (mic in use)
    if ctx.idle_seconds >= away_threshold:
        return DEFER          # briefly away — wait until back and active
    if ctx.idle_seconds < pause_threshold:
        return DEFER          # mid-activity — wait for a pause (0 disables)
    return FIRE
```
Change the `step` signature to thread `pause_threshold`, and its DEFER reason mapping to add `"active"`:
```python
def step(states, ctx,
         natural_threshold=NATURAL_BREAK_IDLE_THRESHOLD_SECONDS,
         away_threshold=AWAY_IDLE_THRESHOLD_SECONDS,
         pause_threshold=0):
```
Inside `step`, the DEFER block currently sets `reason` via `if is_fullscreen / elif is_meeting / else "away"`. Replace the call and the reason mapping:
```python
        if decide(ctx, away_threshold, pause_threshold) == DEFER:
            if ctx.is_fullscreen:
                reason = "fullscreen"
            elif ctx.is_meeting:
                reason = "meeting"
            elif ctx.idle_seconds >= away_threshold:
                reason = "away"
            else:
                reason = "active"             # idle < pause_threshold
            for i in due:
                new_remaining[i] = 0
            return StepResult(new_remaining=new_remaining, defer_reason=reason)
```

- [ ] **Step 4: Run to verify + full suite**

Run: `.venv/bin/python -m pytest tests/test_scheduler_engine.py -q` → PASS
Run: `.venv/bin/python -m pytest -q` → PASS (115 passed: 108 + 7 new)

- [ ] **Step 5: Commit**
```bash
git add dfyb/scheduler/engine.py tests/test_scheduler_engine.py
git commit -m "feat: defer breaks mid-activity (idle below a pause threshold), reason 'active'"
```

---

### Task 2: Thread `pause_threshold` through `advance` + add the "active" held copy (TDD)

**Files:**
- Modify: `dfyb/scheduler/tick.py`, `dfyb/insights/transparency.py`
- Test: `tests/test_scheduler_tick.py`, `tests/test_transparency.py`

**Interfaces:**
- Consumes: `step(..., pause_threshold)` (Task 1).
- Produces: `advance(states, ctx, episode, pause_threshold=0)`; `held_message("active") == "Waited for a pause in your activity."`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_scheduler_tick.py`:
```python
def test_advance_defers_active():
    states = [BreakState(remaining=1, interval_seconds=100, duration_seconds=5)]
    new_remaining, fire_index, events, ep = advance(states, ctx(idle=2), None, pause_threshold=5)
    assert fire_index is None
    assert events == [(BREAK_DEFERRED, {"reason": "active"})]
    assert ep == DEFERRED_EPISODE
```
Add to `tests/test_transparency.py`:
```python
def test_held_message_active():
    assert held_message("active") == "Waited for a pause in your activity."
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_scheduler_tick.py::test_advance_defers_active tests/test_transparency.py::test_held_message_active -q`
Expected: FAIL — `advance()` got an unexpected keyword `pause_threshold`; `held_message("active")` is `None`.

- [ ] **Step 3: Implement**

In `dfyb/scheduler/tick.py`, change `advance`:
```python
def advance(states, ctx, episode, pause_threshold=0):
    """Run one tick. Returns (new_remaining, fire_index, events, new_episode)."""
    result = step(states, ctx, pause_threshold=pause_threshold)
    events, new_episode = events_for_tick(result, ctx, episode)
    return result.new_remaining, result.fire_index, events, new_episode
```
In `dfyb/insights/transparency.py`, add to `HELD_MESSAGES`:
```python
    "active": "Waited for a pause in your activity.",
```

- [ ] **Step 4: Run to verify + full suite**

Run: `.venv/bin/python -m pytest tests/test_scheduler_tick.py tests/test_transparency.py -q` → PASS
Run: `.venv/bin/python -m pytest -q` → PASS (117 passed: 115 + 2 new)

- [ ] **Step 5: Commit**
```bash
git add dfyb/scheduler/tick.py dfyb/insights/transparency.py tests/test_scheduler_tick.py tests/test_transparency.py
git commit -m "feat: thread pause_threshold through advance + add 'active' held-line copy"
```

---

### Task 3: Prefs (toggle + slider) + timer-loop wiring + Settings UI (launch-verified + human check)

**Files:**
- Modify: `launch.py` (constants, `BreakApp.__init__` prefs, `_save_preferences`, `_open_settings` UI, `timer_loop`)

**Interfaces:**
- Consumes: `advance(..., pause_threshold=...)` (Task 2); `ACTIVITY_PAUSE_DEFAULT_SECONDS` (Task 1).

- [ ] **Step 1: Add UI constants**

In `launch.py`, near the "Break popup" constants, add:
```python
# Activity-pause deferral (#34) slider bounds
ACTIVITY_PAUSE_MIN = 2
ACTIVITY_PAUSE_MAX = 15
```

- [ ] **Step 2: Add the two prefs**

In `BreakApp.__init__`, after the `self.defer_during_fullscreen` pref block (before `self.popup_placement`), add:
```python
        self.defer_while_active = ctk.BooleanVar(
            value=self.saved_prefs.get("defer_while_active", True)
        )
        self.defer_while_active.trace_add('write', self._save_preferences)
        self.activity_pause_seconds = ctk.IntVar(
            value=self.saved_prefs.get("activity_pause_seconds", 5)
        )
        self.activity_pause_seconds.trace_add('write', self._save_preferences)
```

- [ ] **Step 3: Persist them**

In `_save_preferences`, after `"defer_during_fullscreen": self.defer_during_fullscreen.get(),`, add:
```python
            "defer_while_active": self.defer_while_active.get(),
            "activity_pause_seconds": self.activity_pause_seconds.get(),
```

- [ ] **Step 4: Add the Settings checkbox + slider**

In `_open_settings`, immediately AFTER the "Pause breaks during fullscreen" checkbox `.pack(...)` and BEFORE the `placement_row` block, insert:
```python
        ctk.CTkCheckBox(
            general_frame, text="Wait until you pause (keyboard or mouse)",
            variable=self.defer_while_active,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
        ).pack(padx=PADDING_PANEL_X, pady=(4, 4), anchor="w")

        pause_row = ctk.CTkFrame(general_frame, fg_color="transparent")
        pause_row.pack(padx=PADDING_PANEL_X, pady=(4, 4), anchor="w", fill="x")
        pause_value_label = ctk.CTkLabel(
            pause_row, text=f"Pause: {self.activity_pause_seconds.get()} sec",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
        )
        pause_value_label.pack(side="left")

        def _on_pause(value):
            secs = int(round(value))
            self.activity_pause_seconds.set(secs)
            pause_value_label.configure(text=f"Pause: {secs} sec")

        pause_slider = ctk.CTkSlider(
            pause_row, from_=ACTIVITY_PAUSE_MIN, to=ACTIVITY_PAUSE_MAX,
            number_of_steps=ACTIVITY_PAUSE_MAX - ACTIVITY_PAUSE_MIN, command=_on_pause
        )
        pause_slider.set(self.activity_pause_seconds.get())
        pause_slider.pack(side="right")
```
(This makes the fullscreen checkbox no longer the last item; it keeps `pady=(4, 4)`. The existing `placement_row` remains after this, ending the frame with its trailing `PADDING_PANEL_Y`.)

- [ ] **Step 5: Wire the threshold into the timer loop**

In `timer_loop`, the tick currently reads `... = advance(states, ctx, self._episode)`. Replace with:
```python
                pause = (self.activity_pause_seconds.get()
                         if self.defer_while_active.get() else 0)
                new_remaining, fire_index, events, self._episode = advance(
                    states, ctx, self._episode, pause_threshold=pause)
```
(Match the exact surrounding indentation; read the current `advance(...)` call first.)

- [ ] **Step 6: Full suite + launch-smoke**

Run: `.venv/bin/python -m pytest -q` → PASS (117 passed — no new tests here)
Run: `timeout 6 .venv/bin/python launch.py; echo "exit=$? (124=ran fine)"` → `exit=124`, no traceback.

- [ ] **Step 7: HUMAN LIVE CHECK**

Run the app, set a break's interval short, Start, then:
- With **"Wait until you pause" checked** (default) and the slider at ~5s: while the break is due, **keep typing / moving the mouse** — it should NOT pop; console logs `event: break_deferred {'reason': 'active'}`. **Stop** all input → it fires ~5s later, and the popup shows *"Waited for a pause in your activity."*
- Slide the threshold to **2s** → it fires after a shorter stillness; to **15s** → longer.
- **Uncheck** it → a due break fires immediately even while typing.
- Settings reopen / restart → toggle + slider value **persist**.

**If any fail:** STOP and report.

- [ ] **Step 8: Commit**
```bash
git add launch.py
git commit -m "feat: 'wait until you pause' setting (toggle + 2-15s slider) wired into the timer loop"
```

---

## Definition of done
- Break due + active → held with reason `active`; fires ~N s after stillness; held line shows; toggle off = fires immediately.
- Toggle + slider persist. `pytest -q` passes (**117**).
- Human live check passed.

## Wrap-up
- Push `activity-pause-deferral`; PR (base `main`) via `GH_CONFIG_DIR="$HOME/.config/gh-personal" gh pr create`, "closes #34" (per-type knobs remain in #41).

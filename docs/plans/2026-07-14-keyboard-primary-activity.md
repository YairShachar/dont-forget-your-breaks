# Keyboard-primary activity for wait-until-you-pause — Implementation Plan (#41)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wait-until-you-pause keys off typing/clicks/scroll, ignoring bare mouse movement (a toggle re-includes it). Away/natural-break detection stays any-input.

**Architecture:** Add `active_idle_seconds` to `Context` (falls back to `idle_seconds` when absent); `decide`'s pause check uses it. A new `sensors.active_idle_seconds(include_mouse_move)` computes it from per-type macOS event idles; a `count_mouse_move` pref gates mouse-move.

**Tech Stack:** Python 3, PyObjC/Quartz, Tkinter/CustomTkinter, pytest.

**Spec:** `~/daily/specs/2026-07-14-keyboard-primary-activity-design.md`

## Global Constraints

- Two idle signals: `idle_seconds` (any input; away/natural — unchanged) and
  `active_idle_seconds` (typing/clicks/scroll; the pause check).
- `Context.active_idle_seconds` defaults to `None`; the pause check falls back to
  `idle_seconds` — existing engine/tick tests must stay green.
- One pref `count_mouse_move` (default False); no per-type knobs.
- No new logged event; away/natural/fullscreen/meeting unchanged.

---

### Task 1: Engine — second idle signal on `Context` + `decide`

**Files:**
- Modify: `dfyb/scheduler/engine.py`, `tests/test_scheduler_engine.py`.

**Interfaces:**
- Produces: `Context(..., active_idle_seconds=None)`; `decide` honoring it — used
  by Tasks 2–3.

- [ ] **Step 1: Write failing `decide` tests.**

Append to `tests/test_scheduler_engine.py`:

```python
def test_decide_fire_when_mouse_moved_but_not_typing():
    # moved mouse (idle low) but no typing (active_idle high) -> not "active" -> FIRE
    ctx = Context(idle_seconds=1, is_fullscreen=False, active_idle_seconds=30)
    assert decide(ctx, pause_threshold=2) == FIRE


def test_decide_defer_active_when_typing():
    ctx = Context(idle_seconds=1, is_fullscreen=False, active_idle_seconds=1)
    assert decide(ctx, pause_threshold=2) == DEFER


def test_decide_active_falls_back_to_idle_when_unset():
    # active_idle_seconds=None -> uses idle_seconds for the pause check (old behavior)
    ctx = Context(idle_seconds=1, is_fullscreen=False)
    assert decide(ctx, pause_threshold=2) == DEFER


def test_decide_away_ignores_active_idle():
    # away keys off idle_seconds (any input) regardless of active_idle
    ctx = Context(idle_seconds=100, is_fullscreen=False, active_idle_seconds=0)
    assert decide(ctx, pause_threshold=2) == DEFER
```

(These import `Context`, `decide`, `FIRE`, `DEFER` — already imported in the file.)

- [ ] **Step 2: Run to verify failure.**

Run: `.venv/bin/python -m pytest tests/test_scheduler_engine.py -q`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'active_idle_seconds'`.

- [ ] **Step 3: Add the `Context` field.**

Change:

```python
@dataclass(frozen=True)
class Context:
    """What the sensors observed this tick."""
    idle_seconds: float
    is_fullscreen: bool
    is_meeting: bool = False
```

to:

```python
@dataclass(frozen=True)
class Context:
    """What the sensors observed this tick."""
    idle_seconds: float
    is_fullscreen: bool
    is_meeting: bool = False
    active_idle_seconds: float | None = None  # typing/clicks idle; None -> use idle_seconds
```

- [ ] **Step 4: Use it in `decide`.**

Change:

```python
    if ctx.idle_seconds >= away_threshold:
        return DEFER          # briefly away — wait until back and active
    if ctx.idle_seconds < pause_threshold:
        return DEFER          # mid-activity — wait for a pause (0 disables)
    return FIRE
```

to:

```python
    if ctx.idle_seconds >= away_threshold:
        return DEFER          # briefly away — any input counts as present
    active_idle = (ctx.idle_seconds if ctx.active_idle_seconds is None
                   else ctx.active_idle_seconds)
    if active_idle < pause_threshold:
        return DEFER          # mid-activity — typing/clicks (not bare mouse-move)
    return FIRE
```

- [ ] **Step 5: Run to verify pass (new + existing).**

Run: `.venv/bin/python -m pytest tests/test_scheduler_engine.py tests/test_scheduler_tick.py -q`
Expected: PASS (all).

- [ ] **Step 6: Commit.**

```bash
git add dfyb/scheduler/engine.py tests/test_scheduler_engine.py
git commit -m "feat: add active_idle_seconds to Context for keyboard-primary pause (#41)"
```

---

### Task 2: Sensor — `active_idle_seconds` + `read_context` param

**Files:**
- Modify: `dfyb/activity/sensors.py`, `tests/test_sensors.py`.

**Interfaces:**
- Consumes: `Context.active_idle_seconds` (Task 1).
- Produces: `active_idle_seconds(include_mouse_move=False)`;
  `read_context(..., count_mouse_move=False)` — used by Task 3.

- [ ] **Step 1: Write failing sensor tests.**

Append to `tests/test_sensors.py`:

```python
def _fake_quartz_per_type(values):
    fake = types.ModuleType("Quartz")
    fake.kCGEventSourceStateHIDSystemState = 1
    fake.kCGEventKeyDown = 10
    fake.kCGEventFlagsChanged = 12
    fake.kCGEventLeftMouseDown = 1
    fake.kCGEventRightMouseDown = 3
    fake.kCGEventScrollWheel = 22
    fake.kCGEventMouseMoved = 5
    fake.CGEventSourceSecondsSinceLastEventType = (
        lambda state, evtype: values.get(evtype, 999.0))
    return fake


def test_active_idle_excludes_mouse_move_by_default(monkeypatch):
    # all meaningful inputs idle 30s; mouse moved 0.5s ago -> excluded -> 30
    values = {10: 30, 12: 30, 1: 30, 3: 30, 22: 30, 5: 0.5}
    monkeypatch.setitem(sys.modules, "Quartz", _fake_quartz_per_type(values))
    monkeypatch.setattr(sensors.sys, "platform", "darwin")
    assert sensors.active_idle_seconds() == 30


def test_active_idle_includes_mouse_move_when_asked(monkeypatch):
    values = {10: 30, 12: 30, 1: 30, 3: 30, 22: 30, 5: 0.5}
    monkeypatch.setitem(sys.modules, "Quartz", _fake_quartz_per_type(values))
    monkeypatch.setattr(sensors.sys, "platform", "darwin")
    assert sensors.active_idle_seconds(include_mouse_move=True) == 0.5


def test_active_idle_is_min_over_meaningful_types(monkeypatch):
    values = {10: 30, 12: 40, 1: 5, 3: 50, 22: 20, 5: 1}
    monkeypatch.setitem(sys.modules, "Quartz", _fake_quartz_per_type(values))
    monkeypatch.setattr(sensors.sys, "platform", "darwin")
    assert sensors.active_idle_seconds() == 5  # the click


def test_active_idle_non_darwin_falls_back(monkeypatch):
    monkeypatch.setattr(sensors.sys, "platform", "linux")
    assert sensors.active_idle_seconds() == 0.0  # idle_seconds() on non-darwin
```

- [ ] **Step 2: Run to verify failure.**

Run: `.venv/bin/python -m pytest tests/test_sensors.py -q`
Expected: FAIL — `AttributeError: module 'dfyb.activity.sensors' has no attribute 'active_idle_seconds'`.

- [ ] **Step 3: Add `_event_idle_seconds` + `active_idle_seconds`.**

In `dfyb/activity/sensors.py`, after `idle_seconds()`:

```python
def _event_idle_seconds(Quartz, event_type):
    return float(Quartz.CGEventSourceSecondsSinceLastEventType(
        Quartz.kCGEventSourceStateHIDSystemState, event_type))


def active_idle_seconds(include_mouse_move=False):
    """Seconds since the last MEANINGFUL input for wait-until-you-pause:
    keyboard + clicks + scroll (+ mouse-move only if include_mouse_move). Bare
    cursor movement is excluded by default — it's noise, not 'busy working'.
    Falls back to idle_seconds() on non-macOS / failure (never worse than today).
    """
    if sys.platform != "darwin":
        return idle_seconds()
    try:
        import Quartz
        types = [Quartz.kCGEventKeyDown, Quartz.kCGEventFlagsChanged,
                 Quartz.kCGEventLeftMouseDown, Quartz.kCGEventRightMouseDown,
                 Quartz.kCGEventScrollWheel]
        if include_mouse_move:
            types.append(Quartz.kCGEventMouseMoved)
        return min(_event_idle_seconds(Quartz, t) for t in types)
    except Exception:
        return idle_seconds()
```

- [ ] **Step 4: Add the `read_context` param.**

Change:

```python
def read_context(check_meeting=True, check_fullscreen=True):
```

to add `count_mouse_move=False`, and add the field to the returned `Context`:

```python
def read_context(check_meeting=True, check_fullscreen=True, count_mouse_move=False):
```

and inside the `Context(...)` call, after `is_meeting=...`:

```python
        active_idle_seconds=active_idle_seconds(include_mouse_move=count_mouse_move),
```

- [ ] **Step 5: Run to verify pass.**

Run: `.venv/bin/python -m pytest tests/test_sensors.py -q`
Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
git add dfyb/activity/sensors.py tests/test_sensors.py
git commit -m "feat: add active_idle_seconds sensor (typing/clicks/scroll) + read_context param (#41)"
```

---

### Task 3: App wiring — pref + settings checkbox

**Files:**
- Modify: `launch.py` — pref init (`:~1100`), `_save_preferences` (`:1363`),
  the two `read_context` calls (`:1794`, `:1955`), settings checkbox (`:1699`).

**Interfaces:**
- Consumes: `read_context(..., count_mouse_move=...)` (Task 2).

- [ ] **Step 1: Add the pref.**

After the `self.activity_pause_seconds` pref block (its `trace_add` line), add:

```python
        self.count_mouse_move = ctk.BooleanVar(
            value=self.saved_prefs.get("count_mouse_move", False))
        self.count_mouse_move.trace_add('write', self._save_preferences)
```

- [ ] **Step 2: Persist it.**

In `_save_preferences`, after `"activity_pause_seconds": self.activity_pause_seconds.get(),`:

```python
            "count_mouse_move": self.count_mouse_move.get(),
```

- [ ] **Step 3: Pass into `read_context` (timer_loop, `:1794`).**

Change:

```python
                ctx = read_context(
                    check_meeting=self.defer_during_meetings.get(),
                    check_fullscreen=self.defer_during_fullscreen.get(),
                )
```

to add:

```python
                ctx = read_context(
                    check_meeting=self.defer_during_meetings.get(),
                    check_fullscreen=self.defer_during_fullscreen.get(),
                    count_mouse_move=self.count_mouse_move.get(),
                )
```

- [ ] **Step 4: Pass into `read_context` (`_requeue_break`, `:1955`).**

Change:

```python
        ctx = read_context(
            check_meeting=self.defer_during_meetings.get(),
            check_fullscreen=self.defer_during_fullscreen.get(),
        )
```

to add `count_mouse_move=self.count_mouse_move.get(),` (same as Step 3).

- [ ] **Step 5: Relabel the checkbox + add the mouse-move toggle.**

Change the "Wait until you pause" checkbox (`:1699`):

```python
        ctk.CTkCheckBox(
            general_frame, text="Wait until you pause (keyboard or mouse)",
            variable=self.defer_while_active,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
        ).pack(padx=PADDING_PANEL_X, pady=(4, 4), anchor="w")
```

to relabel it and add an indented mouse-move checkbox after it:

```python
        ctk.CTkCheckBox(
            general_frame, text="Wait until you pause (typing or clicking)",
            variable=self.defer_while_active,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
        ).pack(padx=PADDING_PANEL_X, pady=(4, 4), anchor="w")

        ctk.CTkCheckBox(
            general_frame, text="↳ also count mouse movement",
            variable=self.count_mouse_move,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label']),
            text_color=COLORS['text_secondary']
        ).pack(padx=(PADDING_PANEL_X + ROW_SPACING, PADDING_PANEL_X),
               pady=(0, 4), anchor="w")
```

- [ ] **Step 6: Verify parse + compile + full suite.**

Run: `.venv/bin/python -c "import ast; ast.parse(open('launch.py').read())"`
Run: `.venv/bin/python -m py_compile launch.py`
Run: `.venv/bin/python -m pytest -q`
Expected: no output for the first two; all pass.

- [ ] **Step 7: Commit.**

```bash
git add launch.py
git commit -m "feat: count_mouse_move pref + settings toggle for keyboard-primary pause (#41)"
```

---

### Task 4: Manual verification

**Files:** none.

- [ ] **Step 1: Run the app.** `.venv/bin/python launch.py`
- [ ] **Step 2:** Settings → the checkbox reads **"Wait until you pause (typing or
  clicking)"** with an indented **"↳ also count mouse movement"** (unchecked).
- [ ] **Step 3:** Enable wait-until-you-pause; make a break due soon. When it's
  due, **move only the mouse** (don't type/click) → the break **fires**.
- [ ] **Step 4:** Repeat but **type** as it comes due → it **holds** (the
  "waiting for a pause…" cue appears).
- [ ] **Step 5:** Check **"↳ also count mouse movement"** → now moving the mouse
  also holds the break.
- [ ] **Step 6:** Leave the machine fully idle > 60s → still deferred as "away".
- [ ] **Step 7:** Toggle the checkboxes, quit + relaunch → settings persist.

# Insights: Transparency Moment + Event Schema Versioning — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> Task 3 ends with a human live check (a break must be *held* then fire).

**Goal:** When a break was *held* (deferred during a meeting/fullscreen/away) and then fires, the popup shows a calm reason line — making the app's invisible timing intelligence visible. Plus a schema `version` on every logged event.

**Architecture:** A new pure `dfyb/insights/` package holds the (testable) held-reason tracking + copy. The timer loop already receives per-tick `events` (with `BREAK_DEFERRED`/`NATURAL_BREAK`); a pure `track_held(events, fired, prev)` folds those into a carried held-reason and surfaces it at fire. The popup renders one subtle line. `EventLog.append` stamps a version. No scheduler change.

**Tech Stack:** Python 3, CustomTkinter, pytest.

**Spec:** `~/daily/specs/2026-07-07-insights-transparency-design.md`

## Global Constraints

- Held-reason copy (exact): `meeting` → "Waited while you were in a meeting.", `fullscreen` → "Waited while you were in full screen.", `away` → "Waited until you were back."; unknown/None → no line.
- The held line appears ONLY when the break was actually held (naturally occasional — no throttle).
- `SCHEMA_VERSION = 1`; every appended event carries `"v"`; `read()` stays backward-compatible with old records missing `v` (no migration).
- No hardcoded values (copy lives in a named constant); conventional commits (summary only).
- Deferred/out of scope: aggregation/query layer, visual dashboard, `break_skipped` logging.
- Baseline suite: **98 passed**.

## Repo conventions
- `.venv/bin/python`. Personal git identity automatic; `gh` uses `GH_CONFIG_DIR="$HOME/.config/gh-personal"`.

## Pre-flight (run once)
```bash
cd ~/data/projects/dont_forget_your_breaks
git checkout main && git pull --ff-only origin main
.venv/bin/python -m pytest -q            # baseline: 98 passed
git checkout -b insights-transparency
```

---

### Task 1: Pure held-reason tracking + copy — `dfyb/insights/transparency.py` (TDD)

**Files:**
- Create: `dfyb/insights/__init__.py` (empty), `dfyb/insights/transparency.py`
- Test: `tests/test_transparency.py`

**Interfaces:**
- Produces:
  - `track_held(events, fired, prev_held) -> (held_to_show, new_held)` — `events` is a list of `(event_type, data_dict)` tuples (as the timer loop gets from `advance`); `fired` is a bool; returns the reason to display on THIS fire (or `None`) and the reason to carry to next tick.
  - `held_message(reason) -> str | None` — reason → copy (or `None`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_transparency.py`:
```python
from dfyb.insights.transparency import track_held, held_message
from dfyb.activity.event_log import BREAK_DEFERRED, NATURAL_BREAK

DEFER = [(BREAK_DEFERRED, {"reason": "meeting"})]
NATURAL = [(NATURAL_BREAK, {"idle_seconds": 400})]


def test_track_held_defer_carries_reason():
    # a defer this tick -> nothing to show, carry the reason forward
    assert track_held(DEFER, fired=False, prev_held=None) == (None, "meeting")


def test_track_held_dedup_tick_keeps_prev():
    # deduped defer tick (no events) while held -> keep carrying the reason
    assert track_held([], fired=False, prev_held="meeting") == (None, "meeting")


def test_track_held_fire_after_held_shows_and_clears():
    # break fires after being held -> show the carried reason, then clear
    assert track_held([], fired=True, prev_held="fullscreen") == ("fullscreen", None)


def test_track_held_normal_fire_shows_nothing():
    assert track_held([], fired=True, prev_held=None) == (None, None)


def test_track_held_natural_break_clears():
    assert track_held(NATURAL, fired=False, prev_held="away") == (None, None)


def test_held_message_maps_each_reason():
    assert held_message("meeting") == "Waited while you were in a meeting."
    assert held_message("fullscreen") == "Waited while you were in full screen."
    assert held_message("away") == "Waited until you were back."
    assert held_message("nonsense") is None
    assert held_message(None) is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_transparency.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'dfyb.insights'`.

- [ ] **Step 3: Create the package + module**

Create empty `dfyb/insights/__init__.py`:
```python
```

Create `dfyb/insights/transparency.py`:
```python
"""Make the invisible timing intelligence visible: track WHY a break was held
(deferred) so the popup can say so. Pure (no Tk, no I/O) — unit-tested."""
from dfyb.activity.event_log import BREAK_DEFERRED, NATURAL_BREAK

# reason -> the calm line shown under the break title when it was held.
HELD_MESSAGES = {
    "meeting": "Waited while you were in a meeting.",
    "fullscreen": "Waited while you were in full screen.",
    "away": "Waited until you were back.",
}


def track_held(events, fired, prev_held):
    """Fold this tick's events into a carried held-reason.

    Returns (held_to_show, new_held): `held_to_show` is the reason to display on
    THIS fire (None if not firing / not held); `new_held` is carried to the next
    tick. A defer records its reason; a natural break clears it; a fire surfaces
    then clears it.
    """
    held = prev_held
    for event_type, data in events:
        if event_type == BREAK_DEFERRED:
            held = data.get("reason")
        elif event_type == NATURAL_BREAK:
            held = None
    if fired:
        return held, None
    return None, held


def held_message(reason):
    """The calm line for a held break, or None for no/unknown reason."""
    return HELD_MESSAGES.get(reason)
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_transparency.py -q` → PASS
Run: `.venv/bin/python -m pytest -q` → PASS (104 passed: 98 + 6 new)

- [ ] **Step 5: Commit**
```bash
git add dfyb/insights/ tests/test_transparency.py
git commit -m "feat: add pure held-reason tracking + copy for the transparency moment"
```

---

### Task 2: Event schema version — `EventLog` (TDD)

**Files:**
- Modify: `dfyb/activity/event_log.py`
- Test: `tests/test_event_log.py`

**Interfaces:**
- Produces: module constant `SCHEMA_VERSION = 1`; every appended event dict includes `"v": SCHEMA_VERSION`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_event_log.py`:
```python
def test_append_stamps_schema_version(tmp_path):
    from dfyb.activity.event_log import EventLog, SCHEMA_VERSION
    log = EventLog(tmp_path / "e.jsonl", clock=lambda: 1.0)
    event = log.append("break_taken", name="Micro")
    assert event["v"] == SCHEMA_VERSION
    assert log.read()[0]["v"] == SCHEMA_VERSION


def test_read_tolerates_unversioned_events(tmp_path):
    from dfyb.activity.event_log import EventLog
    p = tmp_path / "e.jsonl"
    p.write_text('{"ts": 1.0, "type": "break_taken", "data": {}}\n')  # old, no "v"
    events = EventLog(p).read()
    assert events == [{"ts": 1.0, "type": "break_taken", "data": {}}]
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_event_log.py -q`
Expected: FAIL — `ImportError: cannot import name 'SCHEMA_VERSION'` / `KeyError: 'v'`.

- [ ] **Step 3: Add the version**

In `dfyb/activity/event_log.py`, after the event-type constants (after `NATURAL_BREAK = "natural_break"`), add:
```python

# Event record schema version. Bump when the event shape changes; readers may
# branch on it. Old records lacking "v" are treated as unversioned.
SCHEMA_VERSION = 1
```
Then change `append` so the event dict includes the version:
```python
    def append(self, event_type, **data):
        """Append an event and return it. Each event: {ts, type, data, v}."""
        event = {"ts": self._clock(), "type": event_type,
                 "data": data, "v": SCHEMA_VERSION}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
        return event
```

- [ ] **Step 4: Run to verify + full suite**

Run: `.venv/bin/python -m pytest tests/test_event_log.py -q` → PASS
Run: `.venv/bin/python -m pytest -q` → PASS (106 passed: 104 + 2 new)

- [ ] **Step 5: Commit**
```bash
git add dfyb/activity/event_log.py tests/test_event_log.py
git commit -m "feat: stamp a schema version on every logged event"
```

---

### Task 3: Wire it into the timer loop + popup (launch-verified + human check)

**Files:**
- Modify: `launch.py` (imports, `timer_loop`, `trigger_break`, `_process_break_queue`, `CountdownPopup`, `BreakApp` held-state init)

**Interfaces:**
- Consumes: `track_held`, `held_message` (Task 1).

- [ ] **Step 1: Import the helpers**

In `launch.py`, near the other `from dfyb...` imports, add:
```python
from dfyb.insights.transparency import track_held, held_message
```

- [ ] **Step 2: Initialize the carried held-state**

Find where `self._episode` is first initialized (grep `self._episode =` — it's set before/at the start of the timer loop). Add alongside it:
```python
        self._held = None
```
(If `_episode` is only assigned from `advance`'s return inside the loop, add `self._held = None` in `__init__` next to the other timer state like `self._episode = None`. Grep both; init `self._held = None` wherever `self._episode = None` lives.)

- [ ] **Step 3: Track held-reason each tick + pass at fire**

In `timer_loop`, the tick currently reads:
```python
                for event_type, data in events:
                    self._record_event(event_type, **data)
                if fire_index is not None:
                    logging.info(
                        "break due, firing: %s (idle=%.0fs fullscreen=%s)",
                        self.breaks[fire_index].name.get(),
                        ctx.idle_seconds,
                        ctx.is_fullscreen,
                    )
                    if not ctx.is_fullscreen:
                        self._fs23_capture(ctx)  # (only if present; ignore if not)
                    self.trigger_break(self.breaks[fire_index])
```
Replace the fire block so held-reason is tracked and threaded (note: the `_fs23_capture` line was temporary debug and should already be gone — if you see it, it's stale):
```python
                for event_type, data in events:
                    self._record_event(event_type, **data)
                held_reason, self._held = track_held(
                    events, fire_index is not None, self._held)
                if fire_index is not None:
                    logging.info(
                        "break due, firing: %s (idle=%.0fs fullscreen=%s held=%s)",
                        self.breaks[fire_index].name.get(),
                        ctx.idle_seconds,
                        ctx.is_fullscreen,
                        held_reason,
                    )
                    self.trigger_break(self.breaks[fire_index], held_reason=held_reason)
```
(Match the surrounding indentation exactly; read the current block first.)

- [ ] **Step 4: Thread held_reason through the break queue**

In `trigger_break`, add the parameter and carry it in `break_data`:
```python
    def trigger_break(self, config, held_reason=None):
        """Queue a break with the given configuration."""
        break_data = {
            'name': config.name.get(),
            'duration': config.get_duration_seconds(),
            'auto_dismiss': config.auto_dismiss.get(),
            'start_sound': config.start_sound.get(),
            'end_sound': config.end_sound.get(),
            'loop_end_sound': config.loop_end_sound.get(),
            'held_reason': held_reason,
        }
        self.break_queue.append(break_data)
        self.root.after(0, self._process_break_queue)
```
(If `_requeue_break` rebuilds/reuses `break_data`, leave it — a requeued snooze carrying a stale held_reason is acceptable; do NOT add new behavior.)

- [ ] **Step 5: Pass it into the popup**

In `_process_break_queue`, the `CountdownPopup(...)` construction currently ends with `placement=self.popup_placement.get(), target_screen=target_screen,`. Add:
```python
            placement=self.popup_placement.get(),
            target_screen=target_screen,
            held_reason=break_data.get('held_reason'),
        )
```

- [ ] **Step 6: Accept + render the held line in `CountdownPopup`**

In `CountdownPopup.__init__`, add the parameter (after `target_screen=None`):
```python
                 target_screen=None, held_reason=None):
```
and store it near the other assignments (after `self.target_screen = target_screen`):
```python
        self.held_reason = held_reason
```
Then, in the popup body, right AFTER the title label is packed and BEFORE the message label, insert the held line (only when held):
```python
        if self.held_reason:
            held_text = held_message(self.held_reason)
            if held_text:
                ctk.CTkLabel(
                    container, text=held_text,
                    font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['helper']),
                    text_color=COLORS['text_secondary']
                ).pack(pady=(0, 6))
```

- [ ] **Step 7: Full suite + launch-smoke**

Run: `.venv/bin/python -m pytest -q` → PASS (106 passed — launch.py has no unit tests)
Run: `timeout 6 .venv/bin/python launch.py; echo "exit=$? (124=ran fine)"` → `exit=124`, no traceback.

- [ ] **Step 8: HUMAN LIVE CHECK**

Run the app, set a short interval, Start, then:
- Be in a **meeting (mic on)** or **fullscreen** when the break comes due so it **defers** (console logs `break_deferred`), then clear the context → the break fires and the popup shows the line, e.g. **"Waited while you were in full screen."** under the title.
- A break that fires **normally** (never deferred) shows **no** line.
- Console shows `... held=fullscreen` (or the reason) on the held fire, `held=None` on a normal fire.

**If any fail:** STOP and report.

- [ ] **Step 9: Commit**
```bash
git add launch.py
git commit -m "feat: show a calm 'waited while…' line when a held break finally fires"
```

---

## Definition of done
- Held break → popup shows the reason line; normal break shows none; every event carries `v`.
- `pytest -q` passes (**106**).
- Human live check passed.

## Wrap-up
- Push `insights-transparency`; PR (base `main`) via `GH_CONFIG_DIR="$HOME/.config/gh-personal" gh pr create` referencing Phase 3 groundwork (do NOT close #6/#9 — the dashboard is still deferred).

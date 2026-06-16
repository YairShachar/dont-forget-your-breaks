# Phase 1b — Timer-Loop Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make "Perfect Timing" live — wire the Phase 1a brain (`step` + sensors) and the `EventLog` into `BreakApp.timer_loop` so breaks actually defer on fullscreen/away and reset on natural breaks, logging every decision.

**Architecture:** Keep the engine pure. Two new pure helpers — `states_from_configs` (ctk configs → `BreakState`) and `advance` (composes `step` + episode-dedup event logic) — carry all the logic and are fully unit-tested. The `timer_loop` change is ~10 lines of glue: read context, adapt, `advance`, write back, log, trigger. Verified by launching the app.

**Tech Stack:** Python 3, pytest, the Phase 1a `dfyb/scheduler` + `dfyb/activity` modules.

**Spec:** `docs/specs/2026-06-16-phase-1-perfect-timing-design.md` (§6 integration).

**Prerequisite:** Phase 1a (PR #19) **must be merged to `main`** before executing this — it imports `dfyb.scheduler.engine`, `dfyb.activity.sensors`, and the new event constants. Confirm in pre-flight.

**Repo conventions:**
- Repo under `~/data/projects/` → personal Git identity automatically. No identity flags.
- `.venv/bin/python` / `.venv/bin/pip`. Conventional commits, summary only, no co-author trailer.
- **Push before PR; verify the PR diff + CI test count** before claiming done.

**Pre-flight (run once before Task 1):**
```bash
cd ~/data/projects/dont_forget_your_breaks
git checkout main && git pull --ff-only origin main
# Confirm Phase 1a is present (these must all exist):
ls dfyb/scheduler/engine.py dfyb/activity/sensors.py && \
  .venv/bin/python -c "from dfyb.activity.event_log import BREAK_DEFERRED, NATURAL_BREAK; print('1a present')"
git checkout -b phase-1b-integration
.venv/bin/python -m pytest -q     # baseline: 55 passed
```
If the `1a present` check fails, STOP — PR #19 has not been merged yet.

---

### Task 1: Config→state adapter `dfyb/scheduler/adapter.py`

**Files:**
- Create: `dfyb/scheduler/adapter.py`
- Test: `tests/test_scheduler_adapter.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scheduler_adapter.py`:
```python
from dfyb.scheduler.engine import BreakState
from dfyb.scheduler.adapter import states_from_configs


class FakeConfig:
    """Duck-typed stand-in for BreakConfig (no Tk needed)."""
    def __init__(self, remaining, interval, duration):
        self.remaining = remaining
        self._interval = interval
        self._duration = duration

    def get_interval_seconds(self):
        return self._interval

    def get_duration_seconds(self):
        return self._duration


def test_states_from_configs_maps_each_field():
    configs = [FakeConfig(5, 100, 5), FakeConfig(8, 200, 600)]
    states = states_from_configs(configs)
    assert states == [BreakState(5, 100, 5), BreakState(8, 200, 600)]


def test_states_from_configs_empty():
    assert states_from_configs([]) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_scheduler_adapter.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'dfyb.scheduler.adapter'`

- [ ] **Step 3: Create the adapter**

Create `dfyb/scheduler/adapter.py`:
```python
"""Adapt the app's (Tk-bound) BreakConfig objects to plain BreakState snapshots."""
from dfyb.scheduler.engine import BreakState


def states_from_configs(configs):
    """Map an iterable of BreakConfig-like objects to a list[BreakState].

    Each config must expose `.remaining`, `.get_interval_seconds()`,
    `.get_duration_seconds()`. This is the single place BreakConfig is read into
    the pure engine's value type — the engine never sees a BreakConfig.
    """
    return [
        BreakState(
            remaining=c.remaining,
            interval_seconds=c.get_interval_seconds(),
            duration_seconds=c.get_duration_seconds(),
        )
        for c in configs
    ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_scheduler_adapter.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (57 passed)

- [ ] **Step 6: Commit**

```bash
git add dfyb/scheduler/adapter.py tests/test_scheduler_adapter.py
git commit -m "feat: add BreakConfig->BreakState adapter with tests"
```

---

### Task 2: Per-tick composition `dfyb/scheduler/tick.py`

**Files:**
- Create: `dfyb/scheduler/tick.py`
- Test: `tests/test_scheduler_tick.py`

`events_for_tick` applies episode dedup (log a sustained idle/defer once). `advance` composes `step` + `events_for_tick` so the timer loop calls ONE pure function.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scheduler_tick.py`:
```python
from dfyb.scheduler.engine import Context, BreakState
from dfyb.activity.event_log import BREAK_DEFERRED, NATURAL_BREAK
from dfyb.scheduler.tick import (
    events_for_tick, advance, IDLE_EPISODE, DEFERRED_EPISODE,
)


def ctx(idle=0.0, fullscreen=False):
    return Context(idle_seconds=idle, is_fullscreen=fullscreen)


# --- events_for_tick (operates on a StepResult-like object) ---

class R:
    """Minimal StepResult stand-in for events_for_tick tests."""
    def __init__(self, natural_break=False, fire_index=None, defer_reason=None):
        self.natural_break = natural_break
        self.fire_index = fire_index
        self.defer_reason = defer_reason


def test_natural_break_logs_once_then_dedups():
    events, ep = events_for_tick(R(natural_break=True), ctx(idle=400), None)
    assert events == [(NATURAL_BREAK, {"idle_seconds": 400})]
    assert ep == IDLE_EPISODE
    # same episode -> no repeat
    events2, ep2 = events_for_tick(R(natural_break=True), ctx(idle=410), IDLE_EPISODE)
    assert events2 == [] and ep2 == IDLE_EPISODE


def test_defer_logs_once_then_dedups():
    events, ep = events_for_tick(R(defer_reason="fullscreen"), ctx(), None)
    assert events == [(BREAK_DEFERRED, {"reason": "fullscreen"})]
    assert ep == DEFERRED_EPISODE
    events2, ep2 = events_for_tick(R(defer_reason="fullscreen"), ctx(), DEFERRED_EPISODE)
    assert events2 == [] and ep2 == DEFERRED_EPISODE


def test_fire_clears_episode_and_logs_nothing():
    events, ep = events_for_tick(R(fire_index=0), ctx(), DEFERRED_EPISODE)
    assert events == [] and ep is None


def test_nothing_due_clears_episode():
    events, ep = events_for_tick(R(), ctx(), IDLE_EPISODE)
    assert events == [] and ep is None


def test_episode_transition_idle_to_deferred_relogs():
    # was idle, now deferring -> different episode, logs the defer
    events, ep = events_for_tick(R(defer_reason="away"), ctx(), IDLE_EPISODE)
    assert events == [(BREAK_DEFERRED, {"reason": "away"})]
    assert ep == DEFERRED_EPISODE


# --- advance (composes step + events_for_tick) ---

def test_advance_natural_break():
    states = [BreakState(remaining=5, interval_seconds=100, duration_seconds=5)]
    new_remaining, fire_index, events, ep = advance(states, ctx(idle=400), None)
    assert new_remaining == [100]
    assert fire_index is None
    assert events == [(NATURAL_BREAK, {"idle_seconds": 400})]
    assert ep == IDLE_EPISODE


def test_advance_fires_when_due_and_active():
    states = [BreakState(remaining=1, interval_seconds=100, duration_seconds=5)]
    new_remaining, fire_index, events, ep = advance(states, ctx(idle=0), None)
    assert fire_index == 0
    assert new_remaining == [100]
    assert events == []          # BREAK_TAKEN is logged on popup close, not here
    assert ep is None


def test_advance_defers_on_fullscreen():
    states = [BreakState(remaining=1, interval_seconds=100, duration_seconds=5)]
    new_remaining, fire_index, events, ep = advance(states, ctx(fullscreen=True), None)
    assert fire_index is None
    assert new_remaining == [0]  # clamped
    assert events == [(BREAK_DEFERRED, {"reason": "fullscreen"})]
    assert ep == DEFERRED_EPISODE


def test_advance_decrements_when_not_due():
    states = [BreakState(remaining=5, interval_seconds=100, duration_seconds=5)]
    new_remaining, fire_index, events, ep = advance(states, ctx(idle=0), None)
    assert new_remaining == [4]
    assert fire_index is None and events == [] and ep is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_scheduler_tick.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'dfyb.scheduler.tick'`

- [ ] **Step 3: Create the module**

Create `dfyb/scheduler/tick.py`:
```python
"""Per-tick composition: run the engine and decide which events to log.

Pure (no Tk, no I/O). The timer loop calls `advance` once per tick and applies
the returned new_remaining / fire_index / events.
"""
from dfyb.activity.event_log import BREAK_DEFERRED, NATURAL_BREAK
from dfyb.scheduler.engine import step

# Episode markers used to dedup sustained idle/defer logging.
IDLE_EPISODE = "idle"
DEFERRED_EPISODE = "deferred"


def events_for_tick(result, ctx, episode):
    """Given a StepResult, the Context, and the previous episode marker, return
    (events_to_log, new_episode). Logs a sustained idle/defer only once.

    events_to_log is a list of (event_type, data_dict) tuples.
    """
    if result.natural_break:
        if episode != IDLE_EPISODE:
            return [(NATURAL_BREAK, {"idle_seconds": ctx.idle_seconds})], IDLE_EPISODE
        return [], IDLE_EPISODE
    if result.defer_reason is not None:
        if episode != DEFERRED_EPISODE:
            return [(BREAK_DEFERRED, {"reason": result.defer_reason})], DEFERRED_EPISODE
        return [], DEFERRED_EPISODE
    # fire, or nothing due -> episode ends; BREAK_TAKEN is logged on popup close.
    return [], None


def advance(states, ctx, episode):
    """Run one tick. Returns (new_remaining, fire_index, events, new_episode)."""
    result = step(states, ctx)
    events, new_episode = events_for_tick(result, ctx, episode)
    return result.new_remaining, result.fire_index, events, new_episode
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_scheduler_tick.py -q`
Expected: PASS (9 passed)

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (66 passed)

- [ ] **Step 6: Commit**

```bash
git add dfyb/scheduler/tick.py tests/test_scheduler_tick.py
git commit -m "feat: add per-tick advance() composition (step + episode-dedup events) with tests"
```

---

### Task 3: Wire it into `BreakApp` (launch-verified integration)

**Files:**
- Modify: `launch.py` (imports, `EVENTS_FILE` constant, `__init__`, `timer_loop`, `on_popup_close`)

This is the only task that touches the running app. It has no new unit tests — it's verified by launching the app and confirming the event log is written.

- [ ] **Step 1: Add imports**

In `launch.py`, immediately after the existing line `from dfyb.animation import ease_out_quad, prefers_reduced_motion`, add:
```python
from dfyb.activity.event_log import EventLog, BREAK_TAKEN
from dfyb.activity.sensors import read_context
from dfyb.scheduler.adapter import states_from_configs
from dfyb.scheduler.tick import advance
```

- [ ] **Step 2: Add the `EVENTS_FILE` constant**

In `launch.py`, find the line:
```python
LOCK_FILE = Path.home() / "Library" / "Application Support" / "DontForgetYourBreaks" / ".lock"
```
and add immediately after it:
```python
EVENTS_FILE = Path.home() / "Library" / "Application Support" / "DontForgetYourBreaks" / "events.jsonl"
```

- [ ] **Step 3: Create the EventLog + episode state in `__init__`**

In `launch.py`, find this block in `BreakApp.__init__`:
```python
        self.break_queue = []
        self.active_popup = None
        self.break_start_time = None
```
and add two lines after it:
```python
        self.event_log = EventLog(EVENTS_FILE)
        self._episode = None  # idle/deferred dedup marker for the smart-timing loop
```

- [ ] **Step 4: Replace `timer_loop` with the smart-timing version**

In `launch.py`, replace the entire `timer_loop` method:
```python
    def timer_loop(self):
        """Single timer loop managing all breaks."""
        while self.running and not self.stop_event.is_set():
            time.sleep(1)
            if self.paused or self.active_popup:
                continue

            fired_breaks = []
            for config in self.breaks:
                config.remaining -= 1
                if config.remaining <= 0:
                    fired_breaks.append(config)

            if fired_breaks:
                longest = max(fired_breaks, key=lambda c: c.get_duration_seconds())
                for config in fired_breaks:
                    config.reset_timer()
                self.trigger_break(longest)
```
with:
```python
    def timer_loop(self):
        """Single timer loop managing all breaks (context-aware via the scheduler)."""
        while self.running and not self.stop_event.is_set():
            time.sleep(1)
            if self.paused or self.active_popup:
                continue

            ctx = read_context()
            states = states_from_configs(self.breaks)
            new_remaining, fire_index, events, self._episode = advance(
                states, ctx, self._episode
            )
            for config, remaining in zip(self.breaks, new_remaining):
                config.remaining = remaining
            for event_type, data in events:
                self.event_log.append(event_type, **data)
            if fire_index is not None:
                self.trigger_break(self.breaks[fire_index])
```
Note: the engine resets fired breaks (writes the interval into `new_remaining`), so the old `reset_timer()` loop is gone — the write-back handles it.

- [ ] **Step 5: Log `BREAK_TAKEN` on popup close**

In `launch.py`, find this line inside the `on_popup_close` closure (in `_process_break_queue`):
```python
        def on_popup_close():
            elapsed = int(time.time() - self.break_start_time) if self.break_start_time else 0
            for queued_break in self.break_queue:
                queued_break['duration'] -= elapsed
```
and add an event-log line right after `elapsed` is computed (so the block becomes):
```python
        def on_popup_close():
            elapsed = int(time.time() - self.break_start_time) if self.break_start_time else 0
            self.event_log.append(
                BREAK_TAKEN,
                name=break_data['name'],
                duration=break_data['duration'],
                used_seconds=elapsed,
            )
            for queued_break in self.break_queue:
                queued_break['duration'] -= elapsed
```

- [ ] **Step 6: Full suite still green**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (66 passed — no new tests here, but nothing regressed)

- [ ] **Step 7: Launch-smoke the app**

Run: `timeout 6 .venv/bin/python launch.py; echo "exit=$? (124=ran fine)"`
Expected: `exit=124`, no traceback. (The loop only runs after the user presses Start, so this just confirms imports + `EventLog(EVENTS_FILE)` construction don't crash startup.)

- [ ] **Step 8: Behavioral check — the event log gets written on a break**

This proves the integration end-to-end. Run this helper that drives the real loop pieces against a fast break and a temp event file (no GUI needed — it exercises the exact tick→log path the loop runs):
```bash
.venv/bin/python - <<'PY'
import tempfile, os
from dfyb.activity.event_log import EventLog, BREAK_DEFERRED, NATURAL_BREAK
from dfyb.scheduler.engine import Context, BreakState
from dfyb.scheduler.adapter import states_from_configs
from dfyb.scheduler.tick import advance

# Simulate the timer_loop's per-tick sequence over a few ticks.
class C:
    def __init__(s, r, i, d): s.remaining, s._i, s._d = r, i, d
    def get_interval_seconds(s): return s._i
    def get_duration_seconds(s): return s._d

tmp = tempfile.mktemp(suffix=".jsonl")
log = EventLog(tmp)
episode = None
configs = [C(2, 100, 5)]  # micro break due in 2 ticks

# tick 1: active, decrement
states = states_from_configs(configs)
nr, fi, events, episode = advance(states, Context(0.0, False), episode)
for c, r in zip(configs, nr): c.remaining = r
for et, data in events: log.append(et, **data)

# tick 2: fullscreen -> should DEFER and log BREAK_DEFERRED
states = states_from_configs(configs)
nr, fi, events, episode = advance(states, Context(0.0, True), episode)
for c, r in zip(configs, nr): c.remaining = r
for et, data in events: log.append(et, **data)

# tick 3: idle 400 -> NATURAL_BREAK, reset
states = states_from_configs(configs)
nr, fi, events, episode = advance(states, Context(400.0, False), episode)
for c, r in zip(configs, nr): c.remaining = r
for et, data in events: log.append(et, **data)

types = [e["type"] for e in log.read()]
print("logged events:", types)
assert BREAK_DEFERRED in types, "expected a deferred event"
assert NATURAL_BREAK in types, "expected a natural-break event"
os.unlink(tmp)
print("INTEGRATION-OK")
PY
```
Expected: prints `logged events: ['break_deferred', 'natural_break']` then `INTEGRATION-OK`. This confirms the adapter→advance→event-log path the `timer_loop` runs is correct.

- [ ] **Step 9: Commit**

```bash
git add launch.py
git commit -m "feat: make breaks context-aware (natural-break/fullscreen/away defer) via the scheduler"
```

---

## Definition of done (Phase 1b)

- `dfyb/scheduler/adapter.py` (`states_from_configs`) and `dfyb/scheduler/tick.py` (`events_for_tick`, `advance`) exist, fully unit-tested.
- `BreakApp.timer_loop` reads context, runs `advance`, writes back, logs events, and triggers — replacing the old blind countdown.
- `BreakApp` has an `EventLog` instance writing to `~/Library/Application Support/DontForgetYourBreaks/events.jsonl`; `BREAK_TAKEN` is logged on popup close with `used_seconds`.
- `pytest -q` passes (expected total: **66**).
- App launches without a traceback; the Step 8 integration check prints `INTEGRATION-OK`.

## Manual verification (recommended before merge)

Run the app, set the **Micro Break** interval to a few seconds, press Start, and:
- Let it pop → press Done → confirm `~/Library/Application Support/DontForgetYourBreaks/events.jsonl` gains a `break_taken` line.
- Put another app in fullscreen as a break comes due → confirm it does NOT pop and a `break_deferred` line appears; leave fullscreen → it pops.
- Step away for 5 min (or temporarily lower `NATURAL_BREAK_IDLE_THRESHOLD_SECONDS`) → confirm a `natural_break` line and the timers reset.

## Wrap-up

- Push: `git push -u origin phase-1b-integration`; confirm `git log origin/phase-1b-integration..HEAD` is empty.
- Open a PR (base `main`). Verify `gh pr diff <n> --name-only` and the PR CI (66 tests).

## Known limitations carried forward (from Phase 1a review)
- Fullscreen heuristic is main-display + first-layer-0-window only (multi-monitor / floating-overlay edge cases). Revisit in a later phase.
- Meeting/video-call detection is out of scope (a future Phase 1 slice).

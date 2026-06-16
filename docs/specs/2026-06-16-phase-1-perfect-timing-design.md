# Phase 1 — Perfect Timing: Design

**Date:** 2026-06-16
**Author:** Yair Shachar (with Claude)
**Repo:** https://github.com/YairShachar/dont-forget-your-breaks
**Status:** Approved design; to be decomposed into implementation plan(s).
**Builds on:** the `EventLog` spine (Phase 0a) and the extracted service layer (Phase 0b-1).

---

## 1. Goal

Make breaks **earn the interruption** — fire when a break helps, never when it would wreck focus. Today `BreakApp.timer_loop` decrements each break's counter every second and pops the instant one hits zero, completely blind to what the user is doing. This phase makes that fire decision context-aware.

## 2. Scope (first slice)

Three behaviors, driven by **two macOS signals** (idle time, frontmost-app fullscreen):

1. **Natural-break detection** — if idle ≥ a fixed threshold (default 5 min), quietly reset all break timers (you stepped away long enough to count as a real break) so you're not nagged right after returning.
2. **Don't interrupt fullscreen** — defer a due break while the frontmost app is fullscreen (presentations/video/games); fire once you exit.
3. **Defer when away** — if a break comes due while you're briefly idle (≥ 60s, < natural threshold), defer until you're back and active.

**Explicitly out of scope (this slice):** meeting/video-call detection (#2's "don't interrupt meetings" — hardest to detect; later slice), any UI/settings changes (smart timing is always-on with configurable constants), and the full `Scheduler`-owns-the-loop refactor.

## 3. Architecture (Approach A: pure brain + thin sensor layer)

```
  every 1s tick (BreakApp.timer_loop — the ONLY legacy touch)
        │
        ▼
   SENSORS  ──reads──►  dfyb/activity/sensors.py  (Quartz/Cocoa via pyobjc)
   idle_seconds()       non-mac / failure → safe defaults (idle=0, fullscreen=False)
   frontmost_is_fullscreen()
        │ Context{idle_seconds, is_fullscreen}
        ▼
   dfyb/scheduler/engine.py  ── PURE, no Tk, no I/O → fully unit-tested ──
   step(states, ctx) -> StepResult
        │ StepResult (reset / fire / defer / natural-break)
        ▼
   timer_loop translates ctk configs ↔ plain state, applies result,
   calls trigger_break() (unchanged popup path), and logs to
        ▼
   dfyb/activity/event_log.py  (BREAK_TAKEN / BREAK_DEFERRED / NATURAL_BREAK)  → fuels Phase 3
```

**Why Approach A** (vs. a full `Scheduler` class that owns the loop, or wrapping `trigger_break`): it isolates the scheduling *brain* as a pure, testable function and keeps the loop and the ctk configs where they are — **no UI surgery, minimal legacy churn, graceful off-macOS**. The full loop-owning refactor is deferred until the UI is modularized (Phase 0b-2).

## 4. Module layout

| File | Responsibility | Tk? | I/O? |
|------|----------------|-----|------|
| `dfyb/scheduler/__init__.py` | package marker | no | no |
| `dfyb/scheduler/engine.py` | constants, `Context`, `StepResult`, `is_natural_break`, `decide`, `step` — the brain | no | no |
| `dfyb/activity/sensors.py` | `idle_seconds`, `frontmost_is_fullscreen`, `read_context` (macOS via pyobjc; safe fallbacks) | no | yes (mockable) |
| `launch.py` (`BreakApp`) | translate configs ↔ state, apply `StepResult`, log events | yes | — |

New runtime dependency: **`pyobjc`** (Quartz/Cocoa), added to `requirements.txt`. (CI tests never import it — sensors are mocked; the pure engine is stdlib only.)

## 5. The decision logic (`dfyb/scheduler/engine.py`)

**Configurable constants** (module-level; can surface to settings UI in a later phase):
- `NATURAL_BREAK_IDLE_THRESHOLD_SECONDS = 300` (5 min)
- `AWAY_IDLE_THRESHOLD_SECONDS = 60`

**Data shapes:**
```python
@dataclass(frozen=True)
class Context:
    idle_seconds: float
    is_fullscreen: bool

@dataclass(frozen=True)
class BreakState:                  # plain, Tk-free snapshot of one break, parallel to the configs
    remaining: int                 # seconds left on this break's countdown
    interval_seconds: int          # the reset value (BreakConfig.get_interval_seconds())
    duration_seconds: int          # how long the break lasts (used for "longest wins")

@dataclass(frozen=True)
class StepResult:
    new_remaining: list            # updated `remaining` per break (write back to configs)
    natural_break: bool = False
    fire_index: int | None = None  # which break to pop
    defer_reason: str | None = None  # "fullscreen" | "away"
```

**Helpers (pure):**
```python
def is_natural_break(idle_seconds, threshold=NATURAL_BREAK_IDLE_THRESHOLD_SECONDS) -> bool:
    return idle_seconds >= threshold

def decide(ctx, away_threshold=AWAY_IDLE_THRESHOLD_SECONDS) -> str:  # "fire" | "defer"
    if ctx.is_fullscreen:
        return "defer"            # don't interrupt fullscreen
    if ctx.idle_seconds >= away_threshold:
        return "defer"            # briefly away — wait until back & active
    return "fire"
```

**`step(states, ctx) -> StepResult`** where `states` is a `list[BreakState]` parallel to the configs:
1. **idle ≥ natural threshold** → `natural_break=True`, `new_remaining[i] = states[i].interval_seconds` for all i (reset to full). Do not decrement.
2. Else decrement each break's `remaining` by 1; collect indices now ≤ 0 as **due**.
3. If any due:
   - `decide(ctx)` == `"defer"` → clamp each due break's `remaining` to `0` (stays due, no negative drift); `defer_reason` = `"fullscreen"` if `ctx.is_fullscreen` else `"away"`.
   - else (`"fire"`) → `fire_index` = the due break with the **largest `duration_seconds`** (preserves today's "longest wins"); set each due break's `new_remaining` to its `interval_seconds` (reset).
4. Else → just the decremented `new_remaining`.

Note: `remaining` resets to the break's **interval** (the value `BreakConfig.reset_timer()` uses, i.e. `get_interval_seconds()`), which `step` reads from `BreakState.interval_seconds`. `duration_seconds` is only used to choose which simultaneously-due break to pop. `step` stays Tk-free; the loop supplies all three values.

## 6. Integration into `timer_loop` (the only legacy touch)

Per tick (when running, not paused, no active popup):
```
ctx = read_context()                              # sensors
states = [BreakState(c.remaining, c.get_interval_seconds(), c.get_duration_seconds())
          for c in self.breaks]
result = step(states, ctx)
for c, r in zip(self.breaks, result.new_remaining):
    c.remaining = r                               # write back
if result.natural_break:
    if not self._idle_episode:                    # dedup: log once per episode
        self.event_log.append(NATURAL_BREAK, idle_seconds=ctx.idle_seconds)
        self._idle_episode = True
elif result.fire_index is not None:
    self._idle_episode = False
    self._deferred_episode = False
    self.trigger_break(self.breaks[result.fire_index])   # unchanged popup path
elif result.defer_reason:
    if not self._deferred_episode:                # dedup: log once per defer episode
        self.event_log.append(BREAK_DEFERRED, reason=result.defer_reason)
        self._deferred_episode = True
else:
    self._idle_episode = False
    self._deferred_episode = False
```
`BREAK_TAKEN` is logged in the existing `on_popup_close` callback with `used_seconds = int(time.time() - break_start_time)` (sets up #9's "% used").

`self.event_log = EventLog(EVENTS_FILE)` is created in `BreakApp.__init__`; `EVENTS_FILE = Path.home() / "Library" / "Application Support" / "DontForgetYourBreaks" / "events.jsonl"`.

The event-type constants `BREAK_TAKEN` and `IDLE_DETECTED` already exist in `dfyb/activity/event_log.py` (Phase 0a). Phase 1 **adds two new constants** there: `BREAK_DEFERRED = "break_deferred"` and `NATURAL_BREAK = "natural_break"`.

## 7. Sensors (`dfyb/activity/sensors.py`)

- `idle_seconds() -> float` — macOS: `Quartz.CGEventSourceSecondsSinceLastEventType(kCGEventSourceStateHIDSystemState, kCGAnyInputEventType)`. `sys.platform != "darwin"` → `0.0`; any exception → `0.0`.
- `frontmost_is_fullscreen() -> bool` — macOS best-effort: inspect the frontmost on-screen window via `Quartz.CGWindowListCopyWindowInfo` and compare its bounds to the main display bounds (full-cover ⇒ fullscreen). Non-mac → `False`; any exception → `False`. **Heuristic**, documented as such; a wrong `False` just means "fire" (today's behavior) — fails safe.
- `read_context() -> Context` — convenience that returns `Context(idle_seconds(), frontmost_is_fullscreen())`.

## 8. Testing

- **Pure engine** (`tests/test_scheduler_engine.py`) — exhaustive: `is_natural_break` boundary; `decide` over all idle/fullscreen combos; `step` cases — natural-break reset, fullscreen→defer (clamps to 0), away→defer, active→fire-picks-longest, not-due→decrement-only, multiple-due handling. All in CI (stdlib only).
- **Sensors** (`tests/test_sensors.py`) — monkeypatch the `Quartz` calls; assert the mocked idle value flows through; non-darwin and exception paths return safe defaults.
- **EventLog feed** — a test that asserts a `BREAK_DEFERRED` / `NATURAL_BREAK` event is appended with the right `type` + `data`.
- **Integration** (`timer_loop`) — verified by **launching the app** (threaded Tk, not CI-unit-testable). The brain it delegates to is fully covered, so the glue is thin.

## 9. Error handling & degradation

- Sensors never raise into the loop (each wrapped, returns a safe default). A failed sensor ⇒ "fire" path ⇒ today's behavior.
- Off-macOS: `idle=0 / fullscreen=False` ⇒ never natural-break, never defer ⇒ behaves exactly as today.
- EventLog append failures must not break the loop (best-effort logging; wrap if needed — note carried from the Phase 0a review: add a corrupt-line guard in `read()` and consider a `threading.Lock` since `timer_loop` runs on a background thread and may append concurrently with any future reader).

## 10. Decomposition (for the implementation plan)

Likely two plan-sized slices:
- **1a — the brain + sensors (fully testable):** `dfyb/scheduler/engine.py`, `dfyb/activity/sensors.py`, `pyobjc` dep, all unit tests. No behavior change yet.
- **1b — integration:** wire `step`/sensors/EventLog into `timer_loop`, add the `EventLog` instance + `BREAK_TAKEN` on close, dedup episodes. Verified by launching the app.

## 11. Out of scope (explicit)

- Meeting/video-call detection.
- Any settings-UI toggle for smart timing (always-on with constants for now; the UI is being modularized separately in Phase 0b-2).
- The full `Scheduler`-owns-the-loop refactor.
- Cross-platform sensors (macOS-only; others degrade to today's behavior).

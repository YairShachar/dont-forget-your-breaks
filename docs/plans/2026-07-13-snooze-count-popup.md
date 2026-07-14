# Snooze count + "originally due" on the popup — Implementation Plan (#37)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a snoozed break reappears, its popup shows "Snoozed N× already (originally due M min ago)" — derived purely from the event log.

**Architecture:** Three pure helpers in `dfyb/insights/counts.py` compute the count, the first-snooze elapsed time, and the display label from `EventLog.read()`; `CountdownPopup` renders the label; `BreakApp._process_break_queue` computes and passes the values when building the popup.

**Tech Stack:** Python 3, Tkinter/CustomTkinter, pytest.

**Spec:** `~/daily/specs/2026-07-13-snooze-count-popup-design.md`

## Global Constraints

- **Snooze count only** — no held/defer count.
- **Log-derived, pure, testable** — no new runtime state, no event-schema change,
  no change to snooze/requeue logic or `BREAK_SNOOZED` shape.
- Cycle reset = last `NATURAL_BREAK` or last `BREAK_TAKEN` for *this* break
  (whichever later). A `BREAK_TAKEN` for a different break does not reset.
- Copy: `1 → "Snoozed once already (...)"`, `n → "Snoozed {n}× already (...)"`;
  minutes rounded, `< 1 → "less than a minute ago"`.
- The line reuses `FONT_SIZES['helper']` + `COLORS['text_secondary']` (as the
  existing held-reason line).

---

### Task 1: Pure helpers `dfyb/insights/counts.py`

**Files:**
- Create: `dfyb/insights/counts.py`
- Test: `tests/test_counts.py`

**Interfaces:**
- Produces:
  - `snooze_count_since_taken(events, break_name) -> int`
  - `first_snooze_seconds_ago(events, break_name, now) -> float | None`
  - `snooze_summary_label(count, seconds_ago) -> str | None`
  used by Tasks 2–3.

- [ ] **Step 1: Write the failing tests.**

Create `tests/test_counts.py`:

```python
from dfyb.insights.counts import (
    snooze_count_since_taken, first_snooze_seconds_ago, snooze_summary_label)
from dfyb.activity.event_log import BREAK_SNOOZED, BREAK_TAKEN, NATURAL_BREAK


def ev(etype, ts=0, **data):
    return {"ts": ts, "type": etype, "data": data, "v": 1}


# --- snooze_count_since_taken ---

def test_count_no_events():
    assert snooze_count_since_taken([], "Micro") == 0


def test_count_snoozes_no_reset():
    events = [ev(BREAK_SNOOZED, name="Micro"), ev(BREAK_SNOOZED, name="Micro"),
              ev(BREAK_SNOOZED, name="Micro")]
    assert snooze_count_since_taken(events, "Micro") == 3


def test_count_resets_on_taken_same_break():
    events = [ev(BREAK_SNOOZED, name="Micro"),
              ev(BREAK_TAKEN, name="Micro"),
              ev(BREAK_SNOOZED, name="Micro")]
    assert snooze_count_since_taken(events, "Micro") == 1


def test_count_not_reset_by_other_breaks_take():
    events = [ev(BREAK_SNOOZED, name="Micro"),
              ev(BREAK_TAKEN, name="Normal"),
              ev(BREAK_SNOOZED, name="Micro")]
    assert snooze_count_since_taken(events, "Micro") == 2


def test_count_resets_on_natural_break():
    events = [ev(BREAK_SNOOZED, name="Micro"),
              ev(NATURAL_BREAK, idle_seconds=400),
              ev(BREAK_SNOOZED, name="Micro")]
    assert snooze_count_since_taken(events, "Micro") == 1


def test_count_ignores_other_break_snoozes():
    events = [ev(BREAK_SNOOZED, name="Normal"), ev(BREAK_SNOOZED, name="Micro")]
    assert snooze_count_since_taken(events, "Micro") == 1


# --- first_snooze_seconds_ago ---

def test_first_snooze_none_when_no_snooze():
    assert first_snooze_seconds_ago([], "Micro", now=1000) is None


def test_first_snooze_uses_first_in_cycle():
    events = [ev(BREAK_SNOOZED, ts=100, name="Micro"),
              ev(BREAK_SNOOZED, ts=400, name="Micro")]
    assert first_snooze_seconds_ago(events, "Micro", now=1000) == 900


def test_first_snooze_anchors_after_taken():
    events = [ev(BREAK_SNOOZED, ts=100, name="Micro"),
              ev(BREAK_TAKEN, ts=200, name="Micro"),
              ev(BREAK_SNOOZED, ts=700, name="Micro")]
    assert first_snooze_seconds_ago(events, "Micro", now=1000) == 300


# --- snooze_summary_label ---

def test_label_zero_is_none():
    assert snooze_summary_label(0, None) is None


def test_label_once():
    assert snooze_summary_label(1, 180) == "Snoozed once already (originally due 3 min ago)"


def test_label_plural():
    assert snooze_summary_label(2, 900) == "Snoozed 2× already (originally due 15 min ago)"


def test_label_sub_minute():
    assert snooze_summary_label(2, 30) == "Snoozed 2× already (originally due less than a minute ago)"


def test_label_no_time():
    assert snooze_summary_label(2, None) == "Snoozed 2× already"
```

- [ ] **Step 2: Run tests to verify they fail.**

Run: `.venv/bin/python -m pytest tests/test_counts.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'dfyb.insights.counts'`.

- [ ] **Step 3: Implement `dfyb/insights/counts.py`.**

```python
"""Snooze insight counts derived from the event log. Pure — unit-tested."""
from dfyb.activity.event_log import BREAK_SNOOZED, BREAK_TAKEN, NATURAL_BREAK

SECONDS_PER_MINUTE = 60


def _cycle_start_index(events, break_name):
    """Index where this break's current pending cycle begins (after the last
    NATURAL_BREAK or the last BREAK_TAKEN for this break, whichever is later)."""
    start = 0
    for i, e in enumerate(events):
        etype = e["type"]
        if etype == NATURAL_BREAK:
            start = i + 1
        elif etype == BREAK_TAKEN and e["data"].get("name") == break_name:
            start = i + 1
    return start


def snooze_count_since_taken(events, break_name):
    """How many times `break_name` was snoozed in its current cycle."""
    start = _cycle_start_index(events, break_name)
    return sum(1 for e in events[start:]
               if e["type"] == BREAK_SNOOZED and e["data"].get("name") == break_name)


def first_snooze_seconds_ago(events, break_name, now):
    """Seconds since the first snooze of `break_name` in its current cycle, or
    None if it hasn't been snoozed this cycle."""
    start = _cycle_start_index(events, break_name)
    for e in events[start:]:
        if e["type"] == BREAK_SNOOZED and e["data"].get("name") == break_name:
            return now - e["ts"]
    return None


def _format_minutes_ago(seconds):
    minutes = int(round(seconds / SECONDS_PER_MINUTE))
    if minutes < 1:
        return "less than a minute ago"
    return f"{minutes} min ago"


def snooze_summary_label(count, seconds_ago):
    """The popup line for the snooze count, or None when there's nothing to show."""
    if count <= 0:
        return None
    times = "once" if count == 1 else f"{count}×"
    if seconds_ago is None:
        return f"Snoozed {times} already"
    return f"Snoozed {times} already (originally due {_format_minutes_ago(seconds_ago)})"
```

- [ ] **Step 4: Run tests to verify they pass.**

Run: `.venv/bin/python -m pytest tests/test_counts.py -q`
Expected: PASS (14 tests).

- [ ] **Step 5: Commit.**

```bash
git add dfyb/insights/counts.py tests/test_counts.py
git commit -m "feat: add snooze count/first-snooze insight helpers (#37)"
```

---

### Task 2: Popup renders the snooze line

**Files:**
- Modify: `launch.py` — import (~`launch.py:38`); `CountdownPopup.__init__`
  (params + store); `CountdownPopup._build_ui` (after the held-reason block).

**Interfaces:**
- Consumes: `snooze_summary_label` (Task 1).
- Produces: `CountdownPopup(..., snooze_count=, first_snooze_ago=)` — used by Task 3.

- [ ] **Step 1: Import the helpers.**

After `from dfyb.snooze import snooze_delay_ms`:

```python
from dfyb.insights.counts import (
    snooze_count_since_taken, first_snooze_seconds_ago, snooze_summary_label)
```

- [ ] **Step 2: Add the constructor params + store them.**

In `CountdownPopup.__init__`, extend the signature (currently ends with
`snooze_minutes=DEFAULT_SNOOZE_MINUTES`):

```python
                 target_screen=None, held_reason=None,
                 snooze_minutes=DEFAULT_SNOOZE_MINUTES,
                 snooze_count=0, first_snooze_ago=None):
```

and next to `self.snooze_minutes = snooze_minutes` add:

```python
        self.snooze_count = snooze_count
        self.first_snooze_ago = first_snooze_ago
```

- [ ] **Step 3: Render the line after the held-reason block.**

In `_build_ui`, immediately after the held-reason block (`launch.py:313–321`,
the `if self.held_reason:` block), insert:

```python
        # Snooze insight line (#37): "Snoozed 2× already (originally due 15 min ago)".
        summary = snooze_summary_label(self.snooze_count, self.first_snooze_ago)
        if summary:
            ctk.CTkLabel(
                container, text=summary,
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['helper']),
                text_color=COLORS['text_secondary']
            ).pack(pady=(0, 6))
```

- [ ] **Step 4: Verify parse + compile.**

Run: `.venv/bin/python -c "import ast; ast.parse(open('launch.py').read())"`
Run: `.venv/bin/python -m py_compile launch.py`
Expected: no output for both.

- [ ] **Step 5: Commit.**

```bash
git add launch.py
git commit -m "feat: render snooze-count line on the popup (#37)"
```

---

### Task 3: Compute counts at popup creation

**Files:**
- Modify: `launch.py` — `BreakApp._process_break_queue`, right before the
  `self.active_popup = CountdownPopup(...)` call (`launch.py:1809`).

**Interfaces:**
- Consumes: `snooze_count_since_taken`, `first_snooze_seconds_ago` (Task 1);
  `CountdownPopup(..., snooze_count=, first_snooze_ago=)` (Task 2).

- [ ] **Step 1: Compute the values from the event log.**

Immediately before `self.status.configure(text=break_data['name'], ...)` /
`self.active_popup = CountdownPopup(...)`, add:

```python
        events = self.event_log.read()
        snooze_count = snooze_count_since_taken(events, break_data['name'])
        first_snooze_ago = first_snooze_seconds_ago(
            events, break_data['name'], time.time())
```

- [ ] **Step 2: Pass them into the constructor.**

In the `CountdownPopup(...)` call, after `snooze_minutes=self.snooze_minutes.get(),`:

```python
            snooze_minutes=self.snooze_minutes.get(),
            snooze_count=snooze_count,
            first_snooze_ago=first_snooze_ago,
```

- [ ] **Step 3: Verify parse + compile + full suite.**

Run: `.venv/bin/python -c "import ast; ast.parse(open('launch.py').read())"`
Run: `.venv/bin/python -m py_compile launch.py`
Run: `.venv/bin/python -m pytest -q`
Expected: no output for the first two; all tests PASS (incl. Task 1's 14).

- [ ] **Step 4: Commit.**

```bash
git add launch.py
git commit -m "feat: compute snooze count + first-snooze time for the popup (#37)"
```

---

### Task 4: Manual verification

**Files:** none.

- [ ] **Step 1: Run the app.** `.venv/bin/python launch.py`
- [ ] **Step 2:** Trigger a break with **auto-dismiss off**; snooze it (use a
  short snooze if impatient — the ▾ menu min is 5 min, so this step takes a few
  minutes, or temporarily lower an option for testing).
- [ ] **Step 3:** When it reappears → popup shows
  **"Snoozed once already (originally due N min ago)"**.
- [ ] **Step 4:** Snooze again → reappears as
  **"Snoozed 2× already (originally due N min ago)"**, elapsed growing.
- [ ] **Step 5:** Click **Done**; trigger the break fresh → **no** snooze line
  (cycle reset).
- [ ] **Step 6:** A never-snoozed break shows no snooze line; a break with a
  held reason still shows its held line (both can appear together).

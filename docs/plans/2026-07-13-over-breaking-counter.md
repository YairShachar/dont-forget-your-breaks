# Over-breaking counter Implementation Plan (#33)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a break runs past its duration with auto-dismiss off, the popup shows "Break over ✓" and a gentle amber "+MM:SS over your break" line that counts up until the user dismisses it.

**Architecture:** A pure `format_over_time` helper renders the count-up; `CountdownPopup.update_countdown` keeps its 1 Hz loop running past zero (auto-dismiss off) and reveals a hidden amber `over_label`. No change to the auto-dismiss path, progress bar, sounds, or snooze.

**Tech Stack:** Python 3, Tkinter/CustomTkinter, pytest.

**Spec:** `~/daily/specs/2026-07-13-over-breaking-counter-design.md`

## Global Constraints

- Over-breaking UI appears **only when auto-dismiss is off** (auto-dismiss on
  closes the popup at 0 — inherent, no extra guard).
- **No hardcoded strings/colors:** new copy goes in named constants
  (`BREAK_OVER_TEXT`, `OVER_BREAK_SUFFIX`); the amber reuses
  `COLORS['accent_orange']`, font reuses `FONT_SIZES['helper']`.
- The end-sound + `_bring_to_attention()` must still fire **exactly once** at the
  duration transition (today's behavior).
- The over-line sits **directly under the countdown** — use
  `pack(after=self.countdown_label, …)`, never a bare `pack()`.
- Live-only: no event logging, no auto-close, no cap.

---

### Task 1: Pure helper `format_over_time`

**Files:**
- Create: `dfyb/insights/over_break.py`
- Test: `tests/test_over_break.py`

**Interfaces:**
- Produces: `format_over_time(seconds: int) -> str` (e.g. `134 -> "+02:14"`),
  used by Task 4.

- [ ] **Step 1: Write the failing tests.**

Create `tests/test_over_break.py`:

```python
from dfyb.insights.over_break import format_over_time


def test_zero():
    assert format_over_time(0) == "+00:00"


def test_one_second():
    assert format_over_time(1) == "+00:01"


def test_under_a_minute():
    assert format_over_time(59) == "+00:59"


def test_exactly_a_minute():
    assert format_over_time(60) == "+01:00"


def test_minutes_and_seconds():
    assert format_over_time(134) == "+02:14"


def test_negative_clamps_to_zero():
    assert format_over_time(-5) == "+00:00"
```

- [ ] **Step 2: Run tests to verify they fail.**

Run: `.venv/bin/python -m pytest tests/test_over_break.py -q`
Expected: FAIL with `ModuleNotFoundError`/`ImportError` for `dfyb.insights.over_break`.

- [ ] **Step 3: Implement the helper.**

Create `dfyb/insights/over_break.py`:

```python
"""Format the 'over your break' count-up. Pure (no Tk, no I/O) — unit-tested."""


def format_over_time(seconds):
    """Seconds past the break's duration as a signed MM:SS string.

    Always MM:SS (unlike the popup's mixed Xs / MM:SS countdown), e.g.
    1 -> '+00:01', 134 -> '+02:14'. Negative inputs are clamped to 0.
    """
    seconds = max(0, seconds)
    m, s = divmod(seconds, 60)
    return f"+{m:02d}:{s:02d}"
```

- [ ] **Step 4: Run tests to verify they pass.**

Run: `.venv/bin/python -m pytest tests/test_over_break.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit.**

```bash
git add dfyb/insights/over_break.py tests/test_over_break.py
git commit -m "feat: add format_over_time helper for over-breaking count-up (#33)"
```

---

### Task 2: Constants + import

**Files:**
- Modify: `launch.py` — CONFIGURATION block (near the popup copy constants,
  around `launch.py:158`); the imports near `launch.py:29`.

**Interfaces:**
- Produces: `BREAK_OVER_TEXT`, `OVER_BREAK_SUFFIX`, and the imported
  `format_over_time` — used by Tasks 3 and 4.

- [ ] **Step 1: Import the helper.**

Add near the other `dfyb.insights` imports (`launch.py:36` imports from
`transparency`):

```python
from dfyb.insights.over_break import format_over_time
```

- [ ] **Step 2: Add the constants.**

In the CONFIGURATION block, immediately after the `CONFIG_COMMIT_DEBOUNCE_MS`
line:

```python
BREAK_OVER_TEXT = "Break over ✓"       # big label once a break's duration elapses
OVER_BREAK_SUFFIX = "over your break"  # trails the +MM:SS count-up
```

- [ ] **Step 3: Verify parse.**

Run: `.venv/bin/python -c "import ast; ast.parse(open('launch.py').read())"`
Expected: no output.

- [ ] **Step 4: Commit.**

```bash
git add launch.py
git commit -m "chore: add over-breaking copy constants + import (#33)"
```

---

### Task 3: Hidden amber over-line widget

**Files:**
- Modify: `launch.py` — `CountdownPopup._build_ui`, right after the
  `self.countdown_label.pack(...)` (`launch.py:331`).

**Interfaces:**
- Produces: `self.over_label` (a hidden `CTkLabel`) — used by Task 4.

- [ ] **Step 1: Create the hidden over-line.**

After:

```python
        self.countdown_label.pack(pady=10)
```

insert:

```python
        # Amber count-up shown only when a break runs past its duration (#33).
        self.over_label = ctk.CTkLabel(
            container, text="",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['helper']),
            text_color=COLORS['accent_orange']
        )
        # not packed yet — revealed by update_countdown once over the duration
```

- [ ] **Step 2: Verify parse + compile.**

Run: `.venv/bin/python -c "import ast; ast.parse(open('launch.py').read())"`
Run: `.venv/bin/python -m py_compile launch.py`
Expected: no output for both.

- [ ] **Step 3: Commit.**

```bash
git add launch.py
git commit -m "feat: add hidden over-breaking label to the popup (#33)"
```

---

### Task 4: Count-up logic in `update_countdown`

**Files:**
- Modify: `launch.py` — `CountdownPopup.update_countdown` (`launch.py:393–418`).

**Interfaces:**
- Consumes: `format_over_time` (Task 1), `BREAK_OVER_TEXT`/`OVER_BREAK_SUFFIX`
  (Task 2), `self.over_label` (Task 3).

- [ ] **Step 1: Replace `update_countdown` with the count-up version.**

Replace the current method:

```python
    def update_countdown(self):
        if self.closed:
            return

        self.remaining -= 1
        self.countdown_label.configure(text=self._format_time(self.remaining))

        if self.remaining <= 0:
            # Timer finished - handle end sound
            if self.end_sound and self.end_sound != "None":
                if self.loop_end_sound:
                    threading.Thread(
                        target=looping_sound,
                        args=(self.sound_stop_event, self.end_sound),
                        daemon=True
                    ).start()
                else:
                    play_sound(self.end_sound)

            if self.auto_dismiss:
                self.close()
            else:
                self.countdown_label.configure(text="Done!")
                self._bring_to_attention()
        else:
            self.window.after(1000, self.update_countdown)
```

with:

```python
    def update_countdown(self):
        if self.closed:
            return

        self.remaining -= 1

        if self.remaining > 0:
            self.countdown_label.configure(text=self._format_time(self.remaining))
            self.window.after(1000, self.update_countdown)
            return

        if self.remaining == 0:
            # Duration just elapsed — fire the end sound + attention once.
            if self.end_sound and self.end_sound != "None":
                if self.loop_end_sound:
                    threading.Thread(
                        target=looping_sound,
                        args=(self.sound_stop_event, self.end_sound),
                        daemon=True
                    ).start()
                else:
                    play_sound(self.end_sound)

            if self.auto_dismiss:
                self.close()
                return
            self.countdown_label.configure(text=BREAK_OVER_TEXT)
            self._bring_to_attention()

        # auto-dismiss off: count up the time spent over the break (#33).
        over_seconds = -self.remaining
        if over_seconds >= 1:
            self.over_label.configure(
                text=f"{format_over_time(over_seconds)} {OVER_BREAK_SUFFIX}")
            if self.over_label.winfo_manager() != "pack":
                self.over_label.pack(after=self.countdown_label, pady=(0, ROW_SPACING))
        self.window.after(1000, self.update_countdown)
```

- [ ] **Step 2: Verify parse + compile + full suite.**

Run: `.venv/bin/python -c "import ast; ast.parse(open('launch.py').read())"`
Run: `.venv/bin/python -m py_compile launch.py`
Run: `.venv/bin/python -m pytest -q`
Expected: no output for the first two; all tests PASS (incl. Task 1's).

- [ ] **Step 3: Commit.**

```bash
git add launch.py
git commit -m "feat: count up over-breaking time on the popup (#33)"
```

---

### Task 5: Manual verification

**Files:** none.

- [ ] **Step 1: Run the app.** `.venv/bin/python launch.py`
- [ ] **Step 2:** Configure a break with a short duration (~3 s) and
  **auto-dismiss off**; trigger it via "Break now".
- [ ] **Step 3:** At 0 → big label reads "Break over ✓", end sound plays once,
  no over-line yet.
- [ ] **Step 4:** After 1 s → amber "+00:01 over your break" appears directly
  under the label and climbs each second (+00:02, +00:03, …).
- [ ] **Step 5:** Click **Done** (and separately test **Snooze**) → popup
  dismisses and the count-up stops.
- [ ] **Step 6:** A break with **auto-dismiss on** still closes at 0 — no
  over-line, no "Break over ✓" lingering.

# "Snoozed break" row on the main window — Implementation Plan (#51)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a "Snoozed" section below the break cards — one live row per pending snooze (💤 name · returns in MM:SS · ✕) — and log the snooze lifecycle (cancel/return) to the event log.

**Architecture:** A pure `snooze_remaining` helper; two new event constants; an in-memory `_pending_snoozes` list (entry per snooze with `fire_time` + `after_id`) that `update_ui` renders as reconciled rows; `_requeue_break`/`_cancel_snooze` manage entries and log lifecycle events.

**Tech Stack:** Python 3, Tkinter/CustomTkinter, pytest.

**Spec:** `~/daily/specs/2026-07-14-snoozed-break-row-design.md`

## Global Constraints

- Live row state (`_pending_snoozes`) is in-memory only; snooze **history** is
  persisted as events (log-everything ideology, #52).
- Two new event types (`break_snooze_cancelled`, `break_snooze_returned`);
  additive, `SCHEMA_VERSION` stays 1.
- Rows reconcile in place (create/update/destroy by `id(entry)`) — no per-tick
  rebuild/flicker.
- Countdown "returns in MM:SS"; due-but-held → "returning…".
- Reuse existing tokens (`bg_panel`, `text_secondary`, `border`, `bg_hover`,
  `FONT_SIZES`, `CORNER_RADIUS_*`, `BUTTON_HEIGHT_SMALL`, `PADDING_PANEL_X`).

---

### Task 1: Pure additions — `snooze_remaining` + event constants

**Files:**
- Modify: `dfyb/snooze.py`, `tests/test_snooze.py`, `dfyb/activity/event_log.py`.

**Interfaces:**
- Produces: `snooze_remaining(fire_time, now) -> int`;
  `BREAK_SNOOZE_CANCELLED`, `BREAK_SNOOZE_RETURNED` — used by Tasks 2–3.

- [ ] **Step 1: Write the failing `snooze_remaining` tests.**

Append to `tests/test_snooze.py`:

```python
from dfyb.snooze import snooze_remaining


def test_remaining_counts_down():
    assert snooze_remaining(1000, 970) == 30


def test_remaining_zero_at_fire():
    assert snooze_remaining(1000, 1000) == 0


def test_remaining_clamps_past_due():
    assert snooze_remaining(1000, 1010) == 0


def test_remaining_ten_seconds():
    assert snooze_remaining(1010, 1000) == 10
```

- [ ] **Step 2: Run to verify failure.**

Run: `.venv/bin/python -m pytest tests/test_snooze.py -q`
Expected: FAIL — `ImportError: cannot import name 'snooze_remaining'`.

- [ ] **Step 3: Add `snooze_remaining` to `dfyb/snooze.py`.**

After `should_hold_snooze`:

```python
def snooze_remaining(fire_time, now):
    """Whole seconds until a snoozed break returns (clamped at 0)."""
    return max(0, int(fire_time - now))
```

- [ ] **Step 4: Add the two event constants.**

In `dfyb/activity/event_log.py`, after `BREAK_SNOOZED = "break_snoozed"`:

```python
BREAK_SNOOZE_CANCELLED = "break_snooze_cancelled"
BREAK_SNOOZE_RETURNED = "break_snooze_returned"
```

- [ ] **Step 5: Run tests to verify pass.**

Run: `.venv/bin/python -m pytest tests/test_snooze.py -q`
Expected: PASS (26 tests).

- [ ] **Step 6: Commit.**

```bash
git add dfyb/snooze.py tests/test_snooze.py dfyb/activity/event_log.py
git commit -m "feat: add snooze_remaining + snooze cancel/return event constants (#51)"
```

---

### Task 2: Pending-snooze tracking + lifecycle logging

**Files:**
- Modify: `launch.py` — imports (`:29`, `:~37`), `BreakApp.__init__` (`:1047`),
  `on_snooze` closure, `_requeue_break`; add `_cancel_snooze`.

**Interfaces:**
- Consumes: `snooze_remaining`, `BREAK_SNOOZE_CANCELLED`, `BREAK_SNOOZE_RETURNED`
  (Task 1).
- Produces: `self._pending_snoozes`, `self._cancel_snooze(entry)` — used by Task 3.

- [ ] **Step 1: Extend the imports.**

Change (`:29`):

```python
from dfyb.activity.event_log import EventLog, BREAK_TAKEN, BREAK_SNOOZED
```

to:

```python
from dfyb.activity.event_log import (
    EventLog, BREAK_TAKEN, BREAK_SNOOZED,
    BREAK_SNOOZE_CANCELLED, BREAK_SNOOZE_RETURNED)
```

and add `snooze_remaining` to the `dfyb.snooze` import list.

- [ ] **Step 2: Init the tracking state.**

After `self.break_queue = []` (`:1047`):

```python
        self._pending_snoozes = []   # entries: {name, fire_time, after_id}
        self._snooze_rows = {}       # id(entry) -> {"frame", "status"}
```

- [ ] **Step 3: Track the entry in `on_snooze`.**

Replace the scheduling tail of the `on_snooze` closure:

```python
            # An explicit snooze always comes back after its delay, regardless of
            # Start/Stop; _requeue_break holds it while paused or context-deferred.
            self.root.after(snooze_delay_ms(snooze_seconds),
                            lambda: self._requeue_break(break_data))
```

with:

```python
            # An explicit snooze always comes back after its delay, regardless of
            # Start/Stop; _requeue_break holds it while paused or context-deferred.
            entry = {"name": break_data['name'],
                     "fire_time": time.time() + snooze_seconds, "after_id": None}
            entry["after_id"] = self.root.after(
                snooze_delay_ms(snooze_seconds),
                lambda: self._requeue_break(break_data, entry))
            self._pending_snoozes.append(entry)
```

- [ ] **Step 4: Thread `entry` through `_requeue_break` + log the return.**

Replace `_requeue_break`:

```python
    def _requeue_break(self, break_data):
        """Re-show a snoozed break. An explicit snooze always returns regardless of
        Start/Stop; a Pause holds it, and context (meeting/fullscreen/away/
        mid-activity) defers it like a scheduled break (#42), re-checking later."""
        ctx = read_context(
            check_meeting=self.defer_during_meetings.get(),
            check_fullscreen=self.defer_during_fullscreen.get(),
        )
        pause = (self.activity_pause_seconds.get()
                 if self.defer_while_active.get() else 0)
        if should_hold_snooze(self.paused, decide(ctx, pause_threshold=pause) == DEFER):
            # Not a good moment (paused or context-deferred) — wait and re-check.
            logging.info("snoozed break held (paused=%s fullscreen=%s meeting=%s), re-checking",
                         self.paused, ctx.is_fullscreen, ctx.is_meeting)
            self.root.after(SNOOZE_RECHECK_MS, lambda: self._requeue_break(break_data))
            return
        self.break_queue.append(break_data)
        self.root.after(0, self._process_break_queue)
```

with:

```python
    def _requeue_break(self, break_data, entry=None):
        """Re-show a snoozed break. An explicit snooze always returns regardless of
        Start/Stop; a Pause holds it, and context (meeting/fullscreen/away/
        mid-activity) defers it like a scheduled break (#42), re-checking later."""
        ctx = read_context(
            check_meeting=self.defer_during_meetings.get(),
            check_fullscreen=self.defer_during_fullscreen.get(),
        )
        pause = (self.activity_pause_seconds.get()
                 if self.defer_while_active.get() else 0)
        if should_hold_snooze(self.paused, decide(ctx, pause_threshold=pause) == DEFER):
            # Not a good moment (paused or context-deferred) — wait and re-check.
            logging.info("snoozed break held (paused=%s fullscreen=%s meeting=%s), re-checking",
                         self.paused, ctx.is_fullscreen, ctx.is_meeting)
            after_id = self.root.after(SNOOZE_RECHECK_MS,
                                       lambda: self._requeue_break(break_data, entry))
            if entry is not None:
                entry["after_id"] = after_id
            return
        if entry is not None and entry in self._pending_snoozes:
            self._pending_snoozes.remove(entry)
        self._record_event(BREAK_SNOOZE_RETURNED, name=break_data['name'])
        self.break_queue.append(break_data)
        self.root.after(0, self._process_break_queue)
```

- [ ] **Step 5: Add `_cancel_snooze` (logs the cancel).**

Immediately after `_requeue_break`:

```python
    def _cancel_snooze(self, entry):
        """Cancel a pending snooze (✕ on its row): drop the scheduled re-fire."""
        if entry.get("after_id") is not None:
            try:
                self.root.after_cancel(entry["after_id"])
            except Exception:
                pass
        if entry in self._pending_snoozes:
            self._pending_snoozes.remove(entry)
        self._record_event(
            BREAK_SNOOZE_CANCELLED, name=entry["name"],
            remaining_seconds=snooze_remaining(entry["fire_time"], time.time()))
```

- [ ] **Step 6: Verify parse + compile + suite.**

Run: `.venv/bin/python -c "import ast; ast.parse(open('launch.py').read())"`
Run: `.venv/bin/python -m py_compile launch.py`
Run: `.venv/bin/python -m pytest -q`
Expected: no output for the first two; all pass.

- [ ] **Step 7: Commit.**

```bash
git add launch.py
git commit -m "feat: track pending snoozes + log snooze cancel/return (#51)"
```

---

### Task 3: The "Snoozed" section + dynamic rows

**Files:**
- Modify: `launch.py` — `_build_ui` (after cards loop, `:1270`); add
  `_build_snooze_row`, `_render_snooze_rows`; `update_ui` (`:1969–2009`).

**Interfaces:**
- Consumes: `self._pending_snoozes`, `self._snooze_rows`, `snooze_remaining`,
  `self._cancel_snooze` (Task 2).

- [ ] **Step 1: Add the container in `_build_ui`.**

After the cards loop (before `# Bottom bar`, `:1272`):

```python
        # Snoozed-break section (dynamic rows appear while a snooze is pending).
        self._snoozed_container = ctk.CTkFrame(main_frame, fg_color="transparent")
        self._snoozed_container.pack(fill="x")
        self._snooze_header = ctk.CTkLabel(
            self._snoozed_container, text="Snoozed",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['helper']),
            text_color=COLORS['text_secondary'])
        # header + rows packed/cleared by _render_snooze_rows
```

- [ ] **Step 2: Add `_build_snooze_row` and `_render_snooze_rows`.**

Add as methods on `BreakApp` (e.g. just above `update_ui`):

```python
    def _build_snooze_row(self, entry, status):
        row = ctk.CTkFrame(self._snoozed_container, corner_radius=CORNER_RADIUS_PANEL,
                           fg_color=COLORS['bg_panel'])
        row.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(
            row, text=f"💤 {entry['name']}",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
        ).pack(side="left", padx=(PADDING_PANEL_X, 0), pady=8)
        ctk.CTkButton(
            row, text="✕", width=28, height=BUTTON_HEIGHT_SMALL,
            corner_radius=CORNER_RADIUS_INPUT, fg_color="transparent",
            border_width=1, border_color=COLORS['border'], hover_color=COLORS['bg_hover'],
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['helper']),
            command=lambda: self._cancel_snooze(entry)
        ).pack(side="right", padx=(0, PADDING_PANEL_X), pady=8)
        status_label = ctk.CTkLabel(
            row, text=status,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['helper']),
            text_color=COLORS['text_secondary'])
        status_label.pack(side="right", padx=(0, 8), pady=8)
        return {"frame": row, "status": status_label}

    def _render_snooze_rows(self, now):
        entries = self._pending_snoozes
        if entries and self._snooze_header.winfo_manager() != "pack":
            self._snooze_header.pack(anchor="w", padx=PADDING_PANEL_X, pady=(4, 2))
        elif not entries and self._snooze_header.winfo_manager() == "pack":
            self._snooze_header.pack_forget()
        current = set()
        for entry in entries:
            eid = id(entry)
            current.add(eid)
            remaining = snooze_remaining(entry["fire_time"], now)
            status = (f"returns in {self._format_time(remaining)}"
                      if remaining > 0 else "returning…")
            if eid in self._snooze_rows:
                self._snooze_rows[eid]["status"].configure(text=status)
            else:
                self._snooze_rows[eid] = self._build_snooze_row(entry, status)
        for eid in list(self._snooze_rows):
            if eid not in current:
                self._snooze_rows[eid]["frame"].destroy()
                del self._snooze_rows[eid]
```

- [ ] **Step 3: Drive it from `update_ui`.**

Change the start of `update_ui`:

```python
    def update_ui(self):
        """Update timer displays for all breaks."""
        next_break = None
        min_remaining = float('inf')
```

to add a `now`:

```python
    def update_ui(self):
        """Update timer displays for all breaks."""
        next_break = None
        min_remaining = float('inf')
        now = time.time()
```

and change the tail:

```python
        self.root.after(1000, self.update_ui)
```

to:

```python
        self._render_snooze_rows(now)
        self.root.after(1000, self.update_ui)
```

- [ ] **Step 4: Verify parse + compile + suite.**

Run: `.venv/bin/python -c "import ast; ast.parse(open('launch.py').read())"`
Run: `.venv/bin/python -m py_compile launch.py`
Run: `.venv/bin/python -m pytest -q`
Expected: no output for the first two; all pass.

- [ ] **Step 5: Commit.**

```bash
git add launch.py
git commit -m "feat: show live Snoozed-break rows with cancel on the main window (#51)"
```

---

### Task 4: Manual verification

**Files:** none.

- [ ] **Step 1: Run the app.** `.venv/bin/python launch.py`
- [ ] **Step 2:** "Break now" on a snoozable break → **Snooze 30 sec** → a "Snoozed"
  section appears: "💤 Normal Break · returns in 00:29 · ✕", counting down. Console
  logs `break_snoozed ... seconds=30`.
- [ ] **Step 3:** Let it reach 0 → row shows "returning…", the popup returns, the
  row disappears; console logs `break_snooze_returned`.
- [ ] **Step 4:** Snooze again → new row; click **✕** → row disappears, the break
  does NOT return; console logs `break_snooze_cancelled ... remaining_seconds=…`.
- [ ] **Step 5:** Two different breaks snoozed → two rows. No pending → no section.
- [ ] **Step 6:** Pause the app with a snooze pending → countdown hits 0, shows
  "returning…", returns after unpause.

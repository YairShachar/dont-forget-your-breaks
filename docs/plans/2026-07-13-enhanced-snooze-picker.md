# Enhanced snooze picker (seconds + custom) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Snooze durations become seconds-based; the ▾ menu gains short presets (incl. 1 min) plus a "Custom…" dialog for arbitrary durations, remembered as the new default.

**Architecture:** `dfyb/snooze.py` moves to seconds and gains formatting + custom-parse helpers; the popup's Snooze menu is rebuilt from seconds presets with a Custom… item that opens a small token-styled `CTkToplevel`; `BreakApp` persists `snooze_seconds`.

**Tech Stack:** Python 3, Tkinter/CustomTkinter 5.2.2, pytest.

**Spec:** `~/daily/specs/2026-07-13-enhanced-snooze-picker-design.md`

## Global Constraints

- Snooze unit is **seconds** internally. Presets
  `[30, 60, 120, 300, 600, 900, 1800]`; default `300`.
- Pref `snooze_seconds`, backward-compatible with old `snooze_minutes` (×60).
- **No hardcoded values:** presets/default/cap/units are named constants; dialog
  reuses `CORNER_RADIUS_*`, `COLORS`, `FONT_SIZES`, `PADDING_*`.
- Custom value must be a positive integer ≤ `MAX_SNOOZE_SECONDS`; invalid input
  shows an inline hint, never crashes.
- No change to requeue/defer logic; snooze-on-card countdown is separate (#51).
- `BREAK_SNOOZED` logs `seconds` (was `minutes`) — data-field rename, no reader
  depends on the value.

---

### Task 1: `dfyb/snooze.py` — seconds + formatting + custom parse

**Files:**
- Modify: `dfyb/snooze.py`
- Modify: `tests/test_snooze.py` (rewrite for seconds)

**Interfaces:**
- Produces: `snooze_delay_ms(seconds) -> int`, `format_snooze_short(seconds) -> str`,
  `format_snooze_long(seconds) -> str`,
  `custom_snooze_seconds(raw_text, unit, max_seconds) -> int | None` — used by Tasks 2–4.

- [ ] **Step 1: Rewrite the tests.**

Replace the contents of `tests/test_snooze.py` with:

```python
from dfyb.snooze import (
    snooze_delay_ms, format_snooze_short, format_snooze_long, custom_snooze_seconds)

MAX = 24 * 60 * 60


def test_delay_ms_five_minutes():
    assert snooze_delay_ms(300) == 300000


def test_delay_ms_thirty_seconds():
    assert snooze_delay_ms(30) == 30000


def test_delay_ms_is_int():
    result = snooze_delay_ms(1.5)
    assert result == 1500
    assert isinstance(result, int)


def test_short_seconds():
    assert format_snooze_short(30) == "30s"


def test_short_whole_minute():
    assert format_snooze_short(60) == "1m"


def test_short_minutes_and_seconds():
    assert format_snooze_short(90) == "1m30s"


def test_short_five_minutes():
    assert format_snooze_short(300) == "5m"


def test_long_seconds():
    assert format_snooze_long(30) == "30 sec"


def test_long_whole_minute():
    assert format_snooze_long(60) == "1 min"


def test_long_minutes_and_seconds():
    assert format_snooze_long(90) == "1 min 30 sec"


def test_long_five_minutes():
    assert format_snooze_long(300) == "5 min"


def test_custom_seconds_unit():
    assert custom_snooze_seconds("45", "sec", MAX) == 45


def test_custom_minutes_unit():
    assert custom_snooze_seconds("2", "min", MAX) == 120


def test_custom_zero_is_none():
    assert custom_snooze_seconds("0", "sec", MAX) is None


def test_custom_negative_is_none():
    assert custom_snooze_seconds("-3", "sec", MAX) is None


def test_custom_non_numeric_is_none():
    assert custom_snooze_seconds("abc", "sec", MAX) is None


def test_custom_empty_is_none():
    assert custom_snooze_seconds("", "sec", MAX) is None


def test_custom_over_cap_is_none():
    assert custom_snooze_seconds("99999999", "min", 86400) is None
```

- [ ] **Step 2: Run to verify failure.**

Run: `.venv/bin/python -m pytest tests/test_snooze.py -q`
Expected: FAIL — `ImportError` for `format_snooze_short` (and delay assertions
mismatch under the old minutes contract).

- [ ] **Step 3: Rewrite `dfyb/snooze.py`.**

```python
"""Snooze timing + formatting helpers. Pure (no Tk, no I/O) — unit-tested."""

MS_PER_SECOND = 1000
SECONDS_PER_MINUTE = 60


def snooze_delay_ms(seconds):
    """Snooze duration in whole milliseconds for Tk's `after` (needs an int)."""
    return int(seconds * MS_PER_SECOND)


def format_snooze_short(seconds):
    """Compact label for the Snooze button: 45s / 1m / 5m / 1m30s."""
    if seconds < SECONDS_PER_MINUTE:
        return f"{seconds}s"
    minutes, rem = divmod(seconds, SECONDS_PER_MINUTE)
    return f"{minutes}m" if rem == 0 else f"{minutes}m{rem}s"


def format_snooze_long(seconds):
    """Readable label for the ▾ menu: 30 sec / 1 min / 2 min / 1 min 30 sec."""
    if seconds < SECONDS_PER_MINUTE:
        return f"{seconds} sec"
    minutes, rem = divmod(seconds, SECONDS_PER_MINUTE)
    return f"{minutes} min" if rem == 0 else f"{minutes} min {rem} sec"


def custom_snooze_seconds(raw_text, unit, max_seconds):
    """Parse the custom dialog (a number + 'sec'/'min') to seconds, or None if
    not a positive integer within `max_seconds`."""
    try:
        value = int(str(raw_text).strip())
    except (ValueError, TypeError):
        return None
    if value <= 0:
        return None
    seconds = value if unit == "sec" else value * SECONDS_PER_MINUTE
    if seconds > max_seconds:
        return None
    return seconds
```

- [ ] **Step 4: Run to verify pass.**

Run: `.venv/bin/python -m pytest tests/test_snooze.py -q`
Expected: PASS (18 tests).

- [ ] **Step 5: Commit.**

```bash
git add dfyb/snooze.py tests/test_snooze.py
git commit -m "feat: seconds-based snooze helpers + short/long/custom formatters"
```

---

### Task 2: Constants, import, pref migration

**Files:**
- Modify: `launch.py` — CONFIGURATION (`SNOOZE_OPTIONS_MINUTES`/`DEFAULT_SNOOZE_MINUTES`
  lines); imports (`from dfyb.snooze import ...`); `BreakApp.__init__` snooze pref;
  `_save_preferences`.

**Interfaces:**
- Produces: `SNOOZE_OPTIONS_SECONDS`, `DEFAULT_SNOOZE_SECONDS`, `MAX_SNOOZE_SECONDS`,
  `CUSTOM_SNOOZE_UNITS`, `CUSTOM_SNOOZE_DEFAULT_UNIT`, `self.snooze_seconds`,
  imported formatters — used by Tasks 3–4.

- [ ] **Step 1: Swap the constants.**

Replace:

```python
SNOOZE_OPTIONS_MINUTES = [5, 10, 15, 30]  # snooze durations offered on the popup ▾ menu
DEFAULT_SNOOZE_MINUTES = 5                 # default snooze length (persisted as snooze_minutes)
```

with:

```python
SNOOZE_OPTIONS_SECONDS = [30, 60, 120, 300, 600, 900, 1800]  # ▾ menu presets
DEFAULT_SNOOZE_SECONDS = 300                                  # default snooze (5 min)
MAX_SNOOZE_SECONDS = 24 * 60 * 60                             # cap for a custom value
CUSTOM_SNOOZE_UNITS = ["sec", "min"]                          # segmented-control options
CUSTOM_SNOOZE_DEFAULT_UNIT = "sec"                            # unit selected first in the dialog
```

- [ ] **Step 2: Update the import.**

Replace `from dfyb.snooze import snooze_delay_ms` with:

```python
from dfyb.snooze import (
    snooze_delay_ms, format_snooze_short, format_snooze_long, custom_snooze_seconds)
```

- [ ] **Step 3: Migrate the pref.**

Replace the `self.snooze_minutes = ctk.IntVar(...)` block with:

```python
        # Default snooze length (seconds), remembered from the ▾ picker.
        # Migrates an old minutes-based pref (×60) so existing configs still load.
        self.snooze_seconds = ctk.IntVar(
            value=self.saved_prefs.get(
                "snooze_seconds",
                self.saved_prefs.get("snooze_minutes", DEFAULT_SNOOZE_SECONDS // 60) * 60)
        )
```

- [ ] **Step 4: Persist it.**

In `_save_preferences`, replace `"snooze_minutes": self.snooze_minutes.get(),`
with `"snooze_seconds": self.snooze_seconds.get(),`.

- [ ] **Step 5: Verify parse.**

Run: `.venv/bin/python -c "import ast; ast.parse(open('launch.py').read())"`
Expected: no output. (Popup still references the old name until Task 3 — but the
module parses fine.)

- [ ] **Step 6: Commit.**

```bash
git add launch.py
git commit -m "chore: seconds snooze constants + pref migration"
```

---

### Task 3: Popup — seconds, menu, Custom dialog

**Files:**
- Modify: `launch.py` — `CountdownPopup.__init__` (rename param), `_build_ui`
  (button label), `snooze` (seconds), `_open_snooze_menu` (seconds + Custom);
  add `_open_custom_snooze`.

**Interfaces:**
- Consumes: constants + formatters (Task 2).
- Produces: `CountdownPopup(..., snooze_seconds=...)`, `snooze(seconds=None)` —
  used by Task 4.

- [ ] **Step 1: Rename the constructor param + stored attr.**

In `CountdownPopup.__init__`, change `snooze_minutes=DEFAULT_SNOOZE_MINUTES` →
`snooze_seconds=DEFAULT_SNOOZE_SECONDS`, and `self.snooze_minutes = snooze_minutes`
→ `self.snooze_seconds = snooze_seconds`. (Leave `snooze_count`/`first_snooze_ago`.)

- [ ] **Step 2: Button label via `format_snooze_short`.**

In `_build_ui`, change the main snooze button text:

```python
                text=f"Snooze {format_snooze_short(self.snooze_seconds)}",
```

- [ ] **Step 3: `snooze` accepts seconds.**

Replace the `snooze` method:

```python
    def snooze(self, seconds=None):
        """Snooze the break; `seconds` defaults to the current default."""
        if self.closed or self.snoozed:
            return
        chosen = self.snooze_seconds if seconds is None else seconds
        self.snoozed = True
        self.sound_stop_event.set()
        if self.on_snooze:
            self.on_snooze(chosen)
        self.closed = True
        self._dismiss()
```

- [ ] **Step 4: Rebuild `_open_snooze_menu` for seconds + Custom.**

Replace `_open_snooze_menu`:

```python
    def _open_snooze_menu(self):
        """Pop a menu of snooze durations (+ Custom…) under the ▾ button."""
        menu = tk.Menu(self.window, tearoff=0)
        selected = tk.IntVar(value=self.snooze_seconds)
        for seconds in SNOOZE_OPTIONS_SECONDS:
            menu.add_radiobutton(
                label=format_snooze_long(seconds), value=seconds, variable=selected,
                command=lambda s=seconds: self.snooze(s))
        menu.add_separator()
        menu.add_command(label="Custom…", command=self._open_custom_snooze)
        menu.tk_popup(
            self.snooze_menu_btn.winfo_rootx(),
            self.snooze_menu_btn.winfo_rooty() + self.snooze_menu_btn.winfo_height())
```

- [ ] **Step 5: Add the Custom dialog.**

Add immediately after `_open_snooze_menu`:

```python
    def _open_custom_snooze(self):
        """Small styled dialog to snooze for an arbitrary duration."""
        dialog = ctk.CTkToplevel(self.window)
        dialog.title("Custom snooze")
        dialog.resizable(False, False)
        dialog.attributes('-topmost', True)

        frame = ctk.CTkFrame(dialog, fg_color="transparent")
        frame.pack(padx=PADDING_WINDOW, pady=PADDING_WINDOW)

        ctk.CTkLabel(
            frame, text="Snooze for",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
        ).pack(anchor="w", pady=(0, 6))

        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x")

        entry = ctk.CTkEntry(
            row, width=80, height=36, corner_radius=CORNER_RADIUS_INPUT,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['input'])
        )
        entry.pack(side="left")
        entry.focus_set()

        unit = ctk.StringVar(value=CUSTOM_SNOOZE_DEFAULT_UNIT)
        unit_btn = ctk.CTkSegmentedButton(
            row, values=CUSTOM_SNOOZE_UNITS, variable=unit,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
        )
        unit_btn.set(CUSTOM_SNOOZE_DEFAULT_UNIT)
        unit_btn.pack(side="left", padx=(8, 0))

        hint = ctk.CTkLabel(
            frame, text="", text_color=COLORS['accent_orange'],
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['helper'])
        )
        hint.pack(anchor="w", pady=(6, 0))

        def do_set(*_):
            secs = custom_snooze_seconds(entry.get(), unit.get(), MAX_SNOOZE_SECONDS)
            if secs is None:
                hint.configure(text="Enter a positive number")
                return
            dialog.destroy()
            self.snooze(secs)

        ctk.CTkButton(
            frame, text="Set", command=do_set, height=40,
            corner_radius=CORNER_RADIUS_BUTTON,
            fg_color=COLORS['accent_blue'], hover_color=COLORS['accent_hover'],
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['input'], weight="bold")
        ).pack(fill="x", pady=(10, 0))

        entry.bind("<Return>", do_set)
        dialog.bind("<Escape>", lambda e: dialog.destroy())
        dialog.update_idletasks()
        px = self.window.winfo_rootx() + (self.window.winfo_width() - dialog.winfo_reqwidth()) // 2
        py = self.window.winfo_rooty() + (self.window.winfo_height() - dialog.winfo_reqheight()) // 2
        dialog.geometry(f"+{px}+{py}")
```

- [ ] **Step 6: Verify parse + compile.**

Run: `.venv/bin/python -c "import ast; ast.parse(open('launch.py').read())"`
Run: `.venv/bin/python -m py_compile launch.py`
Expected: no output for both.

- [ ] **Step 7: Commit.**

```bash
git add launch.py
git commit -m "feat: seconds snooze menu with presets + Custom… dialog on the popup"
```

---

### Task 4: App wiring — seconds `on_snooze` + popup creation

**Files:**
- Modify: `launch.py` — `on_snooze` closure and the `CountdownPopup(...)` call in
  `_process_break_queue`.

**Interfaces:**
- Consumes: `self.snooze_seconds` (Task 2), `snooze_delay_ms` (Task 1),
  `CountdownPopup(..., snooze_seconds=...)` (Task 3).

- [ ] **Step 1: Update `on_snooze` to seconds.**

Replace the `on_snooze` closure body:

```python
        def on_snooze(snooze_seconds):
            self._record_event(BREAK_SNOOZED, name=break_data['name'], seconds=snooze_seconds)
            self.snooze_seconds.set(snooze_seconds)   # remember as the new default
            self._save_preferences()
            self.active_popup = None
            self.break_start_time = None
            if self.running and not self.paused:
                self.status.configure(text="Working", text_color=COLORS['accent_green'])
                self.root.after(snooze_delay_ms(snooze_seconds),
                                lambda: self._requeue_break(break_data))
```

- [ ] **Step 2: Pass seconds into the popup.**

In the `CountdownPopup(...)` call, replace
`snooze_minutes=self.snooze_minutes.get(),` with:

```python
            snooze_seconds=self.snooze_seconds.get(),
```

- [ ] **Step 3: Verify no stale `snooze_minutes` references remain.**

Run: `grep -n "snooze_minutes\|SNOOZE_OPTIONS_MINUTES\|DEFAULT_SNOOZE_MINUTES" launch.py`
Expected: no matches.

- [ ] **Step 4: Verify parse + compile + full suite.**

Run: `.venv/bin/python -c "import ast; ast.parse(open('launch.py').read())"`
Run: `.venv/bin/python -m py_compile launch.py`
Run: `.venv/bin/python -m pytest -q`
Expected: no output for the first two; all tests PASS.

- [ ] **Step 5: Commit.**

```bash
git add launch.py
git commit -m "feat: persist + schedule snooze in seconds; log BREAK_SNOOZED seconds"
```

---

### Task 5: Manual verification (also verifies #37's snooze line)

**Files:** none.

- [ ] **Step 1: Run the app.** `.venv/bin/python launch.py`
- [ ] **Step 2:** Break (auto-dismiss off) → button "Snooze 5m"; ▾ shows
  30 sec / 1 min / 2 min / 5 min ● / 10 min / 15 min / 30 min / ── / Custom….
- [ ] **Step 3:** Pick **1 min** → snoozes ~1 min (log `BREAK_SNOOZED ... seconds=60`);
  reappears → button "Snooze 1m", ▾ marks 1 min ●, **and** the #37 line shows
  "Snoozed once already (originally due 1 min ago)".
- [ ] **Step 4:** Snooze again via **Custom…** → enter `45`, unit `sec`, Set →
  snoozes ~45 s (`seconds=45`); reappears → button "Snooze 45s"; #37 line now
  "Snoozed 2× already (...)".
- [ ] **Step 5:** Custom with empty / `0` / `abc` → inline "Enter a positive
  number", dialog stays open, no crash. Esc closes the dialog.
- [ ] **Step 6:** Take the break (Done) → trigger fresh → no #37 line (reset).
- [ ] **Step 7:** Quit + relaunch → last snooze default persists; a config that
  only had the old `snooze_minutes` still loads.

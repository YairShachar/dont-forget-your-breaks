# Configurable snooze Implementation Plan (#29)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The popup's Snooze becomes a split button — main click snoozes for the current default; a ▾ opens a 5/10/15/30-min menu, and the pick becomes the persisted new default.

**Architecture:** A pure `snooze_delay_ms` helper handles the minutes→ms conversion; a `snooze_minutes` IntVar pref holds the default; `CountdownPopup` gains a split Snooze control + duration menu; `BreakApp.on_snooze` (already minutes-parameterized) persists the chosen value.

**Tech Stack:** Python 3, Tkinter/CustomTkinter, pytest.

**Spec:** `~/daily/specs/2026-07-13-configurable-snooze-design.md`

## Global Constraints

- Options `5, 10, 15, 30` min; default `5`. Picked value persists as the new
  default (`snooze_minutes` pref, read with `.get("snooze_minutes", DEFAULT_SNOOZE_MINUTES)`).
- **No hardcoded values:** durations/default are named constants; the split-button
  dims reuse `CORNER_RADIUS_BUTTON`, `COLORS['border']`, `COLORS['bg_hover']`,
  `FONT_SIZES['input']`.
- No change to `_requeue_break`, context deferral (#42), the `BREAK_SNOOZED`
  event, or the auto-dismiss (no-snooze) path.
- Snooze control exists only when `not auto_dismiss` (unchanged).

---

### Task 1: Pure helper `snooze_delay_ms`

**Files:**
- Create: `dfyb/snooze.py`
- Test: `tests/test_snooze.py`

**Interfaces:**
- Produces: `snooze_delay_ms(minutes) -> int`, used by Task 4.

- [ ] **Step 1: Write the failing tests.**

Create `tests/test_snooze.py`:

```python
from dfyb.snooze import snooze_delay_ms


def test_five_minutes():
    assert snooze_delay_ms(5) == 300000


def test_ten_minutes():
    assert snooze_delay_ms(10) == 600000


def test_one_minute():
    assert snooze_delay_ms(1) == 60000


def test_fractional_is_int():
    result = snooze_delay_ms(0.5)
    assert result == 30000
    assert isinstance(result, int)
```

- [ ] **Step 2: Run tests to verify they fail.**

Run: `.venv/bin/python -m pytest tests/test_snooze.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'dfyb.snooze'`.

- [ ] **Step 3: Implement.**

Create `dfyb/snooze.py`:

```python
"""Snooze timing helpers. Pure (no Tk, no I/O) — unit-tested."""

MS_PER_MINUTE = 60 * 1000


def snooze_delay_ms(minutes):
    """Snooze duration in whole milliseconds for Tk's `after` (which needs an int).

    int() also guards the historic float-crash (0.5 -> 30000, not 30000.0).
    """
    return int(minutes * MS_PER_MINUTE)
```

- [ ] **Step 4: Run tests to verify they pass.**

Run: `.venv/bin/python -m pytest tests/test_snooze.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit.**

```bash
git add dfyb/snooze.py tests/test_snooze.py
git commit -m "feat: add snooze_delay_ms helper (#29)"
```

---

### Task 2: Constants, pref, save, import

**Files:**
- Modify: `launch.py` — CONFIGURATION block (near `SNOOZE_RECHECK_MS`, ~`launch.py:157`);
  imports (~`launch.py:37`); `BreakApp.__init__` (pref vars); `_save_preferences`.

**Interfaces:**
- Produces: `SNOOZE_OPTIONS_MINUTES`, `DEFAULT_SNOOZE_MINUTES`,
  `self.snooze_minutes` (IntVar), imported `snooze_delay_ms` — used by Tasks 3–4.

- [ ] **Step 1: Add constants.**

After the `BREAK_OVER_TEXT`/`OVER_BREAK_SUFFIX` lines in CONFIGURATION:

```python
SNOOZE_OPTIONS_MINUTES = [5, 10, 15, 30]  # snooze durations offered on the popup ▾ menu
DEFAULT_SNOOZE_MINUTES = 5                 # default snooze length (persisted as snooze_minutes)
```

- [ ] **Step 2: Import the helper.**

After `from dfyb.insights.over_break import format_over_time`:

```python
from dfyb.snooze import snooze_delay_ms
```

- [ ] **Step 3: Add the pref var.**

In `BreakApp.__init__`, next to the other pref vars (e.g. after
`self.defer_while_active = ...` / `self.activity_pause_seconds = ...`):

```python
        self.snooze_minutes = ctk.IntVar(
            value=self.saved_prefs.get("snooze_minutes", DEFAULT_SNOOZE_MINUTES))
```

- [ ] **Step 4: Persist it.**

In `_save_preferences`, add to the preferences dict (near `"defer_while_active"`):

```python
            "snooze_minutes": self.snooze_minutes.get(),
```

- [ ] **Step 5: Verify parse.**

Run: `.venv/bin/python -c "import ast; ast.parse(open('launch.py').read())"`
Expected: no output.

- [ ] **Step 6: Commit.**

```bash
git add launch.py
git commit -m "chore: add snooze_minutes pref + options constants (#29)"
```

---

### Task 3: Popup split Snooze control + duration menu

**Files:**
- Modify: `launch.py` — `CountdownPopup.__init__` (drop `SNOOZE_MINUTES` usage,
  add param), `_build_ui` snooze block (`launch.py:348–362`), `snooze`
  (`launch.py:459–466`); add `_open_snooze_menu`.

**Interfaces:**
- Consumes: `SNOOZE_OPTIONS_MINUTES`, `DEFAULT_SNOOZE_MINUTES` (Task 2).
- Produces: `CountdownPopup(..., snooze_minutes=...)` and
  `snooze(minutes=None)` — used by Task 4.

- [ ] **Step 1: Add the `snooze_minutes` param and remove the class constant.**

Delete the class-level `SNOOZE_MINUTES = 5` line (`launch.py:245`).

In `CountdownPopup.__init__`, add `snooze_minutes=DEFAULT_SNOOZE_MINUTES` to the
signature and store it. Change the signature line:

```python
    def __init__(self, parent, title, message, duration,
                 auto_dismiss=True, on_close=None, on_snooze=None,
                 end_sound=None, loop_end_sound=False, placement="active",
                 target_screen=None, held_reason=None):
```

to:

```python
    def __init__(self, parent, title, message, duration,
                 auto_dismiss=True, on_close=None, on_snooze=None,
                 end_sound=None, loop_end_sound=False, placement="active",
                 target_screen=None, held_reason=None,
                 snooze_minutes=DEFAULT_SNOOZE_MINUTES):
```

and, near the other `self.` assignments at the top of `__init__` (e.g. after
`self.held_reason = held_reason`), add:

```python
        self.snooze_minutes = snooze_minutes
```

- [ ] **Step 2: Replace the snooze button with a split group.**

Replace (`launch.py:348–362`):

```python
        # Snooze button (only if not auto-dismiss) - secondary style
        if not auto_dismiss:
            self.snooze_btn = ctk.CTkButton(
                btn_frame,
                text=f"Snooze {self.SNOOZE_MINUTES}m",
                command=self.snooze,
                width=130,
                height=40,
                corner_radius=CORNER_RADIUS_BUTTON,
                fg_color="transparent",
                border_width=1,
                border_color=COLORS['border'],
                hover_color=COLORS['bg_hover'],
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['input'])
            )
            self.snooze_btn.pack(side="left", padx=8)
```

with:

```python
        # Snooze split control (only if not auto-dismiss): main = snooze for the
        # current default, ▾ = pick another duration (which becomes the default).
        if not auto_dismiss:
            snooze_group = ctk.CTkFrame(btn_frame, fg_color="transparent")
            snooze_group.pack(side="left", padx=8)

            self.snooze_btn = ctk.CTkButton(
                snooze_group,
                text=f"Snooze {self.snooze_minutes}m",
                command=self.snooze,
                width=104,
                height=40,
                corner_radius=CORNER_RADIUS_BUTTON,
                fg_color="transparent",
                border_width=1,
                border_color=COLORS['border'],
                hover_color=COLORS['bg_hover'],
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['input'])
            )
            self.snooze_btn.pack(side="left")

            self.snooze_menu_btn = ctk.CTkButton(
                snooze_group,
                text="▾",
                command=self._open_snooze_menu,
                width=28,
                height=40,
                corner_radius=CORNER_RADIUS_BUTTON,
                fg_color="transparent",
                border_width=1,
                border_color=COLORS['border'],
                hover_color=COLORS['bg_hover'],
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['input'])
            )
            self.snooze_menu_btn.pack(side="left", padx=(4, 0))
```

- [ ] **Step 3: Make `snooze` accept a duration; add `_open_snooze_menu`.**

Replace the current `snooze` method (`launch.py:459–466`):

```python
    def snooze(self):
        """Snooze the break for a few minutes."""
        if self.closed or self.snoozed:
            return
        self.snoozed = True
        self.sound_stop_event.set()
        if self.on_snooze:
            self.on_snooze(self.SNOOZE_MINUTES)
        self.closed = True
        self._dismiss()
```

with:

```python
    def snooze(self, minutes=None):
        """Snooze the break; `minutes` defaults to the current default."""
        if self.closed or self.snoozed:
            return
        chosen = self.snooze_minutes if minutes is None else minutes
        self.snoozed = True
        self.sound_stop_event.set()
        if self.on_snooze:
            self.on_snooze(chosen)
        self.closed = True
        self._dismiss()

    def _open_snooze_menu(self):
        """Pop a small menu of snooze durations under the ▾ button."""
        menu = tk.Menu(self.window, tearoff=0)
        selected = tk.IntVar(value=self.snooze_minutes)
        for minutes in SNOOZE_OPTIONS_MINUTES:
            menu.add_radiobutton(
                label=f"{minutes} min", value=minutes, variable=selected,
                command=lambda m=minutes: self.snooze(m))
        menu.tk_popup(
            self.snooze_menu_btn.winfo_rootx(),
            self.snooze_menu_btn.winfo_rooty() + self.snooze_menu_btn.winfo_height())
```

- [ ] **Step 4: Verify parse + compile.**

Run: `.venv/bin/python -c "import ast; ast.parse(open('launch.py').read())"`
Run: `.venv/bin/python -m py_compile launch.py`
Expected: no output for both.

- [ ] **Step 5: Commit.**

```bash
git add launch.py
git commit -m "feat: split Snooze button with a duration menu on the popup (#29)"
```

---

### Task 4: App-side — pass default, persist the pick, use the helper

**Files:**
- Modify: `launch.py` — `BreakApp` `on_snooze` closure (`launch.py:1753–1760`)
  and the `CountdownPopup(...)` creation (`launch.py:1766–1779`).

**Interfaces:**
- Consumes: `self.snooze_minutes` (Task 2), `snooze_delay_ms` (Task 1/2),
  `CountdownPopup(..., snooze_minutes=...)` (Task 3).

- [ ] **Step 1: Persist the pick + use `snooze_delay_ms` in `on_snooze`.**

Replace the `on_snooze` closure body:

```python
        def on_snooze(snooze_minutes):
            self._record_event(BREAK_SNOOZED, name=break_data['name'], minutes=snooze_minutes)
            self.active_popup = None
            self.break_start_time = None
            if self.running and not self.paused:
                self.status.configure(text="Working", text_color=COLORS['accent_green'])
                snooze_ms = int(snooze_minutes * 60 * 1000)
                self.root.after(snooze_ms, lambda: self._requeue_break(break_data))
```

with:

```python
        def on_snooze(snooze_minutes):
            self._record_event(BREAK_SNOOZED, name=break_data['name'], minutes=snooze_minutes)
            self.snooze_minutes.set(snooze_minutes)   # remember as the new default
            self._save_preferences()
            self.active_popup = None
            self.break_start_time = None
            if self.running and not self.paused:
                self.status.configure(text="Working", text_color=COLORS['accent_green'])
                self.root.after(snooze_delay_ms(snooze_minutes),
                                lambda: self._requeue_break(break_data))
```

- [ ] **Step 2: Pass the current default into the popup.**

In the `self.active_popup = CountdownPopup(...)` call, add the argument
alongside `held_reason=break_data.get('held_reason')`:

```python
            held_reason=break_data.get('held_reason'),
            snooze_minutes=self.snooze_minutes.get(),
```

- [ ] **Step 3: Verify parse + compile + full suite.**

Run: `.venv/bin/python -c "import ast; ast.parse(open('launch.py').read())"`
Run: `.venv/bin/python -m py_compile launch.py`
Run: `.venv/bin/python -m pytest -q`
Expected: no output for the first two; all tests PASS.

- [ ] **Step 4: Commit.**

```bash
git add launch.py
git commit -m "feat: remember snooze choice as the new default (#29)"
```

---

### Task 5: Manual verification

**Files:** none.

- [ ] **Step 1: Run the app.** `.venv/bin/python launch.py`
- [ ] **Step 2:** Trigger a break with **auto-dismiss off** → Snooze control
  shows "Snooze 5m" + ▾.
- [ ] **Step 3:** Click the **main** button → popup dismisses; console log shows
  `BREAK_SNOOZED ... minutes=5`.
- [ ] **Step 4:** Trigger again; click **▾** → menu shows 5/10/15/30 with
  **5 min ●**; pick **15 min** → dismisses; log shows `minutes=15`.
- [ ] **Step 5:** Trigger again → main button reads **"Snooze 15m"**; the ▾ menu
  marks **15 min ●**.
- [ ] **Step 6:** Quit + relaunch → default is still 15 (persisted to prefs).
- [ ] **Step 7:** A break with **auto-dismiss on** → no Snooze control (unchanged).

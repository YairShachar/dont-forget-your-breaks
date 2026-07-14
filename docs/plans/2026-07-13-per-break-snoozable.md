# Per-break "Snoozable" setting — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A per-break "Snoozable" setting decides whether the popup shows the Snooze control, independent of Auto-dismiss.

**Architecture:** Add a `snoozable` BooleanVar to `BreakConfig`, mirror `auto_dismiss` through defaults/load/save/trace and a config-panel checkbox, and change the popup's snooze gate from `not auto_dismiss` to `self.snoozable`.

**Tech Stack:** Python 3, Tkinter/CustomTkinter, pytest.

**Spec:** `~/daily/specs/2026-07-13-per-break-snoozable-design.md`

## Global Constraints

- `snoozable` gates the Snooze control; `auto_dismiss` keeps controlling
  auto-close at duration end (unchanged).
- Defaults: Micro Break `False`, Normal Break `True` (preserves current behavior).
- Backward-compatible: load falls back to the `default_breaks` value when a saved
  config lacks `snoozable`.
- Config plumbing only — no new pure logic; the existing 166-test suite must pass.

---

### Task 1: `BreakConfig` + defaults + persistence

**Files:**
- Modify: `launch.py` — `BreakConfig.__init__` (`:213–224`), `default_breaks`
  (`:1050–1055`), load (`:1118–1128`), save (`:1344–1354`), auto-save trace (`:1496`).

**Interfaces:**
- Produces: `BreakConfig.snoozable` (BooleanVar) — used by Tasks 2–3.

- [ ] **Step 1: Add the constructor param + BooleanVar.**

Change the signature:

```python
    def __init__(self, name, interval_val, interval_unit,
                 duration_val, duration_unit, start_sound, end_sound,
                 loop_end_sound=False, auto_dismiss=True):
```

to add `snoozable=True`:

```python
    def __init__(self, name, interval_val, interval_unit,
                 duration_val, duration_unit, start_sound, end_sound,
                 loop_end_sound=False, auto_dismiss=True, snoozable=True):
```

and after `self.auto_dismiss = ctk.BooleanVar(value=auto_dismiss)` add:

```python
        self.snoozable = ctk.BooleanVar(value=snoozable)
```

- [ ] **Step 2: Add `snoozable` to the default breaks.**

Change the `default_breaks` list:

```python
        self.default_breaks = [
            {"name": "Micro Break", "interval_val": 25, "interval_unit": "min",
             "duration_val": 5, "duration_unit": "sec", "start_sound": "Ping",
             "end_sound": "Glass", "loop_end_sound": False, "auto_dismiss": True},
            {"name": "Normal Break", "interval_val": 50, "interval_unit": "min",
             "duration_val": 10, "duration_unit": "min", "start_sound": "Glass",
             "end_sound": "Submarine", "loop_end_sound": True, "auto_dismiss": False}
        ]
```

to:

```python
        self.default_breaks = [
            {"name": "Micro Break", "interval_val": 25, "interval_unit": "min",
             "duration_val": 5, "duration_unit": "sec", "start_sound": "Ping",
             "end_sound": "Glass", "loop_end_sound": False, "auto_dismiss": True,
             "snoozable": False},
            {"name": "Normal Break", "interval_val": 50, "interval_unit": "min",
             "duration_val": 10, "duration_unit": "min", "start_sound": "Glass",
             "end_sound": "Submarine", "loop_end_sound": True, "auto_dismiss": False,
             "snoozable": True}
        ]
```

- [ ] **Step 3: Load `snoozable`.**

Change (`:1127`):

```python
                auto_dismiss=break_prefs.get("auto_dismiss", default["auto_dismiss"])
            ))
```

to:

```python
                auto_dismiss=break_prefs.get("auto_dismiss", default["auto_dismiss"]),
                snoozable=break_prefs.get("snoozable", default["snoozable"])
            ))
```

- [ ] **Step 4: Save `snoozable`.**

Change (`:1353`):

```python
                "auto_dismiss": config.auto_dismiss.get()
            })
```

to:

```python
                "auto_dismiss": config.auto_dismiss.get(),
                "snoozable": config.snoozable.get()
            })
```

- [ ] **Step 5: Auto-save trace.**

After `config.auto_dismiss.trace_add('write', self._save_preferences)` (`:1496`):

```python
            config.snoozable.trace_add('write', self._save_preferences)
```

- [ ] **Step 6: Verify parse + compile + suite.**

Run: `.venv/bin/python -c "import ast; ast.parse(open('launch.py').read())"`
Run: `.venv/bin/python -m py_compile launch.py`
Run: `.venv/bin/python -m pytest -q`
Expected: no output for the first two; 166 pass.

- [ ] **Step 7: Commit.**

```bash
git add launch.py
git commit -m "feat: add per-break snoozable config + persistence"
```

---

### Task 2: "Snoozable" checkbox in the config panel

**Files:**
- Modify: `launch.py` — `BreakConfigPanel._build_ui`, `row3` (`:869–879`).

**Interfaces:**
- Consumes: `self.config.snoozable` (Task 1).

- [ ] **Step 1: Add the checkbox after "Auto-dismiss".**

After the "Auto-dismiss" checkbox block:

```python
        ctk.CTkCheckBox(
            row3, text="Auto-dismiss",
            variable=self.config.auto_dismiss,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
        ).pack(side="left", padx=(16, 0))
```

insert:

```python
        ctk.CTkCheckBox(
            row3, text="Snoozable",
            variable=self.config.snoozable,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
        ).pack(side="left", padx=(16, 0))
```

- [ ] **Step 2: Verify parse + compile.**

Run: `.venv/bin/python -c "import ast; ast.parse(open('launch.py').read())"`
Run: `.venv/bin/python -m py_compile launch.py`
Expected: no output.

- [ ] **Step 3: Commit.**

```bash
git add launch.py
git commit -m "feat: add Snoozable checkbox to the break config panel"
```

---

### Task 3: Popup gate + break_data wiring

**Files:**
- Modify: `launch.py` — `CountdownPopup.__init__` (`:255, 269`), snooze gate
  (`:381`), `trigger_break` break_data (`:1826`), `_process_break_queue` popup
  creation (`:1903`).

**Interfaces:**
- Consumes: `config.snoozable` (Task 1), `break_data['snoozable']`.

- [ ] **Step 1: Add the popup param + stored attr.**

In `CountdownPopup.__init__`, change the signature line:

```python
                 auto_dismiss=True, on_close=None, on_snooze=None,
```

to:

```python
                 auto_dismiss=True, snoozable=True, on_close=None, on_snooze=None,
```

and after `self.auto_dismiss = auto_dismiss` add:

```python
        self.snoozable = snoozable
```

- [ ] **Step 2: Change the snooze gate.**

Change (`:381`):

```python
        # Snooze split control (only if not auto-dismiss): main = snooze for the
        # current default, ▾ = pick another duration (which becomes the default).
        if not auto_dismiss:
```

to:

```python
        # Snooze split control (only if the break is snoozable): main = snooze for
        # the current default, ▾ = pick another duration (which becomes the default).
        if self.snoozable:
```

- [ ] **Step 3: Carry `snoozable` in break_data.**

In `trigger_break`, change:

```python
            'auto_dismiss': config.auto_dismiss.get(),
```

to:

```python
            'auto_dismiss': config.auto_dismiss.get(),
            'snoozable': config.snoozable.get(),
```

- [ ] **Step 4: Pass it into the popup.**

In `_process_break_queue`, change:

```python
            auto_dismiss=break_data['auto_dismiss'],
```

to:

```python
            auto_dismiss=break_data['auto_dismiss'],
            snoozable=break_data['snoozable'],
```

- [ ] **Step 5: Verify parse + compile + suite.**

Run: `.venv/bin/python -c "import ast; ast.parse(open('launch.py').read())"`
Run: `.venv/bin/python -m py_compile launch.py`
Run: `.venv/bin/python -m pytest -q`
Expected: no output for the first two; 166 pass.

- [ ] **Step 6: Commit.**

```bash
git add launch.py
git commit -m "feat: gate popup snooze control on the snoozable setting"
```

---

### Task 4: Manual verification

**Files:** none.

- [ ] **Step 1: Run the app.** `.venv/bin/python launch.py`
- [ ] **Step 2:** Settings → Micro Break shows **"Snoozable" unchecked**; Normal
  Break shows it **checked**.
- [ ] **Step 3:** "Break now" on **Normal Break** → Snooze + ▾ present (as before).
- [ ] **Step 4:** Uncheck **Normal Break → Snoozable**; "Break now" on it → only
  **Done**, no Snooze.
- [ ] **Step 5:** Check **Micro Break → Snoozable** (and raise its duration or turn
  Auto-dismiss off so the popup lingers); "Break now" → Snooze control appears.
- [ ] **Step 6:** Toggle a Snoozable checkbox, quit + relaunch → the setting
  persists.
- [ ] **Step 7:** Confirm a pre-existing config file still loads (Micro→off,
  Normal→on) with no error.

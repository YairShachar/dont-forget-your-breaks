# Double-click a break to configure it — Implementation Plan (#43)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Double-clicking a break's card (name or countdown timer) on the main window opens Settings and puts keyboard focus in that break's interval field.

**Architecture:** Pure Tk/CTk wiring inside `launch.py`. `BreakConfigPanel` gains a way to focus its own interval field; `BreakApp._open_settings` accepts an optional break to focus and delegates to a small identity-match helper; the main-window cards bind `<Double-Button-1>` to a handler that opens Settings focused on the clicked break.

**Tech Stack:** Python 3, Tkinter/CustomTkinter. No new dependencies.

**Spec:** `~/daily/specs/2026-07-13-double-click-to-configure-design.md`

## Global Constraints

- Single file: all changes in `launch.py`. No package changes.
- No hardcoded/magic values beyond Tk event names (`<Double-Button-1>` is an
  event name, not a tunable). No new constant needed.
- Do not touch the "Break now" button, single-click behavior, or the popup
  Space/focus logic (#21).
- Match a break to its settings panel by **object identity** (`is`), not by
  name string.
- UI wiring is human-verified (no pure logic to unit-test). Run the app and
  follow the manual steps at the end before finishing.

---

### Task 1: Expose the interval entry + add `focus_config()` on `BreakConfigPanel`

**Files:**
- Modify: `launch.py` — `BreakConfigPanel._build_ui` (interval entry at `launch.py:647`); add `focus_config` method (near `expand`/`collapse`, around `launch.py:778–846`).

**Interfaces:**
- Produces: `BreakConfigPanel.interval_entry` (a `CTkEntry`) and
  `BreakConfigPanel.focus_config()` — used by Task 2's `_focus_settings_panel`.

- [ ] **Step 1: Store the interval entry on the instance.**

In `_build_ui`, the interval entry is currently a local variable. Change:

```python
        interval_entry = ctk.CTkEntry(
            row1, width=70, height=36,
            textvariable=self.config.interval_value,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['input']),
            corner_radius=CORNER_RADIUS_INPUT
        )
        interval_entry.pack(side="left", padx=(8, 4))
```

to assign it to `self.interval_entry` and pack via the attribute:

```python
        self.interval_entry = ctk.CTkEntry(
            row1, width=70, height=36,
            textvariable=self.config.interval_value,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['input']),
            corner_radius=CORNER_RADIUS_INPUT
        )
        self.interval_entry.pack(side="left", padx=(8, 4))
```

- [ ] **Step 2: Add the `focus_config` method.**

Place it right after the `expand` method (or anywhere among the panel's
public methods, e.g. just before `collapse`):

```python
    def focus_config(self):
        """Expand (if collapsed) and put keyboard focus in the interval field."""
        if not self._expanded:
            self.expand()
        self.interval_entry.focus_set()
```

- [ ] **Step 3: Sanity-check import/run (no crash).**

Run: `.venv/bin/python -c "import ast; ast.parse(open('launch.py').read())"`
Expected: no output (file parses).

- [ ] **Step 4: Commit.**

```bash
git add launch.py
git commit -m "feat: expose interval entry and add BreakConfigPanel.focus_config"
```

---

### Task 2: Add `focus_config` param + `_focus_settings_panel` to `_open_settings`

**Files:**
- Modify: `launch.py` — `BreakApp._open_settings` (`launch.py:1400`), both the
  already-open early-return path (`launch.py:1402–1406`) and the end of the
  build path (after `launch.py:1523`). Add new method `_focus_settings_panel`.

**Interfaces:**
- Consumes: `BreakConfigPanel.focus_config()` and `panel.config` from Task 1.
- Produces: `BreakApp._open_settings(focus_config=None)` and
  `BreakApp._focus_settings_panel(config)` — used by Task 3.

- [ ] **Step 1: Add the `focus_config` parameter and honor it in the early-return path.**

Change the signature and the already-open branch. Current:

```python
    def _open_settings(self):
        """Open the settings window, or bring it to front if already open."""
        if hasattr(self, '_settings_window') and self._settings_window and self._settings_window.winfo_exists():
            self._settings_window.deiconify()
            self._settings_window.lift()
            self._settings_window.focus_force()
            return
```

to:

```python
    def _open_settings(self, focus_config=None):
        """Open the settings window, or bring it to front if already open.

        If focus_config is a BreakConfig, focus that break's settings panel
        (expanding it and landing keyboard focus in its interval field).
        """
        if hasattr(self, '_settings_window') and self._settings_window and self._settings_window.winfo_exists():
            self._settings_window.deiconify()
            self._settings_window.lift()
            self._settings_window.focus_force()
            self._focus_settings_panel(focus_config)
            return
```

- [ ] **Step 2: Honor it at the end of the build path.**

The build path currently ends (`launch.py:1521–1523`) with:

```python
        self._settings_window.deiconify()
        self._settings_window.lift()
        self._settings_window.focus_force()
```

Add the focus call immediately after `focus_force()`:

```python
        self._settings_window.deiconify()
        self._settings_window.lift()
        self._settings_window.focus_force()
        self._focus_settings_panel(focus_config)
```

- [ ] **Step 3: Add the `_focus_settings_panel` helper.**

Place it directly after `_open_settings` (before the `# ------------------ TIMER`
section, `launch.py:1525`):

```python
    def _focus_settings_panel(self, config):
        """Focus the settings panel that edits the given break (by identity)."""
        if config is None:
            return
        for panel in self._settings_panels:
            if panel.config is config:
                panel.focus_config()
                break
```

- [ ] **Step 4: Sanity-check parse.**

Run: `.venv/bin/python -c "import ast; ast.parse(open('launch.py').read())"`
Expected: no output.

- [ ] **Step 5: Commit.**

```bash
git add launch.py
git commit -m "feat: let _open_settings focus a specific break's config panel"
```

---

### Task 3: Bind `<Double-Button-1>` on each main-window card

**Files:**
- Modify: `launch.py` — `BreakApp._build_ui` card loop (`launch.py:1052–1082`);
  add `_edit_break_config` handler on `BreakApp`.

**Interfaces:**
- Consumes: `BreakApp._open_settings(focus_config=...)` from Task 2.

- [ ] **Step 1: Add the `_edit_break_config` handler.**

Place it next to `_open_settings` (e.g. just above `_open_settings` at
`launch.py:1400`):

```python
    def _edit_break_config(self, config):
        """Open settings focused on the given break (double-click a card)."""
        self._open_settings(focus_config=config)
```

- [ ] **Step 2: Store the name label and bind double-click on card + name + timer.**

In the card loop, the name label is currently created inline. Change:

```python
            ctk.CTkLabel(
                card, text=config.name.get(),
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
            ).pack(side="left", padx=(PADDING_PANEL_X, 0), pady=8)
```

to capture it:

```python
            name_label = ctk.CTkLabel(
                card, text=config.name.get(),
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
            )
            name_label.pack(side="left", padx=(PADDING_PANEL_X, 0), pady=8)
```

Then, immediately after `self._timer_labels.append(timer_label)` (end of the
loop body, `launch.py:1082`), bind the double-click on the three widgets:

```python
            # Double-click the card (name or countdown) jumps into this break's
            # configuration (#43). The "Break now" button keeps its own click.
            for widget in (card, name_label, timer_label):
                widget.bind("<Double-Button-1>",
                            lambda e, c=config: self._edit_break_config(c))
```

- [ ] **Step 3: Sanity-check parse.**

Run: `.venv/bin/python -c "import ast; ast.parse(open('launch.py').read())"`
Expected: no output.

- [ ] **Step 4: Commit.**

```bash
git add launch.py
git commit -m "feat: double-click a break card to jump into its configuration (#43)"
```

---

### Task 4: Manual verification

**Files:** none (verification only).

- [ ] **Step 1: Run the app.**

Run: `.venv/bin/python launch.py`

- [ ] **Step 2: Double-click the Micro Break card.**
Expected: Settings window opens; Micro Break panel expanded; text cursor
blinking in its "Every" (interval) field.

- [ ] **Step 3: Double-click the Normal Break's countdown number.**
Expected: Settings (already open) comes to front; keyboard focus moves to
Normal Break's interval field.

- [ ] **Step 4: Click "Break now" on a card.**
Expected: fires a manual break popup; does NOT open Settings.

- [ ] **Step 5: Collapse a break's panel, close Settings, double-click that break.**
Expected: panel re-expands and its interval field is focused.

- [ ] **Step 6: Confirm no regressions** in opening Settings via the normal
"Settings" button (opens with no particular field focused — `focus_config` is
`None`, so `_focus_settings_panel` returns early).

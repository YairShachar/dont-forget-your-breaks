# Gentle "holding" cue Implementation Plan (#44)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** While a due break is held by a context defer, show a calm dimmed line ("↳ waiting for a pause…") on that break's main-window card explaining why, which disappears when the break fires.

**Architecture:** A pure `holding_cue(remaining, held_reason)` helper (in `dfyb/insights/transparency.py`) turns already-existing state (`config.remaining` clamped to 0 + `self._held` reason) into cue text or `None`. The main-window card gains a hidden sub-label that `update_ui` shows/hides. No scheduler or event-schema change.

**Tech Stack:** Python 3, Tkinter/CustomTkinter, pytest.

**Spec:** `~/daily/specs/2026-07-13-holding-cue-design.md`

## Global Constraints

- Cue is **always on** (no preference/toggle) and **static** (no animation).
- Cue appears **only on main-window cards**, never in settings panels or the popup.
- **No new constant** — reuse `FONT_SIZES['helper']`, `COLORS['text_secondary']`,
  `PADDING_PANEL_X`; the "↳ " prefix is a fixed presentation glyph.
- Reason keys are exactly `"meeting"`, `"fullscreen"`, `"away"`, `"active"`
  (must match the scheduler's emitted reasons and the existing `HELD_MESSAGES`).
- **Preserve #43**: double-clicking a break card still opens its config.
- No scheduler / `self._held` / event-schema changes.
- Network calls are never hit in tests (N/A here — no network in scope).

---

### Task 1: Pure helpers `holding_message` + `holding_cue`

**Files:**
- Modify: `dfyb/insights/transparency.py` (add after the existing
  `held_message`).
- Test: `tests/test_transparency.py` (add to the existing file).

**Interfaces:**
- Produces:
  - `holding_message(reason: str | None) -> str | None`
  - `holding_cue(remaining: int, held_reason: str | None) -> str | None`
  used by Task 3 (`launch.py update_ui`).

- [ ] **Step 1: Write the failing tests.**

Append to `tests/test_transparency.py`:

```python
from dfyb.insights.transparency import holding_message, holding_cue


def test_holding_message_maps_each_reason():
    assert holding_message("meeting") == "waiting until your mic is free…"
    assert holding_message("fullscreen") == "waiting for full screen to end…"
    assert holding_message("away") == "waiting until you're back…"
    assert holding_message("active") == "waiting for a pause…"


def test_holding_message_unknown_or_none():
    assert holding_message("nonsense") is None
    assert holding_message(None) is None


def test_holding_cue_shows_when_due_and_held():
    assert holding_cue(0, "active") == "waiting for a pause…"
    assert holding_cue(0, "meeting") == "waiting until your mic is free…"


def test_holding_cue_none_when_not_due():
    assert holding_cue(5, "active") is None


def test_holding_cue_none_when_not_held():
    assert holding_cue(0, None) is None


def test_holding_cue_none_for_unknown_reason():
    assert holding_cue(0, "nonsense") is None
```

- [ ] **Step 2: Run tests to verify they fail.**

Run: `.venv/bin/python -m pytest tests/test_transparency.py -q`
Expected: FAIL with `ImportError: cannot import name 'holding_message'`.

- [ ] **Step 3: Implement the helpers.**

In `dfyb/insights/transparency.py`, add right after the `held_message`
function:

```python
HOLDING_MESSAGES = {
    "meeting":    "waiting until your mic is free…",
    "fullscreen": "waiting for full screen to end…",
    "away":       "waiting until you're back…",
    "active":     "waiting for a pause…",
}


def holding_message(reason):
    """Present-tense live cue for a currently-held break (or None)."""
    return HOLDING_MESSAGES.get(reason)


def holding_cue(remaining, held_reason):
    """Live cue text for a break card, or None when it isn't being held.

    A break is 'held' when it is due (remaining clamped to 0) and a defer
    reason is active.
    """
    if remaining == 0 and held_reason:
        return holding_message(held_reason)
    return None
```

- [ ] **Step 4: Run tests to verify they pass.**

Run: `.venv/bin/python -m pytest tests/test_transparency.py -q`
Expected: PASS (all transparency tests, old + new).

- [ ] **Step 5: Commit.**

```bash
git add dfyb/insights/transparency.py tests/test_transparency.py
git commit -m "feat: add present-tense holding_message/holding_cue helpers (#44)"
```

---

### Task 2: Card restructure — `top_row` + hidden cue label

**Files:**
- Modify: `launch.py` — `BreakApp._build_ui` card loop (`launch.py:1058–1095`);
  the module import line (`launch.py:36`).

**Interfaces:**
- Consumes: `holding_cue` from Task 1 (imported now, used in Task 3).
- Produces: `self._cue_labels` (list of `CTkLabel`, index-aligned with
  `self.breaks`) and per-card `top_row` — used by Task 3.

- [ ] **Step 1: Add `holding_cue` to the transparency import.**

Change `launch.py:36` from:

```python
from dfyb.insights.transparency import track_held, held_message
```

to:

```python
from dfyb.insights.transparency import track_held, held_message, holding_cue
```

- [ ] **Step 2: Restructure the card loop.**

Replace the current card loop body (`launch.py:1058–1095`):

```python
        # Compact timer display cards
        self._timer_labels = []
        for config in self.breaks:
            card = ctk.CTkFrame(main_frame, corner_radius=CORNER_RADIUS_PANEL, fg_color=COLORS['bg_panel'])
            card.pack(fill="x", pady=(0, 6))

            name_label = ctk.CTkLabel(
                card, text=config.name.get(),
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
            )
            name_label.pack(side="left", padx=(PADDING_PANEL_X, 0), pady=8)

            timer_label = ctk.CTkLabel(
                card, text="--:--",
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['timer'], weight="bold")
            )
            timer_label.pack(side="right", padx=(0, PADDING_PANEL_X), pady=8)

            # Break now button (quick manual trigger, left of the timer)
            ctk.CTkButton(
                card, text="Break now",
                command=lambda c=config: self.break_now(c),
                width=90, height=BUTTON_HEIGHT_SMALL,
                corner_radius=CORNER_RADIUS_INPUT,
                fg_color="transparent",
                border_width=1,
                border_color=COLORS['border'],
                hover_color=COLORS['bg_hover'],
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['helper'])
            ).pack(side="right", padx=(0, 8), pady=8)

            self._timer_labels.append(timer_label)

            # Double-click the card (name or countdown) jumps into this break's
            # configuration (#43). The "Break now" button keeps its own click.
            for widget in (card, name_label, timer_label):
                widget.bind("<Double-Button-1>",
                            lambda e, c=config: self._edit_break_config(c))
```

with (top row holds the same widgets; a hidden cue line sits beneath):

```python
        # Compact timer display cards
        self._timer_labels = []
        self._cue_labels = []
        for config in self.breaks:
            card = ctk.CTkFrame(main_frame, corner_radius=CORNER_RADIUS_PANEL, fg_color=COLORS['bg_panel'])
            card.pack(fill="x", pady=(0, 6))

            top_row = ctk.CTkFrame(card, fg_color="transparent")
            top_row.pack(fill="x")

            name_label = ctk.CTkLabel(
                top_row, text=config.name.get(),
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
            )
            name_label.pack(side="left", padx=(PADDING_PANEL_X, 0), pady=8)

            timer_label = ctk.CTkLabel(
                top_row, text="--:--",
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['timer'], weight="bold")
            )
            timer_label.pack(side="right", padx=(0, PADDING_PANEL_X), pady=8)

            # Break now button (quick manual trigger, left of the timer)
            ctk.CTkButton(
                top_row, text="Break now",
                command=lambda c=config: self.break_now(c),
                width=90, height=BUTTON_HEIGHT_SMALL,
                corner_radius=CORNER_RADIUS_INPUT,
                fg_color="transparent",
                border_width=1,
                border_color=COLORS['border'],
                hover_color=COLORS['bg_hover'],
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['helper'])
            ).pack(side="right", padx=(0, 8), pady=8)

            self._timer_labels.append(timer_label)

            # Gentle "holding" cue (#44): explains why a due break is waiting.
            # Hidden until held; shown/hidden by update_ui.
            cue_label = ctk.CTkLabel(
                card, text="", anchor="w",
                text_color=COLORS['text_secondary'],
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['helper'])
            )
            self._cue_labels.append(cue_label)

            # Double-click the card (name or countdown) jumps into this break's
            # configuration (#43). The "Break now" button keeps its own click.
            for widget in (card, top_row, name_label, timer_label):
                widget.bind("<Double-Button-1>",
                            lambda e, c=config: self._edit_break_config(c))
```

- [ ] **Step 3: Verify the file parses and the app builds without the cue.**

Run: `.venv/bin/python -c "import ast; ast.parse(open('launch.py').read())"`
Expected: no output.

Run: `.venv/bin/python -m py_compile launch.py`
Expected: no output.

- [ ] **Step 4: Commit.**

```bash
git add launch.py
git commit -m "refactor: card top-row + hidden holding-cue label; keep #43 bindings (#44)"
```

---

### Task 3: Show/hide the cue in `update_ui`

**Files:**
- Modify: `launch.py` — `BreakApp.update_ui` (`launch.py:1750–1777`).

**Interfaces:**
- Consumes: `holding_cue` (Task 1), `self._cue_labels` (Task 2), `self._held`
  (existing), `config.remaining` (existing).

- [ ] **Step 1: Drive the cue inside the per-break loop.**

In `update_ui`, the per-break loop currently is:

```python
        for i, config in enumerate(self.breaks):
            time_text = self._format_time(config.remaining)
            if i < len(self._timer_labels):
                self._timer_labels[i].configure(text=time_text)
            # Update settings panel header timer if settings window is open
            if hasattr(self, '_settings_panels') and i < len(self._settings_panels):
                try:
                    self._settings_panels[i].update_header_timer(time_text)
                except Exception:
                    pass

            if self.running and not self.paused and config.remaining < min_remaining:
                min_remaining = config.remaining
                next_break = config
```

Insert the cue show/hide block immediately after the settings-panel update
(before the `if self.running and not self.paused and config.remaining ...`
block):

```python
            # Gentle "holding" cue (#44): show why a due break is waiting.
            cue = holding_cue(config.remaining, self._held) if (
                self.running and not self.paused) else None
            if i < len(self._cue_labels):
                label = self._cue_labels[i]
                if cue:
                    label.configure(text=f"↳ {cue}")
                    if label.winfo_manager() != "pack":   # not already packed
                        label.pack(side="top", anchor="w",
                                   padx=(PADDING_PANEL_X, 0), pady=(0, 8))
                elif label.winfo_manager() == "pack":     # currently packed → hide
                    label.pack_forget()
```

- [ ] **Step 2: Verify parse + compile.**

Run: `.venv/bin/python -c "import ast; ast.parse(open('launch.py').read())"`
Expected: no output.

Run: `.venv/bin/python -m py_compile launch.py`
Expected: no output.

- [ ] **Step 3: Run the full test suite (no regressions).**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (all tests, including the new Task 1 tests).

- [ ] **Step 4: Commit.**

```bash
git add launch.py
git commit -m "feat: show gentle holding cue on held break cards (#44)"
```

---

### Task 4: Manual verification

**Files:** none (verification only).

- [ ] **Step 1: Run the app.**

Run: `.venv/bin/python launch.py`

- [ ] **Step 2: Wait-for-pause cue.**
Enable "Wait until you pause (keyboard or mouse)"; set a break to a short
interval; keep moving the mouse as it reaches 00:00.
Expected: card shows a dimmed "↳ waiting for a pause…"; when you stop moving,
the break fires and the cue line vanishes.

- [ ] **Step 3: Fullscreen cue.**
Enable "Pause breaks during fullscreen"; go fullscreen as a break comes due.
Expected: "↳ waiting for full screen to end…"; leaving fullscreen fires the
break and clears the cue.

- [ ] **Step 4: #43 intact.**
Double-click the card (name, timer, or empty area) → opens that break's config.

- [ ] **Step 5: Pause hides cue.**
While a break is held, pause the app → the cue line disappears.

- [ ] **Step 6: No defers → no cue.**
Disable all defer features and run normally → no cue ever appears; cards look
exactly as before.

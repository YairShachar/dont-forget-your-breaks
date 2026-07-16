# Settings — Collapsible Sections + Nested Sub-Options — Implementation Plan

**Spec:** `~/daily/specs/2026-07-16-settings-sections-nesting-design.md`
**Goal:** Replace the flat "General settings" card with 3 collapsible sections (Smart pausing / Break popup / App), real nested sub-options with grey-out, on a `CollapsibleSection` base shared with `BreakConfigPanel`; persist each section's expand state.

**Global constraints:** No magic numbers (tokens only). Preferences backward-compatible via `.get(key, default)`. Keep the app working after every task. Verify Tk visuals with a Quartz live capture, not just tests. TDD for pure logic.

---

## Task 1 — Pure helper: `suboption_state`

**Files:** Create `dfyb/settings_logic.py`; Test `tests/test_settings_logic.py`.

- [ ] Test: `suboption_state(True) == "normal"`, `suboption_state(False) == "disabled"`.
- [ ] Implement:
```python
def suboption_state(parent_on):
    """Tk widget state for a sub-option gated by its parent toggle."""
    return "normal" if parent_on else "disabled"
```
- [ ] Run `pytest tests/test_settings_logic.py -q` → pass. Commit.

## Task 2 — Extract `CollapsibleSection` base; refactor `BreakConfigPanel`

**Files:** Modify `launch.py` (class `BreakConfigPanel` ~806–1127).

Design:
- New `class CollapsibleSection(ctk.CTkFrame)` with:
  - `__init__(self, parent, title, *, expanded=True, on_toggle=None, title_font=None, **kwargs)` — card frame; sets `_expanded`, `_on_toggle`, animation state (`_animating`, `_animation_id`, `_expanded_height`, `_collapsed_height=PANEL_COLLAPSED_HEIGHT`); builds header; creates `self.body = CTkFrame(...)` (the content area, replaces `content_frame`).
  - `_build_header(title, title_font)` — `self.header_frame`, `self.header_label` (left, title), `self.header_right` (right, for subclass extras), `self.chevron` (▲ expanded / ▼ collapsed, existing glyphs). Bind `<Button-1>` on header widgets + `<Return>`/`<space>` → `toggle_expand`.
  - `finalize()` — caller invokes after filling `self.body`: `self.body.pack(fill="x")`, `update_idletasks()`, `self._expanded_height = winfo_reqheight()`; if not `_expanded`, apply collapsed state immediately (no animation) via `collapse(animate=False)`.
  - `toggle_expand()` — flip; call `expand()`/`collapse()`; then `if self._on_toggle: self._on_toggle(self._expanded)`.
  - `expand(animate=True)` / `collapse(animate=True)` — as today but operate on `self.body`; call hooks `self._on_expand_visual()` / `self._on_collapse_visual()` (default no-op) for subclass header tweaks; `animate=False` path sets final state without `_animate_height`.
  - `is_expanded()`, `_animate_height(...)` — moved verbatim.
- `class BreakConfigPanel(CollapsibleSection)`:
  - `__init__(parent, config, on_test)` → `super().__init__(parent, title=config.name.get(), expanded=True)`; store config/on_test; add `self.header_timer` into `self.header_right` (hidden); build all config rows into `self.body`; `self.finalize()`.
  - Override `_on_expand_visual()` → `header_timer.pack_forget()`; `_on_collapse_visual()` → `header_timer.pack(side="left", padx=(0, SPACE_MD))`.
  - Keep `focus_config()` (uses `self.interval_entry`), `update_header_timer()`.
  - Every `self.content_frame` → `self.body`.

- [ ] Refactor as above.
- [ ] `pytest -q` → all green (existing suite).
- [ ] Live capture the settings window (break panels): expand/collapse still animates, header timer appears when collapsed, looks identical to before. Commit.

## Task 3 — `CollapsibleSection` behavior test (Tk-gated)

**Files:** Create `tests/test_collapsible.py` (self-skips headless).

- [ ] `expanded=True` → `is_expanded()` True; `expanded=False` → False.
- [ ] `toggle_expand()` flips `_expanded`.
- [ ] `on_toggle` fires with the new state on `toggle_expand()`, not on initial build.
- [ ] Run → pass. Commit.

## Task 4 — Three settings sections + nested sub-block + grey-out

**Files:** Modify `launch.py` `_open_settings` (~1808–1890) + CONFIGURATION tokens.

- [ ] Add tokens: `SETTINGS_SUBOPTION_INDENT` (left inset), `SECTION_DEFAULT_EXPANDED = {"smart_pausing": True, "break_popup": False, "app": False}`.
- [ ] Replace `general_frame` block with three `CollapsibleSection`s:
  - **Smart pausing** — mic / fullscreen / wait-to-pause checkboxes into `.body`; then a nested sub-block frame (indent `SETTINGS_SUBOPTION_INDENT`, left hairline `COLORS['border']`) containing "also count mouse movement" checkbox + a pause-length row (label + slider). Labels drop the `↳`.
  - **Break popup** — the "Appears on" row into `.body`.
  - **App** — always-on-top + check-for-updates checkboxes into `.body`.
  - Each: `expanded=self._sections_expanded.get(key, SECTION_DEFAULT_EXPANDED[key])`, `on_toggle=lambda e, k=key: self._set_section_expanded(k, e)`; call `.finalize()`; keep refs in `self._settings_sections`.
- [ ] `_sync_activity_suboptions()` — sets sub-widgets' `state=suboption_state(self.defer_while_active.get())` and label `text_color` (normal vs `text_secondary`). Call at build + via `self.defer_while_active.trace_add('write', ...)`.
- [ ] `pytest -q` green. Live capture: 3 sections, Smart pausing open, sub-options greyed when parent off, no `↳`. Commit.

## Task 5 — Persist section expand state

**Files:** Modify `launch.py` `__init__` (~1166), `_save_preferences` (~1491).

- [ ] `__init__`: `self._sections_expanded = dict(self.saved_prefs.get("sections_expanded", {}))`.
- [ ] Add `_set_section_expanded(self, key, is_open)`: update dict + `self._save_preferences()`.
- [ ] `_save_preferences`: add `"sections_expanded": self._sections_expanded` to the prefs dict.
- [ ] Manual check: toggle a section, reopen settings → state remembered; restart app → still remembered. `pytest -q` green. Commit.

## Task 6 — Final verification

- [ ] Full `pytest -q` green. Full-window + settings live capture. Confirm no regressions in break panels or main window. Commit if any cleanup.

# Design Tokens — Chunk A (Token Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the renamed, role-based, adaptive light/dark token layer (type scale + `make_font`, semantic color tuples, spacing scale, button height) that the rest of the #49 makeover depends on.

**Architecture:** Pure token *logic* (`resolve_font_family`, `resolve_color`) lives in a new headless-testable module `dfyb/theme.py`. The token *data* (`FONT_SIZES`, `COLORS`, `SPACE_*`, `BUTTON_HEIGHT_*`) stays in `launch.py`'s CONFIGURATION block (renamed + tuple-valued), with a thin `make_font()` Tk wrapper. CustomTkinter resolves `(light, dark)` tuples automatically at every call site; the one computed color path (`lerp_color`) is fed through `resolve_color` first.

**Tech Stack:** Python 3 (stdlib), CustomTkinter 5.2.2, pytest. macOS-first.

**Spec:** `~/daily/specs/2026-07-14-design-tokens-chunk-a-design.md`

## Global Constraints

- No new dependencies beyond `customtkinter` (already implicit). stdlib + CTk only.
- No hardcoded visual values: every size/color/space/height is a named token or a parameter. After this chunk there must be **no** `FONT_FAMILY` constant, **no** inline `ctk.CTkFont(... size=NN ...)`, **no** `#FF6B6B`, **no** bare `gray\d+` literal, **no** `✓` in `BREAK_OVER_TEXT`.
- macOS-first with graceful non-darwin fallback: on non-darwin both font families resolve to `"Segoe UI"`.
- Adaptive theming stays on: keep `ctk.set_appearance_mode("system")`. Dark halves = current known-good values (dark mode must render pixel-identical except the intended changes below).
- Do NOT alter popup Space/focus behavior (#21): no AppleScript `activate`, keep `pin_to_active_space`.
- `dfyb/theme.py` must import **no** `tk`/`ctk` (stays a pure, headless unit).
- Run tests with `.venv/bin/python -m pytest -q`. Run the app with `.venv/bin/python launch.py`.

**Intended visible changes (everything else must render identically):** light mode adapts; headings 15→17; gear icon 15→14; row rhythm 10→8; over-state = `"Break over"` + amber countdown + amber flash; version string gray40→#808080.

---

## File Structure

- **Create** `dfyb/theme.py` — pure font/color resolvers + font-family constants. No Tk/CTk import.
- **Create** `tests/test_theme.py` — unit tests for the resolvers + a resolve_color→lerp_color integration test.
- **Modify** `launch.py` — CONFIGURATION block (rename FONT_SIZES/COLORS keys, tuple color values, add `SPACE_*`, `BUTTON_HEIGHT_XLARGE`, `display`/scale sizes, remove `FONT_FAMILY`), add `make_font()`, migrate all font/color/spacing/height call sites, over-state cleanup, `resolve_color` in the lerp path.

---

## Reference maps (single source of truth for the mechanical sweeps)

**FONT role rename + size (old key → new key : size):**
```
title(15)  → heading(17)          # +2px
message(16)→ body_emphasis(16)
control(14)→ subheading(14)
status(13) → body(13)
input(13)  → body(13)
timer(13)  → body(13)
label(12)  → label(12)
helper(10) → caption(10)
(new)      → display(48)
```
**Inline font stragglers:** `size=48`(L~359)→`make_font('display', weight="bold")`; `size=15`(L~1191, gear ⚙)→`make_font('subheading')`; `size=12`(L~767 chevron, L~904 glyph)→`make_font('label')`.

**COLOR rename + `(light, dark)` value:**
```
bg_panel            → surface_card          ("#FFFFFF", "#2C2C2E")
bg_hover            → surface_hover         ("#ECECEE", "#3A3A3C")
border              → border                ("#D1D1D6", "#3A3A3C")
text_secondary      → text_secondary        ("#8E8E93", "#999999")   # dark ≡ old gray60
(gray50 & gray40)   → text_tertiary         ("#AEAEB2", "#808080")   # dark ≡ old gray50
accent_blue         → accent_primary        ("#007AFF", "#0A84FF")
accent_hover        → accent_primary_hover  ("#0068D6", "#0077ED")
accent_green        → accent_success        ("#34C759", "#30D158")
accent_orange       → accent_warning        ("#FF9500", "#FF9F0A")
accent_orange_hover → accent_warning_hover  ("#E68600", "#E8900A")
```
Bare `gray*` sites: `text_color="gray50"`(L~1319)→`COLORS['text_tertiary']`; `text_color="gray40"`(L~1328)→`COLORS['text_tertiary']`.

**SPACE scale + snapping (nearest step, ties→smaller):**
```
SPACE_XXS=4  SPACE_XS=6  SPACE_SM=8  SPACE_MD=12  SPACE_LG=16  SPACE_XL=24  SPACE_2XL=32
4→XXS 6→XS 8→SM 10→SM 12→MD 16→LG 24→XL 30→2XL 32→2XL
PADDING_WINDOW = PADDING_PANEL_X = PADDING_PANEL_Y = SPACE_LG
ROW_SPACING = SPACE_SM
```

---

### Task 1: Pure resolvers in `dfyb/theme.py` (TDD)

**Files:**
- Create: `dfyb/theme.py`
- Test: `tests/test_theme.py`

**Interfaces:**
- Produces: `FONT_FAMILY_TEXT: str`, `FONT_FAMILY_DISPLAY: str`, `FONT_DISPLAY_THRESHOLD: int = 20`, `_IS_DARWIN: bool`; `resolve_font_family(size: int, is_darwin: bool = _IS_DARWIN) -> str`; `resolve_color(value, appearance_mode: str) -> str` where `value` is `str | tuple[str,str] | list`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_theme.py
import pytest
from dfyb import theme
from dfyb.theme import resolve_font_family, resolve_color
from dfyb.animation import lerp_color


class TestResolveFontFamily:
    def test_display_size_on_mac_uses_display_family(self):
        assert resolve_font_family(48, is_darwin=True) == "SF Pro Display"

    def test_boundary_20_on_mac_uses_display_family(self):
        assert resolve_font_family(theme.FONT_DISPLAY_THRESHOLD, is_darwin=True) == "SF Pro Display"

    def test_below_threshold_on_mac_uses_text_family(self):
        assert resolve_font_family(19, is_darwin=True) == "SF Pro Text"
        assert resolve_font_family(13, is_darwin=True) == "SF Pro Text"

    def test_non_mac_always_segoe(self):
        assert resolve_font_family(48, is_darwin=False) == "Segoe UI"
        assert resolve_font_family(10, is_darwin=False) == "Segoe UI"


class TestResolveColor:
    def test_plain_string_passes_through(self):
        assert resolve_color("#0A84FF", "Dark") == "#0A84FF"

    def test_tuple_light_mode_returns_first(self):
        assert resolve_color(("#007AFF", "#0A84FF"), "Light") == "#007AFF"

    def test_tuple_light_mode_is_case_insensitive(self):
        assert resolve_color(("#007AFF", "#0A84FF"), "light") == "#007AFF"

    def test_tuple_dark_mode_returns_second(self):
        assert resolve_color(("#007AFF", "#0A84FF"), "Dark") == "#0A84FF"

    def test_tuple_non_light_defaults_to_dark(self):
        # ctk.get_appearance_mode() only ever returns "Light"/"Dark", but be defensive
        assert resolve_color(("#007AFF", "#0A84FF"), "System") == "#0A84FF"

    def test_list_treated_like_tuple(self):
        assert resolve_color(["#007AFF", "#0A84FF"], "Light") == "#007AFF"


class TestResolveColorFeedsLerp:
    """Guards the tuple-vs-string trap on the progress-bar blend (launch.py L498)."""
    def test_resolved_endpoints_lerp_in_both_modes(self):
        blue = ("#007AFF", "#0A84FF")
        green = ("#34C759", "#30D158")
        for mode in ("Light", "Dark"):
            a, b = resolve_color(blue, mode), resolve_color(green, mode)
            assert lerp_color(a, b, 0.0) == a.lower()
            assert lerp_color(a, b, 1.0) == b.lower()
            assert lerp_color(a, b, 0.5).startswith("#")  # no crash on tuple
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_theme.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'dfyb.theme'`.

- [ ] **Step 3: Write minimal implementation**

```python
# dfyb/theme.py
"""Pure design-token resolvers (no tk/ctk import — headless-testable).

Font optical split: SF Pro ships two optical sizes; the real crossover is 20pt
(<20 = Text, >=20 = Display). Colors may be a (light, dark) tuple; resolve_color
returns the concrete hex for code paths that compute on color (e.g. lerp_color).
"""
import sys

FONT_FAMILY_TEXT = "SF Pro Text" if sys.platform == "darwin" else "Segoe UI"
FONT_FAMILY_DISPLAY = "SF Pro Display" if sys.platform == "darwin" else "Segoe UI"
FONT_DISPLAY_THRESHOLD = 20
_IS_DARWIN = sys.platform == "darwin"


def resolve_font_family(size, is_darwin=_IS_DARWIN):
    """Optical family for a point size: Display at/above the threshold, else Text.
    Non-darwin: both families are 'Segoe UI', so Text is returned unconditionally."""
    if not is_darwin:
        return FONT_FAMILY_TEXT
    return FONT_FAMILY_DISPLAY if size >= FONT_DISPLAY_THRESHOLD else FONT_FAMILY_TEXT


def resolve_color(value, appearance_mode):
    """Concrete hex for a token value. Tuples/lists are (light, dark); plain
    strings pass through. `appearance_mode` is ctk.get_appearance_mode()
    ('Light'/'Dark'); anything not 'light' resolves to the dark half."""
    if isinstance(value, (tuple, list)):
        return value[0] if str(appearance_mode).lower() == "light" else value[1]
    return value
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_theme.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add dfyb/theme.py tests/test_theme.py
git commit -m "Add pure font/color token resolvers (dfyb/theme.py)"
```

---

### Task 2: Type scale + `make_font` migration (launch.py)

**Files:**
- Modify: `launch.py` (CONFIGURATION `FONT_FAMILY`/`FONT_SIZES`; all 56 font call sites + 4 inline stragglers)

**Interfaces:**
- Consumes: `resolve_font_family`, `FONT_FAMILY_TEXT`, `FONT_FAMILY_DISPLAY` from `dfyb.theme`.
- Produces: `make_font(role, weight=None) -> ctk.CTkFont`; renamed `FONT_SIZES` (role keys per reference map).

- [ ] **Step 1: Add imports + replace the FONT_FAMILY block**

In the `dfyb.*` import group add:
```python
from dfyb.theme import (
    resolve_font_family, resolve_color,
    FONT_FAMILY_TEXT, FONT_FAMILY_DISPLAY,
)
```
Delete the `FONT_FAMILY = "SF Pro Display" if ... else "Segoe UI"` line. Replace `FONT_SIZES` with the role scale:
```python
FONT_SIZES = {
    'display': 48,        # popup countdown
    'heading': 17,        # panel header, window title
    'body_emphasis': 16,  # popup primary message
    'subheading': 14,     # main control buttons, gear icon
    'body': 13,           # status, entries, timers
    'label': 12,          # field labels, chevron/▾ glyphs
    'caption': 10,        # helper/hint text
}
```
Add the wrapper immediately after `FONT_SIZES`:
```python
def make_font(role, weight=None):
    """CTkFont for a type-scale role; family auto-picked by the 20pt optical split."""
    size = FONT_SIZES[role]
    family = resolve_font_family(size)
    return ctk.CTkFont(family=family, size=size, **({"weight": weight} if weight else {}))
```

- [ ] **Step 2: Migrate every font call site**

Transformation (apply everywhere, using the FONT role rename map above):
```
ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['OLD'], weight="bold")  →  make_font('NEW', weight="bold")
ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['OLD'])                 →  make_font('NEW')
```
Inline stragglers: `size=48`→`make_font('display', weight="bold")` (keep existing weight); `size=15`(gear)→`make_font('subheading')`; `size=12`→`make_font('label')`.

- [ ] **Step 3: Verify no old font constructs remain**

Run: `grep -n "FONT_FAMILY\|CTkFont(.*size=[0-9]\|FONT_SIZES\['\(title\|status\|input\|timer\|control\|message\|helper\)'\]" launch.py`
Expected: **no output**. (All fonts now `make_font('display'|'heading'|'body_emphasis'|'subheading'|'body'|'label'|'caption', ...)`.)

- [ ] **Step 4: Regression + human verify**

Run: `.venv/bin/python -m pytest -q` → all pass.
Run: `.venv/bin/python launch.py` → app launches; dark mode identical **except** panel header + window title are 2px larger and the gear icon 1px smaller. No crash.

- [ ] **Step 5: Commit**

```bash
git add launch.py
git commit -m "Adopt role-based type scale + make_font with 20pt optical split"
```

---

### Task 3: Semantic color tuples + resolve_color wiring (launch.py)

**Files:**
- Modify: `launch.py` (CONFIGURATION `COLORS`; all 68 color call sites + 2 bare-gray sites + the lerp path at L~498)

**Interfaces:**
- Consumes: `resolve_color` from `dfyb.theme`; `ctk.get_appearance_mode()`.
- Produces: renamed, tuple-valued `COLORS` (per reference map).

- [ ] **Step 1: Replace the COLORS dict**

```python
COLORS = {
    'surface_card':          ("#FFFFFF", "#2C2C2E"),
    'surface_hover':         ("#ECECEE", "#3A3A3C"),
    'border':                ("#D1D1D6", "#3A3A3C"),
    'text_secondary':        ("#8E8E93", "#999999"),
    'text_tertiary':         ("#AEAEB2", "#808080"),
    'accent_primary':        ("#007AFF", "#0A84FF"),
    'accent_primary_hover':  ("#0068D6", "#0077ED"),
    'accent_success':        ("#34C759", "#30D158"),
    'accent_warning':        ("#FF9500", "#FF9F0A"),
    'accent_warning_hover':  ("#E68600", "#E8900A"),
}
```

- [ ] **Step 2: Migrate every color call site**

Rename keys per the COLOR map (`bg_panel→surface_card`, `bg_hover→surface_hover`, `accent_blue→accent_primary`, `accent_hover→accent_primary_hover`, `accent_green→accent_success`, `accent_orange→accent_warning`, `accent_orange_hover→accent_warning_hover`; `border`/`text_secondary` keep name). Replace the two bare grays: `text_color="gray50"`→`text_color=COLORS['text_tertiary']`; `text_color="gray40"`→`text_color=COLORS['text_tertiary']`.

- [ ] **Step 3: Fix the one computed color path (progress-bar blend)**

At the `lerp_color(COLORS['accent_blue'], COLORS['accent_green'], ...)` site (was L~498):
```python
mode = ctk.get_appearance_mode()
self.progress_bar.configure(progress_color=lerp_color(
    resolve_color(COLORS['accent_primary'], mode),
    resolve_color(COLORS['accent_success'], mode),
    1 - progress_value))
```
(Preserve the exact surrounding call; only the two color args are wrapped in `resolve_color(..., mode)`.)

- [ ] **Step 4: Verify no old color names / bare grays remain**

Run: `grep -nE "COLORS\['(bg_panel|bg_hover|accent_blue|accent_hover|accent_green|accent_orange|accent_orange_hover)'\]|\"gray[0-9]+\"" launch.py`
Expected: **no output**.

- [ ] **Step 5: Regression + human verify (both modes)**

Run: `.venv/bin/python -m pytest -q` → all pass (lerp regression green).
Run: `.venv/bin/python launch.py` in dark → identical. Toggle macOS to Light → surfaces/text/borders adapt (colors are starting points; fine to look rough — Task 7 tunes them). Progress bar still blends blue→green.

- [ ] **Step 6: Commit**

```bash
git add launch.py
git commit -m "Convert COLORS to semantic (light,dark) tuples; resolve_color on the lerp path"
```

---

### Task 4: Spacing scale + inline-pad migration (launch.py)

**Files:**
- Modify: `launch.py` (CONFIGURATION spacing block; ~40 inline `padx=/pady=` sites; sub-option indent expression)

**Interfaces:**
- Produces: `SPACE_XXS..SPACE_2XL`; `PADDING_*`/`ROW_SPACING` as aliases.

- [ ] **Step 1: Replace the spacing block**

```python
# Spacing scale (primitive)
SPACE_XXS = 4
SPACE_XS = 6
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24
SPACE_2XL = 32
# Semantic aliases (purpose-named, layered over the scale)
PADDING_WINDOW = SPACE_LG
PADDING_PANEL_X = SPACE_LG
PADDING_PANEL_Y = SPACE_LG
ROW_SPACING = SPACE_SM   # 10 → 8 (tighter rhythm, per proposal)
```

- [ ] **Step 2: Migrate inline magic pads**

Replace inline numeric `padx=/pady=` per the snapping map (nearest step, ties→smaller):
`4→SPACE_XXS 6→SPACE_XS 8→SPACE_SM 10→SPACE_SM 12→SPACE_MD 16→SPACE_LG 24→SPACE_XL 30→SPACE_2XL 32→SPACE_2XL`. Tuple pads map element-wise, `0` stays `0`. Examples: `pady=8`→`pady=SPACE_SM`; `padx=(8,4)`→`padx=(SPACE_SM, SPACE_XXS)`; `pady=(0,6)`→`pady=(0, SPACE_XS)`; `padx=30`→`padx=SPACE_2XL`. Replace the bespoke sub-option indent expression with `SPACE_2XL`.

- [ ] **Step 3: Verify no inline magic pads remain**

Run: `grep -nE "pad[xy]=\(?[0-9]" launch.py`
Expected: **no output** (every pad references a `SPACE_*`/alias or `0`).

- [ ] **Step 4: Human verify layout**

Run: `.venv/bin/python launch.py` → main window, expanded break panels, and settings look intact; row rhythm slightly tighter is acceptable. Note any surface that looks off for Task 7.

- [ ] **Step 5: Commit**

```bash
git add launch.py
git commit -m "Formalize SPACE_* scale and migrate inline pads onto it"
```

---

### Task 5: Name the popup button height (launch.py)

**Files:**
- Modify: `launch.py` (button-dimensions block; 4 `height=40` sites at L~396/411/427/579)

- [ ] **Step 1: Add the token**

After `BUTTON_HEIGHT_SMALL = 28`:
```python
BUTTON_HEIGHT_XLARGE = 40  # popup Snooze / ▾ / Done / Set
```

- [ ] **Step 2: Replace the 4 sites**

Replace each `height=40,` in the popup buttons with `height=BUTTON_HEIGHT_XLARGE,`.

- [ ] **Step 3: Verify**

Run: `grep -n "height=40" launch.py` → **no output**.
Run: `.venv/bin/python launch.py`, trigger a break popup → Snooze/▾/Done render unchanged.

- [ ] **Step 4: Commit**

```bash
git add launch.py
git commit -m "Name the popup button height token (BUTTON_HEIGHT_XLARGE)"
```

---

### Task 6: Over-state cleanup (launch.py)

**Files:**
- Modify: `launch.py` (`BREAK_OVER_TEXT` L~168; countdown over-state at L~476; `_flash_button` L~700-709)

**Interfaces:**
- Consumes: `COLORS['accent_warning']`, the popup's normal countdown color.

- [ ] **Step 1: Drop the glyph**

`BREAK_OVER_TEXT = "Break over ✓"` → `BREAK_OVER_TEXT = "Break over"`.

- [ ] **Step 2: Recolor the countdown when over**

Where the over-state is entered (`self.countdown_label.configure(text=BREAK_OVER_TEXT)`), also set `text_color=COLORS['accent_warning']`. Where a new break starts / the timer resets (countdown text set back to a time), restore the countdown's normal `text_color` (the default label color used before over-time — capture the original color constant/value used at countdown creation and reuse it; do not hardcode).

- [ ] **Step 3: Replace the flash color**

In `_flash_button`, `flash_color = "#FF6B6B"` → `flash_color = COLORS['accent_warning']`.

- [ ] **Step 4: Verify**

Run: `grep -n "FF6B6B\|Break over ✓" launch.py` → **no output**.
Run: `.venv/bin/python launch.py`; start a short break, let it elapse → label reads `"Break over"` in amber, count-up amber, Snooze flash amber. Start another break → countdown color back to normal.

- [ ] **Step 5: Commit**

```bash
git add launch.py
git commit -m "Unify over-state on accent_warning; drop the ✓ glyph"
```

---

### Task 7: Light-mode live tuning (collaborative — with user)

**Files:**
- Modify: `launch.py` (`COLORS` light halves only, as needed)

- [ ] **Step 1:** Run `.venv/bin/python launch.py`; ask the user to toggle macOS → Light.
- [ ] **Step 2:** Screenshot each surface: main window, settings, break popup (incl. elapsed/over amber state).
- [ ] **Step 3:** With the user, tune the **neutral** light halves (`surface_card`, `surface_hover`, `border`, `text_secondary`, `text_tertiary`) against their reference until each reads right. Leave accents on Apple's documented values unless they clash.
- [ ] **Step 4:** Re-verify dark mode still identical; `.venv/bin/python -m pytest -q` green.
- [ ] **Step 5: Commit**

```bash
git add launch.py
git commit -m "Tune light-mode neutral colors from live review"
```

---

## Self-Review

**Spec coverage:** §2 type scale → Task 2; §3 font split → Task 1+2; §4 color tuples → Task 3; §4.1 resolve_color/lerp → Task 1 (test) + Task 3 (wire); §5 spacing → Task 4; §6 button height → Task 5; §7 over-state → Task 6; §8 architecture → Task 1 (module) + Task 2/3 (dicts stay in launch.py); §9 testing → Task 1 tests + per-task verify; §10 light tuning → Task 7; §11 acceptance → distributed grep/verify steps. No gaps.

**Placeholder scan:** mechanical sweeps specify exact transformation rules + a completeness grep rather than 56/68 literal diffs (the transformation rule IS the content); Task 1 has full code. No TBD/TODO.

**Type consistency:** `make_font(role, weight=None)`, `resolve_font_family(size, is_darwin=_IS_DARWIN)`, `resolve_color(value, appearance_mode)` used identically across tasks. FONT_SIZES role keys and COLORS names identical between the reference maps and every task.

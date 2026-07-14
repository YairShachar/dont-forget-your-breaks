# Main-Window Visual Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (inline, with live human-verify checkpoints). Steps use `- [ ]`.

**Goal:** Rebuild the main window as a calm "status cockpit" — a status hero (state dot + next-break countdown + progress), rich break rows with bundled PNG icons, a readable Break-now, a visible "holding" deferral state, and a tight fit-to-content window — all in CustomTkinter, on the Chunk-A token layer.

**Architecture:** A new pure `dfyb/insights/status.py` computes the hero's `StatusView` (state, dot color, headline, subtext, progress, chip) from app state; the widget layer is a dumb renderer refreshed by `update_ui`. Icons are bundled PNGs loaded via `CTkImage` (adds Pillow). The signature is a slow breathing pulse on the status dot (reduced-motion aware).

**Tech Stack:** Python 3, CustomTkinter 5.2.2, **Pillow (new dep, required by CTkImage)**, pytest.

**Design brief:** `~/daily/specs/2026-07-14-redesign-research-and-direction.md` + approved mockup.

## Global Constraints
- Built in CustomTkinter — flat surfaces, borders, corner radius, `CTkImage` icons; **no shadows/gradients/vibrancy**.
- Every visual value is a token from the Chunk-A CONFIGURATION block (extend it; no inline magic).
- Copy is user-side, plain, calm ("look away for 20s", not clinical). Sentence case. Active voice.
- Respect `prefers_reduced_motion` (no dot pulse when set) — reuse `dfyb.animation.prefers_reduced_motion`.
- Preserve existing behaviors: double-click card → config (#43), holding cue (#44), Break now (#50 dedup), snooze rows, popup on active Space (#21). Backward-compatible prefs.
- Pillow added to `requirements.txt` and the `.venv`; icons bundled via the `.spec` `datas`.
- Tests: `.venv/bin/python -m pytest -q`. Run app: `.venv/bin/python launch.py`.

## Design system (derived, CTk-buildable)
- **Color:** dot/status = `accent_success` (on track), `accent_warning` (holding/paused/over), `text_tertiary` (idle). Accent actions = `accent_primary`. Surfaces = `surface_card` (hero + rows), `surface_hover` (icon chip). All Chunk-A tuples already exist.
- **Type:** new `FONT_SIZES['status_hero'] = 28` (≥20 → SF Pro Display). Hero state label = `label` bold; subtext = `caption`/`body` secondary; row name = `body` semibold; interval subtitle = `caption` secondary; countdown = `body` bold.
- **New tokens:** `DOT_SIZE=9`, `ICON_SIZE=20`, `ICON_CHIP=32`, `PROGRESS_HEIGHT=6`, `HERO_PAD=16`, `DOT_PULSE_MS=4000`.
- **Icons:** monochrome line PNGs, accent-colored, light+dark variants, drawn at 3× for retina. `eye` (micro), `mug` (normal), `break` (fallback). Mapped by break index (0→eye, 1→mug, else→break).
- **Signature:** the status dot breathes (~4s ease in/out alpha 1.0↔0.45) when running & on-track; static under reduced motion or when idle/paused.
- **Layout (ASCII):**
```
┌───────────────────────────────┐
│ ● On track               ⚙    │  hero card (surface_card)
│ Next break in 4:32             │  status_hero
│ Micro Break · look away 20s    │  caption secondary
│ ▓▓▓▓▓▓▓░░░░░░░  progress        │  accent, PROGRESS_HEIGHT
│ [    Pause    ][    Reset    ]  │  global controls
├───────────────────────────────┤
│ [eye] Micro Break      4:32     │  rich row
│       every 15 min·20s  Break now
├───────────────────────────────┤
│ [mug] Normal Break    39:32     │
│       every 50 min·5m   Break now
├───────────────────────────────┤
│ ⚙                 v1.8.0·Feedback
└───────────────────────────────┘
```

---

### Task 1: Pure status model — `dfyb/insights/status.py` (TDD)

**Files:** Create `dfyb/insights/status.py`; Test `tests/test_status.py`.

**Interfaces — Produces:**
- `format_countdown(seconds:int)->str` — `"M:SS"`, `"H:MM:SS"` past an hour, `"0:00"` floor.
- `progress_fraction(remaining:int, interval:int)->float` — `1 - remaining/interval`, clamped [0,1]; 0 if interval<=0.
- `StatusView` (dataclass): `state:str, dot:str, headline:str, subtext:str, progress:float, chip:str|None`.
- `compute_status(*, running, paused, held_reason, next_name, next_remaining, next_interval, break_active)->StatusView`.
  - not running → `state="idle", dot="idle", headline="Idle", subtext="Start when you're ready", progress=0, chip=None`.
  - running & paused → `state="paused", dot="warning", headline="Paused", subtext="Breaks are on hold", progress=0, chip=None`.
  - running & held_reason → `state="holding", dot="warning", headline="Waiting — "+held_reason, subtext=next_name+" is due; it'll wait", progress=progress_fraction(...), chip="Breaks pause during "+held_reason`.
  - running & break_active → `state="break", dot="warning", headline="Break time", subtext=next_name, progress=1.0, chip=None`.
  - else (running, on track) → `state="on_track", dot="good", headline="Next break in "+format_countdown(next_remaining), subtext=next_name, progress=progress_fraction(...), chip=None`.

- [ ] **Step 1: failing tests** (`tests/test_status.py`)
```python
from dfyb.insights.status import format_countdown, progress_fraction, compute_status

class TestFormat:
    def test_mmss(self): assert format_countdown(272) == "4:32"
    def test_floor_zero(self): assert format_countdown(-5) == "0:00"
    def test_hours(self): assert format_countdown(3723) == "1:02:03"

class TestProgress:
    def test_mid(self): assert progress_fraction(300, 600) == 0.5
    def test_clamped(self): assert progress_fraction(-10, 600) == 1.0
    def test_zero_interval(self): assert progress_fraction(5, 0) == 0.0

class TestCompute:
    def base(self, **kw):
        d = dict(running=True, paused=False, held_reason=None, next_name="Micro Break",
                 next_remaining=272, next_interval=900, break_active=False); d.update(kw); return d
    def test_idle(self):
        v = compute_status(**self.base(running=False))
        assert v.state == "idle" and v.dot == "idle" and v.progress == 0
    def test_paused(self):
        v = compute_status(**self.base(paused=True))
        assert v.state == "paused" and v.dot == "warning"
    def test_on_track(self):
        v = compute_status(**self.base())
        assert v.state == "on_track" and v.dot == "good"
        assert v.headline == "Next break in 4:32" and v.subtext == "Micro Break"
        assert abs(v.progress - (1 - 272/900)) < 1e-9 and v.chip is None
    def test_holding(self):
        v = compute_status(**self.base(held_reason="a call"))
        assert v.state == "holding" and v.dot == "warning"
        assert v.headline == "Waiting — a call" and v.chip == "Breaks pause during a call"
```
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_status.py -q` → FAIL (module missing).
- [ ] **Step 3:** implement `dfyb/insights/status.py` per the interface contract above (dataclass + the three functions; no tk/ctk import).
- [ ] **Step 4:** rerun → PASS.
- [ ] **Step 5:** commit `Add pure status model for the cockpit hero (dfyb/insights/status.py)`.

---

### Task 2: Icon assets + loader (Pillow)

**Files:** add `Pillow` to `requirements.txt`; `scripts/gen_icons.py` (generator); create `assets/icons/{eye,mug,break}-{light,dark}.png`; modify `launch.py` (icon loader + `.spec` datas); Test `tests/test_icons.py`.

- [ ] **Step 1:** `.venv/bin/pip install pillow` and add `Pillow` to `requirements.txt`.
- [ ] **Step 2:** write `scripts/gen_icons.py` — draw eye/mug/break as anti-aliased line icons at 3×(=60px) on transparent bg with `PIL.ImageDraw` (rounded caps; stroke width ~4 at 3×), in the accent light (`#007AFF`) and dark (`#0A84FF`) hexes; save the six PNGs to `assets/icons/`. Run it.
- [ ] **Step 3 (TDD):** `tests/test_icons.py` — assert the six files exist and open as RGBA via Pillow. Run → PASS.
- [ ] **Step 4:** in `launch.py` add `ICON_DIR = BASE_DIR/"assets"/"icons"` and `load_icon(name, size=ICON_SIZE)->ctk.CTkImage` (light_image/dark_image from the two PNGs). Add `('assets/icons', 'assets/icons')` to the `.spec` `datas`.
- [ ] **Step 5:** human-verify: `.venv/bin/python launch.py` still launches (icons not wired yet). Commit `Add bundled line-icon assets + CTkImage loader (Pillow)`.

---

### Task 3: New tokens

**Files:** modify `launch.py` CONFIGURATION.
- [ ] **Step 1:** add `FONT_SIZES['status_hero']=28`; constants `DOT_SIZE=9, ICON_SIZE=20, ICON_CHIP=32, PROGRESS_HEIGHT=6, HERO_PAD=SPACE_LG, DOT_PULSE_MS=4000`; a `STATUS_DOT_COLORS = {"good": COLORS['accent_success'], "warning": COLORS['accent_warning'], "idle": COLORS['text_tertiary']}` map.
- [ ] **Step 2:** `.venv/bin/python -c "import launch"` OK. Commit `Add cockpit design tokens (status_hero, dot/icon/progress sizes)`.

---

### Task 4: Rebuild the status hero (widget)

**Files:** modify `launch.py` `_build_ui` (status_frame + control_frame → hero) and `update_ui` (wire `compute_status`).
- [ ] **Step 1:** replace `status_frame`/`control_frame` with a `hero` `CTkFrame` (`fg_color=surface_card`, `corner_radius=CORNER_RADIUS_PANEL`, padding `HERO_PAD`) containing: a top row [status dot (a small `CTkFrame`/`CTkCanvas` circle) + `self.status` state label + `self.settings_btn` gear right]; `self.hero_headline` (`status_hero`); `self.hero_sub` (`caption`, secondary); `self.hero_progress` (`CTkProgressBar`, `PROGRESS_HEIGHT`, `accent_primary`); the `self.toggle_btn`/`self.reset_btn` controls row (kept, restyled). Add `self.hero_chip` (hidden `CTkLabel`, amber) for the holding state.
- [ ] **Step 2:** in `update_ui`, gather inputs (running, paused, `self._held`, next break name/remaining/interval, `self.active_popup`), call `compute_status`, and render: dot color from `STATUS_DOT_COLORS[view.dot]`, `self.status`←`view.headline` split (state word) — actually set `self.status` to a short state and `self.hero_headline` to `view.headline`; `hero_sub`←`view.subtext`; `hero_progress.set(view.progress)`; chip shown iff `view.chip`. Remove the old `next_break_label` string.
- [ ] **Step 3:** human-verify (run app, dark+light): hero shows "Idle" then, after Start, "Next break in M:SS" with progress + green dot; Pause → amber "Paused"; simulate holding if feasible. Re-fit window (Task 7).
- [ ] **Step 4:** commit `Rebuild status area as a cockpit hero driven by compute_status`.

---

### Task 5: Rich break rows + readable Break now + icons

**Files:** modify `launch.py` `_build_ui` per-break card loop.
- [ ] **Step 1:** rebuild each card as a grid-like row: `[icon chip: CTkLabel(image=load_icon(...), fg_color=surface_hover, ICON_CHIP)] [meta: name (body semibold) + interval subtitle "every 15 min · 20s" (caption secondary)] [value: countdown (body bold) + "Break now" (a text button, `fg_color=transparent`, `text_color=accent_primary`, `font=make_font('caption', weight='bold')`, no border)]`. Keep `_timer_labels`, `_cue_labels`, double-click binding, `break_now` command. Icon by index.
- [ ] **Step 2:** update `update_ui` row refresh if label references changed (countdown still via `_timer_labels[i]`; add interval subtitle text from `config`).
- [ ] **Step 3:** human-verify: rows show icon + name + interval + countdown + a **readable blue Break now**; double-click still opens config; holding cue still appears. dark+light.
- [ ] **Step 4:** commit `Rich break rows with icons and a readable Break now`.

---

### Task 6: Breathing pulse on the status dot (signature)

**Files:** modify `launch.py` (dot widget + a pulse loop).
- [ ] **Step 1:** implement `_pulse_dot()` — an `after(DOT_PULSE_MS/ N)` loop easing the dot's alpha/shade between full and ~0.45 using `ease_in_quad`/`ease_out_quad` (reuse), only while `state=="on_track"`; **skip entirely if `prefers_reduced_motion()`** or not on track (static full color). Implement "alpha" as a blend between the dot color and `surface_card` via `lerp_color(resolve_color(dot), resolve_color(surface_card), t)`.
- [ ] **Step 2:** human-verify: slow calm pulse when on track; static when paused/idle; static when Reduce Motion is on (System Settings → Accessibility). No flamboyance.
- [ ] **Step 3:** commit `Breathing status-dot pulse (reduced-motion aware)`.

---

### Task 7: Fit-to-content (kill the void)

**Files:** modify `launch.py` `_fit_window_to_content` / `update_ui`.
- [ ] **Step 1:** diagnose the void — after `_build_ui`, print `winfo_reqheight` vs the summed child heights; the likely cause is `bottom_frame.pack(side="bottom")` + an always-packed empty `_snoozed_container` reserving space, or a stale saved height. Fix so the fitted height equals the natural content stack.
- [ ] **Step 2:** call `_fit_window_to_content()` again after dynamic content changes (snooze rows appear/disappear, chip show/hide) so the window stays tight.
- [ ] **Step 3:** human-verify: no grey void below the footer in idle or running states.
- [ ] **Step 4:** commit `Fit main window tightly to content (remove empty void)`.

---

### Task 8: Full pass + verify

- [ ] `.venv/bin/python -m pytest -q` — all green (status + icons + existing).
- [ ] `.venv/bin/python launch.py` — full walkthrough dark+light: idle → Start → on-track (pulse, progress) → Pause → holding (if reproducible) → Break now (popup on active Space, #21) → reset. No void; Break now readable; icons crisp on retina.
- [ ] Update the `.spec`, `requirements.txt`; commit `Bundle icon assets in the app build`.

## Self-Review
- Spec coverage: cockpit hero → T3/T4; rich rows+icons → T2/T5; readable Break now → T5; visible holding → T1/T4; fit-to-content → T7; signature pulse → T6; kind copy → T1/T4/T5 copy. Pure logic isolated + TDD (T1) per CLAUDE.md. Pillow dependency called out (T2, global constraints).
- Open risks: icon drawing quality in PIL (may iterate live); the void root-cause is diagnosed in T7 not assumed; holding state may be hard to reproduce manually (verify via a temporary forced `_held`).

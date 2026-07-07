# Configurable Break-Popup Placement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Task 1 is a human-run spike** that validates the active-screen signal before any feature code. Task 4 ends with a human live check on multi-monitor.

**Goal:** Make the break popup appear on a deliberately-chosen screen (active / primary / cursor) via a user preference, instead of always at the mouse cursor (#25③).

**Architecture:** A pure geometry module (`dfyb/popup_placement.py`) does the screen math; a thin macOS helper (`sensors.frontmost_window_rect`) supplies the keyboard-focus signal, reusing the `CGWindowList` + `_active_display_rects` infra from fullscreen detection; `launch.py` adds the pref + a Settings dropdown and folds the two duplicated cursor blocks into one `_position_popup()` helper.

**Tech Stack:** Python 3, CustomTkinter, pyobjc (Quartz), pytest.

**Spec:** `~/daily/specs/2026-07-06-popup-placement-design.md`

## Global Constraints

- Pref `popup_placement` ∈ `{"active","primary","cursor"}`, default **"active"**, read with `.get("popup_placement", "active")` (backward-compatible).
- `"active"` detection failure falls back to **primary** (never cursor).
- All screen/window rects are `(x, y, w, h)` in **global top-left points** (Quartz `CGDisplayBounds` / `CGWindowBounds` — matches Tk global coords). No AppKit bottom-left coordinates.
- No hardcoded values: `POPUP_WIDTH, POPUP_HEIGHT` replace `380, 300`; placement labels live in a constant.
- macOS calls guarded (`sys.platform == "darwin"` + try/except → safe fallback); non-macOS degrades gracefully.
- Conventional-commit messages (summary only). Baseline suite: **93 passed**.

## Repo conventions

- `.venv/bin/python`. Personal git identity is automatic; `gh` uses `GH_CONFIG_DIR="$HOME/.config/gh-personal"`.

## Pre-flight (run once)

```bash
cd ~/data/projects/dont_forget_your_breaks
git checkout main && git pull --ff-only origin main
.venv/bin/python -m pytest -q            # baseline: 93 passed
git checkout -b popup-placement
```

---

### Task 1: Spike — validate the active-screen signal (human-run, no feature code)

**Goal:** Confirm that "the frontmost non-dfyb window's center, mapped to a display" reliably identifies the screen you're working on, on the real two-monitor setup — before we build on it. Read-only.

**Files:**
- Create: `scratchpad/placement_spike.py` (throwaway; not committed to the repo)

- [ ] **Step 1: Write the probe**

Create `placement_spike.py` in the session scratchpad dir:
```python
"""#25③ spike: does the frontmost non-dfyb window resolve to the screen I'm on?
Prints, once/sec for 30s, to a file (so fullscreen/other apps don't hide it):
  - active displays,
  - the frontmost on-screen layer-0 window NOT owned by our app (owner + rect),
  - which display that window's CENTER falls in.
RUN IT, then click into windows on DIFFERENT monitors every few seconds.
The tell: the resolved display should match the monitor you just clicked."""
import os, sys, time
sys.path.insert(0, os.path.expanduser("~/data/projects/dont_forget_your_breaks"))
from dfyb.activity import sensors
import Quartz

REPORT = os.path.join(os.path.dirname(__file__), "placement_spike.txt")
EXCLUDE = {"Dont Forget Your Breaks", "Python", "python3", "iTerm2"}  # ignore our app + the terminal running the probe

def frontmost_nondfyb():
    wins = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID)
    for w in wins:
        if w.get("kCGWindowLayer", 1) != 0:
            continue
        owner = w.get("kCGWindowOwnerName", "?")
        if owner in EXCLUDE:
            continue
        b = w.get("kCGWindowBounds", {})
        return owner, (b.get("X", 0.0), b.get("Y", 0.0), b.get("Width", 0.0), b.get("Height", 0.0))
    return None, None

def display_for_center(rect, displays):
    if not rect:
        return None
    cx, cy = rect[0] + rect[2] / 2, rect[1] + rect[3] / 2
    for d in displays:
        if d[0] <= cx < d[0] + d[2] and d[1] <= cy < d[1] + d[3]:
            return (int(d[0]), int(d[1]), int(d[2]), int(d[3]))
    return None

lines = []
for i in range(30):
    displays = sensors._active_display_rects(Quartz)
    owner, rect = frontmost_nondfyb()
    disp = display_for_center(rect, displays)
    r = tuple(int(v) for v in rect) if rect else None
    lines.append(f"t={i:2d}s frontmost={owner!r} rect={r} -> display={disp}")
    lines.append(f"    displays={[(int(a),int(b),int(c),int(e)) for (a,b,c,e) in displays]}")
    with open(REPORT, "w") as f:
        f.write("\n".join(lines))
    time.sleep(1)
print("wrote", REPORT)
```

- [ ] **Step 2: Human runs it on multi-monitor**

Run: `.venv/bin/python scratchpad/placement_spike.py`, then click into apps on **different monitors** every few seconds. Read `placement_spike.txt`.

- [ ] **Step 3: Decide**

- **PASS** (resolved `display` tracks the monitor of the window you clicked): proceed — Tasks 2–4 use this signal as written.
- **FAIL** (wrong/None display, or coordinate mismatch): STOP and report the output. Fallback plan is candidate A (`NSScreen.mainScreen` + a y-flip helper); we redesign Task 3 before continuing.

No commit (throwaway spike). Record the outcome in the branch notes.

---

### Task 2: Pure geometry module `dfyb/popup_placement.py` (TDD)

**Files:**
- Create: `dfyb/popup_placement.py`
- Test: `tests/test_popup_placement.py`

**Interfaces:**
- Produces:
  - `screen_for_point(point, screens) -> tuple | None` — `point=(px,py)`, `screens=[(x,y,w,h),...]`; the containing screen rect or `None`.
  - `center_on_screen(screen_rect, w, h) -> (x, y)` — top-left to center a `w×h` popup.
  - `clamp_onscreen(x, y, w, h, screen_rect) -> (x, y)` — keep the popup fully inside the screen.

- [ ] **Step 1: Write failing tests**

Create `tests/test_popup_placement.py`:
```python
from dfyb.popup_placement import screen_for_point, center_on_screen, clamp_onscreen

MAIN = (0, 0, 1920, 1080)
SECOND = (1920, 64, 1512, 982)
SCREENS = [MAIN, SECOND]


def test_screen_for_point_on_each_screen():
    assert screen_for_point((100, 100), SCREENS) == MAIN
    assert screen_for_point((2500, 300), SCREENS) == SECOND


def test_screen_for_point_outside_all_is_none():
    assert screen_for_point((-50, -50), SCREENS) is None
    assert screen_for_point((99999, 99999), SCREENS) is None


def test_center_on_screen_centers_rect():
    assert center_on_screen(MAIN, 380, 300) == (770, 390)
    assert center_on_screen(SECOND, 380, 300) == (1920 + (1512 - 380) // 2, 64 + (982 - 300) // 2)


def test_clamp_onscreen_pulls_popup_fully_inside():
    # pushed off bottom-right -> clamped to the max in-bounds position
    assert clamp_onscreen(1900, 1000, 380, 300, MAIN) == (1920 - 380, 1080 - 300)
    # pushed off top-left -> clamped to the screen origin
    assert clamp_onscreen(-30, -30, 380, 300, MAIN) == (0, 0)
    # already inside -> unchanged
    assert clamp_onscreen(100, 100, 380, 300, MAIN) == (100, 100)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_popup_placement.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'dfyb.popup_placement'`.

- [ ] **Step 3: Implement the module**

Create `dfyb/popup_placement.py`:
```python
"""Pure geometry for placing the break popup on a chosen screen.

No Tk, no macOS — every rect is (x, y, w, h) in global top-left points, so this
is unit-tested off-macOS (mirrors dfyb.activity.sensors.covers_any_display)."""


def screen_for_point(point, screens):
    """The screen rect containing `point=(px, py)`, or None if none does."""
    px, py = point
    for (sx, sy, sw, sh) in screens:
        if sx <= px < sx + sw and sy <= py < sy + sh:
            return (sx, sy, sw, sh)
    return None


def center_on_screen(screen_rect, w, h):
    """Top-left (x, y) that centers a `w`x`h` popup on `screen_rect`."""
    sx, sy, sw, sh = screen_rect
    return (sx + (sw - w) // 2, sy + (sh - h) // 2)


def clamp_onscreen(x, y, w, h, screen_rect):
    """Nudge (x, y) so the `w`x`h` popup stays fully within `screen_rect`."""
    sx, sy, sw, sh = screen_rect
    return (max(sx, min(x, sx + sw - w)), max(sy, min(y, sy + sh - h)))
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_popup_placement.py -q` → PASS
Run: `.venv/bin/python -m pytest -q` → PASS (97 passed: 93 + 4 new)

- [ ] **Step 5: Commit**

```bash
git add dfyb/popup_placement.py tests/test_popup_placement.py
git commit -m "feat: add pure popup-placement geometry helpers"
```

---

### Task 3: macOS keyboard-focus signal — `sensors.frontmost_window_rect` (thin)

**Files:**
- Modify: `dfyb/activity/sensors.py` (add one function)

**Interfaces:**
- Produces: `frontmost_window_rect() -> tuple | None` — `(x, y, w, h)` in global top-left points of the **frontmost application's** frontmost on-screen layer-0 window (via `NSWorkspace.frontmostApplication()` PID, so Stage Manager / `WindowManager` overlays never pollute it — validated by spike v2); `None` on non-macOS / failure / none found.

- [ ] **Step 1: Add the function**

In `dfyb/activity/sensors.py`, add (near `_layer0_window_rects`, reusing the same `CGWindowList` options):
```python
def frontmost_window_rect():
    """(x, y, w, h) of the frontmost APPLICATION's frontmost on-screen layer-0
    window, in global top-left points. None on non-macOS / failure / none.

    Uses NSWorkspace.frontmostApplication() (the app you're working in — never
    Stage Manager / WindowManager) and matches its PID in the on-screen window
    list, so system overlays don't pollute the result. Only the resulting
    screen is used, so picking a minor window of that app is fine.
    """
    if sys.platform != "darwin":
        return None
    try:
        import Quartz
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return None
        pid = app.processIdentifier()
        windows = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID,
        )
        for window in windows:
            if window.get("kCGWindowLayer", 1) != 0:
                continue
            if window.get("kCGWindowOwnerPID") != pid:
                continue
            bounds = window.get("kCGWindowBounds", {})
            return (bounds.get("X", 0.0), bounds.get("Y", 0.0),
                    bounds.get("Width", 0.0), bounds.get("Height", 0.0))
        return None
    except Exception:
        return None
```

- [ ] **Step 2: Sanity-check import + non-crash**

Run:
```bash
.venv/bin/python -c "from dfyb.activity.sensors import frontmost_window_rect; print('ok', frontmost_window_rect() is not None or True)"
```
Expected: prints `ok True` (returns a rect or None, never raises).

- [ ] **Step 3: Full suite (unchanged) + commit**

Run: `.venv/bin/python -m pytest -q` → PASS (97 passed — no new tests; native code is human-verified in Task 4).
```bash
git add dfyb/activity/sensors.py
git commit -m "feat: add frontmost_window_rect for popup active-screen detection"
```

---

### Task 4: Pref + Settings dropdown + `_position_popup()` (launch-verified + human check)

**Files:**
- Modify: `launch.py` (constants, `CountdownPopup` positioning ×2, `BreakApp` pref + `_save_preferences` + Settings dropdown)

**Interfaces:**
- Consumes: `dfyb.popup_placement.{screen_for_point,center_on_screen,clamp_onscreen}` (Task 2); `dfyb.activity.sensors.{_active_display_rects (via a safe wrapper), frontmost_window_rect}` (Task 3).

- [ ] **Step 1: Add constants**

In `launch.py`, after `SETTINGS_WINDOW_Y_OFFSET = 80` (the settings-window constants block), add:
```python
# Break popup
POPUP_WIDTH = 380
POPUP_HEIGHT = 300
# Settings dropdown label -> stored popup_placement value
POPUP_PLACEMENT_LABELS = {
    "Active screen": "active",
    "Primary screen": "primary",
    "Follow cursor": "cursor",
}
```

- [ ] **Step 2: Add the import**

In `launch.py`, alongside the other `from dfyb...` imports at the top, add:
```python
from dfyb.popup_placement import screen_for_point, center_on_screen, clamp_onscreen
from dfyb.activity.sensors import frontmost_window_rect
```
(There is already `from dfyb.activity.sensors import read_context`; extend it or add this line — either is fine.)

- [ ] **Step 3: Add a module-level placement resolver on `CountdownPopup`**

The popup needs the placement mode. In `CountdownPopup.__init__` signature (currently `def __init__(self, parent, title, message, duration, auto_dismiss=True, on_close=None, on_snooze=None, end_sound=None, loop_end_sound=False):`) append:
```python
                 placement="active",
```
and in the body store:
```python
        self.placement = placement
```

- [ ] **Step 4: Add the `_position_popup` method**

Add this method to `CountdownPopup` (place it just before the first current positioning block):
```python
    def _target_screen(self, screens):
        """Pick the screen rect (x, y, w, h) to place the popup on, per mode."""
        if self.placement == "cursor":
            point = (self.window.winfo_pointerx(), self.window.winfo_pointery())
            return screen_for_point(point, screens) or (screens[0] if screens else None)
        if self.placement == "active":
            rect = frontmost_window_rect()
            if rect:
                center = (rect[0] + rect[2] / 2, rect[1] + rect[3] / 2)
                hit = screen_for_point(center, screens)
                if hit:
                    return hit
            return screens[0] if screens else None  # fallback: primary
        return screens[0] if screens else None      # "primary"

    def _position_popup(self):
        """Center the popup on the chosen screen (per placement mode)."""
        from dfyb.activity.sensors import _active_display_rects
        screens = []
        if sys.platform == "darwin":
            try:
                import Quartz
                screens = _active_display_rects(Quartz)
            except Exception:
                screens = []
        screen = self._target_screen(screens)
        if screen is None:  # non-macOS / no Quartz: use the Tk screen
            sw = self.window.winfo_screenwidth()
            sh = self.window.winfo_screenheight()
            screen = (0, 0, sw, sh)
        x, y = center_on_screen(screen, POPUP_WIDTH, POPUP_HEIGHT)
        x, y = clamp_onscreen(x, y, POPUP_WIDTH, POPUP_HEIGHT, screen)
        self.window.geometry(f"{POPUP_WIDTH}x{POPUP_HEIGHT}+{x}+{y}")
```

- [ ] **Step 5: Replace the two cursor blocks**

Read `launch.py` lines ~224-233 and ~430-436. Each currently computes `popup_w, popup_h = 380, 300` then positions from `winfo_pointerx/y`. Replace **each** block's positioning statements with a single call:
```python
        self._position_popup()
```
Remove the now-dead `popup_w, popup_h = 380, 300` / `mouse_x` / `mouse_y` / `x` / `y` / `geometry(...)` lines in both spots. (Grep afterwards: `grep -n "winfo_pointerx\|380, 300" launch.py` must return nothing.)

- [ ] **Step 6: Pass the pref into the popup**

Find where `CountdownPopup(...)` is constructed (in `trigger_break`). Add `placement=self.popup_placement.get()` to the call.

- [ ] **Step 7: Add the pref**

In `BreakApp.__init__`, after the `self.defer_during_fullscreen` pref block, add:
```python
        self.popup_placement = ctk.StringVar(
            value=self.saved_prefs.get("popup_placement", "active")
        )
        self.popup_placement.trace_add('write', self._save_preferences)
```

- [ ] **Step 8: Persist the pref**

In `_save_preferences`, after `"defer_during_fullscreen": self.defer_during_fullscreen.get(),` add:
```python
            "popup_placement": self.popup_placement.get(),
```

- [ ] **Step 9: Add the Settings dropdown**

In `_open_settings`, after the "Pause breaks during fullscreen" checkbox block and before the window-sizing block, add a labelled dropdown. Its `CTkOptionMenu` shows the labels and writes the stored value:
```python
        placement_row = ctk.CTkFrame(general_frame, fg_color="transparent")
        placement_row.pack(padx=PADDING_PANEL_X, pady=(4, PADDING_PANEL_Y), anchor="w", fill="x")
        ctk.CTkLabel(
            placement_row, text="Break popup appears on",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
        ).pack(side="left")
        value_to_label = {v: k for k, v in POPUP_PLACEMENT_LABELS.items()}

        def _on_placement(label):
            self.popup_placement.set(POPUP_PLACEMENT_LABELS[label])

        placement_menu = ctk.CTkOptionMenu(
            placement_row, values=list(POPUP_PLACEMENT_LABELS.keys()),
            command=_on_placement,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZES['label'])
        )
        placement_menu.set(value_to_label.get(self.popup_placement.get(), "Active screen"))
        placement_menu.pack(side="right")
```
(Note: give the "Pause breaks during fullscreen" checkbox above it `pady=(4, 4)` since `placement_row` — with trailing `PADDING_PANEL_Y` — is now the last item in the frame, mirroring the checkbox spacing convention.)

- [ ] **Step 10: Full suite + launch-smoke**

Run: `.venv/bin/python -m pytest -q` → PASS (97 passed).
Run: `timeout 6 .venv/bin/python launch.py; echo "exit=$? (124=ran fine)"` → `exit=124`, no traceback.
Run: `grep -n "winfo_pointerx\|380, 300" launch.py` → no matches (dedup complete).

- [ ] **Step 11: HUMAN LIVE CHECK (multi-monitor)**

Run the app, short break interval, Start, then for each mode (Settings → "Break popup appears on"):
- **Active screen:** work on monitor A (click a window there), let a break fire → popup appears on **monitor A**; repeat on monitor B.
- **Primary screen:** break always appears on the **main** monitor regardless of where you're working.
- **Follow cursor:** popup appears on the monitor with the **mouse**.
- Change the dropdown, reopen Settings / restart → the choice **persisted**.
- Multi-monitor #21 guarantee still holds: no Space switch when the popup appears.

**If any fail:** STOP and report.

- [ ] **Step 12: Commit**

```bash
git add launch.py
git commit -m "feat: configurable break-popup placement (active/primary/cursor) via one _position_popup helper"
```

---

## Definition of done

- `popup_placement` pref (default active) + Settings dropdown + `_position_popup()` replacing both cursor blocks; `POPUP_WIDTH/HEIGHT` constants; no `winfo_pointerx`/`380, 300` left.
- `pytest -q` passes (**97**).
- Human live check passed: active/primary/cursor each place the popup correctly on multi-monitor; choice persists; no Space switch.

## Wrap-up

- Push `popup-placement`; PR (base `main`) via `GH_CONFIG_DIR="$HOME/.config/gh-personal" gh pr create`, "closes part of #25 (item ③)" — do NOT auto-close #25 (items ① and ② remain).

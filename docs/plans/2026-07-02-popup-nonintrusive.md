# Non-intrusive Break Popup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Human-in-the-loop:** Tasks 2 and 3 have a **live verification gate on a real dual-monitor Mac** (macOS Space behavior is empirical and cannot be unit-tested). The controller MUST pause at those gates and have the human run the app and confirm the observed behavior before proceeding.

**Goal:** Make the break popup appear on the user's current Space/display without stealing keyboard focus or switching Spaces (fixes issue #21 on multi-monitor).

**Architecture:** All macOS window manipulation lives in one new isolated, platform-guarded helper `dfyb/macos_window.py` (dispatcher → macOS impl → swappable NSWindow lookup), mirroring `dfyb/activity/sensors.py`. `CountdownPopup` stops calling `focus_force()` and calls `make_nonintrusive(window)` instead; the focus-steal/restore machinery (`_prevent_focus_steal`, `_get_frontmost_app`, AppleScript `activate`) is retired because nothing steals focus anymore.

**Tech Stack:** Python 3, Tkinter/CustomTkinter, pyobjc (AppKit), pytest.

**Spec:** `~/daily/specs/2026-07-02-popup-nonintrusive-design.md`

## Global Constraints

- **Interruption model:** *appear, don't hijack* — the popup floats on top of the current Space with sound/flash; it must NOT activate the app, take keyboard focus, or switch any Space. Once the user deliberately clicks it, activating is acceptable.
- **Platform discipline:** all macOS-only code guarded by `sys.platform == "darwin"` with a graceful fallback; never crash on other platforms. Platform-specific behavior must (a) fall back gracefully, (b) document what other platforms don't get, (c) leave a named seam for a future implementation.
- **No hardcoded magic values** — named constants (this plan adds `FLOATING_WINDOW_LEVEL`).
- **Preferences backward-compatible** — n/a here (no new prefs).
- **Don't regress the popup countdown/snooze/auto-dismiss behavior.**
- **Tests:** `pytest`, files `tests/test_*.py`, run with `.venv/bin/python -m pytest -q`. Existing baseline: **77 passed**.
- **Commits:** conventional-commit summary only, no body, no co-author trailer.

## Repo conventions

- Run everything through the venv: `.venv/bin/python`, `.venv/bin/pip`.
- Repo is under `~/data/projects/` → personal git identity applies automatically. No identity flags.
- `gh` for issues uses the personal config: prefix with `GH_CONFIG_DIR="$HOME/.config/gh-personal"`.
- Push before PR; verify the PR diff + CI test count before claiming done.

## Pre-flight (run once before Task 1)

```bash
cd ~/data/projects/dont_forget_your_breaks
git checkout main && git pull --ff-only origin main
.venv/bin/python -m pytest -q            # baseline: 77 passed
git checkout -b popup-nonintrusive
.venv/bin/python -c "import AppKit; print('pyobjc AppKit present')"   # confirm pyobjc is installed
```
If the AppKit import fails, STOP — the macOS impl needs pyobjc (`.venv/bin/pip install pyobjc`).

---

### Task 1: Isolated macOS window helper `dfyb/macos_window.py`

**Files:**
- Create: `dfyb/macos_window.py`
- Test: `tests/test_macos_window.py`

**Interfaces:**
- Produces: `make_nonintrusive(window) -> None` — configure a Tk `Toplevel` to float on the current Space without activating the app. macOS-only; documented no-op elsewhere. Best-effort: never raises.

This task is pure module creation with the platform-guard/fallback path unit-tested. The actual NSWindow side effects are validated live in Task 2.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_macos_window.py`:
```python
import dfyb.macos_window as macos_window


def test_make_nonintrusive_is_noop_off_macos(monkeypatch):
    monkeypatch.setattr(macos_window.sys, "platform", "linux")
    # Must not touch the window and must not raise on non-macOS.
    macos_window.make_nonintrusive(object())


def test_make_nonintrusive_swallows_failure_on_darwin(monkeypatch):
    monkeypatch.setattr(macos_window.sys, "platform", "darwin")
    # A bad window (no .title()) / missing AppKit must be caught -> no raise.
    macos_window.make_nonintrusive(object())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_macos_window.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'dfyb.macos_window'`

- [ ] **Step 3: Create the module**

Create `dfyb/macos_window.py`:
```python
"""Make a Tk window non-intrusive on macOS: appear on the currently active
Space and float on top WITHOUT activating the app (which is what makes macOS
switch Spaces / steal focus).

Best-effort and platform-guarded, like dfyb/activity/sensors.py: a documented
no-op on non-macOS or on any failure, so callers never need to guard.
"""
import logging
import sys

# NSFloatingWindowLevel — above normal windows, no focus required. Hardcoding
# the numeric value avoids importing AppKit just to read the constant.
FLOATING_WINDOW_LEVEL = 3


def make_nonintrusive(window):
    """Float `window` (a Tk Toplevel) on the active Space without activating
    the app. macOS-only; a documented no-op on other platforms.

    Not implemented on Windows/Linux yet. A future implementation would:
      * Windows: SetWindowPos(HWND_TOPMOST) + WS_EX_NOACTIVATE extended style.
      * Linux/X11: _NET_WM_STATE_ABOVE + _NET_WM_STATE_SKIP_TASKBAR, no focus grab.
    """
    if sys.platform == "darwin":
        _make_nonintrusive_macos(window)


def _make_nonintrusive_macos(window):
    """Set the popup's NSWindow to join all Spaces + float, and order it front
    without activating. Any failure is swallowed (best-effort)."""
    try:
        from AppKit import NSApp, NSWindowCollectionBehaviorCanJoinAllSpaces

        ns_window = _find_nswindow(window, NSApp)
        if ns_window is None:
            return
        ns_window.setCollectionBehavior_(
            ns_window.collectionBehavior() | NSWindowCollectionBehaviorCanJoinAllSpaces
        )
        ns_window.setLevel_(FLOATING_WINDOW_LEVEL)
        ns_window.orderFrontRegardless()  # show on top WITHOUT activating the app
    except Exception:
        logging.debug("make_nonintrusive: no-op (macOS tweak failed)", exc_info=True)


def _find_nswindow(window, ns_app):
    """Locate the NSWindow backing a Tk Toplevel by matching its title.

    Isolated so the (fragile) lookup strategy can be swapped without touching
    callers. Returns None if not found.
    """
    title = window.title()
    for ns_window in ns_app.windows():
        if ns_window.title() == title:
            return ns_window
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_macos_window.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (79 passed)

- [ ] **Step 6: Commit**

```bash
git add dfyb/macos_window.py tests/test_macos_window.py
git commit -m "feat: add macos_window.make_nonintrusive helper with platform fallback"
```

---

### Task 2: Wire into CountdownPopup + LIVE SPIKE GATE

**Files:**
- Modify: `launch.py` (imports; `CountdownPopup` show path)

**Interfaces:**
- Consumes: `make_nonintrusive` from Task 1.

This is the de-risk gate: the *minimal* wiring (drop `focus_force()` on show, call `make_nonintrusive`) proven live BEFORE the larger retirement in Task 3. No unit tests — verified by launching the app on the real dual-monitor rig.

- [ ] **Step 1: Add the import**

In `launch.py`, find the existing line:
```python
from dfyb.timer_lifecycle import timer_should_continue
```
and add immediately after it:
```python
from dfyb.macos_window import make_nonintrusive
```

- [ ] **Step 2: Replace focus_force on show**

In `launch.py`, in `CountdownPopup.__init__`, find:
```python
        # Force focus and request attention
        self.window.lift()
        self.window.focus_force()
        self._request_attention()
```
and replace with:
```python
        # Appear on top of the current Space without activating the app
        # (activating is what makes macOS steal focus / switch Spaces).
        self.window.lift()
        make_nonintrusive(self.window)
        self._request_attention()
```

- [ ] **Step 3: Full suite still green**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (79 passed — no new tests here; nothing regressed)

- [ ] **Step 4: Launch-smoke**

Run: `timeout 6 .venv/bin/python launch.py; echo "exit=$? (124=ran fine)"`
Expected: `exit=124`, no traceback.

- [ ] **Step 5: HUMAN LIVE GATE — dual-monitor + fullscreen**

The human runs the app, sets the Micro Break interval to a few seconds, presses Start, and on a **dual-monitor** setup:
1. Puts an app in native (green-button) fullscreen on the **second** monitor and stays there.
2. Lets a break come due.

**Pass criteria (all must hold):**
- The popup appears on the **currently active** Space/display.
- The **second monitor's Space is NOT switched** (this is the bug being fixed).
- The **foreground app keeps keyboard focus** (you can keep typing).
- The Done/Snooze buttons are usable (note if it takes an extra "activating" click — acceptable per spec; just record it).

**If any fail:** STOP and report. Likely causes: `_find_nswindow` didn't match (title mismatch/timing) or `canJoinAllSpaces` insufficient. Do NOT proceed to Task 3 until the gate passes.

- [ ] **Step 6: Commit (only after the gate passes)**

```bash
git add launch.py
git commit -m "feat: show break popup non-intrusively (no focus/Space steal)"
```

---

### Task 3: Retire the focus-steal machinery

**Files:**
- Modify: `launch.py` (`CountdownPopup`: `__init__`, `close`, remove `_get_frontmost_app` + `_prevent_focus_steal`, strip `focus_force` from `bring_to_user` + `_bring_to_attention`)

With focus no longer stolen, the restore machinery (which used AppleScript `activate` — the *other* Space-switcher) is dead weight. Remove it. Verified by launch + a second human live check.

- [ ] **Step 1: Drop the previous-app capture**

In `launch.py`, `CountdownPopup.__init__`, find:
```python
        self._previous_app = self._get_frontmost_app()  # Remember active app
```
and delete that line.

- [ ] **Step 2: Simplify `close()`**

In `launch.py`, find:
```python
        try:
            self.window.withdraw()
        except Exception:
            pass
        self._prevent_focus_steal()  # Call before destroy to prevent focus transfer
        self.window.destroy()
        self._prevent_focus_steal()  # Call again after to ensure app is deactivated
```
and replace with:
```python
        try:
            self.window.withdraw()
        except Exception:
            pass
        self.window.destroy()
```

- [ ] **Step 3: Remove the two dead methods**

In `launch.py`, delete the entire `_get_frontmost_app` method and the entire `_prevent_focus_steal` method (they are no longer referenced after Steps 1-2).

- [ ] **Step 4: Strip `focus_force` from `bring_to_user`**

In `launch.py`, in `bring_to_user`, find:
```python
            self.window.lift()
            self.window.focus_force()
            self.window.attributes('-topmost', True)
```
and replace with:
```python
            self.window.lift()
            make_nonintrusive(self.window)
            self.window.attributes('-topmost', True)
```

- [ ] **Step 5: Strip `focus_force` from `_bring_to_attention`**

In `launch.py`, in `_bring_to_attention`, find:
```python
            self.window.lift()
            self.window.focus_force()
            self.window.attributes('-topmost', True)
            self._flash_button()
```
and replace with:
```python
            self.window.lift()
            make_nonintrusive(self.window)
            self.window.attributes('-topmost', True)
            self._flash_button()
```

- [ ] **Step 6: Confirm no stray references remain**

Run: `grep -n "focus_force\|_prevent_focus_steal\|_get_frontmost_app\|_previous_app" launch.py`
Expected: **no matches** (all removed).

- [ ] **Step 7: Full suite + launch-smoke**

Run: `.venv/bin/python -m pytest -q` → Expected: PASS (79 passed)
Run: `timeout 6 .venv/bin/python launch.py; echo "exit=$? (124=ran fine)"` → Expected: `exit=124`, no traceback.

- [ ] **Step 8: HUMAN LIVE GATE — close/snooze behavior**

The human triggers a break and confirms:
- Closing the popup (Done) does NOT switch Spaces or yank focus (previously the AppleScript `activate` could).
- Snooze and auto-dismiss still work; the countdown/progress is unaffected.

**If any fail:** STOP and report.

- [ ] **Step 9: Commit (after the gate passes)**

```bash
git add launch.py
git commit -m "refactor: retire popup focus-steal machinery (no longer needed)"
```

---

### Task 4: Record the platform-specific-change convention

**Files:**
- Modify: `CLAUDE.md` (project-local, gitignored — extend the existing rule)
- Create: `docs/conventions.md` (committed)

- [ ] **Step 1: Extend the project CLAUDE.md rule**

In `CLAUDE.md`, find the development rule that begins:
```
- **Keep platform branches explicit.** Guard macOS-only code with `sys.platform == "darwin"` and provide a graceful fallback; never let a macOS-only call crash on Windows/Linux.
```
and append to that same bullet:
```
 When you add platform-specific behavior: (a) provide a graceful fallback, (b) document what other platforms don't get, (c) leave a named seam for a future implementation (see `dfyb/macos_window.py` and `dfyb/activity/sensors.py`). See `docs/conventions.md`.
```

- [ ] **Step 2: Create the committed conventions doc**

Create `docs/conventions.md`:
```markdown
# Development Conventions

## Platform-specific behavior (macOS-first)

This app is macOS-first; cross-platform is out of scope. When you add
platform-specific behavior:

1. **Graceful fallback** — guard with `sys.platform == "darwin"` (or the
   relevant platform) and degrade to a safe no-op/alternative; never let a
   platform-only call crash elsewhere.
2. **Document the gap** — state in the code what other platforms don't get.
3. **Leave a named seam** — structure it as a dispatcher so a future platform
   implementation can slot in, and name the concrete API a future impl would
   use.

Reference implementations: `dfyb/macos_window.py`, `dfyb/activity/sensors.py`.
```

- [ ] **Step 3: Commit**

```bash
git add docs/conventions.md CLAUDE.md
git commit -m "docs: record platform-specific-change convention"
```
Note: `CLAUDE.md` is gitignored, so only `docs/conventions.md` will actually be committed — that's expected; the CLAUDE.md edit is local guidance.

---

### Task 5: Roadmap note + follow-up issues

**Files:**
- Modify: `docs/specs/2026-06-11-roadmap-design.md` (append a note under Phase 4)

- [ ] **Step 1: Add the roadmap note**

In `docs/specs/2026-06-11-roadmap-design.md`, under the **Phase 4 — Delight & invisible** section, add a bullet:
```
- **Break presentation & barge-in UX** — entrance animation, how the popup grabs attention without hijacking, dismiss/snooze feel. (Follows the non-intrusive popup fix, issue #21.)
```

- [ ] **Step 2: Commit the roadmap note**

```bash
git add docs/specs/2026-06-11-roadmap-design.md
git commit -m "docs: note break presentation/barge-in UX in Phase 4 roadmap"
```

- [ ] **Step 3: File the two follow-up GitHub issues (personal gh)**

```bash
GH_CONFIG_DIR="$HOME/.config/gh-personal" gh issue create \
  --title "Configurable: defer breaks during fullscreen (opt to be reminded even in fullscreen)" \
  --body "Today fullscreen always defers. Make it a preference (default: defer on). A pref gating the scheduler's fullscreen-defer. Enabled cleanly by #21 (the non-intrusive popup appears on the fullscreen Space instead of switching Spaces)."

GH_CONFIG_DIR="$HOME/.config/gh-personal" gh issue create \
  --title "Break presentation & barge-in UX polish (animation, attention-without-hijack)" \
  --body "Roadmap Phase 4. Entrance animation, how the popup grabs attention without hijacking, dismiss/snooze feel. Follows the non-intrusive popup fix (#21)."
```
Record the two issue URLs in the PR description.

---

## Definition of done

- `dfyb/macos_window.py` exists (dispatcher + macOS impl + isolated `_find_nswindow`), unit-tested for the no-op/fallback path.
- `CountdownPopup` shows via `make_nonintrusive` (no `focus_force`); `_prevent_focus_steal` / `_get_frontmost_app` / `_previous_app` removed; `grep` finds no stray references.
- `pytest -q` passes (expected **79**).
- **Human live gates passed** on a dual-monitor + fullscreen setup: popup on the active Space, second monitor's Space untouched, foreground keeps focus, Done/Snooze usable, close doesn't switch Spaces.
- Convention recorded in `CLAUDE.md` + committed `docs/conventions.md`.
- Roadmap note added; both follow-up issues filed.

## Wrap-up

- Push: `git push -u origin popup-nonintrusive`.
- Open a PR (base `main`) with `GH_CONFIG_DIR="$HOME/.config/gh-personal" gh pr create`. Include the two follow-up issue URLs. Verify CI (79 tests).

## Known limitations carried forward

- `_find_nswindow` matches by window title; if two on-screen windows share a title the first match wins. Acceptable for the break popup (unique title); revisit if it proves fragile.
- First-click-on-Done may activate the app before the button press (accepted per spec); only address with `acceptsFirstMouse` handling if it proves annoying.

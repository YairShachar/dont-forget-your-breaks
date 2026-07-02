# Don't Forget Your Breaks — Product Roadmap & Architecture Design

**Date:** 2026-06-11
**Author:** Yair Shachar (with Claude)
**Repo:** https://github.com/YairShachar/dont-forget-your-breaks
**Status:** Approved vision & roadmap; Phase 0/1 to be detailed into an implementation plan.

---

## 1. Vision

Make **a break reminder so good you'd keep it on, recommend it, and miss it if it were gone.**

Most break apps get uninstalled within a week, and almost always for the same reason: **they nag at the wrong time** — mid-flow, mid-meeting, mid-sentence — so the user starts skipping, then resents it, then quits. The free competitors (Stretchly, Time Out, BreakTimer) compete on features; they lose on timing.

Our thesis: **the killer feature is earning the interruption** — showing up exactly when a break helps and *never* when it would wreck focus. Everything else is in service of that.

### The five pillars (all in scope)
1. **Perfect timing** — adaptive, context-aware nudges; never a dumb fixed timer.
2. **Restorative breaks** — the break itself is genuinely good (breathing, eye-rest, stretches).
3. **Delight & craft** — premium, calm, beautiful; satisfying micro-interactions.
4. **Invisible & effortless** — zero-config, anti-nag, stays out of the way.
5. **Analysis & trend dashboards** — meaningful insight into focus/break patterns.

---

## 2. The unifying architectural insight

**Smart timing and trend dashboards are the same data viewed two ways.**

To decide *when* to nudge, the app must continuously sense context — idle, typing/flow, in a meeting, fullscreen. Every such signal, plus every break taken/skipped/snoozed, is an **event**. Feed the event stream into a scheduler → **perfect timing**. Feed the same stream into charts → **analysis & trends**. One core, two payoffs.

```
                    ┌─────────────────────────┐
   sensors  ──────► │     ACTIVITY CORE       │ ◄── records every event
 (idle, app,        │  signals + event log    │
  meeting,          └───────────┬─────────────┘
  fullscreen)                   │
            ┌───────────────────┼───────────────────┐
            ▼                   ▼                   ▼
     ⏱ SCHEDULER         📊 INSIGHTS          🧘 BREAK EXPERIENCE
   "earn the             trends, streaks,     guided breathing,
    interruption"        usage dashboards     eye-rest, stretches
            │                                       │
            └──────────────► ✨ DELIGHT + 🫥 INVISIBLE ◄──────┘
              (philosophy applied across everything, not a feature)
```

- **Perfect timing** = Scheduler reading the Activity Core.
- **Analysis & trends** = Insights reading the same event log.
- **Restorative breaks** = the Break Experience layer.
- **Delight & Invisible** = philosophy applied everywhere; Phase 4 is the dedicated polish pass, not the only place craft happens.

---

## 3. Current state (diagnosis)

**Strengths**
- Ships and iterates (v1.0.13) with a real distribution pipeline: DMG + Homebrew cask + GitHub releases + in-app self-update checker.
- Thoughtful UX already present: design-token system, focus-steal prevention, reduced-motion support, single-instance locking.

**Structural risks**
- **One 1,650-line `launch.py`** doing everything (UI, timing, sound, updates, persistence). Hard to test, hard to extend.
- **Zero tests, zero CI** — every release is hand-verified.
- **macOS-only in practice** — Windows/Linux are a beep/bell fallback. (Acceptable: this roadmap stays macOS-first; cross-platform is explicitly out of scope.)

**Product signals (open issues):** a clear pull toward insight (#6 stats, #9 dashboard), engagement/content (#7 quotes, #8 activities), and UX refinement (#5 simplify UI, #10 break-now). One bug (#2 focus) likely already fixed by recent commits.

---

## 4. Technology decision

**Stay on Python + Tkinter/CustomTkinter; modularize in place. No rewrite.**

Rationale: reset away from the monetization/cross-platform path; the goal is a great macOS app. Python can do everything the vision needs on macOS:
- **Idle detection** via Quartz `CGEventSourceSecondsSinceLastEventType` (pyobjc).
- **Active-app / fullscreen / meeting awareness** via `NSWorkspace` and window/space queries (pyobjc).
- Existing CustomTkinter UI and animation primitives are sufficient for Phases 0–3; a delight pass (Phase 4) will test CTk's ceiling and we revisit only if it blocks us.

New runtime dependency anticipated: **pyobjc** (for the macOS sensors). Dev dependencies: **pytest** (tests), keep **pyinstaller** (build).

---

## 5. Architecture target (post-Phase 0)

Split the monolith into focused, independently testable modules. Proposed package layout (names indicative):

| Module | Responsibility | Depends on |
|--------|----------------|------------|
| `activity/` | Sensors (idle, active-app, fullscreen, meeting) + **event log** (append-only store of signals & break events) | macOS APIs (pyobjc), persistence |
| `scheduler/` | Decides *when* a break is due by consuming the event stream; "earn the interruption" rules | activity |
| `breaks/` | Break model (`BreakConfig`), break content/experiences | — |
| `sound/` | Sound playback abstraction (currently macOS `afplay`) | — |
| `persistence/` | Read/write prefs + event log to disk (backward-compatible) | — |
| `updater/` | Version check + self-update | — |
| `ui/` | CustomTkinter screens, popup, settings, dashboard | all above via interfaces |
| `app.py` | Composition root / entry point | all |

**Design rules** (carried into CLAUDE.md):
- Pure logic separated from Tk widgets so logic is unit-testable without a display.
- Sensors and scheduler communicate through the event log / well-defined interfaces, not direct calls.
- Network calls (update check, any future content fetch) are mockable.
- No hardcoded visual values — design tokens only.
- Preferences remain backward-compatible (always `.get(key, default)`).

---

## 6. Phased roadmap

Each phase maps to a **GitHub Milestone**; bullets become **issues**.

### Phase 0 — Activity Core foundation (enabler)
*No user-visible change; everything after gets ~3× easier.*
- Carve `launch.py` into the modules in §5.
- Introduce the **event log** abstraction (append-only, persisted) — the spine.
- Stand up **pytest** + **GitHub Actions CI** (headless: lint + pure-logic tests).
- Add `requirements.txt` / `requirements-dev.txt` (customtkinter, pyobjc, pyinstaller, pytest).
- Verify & close the **#2 focus** bug with a regression test.
- Fix README's missing `customtkinter` dependency.

### Phase 1 — Perfect timing ⭐ (the heart)
- macOS **idle detection**: defer/reset the timer when the user is already away from the keyboard.
- **Active-app / fullscreen awareness**: suppress breaks during fullscreen (presentations, video).
- **Meeting awareness**: suppress/defer during video calls (Zoom/Meet/Teams/FaceTime detection).
- **Adaptive deferral**: "you're mid-flow — wait for a natural pause" rather than interrupting.
- Quick win **#10 "Break now"** (manual trigger / right-click).
- Each behavior emits events into the Activity Core (fuel for Phase 3).

### Phase 2 — Restorative breaks
- Guided **breathing** exercise in the break popup.
- **Eye-rest** (20-20-20) guidance.
- **Micro-stretch** prompts (#8).
- Optional **inspirational line** per break (#7).
- Break experiences are content-driven and testable independently of timing.

### Phase 3 — Insights & trends 📊
*Meaningful precisely because Phases 1–2 have been logging events.*
- Breaks-taken trends over time; streaks.
- Focus/break balance; **break-usage %** (how much of each break was actually used) (#9).
- History view (#6).
- All computed from the event log; no new data source.

### Phase 4 — Delight & invisible (finishing pass)
- Menu-bar-first presence.
- **Simplify main UI** — move settings behind a Settings button (#5).
- Zero-config sensible defaults; anti-nag gentleness tuning.
- Polish sweep: animation, sound design, visuals.
- **Break presentation & barge-in UX** — entrance animation, how the popup grabs attention without hijacking focus (zero-focus-grab), where it appears on multi-monitor, dismiss/snooze feel. (Follows the non-intrusive popup fix, issue #21.)

**Threaded principle:** every phase's definition-of-done includes "feels calm and gets out of the way." Phase 4 is the dedicated craft pass, not the only one. **Behaviors should be configurable** — user-facing behaviors (e.g. whether breaks defer during fullscreen) are preferences with sensible defaults, not hardcoded policy.

---

## 7. Open-issue mapping

| Issue | Phase |
|-------|-------|
| #2 Break popup focus disruption (bug) | Phase 0 (verify/close + regression test) |
| #10 "Take break now" | Phase 1 |
| #8 Customizable break activities | Phase 2 |
| #7 Inspirational quotes | Phase 2 |
| #6 Break statistics & history | Phase 3 |
| #9 Dashboard: breaks taken & % used | Phase 3 |
| #5 Simplify main UI | Phase 4 |

No open issue is orphaned.

---

## 8. Tracking

- **Tracker:** GitHub Issues + Milestones in `YairShachar/dont-forget-your-breaks` (the personal repo — **not** the company Jira).
- **Milestones:** one per phase (Phase 0–4).
- Existing issues get assigned to their mapped milestone; new issues created for the work not yet captured (sensors, event log, CI, modularization, break experiences, dashboard).
- gh access is isolated via a dedicated `GH_CONFIG_DIR=~/.config/gh-personal` (YairShachar), kept fully separate from the work gh config.

---

## 9. Out of scope (explicit)

- Cross-platform (Windows/Linux first-class) — macOS-first only.
- Monetization, accounts, cloud sync, subscriptions, B2B — dropped.
- Framework rewrite (Electron/Tauri/Flutter) — staying on Python/CTk.

---

## 10. Next step

Detail **Phase 0** (and the first slice of **Phase 1**) into an implementation plan via the writing-plans skill, then execute.

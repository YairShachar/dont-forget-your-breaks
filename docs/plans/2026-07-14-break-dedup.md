# Break dedup (no stacking) — Implementation Plan (#50)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A break has at most one instance in play (showing ∪ queued ∪ pending-snoozed); a new trigger for an in-play break is coalesced. "Break now" overrides a pending snooze.

**Spec:** `~/daily/specs/2026-07-14-break-dedup-design.md`

## Global Constraints

- Dedup by break **name**; "in play" = active popup ∪ break_queue ∪ `_pending_snoozes`.
- No engine change (the `active_popup` guard + #45 already stop scheduler auto-repeat).
- Pure predicate is unit-tested; app wiring is human-verified.

---

### Task 1: Pure `break_in_play` predicate

- [x] TDD `dfyb/scheduler/dedup.py` + `tests/test_dedup.py`:
  `break_in_play(name, active_name, queued_names, pending_names)` →
  `name == active_name or name in queued_names or name in pending_names`.
  5 tests (nothing / showing / queued / pending / other-names).

### Task 2: App wiring (`launch.py`)

- [x] Import `break_in_play`.
- [x] `__init__`: `self._active_break_name = None`.
- [x] `_process_break_queue`: set `self._active_break_name = break_data['name']`
  right before creating the popup.
- [x] `on_popup_close` / `on_snooze`: clear `self._active_break_name = None`
  (force-close at the stop path is covered via the popup's `on_close`).
- [x] `trigger_break`: compute queued+pending names; `break_in_play(...)` → skip
  (log "skip duplicate break … already in play").
- [x] `break_now`: cancel any pending snooze for the break first (manual
  override), then reset_timer + trigger_break.
- [x] `_requeue_break`: after logging the return, skip the append if the break is
  already showing/queued (coalesce).

### Task 3: Manual verification

- [ ] Double "Break now" on Normal Break → one popup cycle (2nd coalesced).
- [ ] Snooze Normal Break (row shows) → "Break now" on it → shows immediately,
  row disappears, `break_snooze_cancelled` logged.
- [ ] Snooze → normal return (no other instance) → shows once (no regression).
- [ ] Two different breaks still queue/show independently.

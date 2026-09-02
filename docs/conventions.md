# Development Conventions

## Platform-specific behavior (macOS-first)

This app is macOS-first; cross-platform is out of scope. When you add
platform-specific behavior:

1. **Graceful fallback** — guard with `sys.platform == "darwin"` (or the
   relevant platform) and degrade to a safe no-op/alternative; never let a
   platform-only call crash elsewhere.
2. **Document the gap** — state in the code what other platforms don't get.
3. **Leave a named seam** — structure it as a dispatcher and name the concrete
   API a future platform implementation would use, so it can slot in later.

Reference implementations: `dfyb/macos_window.py`, `dfyb/activity/sensors.py`.

## Make behaviors configurable

User-facing behaviors should be **user preferences with sensible defaults**, not
hardcoded policy. If a behavior changes what the user experiences — whether
breaks defer during fullscreen, sounds, timings, and other "cool" features —
prefer a preference (read with a `.get(key, default)` fallback for backward
compatibility) over a fixed behavior. Zero-config defaults are the goal, but the
user should be able to turn a behavior off.

## Every feature is loggable and self-documenting

A feature that leaves no trace can never be analyzed. Every user-visible
behavior — and every automatic decision the app makes on the user's behalf —
must emit an event to the event log (`dfyb/activity/event_log.py`), because the
dashboard/recap surfaces (#52, #61, #9) can only ever show what we recorded, and
history cannot be backfilled.

When you add a feature:

1. **Name an event constant** in `event_log.py` with an inline comment saying
   what the event means and when it fires. The constant list *is* the schema
   documentation — a reader must understand the event without reading the
   emitter.
2. **Log the decision, not just the outcome.** If the app deferred, suppressed,
   auto-selected or skipped something, record *why* (`{"reason": ...}`) and the
   inputs that drove it, so a future dashboard can explain the behavior back to
   the user rather than just count it.
3. **Include enough dimensions to slice by later** — the break name, the source
   (scheduled / manual), the app involved, durations. Adding a field later
   cannot recover the events already written without it.
4. **Bump `SCHEMA_VERSION`** if you change the meaning or shape of an existing
   event rather than adding a new one.
5. **Pair it with a preference** — see "Make behaviors configurable" above. A
   feature that is logged but not configurable is only half done; the two rules
   apply together to every feature.

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

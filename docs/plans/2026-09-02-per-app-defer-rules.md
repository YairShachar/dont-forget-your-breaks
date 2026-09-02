# Per-App Deferral Exceptions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Attribute the mic and fullscreen deferral signals to the specific app causing them, say so in the UI ("Zoom is using your microphone"), and let the user ignore an app per signal — shipping correct with zero configuration via a built-in ignore list.

**Architecture:** A new pure policy module (`dfyb/activity/app_rules.py`) holds the ignore-list algebra. `sensors.py` gains attribution for both signals — process-level CoreAudio enumeration for the mic, covering-window ownership for fullscreen — each with an explicit "unattributable" (`None`) result that degrades to today's behavior. `read_context()` filters holders through the ignore lists and returns app names alongside the existing booleans; the scheduler's `decide()` is untouched. The UI and event log read the names.

**Tech Stack:** Python 3.14, pyobjc (CoreAudio, AppKit, Quartz), ctypes/libproc, CustomTkinter, pytest.

**Spec:** `/Users/yairs/data/grandapp/data/daily/2026-09-02/specs/2026-09-02-per-app-defer-rules-design.md`

## Global Constraints

- **macOS-first with a graceful fallback.** Guard every platform call with `sys.platform == "darwin"`, degrade to a safe value, document what other platforms don't get, and leave a named seam (`docs/conventions.md`).
- **No hardcoded values.** Colors, sizes, spacing, durations go in the `launch.py` CONFIGURATION block as named constants; pure-module constants live at the top of their module (precedent: `DEFER_GRACE_TICKS` in `sensors.py`).
- **Preferences are backward-compatible.** Every new pref is read with `.get(key, default)`.
- **Every feature is loggable, self-documenting and configurable** (`docs/conventions.md`, added 2026-09-02): a named event constant with an inline comment, the decision's *reason* logged, enough dimensions to slice by later, and a pref with a sensible default.
- **The `None` vs `[]` contract is load-bearing.** For both signals, `None` means "could not ask" (fall back to the raw boolean) and `[]` means "asked, nobody there" (not busy). Never conflate them.
- **`covers_any_display()` geometry is frozen.** All twelve existing cases in `tests/test_sensors.py` must keep passing unchanged; attribution wraps it, never modifies it.
- **Run tests as:** `DFYB_DEV=1 .venv/bin/python -m pytest -q` (never touch the real prefs/lock/events).
- **Commit messages are a summary of changes only** — no `Co-Authored-By` trailer.
- Issues in play: **#40** (mic detection accuracy — closed by Task 6), **#28** (per-app rules table — stays open; `app_rules.py` is its seam).

---

### Task 1: Pure policy module — the ignore-list algebra

**Files:**
- Create: `dfyb/activity/app_rules.py`
- Test: `tests/test_app_rules.py`
- Modify: `docs/conventions.md`, `CLAUDE.md` (already edited on disk — commit them here)

**Interfaces:**
- Consumes: nothing.
- Produces: `MIC`, `FULLSCREEN`, `DEFAULT_MIC_IGNORED_APPS: list[dict]`, `DEFAULT_FULLSCREEN_IGNORED_APPS: list[dict]`, `normalize_app(bundle_id, name) -> str`, `effective_ignores(builtins, user_added, user_removed) -> set[str]`, `surviving_holders(holders, ignored) -> list[tuple]`, `primary_holder(holders) -> tuple | None`, `holder_ref(holder) -> dict`. A **holder** is the 3-tuple `(pid: int, bundle_id: str | None, name: str)` and is the single shape used for BOTH mic holders and fullscreen owners.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_app_rules.py`:

```python
import dfyb.activity.app_rules as rules

SOUND = (45648, "com.apple.Sound-Settings.extension", "Sound")
ZOOM = (700, "us.zoom.xos", "zoom.us")
DAEMON = (4363, None, "corespeechd")


def test_normalize_prefers_bundle_id_and_lowercases():
    assert rules.normalize_app("US.Zoom.xos", "zoom.us") == "us.zoom.xos"


def test_normalize_falls_back_to_name_when_no_bundle_id():
    assert rules.normalize_app(None, "corespeechd") == "corespeechd"


def test_normalize_handles_missing_everything():
    assert rules.normalize_app(None, None) == ""


def test_effective_ignores_includes_builtins():
    keys = rules.effective_ignores(rules.DEFAULT_MIC_IGNORED_APPS, [], [])
    assert "com.apple.sound-settings.extension" in keys


def test_effective_ignores_drops_a_removed_builtin():
    keys = rules.effective_ignores(
        rules.DEFAULT_MIC_IGNORED_APPS, [], ["com.apple.Sound-Settings.extension"])
    assert "com.apple.sound-settings.extension" not in keys


def test_effective_ignores_adds_user_entries():
    keys = rules.effective_ignores([], [{"id": "us.zoom.xos", "name": "Zoom"}], [])
    assert keys == {"us.zoom.xos"}


def test_user_addition_wins_over_removal_of_the_same_key():
    # Precedence is explicit so it can never be ambiguous: if the user both
    # un-ignored a built-in and added it back, it ends up ignored.
    keys = rules.effective_ignores(
        rules.DEFAULT_MIC_IGNORED_APPS,
        [{"id": "com.apple.controlcenter", "name": "Control Center"}],
        ["com.apple.controlcenter"])
    assert "com.apple.controlcenter" in keys


def test_surviving_holders_keeps_a_real_call_alongside_an_ignored_holder():
    ignored = rules.effective_ignores(rules.DEFAULT_MIC_IGNORED_APPS, [], [])
    assert rules.surviving_holders([SOUND, ZOOM], ignored) == [ZOOM]


def test_surviving_holders_empty_when_only_ignored_holders():
    ignored = rules.effective_ignores(rules.DEFAULT_MIC_IGNORED_APPS, [], [])
    assert rules.surviving_holders([SOUND], ignored) == []


def test_primary_holder_prefers_a_bundled_app_over_a_bare_daemon():
    assert rules.primary_holder([DAEMON, ZOOM]) == ZOOM


def test_primary_holder_breaks_ties_by_lowest_pid():
    other = (200, "com.apple.facetime", "FaceTime")
    assert rules.primary_holder([ZOOM, other]) == other


def test_primary_holder_of_nothing_is_none():
    assert rules.primary_holder([]) is None


def test_holder_ref_is_the_json_shape_events_and_prefs_store():
    assert rules.holder_ref(ZOOM) == {"id": "us.zoom.xos", "name": "zoom.us"}


def test_dfyb_ignores_itself_so_it_never_defers_on_its_own_audio():
    keys = rules.effective_ignores(rules.DEFAULT_MIC_IGNORED_APPS, [], [])
    assert "com.yairs.dontforgetyourbreaks" in keys


def test_fullscreen_ships_with_no_ignores():
    assert rules.DEFAULT_FULLSCREEN_IGNORED_APPS == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `DFYB_DEV=1 .venv/bin/python -m pytest tests/test_app_rules.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'dfyb.activity.app_rules'`

- [ ] **Step 3: Write the module**

Create `dfyb/activity/app_rules.py`:

```python
"""Per-app exceptions to the deferral signals (mic in use, fullscreen).

Pure policy — no Tk, no CoreAudio, no I/O — so it is unit-tested headlessly.
Two flat lists (one per signal) share this one helper deliberately: it is the
seam that issue #28's richer per-app rules table can grow from later without a
preferences migration.

A *holder* is the tuple `(pid, bundle_id, name)` and is the single shape used
for both mic holders and fullscreen window owners, so both signals filter
through the same code.
"""

# Signal names — used as the `signal` dimension on the ignore-change events.
MIC = "mic"
FULLSCREEN = "fullscreen"

# Processes that hold the audio INPUT without implying a call, so they must never
# defer a break. Shipped as code rather than copied into prefs, so a release can
# correct or extend the list without stomping the user's edits; the user can
# still un-ignore any of them (see `effective_ignores`).
DEFAULT_MIC_IGNORED_APPS = [
    # The System Settings > Sound pane opens the input to drive its level meter,
    # and its .appex can outlive the closed window (confirmed 2026-09-01: 18h of
    # false "in a call"). Verified bundle id from the .appex Info.plist.
    {"id": "com.apple.Sound-Settings.extension", "name": "Sound (System Settings)"},
    # Holds the input while the Sound module in Control Center is open.
    {"id": "com.apple.controlcenter", "name": "Control Center"},
    # Siri / dictation daemon — speech, but never a meeting. No bundle id.
    {"id": None, "name": "corespeechd"},
    # Never defer on our own audio (break sounds, future features).
    {"id": "com.yairs.dontforgetyourbreaks", "name": "Dont Forget Your Breaks"},
]

# Empty on purpose: today's behavior is that ANY fullscreen app defers.
DEFAULT_FULLSCREEN_IGNORED_APPS = []


def normalize_app(bundle_id, name):
    """Canonical match key for an app: its bundle id lowercased when present,
    else its display name lowercased. Stable across launches and PID changes."""
    return (bundle_id or name or "").strip().lower()


def effective_ignores(builtins, user_added, user_removed):
    """The set of keys actually ignored for one signal.

    `builtins` and `user_added` are lists of `{"id", "name"}` refs; `user_removed`
    is a list of keys the user un-ignored. Built-ins minus removals, plus the
    user's own additions — so a user addition WINS over a removal of the same key.
    """
    removed = {key.strip().lower() for key in user_removed if key}
    keys = {normalize_app(app.get("id"), app.get("name")) for app in builtins}
    keys -= removed
    keys |= {normalize_app(app.get("id"), app.get("name")) for app in user_added}
    return {key for key in keys if key}


def surviving_holders(holders, ignored):
    """The holders whose key is NOT ignored — the ones that still mean 'busy'."""
    return [h for h in holders if normalize_app(h[1], h[2]) not in ignored]


def primary_holder(holders):
    """Which holder to name in the UI when several qualify: one carrying a bundle
    id (a real app) before a bare daemon, then the lowest pid. Deterministic so
    the chip never flickers between two names. None for an empty list."""
    if not holders:
        return None
    return sorted(holders, key=lambda h: (h[1] is None, h[0]))[0]


def holder_ref(holder):
    """The `{"id", "name"}` JSON shape stored in prefs and logged on events."""
    _pid, bundle_id, name = holder
    return {"id": bundle_id, "name": name}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `DFYB_DEV=1 .venv/bin/python -m pytest tests/test_app_rules.py -q`
Expected: PASS (15 tests)

- [ ] **Step 5: Run the whole suite — nothing else may move**

Run: `DFYB_DEV=1 .venv/bin/python -m pytest -q`
Expected: PASS, same count as before plus 15.

- [ ] **Step 6: Commit (includes the convention docs edited on 2026-09-02)**

```bash
git add dfyb/activity/app_rules.py tests/test_app_rules.py docs/conventions.md CLAUDE.md
git commit -m "Per-app deferral exceptions: pure ignore-list policy module + the 'every feature is loggable and self-documenting' convention"
```

---

### Task 2: Mic attribution — who is holding the microphone

**Files:**
- Modify: `dfyb/activity/sensors.py` (add after `microphone_in_use()`, ~line 232)
- Test: `tests/test_sensors.py`

**Interfaces:**
- Consumes: nothing from Task 1 (pure detection).
- Produces: `mic_input_processes() -> list[(pid, bundle_id, name)] | None` — `None` means attribution is UNAVAILABLE (non-macOS, macOS < 14, or failure); `[]` means asked and nobody holds the input. Also `_app_identity(pid) -> (bundle_id | None, name)`.

**Background the implementer needs:** macOS 14 added per-process CoreAudio objects. `kAudioHardwarePropertyProcessObjectList` (`'prs#'`) on `kAudioObjectSystemObject` lists them; each has `kAudioProcessPropertyPID` (`'ppid'`) and `kAudioProcessPropertyIsRunningInput` (`'piri'`). pyobjc does not export these constants by name, so they are built from their four-character codes exactly as `AudioHardware.h` defines them. This was verified live on macOS 26 during the 2026-09-01 incident — it named `Sound.appex` as the sole holder. `NSRunningApplication.runningApplicationWithProcessIdentifier_()` returns **None** for non-GUI processes (verified), so identity falls back to `libproc.proc_pidpath` plus the enclosing bundle's `Info.plist`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sensors.py`:

```python
# --- mic attribution: WHO is holding the input (#40) ---

def _fake_coreaudio_processes(process_objects, running_input, pids, list_ok=True):
    """Fake CoreAudio exposing the macOS 14+ process-object properties.
    `running_input` / `pids` map a process object id -> its property value."""
    fake = types.ModuleType("CoreAudio")
    fake.kAudioObjectSystemObject = 1
    fake.kAudioObjectPropertyScopeGlobal = 0x676C6F62
    fake.kAudioObjectPropertyScopeInput = 0x696E7074
    fake.kAudioObjectPropertyElementMain = 0
    fake.AudioObjectPropertyAddress = lambda sel, scope, elem: (sel, scope, elem)

    def get_size(obj, addr, qsize, qdata, out):
        if not list_ok:
            return (-1, 0)
        return (0, len(process_objects) * 4)

    def get_data(obj, addr, qsize, qdata, size, out):
        sel = addr[0]
        if obj == fake.kAudioObjectSystemObject:
            return (0, size, struct.pack("%dI" % len(process_objects), *process_objects))
        table = running_input if sel == sensors.PROCESS_IS_RUNNING_INPUT else pids
        return (0, 4, struct.pack("I", table.get(obj, 0)))

    fake.AudioObjectGetPropertyDataSize = get_size
    fake.AudioObjectGetPropertyData = get_data
    return fake


def _install_mic_process_fakes(monkeypatch, fake_ca, identities):
    monkeypatch.setattr(sensors.sys, "platform", "darwin")
    monkeypatch.setitem(sys.modules, "CoreAudio", fake_ca)
    monkeypatch.setitem(sys.modules, "objc", types.SimpleNamespace(NULL=None))
    monkeypatch.setattr(sensors, "_app_identity", lambda pid: identities[pid])


def test_mic_input_processes_names_the_holder(monkeypatch):
    fake = _fake_coreaudio_processes(
        process_objects=[10, 11], running_input={10: 1, 11: 0}, pids={10: 700, 11: 800})
    _install_mic_process_fakes(monkeypatch, fake, {700: ("us.zoom.xos", "zoom.us")})
    assert sensors.mic_input_processes() == [(700, "us.zoom.xos", "zoom.us")]


def test_mic_input_processes_empty_when_nobody_holds_input(monkeypatch):
    fake = _fake_coreaudio_processes(
        process_objects=[10], running_input={10: 0}, pids={10: 700})
    _install_mic_process_fakes(monkeypatch, fake, {})
    # [] (asked, nobody there) — NOT None, which would mean "couldn't ask".
    assert sensors.mic_input_processes() == []


def test_mic_input_processes_none_when_api_unavailable(monkeypatch):
    fake = _fake_coreaudio_processes([], {}, {}, list_ok=False)
    _install_mic_process_fakes(monkeypatch, fake, {})
    assert sensors.mic_input_processes() is None


def test_mic_input_processes_none_on_exception(monkeypatch):
    fake = _fake_coreaudio_processes([10], {10: 1}, {10: 700})
    def boom(*a, **k):
        raise RuntimeError("coreaudio boom")
    fake.AudioObjectGetPropertyDataSize = boom
    _install_mic_process_fakes(monkeypatch, fake, {})
    assert sensors.mic_input_processes() is None


def test_mic_input_processes_none_off_macos(monkeypatch):
    monkeypatch.setattr(sensors.sys, "platform", "linux")
    assert sensors.mic_input_processes() is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `DFYB_DEV=1 .venv/bin/python -m pytest tests/test_sensors.py -k mic_input -q`
Expected: FAIL — `AttributeError: module 'dfyb.activity.sensors' has no attribute 'PROCESS_IS_RUNNING_INPUT'`

- [ ] **Step 3: Write the implementation**

Add near the top of `dfyb/activity/sensors.py`, below `DEFER_GRACE_TICKS`:

```python
def _fourcc(code):
    """CoreAudio selectors are four-character codes packed big-endian."""
    return struct.unpack(">I", code.encode())[0]


# Per-process CoreAudio selectors (macOS 14+). pyobjc's CoreAudio module does not
# export these as named constants, so they are built from the four-character codes
# exactly as AudioHardware.h defines them.
PROCESS_OBJECT_LIST = _fourcc("prs#")        # kAudioHardwarePropertyProcessObjectList
PROCESS_PID = _fourcc("ppid")                # kAudioProcessPropertyPID
PROCESS_IS_RUNNING_INPUT = _fourcc("piri")   # kAudioProcessPropertyIsRunningInput
# Max bytes for libproc's executable-path buffer (PROC_PIDPATHINFO_MAXSIZE).
PROC_PATH_MAX = 4096
```

Add after `microphone_in_use()`:

```python
def _bundle_identity_from_path(exe_path):
    """(bundle_id, name) for the .app/.appex enclosing `exe_path`, else (None, basename).

    NSRunningApplication returns None for non-GUI processes (daemons, app
    extensions), which is exactly the class of process that causes false
    'in a call' readings — so the enclosing bundle's Info.plist is read directly.
    """
    import os
    import plistlib
    part = exe_path
    while part and part != "/":
        if part.endswith(".app") or part.endswith(".appex"):
            try:
                with open(os.path.join(part, "Contents", "Info.plist"), "rb") as f:
                    info = plistlib.load(f)
                return (info.get("CFBundleIdentifier"),
                        info.get("CFBundleName") or os.path.basename(part))
            except Exception:
                break
        part = os.path.dirname(part)
    return None, os.path.basename(exe_path)


def _app_identity(pid):
    """(bundle_id | None, display_name) for a pid. Never raises.

    GUI apps resolve through NSRunningApplication; everything else falls back to
    libproc's executable path and the enclosing bundle, so an .appex still gets a
    real name ('Sound') instead of a bare pid.
    """
    import os
    try:
        from AppKit import NSRunningApplication
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is not None:
            return app.bundleIdentifier(), (app.localizedName() or str(pid))
    except Exception:
        pass
    try:
        import ctypes
        libc = ctypes.CDLL("/usr/lib/libSystem.dylib")
        buf = ctypes.create_string_buffer(PROC_PATH_MAX)
        if libc.proc_pidpath(pid, buf, PROC_PATH_MAX) > 0:
            return _bundle_identity_from_path(buf.value.decode("utf-8", "replace"))
    except Exception:
        pass
    return None, "pid %d" % pid


def mic_input_processes():
    """Which processes are running audio INPUT right now.

    Returns [(pid, bundle_id, name), …], or **None when attribution is
    unavailable** (non-macOS, macOS < 14, or any failure). The None/[] distinction
    is load-bearing: [] means 'asked, nobody holds the mic'; None means 'could not
    ask', and the caller must then fall back to the device-level boolean.

    Named seam for other platforms: a Windows/Linux implementation would return
    the same shape from its own audio stack; today they get None.
    """
    if sys.platform != "darwin":
        return None
    try:
        import CoreAudio as CA
        import objc

        def addr(selector):
            return CA.AudioObjectPropertyAddress(
                selector, CA.kAudioObjectPropertyScopeGlobal,
                CA.kAudioObjectPropertyElementMain)

        def u32(obj, selector):
            status, _size, data = CA.AudioObjectGetPropertyData(
                obj, addr(selector), 0, objc.NULL, UINT32_SIZE, None)
            if status != 0:
                return None
            return struct.unpack("I", bytes(data))[0]

        status, size = CA.AudioObjectGetPropertyDataSize(
            CA.kAudioObjectSystemObject, addr(PROCESS_OBJECT_LIST), 0, objc.NULL, None)
        if status != 0:
            return None            # macOS < 14 — the property does not exist
        count = size // UINT32_SIZE
        if count <= 0:
            return []
        status, _size, raw = CA.AudioObjectGetPropertyData(
            CA.kAudioObjectSystemObject, addr(PROCESS_OBJECT_LIST),
            0, objc.NULL, size, None)
        if status != 0:
            return None
        holders = []
        for obj in struct.unpack("%dI" % count, bytes(raw)[:count * UINT32_SIZE]):
            if not u32(obj, PROCESS_IS_RUNNING_INPUT):
                continue
            pid = u32(obj, PROCESS_PID)
            if pid is None:
                continue
            bundle_id, name = _app_identity(pid)
            holders.append((pid, bundle_id, name))
        return holders
    except Exception as e:
        logging.debug("mic_input_processes() failed, attribution unavailable: %s", e)
        return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `DFYB_DEV=1 .venv/bin/python -m pytest tests/test_sensors.py -q`
Expected: PASS (existing cases + 5 new)

- [ ] **Step 5: Verify against the real machine (macOS only, throwaway)**

Run: `DFYB_DEV=1 .venv/bin/python -c "from dfyb.activity.sensors import mic_input_processes as m; print(m())"`
Expected: `[]` with nothing using the mic; start Photo Booth or a call and it must name that app. If it prints `None` on macOS 14+, the selectors are wrong — stop and fix before continuing.

- [ ] **Step 6: Commit**

```bash
git add dfyb/activity/sensors.py tests/test_sensors.py
git commit -m "Mic deferral: identify which processes are running audio input (process-level CoreAudio), with an explicit unavailable result"
```

---

### Task 3: Fullscreen attribution — who owns the covered display

**Files:**
- Modify: `dfyb/activity/sensors.py` (beside `frontmost_is_fullscreen()`, ~line 139)
- Test: `tests/test_sensors.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `covering_owners(owned_windows, displays, tol=FULLSCREEN_COVER_TOLERANCE_PX) -> list[(pid, name)]` (pure) and `fullscreen_state() -> (bool, list[(pid, bundle_id, name)] | None)`.

**Critical constraint:** coverage is still decided by ALL windows together via the existing `_display_is_covered()`, so a thin overlay from another process in front of a fullscreen window keeps working. Only the *naming* uses largest-intersecting-area. `covers_any_display()` and its twelve tests are not modified.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sensors.py`:

```python
# --- fullscreen attribution: WHO covers the display (#40/#28) ---
# owned windows are (rect, pid, owner_name)

def test_covering_owners_names_a_single_window_fullscreen():
    owned = [((0, 0, 1920, 1080), 700, "Google Chrome")]
    assert sensors.covering_owners(owned, [MAIN_DISPLAY]) == [(700, "Google Chrome")]


def test_covering_owners_names_the_largest_area_for_multiwindow_fullscreen():
    # The real #23 capture: strips + a content pane, all Chrome.
    owned = [((0, 0, 1920, 41), 700, "Google Chrome"),
             ((0, 41, 1920, 81), 700, "Google Chrome"),
             ((0, 122, 1920, 958), 700, "Google Chrome")]
    assert sensors.covering_owners(owned, [MAIN_DISPLAY]) == [(700, "Google Chrome")]


def test_covering_owners_does_not_let_a_thin_overlay_steal_the_name():
    # A menu-bar utility's full-width strip sits in front of the fullscreen app;
    # the content pane owns far more area, so the app is still named.
    owned = [((0, 0, 1920, 41), 999, "Bartender"),
             ((0, 0, 1920, 1080), 700, "Google Chrome")]
    assert sensors.covering_owners(owned, [MAIN_DISPLAY]) == [(700, "Google Chrome")]


def test_covering_owners_is_empty_when_nothing_covers():
    owned = [((0, 122, 1920, 958), 700, "Google Chrome")]
    assert sensors.covering_owners(owned, [MAIN_DISPLAY]) == []


def test_covering_owners_reports_one_entry_per_covered_display():
    owned = [((0, 0, 1920, 1080), 700, "Google Chrome"),
             ((1920, 64, 1512, 982), 800, "Keynote")]
    assert sensors.covering_owners(owned, DISPLAYS) == [
        (700, "Google Chrome"), (800, "Keynote")]


def test_fullscreen_state_off_macos_is_not_fullscreen_and_unattributable(monkeypatch):
    monkeypatch.setattr(sensors.sys, "platform", "linux")
    assert sensors.fullscreen_state() == (False, None)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `DFYB_DEV=1 .venv/bin/python -m pytest tests/test_sensors.py -k "covering_owners or fullscreen_state" -q`
Expected: FAIL — `AttributeError: module 'dfyb.activity.sensors' has no attribute 'covering_owners'`

- [ ] **Step 3: Write the implementation**

Add to `dfyb/activity/sensors.py`, after `covers_any_display()`:

```python
def _covered_area(rect, display):
    """Area of the intersection between a window rect and a display rect."""
    wx, wy, ww, wh = rect
    dx, dy, dw, dh = display
    overlap_w = max(0.0, min(wx + ww, dx + dw) - max(wx, dx))
    overlap_h = max(0.0, min(wy + wh, dy + dh) - max(wy, dy))
    return overlap_w * overlap_h


def covering_owners(owned_windows, displays, tol=FULLSCREEN_COVER_TOLERANCE_PX):
    """[(pid, owner_name), …] — one entry per COVERED display, naming the app that
    owns the largest share of that display's area.

    `owned_windows` is [(rect, pid, owner_name)]. Coverage is still decided by ALL
    windows together (so an overlay from another process in front of a fullscreen
    window is still detected); only the naming is per-owner, and the content pane
    always outweighs a thin strip. Pure — unit-tested off macOS.
    """
    rects = [rect for rect, _pid, _name in owned_windows]
    owners = []
    for display in displays:
        if not _display_is_covered(rects, display, tol):
            continue
        area_by_owner = {}
        for rect, pid, name in owned_windows:
            area = _covered_area(rect, display)
            if area <= 0:
                continue
            previous = area_by_owner.get(pid, (0.0, name))
            area_by_owner[pid] = (previous[0] + area, name)
        if not area_by_owner:
            continue
        pid, (_area, name) = max(area_by_owner.items(), key=lambda kv: kv[1][0])
        owners.append((pid, name))
    return owners


def _layer0_owned_windows(Quartz):
    """[(rect, pid, owner_name)] for each on-screen normal (layer-0) window.
    The owner fields come free in the same CGWindowList dicts — no extra API call."""
    windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly
        | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID,
    )
    owned = []
    for window in windows:
        if window.get("kCGWindowLayer", 1) != 0:
            continue
        bounds = window.get("kCGWindowBounds", {})
        owned.append((
            (bounds.get("X", 0.0), bounds.get("Y", 0.0),
             bounds.get("Width", 0.0), bounds.get("Height", 0.0)),
            window.get("kCGWindowOwnerPID"),
            window.get("kCGWindowOwnerName") or "",
        ))
    return owned


def fullscreen_state():
    """(is_fullscreen, owners) in ONE pass over the window list.

    `owners` is [(pid, bundle_id, name)] for the apps covering a display, or
    **None when ownership could not be resolved** while the boolean is still
    valid — the same None/[] contract as `mic_input_processes()`. Off macOS:
    (False, None). Named seam: another platform would fill in its own window
    server query here.
    """
    if sys.platform != "darwin":
        return False, None
    try:
        import Quartz
        displays = _active_display_rects(Quartz)
        owned = _layer0_owned_windows(Quartz)
        covered = covers_any_display([r for r, _p, _n in owned], displays)
        owners = [(pid, _app_identity(pid)[0], name)
                  for pid, name in covering_owners(owned, displays)]
        return covered, owners
    except Exception as e:
        logging.debug("fullscreen_state() failed, attribution unavailable: %s", e)
        return frontmost_is_fullscreen(), None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `DFYB_DEV=1 .venv/bin/python -m pytest tests/test_sensors.py -q`
Expected: PASS — including all twelve original `covers_any_display` cases, unchanged.

- [ ] **Step 5: Verify against the real machine (macOS only, throwaway)**

Run: `DFYB_DEV=1 .venv/bin/python -c "from dfyb.activity.sensors import fullscreen_state; print(fullscreen_state())"`
Expected: `(False, [])` in a normal window; put an app in native fullscreen and it must return `(True, [(pid, bundle, 'That App')])`.

- [ ] **Step 6: Commit**

```bash
git add dfyb/activity/sensors.py tests/test_sensors.py
git commit -m "Fullscreen deferral: name the app covering each display, without touching the proven coverage geometry"
```

---

### Task 4: Wire attribution into the context

**Files:**
- Modify: `dfyb/scheduler/engine.py:14-19` (the `Context` dataclass)
- Modify: `dfyb/activity/sensors.py` (`read_context`, ~line 268)
- Test: `tests/test_sensors.py`, `tests/test_scheduler_engine.py`

**Interfaces:**
- Consumes: `mic_input_processes()`, `fullscreen_state()` (Tasks 2-3); `surviving_holders`, `primary_holder`, `holder_ref` (Task 1).
- Produces: `Context.meeting_app: dict | None` and `Context.fullscreen_app: dict | None`, each `{"id", "name", "count"}` where `count` is how many non-ignored holders/owners there were. `read_context(check_meeting=True, check_fullscreen=True, count_mouse_move=False, mic_ignores=frozenset(), fullscreen_ignores=frozenset())`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sensors.py`:

```python
# --- read_context with attribution + ignore lists ---

SOUND_HOLDER = (45648, "com.apple.Sound-Settings.extension", "Sound")
ZOOM_HOLDER = (700, "us.zoom.xos", "Zoom")


def _stub_context_sensors(monkeypatch, *, mic_on=False, holders=None,
                          covered=False, owners=None):
    monkeypatch.setattr(sensors, "idle_seconds", lambda: 0.0)
    monkeypatch.setattr(sensors, "active_idle_seconds",
                        lambda include_mouse_move=False: 0.0)
    monkeypatch.setattr(sensors, "microphone_in_use", lambda: mic_on)
    monkeypatch.setattr(sensors, "mic_input_processes", lambda: holders)
    monkeypatch.setattr(sensors, "fullscreen_state", lambda: (covered, owners))


def test_ignored_sound_pane_alone_is_not_a_meeting(monkeypatch):
    # REGRESSION for the 2026-09-01 incident: the System Settings Sound pane held
    # the input for 18h and every break was deferred as "you're in a call".
    from dfyb.activity import app_rules
    _stub_context_sensors(monkeypatch, mic_on=True, holders=[SOUND_HOLDER])
    ignores = app_rules.effective_ignores(app_rules.DEFAULT_MIC_IGNORED_APPS, [], [])
    ctx = sensors.read_context(mic_ignores=ignores)
    assert ctx.is_meeting is False and ctx.meeting_app is None


def test_a_real_call_alongside_an_ignored_holder_still_defers(monkeypatch):
    from dfyb.activity import app_rules
    _stub_context_sensors(monkeypatch, mic_on=True,
                          holders=[SOUND_HOLDER, ZOOM_HOLDER])
    ignores = app_rules.effective_ignores(app_rules.DEFAULT_MIC_IGNORED_APPS, [], [])
    ctx = sensors.read_context(mic_ignores=ignores)
    assert ctx.is_meeting is True
    assert ctx.meeting_app == {"id": "us.zoom.xos", "name": "Zoom", "count": 1}


def test_unattributable_mic_falls_back_to_the_device_signal(monkeypatch):
    # macOS 13 / CoreAudio failure: holders is None -> trust the device gate,
    # defer as before, just without a name.
    _stub_context_sensors(monkeypatch, mic_on=True, holders=None)
    ctx = sensors.read_context(mic_ignores=frozenset({"us.zoom.xos"}))
    assert ctx.is_meeting is True and ctx.meeting_app is None


def test_device_gate_off_means_no_enumeration(monkeypatch):
    calls = []
    _stub_context_sensors(monkeypatch, mic_on=False)
    monkeypatch.setattr(sensors, "mic_input_processes",
                        lambda: calls.append(1) or [])
    ctx = sensors.read_context()
    assert ctx.is_meeting is False and calls == []


def test_ignored_fullscreen_app_does_not_defer(monkeypatch):
    _stub_context_sensors(monkeypatch, covered=True,
                          owners=[(900, "com.apple.Terminal", "Terminal")])
    ctx = sensors.read_context(fullscreen_ignores=frozenset({"com.apple.terminal"}))
    assert ctx.is_fullscreen is False and ctx.fullscreen_app is None


def test_second_display_covered_by_another_app_still_defers(monkeypatch):
    _stub_context_sensors(monkeypatch, covered=True,
                          owners=[(900, "com.apple.Terminal", "Terminal"),
                                  (800, "com.apple.iWork.Keynote", "Keynote")])
    ctx = sensors.read_context(fullscreen_ignores=frozenset({"com.apple.terminal"}))
    assert ctx.is_fullscreen is True
    assert ctx.fullscreen_app == {"id": "com.apple.iWork.Keynote",
                                  "name": "Keynote", "count": 1}


def test_unattributable_fullscreen_falls_back_to_the_boolean(monkeypatch):
    _stub_context_sensors(monkeypatch, covered=True, owners=None)
    ctx = sensors.read_context(fullscreen_ignores=frozenset({"com.apple.terminal"}))
    assert ctx.is_fullscreen is True and ctx.fullscreen_app is None


def test_gates_still_win_over_attribution(monkeypatch):
    _stub_context_sensors(monkeypatch, mic_on=True, holders=[ZOOM_HOLDER],
                          covered=True, owners=[(800, "x", "Keynote")])
    ctx = sensors.read_context(check_meeting=False, check_fullscreen=False)
    assert (ctx.is_meeting, ctx.meeting_app) == (False, None)
    assert (ctx.is_fullscreen, ctx.fullscreen_app) == (False, None)
```

Append to `tests/test_scheduler_engine.py`:

```python
def test_context_app_fields_default_to_none():
    c = Context(idle_seconds=0.0, is_fullscreen=False)
    assert c.meeting_app is None and c.fullscreen_app is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `DFYB_DEV=1 .venv/bin/python -m pytest tests/test_sensors.py -k read_context -q`
Expected: FAIL — `TypeError: read_context() got an unexpected keyword argument 'mic_ignores'`

- [ ] **Step 3: Extend the Context**

In `dfyb/scheduler/engine.py`, replace the `Context` dataclass body:

```python
@dataclass(frozen=True)
class Context:
    """What the sensors observed this tick."""
    idle_seconds: float
    is_fullscreen: bool
    is_meeting: bool = False
    active_idle_seconds: float | None = None  # typing/clicks idle; None -> use idle_seconds
    # Which app caused the signal, as {"id", "name", "count"} — for the UI and the
    # event log only; `decide()` never reads them. None when not deferring or when
    # attribution was unavailable.
    meeting_app: dict | None = None
    fullscreen_app: dict | None = None
```

- [ ] **Step 4: Rewrite read_context**

In `dfyb/activity/sensors.py`, replace `read_context` with:

```python
def _attributed(holders, ignores):
    """(busy, app_ref) from a holder list and its ignore set.

    `holders is None` means attribution was unavailable: the caller keeps its raw
    boolean and gets no name. Otherwise only non-ignored holders count as busy,
    and `primary_holder` picks the one to name.
    """
    if holders is None:
        return None, None            # None => "caller, keep your own answer"
    surviving = app_rules.surviving_holders(holders, ignores)
    if not surviving:
        return False, None
    ref = app_rules.holder_ref(app_rules.primary_holder(surviving))
    return True, {**ref, "count": len(surviving)}


def read_context(check_meeting=True, check_fullscreen=True, count_mouse_move=False,
                 mic_ignores=frozenset(), fullscreen_ignores=frozenset()):
    """Snapshot the current context for the scheduler.

    `check_meeting` / `check_fullscreen` gate their signals (the app's
    `defer_during_meetings` / `defer_during_fullscreen` prefs): when False, that
    flag is always False regardless of the real state.

    `mic_ignores` / `fullscreen_ignores` are sets of normalized app keys that must
    not cause a deferral (see `dfyb.activity.app_rules`). Filtering happens HERE,
    before the timer loop's `smooth_signal()` hysteresis, so ignoring an app takes
    effect immediately instead of leaving a grace-window tail of deferral.
    """
    is_meeting, meeting_app = False, None
    if check_meeting and microphone_in_use():
        # The device-level check is the cheap gate; only then do we pay for the
        # per-process enumeration to find out WHO.
        attributed, meeting_app = _attributed(mic_input_processes(), mic_ignores)
        is_meeting = True if attributed is None else attributed

    is_fullscreen, fullscreen_app = False, None
    if check_fullscreen:
        covered, owners = fullscreen_state()
        if covered:
            attributed, fullscreen_app = _attributed(owners, fullscreen_ignores)
            is_fullscreen = True if attributed is None else attributed

    return Context(
        idle_seconds=idle_seconds(),
        is_fullscreen=is_fullscreen,
        is_meeting=is_meeting,
        active_idle_seconds=active_idle_seconds(include_mouse_move=count_mouse_move),
        meeting_app=meeting_app,
        fullscreen_app=fullscreen_app,
    )
```

Add the import at the top of `sensors.py`, beside the existing `from dfyb.scheduler.engine import Context`:

```python
from dfyb.activity import app_rules
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `DFYB_DEV=1 .venv/bin/python -m pytest -q`
Expected: PASS — including `tests/test_deferral_debounce.py`, whose hysteresis behavior must be unchanged.

- [ ] **Step 6: Commit**

```bash
git add dfyb/activity/sensors.py dfyb/scheduler/engine.py tests/test_sensors.py tests/test_scheduler_engine.py
git commit -m "Context carries which app caused a mic/fullscreen deferral, and ignore lists filter it before hysteresis"
```

---

### Task 5: Log the cause, not just the reason

**Files:**
- Modify: `dfyb/scheduler/engine.py` (`StepResult`, `step`)
- Modify: `dfyb/scheduler/tick.py` (`events_for_tick`)
- Test: `tests/test_scheduler_engine.py`, `tests/test_scheduler_tick.py`

**Interfaces:**
- Consumes: `Context.meeting_app` / `Context.fullscreen_app` (Task 4).
- Produces: `defer_reason_and_app(ctx, away_threshold, pause_threshold) -> (reason, app_ref | None)`, `StepResult.defer_app: dict | None`, and a `break_deferred` payload of `{"reason", "app", "app_name", "holder_count"}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scheduler_engine.py`:

```python
ZOOM_REF = {"id": "us.zoom.xos", "name": "Zoom", "count": 1}


def test_defer_reason_and_app_names_the_mic_holder():
    c = Context(idle_seconds=0.0, is_fullscreen=False, is_meeting=True,
                meeting_app=ZOOM_REF)
    assert defer_reason_and_app(c, 60, 0) == ("meeting", ZOOM_REF)


def test_defer_reason_and_app_prefers_fullscreen_like_decide_does():
    # decide() checks fullscreen first; the reason must agree with it.
    keynote = {"id": "com.apple.iWork.Keynote", "name": "Keynote", "count": 1}
    c = Context(idle_seconds=0.0, is_fullscreen=True, is_meeting=True,
                fullscreen_app=keynote, meeting_app=ZOOM_REF)
    assert defer_reason_and_app(c, 60, 0) == ("fullscreen", keynote)


def test_defer_reason_and_app_has_no_app_for_away():
    c = Context(idle_seconds=120.0, is_fullscreen=False)
    assert defer_reason_and_app(c, 60, 0) == ("away", None)


def test_step_carries_the_deferring_app_through():
    states = [BreakState(remaining=1, interval_seconds=600, duration_seconds=15)]
    c = Context(idle_seconds=0.0, is_fullscreen=False, is_meeting=True,
                meeting_app=ZOOM_REF)
    r = step(states, c)
    assert r.defer_reason == "meeting" and r.defer_app == ZOOM_REF
```

Add `defer_reason_and_app` and `BreakState` to that file's imports.

Append to `tests/test_scheduler_tick.py`:

```python
def test_deferred_event_records_which_app_caused_it():
    from dfyb.scheduler.engine import StepResult
    result = StepResult(new_remaining=[0], defer_reason="meeting",
                        defer_app={"id": "us.zoom.xos", "name": "Zoom", "count": 2})
    ctx = Context(idle_seconds=0.0, is_fullscreen=False, is_meeting=True)
    events, episode = events_for_tick(result, ctx, None)
    assert events == [("break_deferred", {"reason": "meeting", "app": "us.zoom.xos",
                                          "app_name": "Zoom", "holder_count": 2})]
    assert episode == "deferred"


def test_deferred_event_without_attribution_keeps_todays_payload():
    from dfyb.scheduler.engine import StepResult
    result = StepResult(new_remaining=[0], defer_reason="away")
    ctx = Context(idle_seconds=120.0, is_fullscreen=False)
    events, _episode = events_for_tick(result, ctx, None)
    assert events == [("break_deferred", {"reason": "away"})]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `DFYB_DEV=1 .venv/bin/python -m pytest tests/test_scheduler_engine.py tests/test_scheduler_tick.py -q`
Expected: FAIL — `ImportError: cannot import name 'defer_reason_and_app'`

- [ ] **Step 3: Implement in engine.py**

Add `defer_app` to `StepResult`:

```python
@dataclass(frozen=True)
class StepResult:
    """What the loop should do this tick."""
    new_remaining: list[int]        # updated `remaining` per break (write back to configs)
    natural_break: bool = False
    fire_index: int | None = None   # which break to pop
    defer_reason: str | None = None  # "fullscreen" | "meeting" | "away" | "active"
    defer_app: dict | None = None    # {"id", "name", "count"} of the app that caused it
```

Add the helper next to `decide()`:

```python
def defer_reason_and_app(ctx, away_threshold=AWAY_IDLE_THRESHOLD_SECONDS,
                         pause_threshold=0):
    """(reason, app_ref) for a deferral, in the SAME priority order as `decide()`.

    Kept beside `decide()` so the two can never drift: if `decide()` deferred
    because of fullscreen, this must not report 'meeting'. `app_ref` is None for
    reasons that have no app (away / active) and when attribution was unavailable.
    """
    if ctx.is_fullscreen:
        return "fullscreen", ctx.fullscreen_app
    if ctx.is_meeting:
        return "meeting", ctx.meeting_app
    if ctx.idle_seconds >= away_threshold:
        return "away", None
    return "active", None
```

In `step()`, replace the inline reason chain:

```python
        if decide(ctx, away_threshold, pause_threshold) == DEFER:
            reason, app = defer_reason_and_app(ctx, away_threshold, pause_threshold)
            for i in due:
                new_remaining[i] = 0          # clamp — stays due, no negative drift
            return StepResult(new_remaining=new_remaining,
                              defer_reason=reason, defer_app=app)
```

- [ ] **Step 4: Implement in tick.py**

Replace the defer branch of `events_for_tick`:

```python
    if result.defer_reason is not None:
        if episode != DEFERRED_EPISODE:
            data = {"reason": result.defer_reason}
            if result.defer_app:
                # Attribute the push-back so the dashboard can total deferred time
                # per app ("Zoom pushed back 47 min of breaks this week").
                data["app"] = result.defer_app.get("id")
                data["app_name"] = result.defer_app.get("name")
                data["holder_count"] = result.defer_app.get("count")
            return [(BREAK_DEFERRED, data)], DEFERRED_EPISODE
        return [], DEFERRED_EPISODE
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `DFYB_DEV=1 .venv/bin/python -m pytest -q`
Expected: PASS — `track_held` still reads `data["reason"]`, so `tests/test_transparency.py` is unaffected.

- [ ] **Step 6: Commit**

```bash
git add dfyb/scheduler/engine.py dfyb/scheduler/tick.py tests/test_scheduler_engine.py tests/test_scheduler_tick.py
git commit -m "break_deferred records which app caused the deferral, in one place shared with decide()"
```

---

### Task 6: Say the app's name (closes #40)

**Files:**
- Modify: `dfyb/insights/status.py` (`HELD_LABELS`, `ANTICIPATED_CHIPS`, `compute_status`)
- Modify: `dfyb/activity/event_log.py` (new constant)
- Modify: `launch.py` — `_render_status` (~4902), `_log_break_fired` (~4330), `timer_loop` (~3905), `_held` init (~2264, 2836, 3090)
- Test: `tests/test_status.py`, `tests/test_event_log.py`

**Interfaces:**
- Consumes: `Context.meeting_app` / `fullscreen_app` (Task 4).
- Produces: `held_label(reason, app_name=None) -> (headline_phrase, chip_tail)`, `anticipated_chip(reason, app_name=None) -> str | None`, `compute_status(..., held_app_name=None, anticipated_app_name=None)`, `MIC_DETECTION_FALLBACK` event constant, and `BreakApp._held_app`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_status.py`:

```python
from dfyb.insights.status import held_label, anticipated_chip


def test_held_label_names_the_mic_holder():
    assert held_label("meeting", "Zoom")[0] == "Zoom is using your microphone"


def test_held_label_names_the_fullscreen_app():
    assert held_label("fullscreen", "Keynote")[0] == "Keynote is in full screen"


def test_held_label_without_an_app_keeps_todays_wording():
    assert held_label("meeting")[0] == "you're in a call"
    assert held_label("fullscreen")[0] == "you're in full screen"


def test_held_label_unknown_reason_falls_back():
    assert held_label("wat") == ("wat", "during wat")


def test_status_headline_uses_the_app_name():
    view = compute_status(running=True, paused=False, held_reason="meeting",
                          next_name="Micro Break", next_remaining=0,
                          next_interval=600, break_active=False,
                          held_app_name="Zoom")
    assert view.headline == "Waiting — Zoom is using your microphone"


def test_status_exposes_the_ignore_action_when_attributed():
    view = compute_status(running=True, paused=False, held_reason="meeting",
                          next_name="Micro Break", next_remaining=0,
                          next_interval=600, break_active=False,
                          held_app_name="Zoom")
    assert view.chip_action_label == "Ignore Zoom"


def test_status_has_no_ignore_action_without_attribution():
    view = compute_status(running=True, paused=False, held_reason="meeting",
                          next_name="Micro Break", next_remaining=0,
                          next_interval=600, break_active=False)
    assert view.chip_action_label is None


def test_anticipated_chip_names_the_app():
    assert anticipated_chip("meeting", "Zoom") == "Zoom is using your microphone — your break will wait"


def test_anticipated_chip_without_an_app_keeps_todays_wording():
    assert anticipated_chip("meeting") == "In a call — your break will wait"
```

Append to `tests/test_event_log.py`:

```python
def test_mic_detection_fallback_constant_exists():
    from dfyb.activity import event_log
    assert event_log.MIC_DETECTION_FALLBACK == "mic_detection_fallback"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `DFYB_DEV=1 .venv/bin/python -m pytest tests/test_status.py tests/test_event_log.py -q`
Expected: FAIL — `ImportError: cannot import name 'held_label'`

- [ ] **Step 3: Implement in status.py**

Replace `HELD_LABELS` / `ANTICIPATED_CHIPS` usage with attributed variants:

```python
# held-reason key -> (friendly phrase for the headline, tail for the chip) when we
# could NOT name the app. Attributed phrasings are built by `held_label` below.
HELD_LABELS = {
    "meeting": ("you're in a call", "during meetings"),
    "fullscreen": ("you're in full screen", "in full screen"),
    "away": ("you're away", "while you're away"),
    "active": ("you're busy", "during activity"),
}

# reason -> "{app} …" headline used when the causing app IS known. Naming the app
# replaces the old assumption that mic-in-use means a call (#40).
ATTRIBUTED_HELD_HEADLINES = {
    "meeting": "{app} is using your microphone",
    "fullscreen": "{app} is in full screen",
}


def held_label(reason, app_name=None):
    """(headline phrase, chip tail) for a held break — naming the app when known,
    falling back to today's generic wording when it is not."""
    generic, tail = HELD_LABELS.get(reason, (reason, f"during {reason}"))
    template = ATTRIBUTED_HELD_HEADLINES.get(reason)
    if app_name and template:
        return template.format(app=app_name), tail
    return generic, tail


def anticipated_chip(reason, app_name=None):
    """The proactive 'your break will wait' chip (#74), naming the app when known."""
    template = ATTRIBUTED_HELD_HEADLINES.get(reason)
    if app_name and template:
        return f"{template.format(app=app_name)} — your break will wait"
    return ANTICIPATED_CHIPS.get(reason)
```

Add the action fields to `StatusView` and use the new helpers in `compute_status`:

```python
@dataclass
class StatusView:
    state: str
    dot: str
    headline: str
    subtext: str
    progress: float
    chip: str | None = None
    progress_style: str = "none"  # 'none' (flat rail) | 'live' (blue) | 'frozen' (grey)
    # One-click "excuse this app" offered on the chip while attributed (#40/#28).
    # The pure layer never holds a callback — launch.py renders and wires it.
    chip_action_label: str | None = None
    chip_action_signal: str | None = None   # 'mic' | 'fullscreen'
```

In `compute_status`, add the two keyword arguments (`held_app_name=None`, `anticipated_app_name=None`) and replace the holding branch:

```python
    if held_reason:
        label, tail = held_label(held_reason, held_app_name)
        signal = {"meeting": "mic", "fullscreen": "fullscreen"}.get(held_reason)
        return StatusView(
            "holding", "warning", f"Waiting — {label}",
            f"{next_name} is due; it'll wait",
            progress_fraction(next_remaining, next_interval),
            chip=f"Breaks pause {tail}", progress_style="live",
            chip_action_label=(f"Ignore {held_app_name}"
                               if held_app_name and signal else None),
            chip_action_signal=signal if held_app_name else None)
```

and the on-track branch's chip:

```python
        chip=(anticipated_chip(anticipated_reason, anticipated_app_name)
              if anticipated_reason else None),
```

- [ ] **Step 4: Add the event constant**

In `dfyb/activity/event_log.py`, after `CHECK_IN`:

```python
MIC_DETECTION_FALLBACK = "mic_detection_fallback"  # per-process mic attribution unavailable
                                                   # (macOS < 14 or a CoreAudio failure) — the
                                                   # deferral fell back to the device-level
                                                   # signal, so it has no app name. Once per session.
```

- [ ] **Step 5: Wire launch.py**

In `BreakApp.__init__` beside `self._held = None` (~2264), and at the two resets (~2836, ~3090), add:

```python
        self._held_app = None       # {"id","name","count"} of the app causing the hold
```

Also in `__init__`:

```python
        self._logged_mic_fallback = False   # mic_detection_fallback is once per session
```

In `timer_loop`, right after `ctx = read_context(...)`, capture the names and log the fallback once:

```python
                # Remember WHO caused each signal, for the chip and the event log.
                self._held_app = ctx.meeting_app or ctx.fullscreen_app
                if (ctx.is_meeting and ctx.meeting_app is None
                        and not self._logged_mic_fallback):
                    self._logged_mic_fallback = True
                    self._record_event(MIC_DETECTION_FALLBACK,
                                       reason="process attribution unavailable")
```

Where `self._anticipated` is set, also keep the name:

```python
                self._anticipated_app = (
                    (ctx.meeting_app or {}).get("name") if eff_meeting else
                    (ctx.fullscreen_app or {}).get("name") if eff_fullscreen else None)
```

(initialize `self._anticipated_app = None` beside `self._anticipated` at ~2265.)

In `_render_status`, pass the names through:

```python
        view = compute_status(
            running=self.running, paused=self.paused, held_reason=self._held,
            next_name=next_name, next_remaining=next_remaining,
            next_interval=next_interval, break_active=self.active_popup is not None,
            just_rested=just_rested, anticipated_reason=self._anticipated,
            held_app_name=(self._held_app or {}).get("name"),
            anticipated_app_name=self._anticipated_app)
```

In `_log_break_fired`, add the parameter and the field:

```python
    def _log_break_fired(self, name, source, *, raw_idle, raw_active_idle,
                         raw_meeting, raw_fullscreen, pause, away, held_reason,
                         scheduled_ts, deferred_seconds, meeting_app=None):
```

```python
            is_meeting=raw_meeting, is_fullscreen=raw_fullscreen,
            meeting_app=meeting_app,
```

and at the call site in `timer_loop`:

```python
                        held_reason=held_reason, scheduled_ts=scheduled_ts,
                        deferred_seconds=deferred_seconds,
                        meeting_app=(ctx.meeting_app or {}).get("name"))
```

Add `MIC_DETECTION_FALLBACK` to the `event_log` import at the top of `launch.py`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `DFYB_DEV=1 .venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 7: Verify in the real app**

Run: `pkill -f launch.py ; rm -f ~/Library/Application\ Support/DontForgetYourBreaks/.lock.dev ; DFYB_DEV=1 .venv/bin/python launch.py`
Set a break interval to ~1 minute, start a call (or Photo Booth), and confirm the hero reads **"Waiting — <App> is using your microphone"**. Confirm `events.dev.jsonl` has a `break_deferred` carrying `app_name`.

- [ ] **Step 8: Commit**

```bash
git add dfyb/insights/status.py dfyb/activity/event_log.py launch.py tests/test_status.py tests/test_event_log.py
git commit -m "Name the app holding the mic / covering the screen in the status hero, the anticipated chip and break_fired; log when attribution is unavailable"
```

**Note on scope:** `dfyb/insights/transparency.py`'s `HELD_MESSAGES` ("Waited while your microphone was in use.") is left generic on purpose — `track_held` carries only a reason string, and that wording is already accurate. Attributing the post-break popup line is a follow-up, not a gap in this task.

---

### Task 7: User-editable ignore lists (preferences)

**Files:**
- Modify: `launch.py` — pref vars (~2309-2322), `_save_preferences` (~2735), `timer_loop` `read_context` call (~3909)
- Modify: `dfyb/activity/event_log.py`
- Test: `tests/test_app_rules.py`, `tests/test_event_log.py`

**Interfaces:**
- Consumes: `effective_ignores` (Task 1), `read_context(mic_ignores=…, fullscreen_ignores=…)` (Task 4).
- Produces: `BreakApp.mic_ignored_apps: list[dict]`, `mic_unignored_builtins: list[str]`, `fullscreen_ignored_apps: list[dict]`, `BreakApp._ignores(signal) -> set[str]`, `BreakApp._toggle_ignore(signal, app_ref, ignore: bool, source: str)`, and the `APP_IGNORE_ADDED` / `APP_IGNORE_REMOVED` events.

- [ ] **Step 1: Write the failing test for the pure part**

Append to `tests/test_app_rules.py`:

```python
def test_ignores_from_prefs_round_trip():
    # The exact shape BreakApp stores: user additions + un-ignored built-ins.
    prefs = {"mic_ignored_apps": [{"id": "us.zoom.xos", "name": "Zoom"}],
             "mic_unignored_builtins": ["com.apple.controlcenter"]}
    keys = rules.effective_ignores(
        rules.DEFAULT_MIC_IGNORED_APPS,
        prefs.get("mic_ignored_apps", []),
        prefs.get("mic_unignored_builtins", []))
    assert "us.zoom.xos" in keys
    assert "com.apple.controlcenter" not in keys
    assert "com.apple.sound-settings.extension" in keys


def test_missing_pref_keys_fall_back_to_builtins_only():
    prefs = {}
    keys = rules.effective_ignores(
        rules.DEFAULT_MIC_IGNORED_APPS,
        prefs.get("mic_ignored_apps", []),
        prefs.get("mic_unignored_builtins", []))
    assert keys == {rules.normalize_app(a.get("id"), a.get("name"))
                    for a in rules.DEFAULT_MIC_IGNORED_APPS}
```

Append to `tests/test_event_log.py`:

```python
def test_app_ignore_event_constants_exist():
    from dfyb.activity import event_log
    assert event_log.APP_IGNORE_ADDED == "app_ignore_added"
    assert event_log.APP_IGNORE_REMOVED == "app_ignore_removed"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `DFYB_DEV=1 .venv/bin/python -m pytest tests/test_app_rules.py tests/test_event_log.py -q`
Expected: FAIL — `AttributeError: module 'dfyb.activity.event_log' has no attribute 'APP_IGNORE_ADDED'`

- [ ] **Step 3: Add the event constants**

In `dfyb/activity/event_log.py`:

```python
APP_IGNORE_ADDED = "app_ignore_added"      # user excused an app from a defer signal
                                           # {signal, app, app_name, source, builtin}
APP_IGNORE_REMOVED = "app_ignore_removed"  # user un-excused an app (incl. a built-in)
```

- [ ] **Step 4: Add the preferences and the helpers in launch.py**

In `BreakApp.__init__`, beside the existing defer prefs (these are plain lists, not
`ctk` vars — they are edited through `_toggle_ignore`, not bound to a widget):

```python
        # Per-app exceptions to the defer signals (#40/#28). Read with .get so
        # older config files keep loading; built-ins live in app_rules, not prefs.
        self.mic_ignored_apps = self.saved_prefs.get("mic_ignored_apps", [])
        self.mic_unignored_builtins = self.saved_prefs.get("mic_unignored_builtins", [])
        self.fullscreen_ignored_apps = self.saved_prefs.get("fullscreen_ignored_apps", [])
```

In `_save_preferences`'s dict:

```python
            "mic_ignored_apps": self.mic_ignored_apps,
            "mic_unignored_builtins": self.mic_unignored_builtins,
            "fullscreen_ignored_apps": self.fullscreen_ignored_apps,
```

Add the two methods next to `_scheduler_thresholds`:

```python
    def _ignores(self, signal):
        """The set of app keys currently ignored for one defer signal."""
        if signal == app_rules.MIC:
            return app_rules.effective_ignores(
                app_rules.DEFAULT_MIC_IGNORED_APPS,
                self.mic_ignored_apps, self.mic_unignored_builtins)
        return app_rules.effective_ignores(
            app_rules.DEFAULT_FULLSCREEN_IGNORED_APPS,
            self.fullscreen_ignored_apps, [])

    def _toggle_ignore(self, signal, app_ref, ignore, source):
        """Add or remove one app from a signal's ignore list, persist, and log it.

        `app_ref` is {"id", "name"}; `source` is 'chip' or 'settings'. Takes effect
        on the next tick — no restart — because the timer loop reads `_ignores()`
        fresh each time.
        """
        key = app_rules.normalize_app(app_ref.get("id"), app_ref.get("name"))
        builtins = (app_rules.DEFAULT_MIC_IGNORED_APPS if signal == app_rules.MIC
                    else app_rules.DEFAULT_FULLSCREEN_IGNORED_APPS)
        is_builtin = any(app_rules.normalize_app(a.get("id"), a.get("name")) == key
                         for a in builtins)
        added = (self.mic_ignored_apps if signal == app_rules.MIC
                 else self.fullscreen_ignored_apps)
        if ignore:
            if not any(app_rules.normalize_app(a.get("id"), a.get("name")) == key
                       for a in added):
                added.append({"id": app_ref.get("id"), "name": app_ref.get("name")})
            if signal == app_rules.MIC and key in {
                    k.strip().lower() for k in self.mic_unignored_builtins}:
                self.mic_unignored_builtins = [
                    k for k in self.mic_unignored_builtins if k.strip().lower() != key]
        else:
            added[:] = [a for a in added
                        if app_rules.normalize_app(a.get("id"), a.get("name")) != key]
            if is_builtin and signal == app_rules.MIC:
                self.mic_unignored_builtins.append(app_ref.get("id") or app_ref.get("name"))
        self._save_preferences()
        self._record_event(APP_IGNORE_ADDED if ignore else APP_IGNORE_REMOVED,
                           signal=signal, app=key, app_name=app_ref.get("name"),
                           source=source, builtin=is_builtin)
```

Pass the lists into the sensor call in `timer_loop`:

```python
                ctx = read_context(
                    check_meeting=self.defer_during_meetings.get(),
                    check_fullscreen=self.defer_during_fullscreen.get(),
                    count_mouse_move=self.count_mouse_move.get(),
                    mic_ignores=self._ignores(app_rules.MIC),
                    fullscreen_ignores=self._ignores(app_rules.FULLSCREEN),
                )
```

Add to the imports at the top of `launch.py`:

```python
from dfyb.activity import app_rules
from dfyb.activity.event_log import APP_IGNORE_ADDED, APP_IGNORE_REMOVED
```

(extend the existing `event_log` import line rather than adding a second one).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `DFYB_DEV=1 .venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 6: Verify persistence by hand**

```bash
DFYB_DEV=1 .venv/bin/python -c "
import launch, json
print(json.load(open(launch.CONFIG_FILE)).get('mic_ignored_apps'))"
```
Expected: `None` before anything is ignored (the pref is absent and defaults cleanly) — this proves the backward-compatible read.

- [ ] **Step 7: Commit**

```bash
git add launch.py dfyb/activity/event_log.py tests/test_app_rules.py tests/test_event_log.py
git commit -m "Per-app ignore lists as preferences, applied live to the mic and fullscreen deferral, with add/remove logged"
```

---

### Task 8: "Ignore Zoom" on the holding chip

**Files:**
- Modify: `launch.py` — hero chip widget (~2476), `_render_status` (~4932)
- Test: `tests/test_status.py` (already covers the pure part from Task 6)

**Interfaces:**
- Consumes: `StatusView.chip_action_label` / `chip_action_signal` (Task 6), `_toggle_ignore` (Task 7).
- Produces: `BreakApp.hero_chip_row`, `BreakApp.hero_chip_action`.

- [ ] **Step 1: Replace the bare chip label with a row**

At ~2476, replace the `hero_chip` label with a transparent row holding the label plus an action button (a text-style button so it reads as a link, not a second primary action):

```python
        # Holding chip — revealed by _render_status only while a break is deferred.
        # A row, not a bare label, so the attributed case can offer "Ignore <app>".
        self.hero_chip_row = ctk.CTkFrame(hero, fg_color="transparent")
        self.hero_chip = ctk.CTkLabel(
            self.hero_chip_row, text="", anchor="w",
            font=make_font('caption', weight="bold"),
            text_color=COLORS['accent_warning'])
        self.hero_chip.pack(side="left")
        self.hero_chip_action = ctk.CTkButton(
            self.hero_chip_row, text="", width=0, height=CHIP_ACTION_HEIGHT,
            fg_color="transparent", hover_color=COLORS['surface_hover'],
            text_color=COLORS['text_secondary'],
            font=make_font('caption'), command=self._handle_chip_ignore)
```

Add the token to the CONFIGURATION block beside the other heights:

```python
CHIP_ACTION_HEIGHT = 20     # inline "Ignore <app>" button on the holding chip
```

- [ ] **Step 2: Render it**

Replace the chip branch of `_render_status`:

```python
        if view.chip:
            self.hero_chip.configure(text=f"⏸ {view.chip}")
            if view.chip_action_label:
                self.hero_chip_action.configure(text=view.chip_action_label)
                if self.hero_chip_action.winfo_manager() != "pack":
                    self.hero_chip_action.pack(side="left", padx=(SPACE_XXS, 0))
            elif self.hero_chip_action.winfo_manager() == "pack":
                self.hero_chip_action.pack_forget()
            if self.hero_chip_row.winfo_manager() != "pack":
                self.hero_chip_row.pack(fill="x", padx=HERO_PAD, pady=(0, SPACE_SM),
                                        after=self.hero_progress)
        elif self.hero_chip_row.winfo_manager() == "pack":
            self.hero_chip_row.pack_forget()
```

- [ ] **Step 3: Handle the click**

Add beside `_toggle_ignore`:

```python
    def _handle_chip_ignore(self):
        """Excuse the app currently holding the break, straight from the chip.

        The list the user actually maintains gets built here, at the moment the
        wrong deferral happens — Settings is for review and correction.
        """
        app_ref, signal = self._held_app, None
        if self._held == "meeting":
            signal = app_rules.MIC
        elif self._held == "fullscreen":
            signal = app_rules.FULLSCREEN
        if not app_ref or signal is None:
            return
        self._toggle_ignore(signal, app_ref, ignore=True, source="chip")
        self._held, self._held_app = None, None   # stop holding immediately
        self._render_status()
```

- [ ] **Step 4: Run the suite**

Run: `DFYB_DEV=1 .venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Verify in the real app**

Run: `pkill -f launch.py ; rm -f ~/Library/Application\ Support/DontForgetYourBreaks/.lock.dev ; DFYB_DEV=1 .venv/bin/python launch.py`
With a ~1 minute break and an app holding the mic (or fullscreen), confirm the chip shows "Ignore <App>", clicking it releases the hold within a tick, and the break fires. Confirm `app_ignore_added` with `"source": "chip"` in `events.dev.jsonl`, and the entry in `…dev.json` prefs.

- [ ] **Step 6: Commit**

```bash
git add launch.py
git commit -m "Holding chip offers a one-click 'Ignore <app>' for the app causing the deferral"
```

---

### Task 9: Settings — review and remove ignored apps

**Files:**
- Modify: `launch.py` — Smart pausing section (~3251-3258)
- Test: manual (Tk UI; the pure list logic is already covered by Tasks 1 and 7)

**Interfaces:**
- Consumes: `_ignores`, `_toggle_ignore` (Task 7), `DEFAULT_*_IGNORED_APPS` (Task 1).
- Produces: `BreakApp._build_ignore_list(parent, signal)`.

- [ ] **Step 1: Add the sub-list builder**

Add to `BreakApp`, following the nesting pattern already used under "Wait until you pause" (indent + left hairline):

```python
    def _build_ignore_list(self, parent, signal):
        """The 'Ignore these apps' sub-block under a defer toggle.

        Rows are built from the built-ins the user has not removed, plus the
        user's own additions, so what the list shows is exactly what `_ignores()`
        applies. Rebuilt in place after every change.
        """
        subwrap = ctk.CTkFrame(parent, fg_color="transparent")
        subwrap.pack(fill="x", anchor="w",
                     padx=(PADDING_PANEL_X + SETTINGS_SUBOPTION_INDENT, PADDING_PANEL_X),
                     pady=(0, PADDING_PANEL_Y))
        ctk.CTkFrame(subwrap, width=SETTINGS_SUBOPTION_RULE_W, height=1,
                     fg_color=COLORS['border']).pack(side="left", fill="y")
        block = ctk.CTkFrame(subwrap, fg_color="transparent")
        block.pack(side="left", fill="x", expand=True, padx=(SPACE_SM, 0))

        def render():
            for child in block.winfo_children():
                child.destroy()
            ctk.CTkLabel(block, text="Ignore these apps", font=make_font('caption'),
                         text_color=COLORS['text_tertiary']).pack(
                anchor="w", pady=(0, SPACE_XXS))
            ignored = self._ignores(signal)
            builtins = (app_rules.DEFAULT_MIC_IGNORED_APPS if signal == app_rules.MIC
                        else app_rules.DEFAULT_FULLSCREEN_IGNORED_APPS)
            added = (self.mic_ignored_apps if signal == app_rules.MIC
                     else self.fullscreen_ignored_apps)
            rows = [(a, True) for a in builtins
                    if app_rules.normalize_app(a.get("id"), a.get("name")) in ignored]
            rows += [(a, False) for a in added]
            if not rows:
                ctk.CTkLabel(block, text="None — every app defers your breaks",
                             font=make_font('caption'),
                             text_color=COLORS['text_tertiary']).pack(anchor="w")
            for app_ref, is_builtin in rows:
                row = ctk.CTkFrame(block, fg_color="transparent")
                row.pack(fill="x", anchor="w", pady=(0, SPACE_XXS))
                label = app_ref.get("name") + (" (built-in)" if is_builtin else "")
                ctk.CTkLabel(row, text=label, font=make_font('label')).pack(side="left")
                ctk.CTkButton(
                    row, text="✕", width=IGNORE_ROW_REMOVE_W, height=CHIP_ACTION_HEIGHT,
                    fg_color="transparent", hover_color=COLORS['surface_hover'],
                    text_color=COLORS['text_secondary'], font=make_font('caption'),
                    command=lambda a=app_ref: self._remove_ignore_row(
                        signal, a, render)).pack(side="right")
            ctk.CTkButton(
                block, text="+ Add app", width=0, height=CHIP_ACTION_HEIGHT,
                fg_color="transparent", hover_color=COLORS['surface_hover'],
                text_color=COLORS['accent_primary'], font=make_font('caption'),
                command=lambda: self._open_app_picker(signal, render)).pack(anchor="w")

        render()
        return render

    def _remove_ignore_row(self, signal, app_ref, render):
        """Un-ignore one app, then rebuild the list on the next event-loop turn.

        The rebuild destroys the very button whose command is running, so it must
        NOT happen inline — `after(0, …)` lets the click finish first.
        """
        self._toggle_ignore(signal, app_ref, ignore=False, source="settings")
        self.after(0, render)
```

Add the token beside `CHIP_ACTION_HEIGHT`:

```python
IGNORE_ROW_REMOVE_W = 24    # ✕ button on an ignored-app row
```

- [ ] **Step 2: Mount it under both toggles**

In the Smart pausing section, after each checkbox:

```python
        _checkbox(smart.body, "Pause breaks while microphone is in use",
                  self.defer_during_meetings)
        self._build_ignore_list(smart.body, app_rules.MIC)
        _checkbox(smart.body, "Pause breaks during fullscreen",
                  self.defer_during_fullscreen)
        self._build_ignore_list(smart.body, app_rules.FULLSCREEN)
```

- [ ] **Step 3: Temporary stub so the section renders before Task 10**

```python
    def _open_app_picker(self, signal, on_done):
        """Chooser of running apps — implemented in Task 10."""
        return None
```

- [ ] **Step 4: Run the suite and the app**

Run: `DFYB_DEV=1 .venv/bin/python -m pytest -q` then relaunch the dev app.
Expected: tests PASS; Settings > Smart pausing shows four built-in mic rows tagged `(built-in)` and "None — every app defers your breaks" under fullscreen. Removing a built-in makes it disappear and survives a relaunch.

- [ ] **Step 5: Commit**

```bash
git add launch.py
git commit -m "Settings: review and remove the apps excused from mic and fullscreen deferral"
```

---

### Task 10: Settings — add an app from the running apps

**Files:**
- Modify: `dfyb/activity/sensors.py` (running-app enumeration)
- Modify: `launch.py` (`_open_app_picker`)
- Test: `tests/test_sensors.py`

**Interfaces:**
- Consumes: `_toggle_ignore` (Task 7), `_build_ignore_list`'s `render` callback (Task 9).
- Produces: `sensors.running_gui_apps() -> list[(bundle_id, name)]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sensors.py`:

```python
def test_running_gui_apps_off_macos_is_empty(monkeypatch):
    monkeypatch.setattr(sensors.sys, "platform", "linux")
    assert sensors.running_gui_apps() == []


def test_running_gui_apps_sorted_and_regular_only(monkeypatch):
    class _App:
        def __init__(self, policy, bundle, name):
            self._p, self._b, self._n = policy, bundle, name
        def activationPolicy(self):
            return self._p
        def bundleIdentifier(self):
            return self._b
        def localizedName(self):
            return self._n

    fake_workspace = types.SimpleNamespace(
        sharedWorkspace=lambda: types.SimpleNamespace(
            runningApplications=lambda: [
                _App(0, "us.zoom.xos", "Zoom"),
                _App(1, "com.apple.dock", "Dock"),        # accessory -> filtered out
                _App(0, "com.apple.Safari", "Safari"),
            ]))
    monkeypatch.setattr(sensors.sys, "platform", "darwin")
    monkeypatch.setitem(sys.modules, "AppKit",
                        types.SimpleNamespace(NSWorkspace=fake_workspace,
                                              NSApplicationActivationPolicyRegular=0))
    assert sensors.running_gui_apps() == [("com.apple.Safari", "Safari"),
                                          ("us.zoom.xos", "Zoom")]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `DFYB_DEV=1 .venv/bin/python -m pytest tests/test_sensors.py -k running_gui -q`
Expected: FAIL — `AttributeError: module 'dfyb.activity.sensors' has no attribute 'running_gui_apps'`

- [ ] **Step 3: Implement**

Add to `dfyb/activity/sensors.py`:

```python
def running_gui_apps():
    """[(bundle_id, name)] for the regular (Dock-visible) apps running now, sorted
    by name — the candidate list for the 'Ignore these apps' picker. Agents and
    daemons are excluded: they are not what a user recognizes or wants to pick.
    Empty on non-macOS or any failure."""
    if sys.platform != "darwin":
        return []
    try:
        from AppKit import NSWorkspace, NSApplicationActivationPolicyRegular
        apps = []
        for app in NSWorkspace.sharedWorkspace().runningApplications():
            if app.activationPolicy() != NSApplicationActivationPolicyRegular:
                continue
            apps.append((app.bundleIdentifier(), app.localizedName() or ""))
        return sorted(apps, key=lambda a: (a[1] or "").lower())
    except Exception:
        return []
```

- [ ] **Step 4: Implement the picker in launch.py**

Replace the Task 9 stub:

```python
    def _open_app_picker(self, signal, on_done):
        """Modal chooser of the running apps, for adding one to an ignore list.

        Deliberately lists only running apps: an app you can see is one you can
        recognize, and the chip covers the "it just happened" case anyway.
        """
        picker = ctk.CTkToplevel(self)
        picker.title("Choose an app")
        picker.geometry(f"{APP_PICKER_W}x{APP_PICKER_H}")
        picker.transient(self)
        picker.grab_set()
        scroll = ctk.CTkScrollableFrame(picker, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=SPACE_SM, pady=SPACE_SM)

        def choose(bundle_id, name):
            self._toggle_ignore(signal, {"id": bundle_id, "name": name},
                                ignore=True, source="settings")
            picker.destroy()
            self.after(0, on_done)   # rebuild the row list off the click, not inline

        ignored = self._ignores(signal)
        for bundle_id, name in sensors_running_gui_apps():
            if app_rules.normalize_app(bundle_id, name) in ignored:
                continue
            ctk.CTkButton(
                scroll, text=name, anchor="w", height=BUTTON_HEIGHT_SMALL,
                fg_color="transparent", hover_color=COLORS['surface_hover'],
                text_color=COLORS['text_primary'], font=make_font('label'),
                command=lambda b=bundle_id, n=name: choose(b, n)).pack(fill="x")
```

Import it at the top of `launch.py` (aliased to keep the existing import line readable):

```python
from dfyb.activity.sensors import (read_context, frontmost_window_rect, smooth_signal,
                                   running_gui_apps as sensors_running_gui_apps)
```

Add the tokens to the CONFIGURATION block beside the other window sizes:

```python
APP_PICKER_W = 320          # "Choose an app" modal width
APP_PICKER_H = 420          # "Choose an app" modal height
```

Confirm `BUTTON_HEIGHT_SMALL` exists in the CONFIGURATION block; if it does not, use the nearest existing button-height token rather than a literal.

- [ ] **Step 5: Run the suite**

Run: `DFYB_DEV=1 .venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 6: Verify in the real app**

Relaunch the dev app, open Settings > Smart pausing > **+ Add app**, pick a running app, and confirm it appears as a row, persists across a relaunch, and logs `app_ignore_added` with `"source": "settings"`.

- [ ] **Step 7: Commit**

```bash
git add dfyb/activity/sensors.py launch.py tests/test_sensors.py
git commit -m "Settings: add an app to an ignore list from a picker of running apps"
```

---

### Task 11: Close the loop on the issues

**Files:** none (GitHub only)

- [ ] **Step 1: Comment on #40 with the root cause**

```bash
GH_CONFIG_DIR=~/.config/gh-personal gh issue comment 40 --body "Root cause confirmed 2026-09-01: the System Settings Sound pane (\`Sound.appex\`, bundle id \`com.apple.Sound-Settings.extension\`) held the audio input for 18h27m after its window was closed, so every break deferred as 'you're in a call'. Fixed by process-level attribution (\`kAudioHardwarePropertyProcessObjectList\` + \`kAudioProcessPropertyIsRunningInput\`, macOS 14+, with a documented fallback), a built-in ignore list, and per-app ignore lists. The UI now names the app instead of asserting a call. The suspected FALSE NEGATIVE (muting a call may release the input device) is NOT addressed here and needs its own issue."
```

- [ ] **Step 2: Open the follow-up for the false negative**

```bash
GH_CONFIG_DIR=~/.config/gh-personal gh issue create --title "Mic deferral false negative: muting a call may release the input device" --body "Split out of #40, whose false-POSITIVE half is fixed by per-app attribution. Suspected: muting in Zoom/Meet stops the input device, so \`microphone_in_use()\` reads false and a break fires mid-call. Needs a probe (does \`kAudioProcessPropertyIsRunningInput\` stay true while muted?) before choosing a fix — candidates in #40 are camera-in-use and known-meeting-app signals."
```

- [ ] **Step 3: Close #40, leave #28 open**

```bash
GH_CONFIG_DIR=~/.config/gh-personal gh issue close 40
GH_CONFIG_DIR=~/.config/gh-personal gh issue comment 28 --body "Partially served: \`dfyb/activity/app_rules.py\` now holds per-app ignore lists for the mic and fullscreen defer signals, with a Settings UI. That module is the seam this issue's full rules table (per-app break intervals / break sets / frontmost-app conditions) should grow from — the ignore lists become one rule kind, no prefs migration needed. Staying open for the table."
```

---

## Self-Review

**Spec coverage:** §4.1 → Task 2; §4.1a → Task 3; §4.2 → Task 1; §4.3 → Tasks 4-5; §4.4 → Task 7; §4.5 → Tasks 6, 8, 9, 10; §5 → Task 7; §6 → Tasks 5, 6, 7; §7 → tests in every task; §8 phases → Tasks 1-6 (phase 1), 7-8 (phase 2), 9-10 (phase 3); §9 → Task 11; §10 → Task 1 Step 6.

**Type consistency:** the holder tuple `(pid, bundle_id, name)` is produced by `mic_input_processes()` (Task 2) and `fullscreen_state()` (Task 3), consumed by `surviving_holders` / `primary_holder` (Task 1) and `_attributed` (Task 4). The app ref `{"id", "name"}` is produced by `holder_ref` (Task 1) and stored in prefs (Task 7), extended to `{"id", "name", "count"}` on `Context` (Task 4) and flattened to `app` / `app_name` / `holder_count` on the event (Task 5). `signal` is always `app_rules.MIC` / `app_rules.FULLSCREEN` (`"mic"` / `"fullscreen"`).

**Known risk to watch:** Task 3's `fullscreen_state()` calls `_app_identity()` once per covered display, which for a non-GUI owner reads an `Info.plist`. If profiling ever shows this on the tick path, cache by pid — deliberately not done now, since covered displays are 0-2 and GUI apps resolve through NSRunningApplication with no file I/O.

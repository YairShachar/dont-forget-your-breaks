"""macOS context sensors (idle time, fullscreen) for the scheduler.

Best-effort: on non-macOS or any failure, returns safe defaults (idle=0.0,
fullscreen=False) so the scheduler falls back to today's 'always fire' behavior.
`Quartz` is imported lazily inside each function so this module imports cleanly
on non-macOS CI (where Quartz is absent).
"""
import logging
import struct
import sys

from dfyb.activity import app_rules
from dfyb.scheduler.engine import Context

# Max active displays to enumerate (well above any real Mac's monitor count).
MAX_DISPLAYS = 16
# Byte size of a CoreAudio UInt32 property value (matches the struct "I" format).
UINT32_SIZE = 4
# A window counts as covering a display if it reaches each edge within this many
# points — absorbs rounding between window bounds and display bounds.
FULLSCREEN_COVER_TOLERANCE_PX = 2
# Once a defer signal (fullscreen / mic-in-use / active-input) is really observed,
# keep treating it as present for this many subsequent ticks even if the raw signal
# drops out for a sample. Bridges brief dropouts — a Space-to-Space swipe hiding the
# covering window (#46), a per-utterance mic-device stop, a momentary typing pause —
# so a due break doesn't fire into the gap (#84).
DEFER_GRACE_TICKS = 3


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
# How many pid -> identity results `_app_identity` keeps. Small on purpose: the
# sensors ask about a handful of pids, over and over, once a second.
APP_IDENTITY_CACHE_MAX = 64


def idle_seconds():
    """Seconds since the last user input event (macOS). 0.0 elsewhere / on failure."""
    if sys.platform != "darwin":
        return 0.0
    try:
        import Quartz
        return float(Quartz.CGEventSourceSecondsSinceLastEventType(
            Quartz.kCGEventSourceStateHIDSystemState,
            Quartz.kCGAnyInputEventType,
        ))
    except Exception:
        return 0.0


def _event_idle_seconds(Quartz, event_type):
    return float(Quartz.CGEventSourceSecondsSinceLastEventType(
        Quartz.kCGEventSourceStateHIDSystemState, event_type))


def active_idle_seconds(include_mouse_move=False):
    """Seconds since the last MEANINGFUL input for wait-until-you-pause:
    keyboard + clicks + scroll (+ mouse-move only if include_mouse_move). Bare
    cursor movement is excluded by default — it's noise, not 'busy working'.
    Falls back to idle_seconds() on non-macOS / failure (never worse than today).
    """
    if sys.platform != "darwin":
        return idle_seconds()
    try:
        import Quartz
        types = [Quartz.kCGEventKeyDown, Quartz.kCGEventFlagsChanged,
                 Quartz.kCGEventLeftMouseDown, Quartz.kCGEventRightMouseDown,
                 Quartz.kCGEventScrollWheel]
        if include_mouse_move:
            types.append(Quartz.kCGEventMouseMoved)
        return min(_event_idle_seconds(Quartz, t) for t in types)
    except Exception:
        return idle_seconds()


def _covers_interval(intervals, lo, hi, tol=FULLSCREEN_COVER_TOLERANCE_PX):
    """Do the (start, end) intervals union-cover [lo, hi]? Pure 1D coverage."""
    cursor = lo
    for start, end in sorted(intervals):
        if start > cursor + tol:
            return False  # gap before this interval -> not fully covered
        cursor = max(cursor, end)
        if cursor >= hi - tol:
            return True
    return cursor >= hi - tol


def _display_is_covered(windows, display, tol=FULLSCREEN_COVER_TOLERANCE_PX):
    """True if `windows` together cover `display` top to bottom.

    A native-fullscreen app can present as SEVERAL windows (e.g. thin auto-hide
    top strips at y=0 plus a content pane below them), so no single window fills
    the display — but the full-width windows' vertical extents union to the full
    height. This checks exactly that. A plain maximized window (content starting
    below the menu bar, with no top strip) leaves a top gap and is NOT counted.
    Each rect is (x, y, w, h) in global points.
    """
    dx, dy, dw, dh = display
    intervals = []
    for wx, wy, ww, wh in windows:
        spans_width = wx <= dx + tol and wx + ww >= dx + dw - tol
        if not spans_width:
            continue
        top = max(wy, dy)
        bottom = min(wy + wh, dy + dh)
        if bottom > top:
            intervals.append((top, bottom))
    return _covers_interval(intervals, dy, dy + dh, tol)


def covers_any_display(windows, displays, tol=FULLSCREEN_COVER_TOLERANCE_PX):
    """True if any display is fully covered (native fullscreen) by the windows.

    Handles fullscreen apps that split into a top strip + content pane, not just
    single-window fullscreen. Pure (no Quartz), so it is unit-tested off macOS."""
    return any(_display_is_covered(windows, d, tol) for d in displays)


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


def _active_display_rects(Quartz):
    """(x, y, w, h) in points for every active display."""
    _err, ids, count = Quartz.CGGetActiveDisplayList(MAX_DISPLAYS, None, None)
    rects = []
    for display_id in list(ids)[:count]:
        bounds = Quartz.CGDisplayBounds(display_id)
        rects.append((bounds.origin.x, bounds.origin.y,
                      bounds.size.width, bounds.size.height))
    return rects


def _layer0_window_rects(Quartz):
    """(x, y, w, h) in points for each on-screen normal (layer-0) window."""
    windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly
        | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID,
    )
    rects = []
    for window in windows:
        if window.get("kCGWindowLayer", 1) != 0:
            continue  # skip menu bar, dock, overlays — only normal app windows
        bounds = window.get("kCGWindowBounds", {})
        rects.append((bounds.get("X", 0.0), bounds.get("Y", 0.0),
                      bounds.get("Width", 0.0), bounds.get("Height", 0.0)))
    return rects


def frontmost_is_fullscreen():
    """Best-effort: is any app in native fullscreen on ANY display?

    True when a normal (layer-0) on-screen window fully covers one of the active
    displays — handles multiple monitors of different sizes and offsets, and a
    thin auto-hide bar sitting in front of the fullscreen window. False on
    non-macOS or any failure (fails safe — 'not fullscreen' => fire).
    """
    if sys.platform != "darwin":
        return False
    try:
        import Quartz
        displays = _active_display_rects(Quartz)
        windows = _layer0_window_rects(Quartz)
        return covers_any_display(windows, displays)
    except Exception:
        return False


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


def smooth_signal(raw_on, grace_left, grace_ticks=DEFER_GRACE_TICKS):
    """Hysteresis over transient dropouts of any boolean defer signal (fullscreen,
    mic-in-use, active-input).

    Pure and tick-based (no clock) so it is unit-tested off macOS. Once the signal
    is really observed, it 'sticks' for up to `grace_ticks` subsequent ticks even
    if the raw reading drops out. Returns (effective_on, new_grace_left); the caller
    carries `new_grace_left` into the next tick.
    """
    if raw_on:
        return True, grace_ticks
    if grace_left > 0:
        return True, grace_left - 1
    return False, 0


def any_input_device_running(device_states):
    """Given `(has_input, is_running)` per audio device, True if any INPUT-capable
    device is running — i.e. the mic is in use by some app, on ANY device (not
    just the system default). Pure; the CoreAudio enumeration builds the list.
    Output devices (music/speakers) must not count, hence the `has_input` gate."""
    return any(has_input and is_running for has_input, is_running in device_states)


def microphone_in_use():
    """True if any INPUT-capable audio device is running somewhere (~ a mic in a
    call/recording). Enumerates ALL devices, not just the system default input —
    a call routed through AirPods/a headset/another device was missed before (#40).
    False on non-macOS or any failure (fails safe)."""
    if sys.platform != "darwin":
        return False
    try:
        import CoreAudio as CA
        import objc

        def _addr(selector, scope=CA.kAudioObjectPropertyScopeGlobal):
            return CA.AudioObjectPropertyAddress(
                selector, scope, CA.kAudioObjectPropertyElementMain)

        def _is_running(device):
            # qualifier MUST be objc.NULL; out-param MUST be None (pyobjc allocates it).
            status, _size, data = CA.AudioObjectGetPropertyData(
                device, _addr(CA.kAudioDevicePropertyDeviceIsRunningSomewhere),
                0, objc.NULL, UINT32_SIZE, None)
            return status == 0 and struct.unpack("I", bytes(data))[0] != 0

        def _has_input(device):
            # An input-capable device has ≥1 input stream (bytes > 0 in input scope).
            status, size = CA.AudioObjectGetPropertyDataSize(
                device, _addr(CA.kAudioDevicePropertyStreams,
                              CA.kAudioObjectPropertyScopeInput),
                0, objc.NULL, None)
            return status == 0 and size > 0

        status, size = CA.AudioObjectGetPropertyDataSize(
            CA.kAudioObjectSystemObject,
            _addr(CA.kAudioHardwarePropertyDevices), 0, objc.NULL, None)
        count = size // UINT32_SIZE
        if status != 0 or count <= 0:
            return False
        status, _size, raw = CA.AudioObjectGetPropertyData(
            CA.kAudioObjectSystemObject, _addr(CA.kAudioHardwarePropertyDevices),
            0, objc.NULL, size, None)
        if status != 0:
            return False
        device_ids = struct.unpack("%dI" % count, bytes(raw)[:count * UINT32_SIZE])

        return any_input_device_running(
            [(_has_input(d), _is_running(d)) for d in device_ids])
    except Exception as e:
        # Was failing SILENTLY to "no mic" — log so this class of miss is visible.
        logging.debug("microphone_in_use() failed, assuming mic free: %s", e)
        return False


_LIBSYSTEM = None
# pid -> (bundle_id, name). A LIVE pid's identity cannot change, and the sensors
# re-ask about the same pids every tick, so this is a pure win. See
# `_cache_identity` for why the (rare) pid-reuse window is safe.
_IDENTITY_CACHE = {}


def _libsystem():
    """The process-wide libSystem handle, opened once.

    ctypes never dlcloses a CDLL and each instance grows its own function-pointer
    cache, so building one per call leaked on the once-a-second sensor path —
    exactly the path an .appex or daemon mic holder takes (#40 final review).
    `argtypes`/`restype` are declared here, once, instead of per call.
    """
    global _LIBSYSTEM
    if _LIBSYSTEM is None:
        import ctypes
        lib = ctypes.CDLL("/usr/lib/libSystem.dylib")
        lib.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        lib.proc_pidpath.restype = ctypes.c_int
        _LIBSYSTEM = lib
    return _LIBSYSTEM


def _cache_identity(pid, identity):
    """Memoize one pid's identity, keeping the cache bounded.

    A cache entry can only go stale if the pid exits AND the OS reuses that
    number AND the new process starts holding the mic / covering a display —
    and even then the worst case is one mis-named app for one deferral episode.
    The window is kept small without an eviction policy: the whole cache is
    dropped when it reaches `APP_IDENTITY_CACHE_MAX`, and `forget_app_identities`
    clears it whenever nothing holds the mic at all (the ordinary gap between
    calls). Rebuilding costs one lookup per live pid.
    """
    if len(_IDENTITY_CACHE) >= APP_IDENTITY_CACHE_MAX:
        _IDENTITY_CACHE.clear()
    _IDENTITY_CACHE[pid] = identity
    return identity


def forget_app_identities():
    """Drop every memoized pid identity. Called when no process holds the audio
    input, which is both the natural cache boundary and the moment pid reuse
    stops mattering."""
    _IDENTITY_CACHE.clear()


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
    import ctypes
    if pid in _IDENTITY_CACHE:
        return _IDENTITY_CACHE[pid]
    try:
        from AppKit import NSRunningApplication
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is not None:
            return _cache_identity(
                pid, (app.bundleIdentifier(), app.localizedName() or str(pid)))
    except Exception as e:
        # Was failing SILENTLY to the libproc fallback — log so this class of
        # miss is visible (same reasoning as microphone_in_use()).
        logging.debug("NSRunningApplication lookup failed for pid %s: %s", pid, e)
    try:
        buf = ctypes.create_string_buffer(PROC_PATH_MAX)
        if _libsystem().proc_pidpath(pid, buf, PROC_PATH_MAX) > 0:
            return _cache_identity(pid, _bundle_identity_from_path(
                buf.value.decode("utf-8", "replace")))
    except Exception as e:
        # Was failing SILENTLY to a bare "pid N" label — log it.
        logging.debug("proc_pidpath lookup failed for pid %s: %s", pid, e)
    return _cache_identity(pid, (None, "pid %d" % pid))


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
            forget_app_identities()
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
        if not holders:
            # Nothing holds the input: the ordinary gap between calls, and the
            # cheapest moment to drop every memoized pid (see `_cache_identity`).
            forget_app_identities()
        return holders
    except Exception as e:
        logging.debug("mic_input_processes() failed, attribution unavailable: %s", e)
        return None


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
    except Exception as e:
        # Was failing SILENTLY to an empty picker, indistinguishable from "no apps
        # are running" — log so this class of miss is visible.
        logging.debug("running_gui_apps() failed, offering no candidates: %s", e)
        return []


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

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

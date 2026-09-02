from dfyb.popup_placement import main_window_geometry

SCREEN = (0, 0, 1000, 800)   # x, y, w, h


def test_remembered_restores_saved_position():
    assert main_window_geometry(300, 200, "remembered", "+120+90", SCREEN) == "300x200+120+90"


def test_remembered_without_saved_is_size_only():
    assert main_window_geometry(300, 200, "remembered", None, SCREEN) == "300x200"


def test_active_centers_on_screen_ignoring_saved():
    # centered: x = (1000-300)//2 = 350, y = (800-200)//2 = 300
    assert main_window_geometry(300, 200, "active", "+120+90", SCREEN) == "300x200+350+300"


def test_active_on_offset_screen():
    scr = (1000, 100, 800, 600)   # a second monitor to the right
    # x = 1000 + (800-300)//2 = 1250 ; y = 100 + (600-200)//2 = 300
    assert main_window_geometry(300, 200, "active", None, scr) == "300x200+1250+300"


def test_active_without_screen_falls_back():
    # no screen (non-macOS / detection failed) -> size-only, no crash
    assert main_window_geometry(300, 200, "active", None, None) == "300x200"


def test_active_without_screen_but_saved_uses_saved():
    assert main_window_geometry(300, 200, "active", "+10+10", None) == "300x200+10+10"


# --- a refit only resizes: never yank a window the user has moved -------------

def test_refit_is_size_only_even_with_a_saved_position():
    assert main_window_geometry(300, 240, "remembered", "+120+90", SCREEN,
                                place=False) == "300x240"


def test_refit_does_not_recenter_in_active_mode():
    assert main_window_geometry(300, 240, "active", None, SCREEN,
                                place=False) == "300x240"

from dfyb.popup_placement import (screen_for_point, center_on_screen, clamp_onscreen,
                                  clamp_saved_position)

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


# --- main window: a saved position must survive a monitor change (#67 carry-over) ---
W, H = 380, 300


def test_saved_position_on_a_gone_monitor_is_pulled_onto_the_primary():
    # the real bug: '+2008+140' saved on a second display, reopened on a 1920 primary
    assert clamp_saved_position(W, H, "+2008+140", [MAIN]) == f"+{1920 - W}+140"


def test_saved_position_on_a_connected_second_screen_is_kept():
    assert clamp_saved_position(W, H, "+2100+200", SCREENS) == "+2100+200"


def test_saved_position_fully_inside_is_unchanged():
    assert clamp_saved_position(W, H, "+100+200", SCREENS) == "+100+200"


def test_saved_position_hanging_off_its_own_screen_is_pulled_fully_inside():
    assert clamp_saved_position(W, H, "+100+1000", [MAIN]) == f"+100+{1080 - H}"


def test_negative_saved_position_is_pulled_onto_the_primary():
    assert clamp_saved_position(W, H, "+-400+-50", SCREENS) == "+0+0"


def test_without_screen_info_the_saved_position_is_left_alone():
    assert clamp_saved_position(W, H, "+2008+140", []) == "+2008+140"


def test_an_unparseable_position_is_left_alone():
    assert clamp_saved_position(W, H, None, SCREENS) is None
    assert clamp_saved_position(W, H, "+100", SCREENS) == "+100"

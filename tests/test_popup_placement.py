from dfyb.popup_placement import screen_for_point, center_on_screen, clamp_onscreen

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

from dfyb.geometry import point_in_rect

# A 22x26 button at screen origin (100, 200) — the play-button footprint.
X, Y, W, H = 100, 200, 22, 26


def test_center_is_inside():
    assert point_in_rect(X + W // 2, Y + H // 2, X, Y, W, H)


def test_top_left_corner_inclusive():
    assert point_in_rect(X, Y, X, Y, W, H)


def test_right_and_bottom_edges_exclusive():
    # x+w and y+h are the first pixels NOT covered by the widget.
    assert not point_in_rect(X + W, Y, X, Y, W, H)
    assert not point_in_rect(X, Y + H, X, Y, W, H)


def test_pointer_left_the_window_is_outside():
    # The stuck-tooltip case: pointer moved far away (e.g. onto another app)
    # without a <Leave> event. Geometry still reports "not over the button".
    assert not point_in_rect(X - 500, Y - 500, X, Y, W, H)
    assert not point_in_rect(X + 500, Y + 500, X, Y, W, H)


def test_just_outside_each_side():
    assert not point_in_rect(X - 1, Y, X, Y, W, H)          # left
    assert not point_in_rect(X, Y - 1, X, Y, W, H)          # above

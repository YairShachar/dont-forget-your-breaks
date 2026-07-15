from dfyb.ring import ring_image

TRACK = (200, 200, 205, 255)
PROG = (10, 132, 255, 255)


def test_returns_rgba_at_requested_size():
    im = ring_image(0.5, 120, 10, TRACK, PROG)
    assert im.mode == "RGBA"
    assert im.size == (120, 120)


def test_full_ring_has_more_progress_pixels_than_empty():
    def prog_pixels(frac):
        im = ring_image(frac, 120, 10, TRACK, PROG)
        return sum(1 for px in im.getdata() if px[:3] == PROG[:3] and px[3] > 128)
    assert prog_pixels(1.0) > prog_pixels(0.25) > prog_pixels(0.0)


def test_frac_clamped():
    # out-of-range fractions must not raise and must stay within a full ring
    assert ring_image(-0.5, 80, 8, TRACK, PROG).size == (80, 80)
    assert ring_image(9.0, 80, 8, TRACK, PROG).size == (80, 80)

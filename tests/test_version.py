from dfyb.version import parse_version, is_newer_version


def test_parse_basic():
    assert parse_version("1.2.3") == (1, 2, 3)


def test_parse_strips_leading_v():
    assert parse_version("v1.0.13") == (1, 0, 13)


def test_parse_invalid_returns_zeros():
    assert parse_version("not-a-version") == (0, 0, 0)
    assert parse_version(None) == (0, 0, 0)


def test_is_newer_true():
    assert is_newer_version("1.0.13", "1.0.12") is True


def test_is_newer_false_when_equal():
    assert is_newer_version("1.0.13", "1.0.13") is False


def test_is_newer_false_when_older():
    assert is_newer_version("1.0.11", "1.0.13") is False

"""Pure version-string helpers (no Tk, no I/O)."""


def parse_version(version_str):
    """Parse a version string like '1.0.3' into a tuple of ints for comparison."""
    try:
        return tuple(int(x) for x in version_str.lstrip('v').split('.'))
    except (ValueError, AttributeError):
        return (0, 0, 0)


def is_newer_version(latest, current):
    """Return True if latest version is newer than current."""
    return parse_version(latest) > parse_version(current)

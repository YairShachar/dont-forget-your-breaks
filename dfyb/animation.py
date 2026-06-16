"""Easing helpers and the macOS reduced-motion preference check."""
import subprocess
import sys


def ease_out_quad(t):
    """Quadratic ease-out: fast start, slow end."""
    return t * (2 - t)


def ease_in_quad(t):
    """Quadratic ease-in: slow start, fast end."""
    return t * t


def prefers_reduced_motion():
    """Check if user has enabled reduced motion (macOS)."""
    if sys.platform != "darwin":
        return False
    try:
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleReduceMotion"],
            capture_output=True, text=True
        )
        return result.stdout.strip() == "1"
    except Exception:
        return False

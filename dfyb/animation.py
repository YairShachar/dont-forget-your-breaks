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


def lerp_color(color_a, color_b, t):
    """Linear-interpolate two '#rrggbb' hex colors; `t` is clamped to [0, 1]."""
    t = max(0.0, min(1.0, t))
    a, b = color_a.lstrip("#"), color_b.lstrip("#")
    channels = [
        round(int(a[i:i + 2], 16) + (int(b[i:i + 2], 16) - int(a[i:i + 2], 16)) * t)
        for i in (0, 2, 4)
    ]
    return "#{:02x}{:02x}{:02x}".format(*channels)

"""Pure logic for the settings window (no Tk, so unit-testable)."""


def suboption_state(parent_on):
    """The Tk widget `state` for a sub-option gated by its parent toggle.

    A nested option (e.g. "also count mouse movement" under "Wait until you
    pause") is only meaningful when its parent is enabled; when the parent is
    off the child is shown disabled/greyed rather than hidden, so the user can
    see it exists.
    """
    return "normal" if parent_on else "disabled"

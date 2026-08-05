"""Pure UI-control styling helpers (no Tk / no COLORS import — take a token map).

Kept out of launch.py so the enabled/disabled affordance logic is unit-testable
headlessly (CI has no display).
"""

# A hairline border on the ENABLED Reset button so it reads as a real (outlined)
# secondary control — the fill alone is too subtle on a white card in light mode.
RESET_ENABLED_BORDER_WIDTH = 1
RESET_DISABLED_BORDER_WIDTH = 0


def reset_button_style(enabled, colors):
    """CTk appearance kwargs for the main-window Reset button per state (#70).

    Enabled reads as a raised, outlined, readable secondary button; disabled recedes
    into the card (flat fill, no border, faded text) so the affordance visibly changes
    with state instead of looking 'always grey'. `colors` is the app's design-token map.
    """
    if enabled:
        return {
            "state": "normal",
            "fg_color": colors["surface_hover"],       # raised above the card
            "text_color": colors["text_secondary"],    # readable
            "hover_color": colors["border"],
            "border_width": RESET_ENABLED_BORDER_WIDTH,  # outlined → clearly a button
            "border_color": colors["border"],
        }
    return {
        "state": "disabled",
        "fg_color": colors["surface_card"],            # sinks into the card → inert
        "text_color": colors["text_tertiary"],         # faded
        "hover_color": colors["surface_card"],         # no hover cue when disabled
        "border_width": RESET_DISABLED_BORDER_WIDTH,   # flat, no outline
        "border_color": colors["surface_card"],
    }

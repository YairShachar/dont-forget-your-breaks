"""Pure decision logic for the 'you're back — resume?' prompt while paused (#77).

No Tk / no sensors — the loop passes in the sampled context, so this is unit-tested
headlessly.
"""


def resume_prompt_step(streak, active_idle, is_meeting, active_threshold,
                       required, already_prompted):
    """Decide, one sample at a time, whether to prompt the user to resume breaks.

    The user is "clearly back" this sample when they're in a meeting OR recently active
    (typing/clicks → `active_idle < active_threshold`). Bare mouse-move is already
    excluded upstream by `active_idle_seconds`. Requires `required` CONSECUTIVE
    back-samples so a lone click won't fire it, and prompts at most once per pause
    episode (`already_prompted`). Pure — returns (new_streak, should_prompt).
    """
    back = bool(is_meeting) or (active_idle is not None and active_idle < active_threshold)
    new_streak = streak + 1 if back else 0
    should_prompt = (not already_prompted) and new_streak >= required
    return new_streak, should_prompt

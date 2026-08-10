from dfyb.resume import resume_prompt_step

TH = 2.0   # active_idle below this = recently active
REQ = 3    # consecutive back-samples required


def step(streak, active_idle=None, is_meeting=False, already=False):
    return resume_prompt_step(streak, active_idle, is_meeting, TH, REQ, already)


def test_sustained_typing_prompts_at_required():
    s, p = step(0, active_idle=0.0); assert (s, p) == (1, False)
    s, p = step(s, active_idle=0.5); assert (s, p) == (2, False)
    s, p = step(s, active_idle=0.0); assert (s, p) == (3, True)   # 3rd consecutive -> prompt


def test_lone_click_does_not_fire():
    s, p = step(0, active_idle=0.0); assert (s, p) == (1, False)  # one active sample
    s, p = step(s, active_idle=10.0); assert (s, p) == (0, False) # then idle -> streak resets


def test_meeting_counts_as_back_regardless_of_idle():
    s, p = step(0, active_idle=999.0, is_meeting=True); assert s == 1
    s, p = step(s, active_idle=999.0, is_meeting=True)
    s, p = step(s, active_idle=999.0, is_meeting=True); assert p is True


def test_idle_none_is_not_back():
    assert step(0, active_idle=None) == (0, False)


def test_prompts_at_most_once_per_episode():
    # already prompted -> never prompt again even while active
    s, p = step(5, active_idle=0.0, already=True)
    assert p is False

from dfyb.scheduler.reschedule import reschedule_step, reschedule_bounds, nudged_remaining


def test_reschedule_step_is_fraction_of_interval():
    assert reschedule_step(2400) == 600      # 40 min * 0.25 = 10 min
    assert reschedule_step(25) == 6          # 25 s * 0.25 = 6 s
    assert reschedule_step(2) == 1           # floors at 1 s


def test_reschedule_bounds():
    assert reschedule_bounds(2400) == (600, 4800)   # step 600 .. 2*2400


def test_nudged_remaining_clamps():
    assert nudged_remaining(2400, 600, 600, 4800) == 3000     # later
    assert nudged_remaining(2400, -600, 600, 4800) == 1800    # sooner
    assert nudged_remaining(700, -600, 600, 4800) == 600      # floor
    assert nudged_remaining(4500, 600, 600, 4800) == 4800     # ceiling

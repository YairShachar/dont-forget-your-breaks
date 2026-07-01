"""Regression tests for the timer-thread liveness rule.

Bug: pressing Reset then Start quickly could revive a previous timer thread —
both the old and new thread stayed alive, so breaks fired multiple times. The
fix gives each timer session a generation token; a thread only keeps running
while its own generation is the current one.
"""
from dfyb.timer_lifecycle import timer_should_continue


def test_current_generation_and_running_continues():
    assert timer_should_continue(
        running=True, stop_set=False, current_generation=3, my_generation=3
    ) is True


def test_stale_generation_stops_even_if_running_and_not_stopped():
    # The revival case: a previous thread whose session was superseded by a new
    # start(). running is True and stop is clear (start() re-armed them), but the
    # generation moved on, so the old thread must stop.
    assert timer_should_continue(
        running=True, stop_set=False, current_generation=4, my_generation=3
    ) is False


def test_not_running_stops():
    assert timer_should_continue(
        running=False, stop_set=False, current_generation=1, my_generation=1
    ) is False


def test_stop_set_stops():
    assert timer_should_continue(
        running=True, stop_set=True, current_generation=1, my_generation=1
    ) is False

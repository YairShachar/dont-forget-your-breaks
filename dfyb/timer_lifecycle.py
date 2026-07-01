"""Pure liveness rule for the app's single timer thread.

Each timer session started by ``BreakApp.start()`` gets a monotonically
increasing generation token. A running timer thread must stop the moment its
own generation is no longer the current one — this prevents a thread left over
from a previous session (revived when ``start()`` re-arms the shared
running/stop flags) from ticking alongside the new session's thread.
"""


def timer_should_continue(running, stop_set, current_generation, my_generation):
    """Return True only while this timer thread should keep ticking.

    A thread keeps running iff the app is running, no stop was requested, and
    this thread owns the current generation. A stale generation stops the
    thread even when ``running`` is True and ``stop_set`` is False (the
    start-after-reset revival case).
    """
    return running and not stop_set and current_generation == my_generation

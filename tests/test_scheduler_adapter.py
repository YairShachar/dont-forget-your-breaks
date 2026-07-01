from dfyb.scheduler.engine import BreakState
from dfyb.scheduler.adapter import states_from_configs


class FakeConfig:
    """Duck-typed stand-in for BreakConfig (no Tk needed)."""
    def __init__(self, remaining, interval, duration):
        self.remaining = remaining
        self._interval = interval
        self._duration = duration

    def get_interval_seconds(self):
        return self._interval

    def get_duration_seconds(self):
        return self._duration


def test_states_from_configs_maps_each_field():
    configs = [FakeConfig(5, 100, 5), FakeConfig(8, 200, 600)]
    states = states_from_configs(configs)
    assert states == [BreakState(5, 100, 5), BreakState(8, 200, 600)]


def test_states_from_configs_empty():
    assert states_from_configs([]) == []

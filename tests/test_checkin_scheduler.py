from dfyb.checkins import model as m
from dfyb.checkins.scheduler import due_question, CHECK_IN_SURFACE_PROB

WIN = 12 * 3600
MIN_GAP = 20 * 60


def q(qid, count=2, enabled=True):
    return m.Question(id=qid, text=qid,
                      answer=m.AnswerSpec(m.SCALE), cadence=m.Cadence(m.TIMES_PER_DAY, count),
                      enabled=enabled)


class Rng:                       # deterministic stub
    def __init__(self, v): self.v = v
    def random(self): return self.v


ALWAYS, NEVER = Rng(0.0), Rng(1.0)   # 0.0 < prob -> surface; 1.0 -> suppress


def call(questions, now, last_prompted, last_prompt_ts, deferring=False,
         in_window=True, rng=ALWAYS):
    return due_question(questions, now, last_prompted, last_prompt_ts, WIN,
                        in_window, deferring, MIN_GAP, rng)


def test_due_when_interval_elapsed():
    qq = q("refreshed")
    interval = m.cadence_interval_seconds(qq.cadence, WIN)      # 6h
    now = 100_000.0
    got = call([qq], now, {"refreshed": now - interval - 1}, now - MIN_GAP - 1)
    assert got is qq


def test_not_due_before_interval():
    qq = q("refreshed")
    now = 100_000.0
    assert call([qq], now, {"refreshed": now - 60}, now - MIN_GAP - 1) is None


def test_deferring_and_window_and_gap_suppress():
    qq = q("refreshed")
    now = 100_000.0
    lp = {"refreshed": 0.0}
    assert call([qq], now, lp, 0.0, deferring=True) is None
    assert call([qq], now, lp, 0.0, in_window=False) is None
    assert call([qq], now, lp, now - 1) is None                 # inside min-gap


def test_probability_makes_it_intermittent():
    qq = q("refreshed")
    now = 100_000.0
    lp = {"refreshed": 0.0}
    assert call([qq], now, lp, 0.0, rng=NEVER) is None          # eligible but suppressed
    assert call([qq], now, lp, 0.0, rng=ALWAYS) is qq


def test_picks_most_overdue():
    a, b = q("a"), q("b")
    now = 100_000.0
    lp = {"a": now - 7 * 3600, "b": now - 40 * 3600}            # b far more overdue
    assert call([a, b], now, lp, 0.0).id == "b"


def test_disabled_and_empty():
    assert call([], 100_000.0, {}, 0.0) is None
    assert call([q("a", enabled=False)], 100_000.0, {"a": 0.0}, 0.0) is None


def test_surface_prob_is_a_constant_in_unit_range():
    assert 0.0 < CHECK_IN_SURFACE_PROB <= 1.0

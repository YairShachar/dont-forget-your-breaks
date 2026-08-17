from dfyb.checkins import model as m
from dfyb.checkins.scheduler import due_break_check_in

WIN = 14 * 3600
MIN_GAP = 20 * 60


def q(qid, count=2, enabled=True, trigger=m.TRIGGER_BREAK, once_per_day=False):
    return m.Question(id=qid, text=qid, answer=m.AnswerSpec(m.SCALE),
                      cadence=m.Cadence(m.TIMES_PER_DAY, count), enabled=enabled,
                      trigger=trigger, once_per_day=once_per_day)


def call(questions, now, last_prompted, last_prompt_ts):
    return due_break_check_in(questions, now, last_prompted, last_prompt_ts, WIN, MIN_GAP)


def test_due_when_interval_elapsed():
    qq = q("refreshed")
    interval = m.cadence_interval_seconds(qq.cadence, WIN)      # 7h
    now = 100_000.0
    assert call([qq], now, {"refreshed": now - interval - 1}, now - MIN_GAP - 1) is qq


def test_not_due_before_interval():
    now = 100_000.0
    assert call([q("refreshed")], now, {"refreshed": now - 60}, now - MIN_GAP - 1) is None


def test_min_gap_suppresses():
    now = 100_000.0
    assert call([q("refreshed")], now, {"refreshed": 0.0}, now - 1) is None


def test_on_demand_questions_are_never_break_due():
    now = 100_000.0
    qq = q("sleep", trigger=m.TRIGGER_ON_DEMAND)
    assert call([qq], now, {"sleep": 0.0}, 0.0) is None


def test_picks_most_overdue_break_question():
    now = 100_000.0
    a, b = q("a"), q("b")
    lp = {"a": now - 8 * 3600, "b": now - 40 * 3600}
    assert call([a, b], now, lp, 0.0).id == "b"


def test_disabled_and_empty():
    assert call([], 100_000.0, {}, 0.0) is None
    assert call([q("a", enabled=False)], 100_000.0, {"a": 0.0}, 0.0) is None


def test_once_per_day_skipped_when_answered_today():
    now = 100_000.0
    once = q("sleep", once_per_day=True)
    lp = {"sleep": now - 40 * 3600}                         # long overdue
    assert due_break_check_in([once], now, lp, 0.0, WIN, MIN_GAP) is once
    assert due_break_check_in([once], now, lp, 0.0, WIN, MIN_GAP,
                              answered_today={"sleep"}) is None


def test_multiple_per_day_not_skipped_when_answered():
    now = 100_000.0
    multi = q("refreshed")                                  # once_per_day defaults False
    lp = {"refreshed": now - 40 * 3600}
    assert due_break_check_in([multi], now, lp, 0.0, WIN, MIN_GAP,
                              answered_today={"refreshed"}) is multi

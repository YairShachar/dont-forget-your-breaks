from dfyb.checkins import model as m


def q(**over):
    base = {"id": "refreshed", "text": "How refreshed?",
            "answer": {"type": "scale", "min": 1, "max": 5, "allow_note": True},
            "cadence": {"type": "times_per_day", "count": 2}}
    base.update(over)
    return base


def test_parse_builds_typed_questions():
    [qq] = m.parse_questions([q()])
    assert qq.id == "refreshed" and qq.enabled is True
    assert qq.answer.type == m.SCALE and qq.answer.max == 5
    assert qq.cadence.type == m.TIMES_PER_DAY and qq.cadence.count == 2


def test_parse_is_tolerant_of_bad_entries():
    good = q()
    bad_missing_id = q(); del bad_missing_id["id"]
    bad_type = q(id="x", answer={"type": "wat"})
    out = m.parse_questions([good, bad_missing_id, bad_type, "not-a-dict", None])
    assert [x.id for x in out] == ["refreshed"]        # only the valid one survives


def test_cadence_interval_seconds():
    win = 12 * 3600
    assert m.cadence_interval_seconds(m.Cadence(m.TIMES_PER_DAY, 2), win) == win / 2
    assert m.cadence_interval_seconds(m.Cadence(m.PER_DAY, 1), win) == m.SECONDS_PER_DAY
    assert m.cadence_interval_seconds(m.Cadence(m.PER_WEEK, 2), win) == 7 * m.SECONDS_PER_DAY / 2
    # count is floored to 1 (never divide by zero)
    assert m.cadence_interval_seconds(m.Cadence(m.TIMES_PER_DAY, 0), win) == win


def test_answer_is_valid():
    scale = m.AnswerSpec(m.SCALE, min=1, max=5)
    assert m.answer_is_valid(scale, 3) and not m.answer_is_valid(scale, 9)
    choices = m.AnswerSpec(m.CHOICES, options=("Good", "OK", "Rough"))
    assert m.answer_is_valid(choices, "OK") and not m.answer_is_valid(choices, "Nope")
    note = m.AnswerSpec(m.NOTE)
    assert m.answer_is_valid(note, None)               # note-only: value is always None


def test_parse_reads_trigger_with_default():
    [a] = m.parse_questions([q()])                      # default -> break
    assert a.trigger == m.TRIGGER_BREAK
    [b] = m.parse_questions([q(trigger="on_demand")])
    assert b.trigger == m.TRIGGER_ON_DEMAND
    [c] = m.parse_questions([q(trigger="nonsense")])    # invalid -> default break
    assert c.trigger == m.TRIGGER_BREAK


def test_parse_reads_once_per_day():
    [a] = m.parse_questions([q()])
    assert a.once_per_day is False
    [b] = m.parse_questions([q(once_per_day=True)])
    assert b.once_per_day is True


def test_parse_number_type_and_validate():
    raw = {"id": "hrs", "text": "Hours slept?",
           "answer": {"type": "number", "unit": "hours", "min": 0, "max": 24, "step": 0.5},
           "cadence": {"type": "per_day", "count": 1}}
    [qq] = m.parse_questions([raw])
    assert qq.answer.type == m.NUMBER
    assert qq.answer.unit == "hours" and qq.answer.step == 0.5
    assert m.answer_is_valid(qq.answer, 7.5)
    assert not m.answer_is_valid(qq.answer, 25)      # above max
    assert not m.answer_is_valid(qq.answer, True)    # bool is not a number answer

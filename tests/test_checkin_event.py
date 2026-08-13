import launch
from dfyb.checkins import model as m


def _q(ans):
    return m.Question(id="refreshed", text="How refreshed?", answer=ans,
                      cadence=m.Cadence(m.TIMES_PER_DAY, 2))


def test_scale_payload():
    p = launch.check_in_event_payload(_q(m.AnswerSpec(m.SCALE, 1, 5)), 4, None)
    assert p == {"question_id": "refreshed", "question": "How refreshed?",
                 "answer_type": "scale", "value": 4, "note": None}


def test_choice_payload_with_note():
    p = launch.check_in_event_payload(
        _q(m.AnswerSpec(m.CHOICES, options=("Great", "OK"))), "OK", "tired though")
    assert p["value"] == "OK" and p["note"] == "tired though"


def test_note_only_payload():
    p = launch.check_in_event_payload(_q(m.AnswerSpec(m.NOTE)), None, "a thought")
    assert p["answer_type"] == "note" and p["value"] is None and p["note"] == "a thought"

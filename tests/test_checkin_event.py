import launch
from dfyb.checkins import model as m


def _q(ans):
    return m.Question(id="refreshed", text="How refreshed?", answer=ans,
                      cadence=m.Cadence(m.TIMES_PER_DAY, 2))


def test_scale_payload():
    p = launch.check_in_event_payload(_q(m.AnswerSpec(m.SCALE, 1, 5)), 4, None, "eid1")
    assert p == {"id": "eid1", "question_id": "refreshed", "question": "How refreshed?",
                 "answer_type": "scale", "value": 4, "note": None}


def test_choice_payload_with_note():
    p = launch.check_in_event_payload(
        _q(m.AnswerSpec(m.CHOICES, options=("Great", "OK"))), "OK", "tired though", "eid2")
    assert p["id"] == "eid2" and p["value"] == "OK" and p["note"] == "tired though"


def test_note_only_payload():
    p = launch.check_in_event_payload(_q(m.AnswerSpec(m.NOTE)), None, "a thought", "eid3")
    assert p["answer_type"] == "note" and p["value"] is None and p["note"] == "a thought"


def test_edit_payload():
    assert launch.check_in_edit_payload("e", "target1", 5, "better") == {
        "id": "e", "edits": "target1", "value": 5, "note": "better"}


def test_remove_payload():
    assert launch.check_in_remove_payload("e", "target1") == {"id": "e", "removes": "target1"}

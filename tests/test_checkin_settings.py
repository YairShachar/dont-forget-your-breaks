"""Settings > Check-ins: the Number answer type (spec v2 §5) — pure pieces only.

The edit modal itself is Tk; everything it computes lives in the pure helpers
below so it can be tested headless.
"""
import launch
from dfyb.checkins.model import (NUMBER, DEFAULT_NUMBER_MIN, DEFAULT_NUMBER_MAX,
                                 parse_questions, answer_is_valid)


# ---- the type is offered in the modal's answer-type menu --------------------

def test_number_is_an_offered_answer_type():
    assert launch.CHECK_IN_ANSWER_TYPE_LABELS[NUMBER] == "Number"


# ---- card summary ----------------------------------------------------------

def _summary(answer):
    return launch.check_in_summary(
        {"id": "sleep_hours", "text": "How many hours did you sleep?",
         "answer": answer, "cadence": {"type": "per_day", "count": 1},
         "trigger": "on_demand"})


def test_number_summary_shows_the_unit():
    assert _summary({"type": "number", "unit": "hours"}).startswith("Number (hours)")


def test_number_summary_without_a_unit_is_just_the_type():
    assert _summary({"type": "number"}).startswith("Number ·")


# ---- number parsing (shared by the modal and the answer popup) -------------

def test_ci_num_keeps_whole_values_as_int():
    assert launch._ci_num("7", None) == 7
    assert isinstance(launch._ci_num("7", None), int)


def test_ci_num_parses_decimals():
    assert launch._ci_num("7.5", None) == 7.5


def test_ci_num_falls_back_on_garbage_and_blanks():
    assert launch._ci_num("", 3) == 3
    assert launch._ci_num("abc", 3) == 3
    assert launch._ci_num(None, None) is None


# ---- building the stored answer dict from the modal's fields ---------------

def test_number_answer_from_fields():
    answer = launch.check_in_number_answer("hours", "0", "24", "0.5", True)
    assert answer == {"type": NUMBER, "unit": "hours", "min": 0, "max": 24,
                      "step": 0.5, "allow_note": True}


def test_number_answer_swaps_a_reversed_range():
    answer = launch.check_in_number_answer("", "24", "0", "1", False)
    assert (answer["min"], answer["max"]) == (0, 24)
    assert answer["allow_note"] is False


def test_number_answer_falls_back_on_blank_fields():
    answer = launch.check_in_number_answer("  ", "", "", "", True)
    assert answer["unit"] == ""
    assert (answer["min"], answer["max"]) == (DEFAULT_NUMBER_MIN, DEFAULT_NUMBER_MAX)
    assert answer["step"] == launch.CHECK_IN_DEFAULT_NUMBER_STEP


def test_number_answer_rejects_a_non_positive_step():
    assert launch.check_in_number_answer("", "0", "10", "0", True)["step"] == \
        launch.CHECK_IN_DEFAULT_NUMBER_STEP


def test_number_answer_round_trips_through_the_model():
    answer = launch.check_in_number_answer("hours", "0", "24", "0.5", True)
    q = parse_questions([{"id": "h", "text": "Hours?", "answer": answer,
                          "cadence": {"type": "per_day", "count": 1}}])[0]
    assert q.answer.unit == "hours" and q.answer.step == 0.5
    assert answer_is_valid(q.answer, 7.5)
    assert not answer_is_valid(q.answer, 25)


# ---- a blank question (Settings' "+ Add question" and the chooser's add row) ----

def test_new_question_is_a_valid_scale_question():
    from dfyb.checkins.model import SCALE, TRIGGER_BREAK
    q = parse_questions([launch.new_check_in_question("mood")])[0]
    assert q.id == "mood"
    assert q.text == launch.CHECK_IN_NEW_QUESTION_TEXT
    assert q.answer.type == SCALE and q.answer.allow_note
    assert q.enabled and q.trigger == TRIGGER_BREAK and q.once_per_day is False


def test_new_question_ids_are_independent():
    a, b = launch.new_check_in_question("a"), launch.new_check_in_question("b")
    a["answer"]["min"] = 99                       # no shared mutable defaults
    assert b["answer"]["min"] != 99

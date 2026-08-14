import launch


def test_defaults_present_and_valid():
    from dfyb.checkins.model import parse_questions
    d = launch.DEFAULT_CHECK_INS
    assert d["enabled"] in (True, False)
    qs = parse_questions(d["questions"])
    assert len(qs) == len(d["questions"]) >= 1     # every default parses cleanly
    assert all(q.id for q in qs)


def test_merge_uses_defaults_when_absent():
    enabled, questions = launch.merge_check_ins({})          # empty prefs (old config)
    assert questions == launch.DEFAULT_CHECK_INS["questions"]
    assert enabled == launch.DEFAULT_CHECK_INS["enabled"]


def test_merge_respects_saved_config():
    saved = {"check_ins": {"enabled": False,
                           "questions": [{"id": "mood", "text": "Mood?",
                                          "answer": {"type": "note"},
                                          "cadence": {"type": "per_day", "count": 1}}]}}
    enabled, questions = launch.merge_check_ins(saved)
    assert enabled is False and questions[0]["id"] == "mood"


def test_default_triggers():
    from dfyb.checkins.model import parse_questions, TRIGGER_BREAK, TRIGGER_ON_DEMAND
    qs = {q.id: q for q in parse_questions(launch.DEFAULT_CHECK_INS["questions"])}
    assert qs["refreshed"].trigger == TRIGGER_BREAK
    assert qs["sleep"].trigger == TRIGGER_ON_DEMAND

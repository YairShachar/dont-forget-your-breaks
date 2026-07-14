from dfyb.scheduler.dedup import break_in_play


def test_not_in_play_when_nothing():
    assert break_in_play("A", None, [], []) is False


def test_in_play_when_showing():
    assert break_in_play("A", "A", [], []) is True


def test_in_play_when_queued():
    assert break_in_play("A", "B", ["A"], []) is True


def test_in_play_when_pending():
    assert break_in_play("A", "B", [], ["A"]) is True


def test_not_in_play_when_only_other_names():
    assert break_in_play("A", "B", ["C"], ["D"]) is False

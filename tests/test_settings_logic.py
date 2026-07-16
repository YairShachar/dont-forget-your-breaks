from dfyb.settings_logic import suboption_state


def test_parent_on_enables_child():
    assert suboption_state(True) == "normal"


def test_parent_off_disables_child():
    assert suboption_state(False) == "disabled"

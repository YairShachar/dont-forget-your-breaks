import dfyb.macos_window as macos_window


def test_make_nonintrusive_is_noop_off_macos(monkeypatch):
    monkeypatch.setattr(macos_window.sys, "platform", "linux")
    # Must not touch the window and must not raise on non-macOS.
    macos_window.make_nonintrusive(object())


def test_make_nonintrusive_swallows_failure_on_darwin(monkeypatch):
    monkeypatch.setattr(macos_window.sys, "platform", "darwin")
    # A bad window (no .title()) / missing AppKit must be caught -> no raise.
    macos_window.make_nonintrusive(object())

"""Regression for the stuck 'Break now' chip.

On Tk 9 Aqua, CTkLabel.place_forget() unmaps the overlay logically but never
repaints the vacated pixels, so the chip ghosts on screen forever. The fix
hides by destroy(); this test locks in the observable contract — after a hide,
the label object is gone (None), not merely place_forget()'d.

Needs a real Tk display, so it self-skips in headless CI.
"""
import pytest

tk = pytest.importorskip("tkinter")


def _make_app():
    ctk = pytest.importorskip("customtkinter")
    try:
        root = ctk.CTk()
    except tk.TclError:
        pytest.skip("no display available")
    import launch
    app = launch.BreakApp(root)
    root.update_idletasks()
    return ctk, root, app


def _play_button(ctk, row):
    return next(w for w in row.winfo_children() if isinstance(w, ctk.CTkButton))


def test_hide_destroys_the_chip_not_just_forgets_it():
    ctk, root, app = _make_app()
    try:
        play = _play_button(ctk, app._timer_labels[0].master)
        app._tip_show(play, "Break now")
        assert app._tip_lbl is not None, "chip should exist while shown"
        app._tip_hide()
        assert app._tip_lbl is None, "hide must destroy the chip (place_forget ghosts on Aqua)"
    finally:
        root.destroy()


def test_dismiss_still_ends_in_destroy(monkeypatch):
    """Fade-out must destroy the chip, not place_forget() it (which ghosts on Aqua).
    Forcing reduced motion makes the fade-out instant and deterministic."""
    import launch
    monkeypatch.setattr(launch, "prefers_reduced_motion", lambda: True)
    ctk, root, app = _make_app()
    try:
        play = _play_button(ctk, app._timer_labels[0].master)
        app._tip_show(play, "Break now")
        app._tip_dismiss()                 # pointer-left path
        assert app._tip_lbl is None        # faded out and destroyed
    finally:
        root.destroy()


def test_reshow_after_destroy_recreates_the_chip():
    ctk, root, app = _make_app()
    try:
        play = _play_button(ctk, app._timer_labels[0].master)
        app._tip_show(play, "Break now")
        app._tip_hide()
        app._tip_show(play, "Break now")   # must not crash on the destroyed label
        assert app._tip_lbl is not None            # recreated
        assert app._tip_lbl.winfo_manager() == "place"   # and placed (map-timing-safe)
    finally:
        root.destroy()

"""Behavior tests for the shared CollapsibleSection. Tk-gated (self-skips headless)."""
import pytest

tk = pytest.importorskip("tkinter")


def _make():
    ctk = pytest.importorskip("customtkinter")
    try:
        root = ctk.CTk()
    except tk.TclError:
        pytest.skip("no display available")
    import launch
    return ctk, launch, root


def _section(ctk, launch, root, **kwargs):
    sec = launch.CollapsibleSection(root, "Demo", **kwargs)
    ctk.CTkLabel(sec.body, text="content").pack()   # some body content
    sec.finalize()
    root.update_idletasks()
    return sec


def test_starts_expanded_by_default():
    ctk, launch, root = _make()
    try:
        assert _section(ctk, launch, root).is_expanded() is True
    finally:
        root.destroy()


def test_starts_collapsed_when_requested():
    ctk, launch, root = _make()
    try:
        assert _section(ctk, launch, root, expanded=False).is_expanded() is False
    finally:
        root.destroy()


def test_toggle_flips_expanded_state():
    ctk, launch, root = _make()
    try:
        sec = _section(ctk, launch, root)
        sec.toggle_expand(); root.update_idletasks()
        assert sec.is_expanded() is False
        sec.toggle_expand(); root.update_idletasks()
        assert sec.is_expanded() is True
    finally:
        root.destroy()


def test_on_toggle_fires_only_on_user_toggle_with_new_state():
    ctk, launch, root = _make()
    try:
        seen = []
        sec = _section(ctk, launch, root, expanded=False,
                       on_toggle=lambda is_open: seen.append(is_open))
        # Building/collapsing at init must NOT fire the callback.
        assert seen == []
        sec.toggle_expand(); root.update_idletasks()   # -> expands
        assert seen == [True]
        sec.toggle_expand(); root.update_idletasks()   # -> collapses
        assert seen == [True, False]
    finally:
        root.destroy()

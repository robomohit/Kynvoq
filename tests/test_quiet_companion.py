"""Tests for the 'quiet companion' overlay behaviour.

The floating bubble used to follow the cursor at all times (a resting orb), which
was distracting — especially mid-game. Now it only appears when there's something
to show (listening / thinking / a fresh answer / an in-flight action), fades out
otherwise, and hides entirely while a fullscreen app is in front.
"""
import os

import pytest


def _overlay():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
        from app.widget.virtual_cursor import VirtualCursorOverlay
    except Exception:
        pytest.skip("PySide6 not importable in this environment")
    QApplication.instance() or QApplication([])
    return VirtualCursorOverlay()


def test_companion_idle_is_inactive():
    ov = _overlay()
    now = ov._now_ms()
    ov._companion_label = ""
    ov._cursor_state = "idle"
    ov._cursor_visible_until = 0
    # Nothing happening -> nothing to show.
    assert ov._companion_active(now) is False


def test_companion_wakes_on_voice_and_thinking():
    ov = _overlay()
    now = ov._now_ms()
    ov._companion_label = ""
    for state in ("listening", "thinking"):
        ov._cursor_state = state
        assert ov._companion_active(now) is True


def test_companion_label_holds_then_goes_quiet():
    ov = _overlay()
    now = ov._now_ms()
    ov._cursor_state = "idle"
    ov._companion_label = "Notepad is open."
    ov._companion_label_set_ms = now
    # A fresh answer stays up briefly...
    assert ov._companion_active(now) is True
    # ...then the bubble goes quiet after the hold window.
    assert ov._companion_active(now + ov.COMPANION_IDLE_HIDE_MS + 1) is False


def test_fullscreen_hide_opt_out_short_circuits():
    ov = _overlay()
    ov._hide_in_fullscreen = False
    assert ov._fullscreen_app_in_front() is False


def test_idle_companion_fades_out():
    ov = _overlay()
    ov._hide_in_fullscreen = False  # don't let a real fullscreen window affect the test
    ov._companion_enabled = True
    ov._cursor_state = "idle"
    ov._companion_label = ""
    ov._cursor_visible_until = 0
    ov._companion_bubble_alpha = 1.0
    # With nothing to show, repeated ticks must fade the bubble toward invisible.
    for _ in range(40):
        ov._tick()
    assert ov._companion_bubble_alpha <= 0.05


def test_active_companion_fades_in():
    ov = _overlay()
    ov._hide_in_fullscreen = False
    ov._companion_enabled = True
    ov._companion_bubble_alpha = 0.0
    ov._cursor_state = "thinking"  # actively working -> should become visible
    for _ in range(20):
        ov._tick()
    assert ov._companion_bubble_alpha >= 0.8


def test_companion_text_lock_blocks_cursor_actions_not_authoritative():
    """While the bubble text is locked (Gemini Live owns it), cursor-action feedback
    must not overwrite the floating text — but the authoritative setter (Live's own
    narration) still can. This is what stops the bubble flashing between the live
    transcript and a Live-spawned task's step labels."""
    ov = _overlay()

    # Unlocked: a cursor action sets the bubble as usual.
    ov.show_uia(10, 20, 30, 40, label="Clicking Save", kind="click")
    assert ov._companion_label == "Clicking Save"

    # Live takes over and speaks; then a desktop task it spawned tries to flash
    # its own step labels through the flying cursor.
    ov.set_companion_text_locked(True)
    ov.set_companion_label("Sure, opening Notepad.")  # authoritative (Live)
    assert ov._companion_label == "Sure, opening Notepad."

    ov.show_uia(50, 60, 70, 80, label="Searching", kind="find")
    ov.show_click(5, 5, label="Clicking")
    ov.show_action("Typing")
    # The cursor still flew (a spotlight was recorded) but the text held steady.
    assert ov._companion_label == "Sure, opening Notepad."
    assert ov._spotlights  # spatial feedback still played

    # Live ends -> cursor actions own the bubble again.
    ov.set_companion_text_locked(False)
    ov.show_uia(1, 2, 3, 4, label="Clicked OK", kind="click")
    assert ov._companion_label == "Clicked OK"

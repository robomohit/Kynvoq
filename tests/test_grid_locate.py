"""Two-stage grid-locate (Set-of-Mark) — coordinate math + fail-safe behavior.

The vision call is mocked, so this is deterministic and offline. It pins the
contract that matters: a coarse cell + a fine sub-cell map back to the right
screen pixel, and any "can't tell" path returns None (never a wrong click).
"""
import sys
import types as _types

import pytest

import app.grid_locate as gl


def test_parse_cell_variants():
    assert gl._parse_cell('{"cell": 42}', 96) == 42
    assert gl._parse_cell("cell = 7", 96) == 7
    assert gl._parse_cell("the answer is 5", 96) == 5
    assert gl._parse_cell('{"cell": 0}', 96) is None      # 0 = not visible
    assert gl._parse_cell("99", 36) is None               # out of range
    assert gl._parse_cell("", 96) is None
    assert gl._parse_cell("no number here", 96) is None


def _install_fake_mss(monkeypatch, w, h):
    fake = _types.ModuleType("mss")

    class _Shot:
        size = (w, h)
        rgb = b"\x20\x20\x20" * (w * h)  # solid gray, valid RGB buffer

    class _Sct:
        monitors = [{}, {"left": 0, "top": 0, "width": w, "height": h}]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def grab(self, mon):
            return _Shot()

    fake.mss = lambda: _Sct()
    monkeypatch.setitem(sys.modules, "mss", fake)


def test_locate_maps_two_stage_picks_to_screen_pixel(monkeypatch):
    """Stage-1 cell 42 (col5,row3) → 3x3 zoom; stage-2 cell 15 (center) → a pixel
    in the middle of the screen. Verifies the full fraction transform."""
    _install_fake_mss(monkeypatch, 1200, 800)
    monkeypatch.setattr("app.widget.gemini_live.gemini_api_key", lambda: "test-key")

    def fake_ask(jpeg, target, max_n, key):
        return 42 if max_n == gl.STAGE1_COLS * gl.STAGE1_ROWS else 15

    monkeypatch.setattr(gl, "_ask_cell", fake_ask)

    res = gl.locate("the New Agent button")
    assert res is not None
    x, y = res
    # Picked cells land mid-screen; assert the right neighbourhood, not exact pixels.
    assert 480 < x < 560, x
    assert 290 < y < 360, y


def test_locate_returns_none_when_not_visible(monkeypatch):
    """Stage-1 says 'not visible' (cell 0 → None) → locate gives up, no wrong click."""
    _install_fake_mss(monkeypatch, 1200, 800)
    monkeypatch.setattr("app.widget.gemini_live.gemini_api_key", lambda: "test-key")
    monkeypatch.setattr(gl, "_ask_cell", lambda *a, **k: None)
    assert gl.locate("a thing that isn't there") is None


def test_locate_returns_none_without_key(monkeypatch):
    """No Gemini key → no vision call attempted, returns None (degrades to UIA miss)."""
    monkeypatch.setattr("app.widget.gemini_live.gemini_api_key", lambda: "")
    called = {"n": 0}
    monkeypatch.setattr(gl, "_ask_cell", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    assert gl.locate("anything") is None
    assert called["n"] == 0


def test_locate_disabled_by_env(monkeypatch):
    monkeypatch.setenv("ORYNN_GRID_LOCATE", "0")
    assert gl.locate("anything") is None

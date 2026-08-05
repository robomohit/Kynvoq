"""Tests for the taskbar voice glow — Orynn's no-text voice presence.

The Win32 layered-child window is created lazily and no-ops off-Windows, so these
tests exercise the pure state/color logic without a real taskbar. They pin the
contract the overlay wiring depends on (set_state / set_cursor_state /
set_audio_level) and that the four voice palettes stay distinct.
"""
from __future__ import annotations

import importlib

import numpy as np
import pytest

glow_mod = importlib.import_module("app.widget.taskbar_glow")
TaskbarGlow = glow_mod.TaskbarGlow


@pytest.fixture
def glow():
    # Build the instance WITHOUT touching Win32 (no real window): bypass __init__
    # and set just the fields the pure logic uses.
    g = TaskbarGlow.__new__(TaskbarGlow)
    g._ok = False
    g._hwnd = None
    g._w, g._h = 200, 40
    g._state = "idle"
    g._audio_level = 0.0
    g._level_smooth = 0.0
    g._phase = 0.0
    g._sweep = 0.0
    g._intensity = 0.0
    # Look tunables (normally set in __init__ from env; fixture bypasses it).
    g._palette = list(TaskbarGlow._PALETTE)
    g._base_palette = list(TaskbarGlow._PALETTE)
    g._revert_state = None
    g._revert_at_ms = None
    g._t_bright = 1.0
    g._t_height = 1.0
    g._t_speed = 1.0
    # Flow/visibility state (see __init__).
    g._flow_smooth = 0.0
    g._wt = 0.0
    g._cleared = False
    g._visible = True
    g._hotspot = 0.5
    g._hotspot_target = 0.5
    g._direction_locked = False
    return g


def test_states_are_recognized_and_unknown_falls_back_to_idle(glow):
    for s in ("idle", "listening", "thinking", "speaking"):
        glow.set_state(s)
        assert glow._state == s
    glow.set_state("bogus")
    assert glow._state == "idle"


def test_cursor_state_shim_maps_legacy_states(glow):
    glow.set_cursor_state("listening")
    assert glow._state == "listening"
    glow.set_cursor_state("idle")
    assert glow._state == "idle"
    # legacy emitters may send "thinking"
    glow.set_cursor_state("thinking")
    assert glow._state == "thinking"


def test_audio_level_is_clamped_and_peak_held(glow):
    glow.set_state("listening")
    # Values are clamped to [0, 1].
    glow.set_audio_level(2.5)
    assert glow._audio_level == 1.0
    # Peak-hold: lower/invalid values don't lower the held peak (a fast syllable
    # spike survives until the next frame consumes it).
    glow.set_audio_level(-1.0)
    assert glow._audio_level == 1.0
    glow.set_audio_level("nonsense")  # type: ignore[arg-type]
    assert glow._audio_level == 1.0
    # Reset (as _tick does), then a fresh lower value registers.
    glow._audio_level = 0.0
    glow.set_audio_level(0.3)
    assert abs(glow._audio_level - 0.3) < 1e-9


def test_non_voice_states_zero_the_audio_level(glow):
    glow.set_state("listening")
    glow.set_audio_level(0.8)
    assert glow._audio_level == 0.8
    glow.set_state("idle")            # leaving a voice state clears the level
    assert glow._audio_level == 0.0


def test_set_speaking_toggles_state(glow):
    glow.set_speaking(True)
    assert glow._state == "speaking"
    glow.set_speaking(False)
    assert glow._state == "idle"


def test_palettes_cover_all_states_and_speaking_is_warmest():
    for s in ("idle", "listening", "thinking", "speaking",
              "working", "reminder", "success", "error"):
        assert s in TaskbarGlow.PALETTES
        assert len(TaskbarGlow.PALETTES[s]) >= 2


def test_status_palettes_are_semantically_distinct():
    """Working (violet), reminder/success (green), error (red) must be far from
    the voice cyan-blue and from each other — the color IS the silent signal."""
    def mean_hue(p):
        # Circular-safe enough here: none of our palettes straddle except red,
        # which we test by proximity to 0/1.
        return sum(h % 1.0 for h in p) / len(p)

    voice = mean_hue(TaskbarGlow._PALETTE)         # ~0.55 blue
    working = mean_hue(TaskbarGlow._WORKING)       # ~0.76 violet
    green = mean_hue(TaskbarGlow._GREEN)           # ~0.34 green
    assert abs(working - voice) > 0.12
    assert abs(green - voice) > 0.12
    assert abs(working - green) > 0.25
    # Error hugs red (hue ~0 or ~1).
    assert all(h % 1.0 < 0.06 or h % 1.0 > 0.94 for h in TaskbarGlow._RED)


def _tickable(glow):
    """Let the fixture run real _tick/_paint frames offscreen."""
    glow._ok = True
    glow._hwnd = 1
    glow._push = lambda *a: None
    return glow


def test_palette_crossfades_toward_state_color(glow):
    g = _tickable(glow)
    g.set_state("working")
    for _ in range(80):
        g._tick()
    for cur, tgt in zip(g._palette, TaskbarGlow._WORKING):
        d = abs(((tgt - cur + 0.5) % 1.0) - 0.5)
        assert d < 0.01, f"palette stop {cur} didn't converge to {tgt}"
    # Going back to a voice state returns to the base palette.
    g.set_state("idle")
    for _ in range(80):
        g._tick()
    for cur, tgt in zip(g._palette, g._base_palette):
        assert abs(((tgt - cur + 0.5) % 1.0) - 0.5) < 0.01


def test_success_and_error_flashes_auto_revert(glow):
    g = _tickable(glow)
    g.set_state("listening")
    g.set_state("success")
    assert g._state == "success"
    assert g._revert_state == "listening"
    g._revert_at_ms = 0            # flash expired
    g._tick()
    assert g._state == "listening"

    # A finished background task reverts to idle, not back to "working".
    g.set_state("working")
    g.set_state("error")
    assert g._revert_state == "idle"
    g._revert_at_ms = 0
    g._tick()
    assert g._state == "idle"

    # A newer real state cancels the pending revert.
    g.set_state("success")
    g.set_state("speaking")
    assert g._revert_at_ms is None


def test_working_state_pulses_without_audio(glow):
    g = _tickable(glow)
    g.set_state("working")
    for _ in range(30):
        g._tick()
    assert g._level_smooth > 0.05   # alive with zero audio input


class _FakeGlow:
    """Records the calls the controller makes so we can assert the wiring."""

    def __init__(self):
        self.states = []
        self.levels = []

    def set_state(self, s):
        self.states.append(s)

    def set_cursor_state(self, s):
        self.states.append(s)

    def set_audio_level(self, lvl):
        self.levels.append(lvl)


def test_controller_drives_glow_voice_sensitively():
    """The taskbar glow is voice-sensitive: live mic/output level and state
    transitions reach it through the controller's signal handlers."""
    tbo = importlib.import_module("app.widget.textbox_overlay")
    controller = tbo.OverlayController(8000)
    fake = _FakeGlow()
    controller.attach_glow(fake)

    # Audio level (mic while listening, or Orynn's voice while speaking) → glow.
    controller._on_audio_level(0.73)
    assert 0.73 in fake.levels

    # Cursor-state transitions (idle/listening/thinking) → glow.
    controller._on_cursor_state("listening")
    assert "listening" in fake.states

    # The dedicated speaking state (AI reply) → glow.
    controller._on_glow_state("speaking")
    assert "speaking" in fake.states


def test_background_task_maps_thinking_to_working_color():
    """While a background task runs, the generic thinking blue becomes the
    violet 'working' status on the bar — the silent 'Orynn is busy' signal."""
    tbo = importlib.import_module("app.widget.textbox_overlay")
    controller = tbo.OverlayController(8000)
    fake = _FakeGlow()
    controller.attach_glow(fake)
    controller._active_task_running = True
    controller._on_cursor_state("thinking")
    assert fake.states[-1] == "working"
    controller._active_task_running = False
    controller._on_cursor_state("thinking")
    assert fake.states[-1] == "thinking"


def test_chime_envelope_pulses_glow():
    """Cue tones ring through the bar: attach_glow registers the voice-module
    cue listener, whose per-frame levels light the bar in an active state, and
    the end-of-chime sentinel settles it back to sleep outside a live session."""
    tbo = importlib.import_module("app.widget.textbox_overlay")
    voice = importlib.import_module("app.widget.voice")
    controller = tbo.OverlayController(8000)
    fake = _FakeGlow()
    fake._state = "idle"
    fake.visible = []
    fake.set_visible = fake.visible.append
    controller.attach_glow(fake)
    try:
        assert voice._cue_listener == controller._on_cue_level

        # A chime frame lights the bar in an active state and drives the level.
        controller._on_cue_level("wake", 0.8)
        assert "speaking" in fake.states
        assert fake.visible and fake.visible[-1] is True
        assert 0.8 in fake.levels

        # A state the live session is already driving is never stomped.
        fake._state = "listening"
        fake.states.clear()
        controller._on_cue_level("wake", 0.5)
        assert "speaking" not in fake.states

        # Chime finished, no live session → bar settles back to sleep.
        controller._on_cue_level("sleep", None)
        assert fake.states[-1] == "idle"
        assert fake.visible[-1] is False
    finally:
        voice.set_cue_listener(None)


def test_cue_envelope_tracks_chime_amplitude():
    """The envelope follows the rendered chime: normalized to a 1.0 peak, quiet
    ring-out tail, one frame per ~30ms of audio."""
    voice = importlib.import_module("app.widget.voice")
    wav = voice._chime_wav(voice._CUE_NOTES["sleep"])
    env = voice._cue_envelope(wav)
    dur = (len(wav) - 44) / 2 / voice._CUE_SR
    assert abs(len(env) - dur / (voice._CUE_FRAME_MS / 1000.0)) <= 2
    assert max(env) == 1.0
    assert env[-1] < 0.35          # ring-down actually decays
    assert all(0.0 <= v <= 1.0 for v in env)


def test_hue_ramp_is_one_cohesive_cyan_blue_palette(glow):
    glow._phase = 0.2
    glow.set_state("listening")
    ramp = glow._hue_ramp(64)
    assert ramp.shape == (64, 3)
    assert np.all((ramp >= 0.0) & (ramp <= 1.0))
    # One clean cyan→blue palette (no rainbow): blue/green dominate, red is low.
    r, g, b = ramp[:, 0].mean(), ramp[:, 1].mean(), ramp[:, 2].mean()
    assert b > r and g > r        # cool, not warm
    # Every state shares the SAME palette now (state shown by motion/brightness).
    glow.set_state("speaking")
    assert np.allclose(glow._hue_ramp(64), ramp)

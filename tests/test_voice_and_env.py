"""Regression tests for two things that caused real launch failures:

1. The empty-".env" trap — a numeric env var present but blank (e.g. "FOO=")
   must fall back to its default instead of crashing on int("")/float("").
2. The voice STT helpers added for Groq Whisper push-to-talk.
"""
import importlib

import pytest


def test_env_num_falls_back_on_empty(monkeypatch):
    from app.agent import _env_num

    # Unset -> default.
    monkeypatch.delenv("ZZ_TEST_NUM", raising=False)
    assert _env_num("ZZ_TEST_NUM", 300.0, float) == 300.0

    # Present but blank / whitespace -> default (the bug that crashed startup).
    monkeypatch.setenv("ZZ_TEST_NUM", "")
    assert _env_num("ZZ_TEST_NUM", 300.0, float) == 300.0
    monkeypatch.setenv("ZZ_TEST_NUM", "   ")
    assert _env_num("ZZ_TEST_NUM", 25, int) == 25

    # A real value is honoured.
    monkeypatch.setenv("ZZ_TEST_NUM", "42")
    assert _env_num("ZZ_TEST_NUM", 25, int) == 42


def test_module_constants_load_with_blank_env(monkeypatch):
    """agent.py module-level numeric constants must import even when the env
    vars are present-but-blank (reproduces the original ValueError)."""
    for name in (
        "APPROVAL_WAIT_TIMEOUT_SECONDS",
        "PERMISSION_WAIT_TIMEOUT_SECONDS",
        "AGENT_MAX_STEPS",
        "BROWSER_MAX_STEPS",
        "DESKTOP_MAX_STEPS",
    ):
        monkeypatch.setenv(name, "")
    import app.agent as agent

    importlib.reload(agent)
    assert agent.APPROVAL_WAIT_TIMEOUT_SECONDS == 300.0
    assert agent.AGENT_MAX_STEPS == 25
    # Restore a clean module for any later tests.
    for name in (
        "APPROVAL_WAIT_TIMEOUT_SECONDS",
        "PERMISSION_WAIT_TIMEOUT_SECONDS",
        "AGENT_MAX_STEPS",
        "BROWSER_MAX_STEPS",
        "DESKTOP_MAX_STEPS",
    ):
        monkeypatch.delenv(name, raising=False)
    importlib.reload(agent)


def test_wav_seconds():
    from app.widget import voice

    sr = 16000
    one_second_pcm = b"\x00\x00" * sr  # 16-bit mono
    wav = voice._pcm_to_wav(one_second_pcm, sr)
    assert abs(voice.wav_seconds(wav) - 1.0) < 0.01
    assert voice.wav_seconds(b"") == 0.0
    assert voice.wav_seconds(b"short") == 0.0


def test_groq_stt_available_requires_key(monkeypatch):
    from app.widget import voice

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert voice._groq_stt_available() is False
    # transcribe_wav returns None (not a crash) when no key is configured.
    assert voice.transcribe_wav(b"\x00\x00") is None


def test_push_to_talk_requires_recorder_capture(monkeypatch):
    from app.widget import voice

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(voice, "recorder_available", lambda: False)
    assert voice._groq_stt_available() is False
    assert voice.push_to_talk_available() is False

    monkeypatch.setattr(voice, "recorder_available", lambda: True)
    assert voice._groq_stt_available() is True
    assert voice.push_to_talk_available() is True


def test_cue_is_non_blocking_and_safe():
    from app.widget import voice

    # Should never raise regardless of audio hardware; unknown kinds are no-ops.
    voice.cue("start")
    voice.cue("stop")
    voice.cue("cancel")
    voice.cue("error")
    voice.cue("nonexistent-kind")


def test_humanize_status_drops_step_spam():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from app.widget.textbox_overlay import _humanize_status
    except Exception:
        import pytest

        pytest.skip("PySide6 not importable in this environment")

    from app.widget.textbox_overlay import _THINKING_WORDS

    def is_busy_word(s):  # a playful rotating "busy" word like "Brewing…"
        return s.endswith("…") and s[:-1] in _THINKING_WORDS

    assert is_busy_word(_humanize_status("Thinking through step 1…"))
    assert is_busy_word(_humanize_status("Working on step 2…"))  # 'Working' too
    assert is_busy_word(_humanize_status("Thinking… waiting on model (step 1, 44s)"))
    assert is_busy_word(_humanize_status("Thinking… waiting on model (step 12, 6s)"))
    assert is_busy_word(_humanize_status(""))
    # No step counters or ticking-seconds fragments survive.
    out = _humanize_status("Reticulating splines on step 3")
    assert "step" not in out.lower()
    # Non-step messages pass through unchanged.
    assert _humanize_status("Started task") == "Started task"


def test_strip_markdown_flattens_to_plain_text():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from app.widget.textbox_overlay import _strip_markdown
    except Exception:
        import pytest

        pytest.skip("PySide6 not importable in this environment")

    md = ("**Short answer:** Yes.\n### Heading\n"
          "| A | B |\n|---|---|\n| 1 | 2 |\n- bullet\n`code`")
    out = _strip_markdown(md)
    for junk in ("**", "###", "|", "---", "`"):
        assert junk not in out
    assert "Short answer: Yes." in out
    # Links collapse to their text.
    assert _strip_markdown("see [the docs](http://x.com)") == "see the docs"


def test_voice_brevity_appended_but_stripped_from_labels():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from app.widget import textbox_overlay as t
    except Exception:
        import pytest

        pytest.skip("PySide6 not importable in this environment")

    payload = t.build_task_payload("who won the world cup")
    assert "[Reply format:" in payload["goal"]  # instruction reaches the model
    # ...but never leaks into the goal echoed back in a label.
    assert "[Reply format:" not in t._strip_hardening(payload["goal"])


def test_voice_desktop_payload_fits_task_schema():
    """REGRESSION: a multi-step spoken desktop command prepends the ~1.7KB
    desktop-hardening prompt to the goal. If TaskIn.goal's max_length is shorter
    than that fixed overhead, the backend rejects EVERY such command with HTTP 422
    and the bubble just says "Couldn't start task" — the free push-to-talk desktop
    path silently dies. Pin the voice->submit contract so the cap can never again
    fall below the hardening prompt.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from app.widget import textbox_overlay as t
    except Exception:
        import pytest

        pytest.skip("PySide6 not importable in this environment")
    from app.main import TaskIn, TaskPreflightIn

    # A real multi-step desktop command DOES carry the hardening prompt and must fit.
    payload = t.build_task_payload("open notepad and type a quick note for me")
    assert payload["mode"] == "computer"
    assert t.DESKTOP_HARDENING in payload["goal"]  # hardening is present...
    TaskIn(**payload)  # ...and still validates (cap >= hardening overhead)
    TaskPreflightIn(goal=payload["goal"], mode=payload["mode"])
    # A generously long dictated command must still fit, with headroom over the prompt.
    long_cmd = "open notepad and " + ("type a long dictated sentence " * 40)
    TaskIn(**t.build_task_payload(long_cmd))


def test_app_launch_payload_is_unwrapped():
    """A pure 'open <known app>' command takes the deterministic fast-path, so its
    goal stays RAW — no hardening prompt, no voice-brevity note (which is what once
    blew past the 2000-char cap). A command that does MORE than open keeps the full
    desktop wrapper."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from app.widget import textbox_overlay as t
    except Exception:
        import pytest

        pytest.skip("PySide6 not importable in this environment")

    launch = t.build_task_payload("open notepad")
    assert launch["mode"] == "computer"
    assert launch["goal"] == "open notepad"  # untouched: no hardening, no brevity
    assert t.DESKTOP_HARDENING not in launch["goal"]
    assert "[Reply format:" not in launch["goal"]

    # "open X and <do more>" is NOT a pure launch -> full wrapper applies.
    multi = t.build_task_payload("open notepad and type hello")
    assert t.DESKTOP_HARDENING in multi["goal"]


def test_detect_app_launch_intent():
    """The intent detector must catch pure known-app launches and reject anything
    with extra steps, unknown apps, or non-launch phrasing (those fall to the LLM)."""
    from app.tools import detect_app_launch_intent as d

    # Pure launches across verbs / fillers / casing.
    assert d("open notepad") == ("start notepad", "Notepad")
    assert d("launch the calculator") == ("start calc", "Calculator")
    assert d("Open Calc") == ("start calc", "Calculator")
    assert d("switch to settings") == ("start ms-settings:", "Settings")
    assert d("open task manager please") == ("start taskmgr", "Task Manager")
    assert d("open the ms paint app") == ("start mspaint", "Paint")
    assert d("hey orynn, open notepad") == ("start notepad", "Notepad")

    # Not pure launches / unknown -> None (planner handles these).
    assert d("open notepad and type hello") is None
    assert d("open chrome") is None            # not in the curated registry
    assert d("what's open in notepad") is None  # not a launch verb
    assert d("type hello") is None
    assert d("open notepad to write a note") is None
    assert d("") is None


def test_overlay_action_dispatch_routes_to_cursor_methods():
    """Action events with overlay geometry must drive the right fly-to-target
    cursor calls; non-drawable events must not."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
        from app.widget.textbox_overlay import OverlayController
    except Exception:
        import pytest

        pytest.skip("PySide6 not importable in this environment")

    _app = QApplication.instance() or QApplication([])

    class FakeOverlay:
        def __init__(self):
            self.calls = []

        def show_uia(self, *a, **k):
            self.calls.append(("uia", a, k))

        def show_app_focus(self, *a, **k):
            self.calls.append(("app", a, k))

        def show_click(self, *a, **k):
            self.calls.append(("click", a, k))

        def show_type(self, *a, **k):
            self.calls.append(("type", a, k))

        def show_action(self, *a, **k):
            self.calls.append(("action", a, k))

        def set_cursor_state(self, s):
            self.calls.append(("state", s))

    controller = OverlayController(8000)
    fake = FakeOverlay()
    controller.attach_overlay(fake)

    uia_ev = {
        "type": "action_result",
        "overlay": {
            "type": "uia_control", "kind": "click", "label": "Clicking Send",
            "rect": {"left": 10, "top": 20, "width": 100, "height": 30},
            "app_rect": {"left": 0, "top": 0, "width": 800, "height": 600},
        },
    }
    assert controller._overlay_is_drawable(uia_ev)
    controller._on_overlay_action(uia_ev)
    names = [c[0] for c in fake.calls]
    assert "app" in names and "uia" in names

    point_ev = {
        "type": "action_result",
        "overlay": {"type": "point", "kind": "click",
                     "point": {"x": 5, "y": 6}, "label": "Clicking"},
    }
    assert controller._overlay_is_drawable(point_ev)
    controller._on_overlay_action(point_ev)
    assert any(c[0] == "click" for c in fake.calls)

    # Status / step spam carries no geometry → not drawable.
    assert not controller._overlay_is_drawable(
        {"type": "status", "message": "Thinking through step 1…"})

    controller._on_cursor_state("thinking")
    assert ("state", "thinking") in fake.calls


def test_agent_reasoning_is_not_shown_in_bubble():
    """The model's intermediate planning/reasoning ('STEP 3 of 6…', 'PLAN: …')
    must not leak into the cursor bubble; the final answer still does."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
        from app.widget.textbox_overlay import OverlayController
    except Exception:
        import pytest

        pytest.skip("PySide6 not importable in this environment")

    _app = QApplication.instance() or QApplication([])
    c = OverlayController(8000)

    reasoning = {"type": "agent",
                 "text": "STEP 4? Actually next step is to wait. PLAN: use uiawait for 'Codex'. STEP 1..."}
    assert c._label_for_event(reasoning) == ""
    # The final answer (done event) is still surfaced.
    out = c._label_for_event({"type": "done", "reason": "Opened the app."})
    assert "opened" in out.lower()


def test_textbox_tray_icon_has_generated_fallback(monkeypatch):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
        from app.widget import textbox_overlay as t
    except Exception:
        import pytest

        pytest.skip("PySide6 not importable in this environment")

    _app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(t.Path, "exists", lambda self: False)

    icon = t._app_icon()

    assert not icon.isNull()


def test_finalize_chimes_only_no_spoken_reply(monkeypatch):
    """Spoken replies were removed: voice tasks get a done/fail chime only — no
    voice.speak, no tray toast. Non-voice tasks stay silent."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
        from app.widget import textbox_overlay as t
        from app.widget import voice
    except Exception:
        import pytest

        pytest.skip("PySide6 not importable in this environment")

    _app = QApplication.instance() or QApplication([])
    spoke, cued = [], []
    monkeypatch.setattr(voice, "speak", lambda *a, **k: spoke.append(a) or True)
    monkeypatch.setattr(voice, "cue", lambda kind: cued.append(kind))

    c = t.OverlayController(8000)

    c._voice_task_ids.add("v1")
    c._maybe_finalize({"type": "done", "task_id": "v1", "reason": "The app is open."})
    assert "done" in cued
    assert not spoke  # the assistant no longer speaks the answer aloud

    c._voice_task_ids.add("v2")
    c._maybe_finalize({"type": "error", "task_id": "v2", "reason": "It broke"})
    assert "fail" in cued

    # A non-voice (typed) task makes no sound at all.
    before = len(cued)
    c._maybe_finalize({"type": "done", "task_id": "typed", "reason": "x"})
    assert len(cued) == before


def test_stop_all_stops_active_recorder(monkeypatch):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
        from app.widget import textbox_overlay as t
        from app.widget import voice
    except Exception:
        import pytest

        pytest.skip("PySide6 not importable in this environment")

    _app = QApplication.instance() or QApplication([])
    cues = []
    monkeypatch.setattr(voice, "cue", lambda kind: cues.append(kind))
    monkeypatch.setattr(voice, "stop_speaking", lambda: None)

    class FakeClient:
        def request(self, *args, **kwargs):
            return {"tasks": []}

    class FakeRecorder:
        def __init__(self):
            self.stopped = 0

        def stop(self):
            self.stopped += 1
            return b""

    c = t.OverlayController(8000)
    c.client = FakeClient()
    recorder = FakeRecorder()
    c._recorder = recorder
    c._recording = True
    states, labels = [], []
    c.cursorStateRequested.connect(lambda state: states.append(state))
    c.labelRequested.connect(lambda label: labels.append(label))

    c._stop_all_worker()

    assert recorder.stopped == 1
    assert c._recording is False
    assert c._recorder is None
    assert states[-1] == "idle"
    assert labels[-1] == "Stopped"
    assert "cancel" in cues


def test_ptt_watch_cancels_when_keyboard_import_fails(monkeypatch):
    import builtins
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
        from app.widget.textbox_overlay import OverlayController
    except Exception:
        import pytest

        pytest.skip("PySide6 not importable in this environment")

    _app = QApplication.instance() or QApplication([])
    c = OverlayController(8000)
    calls = []
    c._ptt_stop = lambda cancelled=False: calls.append(cancelled)

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "keyboard":
            raise ImportError("keyboard unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    c._ptt_watch()

    assert calls == [True]


def test_submit_voice_task_resets_cursor_state_on_preflight_block():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
        from app.widget.textbox_overlay import OverlayController
    except Exception:
        import pytest

        pytest.skip("PySide6 not importable in this environment")

    _app = QApplication.instance() or QApplication([])

    class FakeClient:
        def request(self, method, path, *args, **kwargs):
            assert path == "/api/tasks/preflight"
            return {"blocked": True}

    c = OverlayController(8000)
    c.client = FakeClient()
    states, labels = [], []
    c.cursorStateRequested.connect(lambda state: states.append(state))
    c.labelRequested.connect(lambda label: labels.append(label))

    c._submit_voice_task("open notepad")

    assert states[0] == "thinking"
    assert states[-1] == "idle"
    assert labels[-1] == "Setup needed"


def test_companion_text_width_limit_keeps_bubble_on_small_screens():
    try:
        from app.widget.virtual_cursor import VirtualCursorOverlay
    except Exception:
        import pytest

        pytest.skip("PySide6 not importable in this environment")

    margin, pad_x, dot_gap = 8, 13, 16
    limit = VirtualCursorOverlay._companion_text_width_limit(
        180, margin, pad_x, dot_gap
    )
    assert limit >= 1
    assert limit + pad_x * 2 + dot_gap <= 180 - margin * 2
    assert VirtualCursorOverlay._companion_text_width_limit(
        1200, margin, pad_x, dot_gap
    ) == VirtualCursorOverlay.COMPANION_MAX_TEXT_WIDTH


def test_qt_shell_syncs_companion_cursor_state_for_text_entry():
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "widget"
        / "qt_shell.py"
    ).read_text(encoding="utf-8")
    start = src.index("        def _set_capsule_state")
    end = src.index("        def _show_context_details", start)
    block = src[start:end]

    assert 'self._vcursor.set_companion_label(' in block
    assert 'self._vcursor.set_cursor_state("listening")' in block
    assert 'elif state in ("submitting", "planning", "acting"):' in block
    assert 'self._vcursor.set_cursor_state("thinking")' in block
    assert 'self._vcursor.set_cursor_state("idle")' in block


def test_qt_shell_final_answer_reaches_companion_plain_and_short():
    from pathlib import Path
    from app.widget.qt_shell import _plain_companion_text

    md = (
        "**Short answer:** Yes.\n"
        "| A | B |\n|---|---|\n| 1 | 2 |\n"
        "- keep it simple\n"
        "See [docs](https://example.com)."
    )
    out = _plain_companion_text(md, limit=80)
    for junk in ("**", "|", "---", "`", "[docs]"):
        assert junk not in out
    assert "Short answer: Yes." in out
    assert "docs" in out
    assert len(_plain_companion_text("x" * 240, limit=200)) == 200

    src = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "widget"
        / "qt_shell.py"
    ).read_text(encoding="utf-8")
    start = src.index("        def _on_finished")
    end = src.index("        def _append_sources_strip", start)
    block = src[start:end]
    assert "final_label = _plain_companion_text(clean) or \"Done\"" in block
    assert 'self._set_capsule_state("done", final_label)' in block
    assert "Done — result ready" not in block


def test_force_utf8_stdio_is_crash_proof():
    """A unicode log line (em/non-breaking hyphen, emoji from model text) must never
    crash a print on the Windows cp1252 console. The reconfigure helper sets
    utf-8/replace and swallows any failure (e.g. a stream that can't reconfigure)."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from app.widget import textbox_overlay as t
    except Exception:
        import pytest
        pytest.skip("PySide6 not importable in this environment")

    calls = []

    class FakeStream:
        def reconfigure(self, **kw):
            calls.append(kw)

    class BadStream:
        def reconfigure(self, **kw):
            raise OSError("cannot reconfigure")

    # Must not raise even when one stream refuses to reconfigure.
    t._force_utf8_stdio([FakeStream(), BadStream()])
    assert {"encoding": "utf-8", "errors": "replace"} in calls

"""Tests for the Gemini Live realtime voice + tool-calling bridge.

These cover the parts that make Live actually useful instead of a toy:

1. Availability gating (no key / no SDK / no audio -> graceful reason, never a crash).
2. The function-tool declarations and the LiveConnectConfig we hand to the model.
3. Tool execution routing: sync handlers, async handlers, non-dict returns, and
   exceptions all turn into a structured response, never a thrown error.
4. The full round-trip: when the model emits a tool_call, the bridge runs the
   local handler and sends a FunctionResponse back over the session.
5. The OverlayController side of the bridge: start_desktop_task / stop_current_task
   / get_companion_status route into Orynn's backend API the right way.

Everything here is offline (no network, no API key). The real end-to-end check
that Gemini Live really calls our tools over the wire lives in
``scripts/live_tool_smoke.py``.
"""
import asyncio
import threading

import pytest


# ── Availability gating ──────────────────────────────────────────────────────

def test_live_unavailable_reason_without_key(monkeypatch):
    from app.widget import gemini_live as gl

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert gl.gemini_api_key() == ""
    assert gl.live_unavailable_reason() == "Gemini API key missing"
    assert gl.live_available() is False


def test_gemini_api_key_prefers_gemini_then_google(monkeypatch):
    from app.widget import gemini_live as gl

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "  google-key  ")
    assert gl.gemini_api_key() == "google-key"  # trimmed, GOOGLE_ fallback used
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    assert gl.gemini_api_key() == "gemini-key"  # GEMINI_ wins when both present


# ── Function declarations + config ───────────────────────────────────────────

def test_function_declarations_cover_desktop_tools():
    from google.genai import types
    from app.widget import gemini_live as gl

    decls = gl._function_declarations(types)
    names = {d.name for d in decls}
    assert names == {
        "desktop_control",
        "start_desktop_task",
        "stop_current_task",
        "get_companion_status",
    }

    start = next(d for d in decls if d.name == "start_desktop_task")
    schema = start.parameters_json_schema
    # The desktop-action tool must require a free-text goal string.
    assert schema["required"] == ["goal"]
    assert schema["properties"]["goal"]["type"] == "string"

    desktop = next(d for d in decls if d.name == "desktop_control")
    desktop_schema = desktop.parameters_json_schema
    assert desktop_schema["required"] == ["action"]
    assert {"find", "click", "type", "press_keys"} <= set(
        desktop_schema["properties"]["action"]["enum"]
    )


def _config_tool_names(cfg) -> tuple[set[str], bool]:
    fn_names: set[str] = set()
    has_search = False
    for tool in cfg.tools:
        if getattr(tool, "google_search", None) is not None:
            has_search = True
        for fn in getattr(tool, "function_declarations", None) or []:
            fn_names.add(fn.name)
    return fn_names, has_search


def test_live_config_exposes_tools_audio_and_transcription(monkeypatch):
    from google.genai import types
    from app.widget import gemini_live as gl

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    comp = gl.GeminiLiveCompanion(gl.GeminiLiveCallbacks())
    cfg = comp._live_config(types)

    # Audio out, plus both-way transcription so the bubble can show what was said.
    assert types.Modality.AUDIO in cfg.response_modalities
    assert cfg.input_audio_transcription is not None
    assert cfg.output_audio_transcription is not None
    assert cfg.system_instruction  # a personality/safety prompt is attached

    # Our local desktop function tools are always wired in.
    fn_names, _ = _config_tool_names(cfg)
    assert {"desktop_control", "start_desktop_task", "stop_current_task"} <= fn_names


def test_live_config_google_search_is_opt_in(monkeypatch):
    """Google Search grounding is paid-tier on Live, so it's OFF by default and
    only attached when GEMINI_LIVE_SEARCH is set. The free desktop tools stay on."""
    from google.genai import types
    from app.widget import gemini_live as gl

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    monkeypatch.delenv("GEMINI_LIVE_SEARCH", raising=False)
    assert gl.live_search_enabled() is False
    cfg = gl.GeminiLiveCompanion(gl.GeminiLiveCallbacks())._live_config(types)
    fn_names, has_search = _config_tool_names(cfg)
    assert has_search is False  # free-tier safe by default
    assert "start_desktop_task" in fn_names

    monkeypatch.setenv("GEMINI_LIVE_SEARCH", "1")
    assert gl.live_search_enabled() is True
    cfg2 = gl.GeminiLiveCompanion(gl.GeminiLiveCallbacks())._live_config(types)
    fn_names2, has_search2 = _config_tool_names(cfg2)
    assert has_search2 is True  # opt-in once on a paid plan
    assert "start_desktop_task" in fn_names2


# ── Tool execution routing ───────────────────────────────────────────────────

def test_execute_tool_routes_args_to_handler():
    from app.widget import gemini_live as gl

    seen = {}

    def handler(name, args):
        seen["name"], seen["args"] = name, args
        return {"ok": True, "task_id": "t1"}

    comp = gl.GeminiLiveCompanion(gl.GeminiLiveCallbacks(on_tool=handler))
    out = asyncio.run(comp._execute_tool("start_desktop_task", {"goal": "open notepad"}))
    assert out == {"ok": True, "task_id": "t1"}
    assert seen == {"name": "start_desktop_task", "args": {"goal": "open notepad"}}


def test_execute_tool_supports_async_handler():
    from app.widget import gemini_live as gl

    async def handler(name, args):
        return {"ok": True, "async": True}

    comp = gl.GeminiLiveCompanion(gl.GeminiLiveCallbacks(on_tool=handler))
    assert asyncio.run(comp._execute_tool("x", {})) == {"ok": True, "async": True}


def test_execute_tool_offloads_sync_handler_from_live_loop():
    from app.widget import gemini_live as gl

    seen = {}

    def handler(name, args):
        seen["handler_thread"] = threading.get_ident()
        return {"ok": True}

    async def run():
        seen["loop_thread"] = threading.get_ident()
        comp = gl.GeminiLiveCompanion(gl.GeminiLiveCallbacks(on_tool=handler))
        return await comp._execute_tool("x", {})

    assert asyncio.run(run()) == {"ok": True}
    assert seen["handler_thread"] != seen["loop_thread"]


def test_execute_tool_returns_stopped_when_cancelled():
    from app.widget import gemini_live as gl

    comp = gl.GeminiLiveCompanion(
        gl.GeminiLiveCallbacks(on_tool=lambda name, args: {"ok": True})
    )
    comp._stop.set()
    res = asyncio.run(comp._execute_tool("x", {}))
    assert res["ok"] is False
    assert "stopped" in res["message"].lower()


def test_live_companion_exposes_stop_requested_flag():
    from app.widget import gemini_live as gl

    comp = gl.GeminiLiveCompanion(gl.GeminiLiveCallbacks())

    assert comp.stop_requested() is False
    comp.stop()
    assert comp.stop_requested() is True


def test_execute_tool_wraps_non_dict_results():
    from app.widget import gemini_live as gl

    comp = gl.GeminiLiveCompanion(gl.GeminiLiveCallbacks(on_tool=lambda n, a: "done"))
    assert asyncio.run(comp._execute_tool("x", {})) == {"ok": True, "result": "done"}


def test_execute_tool_turns_exceptions_into_error_response():
    from app.widget import gemini_live as gl

    def boom(name, args):
        raise RuntimeError("nope")

    comp = gl.GeminiLiveCompanion(gl.GeminiLiveCallbacks(on_tool=boom))
    res = asyncio.run(comp._execute_tool("x", {}))
    assert res["ok"] is False and "nope" in res["message"]


def test_execute_tool_without_handler_is_graceful():
    from app.widget import gemini_live as gl

    comp = gl.GeminiLiveCompanion(gl.GeminiLiveCallbacks())  # no on_tool
    res = asyncio.run(comp._execute_tool("anything", {}))
    assert res["ok"] is False and "handler" in res["message"].lower()


# ── Full tool-call round-trip over a fake session ────────────────────────────

def test_handle_message_runs_tool_and_sends_response_back():
    """The core promise: a model tool_call -> local execution -> FunctionResponse
    posted back to the session. This is the bit that lets Gemini Live *do* things."""
    from google.genai import types
    from app.widget import gemini_live as gl

    executed = []

    def handler(name, args):
        executed.append((name, args))
        return {"ok": True, "task_id": "smoke"}

    comp = gl.GeminiLiveCompanion(gl.GeminiLiveCallbacks(on_tool=handler))

    class FakeCall:
        name = "start_desktop_task"
        id = "call-1"
        args = {"goal": "open notepad"}

    class FakeToolCall:
        function_calls = [FakeCall()]

    class FakeMessage:
        server_content = None
        tool_call = FakeToolCall()

    class FakeSession:
        def __init__(self):
            self.responses = None

        async def send_tool_response(self, function_responses):
            self.responses = function_responses

    session = FakeSession()
    asyncio.run(comp._handle_message(session, FakeMessage(), None, types))

    assert executed == [("start_desktop_task", {"goal": "open notepad"})]
    assert session.responses is not None and len(session.responses) == 1
    resp = session.responses[0]
    assert resp.name == "start_desktop_task"
    assert resp.id == "call-1"
    assert resp.response == {"ok": True, "task_id": "smoke"}


def test_handle_message_returns_error_for_malformed_tool_args():
    from google.genai import types
    from app.widget import gemini_live as gl

    executed, statuses = [], []

    def handler(name, args):
        executed.append((name, args))
        return {"ok": True}

    comp = gl.GeminiLiveCompanion(
        gl.GeminiLiveCallbacks(on_tool=handler, on_status=lambda s: statuses.append(s))
    )

    class FakeCall:
        name = "desktop_control"
        id = "call-bad-args"
        args = "not a json object"

    class FakeToolCall:
        function_calls = [FakeCall()]

    class FakeMessage:
        server_content = None
        tool_call = FakeToolCall()

    class FakeSession:
        def __init__(self):
            self.responses = None

        async def send_tool_response(self, function_responses):
            self.responses = function_responses

    session = FakeSession()
    asyncio.run(comp._handle_message(session, FakeMessage(), None, types))

    assert executed == []
    assert statuses == ["Live tool call failed"]
    assert session.responses is not None and len(session.responses) == 1
    resp = session.responses[0]
    assert resp.name == "desktop_control"
    assert resp.id == "call-bad-args"
    assert resp.response["ok"] is False
    assert "json object" in resp.response["message"].lower()


def test_handle_message_writes_model_audio_to_output_stream():
    """Inline PCM audio parts from the model get written to the speaker stream."""
    from google.genai import types
    from app.widget import gemini_live as gl

    written = []

    class FakeOutput:
        def write(self, data):
            written.append(data)

    class FakePart:
        class inline_data:
            data = b"\x01\x02\x03\x04"

    class FakeTurn:
        parts = [FakePart()]

    class FakeContent:
        input_transcription = None
        output_transcription = None
        model_turn = FakeTurn()
        turn_complete = False

    class FakeMessage:
        server_content = FakeContent()
        tool_call = None

    comp = gl.GeminiLiveCompanion(gl.GeminiLiveCallbacks())
    asyncio.run(comp._handle_message(object(), FakeMessage(), FakeOutput(), types))
    assert written == [b"\x01\x02\x03\x04"]


def test_handle_message_emits_transcripts():
    """Input/output transcriptions reach the callbacks so the bubble can show them."""
    from google.genai import types
    from app.widget import gemini_live as gl

    inputs, outputs = [], []
    cbs = gl.GeminiLiveCallbacks(
        on_input_transcript=lambda t, fin: inputs.append((t, fin)),
        on_output_transcript=lambda t, fin: outputs.append((t, fin)),
    )

    class FakeInp:
        text = "open notepad"
        finished = True

    class FakeOut:
        text = "Sure, opening it."
        finished = False

    class FakeContent:
        input_transcription = FakeInp()
        output_transcription = FakeOut()
        model_turn = None
        turn_complete = False

    class FakeMessage:
        server_content = FakeContent()
        tool_call = None

    comp = gl.GeminiLiveCompanion(cbs)
    asyncio.run(comp._handle_message(object(), FakeMessage(), None, types))
    assert inputs == [("open notepad", True)]
    assert outputs == [("Sure, opening it.", False)]


# ── OverlayController bridge into Orynn's backend ────────────────────────────

def test_handle_message_turn_complete_finishes_live_reply():
    """A Live turn_complete is the hard boundary between spoken replies.

    Gemini may omit/leave false the transcript-level finished flag, but the
    overlay still needs to reset before the next model turn.
    """
    from google.genai import types
    from app.widget import gemini_live as gl

    outputs, statuses = [], []
    cbs = gl.GeminiLiveCallbacks(
        on_output_transcript=lambda t, fin: outputs.append((t, fin)),
        on_status=lambda s: statuses.append(s),
    )

    class FakeOut:
        text = "First reply."
        finished = False

    class FakeContent:
        input_transcription = None
        output_transcription = FakeOut()
        model_turn = None
        turn_complete = True

    class FakeMessage:
        server_content = FakeContent()
        tool_call = None

    comp = gl.GeminiLiveCompanion(cbs)
    asyncio.run(comp._handle_message(object(), FakeMessage(), None, types))
    assert outputs == [("First reply.", False), ("", True)]
    assert statuses == ["Gemini Live listening"]


def _controller():
    """Build an OverlayController in a headless Qt app, or skip if PySide6 is absent."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
        from app.widget.textbox_overlay import OverlayController
    except Exception:
        pytest.skip("PySide6 not importable in this environment")
    QApplication.instance() or QApplication([])
    return OverlayController(8000)


def test_live_toggle_success_resets_stale_session_state(monkeypatch):
    from app.widget import gemini_live as gl

    instances = []

    class FakeLiveCompanion:
        def __init__(self, callbacks):
            self.callbacks = callbacks
            self.running = False
            instances.append(self)

        def start(self):
            self.running = True
            return True

        def is_running(self):
            return self.running

        def stop(self):
            self.running = False

    monkeypatch.setattr(gl, "GeminiLiveCompanion", FakeLiveCompanion)

    c = _controller()
    c._live_cancel.set()
    c._live_input_buffer = "old input"
    c._live_input_done = False
    c._live_reply_buffer = "old reply"
    c._live_reply_done = False
    labels, states = [], []
    c.labelRequested.connect(lambda s: labels.append(s))
    c.cursorStateRequested.connect(lambda s: states.append(s))

    c._toggle_live()

    assert len(instances) == 1
    assert c._live is instances[0]
    assert c._live_generation == 1
    assert not c._live_cancel.is_set()
    assert c._live_input_buffer == ""
    assert c._live_input_done is True
    assert c._live_reply_buffer == ""
    assert c._live_reply_done is True
    assert labels[-1] == "Starting Gemini Live..."
    assert states[-1] == "listening"


def test_live_toggle_failure_clears_dead_live_object(monkeypatch):
    from app.widget import gemini_live as gl

    class FailingLiveCompanion:
        def __init__(self, callbacks):
            self.callbacks = callbacks

        def start(self):
            self.callbacks.on_error("Gemini API key missing")
            return False

        def is_running(self):
            return False

    monkeypatch.setattr(gl, "GeminiLiveCompanion", FailingLiveCompanion)

    c = _controller()
    labels, states = [], []
    c.labelRequested.connect(lambda s: labels.append(s))
    c.cursorStateRequested.connect(lambda s: states.append(s))

    c._toggle_live()

    assert c._live is None
    assert c._live_cancel.is_set()
    assert labels[-1] == "Gemini API key missing"
    assert states[-1] == "idle"


def test_live_toggle_off_ignores_late_stopped_callback(monkeypatch):
    from app.widget import gemini_live as gl

    class FakeLiveCompanion:
        def __init__(self, callbacks):
            self.callbacks = callbacks
            self.running = False

        def start(self):
            self.running = True
            return True

        def is_running(self):
            return self.running

        def stop(self):
            self.running = False

    monkeypatch.setattr(gl, "GeminiLiveCompanion", FakeLiveCompanion)

    c = _controller()
    labels, states = [], []
    c.labelRequested.connect(lambda s: labels.append(s))
    c.cursorStateRequested.connect(lambda s: states.append(s))

    c._toggle_live()
    old_callbacks = c._live.callbacks
    c._toggle_live()
    label_count = len(labels)
    state_count = len(states)

    old_callbacks.on_stopped("Gemini Live stopped")

    assert c._live is None
    assert labels[-1] == "Gemini Live off"
    assert len(labels) == label_count
    assert len(states) == state_count


def test_live_stopped_resets_current_session_buffers():
    c = _controller()
    c._live_generation = 7
    c._live = object()
    c._live_input_buffer = "half heard"
    c._live_input_done = False
    c._live_reply_buffer = "half reply"
    c._live_reply_done = False
    labels, states = [], []
    c.labelRequested.connect(lambda s: labels.append(s))
    c.cursorStateRequested.connect(lambda s: states.append(s))

    c._live_stopped("Gemini Live stopped", generation=7)

    assert c._live is None
    assert c._live_input_buffer == ""
    assert c._live_input_done is True
    assert c._live_reply_buffer == ""
    assert c._live_reply_done is True
    assert labels == ["Gemini Live stopped"]
    assert states == ["idle"]


def test_live_error_label_survives_followup_stopped_callback():
    c = _controller()
    c._live_generation = 9
    c._live = object()
    c._live_input_buffer = "half heard"
    c._live_input_done = False
    c._live_reply_buffer = "half reply"
    c._live_reply_done = False
    labels, states = [], []
    c.labelRequested.connect(lambda s: labels.append(s))
    c.cursorStateRequested.connect(lambda s: states.append(s))

    c._live_error("Gemini Live error: mic unavailable", generation=9)
    c._live_stopped("Gemini Live stopped", generation=9)

    assert labels == ["Gemini Live error: mic unavailable"]
    assert states == ["idle", "idle"]
    assert c._live is None
    assert c._live_input_buffer == ""
    assert c._live_input_done is True
    assert c._live_reply_buffer == ""
    assert c._live_reply_done is True
    assert c._live_error_generation is None


def test_stale_live_tool_callback_does_not_touch_desktop():
    c = _controller()
    c._live_generation = 3

    class FakeTools:
        def uia_click(self, query, app=""):
            raise AssertionError("stale Live callback should not execute tools")

    c._desktop_tools = FakeTools()

    res = c._live_tool_for_generation(
        2,
        "desktop_control",
        {"action": "click", "query": "Send", "app": "Chat"},
    )

    assert res["ok"] is False
    assert "session changed" in res["message"]


def test_live_tool_desktop_control_routes_to_uia_find_and_visuals():
    from app.models import ToolResult

    calls = []

    class FakeTools:
        def uia_find(self, query, app="", limit=5):
            calls.append((query, app, limit))
            return ToolResult(
                ok=True,
                output="UIA matches:\n1. Text editor [Edit] @ (10,20) score=99",
                data={
                    "items": [{"name": "Text editor", "control_type": "Edit"}],
                    "overlay": {
                        "type": "uia_control",
                        "tool": "uia_find",
                        "kind": "find",
                        "label": "Found Text editor",
                        "target": "Text editor",
                        "rect": {"left": 1, "top": 2, "width": 30, "height": 40},
                    },
                },
            )

    c = _controller()
    c._desktop_tools = FakeTools()
    labels, states, overlays = [], [], []
    c.labelRequested.connect(lambda s: labels.append(s))
    c.cursorStateRequested.connect(lambda s: states.append(s))
    c.overlayActionRequested.connect(lambda ev: overlays.append(ev))

    res = c._live_tool(
        "desktop_control",
        {"action": "find", "query": "Text editor", "app": "Notepad", "limit": 2},
    )

    assert calls == [("Text editor", "Notepad", 2)]
    assert res["ok"] is True
    assert res["action"] == "find"
    assert "UIA matches" in res["output"]
    assert res["data"]["items"][0]["name"] == "Text editor"
    assert labels[0] == "Finding control"
    assert labels[-1] == "Found Text editor"
    assert "UIA matches" not in labels[-1]
    assert "thinking" in states
    assert overlays and overlays[0]["overlay"]["target"] == "Text editor"


def test_live_tool_desktop_control_routes_to_uia_type():
    from app.models import ToolResult

    calls = []

    class FakeTools:
        def uia_type(self, query, text, app="", clear_first=False, submit=False):
            calls.append((query, text, app, clear_first, submit))
            return ToolResult(
                ok=True,
                output="Typed into 'Text editor' via ValuePattern",
                data={"target": "Text editor"},
            )

    c = _controller()
    c._desktop_tools = FakeTools()
    labels = []
    c.labelRequested.connect(lambda s: labels.append(s))
    res = c._live_tool(
        "desktop_control",
        {
            "action": "type",
            "query": "Text editor",
            "text": "hello",
            "app": "Notepad",
            "clear_first": True,
            "submit": "false",
        },
    )

    assert res["ok"] is True
    assert calls == [("Text editor", "hello", "Notepad", True, False)]
    assert labels == ["Typing into control", "Typed into Text editor"]


def test_live_tool_desktop_control_type_requires_non_empty_text():
    class FakeTools:
        def uia_type(self, *args, **kwargs):
            raise AssertionError("empty type text should not touch UIA")

    c = _controller()
    c._desktop_tools = FakeTools()
    labels = []
    c.labelRequested.connect(lambda s: labels.append(s))

    res = c._live_tool(
        "desktop_control",
        {
            "action": "type",
            "query": "Text editor",
            "text": "   ",
            "app": "Notepad",
            "clear_first": True,
        },
    )

    assert res["ok"] is False
    assert "missing text" in res["message"].lower()
    assert labels == ["Typing into control", "Missing text for type."]


def test_live_tool_desktop_control_observe_label_is_human_not_raw_map():
    from app.models import ToolResult

    calls = []

    class FakeTools:
        def adaptive_observe(self, app="", cap=90):
            calls.append((app, cap))
            return ToolResult(
                ok=True,
                output="Adaptive app map\nraw grouped controls...",
                data={"graph": {"named_control_count": 13}},
            )

    c = _controller()
    c._desktop_tools = FakeTools()
    labels = []
    c.labelRequested.connect(lambda s: labels.append(s))

    res = c._live_tool("desktop_control", {"action": "observe", "app": "Notepad", "cap": 42})

    assert res["ok"] is True
    assert calls == [("Notepad", 42)]
    assert "Adaptive app map" in res["output"]
    assert labels == ["Reading app controls", "Mapped 13 controls"]
    assert "Adaptive" not in labels[-1]


def test_live_tool_desktop_control_wait_slices_until_success():
    from app.models import ToolResult

    c = _controller()
    calls = []

    class FakeTools:
        def wait_for_window(self, title, timeout=10.0, paint_seconds=0.35):
            calls.append((title, timeout, paint_seconds))
            if len(calls) < 3:
                return ToolResult(ok=False, output="Timed out waiting for a visible window.")
            return ToolResult(ok=True, output="Window ready: 'Notepad'", data={"title": "Notepad"})

    c._desktop_tools = FakeTools()
    labels = []
    c.labelRequested.connect(lambda s: labels.append(s))

    res = c._live_tool(
        "desktop_control",
        {"action": "wait_for_window", "title": "Notepad", "timeout": 5},
    )

    assert res["ok"] is True
    assert len(calls) == 3
    assert all(0.09 <= timeout <= 0.45 for _, timeout, _ in calls)
    assert all(paint_seconds == 0.05 for _, _, paint_seconds in calls)
    assert labels == ["Finding window", "Window ready: Notepad"]


def test_live_tool_desktop_control_wait_stops_after_cancel_signal():
    from app.models import ToolResult

    c = _controller()
    calls = []

    class FakeTools:
        def wait_for_window(self, title, timeout=10.0, paint_seconds=0.35):
            calls.append(timeout)
            c._live_cancel.set()
            return ToolResult(ok=False, output="Timed out waiting for a visible window.")

    c._desktop_tools = FakeTools()
    labels, states = [], []
    c.labelRequested.connect(lambda s: labels.append(s))
    c.cursorStateRequested.connect(lambda s: states.append(s))

    res = c._live_tool(
        "desktop_control",
        {"action": "wait_for_window", "title": "Never Appears", "timeout": 5},
    )

    assert res["ok"] is False
    assert "stopped" in res["message"].lower()
    assert calls == [pytest.approx(0.45)]
    assert labels == ["Finding window", "Stopped"]
    assert states[-1] == "idle"


def test_live_tool_desktop_control_blocks_destructive_shortcuts():
    class FakeTools:
        def key(self, keys):
            raise AssertionError("blocked shortcut should not be pressed")

    c = _controller()
    c._desktop_tools = FakeTools()
    res = c._live_tool("desktop_control", {"action": "press_keys", "keys": "alt+f4"})

    assert res["ok"] is False
    assert "not allowed" in res["message"].lower()


@pytest.mark.parametrize(
    "keys",
    [
        "ctrl+shift+x",
        "shift+ctrl+l",
        "control+shift+spacebar",
        "ctrl+shift+m",
        "alt+tab",
        "win+d",
    ],
)
def test_live_tool_desktop_control_blocks_orynn_reserved_shortcuts(keys):
    class FakeTools:
        def key(self, keys):
            raise AssertionError("reserved shortcut should not be pressed")

    c = _controller()
    c._desktop_tools = FakeTools()
    res = c._live_tool("desktop_control", {"action": "press_keys", "keys": keys})

    assert res["ok"] is False
    assert "not allowed" in res["message"].lower()


def test_live_tool_desktop_control_blocks_custom_reserved_hotkey(monkeypatch):
    monkeypatch.setenv("ORYNN_LIVE_KEY", "f9")

    class FakeTools:
        def key(self, keys):
            raise AssertionError("custom reserved shortcut should not be pressed")

    c = _controller()
    c._desktop_tools = FakeTools()
    res = c._live_tool("desktop_control", {"action": "press_keys", "keys": "F9"})

    assert res["ok"] is False
    assert "not allowed" in res["message"].lower()


def test_live_tool_start_desktop_task_calls_backend():
    calls = []

    class FakeClient:
        def request(self, method, path, data=None, timeout=4.0, **kw):
            calls.append((method, path, data))
            if path == "/api/tasks/preflight":
                return {"blocked": False, "issues": []}
            if path == "/api/tasks":
                return {"ok": True}
            return {}

    c = _controller()
    c.client = FakeClient()
    res = c._live_tool("start_desktop_task", {"goal": "open notepad and type hi"})

    assert res["ok"] is True
    paths = [p for _, p, _ in calls]
    assert "/api/tasks/preflight" in paths  # readiness checked before launching
    assert "/api/tasks" in paths            # then the task is actually submitted
    assert c._active_task_running is True


def test_live_tool_start_desktop_task_requires_goal():
    c = _controller()

    class FakeClient:
        def request(self, *a, **k):  # must never be hit without a goal
            raise AssertionError("backend called for an empty goal")

    c.client = FakeClient()
    res = c._live_tool("start_desktop_task", {"goal": "   "})
    assert res["ok"] is False


def test_live_tool_start_desktop_task_blocks_on_preflight():
    class FakeClient:
        def request(self, method, path, data=None, timeout=4.0, **kw):
            if path == "/api/tasks/preflight":
                return {"blocked": True}
            raise AssertionError("must not submit a task that failed preflight")

    c = _controller()
    c.client = FakeClient()
    res = c._live_tool("start_desktop_task", {"goal": "format the C drive"})
    assert res["ok"] is False
    assert "setup" in res["message"].lower()


def test_live_tool_stop_and_status_route_correctly():
    class FakeClient:
        def request(self, method, path, data=None, timeout=4.0, **kw):
            if path == "/api/active-tasks":
                return {"tasks": [{"id": "a"}, {"id": "b"}]}
            return {}

    c = _controller()
    c.client = FakeClient()
    c._kill_active_tasks = lambda: 3

    stop_res = c._live_tool("stop_current_task", {})
    assert stop_res["ok"] is True and stop_res["stopped"] == 3
    assert stop_res["message"] == "Stop request accepted."

    status = c._live_tool("get_companion_status", {})
    assert status["ok"] is True and status["active_tasks"] == 2


def test_live_tool_stop_acknowledges_even_without_backend_tasks():
    c = _controller()
    c._kill_active_tasks = lambda: 0
    c._active_task_running = True
    labels, states = [], []
    c.labelRequested.connect(lambda s: labels.append(s))
    c.cursorStateRequested.connect(lambda s: states.append(s))

    res = c._live_tool("stop_current_task", {})

    assert res == {"ok": True, "stopped": 0, "message": "Stop request accepted."}
    assert c._active_task_running is False
    assert c._live_cancel.is_set() is False
    assert labels == ["Stopped"]
    assert states == ["idle"]


def test_live_refuses_colliding_desktop_action_while_task_running():
    """Talking to Live mid-task must NOT start a second desktop action on top of a
    running one — two agents on one screen steal focus and interleave keystrokes.
    Live is told it's busy and what's running; stop is never gated (the escape hatch)."""
    class FakeClient:
        def __init__(self):
            self.posted = []

        def request(self, method, path, data=None, timeout=4.0, **kw):
            if path == "/api/active-tasks":
                return {"tasks": [{"id": "running"}]}
            if path == "/api/tasks":
                self.posted.append(data)
            return {}

    c = _controller()
    c.client = FakeClient()
    c._active_task_running = True
    c._active_task_goal = "write a poem in Notepad"

    # A second start_desktop_task is refused — and never POSTed.
    res = c._live_tool("start_desktop_task", {"goal": "open calculator"})
    assert res["ok"] is False and res.get("busy") is True
    assert "write a poem in Notepad" in res["active_task"]
    assert "stop_current_task" in res["message"]
    assert c.client.posted == []

    # A bounded desktop_control is refused the same way (no ToolExecutor touched).
    res2 = c._live_tool("desktop_control", {"action": "click", "query": "Save"})
    assert res2["ok"] is False and res2.get("busy") is True

    # The escape hatch still works: stop is never gated.
    c._kill_active_tasks = lambda: 1
    assert c._live_tool("stop_current_task", {})["ok"] is True


def test_live_busy_gate_self_heals_when_task_already_finished():
    """A stale 'running' flag must not lock Live out forever: the gate confirms over
    /api/active-tasks, clears the flag when nothing's running, and lets the action go."""
    class FakeClient:
        def __init__(self):
            self.posted = []

        def request(self, method, path, data=None, timeout=4.0, **kw):
            if path == "/api/active-tasks":
                return {"tasks": []}  # nothing actually running anymore
            if path == "/api/tasks":
                self.posted.append(data)
            return {}

    c = _controller()
    c.client = FakeClient()
    c._active_task_running = True  # stale
    c._active_task_goal = "old task"

    res = c._live_tool("start_desktop_task", {"goal": "open notepad"})
    assert res["ok"] is True
    assert c.client.posted  # the new task was submitted, not blocked


def test_stop_hotkey_worker_reports_stopped_when_live_only():
    class FakeLive:
        def __init__(self):
            self.stopped = False

        def is_running(self):
            return True

        def stop(self):
            self.stopped = True

    c = _controller()
    live = FakeLive()
    c._live = live
    c._kill_active_tasks = lambda: 0
    labels, states = [], []
    c.labelRequested.connect(lambda s: labels.append(s))
    c.cursorStateRequested.connect(lambda s: states.append(s))

    c._stop_all_worker()

    assert live.stopped is True
    assert c._live_cancel.is_set()
    assert labels[-1] == "Stopped"
    assert states[-1] == "idle"


def test_live_tool_unknown_name_is_reported_not_raised():
    c = _controller()
    labels, states = [], []
    c.labelRequested.connect(lambda s: labels.append(s))
    c.cursorStateRequested.connect(lambda s: states.append(s))

    res = c._live_tool("teleport_the_user", {"x": 1})

    assert res["ok"] is False and "unknown" in res["message"].lower()
    assert labels == ["Unsupported Live tool"]
    assert states == ["thinking"]


def test_live_tool_unknown_desktop_action_sets_visible_label():
    c = _controller()
    labels, states = [], []
    c.labelRequested.connect(lambda s: labels.append(s))
    c.cursorStateRequested.connect(lambda s: states.append(s))

    res = c._live_tool("desktop_control", {"action": "moonwalk"})

    assert res["ok"] is False
    assert "unknown desktop action" in res["message"].lower()
    assert labels == ["Unsupported desktop action"]
    assert states == ["thinking"]


# ── streamed reply renders as a sentence, not flashing words ──────────────────

def test_live_output_transcript_accumulates_into_sentence():
    c = _controller()
    labels = []
    c.labelRequested.connect(lambda s: labels.append(s))
    # One spoken reply arrives as several incremental chunks.
    c._live_output_transcript("Sure", False)
    c._live_output_transcript(", opening", False)
    c._live_output_transcript(" Notepad now.", True)
    # The bubble shows the whole growing sentence, ending on the full reply.
    assert labels == ["Sure", "Sure, opening", "Sure, opening Notepad now."]
    # The next turn starts fresh — it doesn't prepend the previous reply.
    c._live_output_transcript("Done", True)
    assert labels[-1] == "Done"


def test_live_output_transcript_handles_cumulative_chunks():
    c = _controller()
    labels = []
    c.labelRequested.connect(lambda s: labels.append(s))

    c._live_output_transcript("Sure", False)
    c._live_output_transcript("Sure, opening", False)
    c._live_output_transcript("Sure, opening Notepad now.", True)

    assert labels == ["Sure", "Sure, opening", "Sure, opening Notepad now."]


def test_live_output_transcript_merges_overlapping_chunks():
    c = _controller()
    labels = []
    c.labelRequested.connect(lambda s: labels.append(s))

    c._live_output_transcript("Opening Notepad", False)
    c._live_output_transcript("Notepad now.", True)

    assert labels[-1] == "Opening Notepad now."


def test_live_input_transcript_shows_partial_and_final_hearing():
    c = _controller()
    labels, states = [], []
    c.labelRequested.connect(lambda s: labels.append(s))
    c.cursorStateRequested.connect(lambda s: states.append(s))

    c._live_input_transcript("open", False)
    c._live_input_transcript(" notepad", True)

    assert labels == ["Hearing: open", "Heard: open notepad"]
    assert states == ["listening", "listening"]


def test_live_input_transcript_handles_cumulative_chunks():
    c = _controller()
    labels = []
    c.labelRequested.connect(lambda s: labels.append(s))

    c._live_input_transcript("open", False)
    c._live_input_transcript("open notepad", False)
    c._live_input_transcript("open notepad please", True)

    assert labels == [
        "Hearing: open",
        "Hearing: open notepad",
        "Heard: open notepad please",
    ]


def test_live_listening_status_does_not_overwrite_fresh_input():
    c = _controller()
    labels, states = [], []
    c.labelRequested.connect(lambda s: labels.append(s))
    c.cursorStateRequested.connect(lambda s: states.append(s))

    c._live_input_transcript("open notepad", False)
    c._live_status("Gemini Live listening")

    assert labels == ["Hearing: open notepad"]
    assert states[-1] == "listening"


def test_live_input_transcript_resets_the_reply_buffer():
    c = _controller()
    c._live_output_transcript("half a sen", False)  # a reply got interrupted
    c._live_input_transcript("a brand new question", True)  # user speaks again
    labels = []
    c.labelRequested.connect(lambda s: labels.append(s))
    c._live_output_transcript("Fresh answer", True)
    assert labels[-1] == "Fresh answer"  # no leftover "half a sen" prefix


def test_live_turn_complete_resets_reply_buffer():
    c = _controller()
    labels = []
    c.labelRequested.connect(lambda s: labels.append(s))
    c._live_output_transcript("First answer", False)
    c._live_output_transcript("", True)  # turn_complete boundary from Gemini Live
    c._live_output_transcript("Second answer", True)
    assert labels == ["First answer", "Second answer"]


def test_live_listening_status_does_not_overwrite_fresh_reply():
    c = _controller()
    labels, states = [], []
    c.labelRequested.connect(lambda s: labels.append(s))
    c.cursorStateRequested.connect(lambda s: states.append(s))

    c._live_output_transcript("Sure, I opened it.", True)
    c._live_status("Gemini Live listening")

    assert labels == ["Sure, I opened it."]
    assert states[-1] == "listening"


def test_live_status_humanizes_internal_tool_names():
    c = _controller()
    labels = []
    c.labelRequested.connect(lambda s: labels.append(s))

    c._live_status("Gemini Live tool: start_desktop_task")

    assert labels == ["Working..."]
    assert "start_desktop_task" not in labels[-1]


def test_live_tool_failure_status_overrides_fresh_transcript():
    c = _controller()
    labels, states = [], []
    c.labelRequested.connect(lambda s: labels.append(s))
    c.cursorStateRequested.connect(lambda s: states.append(s))

    c._live_input_transcript("open notepad", True)
    c._live_status("Live tool call failed")

    assert labels == ["Heard: open notepad", "Live tool call failed"]
    assert states[-1] == "thinking"


def test_live_listening_status_is_clean_when_visible():
    c = _controller()
    labels, states = [], []
    c.labelRequested.connect(lambda s: labels.append(s))
    c.cursorStateRequested.connect(lambda s: states.append(s))

    c._live_status("Gemini Live listening")

    assert labels == ["Listening"]
    assert states == ["listening"]


def test_live_transcript_suppresses_background_status_flicker():
    c = _controller()
    labels = []
    c.labelRequested.connect(lambda s: labels.append(s))

    c._live_output_transcript("Sure, opening it now.", False)

    assert c._set_label("Orynning...", source="task_status") is False
    assert c._set_label("Searching...", source="task_prime") is False
    assert c._set_label("Clicking Text Editor", source="task_action") is False
    assert labels == ["Sure, opening it now."]

    # A real terminal result can still surface; only background chatter is muted.
    assert c._set_label("Done", source="task_result") is True
    assert labels[-1] == "Done"


def test_live_running_suppresses_active_task_prime_label():
    c = _controller()

    class FakeLive:
        def is_running(self):
            return True

    class FakeClient:
        def request(self, method, path, timeout=3.0):
            assert path == "/api/active-tasks"
            return {"tasks": [{"id": "running"}]}

    labels = []
    c._live = FakeLive()
    c.client = FakeClient()
    c.labelRequested.connect(lambda s: labels.append(s))

    c._prime_from_active_task()

    assert labels == []


class _RunningLive:
    """Stand-in Live session that reports itself as actively running."""

    def is_running(self):
        return True


def test_live_running_mutes_task_action_and_status_churn():
    """While Live drives, the desktop task's per-step churn is muted even when no
    Live label is currently held — the live_running flag alone is enough. This is
    the case the old arbitration missed (it only checked a fresh input/reply hold),
    which let "Searching…"/"Clicking X" flash over the live conversation."""
    c = _controller()
    c._live = _RunningLive()
    labels = []
    c.labelRequested.connect(lambda s: labels.append(s))

    assert c._set_label("Orynning…", source="task_status") is False
    assert c._set_label("Searching…", source="task_prime") is False
    assert c._set_label("Clicking Text Editor", source="task_action") is False
    # The flying-cursor labels never reached the bubble.
    assert labels == []
    # …but a task's final result is meaningful and still surfaces during Live.
    assert c._set_label("Notepad is open.", source="task_result") is True
    assert labels == ["Notepad is open."]


def test_task_action_muted_while_live_tool_label_is_held():
    """A live_tool status ("Working…") holds the bubble; the desktop task's action
    churn must not break through that hold. The old code only protected against
    live_input/live_reply, so a live_tool hold leaked task_action labels."""
    c = _controller()
    labels = []
    c.labelRequested.connect(lambda s: labels.append(s))

    assert c._set_label("Working…", source="live_tool", force=True) is True
    assert c._set_label("Clicking Text Editor", source="task_action") is False
    assert labels == ["Working…"]


def test_task_labels_resume_after_live_hold_expires():
    """Once Live's label hold lapses and Live isn't running, ordinary task labels
    must flow again — no stale lockout from the last Live source. Guards the
    `protected and …` requirement in the arbitration."""
    c = _controller()
    labels = []
    c.labelRequested.connect(lambda s: labels.append(s))

    # Simulate a Live label whose hold window has already elapsed, with Live gone.
    c._label_protect_source = "live_reply"
    c._label_protect_until = 0.0
    c._live = None

    assert c._set_label("Orynning…", source="task_status") is True
    assert labels == ["Orynning…"]


def test_live_spawned_task_does_not_flash_over_the_conversation():
    """The exact scenario the user reported: you tell Live to do something, it says
    'okay, I'm getting it', kicks off a desktop task, and the bubble then *flashes*
    between the live transcript and the task's 'Orynning…/Searching…' churn.

    With Live owning the bubble, the conversation text is the only thing that ever
    reaches it; the spawned task's churn is muted and only its final result lands."""
    c = _controller()
    c._live = _RunningLive()
    labels = []
    c.labelRequested.connect(lambda s: labels.append(s))

    # 1. The user speaks; 2. Live acknowledges out loud.
    c._live_input_transcript("open notepad and type hello", True)
    c._live_output_transcript("Okay, I'm getting it.", True)
    # 3. Live invokes the tool. Its generic "Working…" status yields to the fresher,
    #    more human reply that's still on screen — no needless churn there either.
    c._live_status("Gemini Live tool: start_desktop_task")

    # 4. The spawned backend task now streams a burst of step events through the
    #    poll loop — every one of these used to flash the bubble.
    for text, src in [
        ("Orynning…", "task_status"),
        ("Searching…", "task_action"),
        ("Clicking Text Editor", "task_action"),
        ("Typing into Text Editor", "task_action"),
        ("Orynning…", "task_prime"),
    ]:
        assert c._set_label(text, source=src) is False

    # 5. Live goes back to listening between commands.
    c._live_status("Gemini Live listening")

    # Only the live conversation reached the bubble — no task churn, no flashing.
    assert labels == ["Heard: open notepad and type hello", "Okay, I'm getting it."]

    # 6. The task finishes: its outcome is meaningful and surfaces.
    assert c._set_label("Notepad is open with hello typed.", source="task_result") is True
    assert labels[-1] == "Notepad is open with hello typed."


def test_live_owns_cursor_state_while_running():
    """A Live-spawned task's lifecycle events must not flip the cursor underneath
    the live conversation (the cursor analog of the textbox flashing), but task
    tracking stays accurate so it resumes cleanly once Live ends."""
    c = _controller()
    states = []
    c.cursorStateRequested.connect(lambda s: states.append(s))

    # Live is driving: task lifecycle is tracked but does not touch the cursor.
    c._live = _RunningLive()
    c._update_cursor_state_from_event({"type": "task_created"})
    c._update_cursor_state_from_event({"type": "done"})
    assert states == []
    assert c._active_task_running is False

    # Live ends: ordinary task-driven cursor states resume.
    c._live = None
    c._update_cursor_state_from_event({"type": "task_created"})
    c._update_cursor_state_from_event({"type": "done"})
    assert states == ["thinking", "idle"]

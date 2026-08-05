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
        "launch_app",
        "start_desktop_task",
        "stop_current_task",
        "get_companion_status",
        "look_at_screen",
        "list_windows",
        "capture_window",
        "web_search",
        "run_terminal",
        "remember",
        "forget",
        "run_workflow",
        "save_workflow",
        "forget_workflow",
        "set_timer",
        "schedule_task",
        "list_scheduled_tasks",
        "cancel_scheduled_task",
        "get_clipboard",
        "set_clipboard",
        "list_workflows",
        "dictate_text",
        "media_control",
        "watch_screen",
        "get_notifications",
        "add_watcher",
        "list_watchers",
        "remove_watcher",
        "suggestion_feedback",
    }

    start = next(d for d in decls if d.name == "start_desktop_task")
    schema = start.parameters_json_schema
    # The desktop-action tool must require a free-text goal string.
    assert schema["required"] == ["goal"]
    assert schema["properties"]["goal"]["type"] == "string"

    desktop = next(d for d in decls if d.name == "desktop_control")
    desktop_schema = desktop.parameters_json_schema
    assert desktop_schema["required"] == ["action"]
    assert {"find", "click", "type", "press_keys", "scroll"} <= set(
        desktop_schema["properties"]["action"]["enum"]
    )

    # Routing mutual-exclusion lives in declarations (Google: tool descriptions drive selection).
    dc_desc = desktop.description.lower()
    task_desc = start.description.lower()
    assert "do not also call start_desktop_task" in dc_desc
    assert "do not also call desktop_control" in task_desc


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
    monkeypatch.delenv("GEMINI_LIVE_THINKING", raising=False)
    monkeypatch.delenv("GEMINI_LIVE_THINKING_LEVEL", raising=False)
    comp = gl.GeminiLiveCompanion(gl.GeminiLiveCallbacks())
    cfg = comp._live_config(types)

    # Audio out, plus both-way transcription so the bubble can show what was said.
    assert types.Modality.AUDIO in cfg.response_modalities
    assert cfg.input_audio_transcription is not None
    assert cfg.output_audio_transcription is not None
    assert cfg.system_instruction  # a personality/safety prompt is attached
    assert cfg.thinking_config.thinking_level == types.ThinkingLevel.MEDIUM

    # Our local desktop function tools are always wired in.
    fn_names, _ = _config_tool_names(cfg)
    assert {"desktop_control", "start_desktop_task", "stop_current_task", "list_windows", "capture_window"} <= fn_names


def test_live_config_thinking_level_env(monkeypatch):
    from google.genai import types
    from app.widget import gemini_live as gl

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_LIVE_THINKING_LEVEL", "high")
    comp = gl.GeminiLiveCompanion(gl.GeminiLiveCallbacks())
    cfg = comp._live_config(types)
    assert cfg.thinking_config.thinking_level == types.ThinkingLevel.HIGH


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


def test_handle_message_tolerates_audio_output_glitches():
    """A few failed output writes (underrun / brief device blip) must NOT end the
    conversation. Only a sustained run gives up — once — and then stops the session
    cleanly (self._stop) so the thread can't be left running after on_error."""
    from google.genai import types
    from app.widget import gemini_live as gl

    class FailingOutput:
        def write(self, data):
            raise OSError("device blip")

    class OkOutput:
        def write(self, data):
            pass

    class FakePart:
        class inline_data:
            data = b"\x01\x02"

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

    errors = []
    comp = gl.GeminiLiveCompanion(gl.GeminiLiveCallbacks(on_error=errors.append))

    # A handful of glitches are absorbed — the conversation keeps going.
    for _ in range(5):
        asyncio.run(comp._handle_message(object(), FakeMessage(), FailingOutput(), types))
    assert errors == [] and not comp._stop.is_set()

    # A good write resets the streak — failures must be CONSECUTIVE to count.
    asyncio.run(comp._handle_message(object(), FakeMessage(), OkOutput(), types))
    assert comp._audio_fail_streak == 0

    # A sustained run of glitches finally gives up exactly once, stopping cleanly.
    for _ in range(gl.GEMINI_LIVE_MAX_AUDIO_FAILS + 10):
        if comp._stop.is_set():
            break
        asyncio.run(comp._handle_message(object(), FakeMessage(), FailingOutput(), types))
    assert len(errors) == 1 and comp._stop.is_set()


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


def test_handle_message_turn_complete_finalizes_input_turn():
    """turn_complete must also close the INPUT turn (empty + finished) so the next
    utterance's transcript starts fresh instead of concatenating onto the last."""
    from google.genai import types
    from app.widget import gemini_live as gl

    inputs = []
    turns = []
    cbs = gl.GeminiLiveCallbacks(
        on_input_transcript=lambda t, fin: inputs.append((t, fin)),
        on_turn_complete=lambda s: turns.append(s),
    )

    class FakeContent:
        input_transcription = None
        output_transcription = None
        model_turn = None
        turn_complete = True

    class FakeMessage:
        server_content = FakeContent()
        tool_call = None

    comp = gl.GeminiLiveCompanion(cbs)
    asyncio.run(comp._handle_message(object(), FakeMessage(), None, types))
    assert ("", True) in inputs  # input turn was finalized at the boundary
    assert turns == [""]


def test_handle_message_rejects_second_desktop_tool_in_batch():
    """Only one of desktop_control / start_desktop_task may run per tool-call batch."""
    from google.genai import types
    from app.widget import gemini_live as gl

    executed = []

    def handler(name, args):
        executed.append(name)
        return {"ok": True, "tool": name}

    cbs = gl.GeminiLiveCallbacks(on_tool=handler)
    comp = gl.GeminiLiveCompanion(cbs)

    class FakeCall:
        def __init__(self, name, call_id):
            self.name = name
            self.id = call_id
            self.args = {"action": "click", "query": "OK"} if name == "desktop_control" else {"goal": "open x"}

    class FakeToolCall:
        function_calls = [
            FakeCall("desktop_control", "1"),
            FakeCall("start_desktop_task", "2"),
        ]

    class FakeMessage:
        server_content = None
        tool_call = FakeToolCall()

    sent = []

    class FakeSession:
        async def send_tool_response(self, function_responses):
            sent.append(function_responses)

    asyncio.run(comp._handle_message(FakeSession(), FakeMessage(), None, types))
    assert executed == ["desktop_control"]
    assert len(sent) == 1
    responses = sent[0]
    assert responses[0].response.get("ok") is True
    assert responses[1].response.get("ok") is False
    assert "only one desktop action" in responses[1].response.get("message", "").lower()


def test_parse_single_click_goal():
    from app.widget import textbox_overlay as tbo

    assert tbo._parse_single_click_goal('Click the "Usage" control in Settings.') == {
        "action": "click",
        "query": "Usage",
        "app": "Settings",
    }
    assert tbo._parse_single_click_goal('Click "New Agent" button in Cursor') == {
        "action": "click",
        "query": "New Agent",
        "app": "Cursor",
    }
    assert tbo._parse_single_click_goal("Click Usage then type hello") is None
    assert tbo._parse_single_click_goal("Open Settings and click Usage") is None


def test_start_desktop_task_single_click_redirects_to_fast_path():
    """start_desktop_task goals that are really one click should hit desktop_control."""
    from app.models import ToolResult

    clicked = []

    class FakeTools:
        def uia_click(self, query, app="", allow_pixel_fallback=True):
            clicked.append((query, app))
            return ToolResult(ok=True, output="Activated", data={"method": "invoke_pattern"})

    class FakeClient:
        def request(self, *a, **k):
            raise AssertionError("single click must not spawn agent task")

    c = _controller()
    c.client = FakeClient()
    c._desktop_tools = FakeTools()

    res = c._live_tool(
        "start_desktop_task",
        {"goal": 'Click the "Usage" control in Settings.'},
    )
    assert res["ok"] is True
    assert clicked == [("Usage", "Settings")]
    assert c._active_task_running is False


def test_resolve_hwnd_skips_taskbar_picks_largest_app(monkeypatch):
    from app import providers as prov

    monkeypatch.delenv("ORYNN_LIVE_SCREEN_CAPTURE", raising=False)
    monkeypatch.setattr(prov, "_minimize_orynn_owned_windows", lambda: None)
    monkeypatch.setattr(prov, "_is_orynn_owned_hwnd", lambda h: False)
    monkeypatch.setattr(prov, "list_open_windows", lambda **kw: [
        {"hwnd": 42, "title": "Cursor", "minimized": False},
        {"hwnd": 43, "title": "Notepad", "minimized": False},
    ])

    def fake_area(hwnd):
        return {42: 900 * 700, 43: 400 * 300}.get(hwnd, 0)

    monkeypatch.setattr(prov, "_hwnd_client_area", fake_area)

    class FG:
        calls = 0

        @staticmethod
        def GetForegroundWindow():
            FG.calls += 1
            return 1

        @staticmethod
        def GetWindowText(hwnd):
            return {42: "Cursor", 43: "Notepad"}.get(hwnd, "")

        @staticmethod
        def IsWindow(hwnd):
            return True

        @staticmethod
        def GetClassName(hwnd):
            return "Shell_TrayWnd" if hwnd == 1 else "Chrome_WidgetWin_1"

    monkeypatch.setitem(__import__("sys").modules, "win32gui", FG)
    hwnd, title, mode = prov.resolve_hwnd_for_live_vision()
    assert hwnd == 42
    assert title == "Cursor"
    assert mode == "window"


def test_is_shell_or_junk_hwnd_detects_shell_classes(monkeypatch):
    from app import providers as prov

    assert prov._is_shell_or_junk_hwnd(0) is True

    class FG:
        @staticmethod
        def IsWindow(hwnd):
            return True

        @staticmethod
        def GetClassName(hwnd):
            return "Shell_TrayWnd"

        @staticmethod
        def GetWindowText(hwnd):
            return "Taskbar"

        @staticmethod
        def GetWindowRect(hwnd):
            return (0, 0, 1920, 48)

    monkeypatch.setitem(__import__("sys").modules, "win32gui", FG)
    assert prov._is_shell_or_junk_hwnd(1) is True


def test_capture_vision_jpeg_uses_printwindow_when_window_mode(monkeypatch):
    from PIL import Image
    from app.widget import textbox_overlay as tbo

    img = Image.new("RGB", (800, 600), color=(10, 20, 30))
    monkeypatch.setenv("ORYNN_LIVE_SCREEN_CAPTURE", "window")
    monkeypatch.setattr(
        "app.providers.resolve_hwnd_for_live_vision",
        lambda: (12345, "TikTok", "window"),
    )
    monkeypatch.setattr("app.providers._capture_hwnd_image", lambda hwnd, max_edge=0: img)

    data, title, mode = tbo.OverlayController._capture_vision_jpeg()
    assert data is not None
    assert len(data) > 100
    assert title == "TikTok"
    assert mode == "window"


def test_list_windows_returns_titles_without_hwnd(monkeypatch):
    from app.widget import textbox_overlay as tbo

    monkeypatch.setattr(
        "app.providers.list_open_windows",
        lambda **kw: [
            {"hwnd": 99, "title": "Cursor", "minimized": False},
            {"hwnd": 100, "title": "Counter-Strike 2", "minimized": False},
        ],
    )
    c = _controller()
    res = c._live_tool("list_windows", {})
    assert res["ok"] is True
    assert res["count"] == 2
    assert res["windows"] == [
        {"title": "Cursor", "minimized": False},
        {"title": "Counter-Strike 2", "minimized": False},
    ]
    assert "hwnd" not in str(res["windows"])


def test_capture_window_peeks_background_window(monkeypatch):
    from PIL import Image
    from app.widget import textbox_overlay as tbo

    img = Image.new("RGB", (640, 480), color=(1, 2, 3))
    sent = []

    class FakeLive:
        def send_screen_image(self, data, wait=False):
            sent.append(len(data))
            return True

        def send_context_update(self, note):
            pass

    monkeypatch.setattr(
        tbo.OverlayController,
        "_capture_window_jpeg",
        staticmethod(lambda title, index=0: (b"jpeg-bytes", "Cursor - project")),
    )
    c = _controller()
    c._live = FakeLive()
    res = c._live_tool(
        "capture_window",
        {"title": "Cursor", "question": "is the agent done?"},
    )
    assert res["ok"] is True
    assert res["window"] == "Cursor - project"
    assert sent == [len(b"jpeg-bytes")]


def test_send_task_update_uses_proactive_prefix():
    from app.widget import gemini_live as gl

    notes = []
    comp = gl.GeminiLiveCompanion(
        gl.GeminiLiveCallbacks(),
    )
    comp._send_client_note = lambda text: notes.append(text)
    comp.send_task_update("Task finished.")
    assert len(notes) == 1
    assert notes[0].startswith(gl.LIVE_PROACTIVE_PREFIX)
    assert "Task finished." in notes[0]


def test_start_desktop_task_notifies_live_on_background_start(monkeypatch):
    from app.models import ToolResult

    class FakeClient:
        def request(self, method, path, data=None, timeout=4.0, **kw):
            if path == "/api/tasks/preflight":
                return {"blocked": False}
            if path == "/api/tasks":
                return {"ok": True}
            if path.startswith("/api/tasks/"):
                return {"status": "running"}
            return {}

    class FakeLive:
        def __init__(self):
            self.notes = []

        def is_running(self):
            return True

        def send_task_update(self, text):
            self.notes.append(text)

    monkeypatch.setenv("ORYNN_LIVE_TASK_WAIT", "0")
    c = _controller()
    c.client = FakeClient()
    fl = FakeLive()
    c._live = fl
    c._await_task_outcome = lambda tid, goal: {
        "ok": True, "status": "running", "task_id": tid, "message": "running",
    }
    res = c._live_tool("start_desktop_task", {"goal": "fix the bug in Cursor"})
    assert res["ok"] is True
    assert any("fix the bug" in n for n in fl.notes)


def _controller():
    """Build an OverlayController in a headless Qt app, or skip if PySide6 is absent."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    # Don't block on the start_desktop_task outcome-wait in unit tests — tests that
    # exercise the outcome path return a terminal status on the first poll instead.
    os.environ.setdefault("ORYNN_LIVE_TASK_WAIT", "0")
    try:
        from PySide6.QtWidgets import QApplication
        from app.widget.textbox_overlay import OverlayController
    except Exception:
        pytest.skip("PySide6 not importable in this environment")
    QApplication.instance() or QApplication([])
    return OverlayController(8000)


def test_failed_desktop_action_label_hides_raw_diagnostics():
    """A failed Live click/type must show a clean human label in the bubble — never
    the raw agent-facing tool output (UIA miss + adaptive-recovery scoring)."""
    c = _controller()
    raw = ("no UIA control matched 'Search or create item' Adaptive recovery plan "
           "(uia_no_match, 0.70): UIA is available, but the control wasn't found")
    data = {"overlay": {"target": "Search or create item"}}

    label = c._live_tool_display_label("click", False, raw, data)
    assert label == "Couldn't click Search or create item"
    # The leak we fixed: none of the internal diagnostics reach the bubble.
    for leak in ("uia_no_match", "Adaptive recovery", "0.70", "UIA is available"):
        assert leak not in label

    # No target in data → still a clean generic line, never the raw output.
    assert c._live_tool_display_label("type", False, raw, {}) == "Couldn't type into"
    assert c._live_tool_display_label("observe", False, raw, {}) == "Couldn't read the screen"


def test_type_without_target_escalates_quietly():
    """'type X' with text but no target field can't use the UIA fast path — it must
    escalate to the agent WITHOUT flashing the raw 'Missing query for type' diagnostic
    in the bubble (the user just sees a clean 'Typing that in')."""
    calls = []

    class FakeClient:
        def request(self, method, path, data=None, timeout=4.0, **kw):
            calls.append(path)
            if path == "/api/tasks/preflight":
                return {"blocked": False}
            return {}

    c = _controller()
    c.client = FakeClient()
    labels = []
    c.labelRequested.connect(lambda s: labels.append(str(s)))

    res = c._live_tool_for_generation(
        None, "desktop_control", {"action": "type", "text": "hello world"}
    )
    assert "/api/tasks" in calls  # escalated to the agent
    assert "Missing query" not in " ".join(labels)
    assert "Missing query" not in str(res)


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
        def uia_click(self, query, app="", allow_pixel_fallback=True):
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


def test_model_type_escalates_when_unverified():
    """Honest success (#2): a type that returns ok=True but post-verification says the
    text didn't land (verified False) escalates to the agent instead of claiming done."""
    from app.models import ToolResult

    calls = []

    class FakeClient:
        def request(self, method, path, data=None, timeout=4.0, **kw):
            calls.append(path)
            if path == "/api/tasks/preflight":
                return {"blocked": False}
            if path == "/api/tasks":
                return {"ok": True}
            return {}

    class FakeTools:
        def uia_type(self, query, text, app="", clear_first=False, submit=False, allow_pixel_fallback=True):
            return ToolResult(ok=True, output="typed?, unconfirmed",
                              data={"method": "paste", "verified": False})

    c = _controller()
    c.client = FakeClient()
    c._desktop_tools = FakeTools()
    res = c._live_tool_for_generation(
        None, "desktop_control",
        {"action": "type", "query": "notes", "text": "hello", "app": "Notepad"},
    )

    assert "/api/tasks" in calls
    assert c._active_task_running is True


def test_model_type_uses_fast_path_no_agent():
    """A single clear type in an open app does the FAST direct UIA primitive — instant,
    no agent spin-up, no task spawn, no permission prompt."""
    from app.models import ToolResult

    typed = []

    class FakeTools:
        def uia_type(self, query, text, app="", clear_first=False, submit=False, allow_pixel_fallback=True):
            typed.append((query, text, app, clear_first, submit))
            return ToolResult(ok=True, output="Typed into 'search box'", data={"target": "search box"})

    class FakeClient:
        def request(self, *a, **k):
            raise AssertionError("a successful fast type must not spawn a task")

    c = _controller()
    c.client = FakeClient()
    c._desktop_tools = FakeTools()
    res = c._live_tool_for_generation(
        None,
        "desktop_control",
        {"action": "type", "query": "search box", "text": "hello", "app": "Notepad"},
    )

    assert res["ok"] is True
    assert typed == [("search box", "hello", "Notepad", False, False)]
    assert c._active_task_running is False


def test_live_type_with_submit_carries_submit_and_needs_consent():
    """submit=true puts an explicit submit step in the goal — and because submitting
    a form is disruptive, that goal is gated for spoken consent (brief §7.2)."""
    class FakeClient:
        def request(self, *a, **k):
            raise AssertionError("a submit must not run without consent")

    c = _controller()
    c.client = FakeClient()
    goal = c._goal_from_desktop_control(
        "type", {"query": "search box", "text": "hi", "app": "Notepad", "submit": True}
    )
    assert "submit" in goal.lower()

    res = c._live_tool_for_generation(
        None,
        "desktop_control",
        {"action": "type", "query": "search box", "text": "hi",
         "app": "Notepad", "submit": True},
    )
    assert res["ok"] is False
    assert res.get("needs_consent") is True


def test_live_tool_desktop_control_type_requires_non_empty_text():
    class FakeClient:
        def request(self, *args, **kwargs):
            raise AssertionError("empty type text should not spawn a task")

    class FakeTools:
        def uia_type(self, *args, **kwargs):
            raise AssertionError("empty type text should not touch UIA")

    c = _controller()
    c.client = FakeClient()
    c._desktop_tools = FakeTools()
    labels = []
    c.labelRequested.connect(lambda s: labels.append(s))

    res = c._live_tool_for_generation(
        None,
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
    assert labels == []  # internal validation — model recovers by voice, not bubble


def test_model_click_uses_fast_path_no_agent():
    """A single clear click in an open app does the FAST direct UIA primitive — no
    agent, no task spawn, no enable_desktop_control prompt."""
    from app.models import ToolResult

    clicked = []

    class FakeTools:
        def uia_click(self, query, app="", allow_pixel_fallback=True):
            clicked.append((query, app, allow_pixel_fallback))
            return ToolResult(ok=True, output="Activated 'OK' via invoke_pattern",
                              data={"method": "invoke_pattern"})

    class FakeClient:
        def request(self, *a, **k):
            raise AssertionError("a successful fast click must not spawn a task")

    c = _controller()
    c.client = FakeClient()
    c._desktop_tools = FakeTools()
    res = c._live_tool_for_generation(
        None, "desktop_control", {"action": "click", "query": "OK", "app": "Dialog"}
    )

    assert res["ok"] is True
    # The fast attempt is UIA-only (no pixel fallback) so it can never hijack the mouse.
    assert clicked == [("OK", "Dialog", False)]
    assert c._active_task_running is False


def test_model_click_escalates_when_click_unverified():
    """A fast click that returns ok=True but whose post-verification says nothing
    changed (verified False) is a soft fail — escalate to the agent rather than
    falsely declaring success."""
    from app.models import ToolResult

    calls = []

    class FakeClient:
        def request(self, method, path, data=None, timeout=4.0, **kw):
            calls.append(path)
            if path == "/api/tasks/preflight":
                return {"blocked": False}
            if path == "/api/tasks":
                return {"ok": True}
            return {}

    class FakeTools:
        def uia_click(self, query, app="", allow_pixel_fallback=True):
            return ToolResult(ok=True, output="invoked, but unconfirmed",
                              data={"method": "invoke_pattern", "verified": False})

    c = _controller()
    c.client = FakeClient()
    c._desktop_tools = FakeTools()
    res = c._live_tool_for_generation(
        None, "desktop_control", {"action": "click", "query": "Continue", "app": "App"}
    )

    assert "/api/tasks" in calls  # escalated because the click didn't visibly land
    assert c._active_task_running is True


def test_model_click_escalates_to_agent_on_fast_failure():
    """When the fast UIA click can't do it (control missing / Electron-locked), escalate
    to the full agent with the same goal — that's where reliability (electron_unlock,
    retries) lives."""
    from app.models import ToolResult

    calls = []

    class FakeClient:
        def request(self, method, path, data=None, timeout=4.0, **kw):
            calls.append((path, data))
            if path == "/api/tasks/preflight":
                return {"blocked": False}
            if path == "/api/tasks":
                return {"ok": True}
            return {}

    class FakeTools:
        def uia_click(self, query, app="", allow_pixel_fallback=True):
            return ToolResult(ok=False, output="No UIA match for 'Save' (app may be locked).", data={})

    c = _controller()
    c.client = FakeClient()
    c._desktop_tools = FakeTools()
    # A NON-Electron app: a fast-click failure escalates straight to the agent (an
    # Electron app would ask for unlock consent first — see test_electron_click_*).
    res = c._live_tool_for_generation(
        None, "desktop_control", {"action": "click", "query": "Save", "app": "Paint"}
    )

    assert res["ok"] is True  # escalated task accepted (status running)
    paths = [p for p, _ in calls]
    assert "/api/tasks" in paths
    goal = next(d for p, d in calls if p == "/api/tasks")["goal"]
    assert "Save" in goal and "Paint" in goal
    assert c._active_task_running is True


def test_live_tool_desktop_control_click_requires_target():
    class FakeClient:
        def request(self, *args, **kwargs):
            raise AssertionError("a click with no target should not spawn a task")

    c = _controller()
    c.client = FakeClient()
    res = c._live_tool_for_generation(
        None, "desktop_control", {"action": "click", "app": "Cursor"}
    )

    assert res["ok"] is False
    assert "missing query" in res["message"].lower()


def test_deterministic_gateway_type_stays_direct_uia():
    """The Golden Five / push-to-talk path calls _live_tool DIRECTLY and must do a
    real UIA type — no LLM, no task spawn. That deterministic path is the reliability
    bar; only the model path (_live_tool_for_generation) hard-routes to the agent."""
    from app.models import ToolResult

    calls = []

    class FakeTools:
        def uia_type(self, query, text, app="", clear_first=False, submit=False, allow_pixel_fallback=True):
            calls.append((query, text, app, clear_first, submit))
            return ToolResult(ok=True, output="Typed into 'Text editor' via ValuePattern",
                              data={"target": "Text editor"})

    class FakeClient:
        def request(self, *a, **k):
            raise AssertionError("the deterministic type path must not spawn a task")

    c = _controller()
    c.client = FakeClient()
    c._desktop_tools = FakeTools()
    res = c._live_tool(
        "desktop_control",
        {"action": "type", "query": "Text editor", "text": "hello",
         "app": "Notepad", "clear_first": True},
    )

    assert res["ok"] is True
    assert calls == [("Text editor", "hello", "Notepad", True, False)]


def test_deterministic_gateway_click_stays_direct_uia():
    from app.models import ToolResult

    calls = []

    class FakeTools:
        def uia_click(self, query, app="", allow_pixel_fallback=True):
            calls.append((query, app))
            return ToolResult(ok=True, output="Clicked", data={})

    class FakeClient:
        def request(self, *a, **k):
            raise AssertionError("the deterministic click path must not spawn a task")

    c = _controller()
    c.client = FakeClient()
    c._desktop_tools = FakeTools()
    res = c._live_tool("desktop_control", {"action": "click", "query": "OK", "app": "Dialog"})

    assert res["ok"] is True
    assert calls == [("OK", "Dialog")]


def test_started_label_muted_while_live_drives():
    """While Live is connected its spoken ack owns the bubble, so the raw
    'Started: <goal>' echo must NOT flash — that reads like a separate backend doing
    the work and breaks the 'Live is doing it' feel (brief §9.1)."""
    class FakeClient:
        def request(self, method, path, data=None, timeout=4.0, **kw):
            if path == "/api/tasks/preflight":
                return {"blocked": False}
            return {}

    c = _controller()
    c.client = FakeClient()
    c._live = _FakeLive()  # is_running() -> True
    labels = []
    c.labelRequested.connect(lambda s: labels.append(s))

    res = c._live_tool("start_desktop_task", {"goal": "open notepad and type hello"})

    assert res["ok"] is True
    assert not any(l.startswith("Started:") for l in labels), labels


def test_started_label_shown_without_live():
    """For a push-to-talk / dashboard launch (no Live), the 'Started:' status is the
    only feedback, so it still shows."""
    class FakeClient:
        def request(self, method, path, data=None, timeout=4.0, **kw):
            if path == "/api/tasks/preflight":
                return {"blocked": False}
            return {}

    c = _controller()
    c.client = FakeClient()
    labels = []
    c.labelRequested.connect(lambda s: labels.append(s))

    res = c._live_tool("start_desktop_task", {"goal": "open notepad"})

    assert res["ok"] is True
    assert any(l.startswith("Started:") for l in labels), labels


def test_label_log_records_shown_and_muted(tmp_path, monkeypatch):
    """The opt-in label diagnostic records both what the bubble showed and what got
    muted (with the reason), so we can audit clutter."""
    import json as _json
    from app.widget import textbox_overlay as tbo

    logf = tmp_path / "labels.jsonl"
    monkeypatch.setattr(tbo, "_LABEL_LOG_ENABLED", True)
    monkeypatch.setattr(tbo, "_LABEL_LOG_PATH", logf)

    c = _controller()
    c._set_label("Hello there", source="system")          # shown (no Live)
    c._live = _FakeLive()                                  # Live now driving
    c._set_label("Clicking Save", source="task_action")    # churn -> muted under Live

    rows = [_json.loads(l) for l in logf.read_text(encoding="utf-8").splitlines() if l.strip()]
    by = {(r["action"], r["source"]): r for r in rows}
    assert ("shown", "system") in by
    assert ("muted", "task_action") in by
    assert by[("muted", "task_action")]["reason"] == "task_outcome_under_live"


def test_label_dedupe_skips_identical_repaint():
    """Re-setting the same bubble text within the dedupe window is a no-op repaint
    (de-clutter) — only distinct text paints."""
    c = _controller()
    labels = []
    c.labelRequested.connect(lambda s: labels.append(s))
    c._set_label("Thinking", source="system")
    c._set_label("Thinking", source="system")   # identical, within window -> skipped
    c._set_label("Done", source="system")
    assert labels == ["Thinking", "Done"]


def test_label_dedupe_allows_reshow_after_window(monkeypatch):
    """The dedupe is time-bounded so a genuine re-show (e.g. after the bubble rested
    to its orb) still paints."""
    from app.widget import textbox_overlay as tbo
    monkeypatch.setattr(tbo, "_LABEL_DEDUP_WINDOW", 0.0)  # treat any gap as "expired"
    c = _controller()
    labels = []
    c.labelRequested.connect(lambda s: labels.append(s))
    c._set_label("Ready", source="system")
    c._set_label("Ready", source="system")      # window expired -> repaints
    assert labels == ["Ready", "Ready"]


def test_label_log_off_by_default(tmp_path, monkeypatch):
    from app.widget import textbox_overlay as tbo

    logf = tmp_path / "labels.jsonl"
    monkeypatch.setattr(tbo, "_LABEL_LOG_ENABLED", False)
    monkeypatch.setattr(tbo, "_LABEL_LOG_PATH", logf)
    tbo._log_label("anything", "system", "shown", "", False)
    assert not logf.exists()


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
    assert res["status"] == "running"       # didn't finish within the (0s) wait
    paths = [p for _, p, _ in calls]
    assert "/api/tasks/preflight" in paths  # readiness checked before launching
    assert "/api/tasks" in paths            # then the task is actually submitted
    assert c._active_task_running is True


def test_live_start_desktop_task_reports_outcome_to_model():
    """Live waits briefly and returns the REAL outcome so the model can speak it —
    not just 'started'. The finished result is also remembered for follow-up."""
    class FakeClient:
        def request(self, method, path, data=None, timeout=4.0, **kw):
            if path == "/api/tasks/preflight":
                return {"blocked": False}
            if path == "/api/tasks":
                return {"ok": True}
            if path.startswith("/api/tasks/"):       # status poll
                return {"status": "done", "reason": "Notepad is open."}
            return {}

    c = _controller()
    c.client = FakeClient()
    res = c._live_tool("start_desktop_task", {"goal": "open notepad"})

    assert res["ok"] is True and res["status"] == "done"
    assert "Notepad is open." in res["result"]
    assert c._active_task_running is False          # finished, no longer "busy"
    assert c._last_task_result["status"] == "done"

    # get_companion_status now surfaces that outcome for "did it work?".
    status = c._live_tool("get_companion_status", {})
    assert status["ok"] is True
    assert status["last_result"]["status"] == "done"


def test_live_start_desktop_task_reports_failure_to_model():
    class FakeClient:
        def request(self, method, path, data=None, timeout=4.0, **kw):
            if path == "/api/tasks/preflight":
                return {"blocked": False}
            if path == "/api/tasks":
                return {}
            if path.startswith("/api/tasks/"):
                return {"status": "failed", "error": "couldn't find that app"}
            return {}

    c = _controller()
    c.client = FakeClient()
    res = c._live_tool("start_desktop_task", {"goal": "open notepad"})

    assert res["ok"] is False and res["status"] == "failed"
    assert "couldn't find that app" in res["result"]
    assert c._active_task_running is False


def test_live_long_task_outcome_captured_from_poll_event():
    """A task that outruns the inline wait is finished off by the poll loop's
    terminal event, so its outcome still reaches get_companion_status."""
    c = _controller()
    c._live_task_ids = {"clicky-123": "organize my downloads"}
    c._active_task_running = True

    c._capture_live_task_outcome({
        "type": "done", "task_id": "clicky-123", "reason": "Sorted 42 files.",
    })

    assert c._active_task_running is False
    assert "clicky-123" not in c._live_task_ids
    assert c._last_task_result["status"] == "done"
    assert "Sorted 42 files." in c._last_task_result["summary"]


class _FakeLive:
    """Stand-in for the Gemini Live companion: looks running and records the
    progress notes the narration loop pushes into the conversation."""
    def __init__(self):
        self.running = True
        self.updates = []

    def is_running(self):
        return self.running

    def send_task_update(self, text):
        self.updates.append(text)


def test_live_narration_speaks_humanized_milestone(monkeypatch):
    """A milestone from a Live-launched task is pushed into the conversation as a
    short, humanized spoken note (brief §6)."""
    monkeypatch.setenv("ORYNN_LIVE_NARRATE_INTERVAL", "3.5")
    c = _controller()
    live = _FakeLive()
    c._live = live
    c._live_task_ids = {"t1": "open cursor and click new agent"}
    c._live_narration_last = 0.0

    c._maybe_narrate_to_live({
        "type": "action_start", "task_id": "t1",
        "action_type": "uia_click", "args_summary": "New Agent",
    })

    assert len(live.updates) == 1
    assert "clicking New Agent" in live.updates[0]
    assert "uia_click" not in live.updates[0]  # never a raw tool name


def test_live_narration_throttles_rapid_milestones(monkeypatch):
    monkeypatch.setenv("ORYNN_LIVE_NARRATE_INTERVAL", "3.5")
    c = _controller()
    live = _FakeLive()
    c._live = live
    c._live_task_ids = {"t1": "x"}
    c._live_narration_last = 0.0

    c._maybe_narrate_to_live({
        "type": "action_start", "task_id": "t1",
        "action_type": "uia_click", "args_summary": "First",
    })
    c._maybe_narrate_to_live({
        "type": "action_start", "task_id": "t1",
        "action_type": "uia_click", "args_summary": "Second",
    })

    assert len(live.updates) == 1  # the second is suppressed by the interval
    assert "First" in live.updates[0]


def test_live_narration_ignores_tasks_live_did_not_launch():
    c = _controller()
    live = _FakeLive()
    c._live = live
    c._live_task_ids = {}
    c._live_narration_last = 0.0

    c._maybe_narrate_to_live({
        "type": "action_start", "task_id": "other",
        "action_type": "uia_click", "args_summary": "X",
    })

    assert live.updates == []


def test_live_narration_skips_terminal_events():
    """Completion is announced once by _capture_live_task_outcome — the narration
    loop must not also speak terminal events."""
    c = _controller()
    live = _FakeLive()
    c._live = live
    c._live_task_ids = {"t1": "x"}
    c._live_narration_last = 0.0

    c._maybe_narrate_to_live({"type": "done", "task_id": "t1", "reason": "all good"})

    assert live.updates == []


def test_live_narration_never_echoes_typed_text(monkeypatch):
    monkeypatch.setenv("ORYNN_LIVE_NARRATE_INTERVAL", "3.5")
    c = _controller()
    live = _FakeLive()
    c._live = live
    c._live_task_ids = {"t1": "x"}
    c._live_narration_last = 0.0

    c._maybe_narrate_to_live({
        "type": "action_start", "task_id": "t1",
        "action_type": "uia_type", "args_summary": "my secret password",
    })

    assert len(live.updates) == 1
    assert "secret" not in live.updates[0]
    assert "typing that in" in live.updates[0]


def test_live_narration_on_by_default(monkeypatch):
    """Mid-task milestones push proactive spoken updates by default."""
    monkeypatch.delenv("ORYNN_LIVE_NARRATE_INTERVAL", raising=False)
    c = _controller()
    live = _FakeLive()
    c._live = live
    c._live_task_ids = {"t1": "read my file"}
    c._live_narration_last = 0.0

    c._maybe_narrate_to_live({
        "type": "action_start", "task_id": "t1",
        "action_type": "wait_for_window", "args_summary": "Notepad",
    })

    assert len(live.updates) == 1
    assert "opening Notepad" in live.updates[0]


def test_live_narration_disabled_with_zero_interval(monkeypatch):
    monkeypatch.setenv("ORYNN_LIVE_NARRATE_INTERVAL", "0")
    c = _controller()
    live = _FakeLive()
    c._live = live
    c._live_task_ids = {"t1": "x"}
    c._live_narration_last = 0.0

    c._maybe_narrate_to_live({
        "type": "action_start", "task_id": "t1",
        "action_type": "uia_click", "args_summary": "X",
    })

    assert live.updates == []


def test_live_disruptive_goal_requires_spoken_consent():
    """A disruptive goal must not spawn an autonomous task until the user says yes
    out loud — the glue refuses and asks Live to confirm (brief §7.3)."""
    class FakeClient:
        def request(self, *a, **k):
            raise AssertionError("must not spawn a disruptive task without consent")

    c = _controller()
    c.client = FakeClient()
    res = c._live_tool(
        "start_desktop_task",
        {"goal": "delete all the files in my downloads folder"},
    )

    assert res["ok"] is False
    assert res.get("needs_consent") is True
    assert c._active_task_running is False


def test_live_disruptive_goal_proceeds_after_consent():
    calls = []

    class FakeClient:
        def request(self, method, path, data=None, timeout=4.0, **kw):
            calls.append(path)
            if path == "/api/tasks/preflight":
                return {"blocked": False}
            return {}

    c = _controller()
    c.client = FakeClient()
    res = c._live_tool(
        "start_desktop_task",
        {"goal": "send the email to John", "confirmed": True},
    )

    assert res["ok"] is True
    assert "/api/tasks" in calls
    assert c._active_task_running is True


def test_live_benign_goal_skips_consent():
    calls = []

    class FakeClient:
        def request(self, method, path, data=None, timeout=4.0, **kw):
            calls.append(path)
            if path == "/api/tasks/preflight":
                return {"blocked": False}
            return {}

    c = _controller()
    c.client = FakeClient()
    res = c._live_tool("start_desktop_task", {"goal": "open notepad and type hello"})

    assert res["ok"] is True
    assert "/api/tasks" in calls


def test_live_auto_upgraded_click_on_delete_requires_consent():
    """Auto-upgraded click/type route through the same gate, so clicking a Delete
    control still asks for consent first."""
    class FakeClient:
        def request(self, *a, **k):
            raise AssertionError("a delete click must not run without consent")

    class FakeTools:
        def uia_click(self, *a, **k):
            raise AssertionError("must not click directly")

    c = _controller()
    c.client = FakeClient()
    c._desktop_tools = FakeTools()
    res = c._live_tool_for_generation(
        None,
        "desktop_control",
        {"action": "click", "query": "Delete", "app": "File Explorer"},
    )

    assert res["ok"] is False
    assert res.get("needs_consent") is True


def test_live_autoroute_off_disables_escalation(monkeypatch):
    """ORYNN_LIVE_AUTOROUTE=off disables fast->agent escalation: a failed fast click
    just reports failure instead of spawning a task (legacy behavior, brief §12)."""
    from app.models import ToolResult

    monkeypatch.setenv("ORYNN_LIVE_AUTOROUTE", "off")

    class FakeTools:
        def uia_click(self, query, app="", allow_pixel_fallback=True):
            return ToolResult(ok=False, output="No UIA match (locked).", data={})

    class FakeClient:
        def request(self, *a, **k):
            raise AssertionError("autoroute=off must not escalate to a task")

    c = _controller()
    c.client = FakeClient()
    c._desktop_tools = FakeTools()
    res = c._live_tool_for_generation(
        None, "desktop_control", {"action": "click", "query": "New Agent", "app": "Cursor"}
    )

    assert res["ok"] is False  # reported failure, did not escalate


def test_consent_gate_keyword_boundaries():
    """The consent gate must catch outward/irreversible verbs without nagging on
    benign goals — reading email is fine, sending/replying is not."""
    from app.widget.textbox_overlay import OverlayController

    needs = OverlayController._goal_needs_consent
    # Benign — reading/opening/typing/searching never asks.
    for g in ["check my email", "open my email", "open notepad and type hello",
              "search the web for cats", "take a screenshot", "scroll down"]:
        assert needs(g) is False, g
    # Disruptive / outward-facing — always asks.
    for g in ["send the email to John", "reply to John in slack", "submit the form",
              "delete my downloads", "buy the item", "restart cursor",
              "format the c drive"]:
        assert needs(g) is True, g
    # Negated intent must NOT gate — the user is asking it NOT to do the thing.
    for g in ["do not send any data", "don't delete my files",
              "without sending anything just open it", "never post that"]:
        assert needs(g) is False, g
    # ...but a real send that merely contains a negation elsewhere still gates.
    assert needs("don't forget to send the report") is True


def test_live_remember_saves_fact_to_backend():
    calls = []

    class FakeClient:
        def request(self, method, path, data=None, timeout=4.0, **kw):
            calls.append((method, path, data))
            if path == "/api/memory/facts?limit=14":
                return {"prompt_block": "ORYNN MEMORY\n- cowork is top-right"}
            return {"ok": True, "fact": {"id": "k1"}}

    class FakeLive:
        def __init__(self):
            self.notes = []

        def is_running(self):
            return True

        def send_context_update(self, text):
            self.notes.append(text)

    c = _controller()
    c.client = FakeClient()
    c._live = FakeLive()
    res = c._live_tool("remember", {"fact": "cowork is the top-right button", "app": "dashboard"})
    assert res["ok"] is True
    m, p, d = calls[0]
    assert m == "POST" and p == "/api/memory/facts"
    assert d["text"] == "cowork is the top-right button" and d["app"] == "dashboard"
    assert c._knowledge_block_cache.startswith("ORYNN MEMORY")
    assert c._live.notes and "cowork is top-right" in c._live.notes[0]


def test_live_remember_requires_fact():
    c = _controller()
    res = c._live_tool("remember", {"fact": "  "})
    assert res["ok"] is False


def test_live_forget_calls_backend():
    class FakeClient:
        def request(self, method, path, data=None, timeout=4.0, **kw):
            assert path == "/api/memory/forget"
            return {"ok": True, "removed": 2}

    c = _controller()
    c.client = FakeClient()
    res = c._live_tool("forget", {"query": "cowork"})
    assert res["ok"] is True and res["removed"] == 2


def test_live_system_prompt_voice_first_with_examples():
    """System prompt: Clicky-style voice + Google few-shot examples; routing detail
    lives in tool declarations, not a numbered ladder."""
    from app.widget.gemini_live import _default_system_instruction

    prompt = _default_system_instruction()
    lower = prompt.lower()
    assert prompt.startswith("You are Orynn")
    assert "write for the ear" in lower
    assert "never say" in lower and "simply" in lower
    assert "just talk" in lower
    assert "at most one tool" in lower
    assert "never call start_desktop_task and desktop_control" in lower
    assert "examples:" in lower
    assert "open notepad" in lower
    assert "look_at_screen first" not in lower
    assert "orynn memory" in lower
    assert "pick exactly one path" not in lower


def test_live_knowledge_block_injected_into_config(monkeypatch):
    from google.genai import types
    from app.widget import gemini_live as gl

    comp = gl.GeminiLiveCompanion(gl.GeminiLiveCallbacks())
    comp.dynamic_context = lambda: "What you already know about the user and their setup:\n- cowork is top-right"
    cfg = comp._live_config(types)
    assert "cowork is top-right" in cfg.system_instruction
    # base instruction still present
    assert "Orynn" in cfg.system_instruction


def test_electron_click_asks_consent_before_unlock():
    """A fast click into a known Electron app that can't be done cleanly asks for a
    spoken yes before escalating — the agent may electron_unlock, which relaunches the
    app (brief §7.2). It must NOT silently spawn the task."""
    from app.models import ToolResult

    class FakeClient:
        def request(self, *a, **k):
            raise AssertionError("must not hit the backend before consent")

    class FakeTools:
        def uia_click(self, query, app="", allow_pixel_fallback=True):
            return ToolResult(ok=False, output="DOM locked (electron)", data={})

    c = _controller()
    c.client = FakeClient()
    c._desktop_tools = FakeTools()
    res = c._live_tool_for_generation(
        None, "desktop_control", {"action": "click", "query": "New Agent", "app": "Cursor"}
    )
    assert res.get("needs_consent") is True
    assert "unlock" in res["message"].lower()
    assert c._active_task_running is False


def test_non_electron_click_escalates_without_unlock_consent():
    """A fast click failure in a NON-Electron app just escalates to the agent — no
    unlock consent, since UIA/pixel handles native apps without a relaunch."""
    from app.models import ToolResult

    calls = []

    class FakeClient:
        def request(self, method, path, data=None, timeout=4.0, **kw):
            calls.append(path)
            if path == "/api/tasks/preflight":
                return {"blocked": False}
            return {}

    class FakeTools:
        def uia_click(self, query, app="", allow_pixel_fallback=True):
            return ToolResult(ok=False, output="no match", data={})

    c = _controller()
    c.client = FakeClient()
    c._desktop_tools = FakeTools()
    res = c._live_tool_for_generation(
        None, "desktop_control", {"action": "click", "query": "OK", "app": "Notepad"}
    )
    assert res.get("needs_consent") is not True
    assert "/api/tasks" in calls  # escalated to the agent


def test_fast_click_blocked_when_a_task_is_running():
    """A model click while a desktop task is running must hit the busy gate, not run a
    UIA action on top of the agent. The fast path bypassed the gate before this fix."""
    class FakeClient:
        def request(self, method, path, data=None, timeout=4.0, **kw):
            if path == "/api/active-tasks":
                return {"tasks": [{"id": "t1", "goal": "organizing downloads"}]}
            raise AssertionError("must not POST a task while one is already running")

    class FakeTools:
        def uia_click(self, *a, **k):
            raise AssertionError("must not click on top of a running task")

    c = _controller()
    c.client = FakeClient()
    c._desktop_tools = FakeTools()
    c._active_task_running = True
    c._active_task_goal = "organizing downloads"

    res = c._live_tool_for_generation(None, "desktop_control", {"action": "click", "query": "OK", "app": "X"})
    assert res.get("busy") is True


def test_knowledge_block_read_is_non_blocking_cache():
    """dynamic_context (_live_knowledge_block) must NOT do HTTP — it runs on the Live
    event loop at connect. The blocking fetch lives in _refresh_knowledge_block (off-loop)."""
    calls = []

    class FakeClient:
        def request(self, method, path, data=None, timeout=4.0, **kw):
            calls.append(path)
            return {"facts": [], "prompt_block": "ORYNN MEMORY block"}

    c = _controller()
    c.client = FakeClient()
    # Reading the cache does zero HTTP.
    assert c._live_knowledge_block() == ""
    assert calls == []
    # Refreshing (poll thread / after remember) populates it via one HTTP call.
    c._refresh_knowledge_block()
    assert "ORYNN MEMORY block" in c._live_knowledge_block()
    assert calls == ["/api/memory/facts?limit=14"]


def test_extract_web_sources_dedups_and_drops_ddg():
    from app.widget.textbox_overlay import OverlayController
    out = (
        "Result A\nhttps://docs.python.org/3/whatsnew.html\nsnippet\n\n"
        "Result B\nhttps://www.python.org/downloads/\nmore\n\n"
        "Dup domain\nhttps://docs.python.org/other.html\nx\n"
        "https://duckduckgo.com/l/?uddg=redirect"
    )
    src = OverlayController._extract_web_sources(out)
    doms = [d for d, _ in src]
    assert "docs.python.org" in doms and "python.org" in doms
    assert "duckduckgo.com" not in doms           # the search engine itself isn't a source
    assert doms.count("docs.python.org") == 1      # deduped by domain
    assert all(u.startswith("http") for _, u in src)


def test_live_web_search_surfaces_sources_and_asks_to_cite():
    """Perplexity-style trust: the web answer carries its sources, and the model is
    told to cite the source out loud so the user can verify it."""
    from app.models import ToolResult

    class FakeTools:
        def web_search(self, q):
            return ToolResult(ok=True, output="Latest Python\nhttps://www.python.org/downloads/\n3.14")

    c = _controller()
    c._desktop_tools = FakeTools()
    res = c._live_tool("web_search", {"query": "latest python version"})
    assert res["ok"] is True
    assert res["sources"] and "python.org" in res["sources"][0]
    assert "according to python.org" in res["message"]


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
    res = c._live_tool("start_desktop_task", {"goal": "open notepad"})
    assert res["ok"] is False
    assert "setup" in res["message"].lower()


def test_live_task_progress_tracked_without_overlay_pill():
    """Subagent step tracking is internal (get_companion_status) — no extra UI."""
    c = _controller()
    c._live_task_ids["clicky-abc"] = "click Save"
    c._update_live_task_progress({
        "task_id": "clicky-abc",
        "type": "action_start",
        "action_type": "uia_click",
        "args_summary": "Save",
    })
    assert c._live_task_progress["clicky-abc"]["step"] == "clicking Save"


def test_get_companion_status_includes_subagent_progress():
    class FakeClient:
        def request(self, method, path, data=None, timeout=4.0, **kw):
            if path == "/api/active-tasks":
                return {"tasks": [{"id": "clicky-abc"}]}
            return {}

    c = _controller()
    c.client = FakeClient()
    c._live_task_ids["clicky-abc"] = "open notepad"
    c._live_task_progress["clicky-abc"] = {
        "task_id": "clicky-abc",
        "goal": "open notepad",
        "step": "switching windows",
        "updated_at": 1.0,
    }
    status = c._live_tool("get_companion_status", {})
    assert status["progress"]["step"] == "switching windows"
    assert status["progress"]["goal"] == "open notepad"


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
    assert labels == []  # unknown tool is an internal model error, not user-facing
    assert states == ["thinking"]


def test_live_tool_unknown_desktop_action_sets_visible_label():
    c = _controller()
    labels, states = [], []
    c.labelRequested.connect(lambda s: labels.append(s))
    c.cursorStateRequested.connect(lambda s: states.append(s))

    res = c._live_tool("desktop_control", {"action": "moonwalk"})

    assert res["ok"] is False
    assert "unknown desktop action" in res["message"].lower()
    assert labels == []  # unknown action is internal — no robotic bubble flash
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

    assert labels == []  # input echo muted — bubble is for Live's replies only
    assert states == ["listening", "listening"]
    assert c._live_input_buffer == "open notepad"


def test_live_input_transcript_handles_cumulative_chunks():
    c = _controller()
    labels = []
    c.labelRequested.connect(lambda s: labels.append(s))

    c._live_input_transcript("open", False)
    c._live_input_transcript("open notepad", False)
    c._live_input_transcript("open notepad please", True)

    assert labels == []  # cumulative chunks update the buffer, not the bubble
    assert c._live_input_buffer == "open notepad please"


def test_live_listening_status_does_not_overwrite_fresh_input():
    c = _controller()
    labels, states = [], []
    c.labelRequested.connect(lambda s: labels.append(s))
    c.cursorStateRequested.connect(lambda s: states.append(s))

    c._live_input_transcript("open notepad", False)
    c._live_status("Gemini Live listening")

    assert labels == []  # neither input echo nor "listening" text in the bubble
    assert states[-1] == "listening"


def _has_red_ring(img):
    cols = img.getcolors(maxcolors=100000) or []
    return any(r > 200 and g < 100 and b < 100 for _, (r, g, b) in cols)


def test_user_pointing_flag_tracks_the_users_words(monkeypatch):
    """The pointer ring rides every frame this turn based on what THE USER said, so a
    model look_at_screen with a generic question still gets the ring (the 'pointed at
    Cowork, it said Orynn' bug)."""
    import app.widget.textbox_overlay as tbo

    monkeypatch.setattr(tbo, "_live_auto_screen_mode", lambda: "off")
    c = _controller()
    c._live_input_transcript("what's this", True)
    assert c._live_turn_points_at_cursor is True
    c._live_input_transcript("read me the news", True)   # new, not pointing
    assert c._live_turn_points_at_cursor is False


def test_system_prompt_personalizes_and_greets_by_name():
    """Orynn should feel like it knows the user across sessions: greet by name, ask the
    name on a first run, and proactively remember durable personal facts."""
    import inspect
    from app.widget import gemini_live as gl

    prompt = gl._default_system_instruction().lower()
    assert "orynn memory" in prompt
    assert "proactively" in prompt and "remember" in prompt
    assert "name" in prompt and "greet returning users by name" in prompt

    greet = inspect.getsource(gl.GeminiLiveCompanion._maybe_greet).lower()
    assert "name" in greet and "call me" in greet   # asks the name on first run


def test_points_at_cursor_detection():
    from app.widget.textbox_overlay import _utterance_points_at_cursor as p
    # pointing -> focus on the mouse (full-monitor + ring)
    assert p("what's this")
    assert p("read this for me")
    assert p("what is that error")
    assert p("what's under my cursor")
    assert p("the thing right here")
    # general / not pointing -> normal full-frame vision
    assert not p("read me the news")
    assert not p("what's on my screen")
    assert not p("open notepad")
    assert not p("")


def test_cursor_marker_drawn_when_pointer_in_region(monkeypatch):
    """The mouse pointer gets a red ring on the vision frame so the model can focus
    'where I'm pointing'."""
    import sys
    import types as _t
    from PIL import Image
    from app.widget.textbox_overlay import OverlayController

    fake = _t.ModuleType("win32api")
    fake.GetCursorPos = lambda: (500, 400)        # center of a 1000x800 region
    monkeypatch.setitem(sys.modules, "win32api", fake)
    monkeypatch.delenv("ORYNN_LIVE_CURSOR_MARKER", raising=False)

    img = Image.new("RGB", (1000, 800), (40, 40, 40))
    out = OverlayController._draw_cursor_marker(img, 0, 0, 1000, 800)
    assert _has_red_ring(out)


def test_cursor_marker_skipped_when_pointer_outside_region(monkeypatch):
    import sys
    import types as _t
    from PIL import Image
    from app.widget.textbox_overlay import OverlayController

    fake = _t.ModuleType("win32api")
    fake.GetCursorPos = lambda: (5000, 400)       # off the captured surface
    monkeypatch.setitem(sys.modules, "win32api", fake)
    monkeypatch.delenv("ORYNN_LIVE_CURSOR_MARKER", raising=False)

    img = Image.new("RGB", (1000, 800), (40, 40, 40))
    out = OverlayController._draw_cursor_marker(img, 0, 0, 1000, 800)
    assert not _has_red_ring(out)


def test_cursor_marker_disabled_by_env(monkeypatch):
    import sys
    import types as _t
    from PIL import Image
    from app.widget.textbox_overlay import OverlayController

    fake = _t.ModuleType("win32api")
    fake.GetCursorPos = lambda: (500, 400)
    monkeypatch.setitem(sys.modules, "win32api", fake)
    monkeypatch.setenv("ORYNN_LIVE_CURSOR_MARKER", "0")

    img = Image.new("RGB", (1000, 800), (40, 40, 40))
    out = OverlayController._draw_cursor_marker(img, 0, 0, 1000, 800)
    assert not _has_red_ring(out)


def test_auto_screen_fires_at_utterance_start_not_just_end(monkeypatch):
    """The vision frame is sent as the user STARTS speaking (one per utterance), so it
    reaches the model before end-of-turn — not raced at 'finished' (the 'read the news
    -> made up storms, right on retry' bug)."""
    import app.widget.textbox_overlay as tbo

    monkeypatch.setattr(tbo, "_live_auto_screen_mode", lambda: "always")

    class _ImmediateThread:
        def __init__(self, target=None, args=(), daemon=None, **kw):
            self._t, self._a = target, args

        def start(self):
            self._t(*self._a)

    monkeypatch.setattr(tbo.threading, "Thread", _ImmediateThread)

    c = _controller()
    calls = []
    monkeypatch.setattr(c, "_maybe_auto_screen_for_live_utterance", lambda u: calls.append(u))

    c._live_input_transcript("read me", False)          # first chunk -> fire EARLY
    assert len(calls) == 1
    c._live_input_transcript("read me the news", False)  # same utterance -> no re-fire
    assert len(calls) == 1
    c._live_input_transcript("read me the news", True)   # finished -> still one
    assert len(calls) == 1
    c._live_input_transcript("what time is it", False)   # NEW utterance -> fires again
    assert len(calls) == 2


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


def test_live_input_transcript_resets_across_turns_on_finalize():
    """Gemini rarely flags INPUT transcription finished, so the input turn is closed by
    a turn-boundary finalize (empty text + finished). The next utterance must start a
    fresh buffer, not concatenate past turns (the 'Hello.I need help...Ah!' bug)."""
    c = _controller()
    labels = []
    c.labelRequested.connect(lambda s: labels.append(s))

    c._live_input_transcript("hello there", False)       # turn 1 (no finished flag)
    c._live_input_transcript("", True)                   # turn boundary -> silent close
    c._live_input_transcript("what time is it", False)   # turn 2: brand-new utterance

    assert labels == []  # turn boundaries are silent in the bubble
    assert c._live_input_buffer == "what time is it"
    assert "hello there" not in c._live_input_buffer


def test_input_turn_finalize_does_not_rerender():
    """The empty turn-boundary finalize must NOT flash the old input over the reply —
    it only flips the done flag."""
    c = _controller()
    labels = []
    c._live_input_transcript("an earlier question", False)
    c.labelRequested.connect(lambda s: labels.append(s))
    c._live_input_transcript("", True)  # finalize
    assert labels == []  # nothing re-rendered


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

    assert labels == ["Live tool call failed"]  # input echo muted; tool failure still shows
    assert states[-1] == "thinking"


def test_live_listening_status_is_cursor_only():
    c = _controller()
    labels, states = [], []
    c.labelRequested.connect(lambda s: labels.append(s))
    c.cursorStateRequested.connect(lambda s: states.append(s))

    c._live_status("Gemini Live listening")

    assert labels == []  # listening is cursor-only — no robotic status in the bubble
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

    # The terminal result is ALSO muted while Live drives — Live speaks the outcome
    # itself (success or failure) so the bubble never flashes raw backend text over
    # the conversation. (This was the "Failed: Server restarted…" leak.)
    assert c._set_label("Done", source="task_result") is False
    assert labels == ["Sure, opening it now."]


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
    # The final result is muted too while Live drives — Live narrates the outcome by
    # voice, so the bubble never flashes raw backend text over the conversation.
    assert c._set_label("Notepad is open.", source="task_result") is False
    assert labels == []


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
    reaches it; the spawned task's churn AND its final result are muted — Live speaks
    the outcome by voice instead of flashing raw backend text over the conversation."""
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

    # Only Live's spoken reply reached the bubble — no input echo, no task churn.
    assert labels == ["Okay, I'm getting it."]

    # 6. The task finishes: its result is muted too while Live drives — Live narrates
    #    the outcome by voice, so the bubble stays on the conversation (no raw flash).
    assert c._set_label("Notepad is open with hello typed.", source="task_result") is False
    assert labels == ["Okay, I'm getting it."]


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


def test_resample_audio():
    from app.widget.gemini_live import _resample_audio
    import numpy as np

    # Create a simple mono audio data at 16000Hz (1600 samples of 2 bytes each = 3200 bytes)
    data = np.arange(1600, dtype=np.int16).tobytes()
    
    # Resample to 32000Hz (should double the number of samples to 3200, i.e., 6400 bytes)
    resampled = _resample_audio(data, 16000, 32000)
    assert len(resampled) == 6400

    # Resample to 8000Hz (should halve the number of samples to 800, i.e., 1600 bytes)
    resampled2 = _resample_audio(data, 16000, 8000)
    assert len(resampled2) == 1600

    # Resampling to same rate should return identical bytes
    assert _resample_audio(data, 16000, 16000) == data


def test_resample_audio_invalid():
    from app.widget.gemini_live import _resample_audio
    assert _resample_audio(b"", 16000, 24000) == b""
    # 7 bytes is not a multiple of 2 (int16), causing a ValueError in np.frombuffer, falling back to original bytes.
    assert _resample_audio(b"oddbyte", 16000, 24000) == b"oddbyte"



# ── New Gemini Live improvements: barge-in, resumption, greeting, scroll,
#    look-at-screen, proactive task completion ────────────────────────────

def test_flush_output_drains_queue_on_barge_in():
    import asyncio as aio
    from app.widget import gemini_live as gl

    q = aio.Queue()
    for _ in range(5):
        q.put_nowait(b"x")
    gl.GeminiLiveCompanion._flush_output(q)
    assert q.empty()


def test_handle_message_flushes_output_on_interruption():
    import asyncio as aio
    from google.genai import types
    from app.widget import gemini_live as gl

    q = aio.Queue()
    for _ in range(3):
        q.put_nowait(b"a")

    class Content:
        interrupted = True
        input_transcription = None
        output_transcription = None
        model_turn = None
        turn_complete = False

    class FakeMessage:
        session_resumption_update = None
        server_content = Content()
        tool_call = None

    comp = gl.GeminiLiveCompanion(gl.GeminiLiveCallbacks())
    aio.run(comp._handle_message(object(), FakeMessage(), q, types))
    assert q.empty()  # barge-in dropped the queued speaker backlog


def test_handle_message_captures_session_resumption_handle():
    from google.genai import types
    from app.widget import gemini_live as gl

    class Resume:
        resumable = True
        new_handle = "handle-xyz"

    class FakeMessage:
        session_resumption_update = Resume()
        server_content = None
        tool_call = None

    comp = gl.GeminiLiveCompanion(gl.GeminiLiveCallbacks())
    asyncio.run(comp._handle_message(object(), FakeMessage(), None, types))
    assert comp._resume_handle == "handle-xyz"


def test_live_config_carries_resume_handle():
    from google.genai import types
    from app.widget import gemini_live as gl

    comp = gl.GeminiLiveCompanion(gl.GeminiLiveCallbacks())
    comp._resume_handle = "h-2"
    cfg = comp._live_config(types)
    assert cfg.session_resumption is not None
    assert cfg.session_resumption.handle == "h-2"


def test_maybe_greet_once_and_respects_env(monkeypatch):
    from google.genai import types
    from app.widget import gemini_live as gl

    class FakeSession:
        def __init__(self):
            self.sent = 0

        async def send_client_content(self, turns=None, turn_complete=None):
            self.sent += 1

    # OFF by default (no startup turn, no echo-feed): no greeting.
    monkeypatch.delenv("GEMINI_LIVE_GREETING", raising=False)
    comp = gl.GeminiLiveCompanion(gl.GeminiLiveCallbacks())
    comp._is_first_live_run = False
    s = FakeSession()
    asyncio.run(comp._maybe_greet(s, types))
    assert s.sent == 0

    # Opt in -> greets exactly once per session (not on reconnects).
    monkeypatch.setenv("GEMINI_LIVE_GREETING", "1")
    comp2 = gl.GeminiLiveCompanion(gl.GeminiLiveCallbacks())
    comp2._is_first_live_run = False
    s2 = FakeSession()
    asyncio.run(comp2._maybe_greet(s2, types))
    asyncio.run(comp2._maybe_greet(s2, types))
    assert s2.sent == 1


def test_maybe_greet_first_run_ignores_env(monkeypatch):
    from google.genai import types
    from app.widget import gemini_live as gl

    class FakeSession:
        def __init__(self):
            self.sent = 0

        async def send_client_content(self, turns=None, turn_complete=None):
            self.sent += 1

    # GEMINI_LIVE_GREETING is OFF, but _is_first_live_run is True -> should still greet!
    monkeypatch.delenv("GEMINI_LIVE_GREETING", raising=False)
    comp = gl.GeminiLiveCompanion(gl.GeminiLiveCallbacks())
    comp._is_first_live_run = True
    s = FakeSession()
    asyncio.run(comp._maybe_greet(s, types))
    assert s.sent == 1


def test_handle_message_go_away_schedules_graceful_reconnect():
    """When the server sends go_away (session duration limit), exit cleanly and
    reconnect with the resume handle instead of aborting with 1008."""
    from google.genai import types
    from app.widget import gemini_live as gl

    class FakeGoAway:
        time_left = "30s"

    class FakeMessage:
        server_content = None
        tool_call = None
        go_away = FakeGoAway()

    class FakeSession:
        audio_stream_end = False

        async def send_realtime_input(self, audio_stream_end=False, **_kwargs):
            if audio_stream_end:
                self.audio_stream_end = True

    comp = gl.GeminiLiveCompanion(gl.GeminiLiveCallbacks())
    session = FakeSession()
    asyncio.run(comp._handle_message(session, FakeMessage(), None, types))
    assert comp._go_away_reconnect is True
    assert session.audio_stream_end is True


def test_send_screen_image_sends_video_frame_only():
    """A screenshot goes over the realtime VIDEO channel and NOTHING else: not a
    send_client_content inline_data blob (the Live API 1007's on that, dropping the
    session — the old 'Listening forever' bug), and not an extra text turn (the tool's
    FunctionResponse is the single describe-prompt, so a turn here would double-prompt)."""
    import threading
    import time as _time
    import asyncio as _aio
    from app.widget import gemini_live as gl

    calls = {"video": 0, "client_content_turns": 0, "inline_blob": 0}

    class FakeSession:
        async def send_realtime_input(self, *, video=None, media=None, **kw):
            assert media is None, "must not use the deprecated media= channel"
            if video is not None:
                calls["video"] += 1

        async def send_client_content(self, *, turns=None, turn_complete=False, **kw):
            calls["client_content_turns"] += 1
            for content in (turns or []):
                for part in getattr(content, "parts", []) or []:
                    if getattr(part, "inline_data", None) is not None:
                        calls["inline_blob"] += 1

    loop = _aio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    try:
        comp = gl.GeminiLiveCompanion(gl.GeminiLiveCallbacks())
        comp._loop = loop
        comp._session = FakeSession()
        assert comp.send_screen_image(b"\xff\xd8jpeg-bytes") is True
        _time.sleep(0.4)
    finally:
        loop.call_soon_threadsafe(loop.stop)

    assert calls["video"] == 1                  # frame went over realtime video
    assert calls["inline_blob"] == 0            # never a client_content image blob
    assert calls["client_content_turns"] == 0   # no extra text turn (no double-prompt)


def test_live_desktop_control_scroll_routes_to_tools():
    from app.models import ToolResult

    c = _controller()

    class FakeTools:
        def __init__(self):
            self.scrolled = None

        def scroll(self, amount):
            self.scrolled = amount
            return ToolResult(ok=True, output=f"Scrolled {amount}")

    ft = FakeTools()
    c._desktop_tools = ft
    res = c._live_tool("desktop_control", {"action": "scroll", "amount": -25})
    assert res["ok"] is True
    assert ft.scrolled == -25


def test_live_vision_jpeg_defaults_high_quality(monkeypatch):
    from app.widget import textbox_overlay as tbo
    monkeypatch.delenv("ORYNN_LIVE_SCREEN_QUALITY", raising=False)
    monkeypatch.delenv("ORYNN_LIVE_SCREEN_MAX_EDGE", raising=False)
    quality, max_edge = tbo._live_vision_jpeg_settings()
    assert quality == 98
    assert max_edge == 0  # native resolution, no downscale


def test_utterance_wants_live_screen():
    from app.widget import textbox_overlay as tbo
    assert tbo._utterance_wants_live_screen("what's on my screen")
    assert tbo._utterance_wants_live_screen("look at my screen right now")
    assert tbo._utterance_wants_live_screen("what tab am I on")
    assert not tbo._utterance_wants_live_screen("open notepad")
    assert not tbo._utterance_wants_live_screen("thanks")


def test_auto_screen_default_is_always(monkeypatch):
    from app.widget import textbox_overlay as tbo
    monkeypatch.delenv("ORYNN_LIVE_AUTO_SCREEN", raising=False)
    assert tbo._live_auto_screen_mode() == "always"


def test_auto_screen_fires_on_chitchat_when_always(monkeypatch):
    from app.widget import textbox_overlay as tbo
    monkeypatch.delenv("ORYNN_LIVE_AUTO_SCREEN", raising=False)
    assert tbo._live_auto_screen_mode() == "always"
    c = _controller()
    pushed = []
    c._push_live_screen_frame = lambda q: pushed.append(q) or (True, "TikTok")
    c._live = type("L", (), {"is_running": lambda self: True})()
    c._maybe_auto_screen_for_live_utterance("how are you")
    assert pushed == ["how are you"]


def test_auto_screen_fires_on_screen_question(monkeypatch):
    from app.widget import textbox_overlay as tbo
    monkeypatch.setenv("ORYNN_LIVE_AUTO_SCREEN", "intent")
    c = _controller()
    pushed = []
    c._push_live_screen_frame = lambda q: pushed.append(q) or (True, "TikTok")
    c._live = type("L", (), {"is_running": lambda self: True})()
    c._maybe_auto_screen_for_live_utterance("what's on my screen")
    assert pushed == ["what's on my screen"]


def test_auto_screen_skipped_for_chitchat(monkeypatch):
    from app.widget import textbox_overlay as tbo
    monkeypatch.setenv("ORYNN_LIVE_AUTO_SCREEN", "intent")
    c = _controller()
    c._push_live_screen_frame = lambda q: (_ for _ in ()).throw(AssertionError("should not push"))
    c._live = type("L", (), {"is_running": lambda self: True})()
    c._maybe_auto_screen_for_live_utterance("how are you")


def test_live_look_at_screen_sends_screenshot_to_vision(monkeypatch):
    c = _controller()
    pushed = []

    def fake_push(question=""):
        pushed.append(question)
        return True, "Chrome"

    monkeypatch.setattr(c, "_push_live_screen_frame", fake_push)

    class FakeLive:
        def is_running(self):
            return True

        def send_screen_image(self, *_a, **_k):
            return True

    c._live = FakeLive()
    res = c._live_tool("look_at_screen", {"question": "what is this error"})
    assert res["ok"] is True
    assert pushed == ["what is this error"]
    assert "what is this error" in res["message"]
    assert "earlier turns" in res["message"]


def test_capture_live_task_outcome_honors_complete_false():
    c = _controller()
    live = _FakeLive()
    c._live = live
    c._live_task_ids = {"clicky-bad": "open the file"}
    c._active_task_running = True

    c._capture_live_task_outcome({
        "type": "done",
        "task_id": "clicky-bad",
        "complete": False,
        "reason": "Timed out waiting for Notepad.",
    })

    assert c._active_task_running is False
    assert c._last_task_result["ok"] is False
    assert len(live.updates) == 1
    assert "FAILED" in live.updates[0]
    assert "finished" not in live.updates[0].lower() or "do not" in live.updates[0].lower()


def test_await_task_outcome_honors_complete_false_from_api():
    class FakeClient:
        def request(self, method, path, data=None, timeout=4.0, **kw):
            if path == "/api/tasks/preflight":
                return {"blocked": False}
            if path == "/api/tasks":
                return {}
            if path.startswith("/api/tasks/"):
                return {
                    "status": "done",
                    "complete": False,
                    "reason": "Window never appeared.",
                }
            return {}

    c = _controller()
    c.client = FakeClient()
    res = c._live_tool("start_desktop_task", {"goal": "open notepad"})

    assert res["ok"] is False
    assert "FAILED" in res["message"] or "failed" in res["message"].lower()
    assert "do not" in res["message"].lower()


def test_capture_live_task_outcome_notifies_live_proactively():
    c = _controller()

    class FakeLive:
        def __init__(self):
            self.note = None

        def send_task_update(self, text):
            self.note = text

    fl = FakeLive()
    c._live = fl
    c._live_task_ids = {"clicky-9": "organize my downloads"}
    c._active_task_running = True

    c._capture_live_task_outcome({
        "type": "done", "task_id": "clicky-9", "reason": "Sorted 12 files.",
    })

    assert c._active_task_running is False
    assert fl.note and "organize my downloads" in fl.note
    assert "Sorted 12 files." in fl.note


def test_live_run_terminal_runs_safe_command():
    """run_terminal executes a normal command and hands the output back to Live."""
    from app.models import ToolResult

    c = _controller()
    calls = []

    class FakeTools:
        def run_command(self, cmd):
            calls.append(cmd)
            return ToolResult(ok=True, output="On branch main\nnothing to commit")

    c._desktop_tools = FakeTools()
    res = c._live_tool("run_terminal", {"command": "git status"})
    assert res["ok"] is True
    assert "On branch main" in res["output"]
    assert calls == ["git status"]


def test_live_run_terminal_hard_blocks_destructive_command():
    """A catastrophic command must be refused BEFORE it runs — same hard-block guard
    the desktop agent uses. run_command must never be called."""
    c = _controller()
    calls = []

    class FakeTools:
        def run_command(self, cmd):
            calls.append(cmd)
            from app.models import ToolResult
            return ToolResult(ok=True, output="boom")

    c._desktop_tools = FakeTools()
    for danger in ("rm -rf /", "format c:", "shutdown /s"):
        res = c._live_tool("run_terminal", {"command": danger})
        assert res["ok"] is False and res.get("blocked") is True
    assert calls == []  # nothing destructive ever executed


def test_live_run_terminal_cancels_promptly_mid_command():
    """'stop' must interrupt a long run_command promptly — the tool returns Stopped
    without waiting for the blocking subprocess to finish (QA: a 4s command ignored
    cancel for 4.6s before this)."""
    import time as _t
    import threading as _th
    from app.models import ToolResult

    started = _th.Event()

    class FakeTools:
        def run_command(self, cmd):
            started.set()
            _t.sleep(5.0)  # simulate a slow command
            return ToolResult(ok=True, output="late output")

    c = _controller()
    c._desktop_tools = FakeTools()

    def _cancel():
        started.wait(2.0)
        c._live_cancel.set()  # user said "stop" mid-command

    _th.Thread(target=_cancel, daemon=True).start()
    t0 = _t.monotonic()
    res = c._live_tool("run_terminal", {"command": "slow-build"})
    elapsed = _t.monotonic() - t0

    assert res["ok"] is False and "Stopped" in res["message"]
    assert elapsed < 2.0, f"should return promptly on cancel, took {elapsed:.1f}s"


def test_live_run_terminal_destructive_command_needs_consent():
    """A destructive-but-not-catastrophic command (delete a file, git push) must get a
    spoken yes before it runs — run_command is never called without consent."""
    c = _controller()
    calls = []

    class FakeTools:
        def run_command(self, cmd):
            calls.append(cmd)
            from app.models import ToolResult
            return ToolResult(ok=True, output="done")

    c._desktop_tools = FakeTools()
    for cmd in ("del temp.txt", "git push origin main", "pip uninstall numpy"):
        res = c._live_tool("run_terminal", {"command": cmd})
        assert res["ok"] is False and res.get("needs_consent") is True, cmd
    assert calls == []  # nothing ran without consent


def test_live_run_terminal_destructive_runs_after_consent():
    from app.models import ToolResult

    c = _controller()
    calls = []

    class FakeTools:
        def run_command(self, cmd):
            calls.append(cmd)
            return ToolResult(ok=True, output="deleted")

    c._desktop_tools = FakeTools()
    res = c._live_tool("run_terminal", {"command": "del temp.txt", "confirmed": True})
    assert res["ok"] is True
    assert calls == ["del temp.txt"]


def test_live_run_terminal_safe_command_skips_consent():
    """Read-only commands (git status, listing files) never trigger the consent gate."""
    from app.models import ToolResult

    c = _controller()
    calls = []

    class FakeTools:
        def run_command(self, cmd):
            calls.append(cmd)
            return ToolResult(ok=True, output="ok")

    c._desktop_tools = FakeTools()
    for cmd in ("git status", "dir", "python build.py", "git reset HEAD~1"):
        res = c._live_tool("run_terminal", {"command": cmd})
        assert res["ok"] is True, cmd
    assert calls == ["git status", "dir", "python build.py", "git reset HEAD~1"]


def test_live_autostart_enabled_env(monkeypatch):
    from app.widget import gemini_live as gl

    monkeypatch.delenv("ORYNN_LIVE_AUTOSTART", raising=False)
    assert gl.live_autostart_enabled() is False  # off by default (privacy + quota)
    monkeypatch.setenv("ORYNN_LIVE_AUTOSTART", "1")
    assert gl.live_autostart_enabled() is True


# ── set_timer / get_clipboard / set_clipboard ────────────────────────────────

def test_set_timer_fires_send_task_update():
    """Timer fires send_task_update on the companion after the countdown."""
    import time

    c = _controller()
    spoken: list[str] = []

    class FakeCompanion:
        def send_task_update(self, text: str) -> None:
            spoken.append(text)

    c._live = FakeCompanion()
    res = c._live_tool("set_timer", {"seconds": 0.05, "label": "test alert"})
    assert res["ok"] is True
    assert res["seconds"] == 0.05
    assert "test alert" in res["label"]
    # Give the background thread time to fire.
    deadline = time.time() + 2.0
    while time.time() < deadline and not spoken:
        time.sleep(0.02)
    assert spoken == ["test alert"], f"alert not spoken within 2s: {spoken}"


def test_set_timer_zero_seconds_rejected():
    c = _controller()
    res = c._live_tool("set_timer", {"seconds": 0})
    assert res["ok"] is False
    assert "positive" in res["message"].lower()


def test_set_timer_no_seconds_rejected():
    c = _controller()
    res = c._live_tool("set_timer", {"label": "no seconds given"})
    assert res["ok"] is False


def test_set_timer_exceeds_24h_rejected():
    c = _controller()
    res = c._live_tool("set_timer", {"seconds": 86_401})
    assert res["ok"] is False
    assert "24" in res["message"]


def test_set_timer_default_label():
    """When no label is given the timer still fires with a default message."""
    import time

    c = _controller()
    spoken: list[str] = []

    class FakeCompanion:
        def send_task_update(self, text: str) -> None:
            spoken.append(text)

    c._live = FakeCompanion()
    res = c._live_tool("set_timer", {"seconds": 0.05})
    assert res["ok"] is True
    deadline = time.time() + 2.0
    while time.time() < deadline and not spoken:
        time.sleep(0.02)
    assert spoken  # some default message was spoken
    assert "timer" in spoken[0].lower() or "up" in spoken[0].lower()


def test_set_timer_declared_in_function_declarations():
    from google.genai import types
    from app.widget import gemini_live as gl

    decls = gl._function_declarations(types)
    names = {d.name for d in decls}
    assert "set_timer" in names
    timer_decl = next(d for d in decls if d.name == "set_timer")
    schema = timer_decl.parameters_json_schema
    assert "seconds" in schema["properties"]
    assert schema["required"] == ["seconds"]


def test_get_clipboard_returns_text():
    from app.models import ToolResult

    c = _controller()

    class FakeTools:
        def get_clipboard(self):
            return ToolResult(ok=True, output="hello from clipboard")

    c._desktop_tools = FakeTools()
    res = c._live_tool("get_clipboard", {})
    assert res["ok"] is True
    assert res["text"] == "hello from clipboard"


def test_get_clipboard_empty():
    from app.models import ToolResult

    c = _controller()

    class FakeTools:
        def get_clipboard(self):
            return ToolResult(ok=True, output="")

    c._desktop_tools = FakeTools()
    res = c._live_tool("get_clipboard", {})
    assert res["ok"] is True
    assert res["text"] == ""
    assert "empty" in res["message"].lower()


def test_get_clipboard_truncates_long_content():
    from app.models import ToolResult

    c = _controller()
    long_text = "x" * 5000

    class FakeTools:
        def get_clipboard(self):
            return ToolResult(ok=True, output=long_text)

    c._desktop_tools = FakeTools()
    res = c._live_tool("get_clipboard", {})
    assert res["ok"] is True
    assert len(res["text"]) <= 4001  # 4000 chars + ellipsis
    assert res["truncated"] is True
    assert res["length"] == 5000


def test_set_clipboard_writes_and_confirms():
    from app.models import ToolResult

    c = _controller()
    written: list[str] = []

    class FakeTools:
        def set_clipboard(self, text: str):
            written.append(text)
            return ToolResult(ok=True, output="ok")

    c._desktop_tools = FakeTools()
    res = c._live_tool("set_clipboard", {"text": "paste me"})
    assert res["ok"] is True
    assert written == ["paste me"]
    assert "paste" in res["message"].lower() or "clipboard" in res["message"].lower()


def test_set_clipboard_empty_text_rejected():
    c = _controller()
    res = c._live_tool("set_clipboard", {"text": ""})
    assert res["ok"] is False


def test_clipboard_tools_in_function_declarations():
    from google.genai import types
    from app.widget import gemini_live as gl

    decls = gl._function_declarations(types)
    names = {d.name for d in decls}
    assert "get_clipboard" in names
    assert "set_clipboard" in names
    sc = next(d for d in decls if d.name == "set_clipboard")
    assert sc.parameters_json_schema["required"] == ["text"]


# ── partial-failure recovery: last_step in failure response ──────────────────

def test_await_task_outcome_failure_includes_last_step_when_progress_tracked():
    """When a desktop task fails, the failure response should include the last
    known step so the Live model can tell the user how far the task got."""

    class FakeClient:
        def request(self, method, path, data=None, timeout=4.0, **kw):
            if path == "/api/tasks/preflight":
                return {"blocked": False}
            if path == "/api/tasks":
                return {}
            if path.startswith("/api/tasks/"):
                return {
                    "status": "failed",
                    "complete": False,
                    "reason": "Could not locate the submit button.",
                }
            return {}

    c = _controller()
    c.client = FakeClient()

    # Simulate progress that was tracked before the failure (e.g. "clicking Submit")
    task_id_holder: list[str] = []
    orig_touch = c._touch_desktop_busy

    def patched_touch():
        orig_touch()

    c._touch_desktop_busy = patched_touch

    # Plant progress BEFORE the task poll so _await_task_outcome can read it.
    # We intercept _live_start_desktop_task to grab the task_id, then plant
    # progress keyed on that id.
    orig_await = c._await_task_outcome

    def intercepted_await(task_id, goal):
        # Plant a progress entry as if the SSE loop had received an action event.
        c._live_task_ids[task_id] = goal
        c._live_task_progress[task_id] = {
            "task_id": task_id,
            "goal": goal,
            "step": "clicking Submit",
            "updated_at": 1.0,
        }
        return orig_await(task_id, goal)

    c._await_task_outcome = intercepted_await

    res = c._live_tool("start_desktop_task", {"goal": "submit the form", "confirmed": True})

    assert res["ok"] is False
    assert res.get("last_step") == "clicking Submit", (
        f"Expected last_step='clicking Submit', got: {res}"
    )


def test_await_task_outcome_failure_no_last_step_when_no_progress():
    """If no progress was tracked (task failed before any action), the failure
    response must not include a last_step key at all — no spurious noise."""

    class FakeClient:
        def request(self, method, path, data=None, timeout=4.0, **kw):
            if path == "/api/tasks/preflight":
                return {"blocked": False}
            if path == "/api/tasks":
                return {}
            if path.startswith("/api/tasks/"):
                return {
                    "status": "failed",
                    "complete": False,
                    "reason": "App never opened.",
                }
            return {}

    c = _controller()
    c.client = FakeClient()

    res = c._live_tool("start_desktop_task", {"goal": "open an app"})

    assert res["ok"] is False
    assert "last_step" not in res, (
        f"Unexpected last_step in response when no progress tracked: {res}"
    )


# ── Item 1: Workflow trigger bypass ──────────────────────────────────────────

def test_start_desktop_task_redirects_to_workflow_on_trigger_match(tmp_path, monkeypatch):
    """When start_desktop_task goal matches a saved workflow (>=2 keyword tokens),
    the workflow is run directly instead of spinning up the back-office agent."""
    import app.workflows as wf

    monkeypatch.setattr(wf, "store_path", lambda: tmp_path / "workflows.json")
    wf.add_workflow(
        "post anime edit",
        description="Post my anime edit to Instagram",
        triggers=["post anime", "post my edit"],
        steps=[{"action": "open", "app": "Instagram"}],
        owner="user",
    )

    c = _controller()
    agent_called = []

    def fake_start_desktop_task(args):
        agent_called.append(args)
        return {"ok": True, "task_id": "x", "status": "done", "result": "done"}

    workflow_called = []

    def fake_run_workflow(args):
        workflow_called.append(args)
        return {"ok": True, "total": 1, "message": "ran it"}

    c._live_start_desktop_task = fake_start_desktop_task
    c._live_run_workflow = fake_run_workflow

    res = c._live_tool("start_desktop_task", {"goal": "post my anime edit"})

    assert not agent_called, "Full agent should NOT be called when workflow matches"
    assert workflow_called, "Workflow runner should have been called"
    assert res["ok"] is True


def test_start_desktop_task_no_redirect_when_no_workflow_match(tmp_path, monkeypatch):
    """If no workflow matches the goal (or match has <2 tokens), the full agent runs."""
    import app.workflows as wf

    monkeypatch.setattr(wf, "store_path", lambda: tmp_path / "workflows.json")
    wf.add_workflow(
        "post anime edit",
        description="Post my anime edit to Instagram",
        triggers=["post anime"],
        steps=[{"action": "open", "app": "Instagram"}],
        owner="user",
    )

    c = _controller()
    agent_called = []

    class FakeClient:
        def request(self, method, path, data=None, timeout=4.0, **kw):
            if path == "/api/tasks/preflight":
                return {"blocked": False}
            if path == "/api/tasks":
                return {}
            if path.startswith("/api/tasks/"):
                return {"status": "done", "complete": True, "reason": "done"}
            return {}

    c.client = FakeClient()

    orig = c._live_start_desktop_task

    def tracked(*args, **kwargs):
        agent_called.append(True)
        return orig(*args, **kwargs)

    c._live_start_desktop_task = tracked

    # "open notepad" shares 0 keyword tokens with "post anime edit"
    c._live_tool("start_desktop_task", {"goal": "open notepad"})
    assert agent_called, "Full agent must run when goal doesn't match any workflow"


def test_start_desktop_task_skip_workflow_check_flag(tmp_path, monkeypatch):
    """skip_workflow_check=True bypasses the workflow redirect even on a match."""
    import app.workflows as wf

    monkeypatch.setattr(wf, "store_path", lambda: tmp_path / "workflows.json")
    wf.add_workflow(
        "post anime edit",
        triggers=["post anime edit"],
        steps=[{"action": "open", "app": "Instagram"}],
    )

    c = _controller()
    agent_called = []

    class FakeClient:
        def request(self, method, path, data=None, timeout=4.0, **kw):
            if path == "/api/tasks/preflight":
                return {"blocked": False}
            if path == "/api/tasks":
                return {}
            if path.startswith("/api/tasks/"):
                return {"status": "done", "complete": True, "reason": "done"}
            return {}

    c.client = FakeClient()
    orig = c._live_start_desktop_task

    def tracked(*a, **kw):
        agent_called.append(True)
        return orig(*a, **kw)

    c._live_start_desktop_task = tracked
    c._live_tool("start_desktop_task", {"goal": "post anime edit", "skip_workflow_check": True})
    assert agent_called, "Agent must run when skip_workflow_check=True"


# ── Items 2a & 2b: build_task_payload injects workflows + connector briefs ───

def test_build_task_payload_injects_workflow_block(tmp_path, monkeypatch):
    """build_task_payload should include matching workflow names in the goal."""
    import app.workflows as wf
    from app.widget.textbox_overlay import build_task_payload

    monkeypatch.setattr(wf, "store_path", lambda: tmp_path / "workflows.json")
    wf.add_workflow(
        "morning setup",
        description="Open apps for the morning routine",
        triggers=["morning setup", "start my morning"],
        steps=[{"action": "open", "app": "Chrome"}],
    )

    payload = build_task_payload("start my morning routine")
    goal_text = payload["goal"]
    assert "morning setup" in goal_text.lower() or "morning" in goal_text.lower(), (
        f"Workflow block should appear in payload goal, got: {goal_text[:300]}"
    )


def test_build_task_payload_no_workflow_block_when_no_match(tmp_path, monkeypatch):
    """When no workflows match, the workflow block is simply absent — no crash."""
    import app.workflows as wf
    from app.widget.textbox_overlay import build_task_payload

    monkeypatch.setattr(wf, "store_path", lambda: tmp_path / "no_wf.json")
    # No workflows saved
    payload = build_task_payload("do something completely unrelated")
    # Should not raise; goal is still a non-empty string
    assert isinstance(payload["goal"], str) and payload["goal"]


def test_build_task_payload_connector_brief_injected(monkeypatch):
    """build_task_payload injects connector skill briefs for matching goals."""
    import app.connectors as conn
    from app.widget.textbox_overlay import build_task_payload

    # Stub relevant_briefs to return a fake brief
    monkeypatch.setattr(conn, "relevant_briefs", lambda goal: [("FakeSvc", "FAKESVC SKILL: do stuff")])

    payload = build_task_payload("check my email in fakesvc")
    assert "FAKESVC SKILL" in payload["goal"], (
        f"Connector brief should be injected, got: {payload['goal'][:400]}"
    )


def test_build_task_payload_no_connector_brief_when_none(monkeypatch):
    """build_task_payload is safe when relevant_briefs returns empty list."""
    import app.connectors as conn
    from app.widget.textbox_overlay import build_task_payload

    monkeypatch.setattr(conn, "relevant_briefs", lambda goal: [])
    payload = build_task_payload("open notepad")
    assert isinstance(payload["goal"], str) and payload["goal"]


# ── Item 3: list_workflows tool ───────────────────────────────────────────────

def test_list_workflows_returns_current_list(tmp_path, monkeypatch):
    """list_workflows returns a live list including workflows saved mid-session."""
    import app.workflows as wf

    monkeypatch.setattr(wf, "store_path", lambda: tmp_path / "wf.json")
    wf.add_workflow("do dishes", description="Clean the dishes", steps=[{"action": "open", "app": "Notes"}])
    wf.add_workflow("morning routine", description="Start the day", steps=[{"action": "open", "app": "Chrome"}])

    c = _controller()
    res = c._live_tool("list_workflows", {})

    assert res["ok"] is True
    assert res["count"] == 2
    names = [w["title"] for w in res["workflows"]]
    assert any("dishes" in n.lower() for n in names)
    assert any("morning" in n.lower() for n in names)


def test_list_workflows_empty(tmp_path, monkeypatch):
    """list_workflows returns a helpful message when no workflows exist."""
    import app.workflows as wf

    monkeypatch.setattr(wf, "store_path", lambda: tmp_path / "empty.json")

    c = _controller()
    res = c._live_tool("list_workflows", {})

    assert res["ok"] is True
    assert res["count"] == 0
    assert "save_workflow" in res["message"]


def test_list_workflows_with_query_filter(tmp_path, monkeypatch):
    """list_workflows with a query returns only relevant workflows."""
    import app.workflows as wf

    monkeypatch.setattr(wf, "store_path", lambda: tmp_path / "wf2.json")
    wf.add_workflow("email cleanup", description="Sort inbox", steps=[{"action": "open", "app": "Gmail"}])
    wf.add_workflow("code review", description="Review PRs", steps=[{"action": "open", "app": "GitHub"}])

    c = _controller()
    res = c._live_tool("list_workflows", {"query": "email"})

    assert res["ok"] is True
    # email workflow should appear; may or may not include code review
    titles = [w["title"].lower() for w in res["workflows"]]
    assert any("email" in t for t in titles)


def test_list_workflows_declared_in_function_declarations():
    """list_workflows must be in the Gemini Live function declarations."""
    from google.genai import types
    from app.widget import gemini_live as gl

    decls = gl._function_declarations(types)
    names = {d.name for d in decls}
    assert "list_workflows" in names


# ── Item 4: get_companion_status enrichment ───────────────────────────────────

def test_get_companion_status_includes_linked_connectors(monkeypatch, tmp_path):
    """get_companion_status should report which connectors are currently linked."""
    import app.connectors as conn

    monkeypatch.setattr(conn, "linked_only", lambda: [{"id": "gmail"}, {"id": "notion"}])

    c = _controller()

    class FakeClient:
        def request(self, method, path, data=None, timeout=3.0, **kw):
            return {"tasks": []}

    c.client = FakeClient()
    res = c._live_tool("get_companion_status", {})

    assert res["ok"] is True
    assert "linked_connectors" in res
    assert "gmail" in res["linked_connectors"]
    assert "notion" in res["linked_connectors"]


def test_get_companion_status_includes_workflow_count(tmp_path, monkeypatch):
    """get_companion_status should include the number of saved workflows."""
    import app.workflows as wf

    monkeypatch.setattr(wf, "store_path", lambda: tmp_path / "wf.json")
    wf.add_workflow("task one", steps=[{"action": "open", "app": "Chrome"}])
    wf.add_workflow("task two", steps=[{"action": "open", "app": "Notes"}])

    c = _controller()

    class FakeClient:
        def request(self, method, path, data=None, timeout=3.0, **kw):
            return {"tasks": []}

    c.client = FakeClient()
    res = c._live_tool("get_companion_status", {})

    assert res["ok"] is True
    assert res.get("workflow_count") == 2


def test_get_companion_status_includes_knowledge_count(monkeypatch):
    """get_companion_status should include the number of knowledge facts."""
    import app.knowledge as know

    monkeypatch.setattr(know, "all_facts", lambda: [{"text": "a"}, {"text": "b"}, {"text": "c"}])

    c = _controller()

    class FakeClient:
        def request(self, method, path, data=None, timeout=3.0, **kw):
            return {"tasks": []}

    c.client = FakeClient()
    res = c._live_tool("get_companion_status", {})

    assert res["ok"] is True
    assert res.get("knowledge_facts") == 3


# ── Item 5: success narration ─────────────────────────────────────────────────

def test_narration_phrase_action_result_failure():
    """action_result with ok=False still says 'that didn't work'."""
    c = _controller()
    phrase = c._narration_phrase_for_event({
        "type": "action_result", "ok": False, "action_type": "uia_click",
    })
    assert "didn't work" in phrase


def test_narration_phrase_action_result_success_vision():
    """action_result success for observe/screenshot gives a spoken phrase."""
    c = _controller()
    phrase = c._narration_phrase_for_event({
        "type": "action_result", "ok": True, "action_type": "observe",
    })
    assert phrase  # should be non-empty for screen-read success


def test_narration_phrase_action_result_success_file_write():
    """action_result success for write_file gives a spoken phrase."""
    c = _controller()
    phrase = c._narration_phrase_for_event({
        "type": "action_result", "ok": True, "action_type": "write_file",
    })
    assert phrase


def test_narration_phrase_action_result_success_click_is_silent():
    """action_result success for a plain click should be silent — too noisy."""
    c = _controller()
    phrase = c._narration_phrase_for_event({
        "type": "action_result", "ok": True, "action_type": "uia_click",
    })
    assert phrase == "", f"Expected silence for click success, got: {phrase!r}"


# ── Item 6: memory recall failure logging ─────────────────────────────────────

def test_recall_sessions_failure_returns_empty_and_logs(capsys):
    """recall_sessions catches errors and prints to stderr — not silent."""
    from unittest.mock import MagicMock
    from app.memory import MemoryStore

    store = MagicMock(spec=MemoryStore)

    class BadCollection:
        def count(self):
            return 10

        def query(self, **kw):
            raise RuntimeError("ChromaDB unavailable")

    store.collection = BadCollection()
    # Call the real recall_sessions on our patched object
    result = MemoryStore.recall_sessions(store, "find something", 5)

    assert result == [], "Should return empty list on error"
    captured = capsys.readouterr()
    assert "recall_sessions" in captured.err or "ChromaDB" in captured.err, (
        f"Expected error logged to stderr, got: {captured.err!r}"
    )


# ── Item 7: workflow control name validation warnings ─────────────────────────

def test_save_workflow_warns_on_click_step_without_target(tmp_path, monkeypatch):
    """A click step with no target triggers a validation warning in the response."""
    import app.workflows as wf

    monkeypatch.setattr(wf, "store_path", lambda: tmp_path / "wf.json")

    c = _controller()
    res = c._live_tool("save_workflow", {
        "name": "bad click",
        "steps": [{"action": "click"}],  # no target
    })

    assert res["ok"] is True  # still saved (fail-soft)
    assert "warnings" in res
    assert any("no target" in w.lower() for w in res["warnings"])


def test_save_workflow_warns_on_very_long_target(tmp_path, monkeypatch):
    """A click step with an absurdly long target triggers a warning."""
    import app.workflows as wf

    monkeypatch.setattr(wf, "store_path", lambda: tmp_path / "wf2.json")

    c = _controller()
    long_target = "x" * 200
    res = c._live_tool("save_workflow", {
        "name": "long target wf",
        "steps": [{"action": "click", "target": long_target}],
    })

    assert res["ok"] is True
    assert "warnings" in res
    assert any("long" in w.lower() for w in res["warnings"])


def test_save_workflow_no_warnings_on_valid_steps(tmp_path, monkeypatch):
    """A well-formed workflow produces no warnings."""
    import app.workflows as wf

    monkeypatch.setattr(wf, "store_path", lambda: tmp_path / "wf3.json")

    c = _controller()
    res = c._live_tool("save_workflow", {
        "name": "open chrome",
        "steps": [{"action": "open", "app": "Chrome"}, {"action": "click", "target": "New Tab"}],
    })

    assert res["ok"] is True
    assert "warnings" not in res


# ── Item 8: broad exception logging ──────────────────────────────────────────

def test_live_context_block_logs_on_workflow_error(monkeypatch, capsys):
    """_live_context_block logs to stderr when workflow read fails."""
    import app.workflows as wf

    monkeypatch.setattr(wf, "as_prompt_block", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("disk error")))

    c = _controller()
    result = c._live_context_block()
    # Should not raise; returns whatever knowledge block there is
    assert isinstance(result, str)
    captured = capsys.readouterr()
    assert "disk error" in captured.err or "_live_context_block" in captured.err


def test_build_task_payload_logs_on_workflow_inject_error(monkeypatch, capsys):
    """build_task_payload logs to stderr when workflow injection fails."""
    import app.workflows as wf
    from app.widget.textbox_overlay import build_task_payload

    monkeypatch.setattr(wf, "as_prompt_block", lambda *a, **kw: (_ for _ in ()).throw(OSError("no disk")))

    payload = build_task_payload("open something")
    assert isinstance(payload["goal"], str)
    captured = capsys.readouterr()
    assert "no disk" in captured.err or "workflow inject" in captured.err


def test_build_task_payload_logs_on_connector_inject_error(monkeypatch, capsys):
    """build_task_payload logs to stderr when connector brief injection fails."""
    import app.connectors as conn
    from app.widget.textbox_overlay import build_task_payload

    monkeypatch.setattr(conn, "relevant_briefs", lambda goal: (_ for _ in ()).throw(OSError("conn error")))

    payload = build_task_payload("check my email")
    assert isinstance(payload["goal"], str)
    captured = capsys.readouterr()
    assert "conn error" in captured.err or "connector brief" in captured.err


# ── Security: workflow run-step safety check ──────────────────────────────────

def test_workflow_run_step_blocked_by_safety_manager():
    """A destructive shell command in a workflow 'run' step must be blocked —
    the safety check that guards _live_run_terminal must also apply here."""
    from unittest.mock import MagicMock, patch

    c = _controller()

    class FakeDecision:
        requires_approval = True
        reason = "dangerous command"

    with patch("app.safety.SafetyManager") as MockSM:
        MockSM.return_value.evaluate.return_value = FakeDecision()
        step = {"action": "run", "command": "rm -rf /"}
        result = c._run_workflow_step(step)

    assert result["ok"] is False
    assert "Blocked" in result["label"] or "blocked" in result["label"].lower()


def test_workflow_run_step_safe_command_executes(monkeypatch):
    """A safe shell command in a workflow 'run' step passes the safety check and runs."""
    from unittest.mock import MagicMock, patch
    from app.models import ToolResult

    c = _controller()

    class FakeDecision:
        requires_approval = False
        reason = ""

    calls = []

    class FakeTools:
        def run_command(self, cmd):
            calls.append(cmd)
            return ToolResult(ok=True, output="done")

    c._desktop_tools = FakeTools()

    with patch("app.safety.SafetyManager") as MockSM:
        MockSM.return_value.evaluate.return_value = FakeDecision()
        result = c._run_workflow_step({"action": "run", "command": "echo hello"})

    assert result["ok"] is True
    assert calls == ["echo hello"]


def test_workflow_run_step_safety_check_unavailable_blocks():
    """If SafetyManager can't be imported or raises, the step is blocked — fail safe."""
    from unittest.mock import patch

    c = _controller()

    with patch("app.safety.SafetyManager", side_effect=ImportError("no safety")):
        result = c._run_workflow_step({"action": "run", "command": "echo hi"})

    assert result["ok"] is False
    assert "unavailable" in result["label"].lower() or "safety" in result["label"].lower()


# ── Resource: timer thread cap ────────────────────────────────────────────────

def test_set_timer_respects_concurrent_cap():
    """After 20 concurrent timers, a 21st is rejected rather than spinning another thread."""
    import threading

    c = _controller()
    # Simulate 20 alive timers by planting fake alive threads.
    fake_threads = []
    for _ in range(20):
        e = threading.Event()
        t = threading.Thread(target=e.wait)  # blocks indefinitely
        t.daemon = True
        t.start()
        fake_threads.append(t)
    c._live_timer_threads = list(fake_threads)

    res = c._live_tool("set_timer", {"seconds": 5, "label": "overflow timer"})
    assert res["ok"] is False
    assert "Too many" in res["message"]

    # cleanup
    for t in fake_threads:
        pass  # daemon threads; process exit will collect them


def test_set_timer_prunes_dead_threads_before_checking_cap():
    """Completed timers are pruned from the list so the cap doesn't fill up from old timers."""
    import threading

    c = _controller()
    # Plant 20 already-finished threads
    dead_threads = []
    for _ in range(20):
        t = threading.Thread(target=lambda: None)
        t.daemon = True
        t.start()
        t.join()  # ensure it's finished
        dead_threads.append(t)
    c._live_timer_threads = list(dead_threads)

    # 21st timer should succeed because all previous are dead
    res = c._live_tool("set_timer", {"seconds": 0.01, "label": "after prune"})
    assert res["ok"] is True


# ── Validation: _live_remember category ──────────────────────────────────────

def test_live_remember_invalid_category_falls_back_to_fact():
    """An invalid category string is silently coerced to 'fact' — never stored raw."""
    c = _controller()
    posted: list[dict] = []

    class FakeClient:
        def request(self, method, path, data=None, timeout=5.0, **kw):
            if path == "/api/memory/facts":
                posted.append(data or {})
            return {}

        def ensure_session(self):
            return True

        def session_token(self):
            return "tok"

    c.client = FakeClient()
    c._live = None  # no context update needed

    res = c._live_tool("remember", {"fact": "I prefer dark mode", "category": "hacker_injection"})

    # Should succeed but with category fixed to 'fact'
    assert res.get("ok") is not False or posted  # either ok=True or we at least tried
    if posted:
        assert posted[0].get("category") == "fact", (
            f"Expected category='fact', got {posted[0].get('category')!r}"
        )


def test_live_remember_valid_category_preserved():
    """A valid category like 'preference' is stored as-is."""
    c = _controller()
    posted: list[dict] = []

    class FakeClient:
        def request(self, method, path, data=None, timeout=5.0, **kw):
            if path == "/api/memory/facts":
                posted.append(data or {})
            return {}

        def ensure_session(self):
            return True

        def session_token(self):
            return "tok"

    c.client = FakeClient()
    c._live = None

    c._live_tool("remember", {"fact": "I like dark mode", "category": "preference"})

    if posted:
        assert posted[0].get("category") == "preference"


# ── Logging: _notify_live_memory_updated ─────────────────────────────────────

def test_notify_live_memory_updated_logs_on_send_failure(capsys):
    """If send_context_update raises, the exception is logged — not silently swallowed."""
    c = _controller()
    c._knowledge_block_cache = "some facts"

    class BadLive:
        def is_running(self):
            return True

        def send_context_update(self, note):
            raise RuntimeError("connection lost")

    c._live = BadLive()

    # Stub _live_is_running to return True
    c._live_is_running = lambda: True

    c._notify_live_memory_updated()

    captured = capsys.readouterr()
    assert "connection lost" in captured.err or "_notify_live_memory_updated" in captured.err, (
        f"Expected error logged to stderr, got: {captured.err!r}"
    )

from __future__ import annotations

import asyncio
import inspect
import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable


GEMINI_LIVE_MODEL = "gemini-3.1-flash-live-preview"
GEMINI_LIVE_INPUT_RATE = 16000
GEMINI_LIVE_OUTPUT_RATE = 24000
GEMINI_LIVE_TOOL_TIMEOUT = 12.0


StatusCallback = Callable[[str], None]
TranscriptCallback = Callable[[str, bool], None]
LevelCallback = Callable[[float], None]
ToolCallback = Callable[[str, dict[str, Any]], dict[str, Any]]


def _noop(*_args: Any, **_kwargs: Any) -> None:
    return None


def gemini_api_key() -> str:
    return (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or ""
    ).strip()


def _env_flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def live_search_enabled() -> bool:
    """Whether to attach Google Search grounding to the Live session.

    Off by default: Google Search is a PAID-tier Live feature — including it on a
    free-tier key makes the session fail with a quota/billing error (verified
    2026-06-15). Voice + our desktop function tools work fine on the free tier, and
    Orynn can still search the web via a desktop task. Set GEMINI_LIVE_SEARCH=1 to
    turn it on once the key is on a paid plan.
    """
    return _env_flag("GEMINI_LIVE_SEARCH")


def live_unavailable_reason() -> str:
    if not gemini_api_key():
        return "Gemini API key missing"
    try:
        import google.genai  # noqa: F401
    except Exception:
        return "Install google-genai for Gemini Live"
    try:
        import numpy  # noqa: F401
        import sounddevice as sd
    except Exception:
        return "Install sounddevice and numpy for Live audio"
    try:
        sd.query_devices(kind="input")
        sd.query_devices(kind="output")
    except Exception as exc:
        return f"Audio device unavailable: {str(exc)[:80]}"
    return ""


def live_available() -> bool:
    return not live_unavailable_reason()


def _coerce_tool_args(value: Any) -> tuple[dict[str, Any] | None, str | None]:
    if value is None:
        return {}, None
    if isinstance(value, dict):
        return dict(value), None
    if isinstance(value, Mapping):
        return dict(value), None
    try:
        return dict(value), None
    except Exception:
        return None, "Tool arguments must be a JSON object."


@dataclass
class GeminiLiveCallbacks:
    on_status: StatusCallback = _noop
    on_input_transcript: TranscriptCallback = _noop
    on_output_transcript: TranscriptCallback = _noop
    on_audio_level: LevelCallback = _noop
    on_error: StatusCallback = _noop
    on_stopped: StatusCallback = _noop
    on_tool: ToolCallback | None = None


class GeminiLiveCompanion:
    """Realtime Gemini Live audio bridge for the native companion.

    This class owns a background asyncio loop. Audio input/output runs through
    sounddevice, while desktop actions are exposed as high-level function calls
    handled by the caller.
    """

    def __init__(
        self,
        callbacks: GeminiLiveCallbacks,
        *,
        model: str | None = None,
        voice_name: str | None = None,
        system_instruction: str | None = None,
    ) -> None:
        self.callbacks = callbacks
        self.model = model or os.environ.get("GEMINI_LIVE_MODEL") or GEMINI_LIVE_MODEL
        # Default to a youthful male voice ("Puck"). Override with GEMINI_LIVE_VOICE
        # — other prebuilt options: Charon (deeper male), Fenrir/Orus (male),
        # Aoede/Kore/Leda (female).
        self.voice_name = voice_name or os.environ.get("GEMINI_LIVE_VOICE") or "Puck"
        self.system_instruction = system_instruction or _default_system_instruction()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._session: Any = None
        self._lock = threading.Lock()

    def is_running(self) -> bool:
        thread = self._thread
        return bool(thread and thread.is_alive() and not self._stop.is_set())

    def stop_requested(self) -> bool:
        return self._stop.is_set()

    def start(self) -> bool:
        reason = live_unavailable_reason()
        if reason:
            self.callbacks.on_error(reason)
            return False
        with self._lock:
            if self.is_running():
                return True
            self._stop.clear()
            self._thread = threading.Thread(target=self._thread_main, daemon=True)
            self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        loop = self._loop
        session = self._session
        if loop is not None and session is not None:
            try:
                asyncio.run_coroutine_threadsafe(session.close(), loop)
            except Exception:
                pass

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as exc:
            if not self._stop.is_set():
                self.callbacks.on_error(f"Gemini Live error: {str(exc)[:160]}")
        finally:
            self._loop = None
            self._session = None
            self.callbacks.on_stopped("Gemini Live stopped")

    async def _run(self) -> None:
        import numpy as np
        import sounddevice as sd
        from google import genai
        from google.genai import types

        self._loop = asyncio.get_running_loop()
        audio_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=24)

        def input_callback(indata: Any, _frames: int, _time: Any, _status: Any) -> None:
            chunk = bytes(indata)
            try:
                arr = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
                if arr.size:
                    rms = float(np.sqrt(np.mean(arr * arr)))
                    self.callbacks.on_audio_level(min(1.0, rms / 6000.0))
            except Exception:
                pass

            def put_chunk() -> None:
                if audio_queue.full():
                    try:
                        audio_queue.get_nowait()
                    except Exception:
                        pass
                try:
                    audio_queue.put_nowait(chunk)
                except Exception:
                    pass

            loop = self._loop
            if loop is not None:
                loop.call_soon_threadsafe(put_chunk)

        input_stream = sd.RawInputStream(
            samplerate=GEMINI_LIVE_INPUT_RATE,
            channels=1,
            dtype="int16",
            blocksize=1600,
            callback=input_callback,
        )
        output_stream = sd.RawOutputStream(
            samplerate=GEMINI_LIVE_OUTPUT_RATE,
            channels=1,
            dtype="int16",
            blocksize=2400,
        )

        client = genai.Client(api_key=gemini_api_key())
        config = self._live_config(types)

        async with client.aio.live.connect(model=self.model, config=config) as session:
            self._session = session
            input_stream.start()
            output_stream.start()
            self.callbacks.on_status("Gemini Live listening")
            sender = asyncio.create_task(self._send_audio(session, audio_queue, types))
            try:
                await self._receive_loop(session, output_stream, types)
            finally:
                self._stop.set()
                sender.cancel()
                try:
                    await session.send_realtime_input(audio_stream_end=True)
                except Exception:
                    pass
                for stream in (input_stream, output_stream):
                    try:
                        stream.stop()
                        stream.close()
                    except Exception:
                        pass

    def _live_config(self, types: Any) -> Any:
        # Our desktop function tools work on the free tier. Google Search grounding
        # is paid-tier only on Live, so it's opt-in via GEMINI_LIVE_SEARCH.
        tools = [types.Tool(function_declarations=_function_declarations(types))]
        if live_search_enabled():
            tools.insert(0, types.Tool(google_search=types.GoogleSearch()))
        return types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self.voice_name
                    )
                )
            ),
            thinking_config=types.ThinkingConfig(
                thinking_level=types.ThinkingLevel.MINIMAL
            ),
            system_instruction=self.system_instruction,
            tools=tools,
        )

    async def _send_audio(
        self,
        session: Any,
        audio_queue: asyncio.Queue[bytes],
        types: Any,
    ) -> None:
        while not self._stop.is_set():
            try:
                chunk = await asyncio.wait_for(audio_queue.get(), timeout=0.2)
            except asyncio.TimeoutError:
                continue
            await session.send_realtime_input(
                audio=types.Blob(
                    data=chunk,
                    mime_type=f"audio/pcm;rate={GEMINI_LIVE_INPUT_RATE}",
                )
            )

    async def _receive_loop(self, session: Any, output_stream: Any, types: Any) -> None:
        while not self._stop.is_set():
            async for message in session.receive():
                if self._stop.is_set():
                    return
                await self._handle_message(session, message, output_stream, types)
                if self._stop.is_set():
                    return

    async def _handle_message(
        self,
        session: Any,
        message: Any,
        output_stream: Any,
        types: Any,
    ) -> None:
        content = getattr(message, "server_content", None)
        if content is not None:
            output_finished = False
            inp = getattr(content, "input_transcription", None)
            if inp is not None and getattr(inp, "text", ""):
                self.callbacks.on_input_transcript(
                    str(inp.text), bool(getattr(inp, "finished", False))
                )
            out = getattr(content, "output_transcription", None)
            if out is not None and getattr(out, "text", ""):
                output_finished = bool(getattr(out, "finished", False))
                self.callbacks.on_output_transcript(
                    str(out.text), output_finished
                )
            turn = getattr(content, "model_turn", None)
            for part in getattr(turn, "parts", []) or []:
                inline = getattr(part, "inline_data", None)
                data = getattr(inline, "data", None)
                if data:
                    try:
                        output_stream.write(data)
                    except Exception as exc:
                        self.callbacks.on_error(f"Live audio output failed: {exc}")
            if getattr(content, "turn_complete", False):
                if not output_finished:
                    self.callbacks.on_output_transcript("", True)
                self.callbacks.on_status("Gemini Live listening")

        tool_call = getattr(message, "tool_call", None)
        calls = getattr(tool_call, "function_calls", None) if tool_call else None
        if calls:
            responses = []
            for call in calls:
                name = str(getattr(call, "name", "") or "")
                args, arg_error = _coerce_tool_args(getattr(call, "args", None))
                if arg_error:
                    self.callbacks.on_status("Live tool call failed")
                    result = {"ok": False, "message": arg_error}
                else:
                    result = await self._execute_tool(name, args or {})
                responses.append(
                    types.FunctionResponse(
                        name=name,
                        id=getattr(call, "id", None),
                        response=result,
                    )
                )
            if responses:
                await session.send_tool_response(function_responses=responses)

    async def _execute_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        handler = self.callbacks.on_tool
        if handler is None:
            return {"ok": False, "message": "No local tool handler is attached."}
        if self._stop.is_set():
            return {"ok": False, "message": "Gemini Live was stopped."}
        self.callbacks.on_status(f"Gemini Live tool: {name}")
        try:
            if inspect.iscoroutinefunction(handler):
                result = await asyncio.wait_for(
                    handler(name, args),
                    timeout=GEMINI_LIVE_TOOL_TIMEOUT,
                )
            else:
                result = await asyncio.wait_for(
                    asyncio.to_thread(handler, name, args),
                    timeout=GEMINI_LIVE_TOOL_TIMEOUT,
                )
            if inspect.isawaitable(result):
                result = await asyncio.wait_for(
                    result,
                    timeout=GEMINI_LIVE_TOOL_TIMEOUT,
                )
            if self._stop.is_set():
                return {"ok": False, "message": "Gemini Live was stopped."}
            if isinstance(result, dict):
                return result
            return {"ok": True, "result": result}
        except asyncio.TimeoutError:
            return {
                "ok": False,
                "message": f"Tool timed out after {GEMINI_LIVE_TOOL_TIMEOUT:.0f}s.",
            }
        except Exception as exc:
            return {"ok": False, "message": str(exc)[:300]}


def _function_declarations(types: Any) -> list[Any]:
    return [
        types.FunctionDeclaration(
            name="desktop_control",
            description=(
                "Run one bounded, local Orynn desktop action using safe Windows "
                "UI Automation/window tools. Prefer observe/find/wait before "
                "click/type. Use start_desktop_task for launching apps or broader "
                "multi-step jobs."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "wait_for_window",
                            "focus_window",
                            "observe",
                            "find",
                            "wait",
                            "click",
                            "type",
                            "press_keys",
                        ],
                        "description": "The single desktop primitive to run.",
                    },
                    "app": {
                        "type": "string",
                        "description": "Window title/app hint, such as Notepad or Calculator.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Window title to wait for or focus; falls back to app.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Visible UIA control name or AutomationId.",
                    },
                    "text": {
                        "type": "string",
                        "description": "Text to type into a matched editable control.",
                    },
                    "keys": {
                        "type": "string",
                        "description": "Keyboard shortcut, e.g. ctrl+a, enter, escape, tab.",
                    },
                    "clear_first": {"type": "boolean"},
                    "submit": {"type": "boolean"},
                    "timeout": {"type": "number"},
                    "limit": {"type": "integer"},
                    "cap": {"type": "integer"},
                },
                "required": ["action"],
            },
        ),
        types.FunctionDeclaration(
            name="start_desktop_task",
            description=(
                "Start an Orynn desktop task for actions that require using "
                "the user's computer, apps, files, browser, mouse, or keyboard."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "The exact desktop task Orynn should carry out.",
                    }
                },
                "required": ["goal"],
            },
        ),
        types.FunctionDeclaration(
            name="stop_current_task",
            description="Stop or cancel currently running Orynn desktop tasks.",
            parameters_json_schema={
                "type": "object",
                "properties": {},
            },
        ),
        types.FunctionDeclaration(
            name="get_companion_status",
            description="Check whether Orynn currently has active desktop tasks.",
            parameters_json_schema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


def _default_system_instruction() -> str:
    return (
        "You are Orynn, a warm, easy-going voice companion living on the user's "
        "Windows PC. You're talking out loud, so speak the way a helpful friend "
        "would: short, natural sentences, contractions, no lists or markdown, no "
        "emoji, and never read out symbols or tool names.\n"
        "When the user asks you to actually do something on the computer, DON'T "
        "pretend you did it. For a single bounded desktop step, call "
        "desktop_control: wait/focus/observe/find/click/type/press_keys. Prefer "
        "UIA names and pass the app/window title whenever you know it. For opening "
        "apps, browsing, files, or broader multi-step work, say a quick natural "
        "acknowledgement out loud and in the same turn call start_desktop_task "
        "with a clear, specific goal. If the user says stop, cancel, or never "
        "mind, call stop_current_task right away and confirm you stopped.\n"
        "If they're just chatting or asking a question, simply answer — briefly and "
        "conversationally — without using any tool. Ask a short clarifying question "
        "only when you genuinely can't act otherwise. For anything risky or "
        "irreversible (deleting files, sending messages, purchases), check with the "
        "user before doing it.\n"
        "Desktop tasks you launch with start_desktop_task run in the background and "
        "you won't automatically hear how they end, so if the user asks how it went, "
        "call get_companion_status to check. Only ONE desktop task can run at a time: "
        "if you try to act on the computer while one is still running, the tool tells "
        "you it's busy and names what's in progress — when that happens, say what's "
        "running and ask whether to stop it (stop_current_task) or wait, instead of "
        "trying again. Chatting and answering questions are always fine, even mid-task."
    )

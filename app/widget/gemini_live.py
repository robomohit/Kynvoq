from __future__ import annotations

import asyncio
import inspect
import json
import os
import queue
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

# Eager import heavy libraries to avoid slow initial voice hotkey response
try:
    import numpy as np
    import sounddevice as sd
    from google import genai
    from google.genai import types
except ImportError:
    pass


GEMINI_LIVE_MODEL = "gemini-3.1-flash-live-preview"
GEMINI_LIVE_INPUT_RATE = 16000
GEMINI_LIVE_OUTPUT_RATE = 24000
# Outer cap on a tool call. Must stay safely ABOVE the longest bounded desktop
# action (a wait can run ~9s + focus/observe overhead) — otherwise this fires
# first, the thread keeps running uncancellably, and the model is told "timed out"
# while the action is actually still going.
GEMINI_LIVE_TOOL_TIMEOUT = 15.0
# A single audio-output glitch (buffer underrun, device blip) must not kill the
# whole conversation — only give up after this many in a row (~4s of 100ms chunks).
GEMINI_LIVE_MAX_AUDIO_FAILS = 40
# Maximum retry delay capped at 30 seconds for connection robustness.
GEMINI_LIVE_MAX_RETRY_DELAY = 30.0
# Prefix for background alerts injected into Live — model must speak without user prompt.
LIVE_PROACTIVE_PREFIX = (
    "[ORYNN — speak out loud NOW. This is an automatic system alert, not the user "
    "talking. The user may be idle, gaming, or mid-conversation. Respond with spoken "
    "audio immediately in one or two short sentences. Do NOT wait for them to ask.] "
)

_DEBUG_SESSION = "eec63b"
_DEBUG_LOG = (
    Path(__file__).resolve().parents[2].parent / "Ai_computer" / "debug-eec63b.log"
)


def _agent_debug_log(
    hypothesis_id: str,
    location: str,
    message: str,
    data: dict[str, Any] | None = None,
) -> None:
    # region agent log
    try:
        payload = {
            "sessionId": _DEBUG_SESSION,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data or {},
            "timestamp": int(time.time() * 1000),
            "runId": "pre-fix",
        }
        _DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_DEBUG_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, default=str) + "\n")
    except Exception:
        pass
    # endregion


StatusCallback = Callable[[str], None]
TranscriptCallback = Callable[[str, bool], None]
LevelCallback = Callable[[float], None]
ToolCallback = Callable[[str, dict[str, Any]], dict[str, Any]]


def _noop(*_args: Any, **_kwargs: Any) -> None:
    return None


def _resample_audio(data: bytes, from_rate: int, to_rate: int) -> bytes:
    if from_rate == to_rate or not data:
        return data
    import numpy as np
    try:
        arr = np.frombuffer(data, dtype=np.int16)
        duration = len(arr) / from_rate
        num_samples = int(duration * to_rate)
        if num_samples <= 0:
            return data
        x_old = np.linspace(0, duration, len(arr), endpoint=False)
        x_new = np.linspace(0, duration, num_samples, endpoint=False)
        arr_new = np.interp(x_new, x_old, arr).astype(np.int16)
        return arr_new.tobytes()
    except Exception:
        return data


def gemini_api_key() -> str:
    return (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or ""
    ).strip()


def _env_flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def _live_thinking_level(types: Any) -> Any:
    """Gemini 3.1 Live thinking depth. Default MEDIUM for reliable tool routing;
    LOW/MINIMAL for lower latency. Override with GEMINI_LIVE_THINKING or
    GEMINI_LIVE_THINKING_LEVEL (minimal|low|medium|high)."""
    raw = (
        os.environ.get("GEMINI_LIVE_THINKING")
        or os.environ.get("GEMINI_LIVE_THINKING_LEVEL")
        or "medium"
    ).strip().lower()
    level = getattr(types, "ThinkingLevel", None)
    if level is None:
        return None
    mapping = {
        "minimal": getattr(level, "MINIMAL", None),
        "low": getattr(level, "LOW", None),
        "medium": getattr(level, "MEDIUM", None),
        "high": getattr(level, "HIGH", None),
    }
    chosen = mapping.get(raw) or mapping.get("medium") or mapping.get("low")
    return chosen


def _live_greeting_enabled() -> bool:
    """Whether Live says a short hello when it connects. OFF by default — it adds a
    spoken turn on startup and can feed the echo loop (the model hearing its own
    greeting). Opt in with GEMINI_LIVE_GREETING=1."""
    return _env_flag("GEMINI_LIVE_GREETING")


def live_autostart_enabled() -> bool:
    """Whether Gemini Live starts automatically on launch — the 'main agent'
    experience where you just talk, no hotkey. OFF by default because it holds the
    mic open from boot and streams continuously (privacy + free-tier quota); opt in
    with ORYNN_LIVE_AUTOSTART=1. Falls back to push-to-talk if Live is unavailable."""
    return _env_flag("ORYNN_LIVE_AUTOSTART")


def live_wake_enabled() -> bool:
    """Wake-word mode: Live stays asleep (mic listened to LOCALLY/offline, no cloud
    streaming) until you say the wake word ('Orynn'), then it connects; it sleeps
    again after a stretch of silence. Opt in with ORYNN_LIVE_WAKE=1. This is the
    privacy/quota-friendly way to run Live as your always-available agent."""
    return _env_flag("ORYNN_LIVE_WAKE")


def live_idle_sleep_seconds() -> float:
    """How long Live stays connected with no user speech before it sleeps back to
    wake-word listening (wake mode only). Default 60s; override ORYNN_LIVE_IDLE."""
    try:
        return max(10.0, float(os.environ.get("ORYNN_LIVE_IDLE") or "60"))
    except Exception:
        return 60.0


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
    on_turn_complete: StatusCallback = _noop
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
        # Optional hook returning extra system-instruction text (Orynn's knowledge
        # memory). Called on every (re)connect so the latest learned/taught facts are
        # always in context. Best-effort: exceptions are ignored.
        self.dynamic_context: Callable[[], str] | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._session: Any = None
        self._lock = threading.Lock()
        self._audio_fail_streak = 0
        # Session-resumption handle (captured from the server) so a reconnect can
        # resume the SAME conversation instead of starting fresh. None = new session.
        self._resume_handle: str | None = None
        # Greet once per session (not on every reconnect).
        self._greeted = False
        # False until the first session has connected. The mic-queue drain (clearing
        # stale audio) must run ONLY on reconnects — on the first connect that queue
        # holds the user's FIRST utterance (captured between the mic starting and the
        # audio sender starting), so draining it makes them repeat themselves.
        self._connected_once = False
        # Set when the server sends go_away so we exit the receive loop cleanly
        # (instead of waiting for a 1008 abort when the session duration expires).
        self._go_away_reconnect = False

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

        input_rate = GEMINI_LIVE_INPUT_RATE
        input_resample = False

        def input_callback(indata: Any, _frames: int, _time: Any, _status: Any) -> None:
            chunk = bytes(indata)
            if input_resample:
                chunk = _resample_audio(chunk, input_rate, GEMINI_LIVE_INPUT_RATE)
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

        try:
            input_stream = sd.RawInputStream(
                samplerate=input_rate,
                channels=1,
                dtype="int16",
                blocksize=1600,
                callback=input_callback,
            )
        except Exception:
            try:
                device_info = sd.query_devices(kind="input")
                input_rate = int(device_info["default_samplerate"])
            except Exception:
                input_rate = 16000
            input_resample = (input_rate != GEMINI_LIVE_INPUT_RATE)
            blocksize = int(input_rate * 0.1)
            try:
                input_stream = sd.RawInputStream(
                    samplerate=input_rate,
                    channels=1,
                    dtype="int16",
                    blocksize=blocksize,
                    callback=input_callback,
                )
            except Exception as exc:
                self.callbacks.on_error(f"Failed to open microphone stream: {exc}")
                return

        output_rate = GEMINI_LIVE_OUTPUT_RATE
        output_resample = False
        try:
            output_stream = sd.RawOutputStream(
                samplerate=output_rate,
                channels=1,
                dtype="int16",
                blocksize=2400,
            )
        except Exception:
            try:
                device_info = sd.query_devices(kind="output")
                output_rate = int(device_info["default_samplerate"])
            except Exception:
                output_rate = 24000
            output_resample = (output_rate != GEMINI_LIVE_OUTPUT_RATE)
            blocksize = int(output_rate * 0.1)
            try:
                output_stream = sd.RawOutputStream(
                    samplerate=output_rate,
                    channels=1,
                    dtype="int16",
                    blocksize=blocksize,
                )
            except Exception as exc:
                input_stream.close()
                self.callbacks.on_error(f"Failed to open speaker stream: {exc}")
                return

        input_stream.start()
        output_stream.start()
        self.callbacks.on_status("Gemini Live listening")

        # Dedicated playback thread: drains model audio from a thread-safe queue and
        # writes it to the speaker. Writing must happen OFF the asyncio loop (writing
        # from the event-loop thread goes silent here) — and a real dedicated thread
        # (not asyncio.to_thread's shared pool) keeps it smooth: no pool jitter /
        # underruns, and it never blocks the receive loop. Resamples only if needed.
        output_q: "queue.Queue" = queue.Queue()

        def playback_worker() -> None:
            while not self._stop.is_set():
                try:
                    chunk = output_q.get(timeout=0.2)
                except queue.Empty:
                    continue
                if chunk is None:
                    break
                if output_resample:
                    chunk = _resample_audio(chunk, GEMINI_LIVE_OUTPUT_RATE, output_rate)
                try:
                    output_stream.write(chunk)
                    self._audio_fail_streak = 0
                except Exception as exc:
                    self._audio_fail_streak += 1
                    if self._audio_fail_streak >= GEMINI_LIVE_MAX_AUDIO_FAILS:
                        self._stop.set()
                        self.callbacks.on_error(f"Live audio output failed: {exc}")
                        break

        player = threading.Thread(target=playback_worker, name="orynn-live-audio", daemon=True)
        player.start()
        client = genai.Client(api_key=gemini_api_key())

        retries = 0
        retry_delay = 1.0

        try:
            while not self._stop.is_set():
                if retries > 0:
                    self.callbacks.on_status(f"Live reconnecting (attempt {retries})...")
                # Rebuilt each attempt so a reconnect carries the latest resume handle.
                config = self._live_config(types)
                try:
                    async with client.aio.live.connect(model=self.model, config=config) as session:
                        self._session = session
                        self._audio_fail_streak = 0
                        is_reconnect = self._connected_once
                        self._connected_once = True
                        retries = 0
                        retry_delay = 1.0
                        self.callbacks.on_status("Gemini Live listening")
                        # Close any half-captured input turn from the previous session so
                        # a reconnect (go_away / drop) starts a fresh "Hearing:" buffer —
                        # otherwise the next utterance concatenates onto the last
                        # ("Look at my screen.Hello."). No-op on the first connect.
                        try:
                            self.callbacks.on_input_transcript("", True)
                        except Exception:
                            pass
                        await self._maybe_greet(session, types)

                        # Clear stale audio from the mic queue ONLY on a reconnect — on
                        # the FIRST connect this queue holds the user's first utterance
                        # (captured while connecting/greeting), so draining it would make
                        # them repeat their opening command.
                        if is_reconnect:
                            while not audio_queue.empty():
                                try:
                                    audio_queue.get_nowait()
                                except asyncio.QueueEmpty:
                                    break

                        # Clear stale audio chunks from speaker (output) queue on reconnect
                        self._flush_output(output_q)

                        sender = asyncio.create_task(self._send_audio(session, audio_queue, types))
                        try:
                            await self._receive_loop(session, output_q, types)
                        finally:
                            sender.cancel()
                            try:
                                await sender
                            except asyncio.CancelledError:
                                pass
                except Exception as exc:
                    if self._stop.is_set():
                        break
                    retries += 1
                    # region agent log
                    _agent_debug_log(
                        "D",
                        "gemini_live.py:_run:reconnect",
                        "live connection dropped, retrying",
                        {
                            "attempt": retries,
                            "retry_delay": retry_delay,
                            "error": str(exc)[:160],
                            "has_resume_handle": bool(self._resume_handle),
                        },
                    )
                    # endregion

                    # Responsive sleep loop
                    slept = 0.0
                    while slept < retry_delay and not self._stop.is_set():
                        await asyncio.sleep(0.1)
                        slept += 0.1
                    retry_delay = min(retry_delay * 2.0, GEMINI_LIVE_MAX_RETRY_DELAY)
        finally:
            self._stop.set()
            try:
                output_q.put_nowait(None)  # wake the playback thread so it exits
            except Exception:
                pass
            try:
                player.join(timeout=1.0)
            except Exception:
                pass
            if self._session is not None:
                try:
                    await self._session.send_realtime_input(audio_stream_end=True)
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
        instruction = self.system_instruction
        if self.dynamic_context is not None:
            try:
                extra = self.dynamic_context()
                if extra:
                    instruction = f"{instruction}\n\n{extra}"
            except Exception:
                pass
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
                thinking_level=_live_thinking_level(types),
            ),
            system_instruction=instruction,
            tools=tools,
            # Resume the same conversation across reconnects (handle is None on the
            # first connect = fresh session; set from session_resumption_update).
            session_resumption=types.SessionResumptionConfig(handle=self._resume_handle),
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

    @staticmethod
    def _flush_output(output_queue_or_stream: Any) -> None:
        """Drop everything still queued for the speaker — used on barge-in so Orynn
        stops talking immediately instead of draining its audio backlog."""
        if not hasattr(output_queue_or_stream, "get_nowait"):
            return
        try:
            while True:
                output_queue_or_stream.get_nowait()
                try:
                    output_queue_or_stream.task_done()
                except Exception:
                    pass
        except Exception:
            pass

    async def _maybe_greet(self, session: Any, types: Any) -> None:
        """Say a short hello on first connect so the user knows Live is listening.
        Once per session (not on reconnects); silence with GEMINI_LIVE_GREETING=0."""
        if self._greeted or not _live_greeting_enabled():
            return
        self._greeted = True
        try:
            await session.send_client_content(
                turns=[types.Content(role="user", parts=[types.Part(
                    text="Greet me in a warm, natural SPOKEN voice so I know you're "
                         "listening. If your ORYNN MEMORY already tells you my name, use "
                         "it (welcome me back). If your ORYNN MEMORY is EMPTY — you know "
                         "nothing about me yet, so this is our first meeting — briefly "
                         "introduce yourself: you're Orynn, you can see my screen and do "
                         "things on my PC just by voice, and ask what you should call me. "
                         "Otherwise just greet me warmly and ask my name. Keep it to one "
                         "or two short sentences; don't ask what I need yet."
                )])],
                turn_complete=True,
            )
        except Exception:
            pass

    def send_task_update(self, text: str) -> None:
        """Push a background alert that Live should speak out loud (task done, progress).
        Thread-safe; best-effort."""
        note = str(text or "").strip()
        if not note:
            return
        if not note.startswith("[ORYNN"):
            note = LIVE_PROACTIVE_PREFIX + note
        self._send_client_note(note)

    def send_context_update(self, text: str) -> None:
        """Alias for memory/knowledge refreshes mid-session (not spoken alerts)."""
        self._send_client_note(text)

    def _send_client_note(self, text: str) -> None:
        loop = self._loop
        session = self._session
        if loop is None or session is None or self._stop.is_set() or not str(text or "").strip():
            return

        async def _send() -> None:
            try:
                from google.genai import types
                await session.send_client_content(
                    turns=[types.Content(role="user", parts=[types.Part(text=str(text))])],
                    turn_complete=True,
                )
            except Exception:
                pass

        try:
            asyncio.run_coroutine_threadsafe(_send(), loop)
        except Exception:
            pass

    def send_screen_image(self, jpeg_bytes: bytes, *, wait: bool = False) -> bool:
        """Push a screenshot FRAME into the live session so the model can SEE the screen
        (Gemini's own vision — no local OCR). Thread-safe.

        When ``wait`` is True, blocks until the frame is on the wire (and briefly after)
        before returning — look_at_screen uses this so the FunctionResponse cannot race
        ahead of the video frame (which made the model guess 'empty desktop' on the
        first try and only see Chrome after the user pushed back).

        Sends ONLY the frame, over the realtime-input VIDEO channel. Two things matter:
        (1) an image MUST go over realtime input, not a send_client_content blob — the
        Live API rejects an inline image in client_content with WebSocket 1007 and drops
        the whole session (the old "Listening forever" bug). (2) We do NOT also send a
        client_content text turn here: the tool's FunctionResponse already prompts the
        model to describe, so a second turn would be a redundant double-prompt. The
        caller (look_at_screen) puts the question in the FunctionResponse. Verified
        end-to-end by scripts/live_vision_smoke.py (this exact frame-then-FunctionResponse
        sequence)."""
        loop = self._loop
        session = self._session
        if loop is None or session is None or self._stop.is_set() or not jpeg_bytes:
            return False

        async def _send() -> None:
            try:
                from google.genai import types
                await session.send_realtime_input(
                    video=types.Blob(data=jpeg_bytes, mime_type="image/jpeg")
                )
                if wait:
                    # Brief pause so Live can attach the frame before FunctionResponse
                    # triggers the describe turn (smoke test awaits send before response).
                    await asyncio.sleep(0.25)
            except Exception as exc:  # noqa: BLE001
                # region agent log
                _agent_debug_log(
                    "V", "gemini_live.py:send_screen_image:error",
                    "failed to send screen image to Live",
                    {"error": str(exc)[:200]},
                )
                # endregion
                raise

        try:
            future = asyncio.run_coroutine_threadsafe(_send(), loop)
            if wait:
                future.result(timeout=5.0)
            return True
        except Exception:
            return False

    async def _receive_loop(self, session: Any, output_queue_or_stream: Any, types: Any) -> None:
        while not self._stop.is_set():
            async for message in session.receive():
                if self._stop.is_set():
                    return
                await self._handle_message(session, message, output_queue_or_stream, types)
                if self._go_away_reconnect:
                    self._go_away_reconnect = False
                    self.callbacks.on_status("Gemini Live reconnecting")
                    # region agent log
                    _agent_debug_log(
                        "D",
                        "gemini_live.py:_receive_loop:go_away",
                        "exiting receive loop for graceful go_away reconnect",
                        {"has_resume_handle": bool(self._resume_handle)},
                    )
                    # endregion
                    return
                if self._stop.is_set():
                    return

    async def _handle_message(
        self,
        session: Any,
        message: Any,
        output_queue_or_stream: Any,
        types: Any,
    ) -> None:
        # Remember the latest session-resumption handle so a reconnect resumes this
        # same conversation rather than starting over.
        resume = getattr(message, "session_resumption_update", None)
        if resume is not None and getattr(resume, "resumable", False):
            handle = getattr(resume, "new_handle", None)
            if handle:
                self._resume_handle = handle

        content = getattr(message, "server_content", None)
        if content is not None:
            # Barge-in: the user started talking over Orynn. Drop everything still
            # queued for the speaker so it stops mid-sentence instead of draining
            # its backlog and talking over them.
            if getattr(content, "interrupted", False):
                self._flush_output(output_queue_or_stream)
                # Barge-in starts a fresh user turn — close the previous input turn so
                # the new utterance doesn't append onto the last one's transcript.
                self.callbacks.on_input_transcript("", True)
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
                    if hasattr(output_queue_or_stream, "put_nowait"):
                        try:
                            output_queue_or_stream.put_nowait(data)
                        except Exception:
                            pass
                    elif hasattr(output_queue_or_stream, "write"):
                        try:
                            output_queue_or_stream.write(data)
                            self._audio_fail_streak = 0
                        except Exception as exc:
                            # One glitch (underrun, brief device blip) must NOT end the
                            # conversation — skip the chunk and keep going. Only give up
                            # if output fails solidly for a while, and when we do, stop
                            # the session cleanly (self._stop) so the receive loop unwinds
                            # and the thread can't be left running after on_error.
                            self._audio_fail_streak += 1
                            if self._audio_fail_streak >= GEMINI_LIVE_MAX_AUDIO_FAILS:
                                self._stop.set()
                                self.callbacks.on_error(f"Live audio output failed: {exc}")
                                return
            if getattr(content, "turn_complete", False):
                if not output_finished:
                    self.callbacks.on_output_transcript("", True)
                # Close the input turn too. Gemini rarely sets finished=True on input
                # transcription, so without an explicit turn-boundary finalize the
                # bubble's "Hearing:" buffer concatenates every past utterance. Empty
                # text + finished = silent finalize (no re-render of the old input).
                self.callbacks.on_input_transcript("", True)
                self.callbacks.on_status("Gemini Live listening")
                try:
                    self.callbacks.on_turn_complete("")
                except Exception:
                    pass
                if not getattr(getattr(message, "tool_call", None), "function_calls", None):
                    # region agent log
                    _agent_debug_log(
                        "A",
                        "gemini_live.py:_handle_message:turn_complete",
                        "turn finished without tool_call in same message",
                        {
                            "had_output_transcript": bool(
                                getattr(
                                    getattr(content, "output_transcription", None),
                                    "text",
                                    "",
                                )
                            ),
                            "interrupted": bool(getattr(content, "interrupted", False)),
                        },
                    )
                    # endregion

        tool_call = getattr(message, "tool_call", None)
        calls = getattr(tool_call, "function_calls", None) if tool_call else None
        if calls:
            # region agent log
            _agent_debug_log(
                "A",
                "gemini_live.py:_handle_message:tool_call",
                "model tool_call received",
                {
                    "tools": [
                        str(getattr(call, "name", "") or "")
                        for call in calls
                    ],
                },
            )
            # endregion
            responses = []
            from app.specialists.registry import EXCLUSION_GROUPS

            used_groups: set[str] = set()
            for call in calls:
                name = str(getattr(call, "name", "") or "")
                args, arg_error = _coerce_tool_args(getattr(call, "args", None))
                blocked_group = ""
                for group, tools in EXCLUSION_GROUPS.items():
                    if name in tools and group in used_groups:
                        blocked_group = group
                        break
                if arg_error:
                    self.callbacks.on_status("Live tool call failed")
                    result = {"ok": False, "message": arg_error}
                elif blocked_group:
                    group_msg = {
                        "desktop": (
                            "Only one desktop action per turn — pick desktop_control, "
                            "launch_app, OR start_desktop_task, not both. Wait for the result first."
                        ),
                    }
                    result = {
                        "ok": False,
                        "message": group_msg.get(
                            blocked_group,
                            f"Only one {blocked_group} tool per turn — wait for the result before calling another.",
                        ),
                    }
                else:
                    result = await self._execute_tool(name, args or {})
                    for group, tools in EXCLUSION_GROUPS.items():
                        if name in tools:
                            used_groups.add(group)
                responses.append(
                    types.FunctionResponse(
                        name=name,
                        id=getattr(call, "id", None),
                        response=result,
                    )
                )
            if responses:
                await session.send_tool_response(function_responses=responses)

        go_away = getattr(message, "go_away", None)
        if go_away is not None and not self._stop.is_set():
            # region agent log
            _agent_debug_log(
                "D",
                "gemini_live.py:_handle_message:go_away",
                "go_away received, scheduling graceful reconnect",
                {"time_left": str(getattr(go_away, "time_left", "") or "")[:40]},
            )
            # endregion
            try:
                await session.send_realtime_input(audio_stream_end=True)
            except Exception:
                pass
            self._go_away_reconnect = True

    async def _execute_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        handler = self.callbacks.on_tool
        if handler is None:
            return {"ok": False, "message": "No local tool handler is attached."}
        if self._stop.is_set():
            return {"ok": False, "message": "Gemini Live was stopped."}
        self.callbacks.on_status(f"Gemini Live tool: {name}")
        # region agent log
        _agent_debug_log(
            "E",
            "gemini_live.py:_execute_tool:entry",
            "executing local tool handler",
            {"tool": name, "arg_keys": sorted(args.keys())},
        )
        # endregion
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
                # region agent log
                _agent_debug_log(
                    "E",
                    "gemini_live.py:_execute_tool:exit",
                    "tool handler finished",
                    {"tool": name, "ok": bool(result.get("ok", True))},
                )
                # endregion
                return result
            # region agent log
            _agent_debug_log(
                "E",
                "gemini_live.py:_execute_tool:exit",
                "tool handler finished",
                {"tool": name, "ok": True},
            )
            # endregion
            return {"ok": True, "result": result}
        except asyncio.TimeoutError:
            # region agent log
            _agent_debug_log(
                "E",
                "gemini_live.py:_execute_tool:timeout",
                "tool handler timed out",
                {"tool": name},
            )
            # endregion
            return {
                "ok": False,
                "message": f"Tool timed out after {GEMINI_LIVE_TOOL_TIMEOUT:.0f}s.",
            }
        except Exception as exc:
            # region agent log
            _agent_debug_log(
                "E",
                "gemini_live.py:_execute_tool:error",
                "tool handler raised",
                {"tool": name, "error": str(exc)[:160]},
            )
            # endregion
            return {"ok": False, "message": str(exc)[:300]}


def _function_declarations(types: Any) -> list[Any]:
    return [
        types.FunctionDeclaration(
            name="desktop_control",
            description=(
                "ONE fast action (~1-3s) in an app already open: click a named button/"
                "link/menu item, type into one field, a keyboard shortcut, scroll, focus "
                "a window, or read what's on screen (observe/find). Use for 'click that "
                "button' — NOT start_desktop_task. Do NOT also call start_desktop_task "
                "for the same request. Auto-escalates to the full agent if "
                "the action can't land. NOT for opening/launching apps, files, or "
                "multi-step work."
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
                            "scroll",
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
                    "amount": {
                        "type": "integer",
                        "description": "For scroll: how far. Negative scrolls DOWN, "
                                       "positive scrolls UP (a few notches per ~10).",
                    },
                },
                "required": ["action"],
            },
        ),
        types.FunctionDeclaration(
            name="look_at_screen",
            description=(
                "Capture and SEE what's on screen with vision. Default: the foreground "
                "window. Use when the question is about what's visible in front of the "
                "user. Call BEFORE describing anything on screen; never guess from memory. "
                "For a BACKGROUND app while they're doing something else (gaming, etc.), "
                "use list_windows then capture_window instead. Read-only; safe mid-task."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "What the user wants to know about the screen.",
                    }
                },
            },
        ),
        types.FunctionDeclaration(
            name="list_windows",
            description=(
                "List open visible windows on the PC (title + minimized flag). Use when "
                "the user asks about an app that may NOT be in front — e.g. 'is Claude "
                "done' while they're gaming — or to pick which window to peek at. Does "
                "NOT capture yet; follow with capture_window."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "include_minimized": {
                        "type": "boolean",
                        "description": "Include minimized windows (default true).",
                    },
                },
            },
        ),
        types.FunctionDeclaration(
            name="capture_window",
            description=(
                "Screenshot a specific open window by partial title match using PrintWindow "
                "— often WITHOUT stealing focus from what the user is doing. Sends the "
                "frame into vision so you can answer. Use after list_windows when the "
                "target app is in the background. Read-only; safe mid-task."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Partial window title to match (e.g. 'Cursor', 'Claude').",
                    },
                    "index": {
                        "type": "integer",
                        "description": "If several windows match, which one (0 = first).",
                    },
                    "question": {
                        "type": "string",
                        "description": "What to look for in that window.",
                    },
                },
                "required": ["title"],
            },
        ),
        types.FunctionDeclaration(
            name="launch_app",
            description=(
                "Open or switch to an app by name (Spotify, Notepad, Settings, etc.). "
                "Prefer for pure 'open X' — verifies the window before success. "
                "Do NOT also call start_desktop_task for the same request."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "app": {
                        "type": "string",
                        "description": "App to open, e.g. Spotify, Notepad, Calculator.",
                    },
                    "settings_page": {
                        "type": "string",
                        "description": "Optional: display, sound, bluetooth, network, etc.",
                    },
                },
                "required": ["app"],
            },
        ),
        types.FunctionDeclaration(
            name="start_desktop_task",
            description=(
                "Full desktop agent: open/launch apps, files, multi-step goals "
                "('open X and do Y'), or vague setup work. Do NOT also call "
                "desktop_control for the same request. NOT for a single click/type "
                "in an already-open app. Don't web-search for local files or open "
                "Notepad just to display a filename."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "The exact desktop task Orynn should carry out.",
                    },
                    "confirmed": {
                        "type": "boolean",
                        "description": "Set to true ONLY after the user has verbally "
                                       "agreed to a disruptive action (deleting, sending, "
                                       "submitting, paying, formatting, relaunching an app). "
                                       "Leave unset otherwise.",
                    },
                },
                "required": ["goal"],
            },
        ),
        types.FunctionDeclaration(
            name="run_terminal",
            description=(
                "Run a single shell/terminal command on the user's Windows PC and "
                "get its output back — for quick things like git status, listing or "
                "reading files, checking versions, pip/npm, python scripts. Prefer "
                "this for short commands; use start_desktop_task for long-running or "
                "multi-step work. Catastrophic commands (wiping the disk, formatting, "
                "shutdown) are blocked outright; other destructive ones (deleting a "
                "file, git push, killing a process, uninstalling) need spoken consent."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The exact shell command to run.",
                    },
                    "confirmed": {
                        "type": "boolean",
                        "description": "Set to true ONLY after the user verbally agreed to "
                                       "a destructive command (delete, push, kill, uninstall). "
                                       "Leave unset otherwise.",
                    },
                },
                "required": ["command"],
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
            description=(
                "Check active desktop tasks and subagent progress. Returns "
                "active_tasks count, current_task goal, progress.step (what the "
                "worker is doing now — the user also sees this on the cursor pill), "
                "and last_result when a recent job finished."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {},
            },
        ),
        types.FunctionDeclaration(
            name="web_search",
            description=(
                "Real-time web facts: news, weather, scores, prices, current events, or "
                "anything you genuinely don't know or that CHANGES over time. One call "
                "per question — cite the source out loud when you answer. Do NOT search "
                "for basic knowledge you already know (capitals, simple math, definitions, "
                "history, common facts) — answer those instantly without a tool. NOT for "
                "files on their PC (use run_terminal or start_desktop_task)."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to look up.",
                    }
                },
                "required": ["query"],
            },
        ),
        types.FunctionDeclaration(
            name="remember",
            description=(
                "Save a durable fact into your organized memory so you know it next time "
                "— e.g. 'cowork is the button top-right of the dashboard', 'my budget "
                "sheet is in Documents', a rule the user states ('always confirm before "
                "sending'), or what a term/app means. Call it when the user says "
                "'remember that…', states a preference/rule, OR when YOU figure something "
                "out by looking (where an app or button is) so you don't have to look "
                "again — set owner='assistant' for things you learned yourself."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "fact": {"type": "string", "description": "The fact to remember, in plain words."},
                    "category": {
                        "type": "string",
                        "enum": ["rule", "preference", "location", "vocab", "fact", "app"],
                        "description": "How to file it: rule/preference (the user's), location (where "
                                       "something is), vocab (what a term means), app, or general fact.",
                    },
                    "owner": {
                        "type": "string",
                        "enum": ["user", "assistant"],
                        "description": "'user' if the user told you; 'assistant' if you learned it yourself.",
                    },
                    "app": {"type": "string", "description": "Optional app/window it relates to."},
                },
                "required": ["fact"],
            },
        ),
        types.FunctionDeclaration(
            name="forget",
            description="Forget facts you previously remembered that match the given text.",
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text of the fact(s) to forget."},
                },
                "required": ["query"],
            },
        ),
        types.FunctionDeclaration(
            name="run_workflow",
            description=(
                "Run a saved multi-step WORKFLOW by name (see ORYNN WORKFLOWS in your "
                "context for what exists). Use this instead of start_desktop_task when the "
                "user's request matches a saved workflow — it's the fast, reliable repeat. "
                "If a workflow needs confirmation it returns needs_consent; ask, then call "
                "again with confirmed=true."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name of the workflow to run."},
                    "confirmed": {"type": "boolean", "description": "True only after a spoken yes."},
                },
                "required": ["name"],
            },
        ),
        types.FunctionDeclaration(
            name="save_workflow",
            description=(
                "Save a reusable multi-step workflow so you can repeat it later by name "
                "(e.g. the user says 'remember how to post my edit' or after you do a "
                "multi-step task they'll want again). Steps run through the verified "
                "desktop tiers; reference controls by their on-screen NAME, never pixels."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Short name for the workflow."},
                    "description": {"type": "string", "description": "One line on what it does."},
                    "triggers": {"type": "array", "items": {"type": "string"},
                                 "description": "Phrases the user might say to run it."},
                    "steps": {
                        "type": "array",
                        "description": "Ordered steps.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "action": {"type": "string",
                                           "description": "open|click|type|press_keys|scroll|focus|run|wait"},
                                "app": {"type": "string"},
                                "target": {"type": "string", "description": "Control name to act on."},
                                "text": {"type": "string"},
                                "keys": {"type": "string"},
                                "command": {"type": "string"},
                                "seconds": {"type": "number"},
                            },
                            "required": ["action"],
                        },
                    },
                },
                "required": ["name", "steps"],
            },
        ),
        types.FunctionDeclaration(
            name="forget_workflow",
            description="Delete a saved workflow by name.",
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name of the workflow to delete."},
                },
                "required": ["name"],
            },
        ),
    ]


def _default_system_instruction() -> str:
    """Live system prompt — voice-first (Clicky-style), routing via examples + tool
    declarations (Google Gemini 3.x: concise instructions, few-shot examples, don't
    duplicate tool specs here). ORYNN MEMORY is appended separately on connect."""
    return (
        "You are Orynn — a warm voice companion on the user's Windows PC. You're "
        "speaking out loud: short natural sentences, contractions, friendly and direct. "
        "Write for the ear — no lists, markdown, emoji, or reading code or tool names "
        "aloud. Never say \"simply\" or \"just\".\n\n"
        "DEFAULT — JUST TALK\n"
        "Most messages are conversation. If they're chatting, asking something general, "
        "or thinking out loud, answer in voice only with no tools.\n\n"
        "KNOW THEM (MEMORY)\n"
        "You persist across sessions — never act like a blank new chat. Read ORYNN "
        "MEMORY (appended below) and use it: greet returning users by name, and never "
        "re-ask something you already know. When the user shares something DURABLE about "
        "themselves — their name or what to call them, what they do, their preferences "
        "and rules, what they're working on, their vocabulary, or where things live — "
        "PROACTIVELY call remember to save it (a short third-person fact like \"the "
        "user's name is Mohit\"), without being asked and without announcing it. Don't "
        "save one-off or trivial chatter; save what would make the next session feel "
        "like you know them. If you don't know their name yet, ask once, warmly.\n\n"
        "WHEN THEY WANT SOMETHING DONE\n"
        "Use at most ONE tool per request — each tool's description says when to use "
        "it. Never call start_desktop_task and desktop_control for the same goal (pick "
        "one; quick clicks auto-escalate if they fail). Check ORYNN MEMORY before "
        "looking things up or asking where something is. Save new facts with remember.\n\n"
        "Examples:\n"
        "- \"hey\" / \"explain recursion\" / \"capital of France\" / \"what's 8x7\" → "
        "voice only, no tools (basic knowledge — answer instantly, don't web_search)\n"
        "- \"who won the game last night\" → web_search once; cite the source out loud\n"
        "- \"git status\" / \"list my Downloads\" → run_terminal once\n"
        "- \"what's this error on my screen\" / \"look at my screen\" → look_at_screen "
        "once BEFORE describing anything visible; never guess\n"
        "- \"is Claude/Cursor done\" / peek at a background app while user games → "
        "list_windows once, then capture_window with the matching title\n"
        "- \"click that button\" / \"click Save\" / \"click Usage\" (one control, app "
        "already open) → desktop_control once — NOT start_desktop_task\n"
        "- \"click Save in Notepad\" (app already open) → desktop_control once\n"
        "- \"open Notepad\" / \"open Spotify\" / \"open Settings display\" → "
        "launch_app once (NOT start_desktop_task for a pure open)\n"
        "- \"open Chrome and search X\" / \"edit my file\" → "
        "start_desktop_task once\n"
        "- \"remember cowork is top right\" → remember\n"
        "- \"I'm Mohit\" / \"call me M\" / \"I run an anime edit channel\" → remember "
        "(save who they are, unprompted) and use it from now on\n"
        "- \"post my edit\" / \"do my morning setup\" when it matches an ORYNN WORKFLOW "
        "→ run_workflow with that name (the fast reliable repeat — not start_desktop_task)\n"
        "- \"save that as a workflow called X\" / \"remember how to do this\" → "
        "save_workflow with clear named steps\n"
        "- \"stop\" / \"cancel\" / \"never mind\" → stop_current_task\n\n"
        "WHILE WORKING\n"
        "Commands: one short ack (\"On it\", \"Sure\"), then let tools run — they see "
        "on-screen progress. Don't narrate every step. Speak again on done/failed, "
        "consent needed, or if they talk to you.\n\n"
        "BACKGROUND TASKS & PROACTIVE UPDATES\n"
        "When start_desktop_task keeps running in the background, tell the user OUT LOUD "
        "you've started it and you'll report when it's done — they can keep gaming or "
        "chatting. Messages prefixed [ORYNN — speak out loud NOW] are automatic alerts "
        "(task finished, progress, subagent output) — NOT the user. Respond with SPOKEN "
        "AUDIO immediately; never wait for them to ask \"is it done\". You stay listening; "
        "delivering these updates unprompted is expected.\n\n"
        "OUTCOMES\n"
        "Never claim success, finished, or opened until a tool returns ok:true "
        "(launch_app verifies the window). If ok is false or failed: say plainly it "
        "did NOT work. If ok is true: one or two sentences on what happened.\n\n"
        "CONSENT\n"
        "Before delete/send/submit/pay/relaunch, ask out loud. If a tool returns "
        "needs_consent, ask; retry with confirmed=true only after a clear yes.\n\n"
        "One desktop task at a time — if busy, say what's running and offer stop or wait. "
        "Chatting is always fine mid-task.\n\n"
        "VISION\n"
        "What's on screen is ONLY what the LATEST screenshot shows — fresh frames arrive "
        "continuously, so always answer from the most recent one and never describe a "
        "page from an earlier turn. A thin red ring, when present, marks the user's MOUSE "
        "POINTER — it is NOT part of the screen, so don't mention the ring. When they say "
        "'this', 'here', 'that', or ask what they're pointing at, read the element INSIDE "
        "the ring (the specific button/word/link), using the rest of the screen for "
        "context — do NOT default to the page title or biggest heading. If you don't see "
        "what they named, say so plainly and describe what IS there. "
        "Foreground peek: look_at_screen. Background peek (user busy elsewhere): "
        "list_windows → capture_window. If you haven't seen a fresh frame for this "
        "question, capture before answering. "
        "YOU have the eyes here — a fresh screenshot is attached every turn. After you "
        "click or type, CONFIRM the result from what you now see and say what changed. "
        "NEVER ask the user \"what do you see\", \"let me know what's on your screen\", "
        "or \"anything new?\" — that's your job; look_at_screen and tell THEM."
    )

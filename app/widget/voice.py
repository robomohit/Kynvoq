"""Local, free voice I/O for the capsule — no cloud, no API keys.

- speak(text): text-to-speech via Windows SAPI SpVoice (always present on Win).
- listen(): speech-to-text via the modern Windows speech recognizer
  (Windows.Media.SpeechRecognition, single dictation utterance), falling back to
  the classic SAPI in-proc recognizer if the modern one is unavailable.

Everything runs on Windows' built-in engines, so the whole voice loop stays free
and offline-capable, in keeping with the free-models-only product.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

# Speech-to-text backend. Groq Whisper (cloud, very fast + accurate) is used when
# GROQ_API_KEY is set and a mic is available; otherwise we fall back to the
# built-in Windows recognizers below so the capsule still works offline.
GROQ_STT_MODEL = os.environ.get("GROQ_STT_MODEL") or "whisper-large-v3-turbo"
_STT_SAMPLE_RATE = 16000  # Whisper-friendly mono sample rate

# A single dedicated TTS thread + queue so speech serialises and a new line can
# interrupt the previous one (SVSFPurgeBeforeSpeak) on the SAME voice instance.
_tts_lock = threading.Lock()
_tts_queue: list[tuple[str, int, bool]] = []
_tts_thread: threading.Thread | None = None
_tts_stop = False
_groq_tts_ok: bool | None = None  # None=untried, False=unavailable (don't retry)


def tts_available() -> bool:
    try:
        import comtypes.client as cc
        cc.CreateObject("SAPI.SpVoice")
        return True
    except Exception:
        return False


def _select_best_voice(voice) -> None:
    """Pick the least-robotic installed SAPI voice. Default Windows picks 'David'
    (US male) which sounds ancient; prefer a natural/female voice. Override with
    ORYNN_TTS_VOICE (substring match, e.g. 'zira', 'hazel')."""
    pref = (os.environ.get("ORYNN_TTS_VOICE") or "").strip().lower()

    def score(desc: str) -> int:
        d = desc.lower()
        if pref and pref in d:
            return 100
        if "natural" in d or "aria" in d or "jenny" in d or "guy" in d:
            return 60
        if "zira" in d:
            return 30   # US female — clearer than David
        if "hazel" in d:
            return 25   # GB female
        if "david" in d:
            return -10  # the "1600s robot"
        return 0

    try:
        toks = voice.GetVoices()
        best, best_score = None, -10_000
        for i in range(toks.Count):
            tok = toks.Item(i)
            s = score(tok.GetDescription())
            if s > best_score:
                best, best_score = tok, s
        if best is not None and best_score > 0:
            voice.Voice = best
    except Exception as exc:
        print(f"[voice] voice selection failed: {exc}", flush=True)


def _tts_backend() -> str:
    """Preferred TTS engine. ORYNN_TTS=groq|edge|sapi forces it; default 'edge'.
    'groq'  = Groq Orpheus neural voice (fast, free, reuses GROQ_API_KEY; needs a
              one-time terms-accept on the Groq console). Falls back to edge/sapi.
    'edge'  = Microsoft online neural voices (natural, free, no key).
    'sapi'  = legacy offline voices."""
    pref = (os.environ.get("ORYNN_TTS") or "edge").strip().lower()
    if pref == "groq":
        return "groq" if _groq_key() else "edge"
    if pref == "sapi":
        return "sapi"
    return "edge"


def _edge_voice() -> str:
    """Edge neural voice name. Defaults to Ava Multilingual — Microsoft's flagship
    conversational voice, far more human than the older 'Aria'. Override with
    ORYNN_TTS_VOICE (e.g. en-US-AndrewMultilingualNeural, en-GB-SoniaNeural)."""
    v = (os.environ.get("ORYNN_TTS_VOICE") or "").strip()
    return v if "Neural" in v else "en-US-AvaMultilingualNeural"


def _mci_play_file(path: str, mtype: str) -> bool:
    """Play an audio file with native Windows MCI, blocking until done or until a
    new line / stop is queued. mtype is 'mpegvideo' (mp3) or 'waveaudio' (wav)."""
    import ctypes

    mci = ctypes.windll.winmm.mciSendStringW
    alias = "orynntts"

    def _cmd(s: str) -> int:
        return mci(s, None, 0, None)

    try:
        if _cmd(f'open "{path}" type {mtype} alias {alias}') != 0:
            return False
        _cmd(f"play {alias}")
        buf = ctypes.create_unicode_buffer(64)
        while True:
            mci(f"status {alias} mode", buf, 64, None)
            if buf.value != "playing":
                break
            with _tts_lock:
                if _tts_stop or _tts_queue:  # interrupted by stop / next line
                    break
            time.sleep(0.05)
        _cmd(f"stop {alias}")
        _cmd(f"close {alias}")
        return True
    except Exception as exc:
        print(f"[voice] MCI playback failed: {exc}", flush=True)
        return False
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


def _edge_speak_blocking(text: str) -> bool:
    """Synthesize via Microsoft neural TTS and play the MP3. False on failure."""
    import asyncio
    import tempfile

    path = tempfile.mktemp(suffix=".mp3")
    try:
        import edge_tts

        async def _run() -> None:
            await edge_tts.Communicate(text, _edge_voice()).save(path)

        asyncio.run(_run())
        if not os.path.exists(path) or os.path.getsize(path) < 256:
            return False
    except Exception as exc:
        print(f"[voice] edge synth failed: {exc}", flush=True)
        try:
            os.remove(path)
        except Exception:
            pass
        return False
    return _mci_play_file(path, "mpegvideo")


def _groq_speak_blocking(text: str) -> bool:
    """Synthesize via Groq Orpheus neural TTS (fast) and play the WAV. Returns
    False if unavailable (no key / terms not accepted / error) so we fall back."""
    key = _groq_key()
    if not key:
        return False
    # Groq Orpheus voices: autumn, diana, hannah (female) / austin, daniel, troy (male).
    voice_name = (os.environ.get("ORYNN_GROQ_VOICE") or "autumn").strip()
    import tempfile

    try:
        import requests

        resp = requests.post(
            "https://api.groq.com/openai/v1/audio/speech",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": os.environ.get("GROQ_TTS_MODEL") or "canopylabs/orpheus-v1-english",
                "voice": voice_name,
                "input": text[:1200],
                "response_format": "wav",
            },
            timeout=30,
        )
        if resp.status_code != 200 or resp.content[:4] != b"RIFF":
            print(f"[voice] Groq TTS unavailable: {resp.status_code} {resp.text[:160]}", flush=True)
            return False
        path = tempfile.mktemp(suffix=".wav")
        with open(path, "wb") as fh:
            fh.write(resp.content)
    except Exception as exc:
        print(f"[voice] Groq TTS failed: {exc}", flush=True)
        return False
    return _mci_play_file(path, "waveaudio")


def _tts_worker() -> None:
    import pythoncom
    pythoncom.CoInitialize()
    pref = _tts_backend()
    sapi = [None]

    def _ensure_sapi():
        if sapi[0] is None:
            import comtypes.client as cc
            sapi[0] = cc.CreateObject("SAPI.SpVoice")
            _select_best_voice(sapi[0])
        return sapi[0]

    global _tts_thread, _groq_tts_ok
    while True:
        with _tts_lock:
            if not _tts_queue:
                _tts_thread = None
                return
            text, rate, interrupt = _tts_queue.pop(0)
        try:
            spoken = False
            # 1. Groq Orpheus (only if chosen and not already known-unavailable).
            if pref == "groq" and _groq_tts_ok is not False:
                if _groq_speak_blocking(text):
                    _groq_tts_ok = True
                    spoken = True
                else:
                    _groq_tts_ok = False  # terms not accepted yet → use fallback
            # 2. Edge neural (primary, or fallback from Groq).
            if not spoken and pref in ("groq", "edge"):
                spoken = _edge_speak_blocking(text)
            # 3. SAPI offline fallback.
            if not spoken:
                _sapi_speak(_ensure_sapi(), text, rate, interrupt)
        except Exception as exc:
            print(f"[voice] TTS speak failed: {exc}", flush=True)


def _sapi_speak(voice, text: str, rate: int, interrupt: bool) -> None:
    voice.Rate = rate
    flags = 1  # SVSFlagsAsync
    if interrupt:
        flags |= 2  # SVSFPurgeBeforeSpeak — cut off the previous line
    voice.Speak(text, flags)
    while True:  # serialise the queue but stay responsive to stop/next
        with _tts_lock:
            if _tts_stop or _tts_queue:
                try:
                    voice.Speak("", 2)
                except Exception:
                    pass
                break
        try:
            if voice.WaitUntilDone(120):
                break
        except Exception:
            break


def speak(text: str, rate: int = 0, interrupt: bool = True) -> bool:
    """Queue text to be spoken aloud. Returns False if there's nothing to say.
    Rate 0 = natural pace (the old default of 1 sounded rushed/robotic)."""
    text = (text or "").strip()
    if not text:
        return False
    text = text[:1200]  # don't read an essay
    global _tts_thread, _tts_stop
    with _tts_lock:
        _tts_stop = False
        if interrupt:
            _tts_queue.clear()
        _tts_queue.append((text, rate, interrupt))
        if _tts_thread is None or not _tts_thread.is_alive():
            _tts_thread = threading.Thread(target=_tts_worker, daemon=True)
            _tts_thread.start()
    return True


def stop_speaking() -> None:
    global _tts_stop
    with _tts_lock:
        _tts_queue.clear()
        _tts_stop = True


# ── Speech-to-text ───────────────────────────────────────────────────────────
def _groq_key() -> str:
    return (os.environ.get("GROQ_API_KEY") or "").strip()


def recorder_available() -> bool:
    """True when the manual push-to-talk recorder can capture mic audio."""
    try:
        import numpy  # noqa: F401
        import sounddevice  # noqa: F401
        return True
    except Exception:
        return False


def _groq_stt_available() -> bool:
    return bool(_groq_key() and recorder_available())


def push_to_talk_available() -> bool:
    """True when hold-to-talk recording and Groq transcription can both run."""
    return _groq_stt_available()


def stt_available() -> bool:
    if _groq_stt_available():
        return True
    try:
        import winsdk.windows.media.speechrecognition  # noqa: F401
        return True
    except Exception:
        try:
            import comtypes.client as cc
            cc.CreateObject("SAPI.SpInProcRecognizer")
            return True
        except Exception:
            return False


def _record_utterance(timeout: float) -> bytes | None:
    """Capture one spoken utterance from the default mic as 16-bit mono WAV bytes.

    Stops ~0.8s after speech ends, or gives up if nothing is said. Returns WAV
    bytes, b'' if no speech was detected, or None if mic capture is unavailable.
    """
    try:
        import numpy as np
        import sounddevice as sd
    except Exception as exc:
        print(f"[voice] mic capture unavailable: {exc}", flush=True)
        return None

    sr = _STT_SAMPLE_RATE
    block = int(sr * 0.1)              # 100ms blocks
    silence_thresh = 450.0            # int16 RMS below this counts as silence
    max_blocks = max(1, int(timeout / 0.1))
    trailing_silence_blocks = 8       # ~0.8s of quiet ends the utterance
    lead_silence_limit = 30           # give up after ~3s of no speech at all

    frames: list[bytes] = []
    started = False
    silent_run = 0
    try:
        with sd.InputStream(samplerate=sr, channels=1, dtype="int16") as stream:
            for i in range(max_blocks):
                data, _ = stream.read(block)
                arr = np.asarray(data, dtype=np.int16).reshape(-1)
                frames.append(arr.tobytes())
                rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2))) if arr.size else 0.0
                if rms > silence_thresh:
                    started = True
                    silent_run = 0
                else:
                    silent_run += 1
                    if started and silent_run >= trailing_silence_blocks:
                        break
                    if not started and i >= lead_silence_limit:
                        break
    except Exception as exc:
        print(f"[voice] recording failed: {exc}", flush=True)
        return None

    if not started:
        return b""

    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(b"".join(frames))
    return buf.getvalue()


def _pcm_to_wav(pcm: bytes, sample_rate: int = _STT_SAMPLE_RATE) -> bytes:
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def transcribe_wav(wav: bytes) -> str | None:
    """Send WAV bytes to Groq Whisper and return the transcript. Returns '' for
    empty input and None if Groq STT is unavailable (no key) or the call fails."""
    key = _groq_key()
    if not key:
        return None
    if not wav:
        return ""
    try:
        import requests

        resp = requests.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {key}"},
            files={"file": ("speech.wav", wav, "audio/wav")},
            data={"model": GROQ_STT_MODEL, "response_format": "json"},
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"[voice] Groq STT HTTP {resp.status_code}: {resp.text[:200]}", flush=True)
            return None
        return (resp.json().get("text") or "").strip()
    except Exception as exc:
        print(f"[voice] Groq STT failed: {exc}", flush=True)
        return None


class Recorder:
    """Manual start/stop mic recorder for push-to-talk (hold a key to record).

    Call start() when the key goes down and stop() when it's released; stop()
    returns the captured audio as WAV bytes (b'' if nothing/unavailable).
    """

    def __init__(self, sample_rate: int = _STT_SAMPLE_RATE):
        self._sr = sample_rate
        self._frames: list[bytes] = []
        self._stream = None
        self._level = 0.0  # smoothed mic level 0..1 for the live waveform

    def level(self) -> float:
        """Current smoothed mic loudness (0..1) — drives the listening waveform."""
        return self._level

    def start(self) -> bool:
        try:
            import numpy as np
            import sounddevice as sd
        except Exception as exc:
            print(f"[voice] mic capture unavailable: {exc}", flush=True)
            return False
        self._frames = []

        def _cb(indata, _frames, _time, _status):
            raw = bytes(indata)
            self._frames.append(raw)
            # Track a smoothed loudness level for the reactive waveform.
            try:
                arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
                if arr.size:
                    rms = float(np.sqrt(np.mean(arr * arr)))
                    lvl = min(1.0, rms / 6000.0)  # ~speech RMS → full scale
                    # Fast attack, slower release so it feels lively but smooth.
                    if lvl > self._level:
                        self._level = lvl
                    else:
                        self._level = self._level * 0.8 + lvl * 0.2
            except Exception:
                pass

        try:
            self._stream = sd.RawInputStream(
                samplerate=self._sr, channels=1, dtype="int16", callback=_cb
            )
            self._stream.start()
            return True
        except Exception as exc:
            print(f"[voice] recording failed to start: {exc}", flush=True)
            self._stream = None
            return False

    def stop(self) -> bytes:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if not self._frames:
            return b""
        return _pcm_to_wav(b"".join(self._frames), self._sr)


# Soft, musical cue tones (Hz, ms). Played as smooth sine chimes — NOT the harsh
# square-wave winsound.Beep, which sounded like an old PC speaker. ORYNN_CUES=0
# disables them entirely.
# Notes are (freq_hz, decay_ms) or (freq_hz, decay_ms, start_ms) — with start
# offsets the notes OVERLAP and ring into each other like a soft bell/marimba
# (the Alexa earcon family), instead of beeping strictly in sequence.
_CUE_NOTES = {
    # Wake — "hey jarvis" heard, the bar rises: a warm rising major sixth that
    # blooms and rings out, "I'm listening". Long decays overlap into a chord.
    "wake": [(523.25, 700, 0), (880.0, 1100, 160)],           # C5 → A5
    # Sleep — the session fades away: soft falling third dissolving into a low
    # root, final but gentle.
    "sleep": [(659.25, 650, 0), (523.25, 700, 170), (392.0, 1200, 340)],  # E5→C5→G4
    # Reminder — Orynn woke ITSELF: a distinct rising major-triad arpeggio that
    # rings into one chord (doorbell-ish), never confused with wake/sleep.
    "reminder": [(523.25, 900, 0), (659.25, 900, 150), (783.99, 1300, 300)],
    "start": [(659.25, 500, 0)],                          # gentle single "ready"
    "stop": [],                                           # silent — waveform shows it
    "cancel": [(587.33, 450, 0), (440.0, 700, 140)],      # soft falling fourth
    "done": [(659.25, 500, 0), (1046.5, 950, 130)],       # bright rising octave-ish
    "error": [(415.3, 750, 0)],                           # single soft low tone
    "fail": [(466.16, 550, 0), (349.23, 900, 160)],       # soft falling, minor feel
}
_CUE_CACHE: dict[str, bytes] = {}
_CUE_SR = 44100                       # must match _chime_wav's sample rate
_CUE_FRAME_MS = 30                    # envelope frame ≈ glow tick (30fps)
_CUE_ENV_CACHE: dict[str, list[float]] = {}
_cue_listener = None                  # fn(kind, level 0..1) per frame; fn(kind, None) at end


def set_cue_listener(fn) -> None:
    """Register a callback that receives each chime's amplitude envelope while
    it plays — fn(kind, level) every ~30ms, then fn(kind, None) when the sound
    ends. Lets the taskbar glow pulse in sync with the cue tones, so the chime
    looks like it comes FROM the bar."""
    global _cue_listener
    _cue_listener = fn


def _cue_envelope(wav: bytes, sr: int = _CUE_SR,
                  frame_ms: int = _CUE_FRAME_MS) -> list[float]:
    """Per-frame RMS envelope of a 16-bit mono WAV, normalized to 0..1 with a
    gentle power curve so quiet ring-out tails still read visually."""
    import numpy as np

    pcm = np.frombuffer(wav[44:], dtype="<i2").astype(np.float64)
    if pcm.size == 0:
        return []
    n = max(1, int(sr * frame_ms / 1000))
    pad = (-pcm.size) % n
    if pad:
        pcm = np.concatenate([pcm, np.zeros(pad)])
    rms = np.sqrt(np.mean(pcm.reshape(-1, n) ** 2, axis=1))
    peak = float(rms.max()) or 1.0
    return [float(min(1.0, (r / peak) ** 0.7)) for r in rms]


def _chime_wav(notes, volume: float = 0.16, sr: int = 44100) -> bytes:
    """Render notes into one WAV as a soft, glassy bell (marimba/celesta family).

    Per note: a slightly detuned pair of fundamentals (natural chorus 'shimmer'),
    a quiet octave partial that decays FASTER than the fundamental (real struck
    bells lose their brightness first), and a whisper of a 12th for glass. The
    attack is a smooth 18 ms half-cosine bloom — no click — and the tail is a
    long exponential ring-down eased to true silence. Notes with start offsets
    are MIXED (overlapping); legacy 2-tuples play in sequence."""
    import numpy as np

    if not notes:
        return _pcm_to_wav(b"\x00\x00", sr)
    norm = []
    cursor = 0
    for note in notes:
        if len(note) == 3:
            freq, ms, start = note
        else:
            freq, ms = note
            start = cursor
            cursor += ms
        norm.append((float(freq), int(ms), int(start)))
    total_ms = max(start + ms for _f, ms, start in norm) + 120
    out = np.zeros(int(sr * total_ms / 1000) + 1, dtype=np.float64)
    for freq, ms, start in norm:
        n = max(1, int(sr * ms / 1000))
        t = np.arange(n) / sr
        dur = max(0.08, ms / 1000.0)
        # Ring-downs: octave partial fades ~2.4x faster than the fundamental,
        # so each note starts bright and melts into a pure warm tone.
        env_f = np.exp(-t * (5.0 / dur))
        env_o = np.exp(-t * (12.0 / dur))
        # Detuned fundamental pair → gentle chorus beat instead of a static sine.
        sig = (0.55 * np.sin(2 * np.pi * freq * 0.9990 * t)
               + 0.55 * np.sin(2 * np.pi * freq * 1.0012 * t)) * env_f
        sig += 0.22 * np.sin(2 * np.pi * freq * 2.0 * t) * env_o        # octave
        sig += 0.07 * np.sin(2 * np.pi * freq * 3.0 * t) * env_o        # 12th
        # Smooth half-cosine bloom (no click), and ease the very end to zero.
        attack = max(1, int(sr * 0.018))
        ramp = 0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, min(attack, n)))
        sig[: ramp.size] *= ramp
        tail = max(1, int(sr * 0.030))
        if n > tail:
            sig[-tail:] *= np.linspace(1.0, 0.0, tail)
        i0 = int(sr * start / 1000)
        seg = sig[: max(0, out.size - i0)]
        out[i0:i0 + seg.size] += seg
    # Soft-knee saturation rounds any overlap peaks, then normalize.
    out = np.tanh(out * 1.2) / 1.2
    peak = float(np.max(np.abs(out))) or 1.0
    out *= volume / max(1.0, peak / 0.98)
    pcm = (np.clip(out, -1, 1) * 32767).astype("<i2").tobytes()
    return _pcm_to_wav(pcm, sr)


def cue(kind: str) -> None:
    """Play a soft, non-blocking audio chime for voice feedback. Unknown kinds and
    ORYNN_CUES=0 are no-ops."""
    cues_env = (os.environ.get("ORYNN_CUES") or "1").strip().lower()
    notes = _CUE_NOTES.get(kind)
    if cues_env in ("0", "false", "no"):
        return
    if not notes:
        return

    def _play() -> None:
        try:
            import winsound

            data = _CUE_CACHE.get(kind)
            if data is None:
                data = _chime_wav(notes)
                _CUE_CACHE[kind] = data
            listener = _cue_listener
            if listener is not None:
                env = _CUE_ENV_CACHE.get(kind)
                if env is None:
                    env = _cue_envelope(data)
                    _CUE_ENV_CACHE[kind] = env

                def _pulse(env=env) -> None:
                    try:
                        t0 = time.monotonic()
                        for i, lvl in enumerate(env):
                            listener(kind, lvl)
                            # Pace against the wall clock so the glow stays in
                            # sync with playback instead of drifting.
                            time.sleep(max(
                                0.0,
                                t0 + (i + 1) * (_CUE_FRAME_MS / 1000.0)
                                - time.monotonic(),
                            ))
                        listener(kind, None)
                    except Exception:
                        pass

                threading.Thread(target=_pulse, daemon=True).start()
            # SND_ASYNC is invalid with SND_MEMORY (winsound raises "Cannot play
            # asynchronously from memory"); we're on a worker thread anyway, so
            # blocking playback here keeps the app non-blocking.
            winsound.PlaySound(data, winsound.SND_MEMORY)
        except Exception:
            pass

    threading.Thread(target=_play, daemon=True).start()


def wav_seconds(wav: bytes) -> float:
    """Approximate duration of a 16-bit mono WAV produced by this module."""
    if not wav or len(wav) <= 44:
        return 0.0
    return (len(wav) - 44) / 2 / float(_STT_SAMPLE_RATE)


def _listen_groq(timeout: float) -> str | None:
    """Transcribe one utterance via Groq Whisper. Returns the transcript, '' on
    no-speech, or None if Groq STT is unavailable (no key/mic) or the call fails
    (so the caller can fall back to the Windows recognizers)."""
    if not _groq_key():
        return None
    wav = _record_utterance(timeout)
    if wav is None:
        return None
    return transcribe_wav(wav)


_WINRT_DEAD = False   # latched when WinRT fails with a permanent error


def _listen_winrt(timeout: float) -> str | None:
    """One dictation utterance via the modern Windows recognizer. Returns the
    transcript, '' on no-speech, or None if the engine is unavailable.

    Permanent failures are LATCHED: 0x80045509 means the Windows 'Online speech
    recognition' privacy toggle is off — retrying every wake cycle just burned
    time before each fallback and spammed the log."""
    global _WINRT_DEAD
    if _WINRT_DEAD:
        return None
    import asyncio

    async def _run() -> str:
        import winsdk.windows.media.speechrecognition as sr
        recognizer = sr.SpeechRecognizer()
        # default constraints = free-form dictation
        await recognizer.compile_constraints_async()
        try:
            recognizer.timeouts.babble_timeout = _td(timeout)
            recognizer.timeouts.end_silence_timeout = _td(1.2)
        except Exception:
            pass
        result = await recognizer.recognize_async()
        try:
            # 0 = Success
            status = int(result.status)
        except Exception:
            status = 0
        return result.text if status == 0 else ""

    try:
        return asyncio.run(_run())
    except Exception as exc:
        msg = str(exc)
        if "-2147199735" in msg or "80045509" in msg.lower():
            # Privacy toggle off — permanent for this session. Say WHY, once,
            # with the actual fix, then stop retrying.
            _WINRT_DEAD = True
            print("[voice] WinRT speech is blocked by Windows privacy settings "
                  "(Settings > Privacy & security > Speech > enable 'Online "
                  "speech recognition'). Using SAPI/Groq fallback for the wake "
                  "word instead.", flush=True)
        else:
            print(f"[voice] WinRT STT failed: {exc}", flush=True)
        return None


def _td(seconds: float):
    """python float seconds -> WinRT TimeSpan (datetime.timedelta works)."""
    import datetime
    return datetime.timedelta(seconds=max(0.1, float(seconds)))


def _listen_sapi(timeout: float) -> str:
    """Fallback: classic SAPI in-proc dictation, polled for `timeout` seconds."""
    import pythoncom
    pythoncom.CoInitialize()
    text = ""
    try:
        import comtypes.client as cc
        rec = cc.CreateObject("SAPI.SpInProcRecognizer")
        ctx = rec.CreateRecoContext()
        grammar = ctx.CreateGrammar()
        grammar.DictationSetState(1)
        start = time.time()
        while time.time() - start < timeout:
            try:
                ev = ctx.WaitForNotifyEvent(200)
                if ev and getattr(ev, "Result", None):
                    text += " " + ev.Result.PhraseInfo.GetText()
            except Exception:
                pass
        grammar.DictationSetState(0)
    except Exception as exc:
        print(f"[voice] SAPI STT failed: {exc}", flush=True)
    return text.strip()


def listen(timeout: float = 8.0) -> str:
    """Capture one spoken utterance and return the transcript ('' if none).
    Blocking — call from a worker thread. Tries Groq Whisper first (when
    GROQ_API_KEY + mic are available), then the modern Windows recognizer,
    then classic SAPI."""
    out = _listen_groq(timeout)
    if out is not None:
        return out
    out = _listen_winrt(timeout)
    if out is not None:
        return (out or "").strip()
    return _listen_sapi(timeout)


# Common ways a general recognizer mangles the made-up name "Orynn" (it isn't a
# dictionary word, so Whisper/WinRT guess at it). Used for wake-word matching.
_WAKE_VARIANTS = {
    "orynn", "oryn", "orinn", "orin", "oren", "oran", "orrin",
    "auryn", "aurin", "oryan",
}


def matches_wake_word(transcript: str, wake: str = "") -> bool:
    """True if the transcript contains the wake word (default 'Orynn'), tolerant of
    how a general recognizer mishears a made-up name. Set ORYNN_WAKE_WORD to a word
    your recognizer hears reliably if 'Orynn' is flaky."""
    import re
    import difflib

    wake = (wake or os.environ.get("ORYNN_WAKE_WORD") or "orynn").lower().strip()
    text = (transcript or "").lower()
    if not text or not wake:
        return False
    if wake in text:
        return True
    variants = _WAKE_VARIANTS if wake == "orynn" else {wake}
    for w in re.findall(r"[a-z']+", text):
        if w in variants:
            return True
        if difflib.SequenceMatcher(None, w, wake).ratio() >= 0.82:
            return True
    return False


_OWW_MODEL = None   # cached openwakeword model (loads once)
_OWW_DEAD = False   # latched when openwakeword can't load — don't retry every cycle


def _listen_openwakeword(timeout: float) -> str | None:
    """Dedicated keyword-spotting wake engine (opt-in: ORYNN_WAKE_ENGINE=openwakeword).
    Streams the mic through a local openWakeWord model — sub-second, fully offline,
    far more reliable than general STT for a fixed phrase. Default model is the
    pretrained 'hey_jarvis' (override ORYNN_OWW_MODELS with comma-separated names or
    paths, e.g. a custom-trained 'orynn' model). Returns the configured wake word on
    detection (so matches_wake_word passes), '' on timeout, None if unavailable."""
    global _OWW_MODEL, _OWW_DEAD
    if _OWW_DEAD:
        return None
    try:
        import sounddevice as sd
        if _OWW_MODEL is None:
            from openwakeword.model import Model
            names = [n.strip() for n in
                     (os.environ.get("ORYNN_OWW_MODELS") or "hey_jarvis").split(",")
                     if n.strip()]
            # onnx by default: tflite-runtime has no Windows wheels, so the
            # openwakeword default framework would fail here.
            framework = (os.environ.get("ORYNN_OWW_FRAMEWORK") or "onnx").strip()
            _OWW_MODEL = Model(wakeword_models=names, inference_framework=framework)
    except Exception:
        _OWW_DEAD = True
        return None
    try:
        threshold = float(os.environ.get("ORYNN_OWW_THRESHOLD") or "0.5")
    except Exception:
        threshold = 0.5
    deadline = time.time() + max(1.0, timeout)
    hit = False
    try:
        with sd.InputStream(samplerate=16000, channels=1, dtype="int16",
                            blocksize=1280) as stream:
            while time.time() < deadline:
                data, _overflow = stream.read(1280)
                frame = data[:, 0] if getattr(data, "ndim", 1) > 1 else data
                scores = _OWW_MODEL.predict(frame)
                if any(float(v) >= threshold for v in scores.values()):
                    hit = True
                    break
    except Exception:
        return None
    finally:
        try:
            _OWW_MODEL.reset()
        except Exception:
            pass
    if hit:
        return (os.environ.get("ORYNN_WAKE_WORD") or "orynn").strip().lower()
    return ""


def listen_for_wake(timeout: float = 5.0) -> str:
    """One utterance for wake-word listening. Prefers OFFLINE recognizers (WinRT,
    then SAPI) so ambient listening costs no Groq quota and stays local; only falls
    back to Groq if no offline engine works. Returns a lowercase transcript ('' if
    nothing was said or no engine is available).

    ORYNN_WAKE_ENGINE=openwakeword switches to a dedicated local keyword-spotting
    model instead — much lower latency and fewer misses than STT-in-windows."""
    engine = (os.environ.get("ORYNN_WAKE_ENGINE") or "").strip().lower()
    if engine in ("oww", "openwakeword"):
        out = _listen_openwakeword(timeout)
        if out is not None:
            return out
    try:
        out = _listen_winrt(timeout)
        if out is not None:
            return (out or "").strip().lower()
    except Exception:
        pass
    try:
        out = _listen_sapi(timeout)
        if out:
            return out.strip().lower()
    except Exception:
        pass
    out = _listen_groq(timeout)
    return (out or "").strip().lower() if out is not None else ""

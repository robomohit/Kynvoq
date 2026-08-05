"""Taskbar voice glow — Orynn's ambient, no-text voice presence.

Instead of a floating textbox that moves around and obscures the screen, the
voice interaction lives in the **taskbar itself**: a flowing multicolor light
that washes across the bar, brightest at the bottom edge, reacting to your voice
and to Orynn speaking — like Alexa's light ring, but it IS the taskbar.

HOW IT WORKS (the part that matters):
A plain always-on-top window renders BEHIND the shell taskbar (Shell_TrayWnd
sits in a special elevated z-band), so an overlay just floats above the bar —
wrong. Instead we create a raw Win32 **layered child window parented INTO the
taskbar** (`SetParent`/`CreateWindowEx(parent=Shell_TrayWnd)`), paint per-pixel
BGRA with `UpdateLayeredWindow`, and sink it to the BOTTOM of the taskbar's
children every frame so the icons stay on top and clearly visible. The gradient
then renders ON the taskbar surface, behind the icons. (Verified on a real
Windows 11 taskbar.)

States (set via `set_state`):
  - "idle"      : slow, dim multicolor breathing (Orynn is awake / waiting).
  - "listening" : cool palette (blue → cyan → violet); brightness + amplitude
                  react to the live mic level (`set_audio_level`).
  - "thinking"  : a traveling shimmer sweeping across the bar (working).
  - "speaking"  : warm multicolor flow (teal → green → amber); reacts to the
                  AI's output so the bar "talks back".

Pure Python + ctypes (no extra deps, no DLL injection). A QTimer drives the
animation on the Qt event loop, so it lives happily inside the overlay process.
On non-Windows / if the taskbar can't be found, it silently no-ops.
"""
from __future__ import annotations

import ctypes
import math
import os
import time
from ctypes import wintypes

import numpy as np

from PySide6.QtCore import QObject, QTimer

# ── Win32 plumbing ────────────────────────────────────────────────────────────
try:
    _u = ctypes.windll.user32
    _gdi = ctypes.windll.gdi32
    _k32 = ctypes.windll.kernel32
    _HAVE_WIN = True
except Exception:  # pragma: no cover — non-Windows
    _HAVE_WIN = False

if _HAVE_WIN:
    _u.DefWindowProcW.restype = ctypes.c_longlong
    _u.DefWindowProcW.argtypes = [wintypes.HWND, ctypes.c_uint,
                                  ctypes.c_ulonglong, ctypes.c_longlong]
    _u.CreateWindowExW.restype = wintypes.HWND
    _u.FindWindowW.restype = wintypes.HWND
    _u.GetParent.restype = wintypes.HWND

WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
HWND_BOTTOM = 1
HWND_TOPMOST = -1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040


def _now_ms() -> int:
    return int(time.monotonic() * 1000)


def _envf(name: str, default: float) -> float:
    """Read a float tunable from the environment (for live look-tuning without
    editing code — just set the var and restart)."""
    try:
        v = os.environ.get(name)
        return float(v) if v not in (None, "") else default
    except Exception:
        return default


def taskbar_rect() -> tuple[int, int, int, int] | None:
    """(x, y, w, h) of the primary Windows taskbar in physical pixels, or None."""
    if not _HAVE_WIN:
        return None
    try:
        hwnd = _u.FindWindowW("Shell_TrayWnd", None)
        if not hwnd:
            return None
        r = wintypes.RECT()
        _u.GetWindowRect(hwnd, ctypes.byref(r))
        w, h = r.right - r.left, r.bottom - r.top
        if w <= 0 or h <= 0:
            return None
        return (r.left, r.top, w, h)
    except Exception:
        return None


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32)]


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
                ("SourceConstantAlpha", ctypes.c_byte), ("AlphaFormat", ctypes.c_byte)]


# Keep a module-ref to the WNDPROC so it isn't garbage-collected (crash otherwise).
_WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, ctypes.c_uint,
                              ctypes.c_ulonglong, ctypes.c_longlong) if _HAVE_WIN else None
_wndproc_ref = None
_class_registered = False


def _ensure_class() -> bool:
    global _wndproc_ref, _class_registered
    if not _HAVE_WIN:
        return False
    if _class_registered:
        return True

    def _proc(h, m, w, l):
        return _u.DefWindowProcW(h, m, w, l)

    _wndproc_ref = _WNDPROC(_proc)

    class _WC(ctypes.Structure):
        _fields_ = [("style", ctypes.c_uint), ("proc", _WNDPROC),
                    ("ce", ctypes.c_int), ("we", ctypes.c_int),
                    ("inst", wintypes.HINSTANCE), ("ico", wintypes.HICON),
                    ("cur", wintypes.HANDLE), ("bg", wintypes.HBRUSH),
                    ("menu", wintypes.LPCWSTR), ("cls", wintypes.LPCWSTR)]

    wc = _WC()
    wc.proc = _wndproc_ref
    wc.inst = _k32.GetModuleHandleW(None)
    wc.cls = "OrynnTaskbarGlow"
    _u.RegisterClassW(ctypes.byref(wc))
    _class_registered = True
    return True


class TaskbarGlow(QObject):
    """Sound-reactive multicolor glow painted INTO the Windows taskbar."""

    TICK_MS = 33  # ~30fps — plenty smooth for a glow, light on CPU

    # State color stops as HSV hues (0..1); the bar flows through these.
    # The four VOICE states share one cohesive cyan→blue "assistant" glow (the
    # golden look) — their state is shown by brightness and motion. The STATUS
    # states carry their own color, because they're the silent channel: when a
    # scheduled task runs at 3am there's no voice, the bar's COLOR is how you
    # know what Orynn is doing. Color changes crossfade smoothly in _tick.
    _PALETTE = [0.50, 0.55, 0.60, 0.53]        # cyan → blue, gentle flow
    _WORKING = [0.72, 0.76, 0.80, 0.75]        # violet — "AI at work"
    _GREEN = [0.30, 0.34, 0.38, 0.33]          # soft green — reminder/success
    _RED = [0.97, 0.005, 0.03, 0.99]           # light red — something failed
    _AMBER = [0.075, 0.095, 0.115, 0.09]       # amber — "worth a glance"
    PALETTES = {
        "idle": _PALETTE,
        "listening": _PALETTE,
        "thinking": _PALETTE,
        "speaking": _PALETTE,
        "working": _WORKING,     # background task running (silent presence)
        "reminder": _GREEN,      # scheduled reminder being announced
        "success": _GREEN,       # brief done-flash, auto-reverts
        "error": _RED,           # brief fail-flash, auto-reverts
        "attention": _AMBER,     # watcher ping — glance when you feel like it
    }
    # States whose color is the base (env-tunable) voice palette.
    _VOICE_STATES = ("idle", "listening", "thinking", "speaking")
    # Transient status flashes: auto-revert after this many seconds.
    # Attention is the bottom rung of the awareness ladder: it lingers a little
    # longer than a done-flash (the user may not be looking), then lets go —
    # an unglanced amber ping must never become a permanent nag.
    _TRANSIENT_S = {"success": 3.0, "error": 6.0, "attention": 8.0}

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ok = _HAVE_WIN and _ensure_class()
        self._hwnd = None
        self._tb = None
        self._x = 0
        self._y = 0
        self._w = 0
        self._h = 0

        self._state = "idle"
        self._audio_level = 0.0
        self._level_smooth = 0.0
        self._flow_smooth = 0.0   # slow envelope driving the water's flow speed
        self._wt = 0.0            # integrated wave-time (flow position)
        self._cleared = False     # pushed a transparent frame while hidden
        self._phase = 0.0
        self._sweep = 0.0
        self._intensity = 0.0
        # Hotspot = the bright "where the sound is coming from" segment, 0..1
        # across the bar (0=left, 0.5=center, 1=right). _hotspot is the smoothed
        # rendered position; _hotspot_target is where it's heading.
        self._hotspot = 0.5
        self._hotspot_target = 0.5
        self._direction_locked = False   # True once real DOA data drives it
        # Bar hidden until woken ("hey jarvis"); fades out after silence.
        self._visible = False

        # ── LOOK TUNABLES (set env vars + restart to dial in your taste) ──────
        #   ORYNN_GLOW_BRIGHT   overall brightness      (default 1.0)
        #   ORYNN_GLOW_HEIGHT   wave/crest height       (default 1.0)
        #   ORYNN_GLOW_SPEED    motion / flow speed     (default 1.0)
        #   ORYNN_GLOW_HUE      base color hue 0..1     (0.5=cyan .55=blue
        #                       .33=green .0=red .8=violet; default = palette)
        self._t_bright = max(0.2, _envf("ORYNN_GLOW_BRIGHT", 1.0))
        self._t_height = max(0.2, _envf("ORYNN_GLOW_HEIGHT", 1.0))
        self._t_speed = max(0.1, _envf("ORYNN_GLOW_SPEED", 1.0))
        hue = _envf("ORYNN_GLOW_HUE", -1.0)
        if 0.0 <= hue <= 1.0:
            # Re-center the VOICE palette on the chosen hue, keeping the gentle
            # spread. Status colors (working/reminder/error) are semantic and
            # stay fixed — they must always mean the same thing.
            self._base_palette = [hue - 0.03, hue + 0.02, hue + 0.05, hue]
        else:
            self._base_palette = list(self._PALETTE)
        # _palette = the stops currently RENDERED; _tick eases them toward the
        # active state's stops so color changes melt instead of snapping.
        self._palette = list(self._base_palette)
        # Transient-state bookkeeping (success/error auto-revert).
        self._revert_state: str | None = None
        self._revert_at_ms: int | None = None

        # Precompute the horizontal color ramp once per frame (cached per width).
        self._ramp_cache_w = 0
        self._ramp: list[tuple[int, int, int]] = []

        if self._ok:
            self._create_window()

        self._timer = QTimer(self)
        self._timer.setInterval(self.TICK_MS)
        self._timer.timeout.connect(self._tick)
        if self._ok:
            self._timer.start()

        # Re-find the taskbar / re-sink periodically (resolution change, explorer
        # restart, taskbar move).
        self._geo_timer = QTimer(self)
        self._geo_timer.setInterval(1500)
        self._geo_timer.timeout.connect(self._resync)
        if self._ok:
            self._geo_timer.start()

    # ── public API (mirrors the old overlay so wiring is a drop-in) ───────────
    def set_state(self, state: str) -> None:
        if state not in self.PALETTES:
            state = "idle"
        if state in self._TRANSIENT_S:
            # Success/error are FLASHES: remember what to go back to. A finished
            # background task reverts to idle (the work is over), anything else
            # (e.g. flash while a live session listens) restores that state.
            if self._state not in self._TRANSIENT_S:
                self._revert_state = ("idle" if self._state == "working"
                                      else self._state)
            self._revert_at_ms = _now_ms() + int(self._TRANSIENT_S[state] * 1000)
        else:
            self._revert_state = None
            self._revert_at_ms = None
        self._state = state
        if state not in ("listening", "speaking", "reminder"):
            self._audio_level = 0.0

    def _palette_target(self) -> list[float]:
        """Hue stops the current state wants: voice states use the (env-tunable)
        base palette; status states use their fixed semantic colors."""
        if self._state in self._VOICE_STATES:
            return self._base_palette
        return self.PALETTES.get(self._state, self._base_palette)

    def set_cursor_state(self, state: str) -> None:
        self.set_state(state if state in self.PALETTES else "idle")

    def set_audio_level(self, level: float) -> None:
        # Audio arrives faster (~50/s) than we render (~30fps), so keep the PEAK
        # since the last frame — otherwise fast syllable spikes get dropped and
        # the speech rhythm washes out. _tick() consumes and resets it.
        try:
            v = max(0.0, min(1.0, float(level)))
        except Exception:
            v = 0.0
        self._audio_level = max(self._audio_level, v)

    def set_direction(self, pos: float) -> None:
        """Point the bright hotspot toward where the sound is coming from.
        `pos` is 0..1 across the bar (0=left, 0.5=center, 1=right) — e.g. from
        stereo mic L/R balance or a mic-array DOA estimate. The segment eases to
        this position so it tracks the speaker like an Echo's cyan segment."""
        try:
            self._hotspot_target = max(0.0, min(1.0, float(pos)))
            self._direction_locked = True
        except Exception:
            pass

    def set_speaking(self, on: bool) -> None:
        self.set_state("speaking" if on else "idle")

    def set_visible(self, on: bool) -> None:
        """Show/hide the bar. On wake ('hey jarvis') → fade in; after a stretch
        of silence → fade out so the taskbar is clean when Orynn isn't engaged.
        The fade is handled in _tick via _visible gating the master intensity."""
        self._visible = bool(on)

    def show(self) -> None:
        """Compatibility no-op: the layered child is shown on creation."""
        if self._ok and self._hwnd:
            try:
                _u.ShowWindow(self._hwnd, 5)  # SW_SHOW
            except Exception:
                pass

    def stop(self) -> None:
        self._timer.stop()
        self._geo_timer.stop()
        if self._hwnd:
            try:
                _u.DestroyWindow(self._hwnd)
            except Exception:
                pass
            self._hwnd = None

    # ── window lifecycle ──────────────────────────────────────────────────────
    def _create_window(self) -> None:
        rect = taskbar_rect()
        if rect is None:
            self._ok = False
            return
        x, y, w, h = rect
        self._tb = _u.FindWindowW("Shell_TrayWnd", None)
        self._x, self._y, self._w, self._h = x, y, w, h
        # TOP-LEVEL layered popup positioned over the taskbar. UpdateLayeredWindow
        # is only reliable on top-level windows (it often silently no-ops on a
        # WS_CHILD), which is why the child approach rendered nothing on some
        # Win11 builds. WS_EX_TOOLWINDOW keeps it off alt-tab/taskbar; the
        # taskbar is set as OWNER so it tracks/cleans up with the shell. We then
        # re-assert TOPMOST every frame to sit above the taskbar surface.
        self._hwnd = _u.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE
            | WS_EX_TOOLWINDOW | WS_EX_TOPMOST,
            "OrynnTaskbarGlow", "",
            WS_POPUP | WS_VISIBLE,
            x, y, w, h,
            self._tb, None, _k32.GetModuleHandleW(None), None,
        )
        if not self._hwnd:
            self._ok = False
            return
        # Lift above the taskbar without activating.
        _u.SetWindowPos(self._hwnd, HWND_TOPMOST, x, y, w, h,
                        SWP_NOACTIVATE | SWP_SHOWWINDOW)

    def _resync(self) -> None:
        """Keep the glow alive and correctly sized across taskbar changes:
        resolution change, taskbar move, or an explorer.exe restart (which
        destroys Shell_TrayWnd and our child with it, and creates a new one)."""
        rect = taskbar_rect()
        if rect is None:
            return
        x, y, w, h = rect
        cur_tb = _u.FindWindowW("Shell_TrayWnd", None)
        # Our window died (explorer restart) or the taskbar handle changed →
        # recreate the child under the new taskbar.
        if (not self._hwnd or not _u.IsWindow(self._hwnd)
                or cur_tb != self._tb):
            try:
                if self._hwnd and _u.IsWindow(self._hwnd):
                    _u.DestroyWindow(self._hwnd)
            except Exception:
                pass
            self._hwnd = None
            self._create_window()
            return
        # Compare against where the window ACTUALLY is, not just our stored
        # values — DWM/shell can move a popup out from under us (fullscreen
        # transitions, taskbar slide animations), and trusting the cache left
        # the glow stranded mid-screen with the rail nowhere near the bar edge.
        try:
            wr = wintypes.RECT()
            _u.GetWindowRect(self._hwnd, ctypes.byref(wr))
            actual = (wr.left, wr.top, wr.right - wr.left, wr.bottom - wr.top)
        except Exception:
            actual = None
        if actual != (x, y, w, h) or \
                (x, y, w, h) != (self._x, self._y, self._w, self._h):
            self._x, self._y, self._w, self._h = x, y, w, h
            _u.SetWindowPos(self._hwnd, HWND_TOPMOST, x, y, w, h,
                            SWP_NOACTIVATE)

    # ── animation ──────────────────────────────────────────────────────────────
    def _tick(self) -> None:
        if not self._ok or not self._hwnd:
            return
        # Transient success/error flash has run its course → ease back.
        if self._revert_at_ms is not None and _now_ms() >= self._revert_at_ms:
            self.set_state(self._revert_state or "idle")
        # Crossfade the rendered hue stops toward the state's palette (wrap-aware
        # shortest path, like _hue_ramp) so color changes melt, never snap.
        target = self._palette_target()
        for i in range(len(self._palette)):
            d = ((target[i] - self._palette[i] + 0.5) % 1.0) - 0.5
            self._palette[i] = (self._palette[i] + d * 0.10) % 1.0

        active = self._state in ("listening", "speaking", "reminder",
                                 "success", "error")

        lvl_raw = self._audio_level if active else 0.0
        if self._state == "working":
            # No audio to react to while Orynn works in the background — give
            # the bar a slow autonomous pulse so it visibly "works" in silence.
            lvl_raw = 0.18 + 0.14 * (0.5 + 0.5 * math.sin(_now_ms() / 850.0))
        elif self._state == "attention":
            # Quicker heartbeat than "working": a ping, not a hum.
            lvl_raw = 0.22 + 0.16 * (0.5 + 0.5 * math.sin(_now_ms() / 550.0))
        self._audio_level = 0.0   # consume the per-frame peak (see set_audio_level)
        # TWO envelopes from the same voice level, for two different jobs:
        #  - _level_smooth (fast attack / medium release) drives the wave HEIGHT
        #    → responsive: crests rise on each phrase and ease back down.
        #  - _flow_smooth (slow both ways) drives the water's FLOW SPEED
        #    → the current accelerates gracefully when there's voice and glides
        #    back to near-still in silence. Loud voice = faster water.
        if lvl_raw > self._level_smooth:
            self._level_smooth += (lvl_raw - self._level_smooth) * 0.50
        else:
            self._level_smooth += (lvl_raw - self._level_smooth) * 0.12
        self._flow_smooth += (lvl_raw - self._flow_smooth) * \
            (0.10 if lvl_raw > self._flow_smooth else 0.04)
        lvl = self._level_smooth

        # FLOW = integrated wave-time. The earlier "speed follows loudness"
        # attempt was jerky because the phase used ABSOLUTE time × speed — any
        # speed change teleported the phase. Integrating speed (accumulate
        # dt × current_speed) makes loudness smoothly ACCELERATE the flow with
        # zero jumps: still water in silence, streaming water while talking.
        dt = self.TICK_MS / 1000.0
        flow_speed = (0.25 + 3.2 * self._flow_smooth) * self._t_speed
        self._wt += dt * flow_speed
        self._phase = (self._phase + 0.0035 * self._t_speed) % 1.0

        # Skip painting entirely while hidden and fully faded — near-zero CPU
        # when Orynn is asleep (the practical default state).
        if not self._visible and self._intensity < 0.01:
            if not self._cleared:
                self._push_clear()
                self._cleared = True
            return
        self._cleared = False

        # Bright when engaged; fully faded out when not visible (not woken /
        # timed out) so the taskbar is clean until you say "hey jarvis".
        if self._visible:
            target_i = {"idle": 0.95, "listening": 1.0, "thinking": 1.0,
                        "speaking": 1.0, "working": 1.0, "reminder": 1.0,
                        "success": 1.0, "error": 1.0,
                        "attention": 1.0}.get(self._state, 0.95)
        else:
            target_i = 0.0
        self._intensity += (target_i - self._intensity) * 0.16

        if self._state == "thinking":
            self._sweep = (self._sweep + 0.012) % 1.0
            # During thinking, the bright segment sweeps back and forth.
            self._hotspot_target = 0.5 + 0.42 * math.sin(_now_ms() / 700.0)
        elif self._state == "idle":
            # Gentle ambient drift so the resting bar feels alive.
            self._hotspot_target = 0.5 + 0.18 * math.sin(_now_ms() / 2600.0)
        elif not self._direction_locked:
            # Listening/speaking with no real DOA data: let the bright segment
            # breathe around center on a slow organic path so it feels alive and
            # "aimed" rather than frozen. set_direction() overrides this with real
            # positional data (stereo balance / mic array) when available.
            t = _now_ms()
            self._hotspot_target = 0.5 + 0.22 * math.sin(t / 1700.0) \
                + 0.10 * math.sin(t / 640.0)

        # Ease the hotspot toward its target so it glides, never jumps.
        self._hotspot += (self._hotspot_target - self._hotspot) * 0.18

        self._paint()
        # Re-assert TOPMOST so the glow stays composited over the taskbar (the
        # shell periodically reclaims top z). It's click-through (WS_EX_TRANSPARENT)
        # and translucent, so icons remain visible and clickable underneath.
        try:
            _u.SetWindowPos(self._hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        except Exception:
            pass

    # ── color ──────────────────────────────────────────────────────────────────
    def _hue_ramp(self, w: int) -> np.ndarray:
        """(w, 3) float RGB in 0..1 across the width, flowing with self._phase."""
        hues = self._palette   # tunable base palette (ORYNN_GLOW_HUE)
        stops = np.asarray(hues, dtype=np.float64)
        n = len(hues)
        t = np.linspace(0.0, 1.0, w, endpoint=False)
        pos = (t + self._phase) % 1.0
        fpos = pos * n
        i = np.floor(fpos).astype(int) % n
        j = (i + 1) % n
        frac = fpos - np.floor(fpos)
        h0 = stops[i]
        h1 = stops[j]
        dh = h1 - h0
        dh = np.where(dh > 0.5, dh - 1.0, dh)
        dh = np.where(dh < -0.5, dh + 1.0, dh)
        hue = (h0 + dh * frac) % 1.0
        sat = 0.88   # consistent rich saturation across all states
        # Vectorized HSV(h, sat, 1.0) → RGB.
        hp = hue * 6.0
        c = sat                      # since V=1, chroma = sat
        x = c * (1.0 - np.abs((hp % 2.0) - 1.0))
        m = 1.0 - c
        z = np.zeros_like(hue)
        seg = np.floor(hp).astype(int) % 6
        r = np.choose(seg, [c, x, z, z, x, c])
        g = np.choose(seg, [x, c, c, x, z, z])
        b = np.choose(seg, [z, z, x, c, c, x])
        return np.stack([r + m, g + m, b + m], axis=1)

    # ── paint ───────────────────────────────────────────────────────────────────
    def _paint(self) -> None:
        w, h = self._w, self._h
        if w <= 0 or h <= 0:
            return
        master = max(0.0, self._intensity)
        lvl = self._level_smooth                       # 0..1 smoothed voice level
        active = self._state in ("listening", "speaking", "reminder",
                                 "success", "error", "working")

        t = _now_ms() / 1000.0

        # ── LASER LINE ⇄ FLOWING WATER ──────────────────────────────────────
        # The unified design: in silence the bar is a calm, near-flat luminous
        # LINE (instantly readable — "I'm listening"); when there's voice, the
        # line melts into layered water whose HEIGHT rises with loudness and
        # whose FLOW SPEED is the integrated `self._wt` (loud = faster current,
        # accelerating smoothly, never jumping). Icons stay readable via the
        # vertical dimming below.
        #
        # PERF: everything is computed at HALF horizontal resolution (the glow
        # is smooth gradients — invisible difference) and upscaled at the end;
        # this halves the per-frame cost so the animation never stutters.
        w2 = (w + 1) // 2
        rgb = self._hue_ramp(w2).astype(np.float32)    # (w2, 3) palette
        nx = np.linspace(-1.0, 1.0, w2, dtype=np.float32)

        # Smooth flat-top bell → clean tapered ends.
        atten = (1.0 / (1.0 + (2.4 * nx) ** 4)) ** 1.1        # (w2,)

        # Height: essentially the voice. Near-zero in silence (the flat laser
        # line, with only a faint slow breath so it never looks dead), rising
        # tall with loudness.
        breath = 0.07 + 0.03 * math.sin(t * 0.7)
        amp = breath + (0.95 * lvl if active else 0.0)
        amp = min(1.1, amp)

        yb = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, np.newaxis]  # (h,1)
        bottom = np.float32(1.0)
        # Crest travel: slim at silence (line), tall with voice (water).
        reach = min(0.75, (0.05 + 0.62 * amp) * self._t_height)
        thick = 0.075 + 0.06 * amp

        # Layers: (amp, spatial freq, wave-time mult, phase, brightness).
        # Flow position uses self._wt — integrated loudness-driven wave-time.
        layers = (
            (1.00, 2.6,  1.0, 0.0, 0.60),
            (0.74, 4.3, -1.3, 1.6, 0.42),
            (0.52, 6.1,  1.7, 3.4, 0.30),
        )
        glow = np.zeros((h, w2), dtype=np.float32)
        for a_mul, freq, wt_mul, ph, bright in layers:
            wave = np.sin(nx * freq * math.pi + self._wt * wt_mul + ph
                          + self._hotspot * 1.5)             # (w2,) -1..1
            crest_y = bottom - (0.5 + 0.5 * wave) * reach * a_mul * atten
            d = (yb - crest_y[np.newaxis, :])                # signed vert distance
            # Asymmetric falloff: crisper above the crest, softer below — smooth
            # ribbons with no seams.
            width = np.where(d < 0, thick * 0.55, thick * 1.25)
            ribbon = np.exp(-0.5 * (d / width) ** 2)
            glow += ribbon * bright * atten[np.newaxis, :]

        # Soft outer bloom rising from the base — the light radiates.
        bloom_top = bottom - (reach + 0.10)
        bd = np.clip((yb - bloom_top) / (bottom - bloom_top + 1e-3), 0.0, 1.0)
        glow += (bd * bd) * atten[np.newaxis, :] * (0.16 + 0.14 * amp)

        # The constant luminous RAIL on the bottom edge — this IS the laser line
        # when everything above it is flat.
        base = np.exp(-((yb - bottom) / 0.05) ** 2) * atten[np.newaxis, :] \
            * (0.72 + 0.28 * amp)
        glow = np.maximum(glow, base)

        # Icon-friendly vertical dimming: full strength at the bottom edge,
        # gently faded up where the icon glyphs sit.
        icon_dim = 0.22 + 0.78 * (yb ** 2.2)
        glow = glow * icon_dim

        # Crisp bright core (single cheap sharpen on the final array).
        glow = glow + 0.6 * (glow * glow)

        amap = np.clip(glow * master * self._t_bright, 0.0, 1.0)

        # Color + white lift at the brightest peaks, composed at half-res.
        col = np.broadcast_to(rgb[np.newaxis, :, :], (h, w2, 3)).copy()
        lift = np.clip((amap - 0.7) / 0.3, 0.0, 1.0)[..., np.newaxis] * 0.5
        col = col + (1.0 - col) * lift

        a8 = amap * 255.0
        out2 = np.empty((h, w2, 4), dtype=np.uint8)
        out2[..., 0] = (col[..., 2] * a8).astype(np.uint8)   # B (premultiplied)
        out2[..., 1] = (col[..., 1] * a8).astype(np.uint8)   # G
        out2[..., 2] = (col[..., 0] * a8).astype(np.uint8)   # R
        out2[..., 3] = a8.astype(np.uint8)
        # Upscale to full width (pixel-double, then trim odd widths).
        out = np.repeat(out2, 2, axis=1)[:, :w]

        self._push(np.ascontiguousarray(out).tobytes(), w, h)

    def _push_clear(self) -> None:
        """Push one fully-transparent frame (used when hidden, so we can stop
        painting entirely without leaving a stale image on the taskbar)."""
        w, h = self._w, self._h
        if w > 0 and h > 0:
            self._push(bytes(w * h * 4), w, h)

    def _push(self, bgra: bytes, w: int, h: int) -> None:
        scr = _u.GetDC(0)
        hdc = _gdi.CreateCompatibleDC(scr)
        bi = _BITMAPINFOHEADER()
        bi.biSize = ctypes.sizeof(bi)
        bi.biWidth = w
        bi.biHeight = -h          # top-down
        bi.biPlanes = 1
        bi.biBitCount = 32
        bi.biCompression = 0
        bits = ctypes.c_void_p()
        dib = _gdi.CreateDIBSection(hdc, ctypes.byref(bi), 0,
                                    ctypes.byref(bits), None, 0)
        old = _gdi.SelectObject(hdc, dib)
        ctypes.memmove(bits, bgra, len(bgra))
        bf = _BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        size = wintypes.SIZE(w, h)
        src = wintypes.POINT(0, 0)
        try:
            _u.UpdateLayeredWindow(self._hwnd, scr, None, ctypes.byref(size),
                                   hdc, ctypes.byref(src), 0,
                                   ctypes.byref(bf), ULW_ALPHA)
        finally:
            _gdi.SelectObject(hdc, old)
            _gdi.DeleteObject(dib)
            _gdi.DeleteDC(hdc)
            _u.ReleaseDC(0, scr)

"""Virtual cursor overlay — gives the user a smooth visual cue whenever the
agent clicks/types somewhere on screen.

Designed to feel like Clicky / Claude-Computer-Use cursors: the pointer
glides along a gentle bezier curve, leaves a fading dotted trail, sits
inside a soft accent glow halo, and gives a satisfying scale-pulse on
click. No abrupt jumps, no clipped straight lines.

  • Frameless always-on-top fully-transparent overlay spanning the virtual
    desktop. WA_TransparentForMouseEvents so it never blocks input.
  • show_click(x, y) animates the cursor along a quadratic bezier to the
    target, then plays a click pulse + ripple.
  • show_type(x, y, text) flashes a typewriter caret at the location with
    a small label showing the text being typed.

Call sites: qt_shell capsule, which polls agent action_start events and
forwards mouse_click / keyboard_type to this overlay.
"""
from __future__ import annotations

import math
import os
import re

from PySide6.QtCore import (Qt, QPoint, QPointF, QRect, QRectF, QTimer,
                             QPropertyAnimation, QEasingCurve, Property,
                             QObject)
from PySide6.QtGui import (QColor, QPainter, QPen, QBrush, QPainterPath,
                           QFont, QGuiApplication, QCursor)
from PySide6.QtWidgets import QWidget


# Tunable look
RIPPLE_COLOR = QColor(91, 224, 208)        # accent teal
COMPANION_BLUE = QColor(0x33, 0x80, 0xFF)  # legacy status bubble accent
CURSOR_COLOR = QColor(20, 24, 32, 235)     # near-black
CURSOR_OUTLINE = QColor(255, 255, 255, 240)
LABEL_BG = QColor(20, 24, 32, 220)
LABEL_FG = QColor(240, 242, 248, 245)

# Clicky-inspired dark-glass palette for the companion textbox (Farza's Clicky
# DesignSystem.swift). The bubble grows to fit wrapped text and carries an
# animated status dot, matching Clicky's floating response overlay.
DS_SURFACE = QColor(0x17, 0x19, 0x18)      # surface1 #171918
DS_BORDER = QColor(0x37, 0x3B, 0x39)       # borderSubtle #373B39
DS_TEXT = QColor(0xEC, 0xEE, 0xED)         # textPrimary #ECEEED
DS_BLUE = QColor(0x60, 0xA5, 0xFA)         # blue400 — listening/working
DS_GREEN = QColor(0x34, 0xD3, 0x99)        # success — idle/heard/done
DS_AMBER = QColor(0xFF, 0xB2, 0x24)        # warning — errors/cancel


class _Ripple:
    """A single expanding ring + filled dot for one click."""
    __slots__ = ("x", "y", "t", "duration_ms")

    def __init__(self, x: int, y: int, duration_ms: int = 600):
        self.x = x; self.y = y; self.t = 0.0; self.duration_ms = duration_ms

    def progress(self) -> float:
        return min(1.0, self.t / max(1, self.duration_ms))

    def alive(self) -> bool:
        return self.t < self.duration_ms


class _Caret:
    """Brief typewriter caret indicator at a position."""
    __slots__ = ("x", "y", "t", "duration_ms", "text")

    def __init__(self, x: int, y: int, text: str = "", duration_ms: int = 900):
        self.x = x; self.y = y; self.t = 0.0
        self.duration_ms = duration_ms
        self.text = (text or "")[:32]

    def alive(self) -> bool:
        return self.t < self.duration_ms


class _Spotlight:
    """A precise focus-ring around a real UIA control's bounds, with a label.
    This is the UIA analogue of the virtual mouse: instead of guessing a pixel
    and moving a cursor, UIA knows the control's EXACT rectangle, so we trace it
    directly — a snapping focus ring + glow + a 'what it's doing' label."""
    __slots__ = ("x", "y", "w", "h", "label", "kind", "t", "duration_ms")

    def __init__(self, x, y, w, h, label="", kind="click", duration_ms=2200):
        self.x = int(x); self.y = int(y)
        self.w = max(8, int(w)); self.h = max(8, int(h))
        self.label = (label or "")[:48]
        self.kind = kind                 # click | type | find
        self.t = 0.0
        self.duration_ms = duration_ms

    def alive(self) -> bool:
        return self.t < self.duration_ms

    def progress(self) -> float:
        return min(1.0, self.t / max(1, self.duration_ms))


class _AppGlow:
    """A breathing glow tracing the edges of the whole app window the agent is
    working in (brand-colour). Persistent: re-armed on each action, fades out
    after a short hold of inactivity."""
    __slots__ = ("x", "y", "w", "h", "label", "t0", "armed_until", "fade_ms")

    def __init__(self, x, y, w, h, label, now, hold_ms=3500, fade_ms=480):
        self.x = int(x); self.y = int(y); self.w = int(w); self.h = int(h)
        self.label = (label or "")[:48]
        self.t0 = now
        self.armed_until = now + hold_ms
        self.fade_ms = fade_ms

    def rearm(self, x, y, w, h, label, now, hold_ms=3500):
        self.x = int(x); self.y = int(y); self.w = int(w); self.h = int(h)
        if label:
            self.label = label[:48]
        self.armed_until = now + hold_ms

    def alive(self, now) -> bool:
        return now < self.armed_until + self.fade_ms


class VirtualCursorOverlay(QWidget):
    """Full-screen click-through overlay that paints animated agent activity."""

    TICK_MS = 16
    CURSOR_DECAY_MS = 2800  # how long the cursor stays after activity
    # Smooth motion tunables — slower + curvier than a linear lerp
    TRAVEL_BASE_MS = 360      # baseline travel time for short hops
    TRAVEL_PER_PX = 0.7       # extra ms per pixel of distance (cap below)
    TRAVEL_MAX_MS = 900       # maximum travel time
    TRAIL_LEN = 14            # how many breadcrumb dots to keep
    TRAIL_STRIDE_MS = 30      # how often to record a trail point
    GLOW_RADIUS = 26          # soft accent halo radius around the cursor
    CLICK_PULSE_MS = 320      # cursor scale pulse duration on click
    COMPANION_OFFSET_X = 35   # Clicky: buddyX = cursorX + 35
    COMPANION_OFFSET_Y = 25
    COMPANION_STIFFNESS = 0.30
    # Over-damped on purpose: with stiffness 0.30 the follow only overshoots
    # (i.e. bounces past the cursor and wobbles back) when damping is above
    # ~0.22. Keep it well below that so the bubble glides to the cursor and
    # settles without any spring/bounce.
    COMPANION_DAMPING = 0.0
    COMPANION_SNAP_DISTANCE = 900
    EXPAND_HOLD_MS = 10000  # collapse textbox → orb this long after last activity
    # Companion follow/bubble behavior adapted from
    # Bitshank-2338/clicky-windows ui/overlay.py, MIT License.

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.NoFocus)

        self._origin_x = 0
        self._origin_y = 0
        self._sync_virtual_geometry()

        self._ripples: list[_Ripple] = []
        self._carets: list[_Caret] = []
        self._spotlights: list[_Spotlight] = []
        self._app_glow: "_AppGlow | None" = None
        self._cursor_x = -100
        self._cursor_y = -100
        self._cursor_visible_until = 0  # epoch ms; 0 = hide
        self._click_pulse_start_ms = 0  # when last click happened

        # Bezier path animation toward the next target
        # Quadratic bezier: P0 (start) → P1 (control, off-line) → P2 (end)
        self._p0 = (-100, -100)
        self._p1 = (-100, -100)
        self._p2 = (-100, -100)
        self._anim_t = 1.0       # 0..1
        self._anim_duration_ms = self.TRAVEL_BASE_MS
        self._anim_elapsed_ms = self._anim_duration_ms

        # Trail breadcrumbs (newest last)
        self._trail: list[tuple[int, int, float]] = []  # (x, y, age_ms)
        self._last_trail_ms = 0

        # Floating action label under the cursor — e.g. "Clicking",
        # "Typing 'hello'", "Scrolling", "Looking at the screen". Fades
        # in/out smoothly as the agent's current action changes.
        self._action_label_text = ""
        self._action_label_set_ms = 0
        self._ACTION_LABEL_FADE_MS = 200
        self._ACTION_LABEL_HOLD_MS = 1100  # show for 1.1s after last update
        self._companion_enabled = False
        self._companion_label = ""
        self._companion_label_set_ms = 0
        # When True, cursor-action feedback (show_click / show_uia / show_action …)
        # stops writing the bubble text. Set while Gemini Live owns the bubble so a
        # Live-spawned desktop task can't flash its per-step labels over the live
        # conversation — the cursor still flies and the rings/glow still draw, only
        # the floating text is held. The authoritative set_companion_label (used by
        # Live's own narration) is never gated by this.
        self._companion_text_locked = False
        self._companion_display_pos = self._companion_cursor_target()
        self._companion_vel = QPointF(0, 0)
        self._companion_bubble_alpha = 1.0
        self._companion_bubble_scale = 1.0
        # Cursor state morph: "idle" (arrow), "listening" (pulsing waveform while
        # push-to-talk is held), "thinking" (spinner while the agent works).
        self._cursor_state = "idle"
        self._audio_level = 0.0  # live mic loudness 0..1 for the waveform
        # Orb ↔ textbox morph: 0 = resting "presence" orb (minimized cursor),
        # 1 = full textbox. Eases up on voice/agent activity, collapses back to
        # the orb EXPAND_HOLD_MS after the last activity/answer.
        self._companion_expand = 0.0

        # Quiet companion: the bubble is invisible while idle and only appears
        # when there's something to show; it also auto-hides while a fullscreen
        # app (e.g. a game) is in front. How long an answer/label lingers before
        # it fades back to invisible (ms); fullscreen-hide can be disabled.
        self.COMPANION_IDLE_HIDE_MS = int(os.getenv("ORYNN_COMPANION_HIDE_MS") or "6500")
        self._hide_in_fullscreen = (
            os.getenv("ORYNN_HIDE_IN_FULLSCREEN") or "1"
        ).strip().lower() not in ("0", "false", "no", "off")
        self._fs_check_ms = 0       # throttle the (cheap) foreground-window probe
        self._fs_cached = False

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(self.TICK_MS)

    # ── public API ──────────────────────────────────────────────────────
    def show_click(self, x: int, y: int, label: str = "Clicking") -> None:
        x, y = self._to_local_point(x, y)
        self._move_cursor_to(x, y)
        self._ripples.append(_Ripple(x, y))
        self._click_pulse_start_ms = self._now_ms()
        self._set_action_label(label)
        self._action_companion_label(label)
        self._bump_cursor_visibility()
        self._ensure_visible()

    def show_type(self, x: int, y: int, text: str = "") -> None:
        x, y = self._to_local_point(x, y)
        self._move_cursor_to(x, y)
        self._carets.append(_Caret(x, y, text))
        if text:
            self._set_action_label(f"Typing “{text[:24]}”")
            self._action_companion_label(f"Typing {text[:32]}")
        else:
            self._set_action_label("Typing")
            self._action_companion_label("Typing")
        self._bump_cursor_visibility()
        self._ensure_visible()

    def set_cursor_state(self, state: str) -> None:
        """Morph the idle cursor: 'idle' (arrow), 'listening' (waveform), or
        'thinking' (spinner). No-op if unchanged."""
        state = state if state in ("idle", "listening", "thinking") else "idle"
        if state != self._cursor_state:
            self._cursor_state = state
            if state != "listening":
                self._audio_level = 0.0
            self._ensure_visible()
            self.update()

    def set_audio_level(self, level: float) -> None:
        """Live mic loudness (0..1) so the listening waveform reacts to the voice."""
        try:
            self._audio_level = max(0.0, min(1.0, float(level)))
        except Exception:
            self._audio_level = 0.0
        if self._cursor_state == "listening":
            self._ensure_visible()
            self.update()

    def show_uia(self, x: int, y: int, w: int, h: int,
                 label: str = "", kind: str = "click") -> None:
        """UIA action feedback: fly the buddy to the control, then trace a focus
        ring around its exact bounds. The ring stays authoritative (the true
        bounds); the flying cursor is the 'presenter' so the user sees WHERE the
        agent is acting — the Clicky fly-to-element feel, on the reliable UIA
        path. Keep only the latest spotlight so the view stays clean."""
        x, y, w, h = self._to_local_rect(x, y, w, h)
        self._spotlights = [s for s in self._spotlights if s.progress() < 0.7]
        self._spotlights.append(_Spotlight(x, y, w, h, label, kind))
        interactive = kind in ("click", "double_click", "type", "drag", "press")
        if interactive:
            # Land on the control centre, pulse, and ping a ripple — a click.
            cx, cy = x + w // 2, y + h // 2
            self._move_cursor_to(cx, cy)
            self._click_pulse_start_ms = self._now_ms()
            self._ripples.append(_Ripple(cx, cy))
        else:
            # find/wait: point at the control's leading corner, no click.
            self._move_cursor_to(x + min(16, max(4, w // 3)),
                                 y + min(16, max(4, h // 3)))
        self._set_action_label(label or f"UIA {kind}")
        self._action_companion_label(label or f"UIA {kind}")
        self._bump_cursor_visibility()
        self._ensure_visible()

    def show_app_focus(self, x: int, y: int, w: int, h: int,
                       label: str = "") -> None:
        """Glow the edges of the whole app window the agent is operating in
        (brand colour), with a status label. Re-armed on every action so the
        glow stays up while the agent works, then fades once it's idle."""
        x, y, w, h = self._to_local_rect(x, y, w, h)
        now = self._now_ms()
        if self._app_glow is None:
            self._app_glow = _AppGlow(x, y, w, h, label, now)
        else:
            self._app_glow.rearm(x, y, w, h, label, now)
        if label:
            self._action_companion_label(label)
        self._ensure_visible()

    def keep_app_glow_alive(self) -> None:
        """Extend the app-edge glow's lifetime so it stays SOLID while the agent
        is busy — even when a slow model pauses several seconds between actions.
        Called on a heartbeat by the capsule while a task is running; once the
        task ends the heartbeat stops and the glow fades out naturally."""
        if self._app_glow is not None:
            self._app_glow.armed_until = self._now_ms() + 3500
            self._ensure_visible()

    def clear_app_glow(self) -> None:
        """Begin fading the app-edge glow out NOW (call the instant a task ends
        so the glow doesn't linger ~4s after completion). Fades over fade_ms
        (~0.5s) rather than vanishing, so it still feels smooth."""
        if self._app_glow is not None:
            self._app_glow.armed_until = self._now_ms()
            self._ensure_visible()

    def show_action(self, label: str, x: int | None = None,
                    y: int | None = None) -> None:
        """Show a label without firing a click/type — for actions like
        scrolling, focusing a window, taking a screenshot, etc."""
        if x is not None and y is not None:
            x, y = self._to_local_point(x, y)
            self._move_cursor_to(x, y)
        self._set_action_label(label)
        self._action_companion_label(label)
        self._bump_cursor_visibility()
        self._ensure_visible()

    def set_companion_enabled(self, enabled: bool,
                              label: str = "Ready") -> None:
        """Turn the idle companion cursor on/off without ever taking input."""
        self._companion_enabled = bool(enabled)
        if label:
            self.set_companion_label(label)
        if self._companion_enabled:
            self._companion_display_pos = self._companion_cursor_target()
            self._companion_vel = QPointF(0, 0)
            self._ensure_visible()
        else:
            self.update()

    def set_companion_label(self, label: str) -> None:
        """Update the bubble that follows the real pointer. The bubble word-wraps
        and grows to fit, so allow a few lines of text (Clicky-style) rather than
        a single truncated line."""
        text = (label or "").strip()
        if len(text) > 220:
            text = text[:217].rstrip() + "..."
        if text != self._companion_label:
            self._companion_label = text
            self._companion_label_set_ms = self._now_ms()
            self._companion_bubble_alpha = 0.0
            # Subtle pop-in: start near full size so it eases in gently rather
            # than springing from tiny (which read as "slop").
            self._companion_bubble_scale = 0.88
        if self._companion_enabled:
            if not self.isVisible():
                self._ensure_visible()
            self.update()

    def set_companion_text_locked(self, locked: bool) -> None:
        """Lock/unlock the bubble text against cursor-action feedback. While locked
        (Gemini Live owns the bubble), show_* keep flying the cursor and drawing
        rings/glow but stop overwriting the floating text, so a Live-spawned task's
        step labels can't flash over the live conversation."""
        self._companion_text_locked = bool(locked)

    def _action_companion_label(self, label: str) -> None:
        """Set the bubble text from a cursor action — unless something else (Live)
        currently owns it, in which case the spatial feedback still plays but the
        text is left untouched."""
        if self._companion_text_locked:
            return
        self.set_companion_label(label)

    # Internal: set the floating action label that follows the cursor.
    def _set_action_label(self, label: str) -> None:
        self._action_label_text = (label or "").strip()
        self._action_label_set_ms = self._now_ms()

    # ── internal ────────────────────────────────────────────────────────
    def _now_ms(self) -> int:
        from PySide6.QtCore import QDateTime
        return QDateTime.currentMSecsSinceEpoch()

    def _ensure_visible(self) -> None:
        self._sync_virtual_geometry()
        if not self.isVisible():
            self.show()
            self.raise_()

    def _companion_active(self, now_ms: int) -> bool:
        """True when the companion has something worth showing right now. When this
        is False the bubble fades out and the overlay disappears — so it's only ever
        on screen while listening, thinking, surfacing an answer, or drawing an
        in-flight action; never just sitting there following the cursor."""
        if self._cursor_state in ("listening", "thinking"):
            return True
        if self._companion_label and (
                now_ms - self._companion_label_set_ms) < self.COMPANION_IDLE_HIDE_MS:
            return True
        if (self._ripples or self._carets or self._spotlights
                or self._app_glow is not None or self._trail):
            return True
        if self._action_label_text and (
                now_ms - self._action_label_set_ms) < (
                    self._ACTION_LABEL_HOLD_MS + self._ACTION_LABEL_FADE_MS):
            return True
        if now_ms < self._cursor_visible_until:
            return True
        return False

    def _fullscreen_app_in_front(self) -> bool:
        """True when a fullscreen app (e.g. a game) owns the foreground, so the
        companion should stay out of the way. The probe is cheap but throttled +
        cached so it runs at most ~2x/sec. Opt out with ORYNN_HIDE_IN_FULLSCREEN=0."""
        if not self._hide_in_fullscreen:
            return False
        now = self._now_ms()
        if now - self._fs_check_ms < 400:
            return self._fs_cached
        self._fs_check_ms = now
        self._fs_cached = self._compute_fullscreen_in_front()
        return self._fs_cached

    def _compute_fullscreen_in_front(self) -> bool:
        try:
            import win32api
            import win32con
            import win32gui
        except Exception:
            return False
        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return False
            # The desktop / shell / taskbar are not "a fullscreen app".
            if win32gui.GetClassName(hwnd) in (
                "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"
            ):
                return False
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            mon = win32api.GetMonitorInfo(
                win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST)
            )["Monitor"]
            # Foreground window covers the WHOLE monitor (including the taskbar
            # area) → borderless/exclusive fullscreen. A merely maximized window
            # leaves the taskbar, so its rect won't reach the monitor's bounds.
            return (left <= mon[0] and top <= mon[1]
                    and right >= mon[2] and bottom >= mon[3])
        except Exception:
            return False

    def _sync_virtual_geometry(self) -> None:
        """Cover all monitors and remember the global-to-local offset."""
        try:
            screens = QGuiApplication.screens()
            if not screens:
                screen = QGuiApplication.primaryScreen()
                screens = [screen] if screen is not None else []
            if not screens:
                return
            geo = screens[0].geometry()
            for screen in screens[1:]:
                geo = geo.united(screen.geometry())
            self._origin_x = int(geo.x())
            self._origin_y = int(geo.y())
            if self.geometry() != geo:
                self.setGeometry(geo)
        except Exception:
            pass

    def _to_local_point(self, x: int, y: int) -> tuple[int, int]:
        self._sync_virtual_geometry()
        return int(x) - self._origin_x, int(y) - self._origin_y

    def _companion_cursor_target(self) -> QPointF:
        qp = QCursor.pos()
        return QPointF(
            qp.x() + self.COMPANION_OFFSET_X - self._origin_x,
            qp.y() + self.COMPANION_OFFSET_Y - self._origin_y,
        )

    def _to_local_rect(self, x: int, y: int, w: int, h: int) -> tuple[int, int, int, int]:
        lx, ly = self._to_local_point(x, y)
        return lx, ly, int(w), int(h)

    def _bump_cursor_visibility(self) -> None:
        self._cursor_visible_until = self._now_ms() + self.CURSOR_DECAY_MS

    def _move_cursor_to(self, x: int, y: int) -> None:
        """Snap the cursor instantly to (x, y) without travel delay."""
        self._cursor_x, self._cursor_y = x, y
        self._p0 = self._p2 = self._p1 = (x, y)
        self._anim_t = 1.0
        self._anim_elapsed_ms = self._anim_duration_ms
        self._trail.clear()

    @staticmethod
    def _ease_in_out_cubic(t: float) -> float:
        """Smooth start AND smooth landing — clicky agent feel."""
        if t < 0.5:
            return 4 * t * t * t
        return 1 - ((-2 * t + 2) ** 3) / 2

    def _bezier_point(self, t: float) -> tuple[float, float]:
        """Evaluate the quadratic bezier at parameter t."""
        x0, y0 = self._p0; x1, y1 = self._p1; x2, y2 = self._p2
        u = 1 - t
        x = u * u * x0 + 2 * u * t * x1 + t * t * x2
        y = u * u * y0 + 2 * u * t * y1 + t * t * y2
        return (x, y)

    def _tick(self) -> None:
        # Drive cursor animation along the bezier with eased timing
        if self._anim_t < 1.0:
            self._anim_elapsed_ms += self.TICK_MS
            raw_t = min(1.0, self._anim_elapsed_ms / self._anim_duration_ms)
            self._anim_t = raw_t
            eased = self._ease_in_out_cubic(raw_t)
            x, y = self._bezier_point(eased)
            self._cursor_x, self._cursor_y = int(x), int(y)

        now_ms = self._now_ms()

        # Record trail breadcrumbs (independent of motion — tracks position)
        if (self._cursor_x >= 0
                and now_ms - self._last_trail_ms >= self.TRAIL_STRIDE_MS
                and self._anim_t < 1.0):  # only drop trail while moving
            self._trail.append((self._cursor_x, self._cursor_y, 0))
            self._last_trail_ms = now_ms
            if len(self._trail) > self.TRAIL_LEN:
                self._trail.pop(0)
        # Age trail
        self._trail = [(x, y, age + self.TICK_MS) for (x, y, age) in self._trail
                       if age < 800]

        # Age ripples + carets
        for r in self._ripples:
            r.t += self.TICK_MS
        self._ripples = [r for r in self._ripples if r.alive()]
        for c in self._carets:
            c.t += self.TICK_MS
        self._carets = [c for c in self._carets if c.alive()]
        for s in self._spotlights:
            s.t += self.TICK_MS
        self._spotlights = [s for s in self._spotlights if s.alive()]
        if self._app_glow is not None and not self._app_glow.alive(now_ms):
            self._app_glow = None

        # Quiet companion: it's only "awake" (visible + following the cursor) while
        # there's something to show — listening, thinking, a fresh answer, or
        # in-flight action effects. Otherwise it fades out and disappears, so it
        # never sits on screen distracting the user (e.g. while gaming). A
        # fullscreen app in the foreground force-sleeps it.
        awake = (
            self._companion_enabled
            and self._companion_active(now_ms)
            and not self._fullscreen_app_in_front()
        )
        companion_alive = False
        if self._companion_enabled:
            try:
                if awake:
                    target = self._companion_cursor_target()
                    dx = target.x() - self._companion_display_pos.x()
                    dy = target.y() - self._companion_display_pos.y()
                    dist = math.hypot(dx, dy)
                    if dist > self.COMPANION_SNAP_DISTANCE:
                        self._companion_display_pos = QPointF(
                            target.x(), target.y())
                        self._companion_vel = QPointF(0, 0)
                    else:
                        stiffness, damping = (
                            self.COMPANION_STIFFNESS,
                            self.COMPANION_DAMPING,
                        )
                        ax = dx * stiffness
                        ay = dy * stiffness
                        self._companion_vel = QPointF(
                            self._companion_vel.x() * damping + ax,
                            self._companion_vel.y() * damping + ay,
                        )
                        self._companion_display_pos = QPointF(
                            self._companion_display_pos.x()
                            + self._companion_vel.x(),
                            self._companion_display_pos.y()
                            + self._companion_vel.y(),
                        )
                    # Smooth, quick fade-in + gentle ease to full size (no bounce).
                    self._companion_bubble_alpha = min(
                        1.0, self._companion_bubble_alpha + 0.16)
                    self._companion_bubble_scale += (
                        1.0 - self._companion_bubble_scale) * 0.22
                else:
                    # Asleep: fade out in place (don't chase the cursor), then the
                    # window hides once it's fully transparent.
                    self._companion_bubble_alpha = max(
                        0.0, self._companion_bubble_alpha - 0.12)
                    self._companion_bubble_scale += (
                        0.9 - self._companion_bubble_scale) * 0.16
                companion_alive = self._companion_bubble_alpha > 0.02
                if companion_alive and not self.isVisible():
                    self._ensure_visible()
            except Exception:
                companion_alive = False

        label_alive = (self._action_label_text and
                       now_ms - self._action_label_set_ms <
                       (self._ACTION_LABEL_HOLD_MS
                        + self._ACTION_LABEL_FADE_MS))

        # Repaint ONLY when something is actually moving/animating. The overlay
        # used to update() every single tick (60fps) even sitting idle, burning
        # CPU/battery for an identical frame. A still mouse on a settled bubble
        # now costs zero repaints.
        companion_moving = False
        if companion_alive:
            tgt = self._companion_cursor_target()
            companion_moving = math.hypot(
                tgt.x() - self._companion_display_pos.x(),
                tgt.y() - self._companion_display_pos.y()) > 0.5
        # "Animating" only while the bubble is at least faintly visible and not yet
        # settled. A fully-faded (asleep) bubble has alpha 0 and must NOT count as
        # animating — otherwise it would repaint forever and never hide.
        bubble_anim = self._companion_bubble_alpha > 0.02 and (
            self._companion_bubble_alpha < 0.999
            or abs(self._companion_bubble_scale - 1.0) > 0.004)

        # Orb ↔ textbox morph: expand to the textbox while busy or while a recent
        # label is still fresh; collapse back to the resting orb EXPAND_HOLD_MS
        # after the last activity/answer.
        busy = (
            self._anim_t < 1.0
            or bool(self._ripples or self._carets or self._spotlights)
            or self._app_glow is not None
            or bool(self._trail)
            or label_alive
            or now_ms < self._cursor_visible_until
            or self._cursor_state in ("listening", "thinking")
        )
        recent_label = (now_ms - self._companion_label_set_ms) < self.EXPAND_HOLD_MS
        target_expand = 1.0 if (busy or recent_label) else 0.0
        self._companion_expand += (target_expand - self._companion_expand) * 0.18
        expand_anim = abs(self._companion_expand - target_expand) > 0.01

        animating = busy or bubble_anim or companion_moving or expand_anim

        if not companion_alive and not animating:
            if self.isVisible():
                self.hide()
                self._action_label_text = ""
        elif animating:
            self.update()

    # ── painting ────────────────────────────────────────────────────────
    def paintEvent(self, _e) -> None:
        from PySide6.QtGui import QRadialGradient
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # CRITICAL: explicitly clear the layered overlay to fully transparent
        # every frame. With WA_NoSystemBackground this window is NOT auto-cleared,
        # so without this each repaint draws ON TOP of the last — leaving a trail
        # of hundreds of ghost bubbles as the cursor moves (the screen-flood bug).
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.fillRect(self.rect(), Qt.transparent)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

        # 1. Trail breadcrumbs — disabled to keep UI clean and snap-instant
        pass

        # 2. Ripples (under the cursor, on click sites) — removed per user request
        pass

        # 3. Carets (typing indicator)
        for c in self._carets:
            t = c.t
            on = (int(t // 250) % 2) == 0
            if on:
                p.setPen(QPen(RIPPLE_COLOR, 2))
                p.drawLine(c.x, c.y - 10, c.x, c.y + 10)
            if c.text:
                p.setFont(QFont("Segoe UI Variable Text", 10, QFont.Medium))
                tw = max(40, p.fontMetrics().horizontalAdvance(c.text) + 18)
                rect = QRect(c.x + 14, c.y - 12, tw, 24)
                p.setBrush(QBrush(LABEL_BG))
                p.setPen(QPen(QColor(255, 255, 255, 40), 1))
                p.drawRoundedRect(rect, 6, 6)
                p.setPen(QPen(LABEL_FG))
                p.drawText(rect.adjusted(8, 0, -8, 0),
                           Qt.AlignVCenter | Qt.AlignLeft, c.text)

        # 3a. App-edge glow — disabled per user request
        now0 = self._now_ms()

        # 3b. UIA spotlights — disabled per user request

        # 4. Cursor pointer and action label — disabled per user request to only show ripple
        now = self._now_ms()
        if self._companion_enabled and self._companion_display_pos.x() >= 0:
            has_target_overlay = bool(self._spotlights or self._ripples
                                      or self._carets)
            if not has_target_overlay:
                cx = self._companion_display_pos.x()
                cy = self._companion_display_pos.y()
                # The listening/thinking indicators are drawn INSIDE the bubble
                # (in the status-dot slot) by _paint_companion_bubble, so they
                # read as one tidy element instead of a circle floating off the
                # corner.
                self._paint_companion_bubble(p, cx, cy, now)

        p.end()

    def _paint_app_glow(self, p: QPainter, g: "_AppGlow", now_ms: int) -> None:
        """Draw a soft, breathing brand-colour border hugging the app window's
        edges, with a status label tag at the top."""
        if now_ms < g.armed_until:
            a = min(1.0, (now_ms - g.t0) / 200.0)      # ease in
        else:
            a = max(0.0, 1.0 - (now_ms - g.armed_until) / g.fade_ms)
        if a <= 0.01:
            return
        pulse = (1 + math.sin(now_ms / 430.0)) / 2      # 0..1 gentle breathing
        # Sit the ring a hair inside the window outline.
        rect = QRectF(g.x + 1.5, g.y + 1.5, g.w - 3, g.h - 3)
        rad = 11.0
        # wide soft glow passes (outer → inner), breathing in intensity
        for gw, ga in ((26.0, 22), (16.0, 44), (8.0, 78)):
            c = QColor(RIPPLE_COLOR)
            c.setAlpha(int(ga * a * (0.62 + 0.38 * pulse)))
            p.setPen(QPen(c, gw)); p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect, rad, rad)
        # crisp inner line
        c = QColor(RIPPLE_COLOR); c.setAlpha(int(248 * a))
        p.setPen(QPen(c, 2.4)); p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, rad, rad)
        # status tag near the top edge of the window
        if g.label:
            self._draw_label_pill(p, int(g.x + g.w / 2), int(g.y + 14),
                                  g.label, a)

    def _paint_spotlight(self, p: QPainter, s: "_Spotlight", now_ms: int) -> None:
        """Draw a snapping focus ring + glow around a UIA control's bounds, with
        a label pill below it. Animated: a quick expand-in, hold, fade-out."""
        prog = s.progress()
        intro, outro = 0.10, 0.16
        if prog < intro:
            a = prog / intro
        elif prog > 1 - outro:
            a = max(0.0, (1 - prog) / outro)
        else:
            a = 1.0
        if a <= 0.01:
            return

        # Intro starts slightly outside the exact UIA bounds and settles onto
        # the true rectangle. Keep this tight so the outline feels precise.
        grow = (1 - min(1.0, prog / intro)) * 3 if prog < intro else 0.0
        # 'type' keeps a very gentle breathing pulse while it holds.
        if s.kind == "type" and intro <= prog <= 1 - outro:
            grow += 0.75 * (1 + math.sin(s.t / 130.0)) / 2

        x = s.x - grow
        y = s.y - grow
        w = s.w + 2 * grow
        h = s.h + 2 * grow
        rad = min(7.0, max(2.0, min(w, h) / 5))
        rect = QRectF(x + 0.5, y + 0.5, max(1.0, w - 1), max(1.0, h - 1))

        # Faint interior tint.
        fc = QColor(RIPPLE_COLOR); fc.setAlpha(int(12 * a))
        p.setPen(Qt.NoPen); p.setBrush(QBrush(fc))
        p.drawRoundedRect(rect, rad, rad)

        # Tight glow, then an exact hairline. Big glows made small controls feel
        # approximate; this keeps the user's eye on the actual UIA rectangle.
        for gw, ga in ((6.0, 20), (3.0, 46)):
            gc = QColor(RIPPLE_COLOR); gc.setAlpha(int(ga * a))
            p.setPen(QPen(gc, gw)); p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect, rad, rad)

        # Crisp exact ring with a faint outer contrast line for light UIs.
        oc = QColor(0, 0, 0, int(72 * a))
        p.setPen(QPen(oc, 3.2)); p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, rad, rad)
        rc = QColor(RIPPLE_COLOR); rc.setAlpha(int(235 * a))
        p.setPen(QPen(rc, 1.8)); p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, rad, rad)

        # Corner brackets make the exact bounds legible without flooding the
        # whole control. Draw them inside the rectangle so they never drift.
        corner = max(8, min(22, int(min(w, h) * 0.35)))
        bx0, by0 = int(rect.left()), int(rect.top())
        bx1, by1 = int(rect.right()), int(rect.bottom())
        bc = QColor(255, 255, 255, int(235 * a))
        p.setPen(QPen(bc, 1.4))
        p.drawLine(bx0 + 1, by0 + 1, bx0 + corner, by0 + 1)
        p.drawLine(bx0 + 1, by0 + 1, bx0 + 1, by0 + corner)
        p.drawLine(bx1 - corner, by0 + 1, bx1 - 1, by0 + 1)
        p.drawLine(bx1 - 1, by0 + 1, bx1 - 1, by0 + corner)
        p.drawLine(bx0 + 1, by1 - 1, bx0 + corner, by1 - 1)
        p.drawLine(bx0 + 1, by1 - corner, bx0 + 1, by1 - 1)
        p.drawLine(bx1 - corner, by1 - 1, bx1 - 1, by1 - 1)
        p.drawLine(bx1 - 1, by1 - corner, bx1 - 1, by1 - 1)

        # label pill, centred below the control (flips above if no room)
        if s.label:
            self._draw_label_pill(p, int(x + w / 2), int(y + h + 12), s.label, a)

    def _draw_label_pill(self, p: QPainter, cx: int, top_y: int,
                         text: str, alpha_mul: float) -> None:
        """A floating 'what it's doing' pill anchored at (cx centre, top_y)."""
        if not text or alpha_mul <= 0.01:
            return
        p.setFont(QFont("Segoe UI Variable Text", 10, QFont.Medium))
        fm = p.fontMetrics()
        pad_x, pad_y = 12, 6
        tw = fm.horizontalAdvance(text)
        w = tw + pad_x * 2 + 10           # +10 for the accent dot
        h = fm.height() + pad_y * 2
        geo = self.geometry()
        x = cx - w // 2
        y = top_y
        x = max(6, min(x, geo.width() - 6 - w))
        if y + h > geo.height() - 6:
            y = top_y - 24 - h
        # drop shadow
        for dy, sa in ((3, 26), (2, 40), (1, 54)):
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(0, 0, 0, int(sa * alpha_mul))))
            p.drawRoundedRect(x, y + dy, w, h, h // 2, h // 2)
        # glass pill
        p.setBrush(QBrush(QColor(20, 24, 32, int(228 * alpha_mul))))
        p.setPen(QPen(QColor(255, 255, 255, int(70 * alpha_mul)), 1.0))
        p.drawRoundedRect(x, y, w, h, h // 2, h // 2)
        # accent dot
        dc = QColor(RIPPLE_COLOR); dc.setAlpha(int(235 * alpha_mul))
        p.setBrush(QBrush(dc)); p.setPen(Qt.NoPen)
        p.drawEllipse(QPoint(x + pad_x, y + h // 2), 3, 3)
        # text
        p.setPen(QPen(QColor(240, 242, 248, int(245 * alpha_mul))))
        p.drawText(QRect(x + pad_x + 10, y, w - pad_x * 2 - 10, h),
                   Qt.AlignVCenter | Qt.AlignLeft, text)

    COMPANION_MAX_TEXT_WIDTH = 300  # px, like Clicky's response overlay

    @classmethod
    def _companion_text_width_limit(
        cls,
        screen_width: int,
        margin: int,
        pad_x: int,
        dot_gap: int,
    ) -> int:
        """Return a text width that keeps the expanded bubble inside the screen."""
        available_w = max(1, int(screen_width) - max(0, margin) * 2)
        chrome_w = max(0, pad_x) * 2 + max(0, dot_gap)
        return max(1, min(cls.COMPANION_MAX_TEXT_WIDTH, available_w - chrome_w))

    def _companion_dot(self, text: str) -> tuple:
        """Pick the status-dot colour (and whether it pulses) from the label,
        mirroring Clicky's animated status dot."""
        t = text.lower()
        if t.startswith("listening"):
            return DS_BLUE, True
        bad = ("didn't", "failed", "couldn't", "unavailable", "cancel",
               "error", "timed out", "needs approval")
        if any(k in t for k in bad):
            return DS_AMBER, False
        # Settled/idle states are green even if their text mentions an action
        # word (e.g. a completion reason that says "typing").
        settled = ("orynn ready", "heard:", "done", "ready", "welcome", "all set")
        if any(t.startswith(k) for k in settled):
            return DS_GREEN, False
        busy = ("transcrib", "working", "thinking", "started", "queued",
                "using", "clicking", "typing", "reading", "focus", "finding",
                "waiting", "scrolling", "running", "editing", "pressing")
        if any(k in t for k in busy):
            return DS_BLUE, True
        return DS_GREEN, False

    def _paint_orb(self, p: QPainter, ox: float, oy: float,
                   color: QColor, a: float, r: float = 4.6) -> None:
        """The resting 'presence' orb — a glossy glowing dot: soft layered glow,
        a crisp core, and a small offset highlight for a 3D sheen."""
        p.setPen(Qt.NoPen)
        for rr, alpha in ((r * 2.7, 24), (r * 1.9, 40), (r * 1.3, 75)):
            c = QColor(color); c.setAlpha(int(alpha * a))
            p.setBrush(QBrush(c))
            p.drawEllipse(QPointF(ox, oy), rr, rr)
        core = QColor(color); core.setAlpha(int(255 * a))
        p.setBrush(QBrush(core))
        p.drawEllipse(QPointF(ox, oy), r, r)
        hi = QColor(255, 255, 255); hi.setAlpha(int(150 * a))
        p.setBrush(QBrush(hi))
        p.drawEllipse(QPointF(ox - r * 0.32, oy - r * 0.32), r * 0.34, r * 0.34)

    def _paint_companion_bubble(self, p: QPainter, cx: float, cy: float,
                                now_ms: int) -> None:
        """Morphs between a resting 'presence' orb (the minimized cursor) and the
        full textbox. self._companion_expand drives it: 0 = just the orb, 1 = the
        capsule unfolded with text."""
        text = self._companion_label or ""
        if text in ("Ready", "Orynn ready"):
            text = "Orynn ready"
        expand = max(0.0, min(1.0, self._companion_expand))
        orb_a = max(0.0, min(1.0, self._companion_bubble_alpha))
        if orb_a < 0.02:
            return

        p.setFont(QFont("Segoe UI", 10))
        fm = p.fontMetrics()
        pad_x, pad_y = 13, 9
        dot_gap = 16

        geo = self.geometry()
        margin = 8
        available_w = max(26, int(geo.width()) - margin * 2)
        available_h = max(26, int(geo.height()) - margin * 2)

        max_tw = self._companion_text_width_limit(
            geo.width(), margin, pad_x, dot_gap
        )
        flags = int(Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop)
        bound = fm.boundingRect(QRect(0, 0, max_tw, 4000), flags, text or " ")
        tw = max(1, min(max_tw, bound.width()))
        th = min(
            max(fm.height(), bound.height()),
            max(fm.height(), available_h - pad_y * 2),
        )
        full_w = min(tw + pad_x * 2 + dot_gap, available_w)
        full_h = min(th + pad_y * 2, available_h)
        text_w = max(1.0, full_w - pad_x * 2 - dot_gap)
        text_h = max(1.0, full_h - pad_y * 2)

        # Expanded box position, clamped on-screen using the FULL size so the orb
        # anchor stays put across the whole morph (no jump as it grows/shrinks).
        box_x, box_y = cx, cy
        if box_x + full_w > geo.width() - margin:
            box_x = cx - full_w - 18
        if box_y + full_h > geo.height() - margin:
            box_y = cy - full_h - 8
        max_x = max(margin, geo.width() - full_w - margin)
        max_y = max(margin, geo.height() - full_h - margin)
        box_x = max(margin, min(box_x, max_x))
        box_y = max(margin, min(box_y, max_y))

        # Fixed orb anchor (the resting cursor): the top-left indicator slot.
        orb_cx = box_x + pad_x + 4
        orb_cy = box_y + pad_y + fm.ascent() / 2 + 1

        # The capsule grows from a small circle hugging the orb to the full box.
        coll = 26.0
        cap_x = (orb_cx - coll / 2) + (box_x - (orb_cx - coll / 2)) * expand
        cap_y = (orb_cy - coll / 2) + (box_y - (orb_cy - coll / 2)) * expand
        cap_w = coll + (full_w - coll) * expand
        cap_h = coll + (full_h - coll) * expand
        radius = 13.0 + (11.0 - 13.0) * expand
        cap_a = orb_a * expand

        p.save()
        p.setPen(Qt.NoPen)
        if cap_a > 0.01:
            bg = QColor(DS_SURFACE); bg.setAlpha(int(245 * cap_a))
            p.setBrush(QBrush(bg))
            border = QColor(DS_BORDER); border.setAlpha(int(220 * cap_a))
            p.setPen(QPen(border, 1.0))
            p.drawRoundedRect(QRectF(cap_x, cap_y, cap_w, cap_h), radius, radius)

        # Persistent orb / state indicator at the fixed anchor.
        if self._cursor_state == "thinking":
            self._paint_mini_spinner(p, orb_cx, orb_cy, 6.0, now_ms, orb_a)
        elif self._cursor_state == "listening":
            lvl = self._audio_level
            glow = QColor(DS_BLUE); glow.setAlpha(int(70 * orb_a))
            p.setPen(Qt.NoPen); p.setBrush(QBrush(glow))
            p.drawEllipse(QPointF(orb_cx, orb_cy), 5 + lvl * 5, 5 + lvl * 5)
            core = QColor(DS_BLUE); core.setAlpha(int(255 * orb_a))
            p.setBrush(QBrush(core))
            p.drawEllipse(QPointF(orb_cx, orb_cy), 3 + lvl * 4, 3 + lvl * 4)
        else:
            col, _ = self._companion_dot(text)
            if col != DS_AMBER:  # blue "presence" everywhere except errors
                col = DS_BLUE
            self._paint_orb(p, orb_cx, orb_cy, col, orb_a)

        # Text fades in over the second half of the expansion.
        text_a = max(0.0, (expand - 0.4) / 0.6) * orb_a
        if text_a > 0.02 and text:
            fg = QColor(DS_TEXT); fg.setAlpha(int(255 * text_a))
            p.setPen(QPen(fg))
            text_rect = QRectF(
                box_x + pad_x + dot_gap,
                box_y + pad_y,
                text_w,
                text_h,
            )
            p.drawText(text_rect, flags, text)
        p.restore()

    def _flight_scale(self) -> float:
        """1.0 at rest; swells toward ~1.28x at the bezier arc's apex while the
        cursor is in flight, settling back to 1.0 on landing."""
        if 0.0 < self._anim_t < 1.0:
            return 1.0 + 0.28 * math.sin(math.pi * self._anim_t)
        return 1.0

    def _paint_mini_spinner(self, p: QPainter, cx: float, cy: float,
                            r: float, now_ms: int, a: float = 1.0) -> None:
        """A small comet-arc spinner drawn inside the bubble's indicator slot:
        a faint track with a bright head fading into a tapering tail. The angle
        is taken mod 360 — now_ms is the raw epoch (~1.7e12) and an unbounded
        angle overflows the 32-bit int QPainter.drawArc expects."""
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        track = QColor(DS_BLUE); track.setAlpha(int(30 * a))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(track, 2.0))
        p.drawArc(rect, 0, 360 * 16)
        head = ((now_ms / 1100.0) * 360.0) % 360.0
        span = 220.0
        segs = 14
        seg = span / segs
        for i in range(segs):
            frac = (i + 1) / segs
            ang = head - (1.0 - frac) * span
            alpha = int((18 + 212 * (frac ** 1.6)) * a)
            col = QColor(DS_BLUE); col.setAlpha(alpha)
            p.setPen(QPen(col, 2.0, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(rect, int(-ang * 16), int(-(seg + 0.8) * 16))

    def _paint_action_label(self, p: QPainter, cx: int, cy: int,
                            now_ms: int) -> None:
        """Render the floating action-name pill under the cursor."""
        if not self._action_label_text:
            return
        age = now_ms - self._action_label_set_ms
        hold = self._ACTION_LABEL_HOLD_MS
        fade = self._ACTION_LABEL_FADE_MS
        if age >= hold + fade:
            return
        # Fade-in over first 120ms, hold, fade-out at the end
        if age < 120:
            alpha_mul = age / 120.0
        elif age > hold:
            alpha_mul = max(0.0, 1.0 - (age - hold) / fade)
        else:
            alpha_mul = 1.0

        text = self._action_label_text
        p.setFont(QFont("Segoe UI Variable Text", 10, QFont.Medium))
        fm = p.fontMetrics()
        text_w = fm.horizontalAdvance(text)
        pad_x, pad_y = 11, 6
        w = text_w + pad_x * 2
        h = fm.height() + pad_y * 2
        # Position below the cursor, slight offset to avoid overlapping the
        # arrow's tail. Keep within screen edges.
        rect_x = cx - w // 2 + 6
        rect_y = cy + 28
        screen_geo = self.geometry()
        if rect_x < 6: rect_x = 6
        if rect_x + w > screen_geo.width() - 6:
            rect_x = screen_geo.width() - 6 - w
        if rect_y + h > screen_geo.height() - 6:
            rect_y = cy - 28 - h  # flip above if no room below

        # Subtle drop shadow under the pill
        for dy, a in ((3, 28), (2, 42), (1, 56)):
            shadow_col = QColor(0, 0, 0, int(a * alpha_mul))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(shadow_col))
            p.drawRoundedRect(rect_x, rect_y + dy, w, h, h // 2, h // 2)

        # Pill background — dark glass with subtle accent rim
        bg = QColor(20, 24, 32, int(225 * alpha_mul))
        p.setBrush(QBrush(bg))
        rim = QColor(255, 255, 255, int(70 * alpha_mul))
        p.setPen(QPen(rim, 1.0))
        p.drawRoundedRect(rect_x, rect_y, w, h, h // 2, h // 2)

        # Small accent dot on the left side — gives it the "live" feel
        dot_r = 3
        dot_x = rect_x + pad_x - 2
        dot_y = rect_y + h // 2
        dot_col = QColor(RIPPLE_COLOR); dot_col.setAlpha(int(235 * alpha_mul))
        p.setBrush(QBrush(dot_col))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPoint(dot_x, dot_y), dot_r, dot_r)

        # Text
        fg = QColor(240, 242, 248, int(245 * alpha_mul))
        p.setPen(QPen(fg))
        text_rect = QRect(rect_x + pad_x + 6, rect_y, w - pad_x * 2 - 6, h)
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, text)

    def _click_pulse_scale(self, now_ms: int) -> float:
        """Returns a scale 0.80..1.0 right after a click, then 1.0 baseline."""
        if self._click_pulse_start_ms <= 0:
            return 1.0
        elapsed = now_ms - self._click_pulse_start_ms
        if elapsed >= self.CLICK_PULSE_MS:
            return 1.0
        t = elapsed / self.CLICK_PULSE_MS  # 0..1
        # Ease: dip down then back up. min around t=0.35
        if t < 0.35:
            local = t / 0.35
            return 1.0 - 0.20 * local  # 1.0 → 0.80
        else:
            local = (t - 0.35) / 0.65
            # ease-out cubic back to 1
            return 0.80 + 0.20 * (1 - (1 - local) ** 3)

    def _paint_cursor(self, p: QPainter, x: int, y: int,
                      scale: float = 1.0) -> None:
        """Draw the macOS-style arrow at (x, y), tip on the point.
        Adds a soft drop shadow under the cursor for depth, and supports
        click-pulse scale animation around the tip."""
        # Drop shadow (slightly offset, blurred via semi-transparent fills)
        for offset, alpha in ((3, 28), (2, 40), (1, 55)):
            self._draw_arrow_path(p, x, y + offset, scale, fill=False,
                                  shadow_alpha=alpha)
        # Main arrow
        self._draw_arrow_path(p, x, y, scale, fill=True)

    def _draw_arrow_path(self, p: QPainter, x: int, y: int, scale: float,
                         fill: bool, shadow_alpha: int = 0) -> None:
        """Draw the arrow polygon, optionally as a shadow blob."""
        def sx(dx): return x + dx * scale
        def sy(dy): return y + dy * scale
        path = QPainterPath()
        path.moveTo(sx(0), sy(0))
        path.lineTo(sx(14), sy(14))
        path.lineTo(sx(8), sy(15))
        path.lineTo(sx(12), sy(22))
        path.lineTo(sx(10), sy(23))
        path.lineTo(sx(6), sy(17))
        path.lineTo(sx(2), sy(22))
        path.lineTo(sx(0), sy(0))
        path.closeSubpath()
        if shadow_alpha:
            col = QColor(0, 0, 0, shadow_alpha)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(col))
            p.drawPath(path)
            return
        if fill:
            p.setPen(QPen(CURSOR_OUTLINE, 1.8))
            p.setBrush(QBrush(CURSOR_COLOR))
            p.drawPath(path)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers for parsing the agent's action_start args_summary
# ─────────────────────────────────────────────────────────────────────────────

_NUM_PAIR_RE = re.compile(r"(-?\d+)\s*[, ]\s*(-?\d+)")
_AT_XY_RE = re.compile(r"\bat\s+(-?\d+)\s*[, ]\s*(-?\d+)", re.IGNORECASE)


def parse_click_xy(args_summary: str) -> tuple[int, int] | None:
    """Extract (x, y) from a mouse_click action's args_summary OR from the
    action_result's output text.

    The dashboard's `args_summary` for mouse_click is often just parameter
    NAMES ("x, y, button") rather than values — so we also look at result
    text patterns like "Clicked left 1 times at 656, 525".
    """
    if not args_summary:
        return None
    s = str(args_summary)
    # "Clicked left 1 times at 656, 525" or "moved to 100, 200"
    m = _AT_XY_RE.search(s)
    if m:
        return int(m.group(1)), int(m.group(2))
    # x=…, y=…
    mx = re.search(r"x[=:]\s*(-?\d+)", s)
    my = re.search(r"y[=:]\s*(-?\d+)", s)
    if mx and my:
        return int(mx.group(1)), int(my.group(1))
    # bare "123, 456" but ONLY if there are no letters (avoid parsing
    # field-name strings like "x, y, button" as coordinates)
    if not re.search(r"[A-Za-z]", s):
        m2 = _NUM_PAIR_RE.search(s)
        if m2:
            return int(m2.group(1)), int(m2.group(2))
    return None

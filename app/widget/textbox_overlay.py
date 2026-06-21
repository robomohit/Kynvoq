from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QColor, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .virtual_cursor import VirtualCursorOverlay


DESKTOP_HARDENING = (
    "You are driving the user's Windows desktop. Prefer UI Automation "
    "(UIA) over screenshots - it is faster and never mis-clicks:\n"
    "1. To OPEN or launch an app, press the Windows key, type the app "
    "name, then press Enter (Start-menu search) - this works for any "
    "installed app. Do NOT guess `start appname:` protocol/URI links "
    "(e.g. 'microsoftcopilot:') - an unregistered one just pops a 'no "
    "app to open this link' error. Common built-ins can also be launched "
    "directly via run_command: notepad, calc, explorer, mspaint, cmd, "
    "taskmgr; for Windows Settings use run_command `start ms-settings:` "
    "(this IS a registered protocol - the warning above is only about "
    "GUESSING unregistered ones). After launching, confirm with "
    "`wait_for_window` before reporting done - never claim an app opened "
    "without verifying its window. If Start search shows no match, tell "
    "the user the app isn't installed rather than guessing.\n"
    "2. `focus_window` (or `wait_for_window`) to bring the target app "
    "to the front.\n"
    "3. `uia_find` with the control's visible NAME (e.g. 'File', "
    "'Search', 'Send') to locate it - DO NOT take a screenshot or "
    "guess coordinates. ALWAYS pass the `app` window-title (e.g. "
    "app='Notepad') so UIA targets the right window even if focus "
    "didn't take.\n"
    "4. Act with `uia_click` (buttons/menus/channels) or `uia_type` "
    "(text boxes; clear_first=true to replace text, submit=true to "
    "press Enter and send/search in one step). After navigating, use "
    "`uia_wait` to block until the next control appears instead of "
    "guessing a delay.\n"
    "5. If `uia_find` returns nothing AND the app is Electron "
    "(VS Code, Slack, Discord, Spotify, Notion, Cursor...), call "
    "`electron_check` then `electron_unlock` on its .exe to relaunch "
    "with --force-renderer-accessibility, then retry uia_find.\n"
    "6. Only fall back to `screenshot` + coordinate clicks when a "
    "control has no accessible name (canvas/custom-drawn UI).\n"
    "7. Stop after at most 10 steps. If blocked, ask a clear question "
    "instead of looping.\n"
    "8. Never click Send / Submit / Pay / Delete without explicit "
    "user confirmation.\n\n"
    "TASK: "
)


ACTION_LABELS = {
    "mouse_click": "Clicking",
    "left_click": "Clicking",
    "click": "Clicking",
    "uia_click": "Clicking control",
    "uia_type": "Typing",
    "keyboard_type": "Typing",
    "type_with_delay": "Typing",
    "press_key": "Pressing key",
    "hotkey": "Pressing shortcut",
    "screenshot": "Reading screen",
    "get_screenshot": "Reading screen",
    "focus_window": "Focusing app",
    "wait_for_window": "Finding window",
    "uia_find": "Finding control",
    "uia_wait": "Waiting for UI",
    "scroll": "Scrolling",
    "mouse_scroll": "Scrolling",
    "write_file": "Writing file",
    "edit_file": "Editing file",
    "run_command": "Running command",
}

LIVE_DESKTOP_ACTION_LABELS = {
    "wait_for_window": "Finding window",
    "focus_window": "Focusing app",
    "observe": "Reading app controls",
    "find": "Finding control",
    "wait": "Waiting for control",
    "click": "Clicking control",
    "type": "Typing into control",
    "press_keys": "Pressing shortcut",
    "scroll": "Scrolling",
}

LIVE_DESKTOP_ACTIONS = set(LIVE_DESKTOP_ACTION_LABELS)

# The "acting" verbs that manipulate app UI. On the MODEL path these get fast-path-
# then-escalate routing (see _desktop_control_route): Live tries the direct UIA
# primitive first — fast (~1-4s), no agent, no permission prompt, no mouse-jump — and
# only escalates to the full agent (start_desktop_task) if that fails (control missing
# / Electron-locked). A single clear click stays fast; the heavy back office is reserved
# for multi-step / app-launch / vague goals (which the model sends to start_desktop_task
# directly) and for fast-click failures. The remaining desktop_control actions are never
# escalated: read-only inspection (observe/find/wait) and one-shot input
# (focus_window/wait_for_window/press_keys/scroll).
LIVE_UPGRADE_ACTIONS = {"click", "type"}

LIVE_BLOCKED_KEY_COMBOS = {
    "alt+f4",
    "alt+tab",
    "ctrl+shift+l",
    "ctrl+shift+m",
    "ctrl+shift+space",
    "ctrl+shift+x",
    "ctrl+q",
    "ctrl+w",
    "ctrl+shift+w",
    "win+d",
    "shift+delete",
    "win+l",
    "delete",
    "del",
}

LIVE_LABEL_HOLD_SECONDS = 2.8
LIVE_TOOL_LABEL_HOLD_SECONDS = 1.6

# How long start_desktop_task waits for the job to finish before handing back
# "still working" — most spoken commands (opens, quick actions) finish within this,
# so Live can speak the REAL outcome instead of a bare "started". Override with
# ORYNN_LIVE_TASK_WAIT. Kept well under GEMINI_LIVE_TOOL_TIMEOUT (15s) so the wait
# always returns before the outer tool timeout could fire.
LIVE_TASK_RESULT_WAIT = 6.0
TERMINAL_TASK_STATES = {"done", "complete", "error", "failed", "cancelled"}

# Minimum gap between spoken mid-task progress notes pushed into the Live
# conversation, so a busy task doesn't machine-gun the user with narration
# (brief §6.4 silence rules). Override with ORYNN_LIVE_NARRATE_INTERVAL; 0 disables.
LIVE_NARRATE_INTERVAL = 3.5

# Disruptive / hard-to-undo intents that must get spoken user consent before Live
# spawns an autonomous task to do them (brief §7.2): deleting, sending/submitting,
# paying, formatting/uninstalling, and relaunching/restarting apps (the electron
# relaunch case). Live-spawned tasks run autonomously with no dashboard approval
# popup, so this voice gate is the only thing standing between "open Notepad" and
# "send that email" — keep it focused on genuinely outward-facing or irreversible
# verbs to avoid nagging on benign goals. Matched with word boundaries.
LIVE_CONSENT_RE = re.compile(
    r"\b("
    r"delete|deletes|deleting|uninstall|uninstalls|uninstalling|"
    r"format|formats|formatting|wipe|wipes|wiping|erase|erases|erasing|"
    r"send|sends|sending|submit|submits|submitting|post|posts|posting|"
    r"publish|publishes|publishing|reply|replies|replying|"
    r"pay|pays|paying|purchase|purchases|purchasing|buy|buys|buying|"
    r"checkout|transfer|transfers|transferring|"
    r"relaunch|relaunches|relaunching|restart|restarts|restarting|"
    r"reboot|reboots|rebooting|shutdown|"
    r"shut\s*down|sign\s*out|log\s*out|factory\s*reset"
    r")\b",
    re.IGNORECASE,
)

# A negation right before a disruptive verb flips the intent — "do NOT send",
# "without deleting", "don't submit". Used to avoid gating those for consent (the
# user is telling Orynn NOT to do the thing).
_NEGATION_RE = re.compile(
    r"\b(?:not|never|without|don'?t|do\s+not|won'?t|cannot|can'?t|avoid|no\s+need\s+to)\W*$",
    re.IGNORECASE,
)


def _has_unnegated_match(text: str, regex: "re.Pattern[str]") -> bool:
    """True if `text` contains a regex match that is NOT immediately preceded by a
    negation — so 'delete the file' gates but 'do not delete the file' does not."""
    text = text or ""
    for m in regex.finditer(text):
        if _NEGATION_RE.search(text[:m.start()][-28:]):
            continue
        return True
    return False


# Shell commands that change or remove something hard to undo and so need spoken
# consent before Live runs them — the run_terminal analog of LIVE_CONSENT_RE.
# Catastrophic commands (rm -rf /, format, mkfs, shutdown) are already HARD-BLOCKED
# upstream by SafetyManager; this catches the merely-destructive tier (del a file,
# git push, taskkill, pip uninstall) that would otherwise run silently. Matched at a
# command boundary (start, or after a separator) so "git status" / "type file" are
# never caught by a substring.
LIVE_TERMINAL_CONSENT_RE = re.compile(
    r"(?:^|[\s;&|(`])"
    r"(?:"
    r"rm|del|erase|rmdir|rd|remove-item|"
    r"format|mkfs|diskpart|"
    r"shutdown|reboot|restart-computer|"
    r"taskkill|stop-process|"
    r"pip\s+uninstall|npm\s+uninstall|npm\s+publish|"
    r"git\s+push|git\s+clean|git\s+reset\s+--hard"
    r")\b",
    re.IGNORECASE,
)

_LIVE_LABEL_SOURCES = {
    "live_status",
    "live_input",
    "live_reply",
    "live_tool",
    "live_error",
    "live_stop",
}

# Desktop-task "churn" label sources — the noisy per-step status/action chatter
# from a running task ("Orynning…", "Searching…", "Clicking Save"). While Gemini
# Live is the active driver it OWNS the bubble text (Live narrates the task out
# loud), so this churn is muted to stop the bubble flashing between the live
# transcript and the task's step labels. The flying cursor still shows what's
# happening on screen. The one exception is `task_result`: a task's final answer
# is meaningful and a single, non-flickering update, so it surfaces even mid-Live.
_TASK_CHURN_SOURCES = {
    "task_status",
    "task_prime",
    "task_action",
    "system_wait",
}

# Optional diagnostic: record every textbox-label decision — what text was shown, its
# source, and (when suppressed) why — to logs/textbox_labels.jsonl. It lets us see
# exactly what the bubble displayed over a session and prune redundant/cluttered
# labels. Opt-in (ORYNN_LABEL_LOG=1) because it fires on nearly every UI tick.
_LABEL_LOG_ENABLED = str(os.getenv("ORYNN_LABEL_LOG") or "").strip().lower() in {"1", "true", "yes", "on"}
_LABEL_LOG_PATH = Path(__file__).resolve().parents[2] / "logs" / "textbox_labels.jsonl"

# Within this window, re-setting the SAME bubble text is a no-op repaint and is
# skipped (de-clutter). Kept under the overlay's ~10s auto-collapse so a genuine
# re-show after the bubble has rested to its orb still paints.
_LABEL_DEDUP_WINDOW = 4.0


def _log_label(text: str, source: str, action: str, reason: str, live_running: bool) -> None:
    """Append one label decision to the label diagnostic log (best-effort, no-throw).
    action is 'shown' or 'muted'; reason explains a mute ('' when shown)."""
    if not _LABEL_LOG_ENABLED:
        return
    try:
        rec = {
            "ts": round(time.time(), 3),
            "action": action,
            "source": source,
            "reason": reason,
            "live": bool(live_running),
            "text": str(text)[:200],
        }
        _LABEL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_LABEL_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _clean_text(value: Any) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _short(value: Any, limit: int = 56) -> str:
    text = _clean_text(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MD_TABLE_SEP_RE = re.compile(r"(?m)^\s*\|?\s*:?-{2,}[-\s|:]*$")


def _strip_markdown(value: Any) -> str:
    """Flatten model markdown into plain prose for the popup bubble — no
    asterisks, headings, tables, bullets, or code fences."""
    text = str(value or "")
    text = text.replace("```", " ")
    text = _MD_LINK_RE.sub(r"\1", text)          # [text](url) -> text
    text = _MD_TABLE_SEP_RE.sub(" ", text)       # drop |---|---| separator rows
    text = text.replace("|", " ")                # table cell pipes -> spaces
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)     # headings
    text = re.sub(r"(?m)^\s{0,3}>\s?", "", text)          # blockquotes
    text = re.sub(r"(?m)^\s{0,3}[-*+]\s+", "", text)      # bullet lists
    text = re.sub(r"(?m)^\s{0,3}\d+\.\s+", "", text)      # numbered lists
    text = text.replace("**", "").replace("__", "")       # bold
    text = re.sub(r"[*_`~]", "", text)                    # leftover emphasis/code
    return text


def _merge_streamed_text(current: str, chunk: str) -> str:
    """Merge either delta or cumulative transcript chunks without duplication."""
    current = str(current or "")
    chunk = str(chunk or "")
    if not current:
        return chunk
    if not chunk:
        return current
    if chunk == current or current.endswith(chunk):
        return current
    if chunk.startswith(current):
        return chunk
    max_overlap = min(len(current), len(chunk))
    for size in range(max_overlap, 0, -1):
        if current[-size:] == chunk[:size]:
            return current + chunk[size:]
    return current + chunk


def _clean_live_status(value: Any) -> str:
    text = _clean_text(value)
    low = text.lower()
    if low.startswith("gemini live tool:"):
        return "Working..."
    if low == "gemini live listening":
        return "Listening"
    return text


# Playful "working" words shown in the bubble while the agent is busy — rotated
# at random as status events arrive, Claude-Code style ("Brewing", "Noodling"…).
_THINKING_WORDS = [
    "Thinking", "Brewing", "Cooking", "Noodling", "Percolating", "Pondering",
    "Conjuring", "Cogitating", "Scheming", "Mulling", "Tinkering", "Finagling",
    "Vibing", "Crunching", "Wrangling", "Plotting", "Hatching", "Summoning",
    "Channelling", "Whirring", "Spelunking", "Marinating", "Simmering",
    "Manifesting", "Untangling", "Orynning", "Computing", "Calculating",
]
_last_thinking_word = [""]


def _thinking_word() -> str:
    """A random playful 'busy' word, avoiding an immediate repeat."""
    import random
    pool = [w for w in _THINKING_WORDS if w != _last_thinking_word[0]] or _THINKING_WORDS
    word = random.choice(pool)
    _last_thinking_word[0] = word
    return word + "…"


def _humanize_status(message: Any) -> str:
    """Collapse the agent's noisy per-step status spam into a friendly label.

    "Thinking through step 3…", "Working on step 3…", and "…waiting on model
    (step 3, 12s)" all become a random playful word ("Brewing…", "Noodling…").
    Other messages keep their text with any "step N" fragments stripped.
    """
    text = _clean_text(message)
    low = text.lower()
    if not text:
        return _thinking_word()
    if "waiting on model" in low or low.startswith(("thinking", "working")):
        return _thinking_word()
    # Strip any leftover "step N" / "(step N, Xs)" fragments from other messages.
    cleaned = re.sub(r"\s*\(?\bstep\s*\d+(?:,\s*\d+\s*s)?\)?", "", text, flags=re.I)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" …·-")
    return cleaned or _thinking_word()


def _strip_hardening(goal: str) -> str:
    goal = str(goal or "")
    if goal.startswith(DESKTOP_HARDENING):
        goal = goal[len(DESKTOP_HARDENING):]
    # Drop the voice-brevity reply-format note appended in build_task_payload so
    # it never shows up when echoing the goal back in a label.
    idx = goal.find(VOICE_BREVITY)
    if idx != -1:
        goal = goal[:idx]
    else:
        marker = "[Reply format:"
        if marker in goal:
            goal = goal[: goal.find(marker)]
    return goal.rstrip()


def _detect_mode(goal: str) -> str:
    try:
        from app.providers import detect_task_mode

        detected = detect_task_mode(goal)
    except Exception:
        detected = "auto"
    if detected in {"computer", "computer_isolated"}:
        return "computer"
    if detected == "computer_use":
        return "computer_use"
    if detected == "coding":
        return "coding"
    return "auto"


def _screen_size() -> tuple[int, int]:
    try:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return 1280, 800
        geo = screen.geometry()
        return max(1, int(geo.width())), max(1, int(geo.height()))
    except Exception:
        return 1280, 800


VOICE_BREVITY = (
    "\n\n[Reply format: your final answer is shown in a tiny on-screen popup. "
    "Use plain text only — no markdown, asterisks, headings, tables, or bullet "
    "lists. Keep it to one or two short sentences (about 200 characters max). "
    "If the full answer won't fit, give only the single most important point.]"
)


def _force_utf8_stdio(streams: Any = None) -> None:
    """Make stdout/stderr UTF-8 with errors='replace' so model text (smart quotes,
    em / non-breaking hyphens, emoji) can NEVER crash a print on the Windows cp1252
    console — a UnicodeEncodeError in a log line must not take down a thread."""
    for s in (streams if streams is not None else (sys.stdout, sys.stderr)):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def build_task_payload(goal: str) -> dict[str, Any]:
    mode = _detect_mode(goal)
    # A pure "open/launch/switch to <known app>" command runs the deterministic
    # fast-path server-side (no LLM), so keep its goal RAW — prepending the long
    # desktop-hardening prompt or the voice-brevity note would only bloat it (and
    # the hardening prompt is what once pushed the goal past the 2000-char cap).
    try:
        from app.tools import detect_app_launch_intent
        is_app_launch = detect_app_launch_intent(goal) is not None
    except Exception:
        is_app_launch = False
    payload_goal = goal
    if not is_app_launch:
        if mode in {"computer", "computer_use", "computer_isolated"}:
            payload_goal = DESKTOP_HARDENING + goal
        payload_goal = payload_goal + VOICE_BREVITY
    width, height = _screen_size()
    return {
        "task_id": "clicky-" + secrets.token_hex(5),
        "goal": payload_goal,
        "mode": mode,
        "screen_width": width,
        "screen_height": height,
        # Floating-bubble tasks run with NO approval prompts — stop with the
        # Ctrl+Shift+X hotkey instead. (Catastrophic shell commands still gate.)
        "autonomy_level": "autonomous",
        "thinking_budget": "off",
    }


class BackendClient:
    def __init__(self, port: int):
        self.base_url = f"http://127.0.0.1:{int(port)}"
        self._cookies = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._cookies)
        )
        self._session_ready = False

    def ensure_session(self) -> bool:
        if self._session_ready:
            return True
        try:
            self.request("POST", "/api/session", timeout=2.0, require_session=False)
            self._session_ready = True
            return True
        except Exception:
            return False

    def request(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
        timeout: float = 4.0,
        require_session: bool = True,
    ) -> dict[str, Any]:
        if require_session and not self.ensure_session():
            raise RuntimeError("Backend session unavailable")
        body = None
        headers = {"Accept": "application/json"}
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            self.base_url + path,
            data=body,
            headers=headers,
            method=method.upper(),
        )
        with self._opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        if not raw:
            return {}
        return json.loads(raw)


class OverlayController(QObject):
    labelRequested = Signal(str)
    listenRequested = Signal()
    quitRequested = Signal()
    # Carries a parsed overlay-action payload from the poll thread to the GUI
    # thread, where it drives the VirtualCursorOverlay (fly-to-target, focus
    # ring, app glow). Cross-thread Qt signals marshal automatically.
    overlayActionRequested = Signal(dict)
    cursorStateRequested = Signal(str)  # "idle" | "listening" | "thinking"
    audioLevelRequested = Signal(float)  # live mic level → reactive waveform
    notifyRequested = Signal(str, str)   # (title, message) → tray toast

    def __init__(self, port: int, speak_replies: bool = False):
        super().__init__()
        self.client = BackendClient(port)
        self._stop = threading.Event()
        self._cursor = 0
        self._voice_task_ids: set[str] = set()
        self._speak_replies = bool(speak_replies)
        self._recorder: Any = None
        self._recording = False
        self._ptt_lock = threading.Lock()
        self._ptt_combo = "ctrl+shift+space"
        self._live_combo = "ctrl+shift+l"
        self._stop_combo = "ctrl+shift+x"
        self._overlay: Any = None       # VirtualCursorOverlay, attached in main()
        self._tray: Any = None          # QSystemTrayIcon, for completion toasts
        self._effects_enabled = True    # honoured from the show_action_glow pref
        self._active_task_running = False
        # Goal of the desktop task currently running (if any), so Live can name it
        # when it refuses to start a second, colliding action on top of it.
        self._active_task_goal: str = ""
        self._consecutive_failures = 0
        # Tasks Live launched (task_id -> short goal), so when one finishes we can
        # feed the outcome back to the conversation instead of losing it.
        self._live_task_ids: dict[str, str] = {}
        # The most recent finished Live task's outcome, surfaced via
        # get_companion_status so Live can answer "did it work?" for longer jobs.
        self._last_task_result: dict[str, Any] | None = None
        # Mid-task voice narration (brief §6): while a Live-launched task runs, feed
        # throttled, humanized milestones into the conversation so Live can speak
        # progress ("clicking New Agent") instead of going silent after the ack.
        self._live_narration_last = 0.0
        self._live_narration_text = ""
        # Cached knowledge-memory prompt block, refreshed off the Live event loop (poll
        # thread + after remember/forget). dynamic_context reads this cache so it never
        # makes a blocking HTTP call on the event loop during (re)connect.
        self._knowledge_block_cache = ""
        self._knowledge_refreshed_at = 0.0
        self._live: Any = None
        self._live_cancel = threading.Event()
        # Wake-word mode: a background listener wakes Live on "Orynn" and lets it
        # sleep again after idle. _live_last_activity tracks the last user speech so
        # the session sleeps back to local wake-listening instead of streaming forever.
        self._wake_stop = threading.Event()
        self._wake_thread: threading.Thread | None = None
        self._live_last_activity = 0.0
        self._live_generation = 0
        self._live_error_generation: int | None = None
        self._desktop_tools: Any = None
        # Gemini Live streams its spoken reply as many tiny transcript chunks;
        # accumulate them into the running sentence instead of flashing one word
        # at a time. _live_reply_done=True means the next chunk starts a new reply.
        self._live_input_buffer = ""
        self._live_input_done = True
        self._live_reply_buffer = ""
        self._live_reply_done = True
        self._label_protect_until = 0.0
        self._label_protect_source = ""
        # Last text actually painted + when, so an unchanged label can't repaint and
        # flicker the bubble. Time-bounded so a legit re-show after the bubble
        # auto-collapses to its orb still paints.
        self._last_emitted_label = ""
        self._last_emitted_at = 0.0
        # _set_label is called from the Live audio thread, the poll thread and the
        # GUI thread; guard the read-decide-write of the protection window so the
        # arbitration can't race into a flicker.
        self._label_lock = threading.Lock()
        self.listenRequested.connect(self.listen_once)
        self.notifyRequested.connect(self._on_notify)

    def _reset_live_buffers(self) -> None:
        self._live_input_buffer = ""
        self._live_input_done = True
        self._live_reply_buffer = ""
        self._live_reply_done = True

    def _clear_live_if_inactive(self) -> None:
        live = self._live
        if live is None:
            return
        try:
            if live.is_running():
                return
        except Exception:
            pass
        self._live = None

    def _next_live_generation(self) -> int:
        self._live_generation += 1
        self._live_error_generation = None
        return self._live_generation

    def _live_generation_current(self, generation: int | None) -> bool:
        return generation is None or generation == self._live_generation

    def attach_overlay(self, overlay: Any) -> None:
        """Give the controller the cursor overlay so it can drive fly-to-target
        animations. Wires the cross-thread signals to GUI-thread handlers."""
        self._overlay = overlay
        self.overlayActionRequested.connect(self._on_overlay_action)
        self.cursorStateRequested.connect(self._on_cursor_state)
        self.audioLevelRequested.connect(self._on_audio_level)

    def set_tray(self, tray: Any) -> None:
        """Give the controller the tray icon so it can show completion toasts."""
        self._tray = tray

    def _on_audio_level(self, level: float) -> None:
        if self._overlay is not None and hasattr(self._overlay, "set_audio_level"):
            try:
                self._overlay.set_audio_level(level)
            except Exception:
                pass

    def _on_notify(self, title: str, message: str) -> None:
        if self._tray is None or not message:
            return
        try:
            self._tray.showMessage(title, message, QSystemTrayIcon.Information, 5000)
        except Exception:
            pass

    def _live_is_running(self) -> bool:
        live = self._live
        try:
            return bool(live is not None and live.is_running())
        except Exception:
            return False

    def _set_live_owns_bubble(self, owns: bool) -> None:
        """Tell the overlay whether Gemini Live currently owns the bubble text, so a
        Live-spawned desktop task's flying-cursor step labels don't flash over the
        live conversation. (The cursor still flies; only the bubble text is held.)"""
        ov = self._overlay
        if ov is not None and hasattr(ov, "set_companion_text_locked"):
            try:
                ov.set_companion_text_locked(bool(owns))
            except Exception:
                pass

    # ── Wake-word mode ───────────────────────────────────────────────────────
    @staticmethod
    def _wake_word_display() -> str:
        return (os.getenv("ORYNN_WAKE_WORD") or "Orynn").strip().title() or "Orynn"

    def start_wake_listener(self) -> None:
        """Run Live as a wake-word agent: stay asleep, listening LOCALLY (offline,
        no cloud streaming) for 'Orynn', then connect Live; sleep again after idle.
        Safe to call once at startup."""
        if self._wake_thread and self._wake_thread.is_alive():
            return
        self._wake_stop.clear()
        self._wake_thread = threading.Thread(target=self._wake_loop, daemon=True)
        self._wake_thread.start()
        self._set_label(f"Say “{self._wake_word_display()}” to wake me", source="system", force=True)

    def stop_wake_listener(self) -> None:
        self._wake_stop.set()

    def _wake_matches(self, text: str) -> bool:
        try:
            from . import voice
            return bool(voice.matches_wake_word(text))
        except Exception:
            return False

    def _wake_loop(self) -> None:
        from .gemini_live import live_idle_sleep_seconds
        while not self._stop.is_set() and not self._wake_stop.is_set():
            if self._live_is_running():
                # Live is active — don't fight it for the mic; just enforce idle-sleep.
                self._maybe_sleep_live(live_idle_sleep_seconds())
                self._stop.wait(1.0)
                continue
            try:
                from . import voice
                text = voice.listen_for_wake(timeout=5.0)
            except Exception:
                self._stop.wait(1.0)
                continue
            if self._stop.is_set() or self._wake_stop.is_set():
                break
            if text and self._wake_matches(text) and not self._live_is_running():
                try:
                    from . import voice
                    voice.cue("start")
                except Exception:
                    pass
                self._live_last_activity = time.monotonic()
                self._toggle_live()  # starts Live (safe from this worker thread)

    def _maybe_sleep_live(self, idle_seconds: float) -> None:
        """Put Live back to sleep (→ wake-listening) after a stretch of no user speech,
        so a wake-mode session never streams forever."""
        if not self._live_is_running():
            return
        last = self._live_last_activity or time.monotonic()
        if (time.monotonic() - last) < idle_seconds:
            return
        live = self._live
        try:
            from . import voice
            voice.cue("stop")
        except Exception:
            pass
        self._next_live_generation()
        self._live_cancel.set()
        if live is not None:
            try:
                live.stop()
            except Exception:
                pass
        self._live = None
        self._set_live_owns_bubble(False)
        self.cursorStateRequested.emit("idle")
        self._set_label(f"Asleep — say “{self._wake_word_display()}” to wake me", source="live_stop", force=True)

    def _set_label(
        self,
        text: Any,
        *,
        source: str = "system",
        hold_seconds: float | None = None,
        force: bool = False,
    ) -> bool:
        label = _clean_text(text)
        if not label:
            return False
        with self._label_lock:
            now = time.monotonic()
            protected = now < self._label_protect_until
            # "Live is holding the bubble" = a Live label is still inside its hold
            # window. Requiring `protected` (not just the source) means task labels
            # resume the instant Live's hold expires / Live stops — no stale lockout.
            live_holding = protected and self._label_protect_source in _LIVE_LABEL_SOURCES
            live_running = self._live_is_running()

            if not force:
                # Gemini Live owns the bubble while it drives: mute the desktop
                # task's per-step churn so it can't flash over the conversation.
                # (task_result — the final answer — is deliberately not in the
                # churn set, so a task's outcome still surfaces during Live.)
                if source in _TASK_CHURN_SOURCES and (live_running or live_holding):
                    _log_label(label, source, "muted", "task_churn_under_live", live_running)
                    return False
                # Don't let the periodic "Listening" status wipe a fresher, more
                # meaningful Live label (what the user said / the reply / a tool).
                if (
                    source == "live_status"
                    and live_holding
                    and self._label_protect_source in {"live_input", "live_reply", "live_tool"}
                ):
                    _log_label(label, source, "muted", "live_status_under_hold", live_running)
                    return False

            if hold_seconds is None:
                if source == "live_tool":
                    hold_seconds = LIVE_TOOL_LABEL_HOLD_SECONDS
                elif source in _LIVE_LABEL_SOURCES:
                    hold_seconds = LIVE_LABEL_HOLD_SECONDS
                elif source in {"task_action", "task_result", "voice", "system"}:
                    hold_seconds = 1.2
                else:
                    hold_seconds = 0.0
            if hold_seconds > 0:
                next_until = now + float(hold_seconds)
                if next_until >= self._label_protect_until:
                    self._label_protect_until = next_until
                    self._label_protect_source = source
            # Skip a no-op repaint of the text that's already on screen (de-clutter),
            # but only within a short window so a re-show after the bubble has rested
            # to its orb still paints.
            duplicate = (
                label == self._last_emitted_label
                and (now - self._last_emitted_at) < _LABEL_DEDUP_WINDOW
            )
            if not duplicate:
                self._last_emitted_label = label
                self._last_emitted_at = now

        if duplicate:
            _log_label(label, source, "muted", "duplicate_of_current", live_running)
            return False
        _log_label(label, source, "shown", "", live_running)
        self.labelRequested.emit(label)
        return True

    def start(self) -> None:
        threading.Thread(target=self._poll_loop, daemon=True).start()
        self._load_preferences_async()

    def stop(self) -> None:
        self._stop.set()
        self._live_cancel.set()
        live = self._live
        if live is not None:
            try:
                live.stop()
            except Exception:
                pass

    def install_hotkey(self) -> bool:
        """Push-to-talk: hold the hotkey to record, release to transcribe + send.

        Default hold key is Ctrl+Shift+Space (override with ORYNN_PTT_KEY, e.g.
        "f8"). The classic tap-to-talk on Ctrl+Shift+M is kept as a fallback.
        """
        try:
            import keyboard

            self._ptt_combo = (os.getenv("ORYNN_PTT_KEY") or "ctrl+shift+space").strip()
            # Press starts recording; a watcher thread detects release (combo
            # trigger_on_release is unreliable in the keyboard lib, so we poll).
            keyboard.add_hotkey(self._ptt_combo, self._ptt_start)
            # Backwards-compatible tap-to-talk (records until silence).
            keyboard.add_hotkey("ctrl+shift+m", self.listenRequested.emit)
            # Real-time Gemini Live conversation (toggle on/off).
            self._live_combo = (os.getenv("ORYNN_LIVE_KEY") or "ctrl+shift+l").strip()
            keyboard.add_hotkey(self._live_combo, self._toggle_live)
            # Emergency stop: instantly kill whatever the agent is doing.
            self._stop_combo = (os.getenv("ORYNN_STOP_KEY") or "ctrl+shift+x").strip()
            keyboard.add_hotkey(self._stop_combo, self._stop_all)
            print(f"[clicky] push-to-talk: hold {self._ptt_combo} (tap Ctrl+Shift+M); "
                  f"live: {self._live_combo}; stop: {self._stop_combo}", flush=True)
            return True
        except Exception as exc:
            print(f"[clicky] voice hotkey unavailable: {exc}", flush=True)
            return False

    # ── Push-to-talk ─────────────────────────────────────────────────────────
    # Hold the hotkey to record; release to send. Tap Esc while holding to
    # cancel. A safety cap stops a stuck key from recording forever.
    PTT_MAX_SECONDS = 60.0
    PTT_MIN_SECONDS = 0.4  # shorter than this = accidental tap, ignore

    def _ptt_start(self) -> None:
        with self._ptt_lock:
            if self._recording:
                return
            try:
                from . import voice
            except Exception:
                self.cursorStateRequested.emit("idle")
                self._set_label("Voice unavailable", source="voice", force=True)
                return
            if not voice.push_to_talk_available():
                self.cursorStateRequested.emit("idle")
                if voice.stt_available():
                    self._set_label("Hold-to-talk unavailable; tap Ctrl+Shift+M", source="voice", force=True)
                else:
                    self._set_label("Voice unavailable", source="voice", force=True)
                return
            recorder = voice.Recorder()
            if not recorder.start():
                self.cursorStateRequested.emit("idle")
                self._set_label("Mic unavailable", source="voice", force=True)
                return
            self._recorder = recorder
            self._recording = True
            voice.cue("start")
            self.cursorStateRequested.emit("listening")
            self._set_label("Listening…", source="voice", force=True)
        threading.Thread(target=self._ptt_watch, daemon=True).start()

    def _ptt_watch(self) -> None:
        """Poll the hotkey until released (more reliable than the keyboard lib's
        trigger_on_release for combos). Esc cancels; a max cap is enforced."""
        try:
            import keyboard
        except Exception:
            self._ptt_stop(cancelled=True)
            return
        start = time.time()
        cancelled = False
        while self._recording:
            # Feed the live mic level to the reactive listening waveform.
            rec = self._recorder
            if rec is not None:
                try:
                    self.audioLevelRequested.emit(rec.level())
                except Exception:
                    pass
            try:
                held = keyboard.is_pressed(self._ptt_combo)
                esc = keyboard.is_pressed("esc")
            except Exception:
                held, esc = False, False
            if esc:
                cancelled = True
                break
            if not held:
                break
            if time.time() - start >= self.PTT_MAX_SECONDS:
                break
            time.sleep(0.05)
        self._ptt_stop(cancelled=cancelled)

    def _discard_recording(self) -> None:
        """Stop and forget any active recorder without transcribing it."""
        with self._ptt_lock:
            self._recording = False
            recorder = self._recorder
            self._recorder = None
        if recorder is None:
            return
        try:
            recorder.stop()
        except Exception:
            pass

    def _ptt_stop(self, cancelled: bool = False) -> None:
        with self._ptt_lock:
            if not self._recording:
                return
            self._recording = False
            recorder = self._recorder
            self._recorder = None
        if recorder is None:
            return
        threading.Thread(
            target=self._ptt_finish, args=(recorder, cancelled), daemon=True
        ).start()

    def _ptt_finish(self, recorder: Any, cancelled: bool = False) -> None:
        from . import voice

        try:
            wav = recorder.stop()
        except Exception:
            wav = b""
        if cancelled:
            voice.cue("cancel")
            self.cursorStateRequested.emit("idle")
            self._set_label("Cancelled", source="voice", force=True)
            return
        # Ignore accidental ultra-short taps without burning an API call.
        if voice.wav_seconds(wav) < self.PTT_MIN_SECONDS:
            voice.cue("error")
            self.cursorStateRequested.emit("idle")
            self._set_label("Didn't catch that", source="voice", force=True)
            return
        voice.cue("stop")
        self.cursorStateRequested.emit("thinking")
        self._set_label(_thinking_word(), source="voice", force=True)
        try:
            transcript = voice.transcribe_wav(wav) or ""
        except Exception:
            transcript = ""
        transcript = _clean_text(transcript)
        if not transcript:
            voice.cue("error")
            self.cursorStateRequested.emit("idle")
            self._set_label("Didn't catch that", source="voice", force=True)
            return
        self._set_label("Heard: " + _short(transcript, 150), source="voice", force=True)
        self._submit_voice_task(transcript)

    # ── Emergency stop ───────────────────────────────────────────────────────
    def _stop_all(self) -> None:
        """Hotkey handler: instantly halt everything — cancel any recording, stop
        speech, and KILL every running/queued task. Runs off the keyboard thread
        so the UI stays responsive."""
        threading.Thread(target=self._stop_all_worker, daemon=True).start()

    def _kill_active_tasks(self) -> int:
        stopped = 0
        data = self.client.request("GET", "/api/active-tasks", timeout=3.0)
        tasks = data.get("tasks", []) if isinstance(data, dict) else []
        for t in tasks:
            if not isinstance(t, dict):
                continue
            tid = str(t.get("id") or t.get("task_id") or "").strip()
            if not tid:
                continue
            try:
                self.client.request("POST", f"/api/tasks/{tid}/kill", timeout=5.0)
                stopped += 1
            except Exception:
                pass
        return stopped

    def _stop_all_worker(self) -> None:
        # 1. Drop any in-progress voice capture and stop the spinner.
        recording_was_active = bool(self._recording)
        self._discard_recording()
        self._live_cancel.set()
        live = self._live
        live_was_running = False
        if live is not None:
            try:
                live_was_running = bool(live.is_running())
                live.stop()
            except Exception:
                pass
        self._set_live_owns_bubble(False)
        try:
            from . import voice
            voice.stop_speaking()
            voice.cue("cancel")
        except Exception:
            pass
        self.cursorStateRequested.emit("idle")
        # 2. Kill every active task (the kill flag halts the worker at its next
        #    checkpoint — more aggressive than a plain cancel).
        stopped = 0
        try:
            stopped = self._kill_active_tasks()
        except Exception:
            pass
        self._active_task_running = False
        self._active_task_goal = ""
        did_stop = bool(stopped or live_was_running or recording_was_active)
        self._set_label("Stopped" if did_stop else "Nothing to stop", source="live_stop", force=True)

    # ── Gemini Live conversation ─────────────────────────────────────────────
    def _toggle_live(self) -> None:
        live = self._live
        if live is not None and live.is_running():
            self._next_live_generation()
            self._live_cancel.set()
            live.stop()
            self._live = None
            self._set_live_owns_bubble(False)
            self.cursorStateRequested.emit("idle")
            self._set_label("Gemini Live off", source="live_stop", force=True)
            return
        try:
            from .gemini_live import GeminiLiveCallbacks, GeminiLiveCompanion

            generation = self._next_live_generation()
            callbacks = GeminiLiveCallbacks(
                on_status=lambda text, gen=generation: self._live_status(text, gen),
                on_input_transcript=(
                    lambda text, finished, gen=generation:
                    self._live_input_transcript(text, finished, gen)
                ),
                on_output_transcript=(
                    lambda text, finished, gen=generation:
                    self._live_output_transcript(text, finished, gen)
                ),
                on_audio_level=(
                    lambda level, gen=generation:
                    self.audioLevelRequested.emit(level)
                    if self._live_generation_current(gen) else None
                ),
                on_error=lambda text, gen=generation: self._live_error(text, gen),
                on_stopped=lambda text, gen=generation: self._live_stopped(text, gen),
                on_tool=lambda name, args, gen=generation: self._live_tool_for_generation(gen, name, args),
            )
            live = GeminiLiveCompanion(callbacks)
            # Inject Orynn's knowledge memory into the Live system prompt on every
            # (re)connect, so it knows the user's setup/vocabulary in conversation.
            live.dynamic_context = self._live_knowledge_block
            self._live = live
            if live.start():
                self._live_cancel.clear()
                self._reset_live_buffers()
                self._live_last_activity = time.monotonic()
                self._set_live_owns_bubble(True)
                self.cursorStateRequested.emit("listening")
                self._set_label("Starting Gemini Live...", source="live_status", force=True)
            else:
                self._live = None
                self._set_live_owns_bubble(False)
        except Exception as exc:
            self._live = None
            self._set_live_owns_bubble(False)
            self.cursorStateRequested.emit("idle")
            self._set_label("Gemini Live unavailable", source="live_error", force=True)
            print(f"[clicky] Gemini Live unavailable: {exc}", flush=True)

    def _live_status(self, text: str, generation: int | None = None) -> None:
        if not self._live_generation_current(generation):
            return
        msg = _clean_live_status(text) or "Gemini Live"
        if msg == "Live tool call failed":
            self.cursorStateRequested.emit("thinking")
            self._set_label(msg, source="live_tool", force=True)
            return
        if "listening" in msg.lower():
            self.cursorStateRequested.emit("listening")
        self._set_label(_short(msg, 150), source="live_status")

    def _live_input_transcript(self, text: str, finished: bool, generation: int | None = None) -> None:
        if not self._live_generation_current(generation):
            return
        # The user spoke — refresh activity so wake-mode's idle-sleep timer resets.
        self._live_last_activity = time.monotonic()
        chunk = text or ""
        # Turn-boundary finalize: Gemini rarely flags INPUT transcription as finished,
        # so the caller closes the turn at turn_complete with an empty finished signal.
        # Just mark the turn done so the NEXT utterance starts a fresh buffer — without
        # re-rendering the old input over the reply. Without this the bubble concatenates
        # every past turn ("Hello.I need help...Ah! What does this page say?Ah!...").
        if finished and not chunk:
            self._live_input_done = True
            return
        if not chunk:
            return
        if self._live_input_done:
            self._live_input_buffer = ""
            self._live_input_done = False
        self._live_input_buffer = _merge_streamed_text(self._live_input_buffer, chunk)
        heard = _short(_strip_markdown(self._live_input_buffer).strip(), 150)
        if heard:
            prefix = "Heard: " if finished else "Hearing: "
            self.cursorStateRequested.emit("listening")
            self._set_label(prefix + heard, source="live_input", force=True)
        if finished:
            self._live_input_done = True
            self._live_reply_done = True

    def _live_output_transcript(self, text: str, finished: bool, generation: int | None = None) -> None:
        if not self._live_generation_current(generation):
            return
        # Gemini sends the spoken reply as incremental chunks. Append them so the
        # bubble shows the growing sentence, not one flashing word at a time.
        chunk = text or ""
        if finished and not chunk:
            self._live_reply_done = True
            self.cursorStateRequested.emit("listening")
            return
        if self._live_reply_done:
            self._live_reply_buffer = ""
            self._live_reply_done = False
        self._live_reply_buffer = _merge_streamed_text(self._live_reply_buffer, chunk)
        display = _short(_strip_markdown(self._live_reply_buffer).strip(), 220)
        if display:
            self.cursorStateRequested.emit("thinking")
            self._set_label(display, source="live_reply", force=True)
        if finished:
            self._live_reply_done = True
            self.cursorStateRequested.emit("listening")

    def _live_error(self, text: str, generation: int | None = None) -> None:
        if not self._live_generation_current(generation):
            return
        self.cursorStateRequested.emit("idle")
        self._live_cancel.set()
        self._live_error_generation = generation if generation is not None else self._live_generation
        self._live = None
        self._set_live_owns_bubble(False)
        self._set_label(_short(text or "Gemini Live error", 180), source="live_error", force=True)

    def _live_stopped(self, text: str = "", generation: int | None = None) -> None:
        if not self._live_generation_current(generation):
            return
        current_generation = generation if generation is not None else self._live_generation
        self.cursorStateRequested.emit("idle")
        self._reset_live_buffers()
        self._live = None
        self._set_live_owns_bubble(False)
        if self._live_error_generation == current_generation:
            self._live_error_generation = None
            return
        self._set_label(_short(text or "Gemini Live stopped", 120), source="live_stop", force=True)

    def _live_desktop_tools(self) -> Any:
        tools = self._desktop_tools
        if tools is not None:
            return tools
        from app.tools import ToolExecutor

        raw = os.getenv("ORYNN_WORKSPACE") or os.getenv("AI_COMPUTER_WORKSPACE")
        workspace = Path(raw).expanduser() if raw else Path(__file__).resolve().parents[2]
        try:
            workspace.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        self._desktop_tools = ToolExecutor(workspace)
        return self._desktop_tools

    @staticmethod
    def _live_float(value: Any, default: float, low: float, high: float) -> float:
        try:
            parsed = float(value)
        except Exception:
            parsed = default
        return max(low, min(high, parsed))

    @staticmethod
    def _live_int(value: Any, default: int, low: int, high: int) -> int:
        try:
            parsed = int(value)
        except Exception:
            parsed = default
        return max(low, min(high, parsed))

    @staticmethod
    def _live_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value or "").strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _normalize_keys(keys: Any) -> str:
        aliases = {
            "control": "ctrl",
            "ctl": "ctrl",
            "windows": "win",
            "window": "win",
            "cmd": "win",
            "command": "win",
            "spacebar": "space",
        }
        order = {"ctrl": 0, "shift": 1, "alt": 2, "win": 3}
        parts = [
            aliases.get(p.strip().lower(), p.strip().lower())
            for p in str(keys or "").split("+")
            if p.strip()
        ]
        parts = sorted(dict.fromkeys(parts), key=lambda p: (order.get(p, 10), p))
        return "+".join(parts)

    @classmethod
    def _live_keys_allowed(cls, keys: Any) -> bool:
        normalized = cls._normalize_keys(keys)
        if not normalized:
            return False
        blocked = set(LIVE_BLOCKED_KEY_COMBOS)
        for env_name in ("ORYNN_LIVE_KEY", "ORYNN_STOP_KEY", "ORYNN_PTT_KEY"):
            env_combo = cls._normalize_keys(os.getenv(env_name) or "")
            if env_combo:
                blocked.add(env_combo)
        if normalized in blocked:
            return False
        parts = set(normalized.split("+"))
        if {"delete", "del"} & parts:
            return False
        if not re.fullmatch(r"[a-z0-9_+\- ]+", normalized):
            return False
        return True

    @staticmethod
    def _compact_live_tool_data(data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            return {}
        keep: dict[str, Any] = {}
        for key in (
            "items",
            "controls",
            "count",
            "target",
            "method",
            "verified",
            "title",
            "hwnd",
            "pid",
            "summary",
            "next_tools",
            "error",
        ):
            if key in data:
                keep[key] = data[key]
        try:
            encoded = json.dumps(keep, default=str)
        except Exception:
            return {"summary": _short(str(keep), 1800)}
        if len(encoded) > 1800:
            return {"summary": _short(encoded, 1800), "truncated": True}
        return keep

    def _emit_live_tool_overlay(self, data: Any, ok: bool) -> None:
        if not isinstance(data, dict):
            return
        overlay = data.get("overlay")
        if not isinstance(overlay, dict):
            return
        event = {"type": "action_result", "ok": ok, "overlay": overlay}
        if self._overlay_is_drawable(event):
            self.overlayActionRequested.emit(event)

    @staticmethod
    def _live_tool_target(data: Any) -> str:
        if not isinstance(data, dict):
            return ""
        overlay = data.get("overlay")
        if isinstance(overlay, dict):
            target = _clean_text(overlay.get("target") or "")
            if target:
                return target
        for key in ("target", "title", "name", "automation_id"):
            target = _clean_text(data.get(key) or "")
            if target:
                return target
        items = data.get("items")
        if isinstance(items, list) and items:
            first = items[0]
            if isinstance(first, dict):
                for key in ("name", "automation_id"):
                    target = _clean_text(first.get(key) or "")
                    if target:
                        return target
        return ""

    @staticmethod
    def _live_tool_graph_count(data: Any) -> int | None:
        if not isinstance(data, dict):
            return None
        graph = data.get("graph")
        if not isinstance(graph, dict):
            return None
        try:
            count = int(graph.get("named_control_count"))
        except Exception:
            return None
        return count if count >= 0 else None

    @staticmethod
    def _live_tool_title_from_output(output: str) -> str:
        match = re.search(r"(?:Focused window|Window ready):\s*'([^']+)'", output or "")
        return _clean_text(match.group(1)) if match else ""

    def _live_tool_display_label(self, action: str, ok: bool, output: str, data: Any) -> str:
        if not ok:
            return _short(output or "Action failed", 120)

        target = self._live_tool_target(data)
        if action in {"wait_for_window", "focus_window"} and not target:
            target = self._live_tool_title_from_output(output)

        if action == "wait_for_window":
            return f"Window ready: {_short(target, 70)}" if target else "Window ready"
        if action == "focus_window":
            return f"Focused: {_short(target, 70)}" if target else "Focused app"
        if action == "observe":
            count = self._live_tool_graph_count(data)
            return f"Mapped {count} controls" if count is not None else "Read app controls"
        if action == "find":
            return f"Found {_short(target, 80)}" if target else "Found control"
        if action == "wait":
            return f"Control ready: {_short(target, 80)}" if target else "Control ready"
        if action == "click":
            return f"Clicked {_short(target, 80)}" if target else "Clicked control"
        if action == "type":
            return f"Typed into {_short(target, 80)}" if target else "Typed into control"
        if action == "press_keys":
            return "Pressed shortcut"
        return "Done"

    def _live_tool_result(self, action: str, result: Any) -> dict[str, Any]:
        ok = bool(getattr(result, "ok", False))
        output = _clean_text(getattr(result, "output", "") or "")
        data = getattr(result, "data", None)
        self._emit_live_tool_overlay(data, ok)
        label = self._live_tool_display_label(action, ok, output, data)
        self._set_label(_short(label, 150), source="live_tool", force=True)
        self.cursorStateRequested.emit("thinking")
        response: dict[str, Any] = {
            "ok": ok,
            "action": action,
            "output": _short(output, 1200),
        }
        compact = self._compact_live_tool_data(data)
        if compact:
            response["data"] = compact
        return response

    def _live_cancel_requested(self) -> bool:
        if self._stop.is_set() or self._live_cancel.is_set():
            return True
        live = self._live
        try:
            if live is not None and hasattr(live, "stop_requested"):
                return bool(live.stop_requested())
        except Exception:
            pass
        return False

    def _raise_if_live_cancelled(self) -> None:
        if self._live_cancel_requested():
            raise InterruptedError("Gemini Live was stopped.")

    def _run_cancellable(self, fn: Any, *args: Any, poll: float = 0.12) -> Any:
        """Run a blocking call on a worker thread while watching the Live cancel flag,
        so 'stop' interrupts a long call (e.g. run_terminal) within ~poll seconds
        instead of only after it returns. Raises InterruptedError on cancel; the
        underlying call is left to finish in the background (its own timeout bounds it).
        Returns fn(*args), or re-raises whatever fn raised."""
        box: dict[str, Any] = {}
        done = threading.Event()

        def _worker() -> None:
            try:
                box["result"] = fn(*args)
            except BaseException as exc:  # noqa: BLE001 — surface any failure to the caller
                box["error"] = exc
            finally:
                done.set()

        threading.Thread(target=_worker, name="orynn-live-cancellable", daemon=True).start()
        while not done.wait(poll):
            if self._live_cancel_requested():
                raise InterruptedError("Gemini Live was stopped.")
        if "error" in box:
            raise box["error"]
        return box.get("result")

    def _run_live_interruptible_wait(self, runner: Any, timeout: float) -> Any:
        deadline = time.monotonic() + max(0.1, float(timeout))
        last_result = None
        while True:
            self._raise_if_live_cancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return last_result
            result = runner(min(0.45, max(0.1, remaining)))
            self._raise_if_live_cancelled()
            if bool(getattr(result, "ok", False)):
                return result
            last_result = result
            output = _clean_text(getattr(result, "output", "") or "").lower()
            if any(term in output for term in ("only available", "not available", "needs a")):
                return result
            if time.monotonic() >= deadline:
                return result

    def _run_live_desktop_action(self, action: str, args: dict[str, Any], *, fast_invoke_only: bool = False) -> Any:
        self._raise_if_live_cancelled()
        tools = self._live_desktop_tools()
        app = _clean_text(args.get("app") or "")
        title = _clean_text(args.get("title") or app)
        query = _clean_text(args.get("query") or "")
        # Cap below GEMINI_LIVE_TOOL_TIMEOUT so the bounded wait always finishes
        # before the outer tool timeout could fire (no leaked, "timed-out" thread).
        timeout = self._live_float(args.get("timeout"), 6.0, 0.5, 9.0)
        limit = self._live_int(args.get("limit"), 5, 1, 10)
        cap = self._live_int(args.get("cap"), 90, 20, 220)

        if action == "wait_for_window":
            if not title:
                raise ValueError("Missing title or app for wait_for_window.")
            return self._run_live_interruptible_wait(
                lambda step_timeout: tools.wait_for_window(
                    title,
                    timeout=step_timeout,
                    paint_seconds=0.05,
                ),
                timeout,
            )
        if action == "focus_window":
            if not title:
                raise ValueError("Missing title or app for focus_window.")
            result = tools.focus_window(title)
            self._raise_if_live_cancelled()
            return result
        if action == "observe":
            result = tools.adaptive_observe(app, cap=cap)
            self._raise_if_live_cancelled()
            return result
        if action == "find":
            if not query:
                raise ValueError("Missing query for find.")
            result = tools.uia_find(query, app, limit=limit)
            self._raise_if_live_cancelled()
            return result
        if action == "wait":
            if not query:
                raise ValueError("Missing query for wait.")
            return self._run_live_interruptible_wait(
                lambda step_timeout: tools.uia_wait(query, app, timeout=step_timeout),
                timeout,
            )
        if action == "click":
            if not query:
                raise ValueError("Missing query for click.")
            # Live's fast path forbids the pixel-click tier so a click either lands
            # cleanly via UIA (no mouse) or fails fast and escalates to the agent.
            result = tools.uia_click(query, app, allow_pixel_fallback=not fast_invoke_only)
            self._raise_if_live_cancelled()
            return result
        if action == "type":
            if not query:
                raise ValueError("Missing query for type.")
            text = str(args.get("text") or "")
            if not text.strip():
                raise ValueError("Missing text for type.")
            result = tools.uia_type(
                query,
                text,
                app,
                clear_first=self._live_bool(args.get("clear_first")),
                submit=self._live_bool(args.get("submit")),
                allow_pixel_fallback=not fast_invoke_only,
            )
            self._raise_if_live_cancelled()
            return result
        if action == "press_keys":
            keys = _clean_text(args.get("keys") or "")
            if not self._live_keys_allowed(keys):
                raise ValueError("That keyboard shortcut is not allowed from Live.")
            if app:
                focused = tools.focus_window(app)
                self._raise_if_live_cancelled()
                if not bool(getattr(focused, "ok", False)):
                    return focused
            result = tools.key(keys)
            self._raise_if_live_cancelled()
            return result
        if action == "scroll":
            # Negative scrolls down, positive up (pyautogui clicks; ~a notch per unit).
            amount = self._live_int(args.get("amount"), -10, -1000, 1000)
            if app:
                tools.focus_window(app)
                self._raise_if_live_cancelled()
            result = tools.scroll(amount)
            self._raise_if_live_cancelled()
            return result
        raise ValueError(f"Unsupported desktop action: {action}")

    def _goal_from_desktop_control(self, action: str, args: dict[str, Any]) -> str:
        """Turn a low-level desktop_control click/type call into a clear natural-language
        goal for the full agent, so a hard-routed action reads like an instruction the
        back office can plan around (brief §5.2 "convert to a clear goal string")."""
        app = _clean_text(args.get("app") or args.get("title") or "")
        query = _clean_text(args.get("query") or "")
        in_app = f" in {app}" if app else ""
        if action == "click":
            target = f'the "{query}" control' if query else "the requested control"
            return f"Click {target}{in_app}."
        if action == "type":
            text = str(args.get("text") or "").strip()
            field = f'the "{query}" field' if query else "the focused field"
            goal = f'Type "{text}" into {field}{in_app}.'
            if self._live_bool(args.get("submit")):
                goal += " Then submit it."
            return goal
        return ""

    @staticmethod
    def _live_fast_then_escalate_actions() -> set[str]:
        """desktop_control actions that try the FAST direct UIA primitive first and
        escalate to the full agent only on failure (click/type). ORYNN_LIVE_AUTOROUTE=off
        disables escalation entirely — a failed fast click just reports failure, the
        legacy behavior (brief §12 auto-route pref)."""
        mode = str(os.getenv("ORYNN_LIVE_AUTOROUTE", "") or "").strip().lower()
        if mode in ("off", "0", "false", "no", "none"):
            return set()
        return set(LIVE_UPGRADE_ACTIONS)

    def _desktop_control_route(self, args: dict[str, Any]) -> dict[str, Any] | None:
        """Model-path routing for a desktop_control click/type. Try a FAST UIA-only
        attempt first — instant (~1-4s), no agent spin-up, no enable_desktop_control
        prompt, and genuinely no mouse-jump (the pixel-click tier is disabled, so a
        click lands via an accessibility pattern or not at all). Escalate to the full
        agent only when that can't do it cleanly (no invoke pattern / Electron-locked /
        the click didn't visibly land) — that's where electron_unlock, pixel-clicking
        with the user's awareness, retries, and sequences live. Returns None for
        non-acting actions (observe/find/wait/focus/press_keys/scroll) so they run as
        bounded primitives unchanged. The model sends genuinely multi-step / app-launch
        / vague work to start_desktop_task directly, so it never reaches here. Lives at
        the MODEL boundary only — the deterministic gateway (Golden Five, push-to-talk)
        calls _live_tool directly and keeps its pixel fallback."""
        action = _clean_text(args.get("action") or "").lower().replace("-", "_")
        if action not in self._live_fast_then_escalate_actions():
            return None
        # Busy gate FIRST: the fast UIA click/type runs here, before _live_tool's gate,
        # so without this a model click during a running task would interleave a UIA
        # action with the agent and fight for focus (the exact thing the gate prevents).
        busy = self._busy_response()
        if busy is not None:
            return busy
        query = _clean_text(args.get("query") or "")
        if action == "click" and not query:
            self.cursorStateRequested.emit("thinking")
            self._set_label("Missing target to click", source="live_tool", force=True)
            return {"ok": False, "action": action, "message": "Missing query for click."}
        if action == "type" and not str(args.get("text") or "").strip():
            self.cursorStateRequested.emit("thinking")
            self._set_label("Missing text for type.", source="live_tool", force=True)
            return {"ok": False, "action": action, "message": "Missing text for type."}
        goal = self._goal_from_desktop_control(action, args)
        # Disruptive targets still need a spoken yes first. A confirmed one runs via
        # start_desktop_task (confirmed=true) — desktop_control has no confirmed flag.
        if self._goal_needs_consent(goal) and not self._live_bool(args.get("confirmed")):
            self.cursorStateRequested.emit("thinking")
            self._set_label("Needs your OK", source="live_tool", force=True)
            return {
                "ok": False,
                "needs_consent": True,
                "message": (
                    "This could change or send something that's hard to undo "
                    f'("{_short(goal, 90)}"). Do NOT do it yet. Ask the user out loud '
                    "to confirm; only if they clearly say yes, call start_desktop_task "
                    "with the same goal and confirmed set to true. If they say no, drop it."
                ),
            }
        # FAST path: UIA-only (no pixel fallback), so a click either lands cleanly via
        # an accessibility pattern — instant, no mouse-jump — or fails fast. A click
        # that "worked" only by stealing the mouse is exactly the flaky Electron case,
        # so we never let that count as success here.
        fast = self._live_desktop_control(args, fast_invoke_only=True)
        if isinstance(fast, dict) and fast.get("ok") and not self._fast_result_is_soft_fail(fast):
            return fast
        # Couldn't do it cleanly (no invoke pattern / Electron-locked / click didn't
        # visibly land) → escalate to the back office, which can electron_unlock,
        # pixel-click with the user's awareness, and retry. Live's spoken narration
        # owns the bubble while it drives, so don't flash a raw handoff status over it.
        self.cursorStateRequested.emit("thinking")
        if not self._live_is_running():
            self._set_label("Trying the full agent", source="live_tool", force=True)
        return self._live_tool("start_desktop_task", {"goal": goal})

    @staticmethod
    def _fast_result_is_soft_fail(fast: dict[str, Any]) -> bool:
        """A fast action returned ok=True but shouldn't be trusted as done: post-action
        verification explicitly said the UI didn't change (verified is False). Escalate
        those so the agent can do it for real. (Mouse-fallback successes can't reach
        here — the fast path runs UIA-only.)"""
        data = fast.get("data") if isinstance(fast.get("data"), dict) else {}
        return data.get("verified") is False

    def _live_desktop_control(self, args: dict[str, Any], *, fast_invoke_only: bool = False) -> dict[str, Any]:
        action = _clean_text(args.get("action") or "").lower().replace("-", "_")
        if action not in LIVE_DESKTOP_ACTIONS:
            self.cursorStateRequested.emit("thinking")
            self._set_label("Unsupported desktop action", source="live_tool", force=True)
            return {"ok": False, "message": f"Unknown desktop action: {action or '(missing)'}"}
        self.cursorStateRequested.emit("thinking")
        self._set_label(LIVE_DESKTOP_ACTION_LABELS[action], source="live_tool", force=True)
        try:
            result = self._run_live_desktop_action(action, args, fast_invoke_only=fast_invoke_only)
            return self._live_tool_result(action, result)
        except InterruptedError as exc:
            message = str(exc)[:200] or "Gemini Live was stopped."
            self.cursorStateRequested.emit("idle")
            self._set_label("Stopped", source="live_stop", force=True)
            return {"ok": False, "action": action, "message": message}
        except Exception as exc:
            message = str(exc)[:200] or "Desktop action failed."
            self.cursorStateRequested.emit("thinking")
            self._set_label(_short(message, 150), source="live_tool", force=True)
            return {"ok": False, "action": action, "message": message}

    def _live_tool_for_generation(self, generation: int, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if not self._live_generation_current(generation):
            return {"ok": False, "message": "Gemini Live session changed."}
        args = args if isinstance(args, dict) else {}
        # Model-driven dispatch only: a click/type tries the fast UIA primitive and
        # escalates to the full agent on failure (see _desktop_control_route). The
        # deterministic gateway (_live_tool direct) stays a pure UIA primitive path.
        if name == "desktop_control":
            routed = self._desktop_control_route(args)
            if routed is not None:
                return routed
        return self._live_tool(name, args)

    def _live_remember(self, args: dict[str, Any]) -> dict[str, Any]:
        """Save a durable fact into Orynn's knowledge memory (backend-persisted, shared
        with the desktop agent) so it's known in future conversations."""
        fact = _clean_text(args.get("fact") or "")
        if not fact:
            return {"ok": False, "message": "Nothing to remember — say the fact."}
        owner = _clean_text(args.get("owner") or "user").lower()
        category = _clean_text(args.get("category") or "fact").lower()
        try:
            self.client.request("POST", "/api/memory/facts",
                                {"text": fact, "app": _clean_text(args.get("app") or ""),
                                 "owner": owner if owner in ("user", "assistant") else "user",
                                 "category": category},
                                timeout=5.0)
        except Exception as exc:
            return {"ok": False, "message": f"Couldn't save that: {str(exc)[:120]}"}
        self._refresh_knowledge_block()  # so the next (re)connect injects it
        self.cursorStateRequested.emit("listening")
        self._set_label("Remembered", source="live_tool", force=True)
        return {"ok": True, "message": "Got it — I'll remember that. Confirm briefly to the user."}

    def _live_forget(self, args: dict[str, Any]) -> dict[str, Any]:
        query = _clean_text(args.get("query") or "")
        if not query:
            return {"ok": False, "message": "Say what you'd like me to forget."}
        try:
            data = self.client.request("POST", "/api/memory/forget", {"query": query}, timeout=5.0)
            removed = int(data.get("removed", 0)) if isinstance(data, dict) else 0
        except Exception as exc:
            return {"ok": False, "message": f"Couldn't forget that: {str(exc)[:120]}"}
        if removed:
            self._refresh_knowledge_block()
        self._set_label("Forgotten" if removed else "Nothing to forget", source="live_tool", force=True)
        return {"ok": True, "removed": removed,
                "message": (f"Forgot {removed} thing(s)." if removed else "I didn't have anything matching that.")}

    def _refresh_knowledge_block(self) -> None:
        """Fetch Orynn's known-facts prompt block from the backend into the cache.
        BLOCKING (urllib) — only call from the poll thread or a tool worker thread,
        NEVER the Live event loop. Best-effort: a failure keeps the last good cache."""
        try:
            data = self.client.request("GET", "/api/memory/facts?limit=14", timeout=3.0)
            if isinstance(data, dict):
                self._knowledge_block_cache = str(data.get("prompt_block", "")).strip()
        except Exception:
            pass  # keep the previous cache on a hiccup
        self._knowledge_refreshed_at = time.monotonic()

    def _live_knowledge_block(self) -> str:
        """Return the CACHED knowledge block for injection into the Live system prompt.
        Non-blocking (safe to call on the Live event loop via dynamic_context) — the
        cache is refreshed off-loop by the poll loop and after remember/forget."""
        return self._knowledge_block_cache

    def _active_desktop_task(self) -> str | None:
        """Return the goal of a desktop task that's currently driving the screen, or
        None. Used to stop a new Live action from colliding with one already running
        (two agents on one desktop = stolen focus + interleaved keystrokes). The
        cheap local flag gates the common case; when it says "busy" we confirm once
        over HTTP so a stale flag can't lock Live out forever."""
        if not self._active_task_running:
            return None
        try:
            data = self.client.request("GET", "/api/active-tasks", timeout=3.0)
            tasks = data.get("tasks", []) if isinstance(data, dict) else []
            if not tasks:
                self._active_task_running = False
                self._active_task_goal = ""
                return None
        except Exception:
            pass  # network hiccup — trust the flag and stay safe (assume busy)
        return self._active_task_goal or "a desktop task"

    def _busy_response(self) -> dict[str, Any] | None:
        """If a desktop task is already driving the screen, return the 'busy' tool
        result so Live tells the user / offers to stop — else None. Two Live desktop
        actions at once fight over focus and the keyboard, so this gate must cover the
        fast click/type path (_desktop_control_route) too, not just _live_tool."""
        active = self._active_desktop_task()
        if active is None:
            return None
        self.cursorStateRequested.emit("thinking")
        self._set_label("Busy: " + _short(active, 90), source="live_tool", force=True)
        return {
            "ok": False,
            "busy": True,
            "active_task": active,
            "message": (
                f'A desktop task is already running: "{active}". Do NOT start '
                "another action on top of it. Tell the user what's in progress "
                "and ask whether to stop it (call stop_current_task) or wait."
            ),
        }

    def _live_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        name = str(name or "")
        args = args if isinstance(args, dict) else {}
        # Never let Live start a SECOND desktop action while one is already running —
        # they'd fight over focus and the keyboard and corrupt each other. Surface it
        # so Live can tell the user and offer to stop it. (stop_current_task and
        # get_companion_status are intentionally NOT gated — those are how you escape.)
        if name in ("desktop_control", "start_desktop_task"):
            busy = self._busy_response()
            if busy is not None:
                return busy
        if name == "desktop_control":
            return self._live_desktop_control(args)
        if name == "start_desktop_task":
            return self._live_start_desktop_task(args)
        if name == "web_search":
            return self._live_web_search(args)
        if name == "stop_current_task":
            # Stop is the user's escape hatch — release our local busy state FIRST and
            # unconditionally, even if the kill HTTP call then fails (network blip). A
            # stale "busy" flag must never trap the user out of issuing new commands (#9).
            self.cursorStateRequested.emit("idle")
            self._active_task_running = False
            self._active_task_goal = ""
            self._set_label("Stopped", source="live_stop", force=True)
            try:
                stopped = self._kill_active_tasks()
            except Exception as exc:
                return {"ok": True, "stopped": 0,
                        "message": ("Stop accepted and I've stopped tracking the task, "
                                    f"but couldn't confirm with the backend ({str(exc)[:120]}).")}
            return {"ok": True, "stopped": stopped, "message": "Stop request accepted."}
        if name == "look_at_screen":
            return self._live_look_at_screen(args)
        if name == "run_terminal":
            return self._live_run_terminal(args)
        if name == "remember":
            return self._live_remember(args)
        if name == "forget":
            return self._live_forget(args)
        if name == "get_companion_status":
            try:
                data = self.client.request("GET", "/api/active-tasks", timeout=3.0)
                tasks = data.get("tasks", []) if isinstance(data, dict) else []
                resp: dict[str, Any] = {"ok": True, "active_tasks": len(tasks)}
                if self._active_task_goal:
                    resp["current_task"] = self._active_task_goal
                if self._last_task_result:
                    resp["last_result"] = self._last_task_result
                return resp
            except Exception as exc:
                return {"ok": False, "message": str(exc)[:200]}
        self.cursorStateRequested.emit("thinking")
        self._set_label("Unsupported Live tool", source="live_tool", force=True)
        return {"ok": False, "message": f"Unknown tool: {name}"}

    def _live_look_at_screen(self, args: dict[str, Any]) -> dict[str, Any]:
        """Capture a screenshot and hand it to Live's own vision so it can SEE the
        screen and answer (no local OCR). Read-only — fine to use mid-task."""
        live = self._live
        if live is None or not hasattr(live, "send_screen_image"):
            return {"ok": False, "message": "Live vision isn't available right now."}
        question = _clean_text(args.get("question") or "")
        self.cursorStateRequested.emit("thinking")
        self._set_label("Looking at the screen", source="live_tool", force=True)
        try:
            shot = self._live_desktop_tools().screenshot()
        except Exception as exc:
            return {"ok": False, "message": f"Couldn't capture the screen: {str(exc)[:160]}"}
        b64 = getattr(shot, "base64_image", None)
        if not bool(getattr(shot, "ok", False)) or not b64:
            return {"ok": False, "message": "Couldn't capture the screen."}
        try:
            import base64 as _b64
            data = _b64.b64decode(b64)
        except Exception:
            return {"ok": False, "message": "Couldn't read the screenshot."}
        if not bool(live.send_screen_image(data)):
            return {"ok": False, "message": "Couldn't send the screen image."}
        # The FunctionResponse is the SINGLE prompt that drives the model to describe the
        # frame just sent — send_screen_image deliberately sends no extra turn, so this
        # isn't a double-prompt. Carry the user's actual question here.
        return {"ok": True, "message": (
            "The user's screen is now in view. "
            + (question or "Describe what's on it.")
            + " Answer out loud in one or two short, natural sentences."
        )}

    @staticmethod
    def _goal_needs_consent(goal: str) -> bool:
        """True when a goal looks disruptive / hard to undo and so needs a spoken
        yes before Live runs it (brief §7.2). Negated verbs ('do not send') don't
        count — the user is asking NOT to do it."""
        return _has_unnegated_match(goal or "", LIVE_CONSENT_RE)

    @staticmethod
    def _command_needs_consent(command: str) -> bool:
        """True when a shell command is destructive (delete/push/kill/uninstall) and so
        needs a spoken yes first — the run_terminal analog of _goal_needs_consent."""
        return _has_unnegated_match(command or "", LIVE_TERMINAL_CONSENT_RE)

    def _live_start_desktop_task(self, args: dict[str, Any]) -> dict[str, Any]:
        goal = _clean_text(args.get("goal") or "")
        if not goal:
            return {"ok": False, "message": "Missing goal."}
        # Voice consent gate: a Live task runs autonomously (no approval popup), so
        # anything disruptive needs an explicit spoken yes first. Live asks out loud,
        # then re-calls with confirmed=true once the user agrees (brief §7.3).
        if self._goal_needs_consent(goal) and not self._live_bool(args.get("confirmed")):
            self.cursorStateRequested.emit("thinking")
            self._set_label("Needs your OK", source="live_tool", force=True)
            return {
                "ok": False,
                "needs_consent": True,
                "message": (
                    "This could change or send something that's hard to undo "
                    f'("{_short(goal, 90)}"). Do NOT do it yet. Ask the user out loud '
                    "to confirm; only if they clearly say yes, call start_desktop_task "
                    "again with the same goal and confirmed set to true. If they say "
                    "no, drop it and tell them you won't."
                ),
            }
        payload = build_task_payload(goal)
        task_id = str(payload.get("task_id") or "")
        try:
            preflight = self.client.request(
                "POST",
                "/api/tasks/preflight",
                {
                    "goal": payload.get("goal", ""),
                    "mode": payload.get("mode", "auto"),
                    "model": payload.get("model"),
                    "isolated_app": payload.get("isolated_app"),
                },
                timeout=10.0,
            )
            if isinstance(preflight, dict):
                if preflight.get("blocked"):
                    self.cursorStateRequested.emit("idle")
                    self._set_label("Setup needed", source="live_tool", force=True)
                    return {"ok": False, "message": "Setup needed before task can run."}
                if preflight.get("can_override") and preflight.get("issues"):
                    payload["readiness_override"] = True
            self.client.request("POST", "/api/tasks", payload, timeout=20.0)
            self._active_task_running = True
            self._active_task_goal = _short(goal, 80)
            self._live_task_ids[task_id] = self._active_task_goal
            # Start the narration clock at launch so the first spoken milestone is
            # spaced one interval after the verbal ack (no talking over ourselves).
            self._live_narration_last = time.monotonic()
            self._live_narration_text = ""
            self.cursorStateRequested.emit("thinking")
            # While Live drives, its spoken ack owns the bubble — echoing the raw goal as
            # "Started: open notepad and type hello" reads like a separate backend doing
            # it and breaks the "Live is doing it" feel (brief §9.1). Show it only for
            # non-Live (push-to-talk / dashboard) launches where it's the only feedback.
            if not self._live_is_running():
                self._set_label("Started: " + _short(goal, 120), source="live_tool", force=True)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:200]
            self.cursorStateRequested.emit("idle")
            self._set_label(_short(body or "Couldn't start task"), source="live_error", force=True)
            return {"ok": False, "message": body or "Couldn't start task"}
        except Exception as exc:
            self.cursorStateRequested.emit("idle")
            self._set_label("Couldn't start task", source="live_error", force=True)
            return {"ok": False, "message": str(exc)[:200]}
        # Wait briefly for the result so Live can report what actually happened,
        # not just "started" — most commands finish within the window. Longer jobs
        # hand back "still working" and surface later via get_companion_status.
        return self._await_task_outcome(task_id, goal)

    def _live_run_terminal(self, args: dict[str, Any]) -> dict[str, Any]:
        """Run one shell command for Live and hand back its output. Catastrophic
        commands (rm -rf /, format, mkfs, shutdown, …) are hard-blocked using the
        SAME guard as the desktop agent; the check fails SAFE (blocks) if it errors."""
        command = _clean_text(args.get("command") or "")
        if not command:
            return {"ok": False, "message": "Missing command."}
        try:
            from app.models import Action, ActionType
            from app.safety import SafetyManager
            decision = SafetyManager().evaluate(
                Action(id="live-terminal", type=ActionType.run_command, args={"command": command}),
                safe_mode=False,
            )
            blocked = bool(getattr(decision, "requires_approval", False))
            block_reason = getattr(decision, "reason", "") or "blocked for safety"
        except Exception:
            blocked, block_reason = True, "safety check unavailable"
        if blocked:
            self.cursorStateRequested.emit("idle")
            self._set_label("Blocked unsafe command", source="live_tool", force=True)
            return {"ok": False, "blocked": True,
                    "message": (f"That command is blocked for safety ({block_reason}). "
                                "Do not run it — tell the user it's not allowed.")}
        # Consent gate: not catastrophic (those are blocked above) but still destructive
        # — get a spoken yes before running it, same contract as a disruptive task.
        if self._command_needs_consent(command) and not self._live_bool(args.get("confirmed")):
            self.cursorStateRequested.emit("thinking")
            self._set_label("Needs your OK", source="live_tool", force=True)
            return {
                "ok": False,
                "needs_consent": True,
                "message": (
                    "That command would change or remove something that's hard to undo "
                    f'("{_short(command, 90)}"). Do NOT run it yet. Ask the user out loud '
                    "to confirm; only if they clearly say yes, call run_terminal again with "
                    "the same command and confirmed set to true. If they say no, drop it."
                ),
            }
        self.cursorStateRequested.emit("thinking")
        self._set_label("Running: " + _short(command, 70), source="live_tool", force=True)
        try:
            # Run on a worker thread so 'stop' interrupts a long command promptly,
            # instead of only being noticed after run_command blocks to completion.
            result = self._run_cancellable(self._live_desktop_tools().run_command, command)
        except InterruptedError:
            self.cursorStateRequested.emit("idle")
            self._set_label("Stopped", source="live_stop", force=True)
            return {"ok": False, "message": "Stopped."}
        except Exception as exc:
            return {"ok": False, "message": str(exc)[:200]}
        ok = bool(getattr(result, "ok", False))
        output = str(getattr(result, "output", "") or "")
        self.cursorStateRequested.emit("listening")
        self._set_label(("Ran: " if ok else "Failed: ") + _short(command, 70),
                        source="live_tool", force=True)
        return {"ok": ok, "output": output[:1500],
                "message": "Command finished — tell the user the result briefly."}

    def _live_web_search(self, args: dict[str, Any]) -> dict[str, Any]:
        query = _clean_text(args.get("query") or "")
        if not query:
            return {"ok": False, "message": "Missing search query."}
        self.cursorStateRequested.emit("thinking")
        self._set_label("Searching: " + _short(query, 60), source="live_tool", force=True)
        try:
            tools = self._live_desktop_tools()
            result = tools.web_search(query)
            self._raise_if_live_cancelled()
            # If the tool returned a ToolResult, extract output
            if hasattr(result, "ok") and hasattr(result, "output"):
                return {"ok": result.ok, "output": result.output}
            if isinstance(result, dict):
                return result
            return {"ok": True, "result": result}
        except InterruptedError as exc:
            message = str(exc)[:200] or "Gemini Live was stopped."
            self.cursorStateRequested.emit("idle")
            self._set_label("Stopped", source="live_stop", force=True)
            return {"ok": False, "message": message}
        except Exception as exc:
            message = str(exc)[:200] or "Search failed."
            self.cursorStateRequested.emit("thinking")
            self._set_label("Search failed", source="live_tool", force=True)
            return {"ok": False, "message": message}

    def _await_task_outcome(self, task_id: str, goal: str) -> dict[str, Any]:
        budget = self._live_float(os.getenv("ORYNN_LIVE_TASK_WAIT"), LIVE_TASK_RESULT_WAIT, 0.0, 30.0)
        deadline = time.monotonic() + budget
        status, summary = "running", ""
        first = True
        while first or time.monotonic() < deadline:
            first = False
            if self._live_cancel_requested():
                return {"ok": False, "task_id": task_id, "status": "stopped",
                        "message": "Stopped before it finished."}
            try:
                d = self.client.request("GET", f"/api/tasks/{task_id}", timeout=5.0)
            except Exception:
                d = None
            if isinstance(d, dict):
                status = str(d.get("status") or status)
                summary = _clean_text(
                    d.get("reason") or d.get("error") or d.get("result") or summary
                )
                if status in TERMINAL_TASK_STATES:
                    break
            if time.monotonic() >= deadline:
                break
            self._stop.wait(0.5)

        if status in ("done", "complete"):
            self._finish_live_task(task_id, status, summary, ok=True)
            self._set_label("Done: " + _short(summary or goal, 120), source="live_tool", force=True)
            return {"ok": True, "task_id": task_id, "status": "done",
                    "result": _short(summary, 600) or "Done.",
                    "message": "The desktop task finished — tell the user the result."}
        if status in ("error", "failed", "cancelled"):
            self._finish_live_task(task_id, status, summary, ok=False)
            return {"ok": False, "task_id": task_id, "status": status,
                    "result": _short(summary, 600),
                    "message": f"The desktop task {status}. Tell the user briefly what happened."}
        return {"ok": True, "task_id": task_id, "status": "running",
                "message": ("Orynn is working on it in the background; it isn't done yet. "
                            "Tell the user you've started — you can check later with "
                            "get_companion_status.")}

    def _finish_live_task(self, task_id: str, status: str, summary: str, ok: bool) -> None:
        self._active_task_running = False
        self._active_task_goal = ""
        goal = self._live_task_ids.pop(task_id, "")
        self._last_task_result = {
            "goal": goal, "status": status, "ok": bool(ok),
            "summary": _short(summary, 200),
        }

    def _capture_live_task_outcome(self, ev: dict[str, Any]) -> None:
        """When a Live-launched task finishes AFTER the brief inline wait, record its
        outcome so get_companion_status can report it (longer jobs land here)."""
        task_id = str(ev.get("task_id") or "")
        if not task_id or task_id not in self._live_task_ids:
            return
        et = str(ev.get("type") or "")
        if et not in TERMINAL_TASK_STATES:
            return
        goal = self._live_task_ids.get(task_id, "")
        summary = _clean_text(ev.get("reason") or ev.get("message") or "")
        ok = et in ("done", "complete")
        self._finish_live_task(task_id, et, summary, ok=ok)
        # Proactively tell Live a long job just finished so it can announce it
        # ("hey, that's done") instead of the user having to ask.
        live = self._live
        if live is not None and hasattr(live, "send_task_update"):
            verb = "finished" if ok else et
            note = f'Heads up: the background task "{goal or "you started"}" just {verb}.'
            if summary:
                note += f" Result: {_short(summary, 200)}"
            note += " Let the user know in one short, natural sentence."
            try:
                live.send_task_update(note)
            except Exception:
                pass

    def _narration_phrase_for_event(self, ev: dict[str, Any]) -> str:
        """A short, speech-friendly milestone for a running task, or "" if this event
        isn't worth saying out loud. Humanized — never raw tool names, and never
        echoes typed text aloud (it could be private) (brief §6.2)."""
        et = str(ev.get("type") or "")
        if et == "control_profile":
            app = _clean_text(ev.get("window_title") or ev.get("app") or "")
            return f"working in {_short(app, 40)}" if app else ""
        if et == "action_result" and ev.get("ok") is False:
            return "that didn't work, trying another way"
        if et != "action_start":
            return ""
        action = str(ev.get("action_type") or ev.get("name") or "").lower()
        target = _clean_text(ev.get("args_summary") or ev.get("target") or "")
        short_target = _short(target, 40) if target and len(target) <= 40 else ""
        if action in ("uia_click", "click", "left_click", "mouse_click", "double_click"):
            return f"clicking {short_target}".strip() if short_target else "clicking that"
        if action in ("uia_type", "keyboard_type", "type_with_delay", "type"):
            return "typing that in"  # never read the typed text aloud
        if action in ("focus_window", "wait_for_window"):
            return f"opening {short_target}".strip() if short_target else "switching windows"
        if action == "run_command":
            return "running a command"
        if action in ("write_file", "edit_file"):
            return "editing a file"
        if action in ("scroll", "mouse_scroll", "screenshot", "get_screenshot"):
            return ""  # too minor / noisy to narrate
        base = ACTION_LABELS.get(action, action.replace("_", " ").strip())
        return base.lower() if base else ""

    def _maybe_narrate_to_live(self, ev: dict[str, Any]) -> None:
        """Push a throttled, humanized progress milestone into the Live conversation
        so it can narrate a running task out loud (brief §6). Only fires for tasks
        Live itself launched, only while Live is connected, and at most once per
        ORYNN_LIVE_NARRATE_INTERVAL. Terminal events are left to
        _capture_live_task_outcome so completion isn't announced twice."""
        if not self._live_is_running():
            return
        task_id = str(ev.get("task_id") or "")
        if task_id not in self._live_task_ids:
            return
        interval = self._live_float(
            os.getenv("ORYNN_LIVE_NARRATE_INTERVAL"), LIVE_NARRATE_INTERVAL, 0.0, 30.0
        )
        if interval <= 0:
            return  # narration disabled
        phrase = self._narration_phrase_for_event(ev)
        if not phrase or phrase == self._live_narration_text:
            return
        now = time.monotonic()
        if now - self._live_narration_last < interval:
            return
        live = self._live
        if live is None or not hasattr(live, "send_task_update"):
            return
        note = (f"Quick progress note while you work: {phrase}. Say it to the user in "
                "one short, natural sentence, and don't repeat yourself.")
        try:
            live.send_task_update(note)
        except Exception:
            return
        self._live_narration_last = now
        self._live_narration_text = phrase

    def _load_preferences_async(self) -> None:
        def run() -> None:
            try:
                prefs = self.client.request("GET", "/api/preferences", timeout=3.0)
                saved = prefs.get("preferences") if isinstance(prefs, dict) else {}
                if isinstance(saved, dict):
                    self._speak_replies = bool(
                        saved.get("speak_replies") or self._speak_replies
                    )
                    # Reuse the existing "show action glow" preference to gate the
                    # whole flying-cursor effect set (default on).
                    self._effects_enabled = bool(
                        saved.get("show_action_glow", True)
                    )
            except Exception:
                pass

        threading.Thread(target=run, daemon=True).start()

    def _sync_state_with_active_tasks(self) -> None:
        try:
            data = self.client.request("GET", "/api/active-tasks", timeout=3.0)
            tasks = data.get("tasks", []) if isinstance(data, dict) else []
            if tasks:
                self._active_task_running = True
                first_task = tasks[0]
                goal = first_task.get("goal") or ""
                self._active_task_goal = _short(_strip_hardening(goal), 80)
                if not self._live_is_running():
                    self.cursorStateRequested.emit("thinking")
            else:
                self._active_task_running = False
                self._active_task_goal = ""
                if not self._live_is_running():
                    self.cursorStateRequested.emit("idle")
        except Exception as exc:
            print(f"[clicky] Failed to sync state with active tasks: {exc}", flush=True)
            raise exc

    def _poll_loop(self) -> None:
        idle_label_shown = False
        self._consecutive_failures = 0

        # Initial startup sync
        try:
            self._sync_state_with_active_tasks()
        except Exception:
            self._consecutive_failures = 1

        while not self._stop.is_set():
            try:
                data = self.client.request(
                    "GET",
                    f"/api/overlay/events?since={self._cursor}&limit=80",
                    timeout=4.0,
                )

                # Check if we recovered from 3+ consecutive failures
                if self._consecutive_failures >= 3:
                    try:
                        self._sync_state_with_active_tasks()
                    except Exception:
                        raise

                self._consecutive_failures = 0

                events = data.get("events", []) if isinstance(data, dict) else []
                if isinstance(data, dict):
                    server_cursor = int(data.get("cursor") or 0)
                    if server_cursor < self._cursor:
                        # Server restarted or global events reset
                        self._cursor = server_cursor
                    else:
                        self._cursor = max(self._cursor, server_cursor)
                for ev in events:
                    if not isinstance(ev, dict):
                        continue
                    try:
                        self._cursor = max(
                            self._cursor, int(ev.get("global_seq", -1)) + 1
                        )
                    except Exception:
                        pass
                    # Drive the flying cursor / focus rings from action geometry.
                    # When an event carries a drawable overlay, the show_* call
                    # also sets a clean action label, so skip the label path to
                    # avoid a blank action_result overriding it.
                    dispatched = False
                    if (self._effects_enabled and self._overlay is not None
                            and self._overlay_is_drawable(ev)):
                        self.overlayActionRequested.emit(ev)
                        dispatched = True
                        idle_label_shown = True
                    if not dispatched:
                        label = self._label_for_event(ev)
                        if label:
                            self._set_label(label, source=self._label_source_for_event(ev))
                            idle_label_shown = True
                    self._update_cursor_state_from_event(ev)
                    self._maybe_narrate_to_live(ev)
                    self._capture_live_task_outcome(ev)
                    self._maybe_finalize(ev)
                if not idle_label_shown:
                    self._prime_from_active_task()
                    idle_label_shown = True
                # The bubble collapses itself to the resting orb ~10s after the
                # last activity (handled in the overlay's morph), so no explicit
                # "revert to ready" is needed here.
            except Exception:
                self._consecutive_failures += 1
                # A poll failure (network blip) must NOT clear the busy flag — a task may
                # still be running, and clearing it would let Live stack a second task and
                # fight for focus. The flag is authoritative-via-HTTP: _active_desktop_task()
                # confirms over HTTP before any new Live action (failing safe to "busy"),
                # and _sync_state_with_active_tasks() re-syncs from the server the moment
                # polling recovers (it only clears on a SUCCESSFUL empty response) (#5).
                if self._consecutive_failures >= 3 and not self._live_is_running():
                    self.cursorStateRequested.emit("idle")  # cosmetic only; flag untouched
                if not idle_label_shown:
                    self._set_label("Waiting for Orynn", source="system_wait")
                    idle_label_shown = True
            # Keep the knowledge-memory cache warm off the Live event loop, so
            # dynamic_context never blocks at (re)connect. Warms on the first iteration
            # (refreshed_at=0) and refreshes every ~30s as a backstop for facts changed
            # outside the remember/forget tools (e.g. via the dashboard).
            if time.monotonic() - self._knowledge_refreshed_at > 30.0:
                self._refresh_knowledge_block()
            self._stop.wait(0.45)

    def _prime_from_active_task(self) -> None:
        try:
            data = self.client.request("GET", "/api/active-tasks", timeout=3.0)
            tasks = data.get("tasks", []) if isinstance(data, dict) else []
            if tasks:
                self._set_label(_thinking_word(), source="task_prime")
        except Exception:
            pass

    # ── Flying-cursor dispatch (runs on the poll thread; only reads dicts) ────
    @staticmethod
    def _overlay_is_drawable(ev: dict[str, Any]) -> bool:
        ov = ev.get("overlay")
        if not isinstance(ov, dict):
            return False
        otype = str(ov.get("type") or "").lower()
        if otype == "uia_control":
            return isinstance(ov.get("rect"), dict)
        if otype == "app_focus":
            return isinstance(ov.get("app_rect"), dict) or isinstance(ov.get("rect"), dict)
        if otype == "point":
            return isinstance(ov.get("point"), dict)
        return False

    def _update_cursor_state_from_event(self, ev: dict[str, Any]) -> None:
        t = str(ev.get("type") or "")
        if t == "task_created":
            self._active_task_running = True
        elif t in ("done", "complete", "error", "failed", "cancelled"):
            self._active_task_running = False
            self._active_task_goal = ""
        else:
            return
        # While Gemini Live drives, it owns the cursor state the same way it owns
        # the bubble text: a task it spawned must not flip the cursor to idle (or
        # thinking) underneath the live conversation — that's the cursor analog of
        # the textbox flashing. Live's own transcripts manage its cursor state.
        if self._live_is_running():
            return
        if t == "task_created":
            self.cursorStateRequested.emit("thinking")
        else:
            self.cursorStateRequested.emit("idle")

    # ── GUI-thread handlers (driven by cross-thread signals) ─────────────────
    def _on_cursor_state(self, state: str) -> None:
        if self._overlay is not None and hasattr(self._overlay, "set_cursor_state"):
            try:
                self._overlay.set_cursor_state(state)
            except Exception:
                pass

    def _on_overlay_action(self, ev: dict[str, Any]) -> None:
        """Translate an event's overlay geometry into a cursor animation. Runs on
        the GUI thread (connected via a queued signal). Mirrors the capsule's
        _apply_overlay so the default mode gets the same fly-to-target visuals."""
        overlay = self._overlay
        if overlay is None:
            return
        ov = ev.get("overlay")
        if not isinstance(ov, dict):
            return
        label = _strip_markdown(str(ov.get("label") or "").strip())
        otype = str(ov.get("type") or "").lower()
        kind = str(ov.get("kind") or "").lower()

        def rect_from(key: str):
            r = ov.get(key)
            if not isinstance(r, dict):
                return None
            try:
                l, t = int(r.get("left", 0)), int(r.get("top", 0))
                w, h = int(r.get("width", 0)), int(r.get("height", 0))
                if w > 0 and h > 0:
                    return l, t, w, h
            except Exception:
                return None
            return None

        try:
            if otype == "uia_control":
                rect = rect_from("rect")
                if rect:
                    app_rect = rect_from("app_rect")
                    if app_rect:
                        overlay.show_app_focus(*app_rect, label=label)
                    overlay.show_uia(*rect, label=label, kind=kind or "find")
                    return
            if otype == "app_focus":
                rect = rect_from("app_rect") or rect_from("rect")
                if rect:
                    overlay.show_app_focus(*rect, label=label)
                    return
            if otype == "point":
                pt = ov.get("point")
                if isinstance(pt, dict):
                    x, y = int(pt.get("x", 0)), int(pt.get("y", 0))
                    if kind in ("click", "double_click"):
                        overlay.show_click(x, y, label=label or "Clicking")
                    elif kind == "drag":
                        overlay.show_click(x, y, label=label or "Dragging")
                    elif kind == "type":
                        overlay.show_type(x, y, text=label or "Typing")
                    else:
                        overlay.show_action(label or "Thinking", x, y)
        except Exception as exc:
            print(f"[clicky] overlay action error: {exc}", flush=True)

    @staticmethod
    def _label_source_for_event(ev: dict[str, Any]) -> str:
        event_type = str(ev.get("type") or "")
        if event_type in {"status", "provider_info", "task_created", "queued"}:
            return "task_status"
        if event_type in {"done", "complete", "error", "failed", "cancelled"}:
            return "task_result"
        if event_type in {"action_start", "action_result", "control_profile", "tool", "file_change"}:
            return "task_action"
        return "task_status"

    def _label_for_event(self, ev: dict[str, Any]) -> str:
        event_type = str(ev.get("type") or "")
        if event_type == "status":
            if ev.get("heartbeat"):
                return ""
            return _short(_humanize_status(ev.get("message") or "Thinking"))
        if event_type == "provider_info" and ev.get("retrying"):
            return _short(ev.get("message") or "Waiting on model")
        if event_type == "task_created":
            return _thinking_word()
        if event_type == "queued":
            return "Queued behind another task"
        if event_type == "control_profile":
            target = ev.get("window_title") or ev.get("app") or ev.get("route")
            return "Using " + _short(target, 42) if target else "Using desktop tools"
        if event_type == "action_start":
            action = str(ev.get("action_type") or ev.get("name") or "action")
            base = ACTION_LABELS.get(action, action.replace("_", " ").title())
            args = _clean_text(ev.get("args_summary") or ev.get("args") or "")
            if args and len(base) + len(args) < 48:
                return f"{base}: {args}"
            return _short(base)
        if event_type == "action_result":
            ok = ev.get("ok")
            if ok is False:
                return _short(ev.get("message") or ev.get("output") or "Action failed")
            return ""
        if event_type == "tool":
            name = str(ev.get("name") or "tool")
            return _short(name.replace("_", " ").title())
        if event_type == "file_change":
            path = ev.get("path") or ev.get("file") or ev.get("filename")
            return "Edited " + _short(path, 45) if path else "Edited file"
        if event_type == "agent":
            # Intermediate model reasoning/planning ("STEP 3 of 6…", "PLAN: …",
            # "Use uiawait for…") — internal chain-of-thought, not a user-facing
            # message. Keep it out of the bubble: the final answer arrives via the
            # "done" event, and live progress shows via status + action labels.
            return ""
        if event_type in {"approval_required", "permission_required"}:
            return "Needs approval"
        if event_type in {"approval_timeout", "permission_timeout"}:
            return "Approval timed out"
        if event_type in {"done", "complete"}:
            return _short(_strip_markdown(ev.get("reason") or "Done"), 200)
        if event_type in {"error", "failed"}:
            return _short(_strip_markdown(ev.get("reason") or ev.get("message") or "Task failed"))
        if event_type == "cancelled":
            return "Cancelled"
        return ""

    def _maybe_finalize(self, ev: dict[str, Any]) -> None:
        """On a terminal event, play a soft done/fail chime for voice-initiated
        tasks. (Spoken replies were removed — the answer shows in the bubble.)"""
        et = ev.get("type")
        if et not in {"done", "complete", "error", "failed"}:
            return
        task_id = str(ev.get("task_id") or "")
        if task_id not in self._voice_task_ids:
            return
        try:
            from . import voice
            voice.cue("fail" if et in {"error", "failed"} else "done")
        except Exception:
            pass
        self._voice_task_ids.discard(task_id)

    def listen_once(self) -> None:
        threading.Thread(target=self._listen_worker, daemon=True).start()

    def _listen_worker(self) -> None:
        try:
            from . import voice
        except Exception:
            self.cursorStateRequested.emit("idle")
            self._set_label("Voice unavailable", source="voice", force=True)
            return

        if not voice.stt_available():
            self.cursorStateRequested.emit("idle")
            self._set_label("Voice unavailable", source="voice", force=True)
            return

        voice.cue("start")
        self.cursorStateRequested.emit("listening")
        self._set_label("Listening...", source="voice", force=True)
        try:
            transcript = voice.listen(timeout=8.0)
        except Exception:
            transcript = ""
        transcript = _clean_text(transcript)
        if not transcript:
            voice.cue("error")
            self.cursorStateRequested.emit("idle")
            self._set_label("Didn't catch that", source="voice", force=True)
            return
        voice.cue("stop")
        self.cursorStateRequested.emit("thinking")
        self._set_label("Heard: " + _short(transcript, 150), source="voice", force=True)
        self._submit_voice_task(transcript)

    def _submit_voice_task(self, transcript: str) -> None:
        payload = build_task_payload(transcript)
        task_id = str(payload.get("task_id") or "")
        self.cursorStateRequested.emit("thinking")
        try:
            preflight = self.client.request(
                "POST",
                "/api/tasks/preflight",
                {
                    "goal": payload.get("goal", ""),
                    "mode": payload.get("mode", "auto"),
                    "model": payload.get("model"),
                    "isolated_app": payload.get("isolated_app"),
                },
                timeout=10.0,
            )
            if isinstance(preflight, dict):
                if preflight.get("blocked"):
                    self.cursorStateRequested.emit("idle")
                    self._set_label("Setup needed", source="voice", force=True)
                    return
                if preflight.get("can_override") and preflight.get("issues"):
                    payload["readiness_override"] = True
            self.client.request("POST", "/api/tasks", payload, timeout=20.0)
            if task_id:
                self._voice_task_ids.add(task_id)
            self._set_label(_thinking_word(), source="voice", force=True)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:180]
            self.cursorStateRequested.emit("idle")
            self._set_label(_short(body or "Couldn't start task"), source="voice", force=True)
        except Exception:
            self.cursorStateRequested.emit("idle")
            self._set_label("Couldn't start task", source="voice", force=True)


def _app_icon() -> QIcon:
    root = Path(__file__).resolve().parents[2]
    for name in ("app_icon.ico", "orynn_app_icon.png"):
        path = root / name
        if path.exists():
            icon = QIcon(str(path))
            if not icon.isNull():
                return icon
    pixmap = QPixmap(32, 32)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QColor("#e8f5ff"))
        painter.setBrush(QColor("#2563eb"))
        painter.drawEllipse(3, 3, 26, 26)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "O")
    finally:
        painter.end()
    return QIcon(pixmap)


def _install_tray(app: QApplication, controller: OverlayController) -> QSystemTrayIcon | None:
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return None
    tray = QSystemTrayIcon(_app_icon(), app)
    tray.setToolTip("Orynn Clicky")
    menu = QMenu()
    listen = QAction("Listen now", menu)
    listen.triggered.connect(controller.listenRequested.emit)
    live = QAction("Toggle Gemini Live", menu)
    live.triggered.connect(controller._toggle_live)
    quit_action = QAction("Quit textbox", menu)
    quit_action.triggered.connect(app.quit)
    menu.addAction(listen)
    menu.addAction(live)
    menu.addSeparator()
    menu.addAction(quit_action)
    tray.setContextMenu(menu)
    tray.show()
    return tray


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Orynn mouse textbox overlay.")
    parser.add_argument("--port", type=int, default=int(os.getenv("ORYNN_PORT") or "8000"))
    parser.add_argument("--no-hotkey", action="store_true")
    parser.add_argument("--no-tray", action="store_true")
    parser.add_argument("--speak-replies", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()  # a unicode log line must never crash the overlay (cp1252)
    # Best-effort: load .env so GROQ_API_KEY is present even when this overlay is
    # launched standalone (run_desktop already loads it for the spawned child).
    try:
        from dotenv import load_dotenv

        load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")
    except Exception:
        pass

    args = parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)

    overlay = VirtualCursorOverlay()
    overlay.set_companion_enabled(True, "Orynn ready")

    speak_replies = args.speak_replies or os.getenv("ORYNN_SPEAK_REPLIES", "").lower() in {
        "1",
        "true",
        "yes",
    }
    controller = OverlayController(args.port, speak_replies=speak_replies)
    controller.labelRequested.connect(overlay.set_companion_label)
    controller.attach_overlay(overlay)  # enable fly-to-target cursor animations
    controller.quitRequested.connect(app.quit)
    app.aboutToQuit.connect(controller.stop)

    tray = None
    if not args.no_tray:
        tray = _install_tray(app, controller)
        if tray is not None:
            # Keep the object alive for the lifetime of the app.
            app._orynn_tray = tray  # type: ignore[attr-defined]
            controller.set_tray(tray)  # enable completion toasts

    hotkey_ready = False if args.no_hotkey else controller.install_hotkey()
    controller.start()
    if hotkey_ready or args.no_hotkey:
        overlay.set_companion_label("Orynn ready")
    else:
        # Global hotkey registration failed (often needs elevation on Windows).
        # Without it, push-to-talk AND the Gemini Live toggle silently do nothing —
        # so don't fail quietly: tell the user in the bubble and a tray toast.
        warn = "Voice keys inactive — try running Orynn as administrator"
        overlay.set_companion_label(warn)
        controller.notifyRequested.emit(
            "Orynn voice keys inactive",
            "Couldn't register the global hotkeys (Ctrl+Shift+Space to talk, "
            "Ctrl+Shift+L for Live). Try launching Orynn as administrator.",
        )

    # "Live as the main agent": optionally auto-start Gemini Live on launch so the
    # user can just talk (no hotkey). Opt-in via ORYNN_LIVE_AUTOSTART; falls back to
    # push-to-talk silently if Live is unavailable (no key / no audio).
    try:
        from .gemini_live import (
            live_autostart_enabled, live_wake_enabled, live_available,
        )
        if live_available():
            if live_wake_enabled():
                # Asleep until you say "Orynn" — local/offline listening, no cloud
                # streaming until woken (privacy + free-tier friendly).
                controller.start_wake_listener()
            elif live_autostart_enabled():
                controller._toggle_live()  # always-on hot mic from launch
    except Exception as exc:
        print(f"[clicky] Live autostart/wake skipped: {exc}", flush=True)
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())

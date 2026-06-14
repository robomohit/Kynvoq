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

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .virtual_cursor import VirtualCursorOverlay


DESKTOP_HARDENING = (
    "You are driving the user's Windows desktop. Prefer UI Automation "
    "(UIA) over screenshots - it is faster and never mis-clicks:\n"
    "1. `focus_window` (or `wait_for_window`) to bring the target app "
    "to the front.\n"
    "2. `uia_find` with the control's visible NAME (e.g. 'File', "
    "'Search', 'Send') to locate it - DO NOT take a screenshot or "
    "guess coordinates. ALWAYS pass the `app` window-title (e.g. "
    "app='Notepad') so UIA targets the right window even if focus "
    "didn't take.\n"
    "3. Act with `uia_click` (buttons/menus/channels) or `uia_type` "
    "(text boxes; clear_first=true to replace text, submit=true to "
    "press Enter and send/search in one step). After navigating, use "
    "`uia_wait` to block until the next control appears instead of "
    "guessing a delay.\n"
    "4. If `uia_find` returns nothing AND the app is Electron "
    "(VS Code, Slack, Discord, Spotify, Notion, Cursor...), call "
    "`electron_check` then `electron_unlock` on its .exe to relaunch "
    "with --force-renderer-accessibility, then retry uia_find.\n"
    "5. Only fall back to `screenshot` + coordinate clicks when a "
    "control has no accessible name (canvas/custom-drawn UI).\n"
    "6. Stop after at most 8 steps. If blocked, ask a clear question "
    "instead of looping.\n"
    "7. Never click Send / Submit / Pay / Delete without explicit "
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


def _clean_text(value: Any) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _short(value: Any, limit: int = 56) -> str:
    text = _clean_text(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _strip_hardening(goal: str) -> str:
    goal = str(goal or "")
    if goal.startswith(DESKTOP_HARDENING):
        return goal[len(DESKTOP_HARDENING):]
    return goal


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


def build_task_payload(goal: str) -> dict[str, Any]:
    mode = _detect_mode(goal)
    payload_goal = goal
    if mode in {"computer", "computer_use", "computer_isolated"}:
        payload_goal = DESKTOP_HARDENING + goal
    width, height = _screen_size()
    return {
        "task_id": "clicky-" + secrets.token_hex(5),
        "goal": payload_goal,
        "mode": mode,
        "screen_width": width,
        "screen_height": height,
        "autonomy_level": "balanced",
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

    def __init__(self, port: int, speak_replies: bool = False):
        super().__init__()
        self.client = BackendClient(port)
        self._stop = threading.Event()
        self._cursor = 0
        self._voice_task_ids: set[str] = set()
        self._speak_replies = bool(speak_replies)
        self.listenRequested.connect(self.listen_once)

    def start(self) -> None:
        threading.Thread(target=self._poll_loop, daemon=True).start()
        self._load_preferences_async()

    def stop(self) -> None:
        self._stop.set()

    def install_hotkey(self) -> bool:
        try:
            import keyboard

            keyboard.add_hotkey("ctrl+shift+m", self.listenRequested.emit)
            return True
        except Exception as exc:
            print(f"[clicky] voice hotkey unavailable: {exc}", flush=True)
            return False

    def _load_preferences_async(self) -> None:
        def run() -> None:
            try:
                prefs = self.client.request("GET", "/api/preferences", timeout=3.0)
                saved = prefs.get("preferences") if isinstance(prefs, dict) else {}
                if isinstance(saved, dict):
                    self._speak_replies = bool(
                        saved.get("speak_replies") or self._speak_replies
                    )
            except Exception:
                pass

        threading.Thread(target=run, daemon=True).start()

    def _poll_loop(self) -> None:
        idle_label_shown = False
        while not self._stop.is_set():
            try:
                data = self.client.request(
                    "GET",
                    f"/api/overlay/events?since={self._cursor}&limit=80",
                    timeout=4.0,
                )
                events = data.get("events", []) if isinstance(data, dict) else []
                if isinstance(data, dict):
                    self._cursor = max(self._cursor, int(data.get("cursor") or 0))
                for ev in events:
                    if not isinstance(ev, dict):
                        continue
                    try:
                        self._cursor = max(
                            self._cursor, int(ev.get("global_seq", -1)) + 1
                        )
                    except Exception:
                        pass
                    label = self._label_for_event(ev)
                    if label:
                        self.labelRequested.emit(label)
                        idle_label_shown = True
                    self._maybe_speak_final(ev)
                if not idle_label_shown:
                    self._prime_from_active_task()
                    idle_label_shown = True
            except Exception:
                if not idle_label_shown:
                    self.labelRequested.emit("Waiting for Orynn")
                    idle_label_shown = True
            self._stop.wait(0.45)

    def _prime_from_active_task(self) -> None:
        try:
            data = self.client.request("GET", "/api/active-tasks", timeout=3.0)
            tasks = data.get("tasks", []) if isinstance(data, dict) else []
            if not tasks:
                return
            tasks = [task for task in tasks if isinstance(task, dict)]
            tasks.sort(key=lambda task: str(task.get("created_at") or ""))
            task = tasks[-1]
            goal = _strip_hardening(str(task.get("goal") or "Working"))
            self.labelRequested.emit("Working: " + _short(goal, 42))
        except Exception:
            pass

    def _label_for_event(self, ev: dict[str, Any]) -> str:
        event_type = str(ev.get("type") or "")
        if event_type == "status":
            if ev.get("heartbeat"):
                return ""
            return _short(ev.get("message") or "Working")
        if event_type == "provider_info" and ev.get("retrying"):
            return _short(ev.get("message") or "Waiting on model")
        if event_type == "task_created":
            goal = _strip_hardening(str(ev.get("goal") or ""))
            return "Started: " + _short(goal, 45) if goal else "Started task"
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
            text = ev.get("text") or ""
            first_sentence = re.split(r"(?<=[.!?])\s+", str(text), maxsplit=1)[0]
            return _short(first_sentence)
        if event_type in {"approval_required", "permission_required"}:
            return "Needs approval"
        if event_type in {"approval_timeout", "permission_timeout"}:
            return "Approval timed out"
        if event_type in {"done", "complete"}:
            return _short(ev.get("reason") or "Done")
        if event_type in {"error", "failed"}:
            return _short(ev.get("reason") or ev.get("message") or "Task failed")
        if event_type == "cancelled":
            return "Cancelled"
        return ""

    def _maybe_speak_final(self, ev: dict[str, Any]) -> None:
        if not self._speak_replies:
            return
        if ev.get("type") not in {"done", "complete"}:
            return
        task_id = str(ev.get("task_id") or "")
        if task_id not in self._voice_task_ids:
            return
        text = _short(ev.get("reason") or "Done", 160)
        try:
            from . import voice

            voice.speak(text)
        except Exception:
            pass

    def listen_once(self) -> None:
        threading.Thread(target=self._listen_worker, daemon=True).start()

    def _listen_worker(self) -> None:
        try:
            from . import voice
        except Exception:
            self.labelRequested.emit("Voice unavailable")
            return

        if not voice.stt_available():
            self.labelRequested.emit("Voice unavailable")
            return

        self.labelRequested.emit("Listening...")
        try:
            transcript = voice.listen(timeout=8.0)
        except Exception:
            transcript = ""
        transcript = _clean_text(transcript)
        if not transcript:
            self.labelRequested.emit("Didn't catch that")
            return
        self.labelRequested.emit("Heard: " + _short(transcript, 44))
        self._submit_voice_task(transcript)

    def _submit_voice_task(self, transcript: str) -> None:
        payload = build_task_payload(transcript)
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
                    self.labelRequested.emit("Setup needed")
                    return
                if preflight.get("can_override") and preflight.get("issues"):
                    payload["readiness_override"] = True
            self.client.request("POST", "/api/tasks", payload, timeout=20.0)
            if task_id:
                self._voice_task_ids.add(task_id)
            self.labelRequested.emit("Working in background")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:180]
            self.labelRequested.emit(_short(body or "Couldn't start task"))
        except Exception:
            self.labelRequested.emit("Couldn't start task")


def _app_icon() -> QIcon:
    root = Path(__file__).resolve().parents[2]
    for name in ("app_icon.ico", "orynn_app_icon.png"):
        path = root / name
        if path.exists():
            return QIcon(str(path))
    return QIcon()


def _install_tray(app: QApplication, controller: OverlayController) -> QSystemTrayIcon | None:
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return None
    tray = QSystemTrayIcon(_app_icon(), app)
    tray.setToolTip("Orynn Clicky")
    menu = QMenu()
    listen = QAction("Listen now", menu)
    listen.triggered.connect(controller.listenRequested.emit)
    quit_action = QAction("Quit textbox", menu)
    quit_action.triggered.connect(app.quit)
    menu.addAction(listen)
    menu.addSeparator()
    menu.addAction(quit_action)
    tray.setContextMenu(menu)
    tray.show()
    return tray


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Orynn mouse textbox overlay.")
    parser.add_argument("--port", type=int, default=int(os.getenv("ORYNN_PORT", "8000")))
    parser.add_argument("--no-hotkey", action="store_true")
    parser.add_argument("--no-tray", action="store_true")
    parser.add_argument("--speak-replies", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
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
    controller.quitRequested.connect(app.quit)
    app.aboutToQuit.connect(controller.stop)

    tray = None
    if not args.no_tray:
        tray = _install_tray(app, controller)
        if tray is not None:
            # Keep the object alive for the lifetime of the app.
            app._orynn_tray = tray  # type: ignore[attr-defined]

    hotkey_ready = False if args.no_hotkey else controller.install_hotkey()
    controller.start()
    overlay.set_companion_label("Orynn ready" if hotkey_ready else "Orynn ready")
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())

"""Local smoke for the Gemini Live direct desktop gateway.

This does not call Gemini or use the microphone. It simulates the exact local
tool calls Gemini Live sends to OverlayController._live_tool("desktop_control",
...) and verifies that the gateway can drive a real Notepad window with UIA.

Run from the Orynn project root:

    python scripts/live_direct_desktop_smoke.py

It opens Notepad on a temporary file, types one line, verifies the UIA action,
then closes the window without saving.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.tools import ToolExecutor  # noqa: E402
from app.widget.textbox_overlay import OverlayController  # noqa: E402


def _discard_notepad_tab(tools: ToolExecutor, title_hint: str) -> None:
    try:
        tools.focus_window(title_hint)
        tools.key("ctrl+w")
        time.sleep(0.25)
        dont_save = tools.uia_find("Don't Save", title_hint)
        if dont_save.ok:
            tools.uia_click("Don't Save", title_hint)
    except Exception:
        pass


def _kill_process(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=3)
    except Exception:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/F"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            pass


def _step(
    controller: OverlayController,
    name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    started = time.perf_counter()
    result = controller._live_tool("desktop_control", args)
    return {
        "name": name,
        "ok": bool(result.get("ok")),
        "duration_s": round(time.perf_counter() - started, 3),
        "result": result,
    }


def main() -> int:
    QApplication.instance() or QApplication(sys.argv[:1])
    workspace = Path(tempfile.mkdtemp(prefix="orynn-live-direct-"))
    canary_file = workspace / f"orynn-live-direct-{int(time.time() * 1000)}.txt"
    canary_file.write_text("", encoding="utf-8")
    title_hint = canary_file.name
    text = f"Orynn Live direct smoke {int(time.time())}"

    controller = OverlayController(8000)
    tools = ToolExecutor(workspace)
    controller._desktop_tools = tools
    labels: list[str] = []
    states: list[str] = []
    overlays: list[dict[str, Any]] = []
    controller.labelRequested.connect(lambda value: labels.append(value))
    controller.cursorStateRequested.connect(lambda value: states.append(value))
    controller.overlayActionRequested.connect(lambda value: overlays.append(value))

    proc: subprocess.Popen | None = None
    steps: list[dict[str, Any]] = []
    try:
        proc = subprocess.Popen(["notepad.exe", str(canary_file)])
        steps.append(_step(
            controller,
            "wait_for_notepad",
            {"action": "wait_for_window", "title": title_hint, "timeout": 10},
        ))
        steps.append(_step(
            controller,
            "observe_notepad",
            {"action": "observe", "app": title_hint, "cap": 120},
        ))
        steps.append(_step(
            controller,
            "type_text",
            {
                "action": "type",
                "query": "Text editor",
                "app": title_hint,
                "text": text,
                "clear_first": True,
            },
        ))
        steps.append(_step(
            controller,
            "find_editor",
            {"action": "find", "query": "Text editor", "app": title_hint, "limit": 1},
        ))
    finally:
        _discard_notepad_tab(tools, title_hint)
        _kill_process(proc)
        try:
            canary_file.unlink(missing_ok=True)
        except Exception:
            pass

    type_result = next((s for s in steps if s["name"] == "type_text"), {})
    type_data = ((type_result.get("result") or {}).get("data") or {})
    verified = type_data.get("verified")
    failed = [s["name"] for s in steps if not s.get("ok")]
    if verified is False:
        failed.append("type_text_unverified")
    report = {
        "ok": not failed,
        "failed_steps": failed,
        "steps": steps,
        "labels_seen": labels[-8:],
        "states_seen": states[-8:],
        "overlay_events": len(overlays),
    }
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

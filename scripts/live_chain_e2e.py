"""Canonical full-chain Gemini Live e2e: voice intent -> real model -> whichever
tool the model picks -> the REAL production bridge (OverlayController._live_tool)
-> verify the effect actually happened on the desktop.

Unlike live_open_notepad.py (which only recognized start_desktop_task and broke
when the model started using the faster launch_app), this drives the model with
text, then dispatches the model's ACTUAL tool call through the real controller --
so it stays correct no matter which open/launch tool the model routes to.

Verification is by win32 window enumeration (we never close the user's windows;
we only check whether a Notepad-titled window EXISTS after the tool returns).

    python scripts/live_chain_e2e.py [N]      # default N=5 reps

Needs GEMINI_API_KEY/GOOGLE_API_KEY in .env and a real Windows desktop. The
backend is NOT required: launch_app runs locally; start_desktop_task needs :8000
(skipped-with-note if the model routes there and no backend is up). Exits 0 iff
every rep produced a Notepad window. Keys are never printed.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:
    pass

from app.widget.gemini_live import (  # noqa: E402
    GeminiLiveCallbacks,
    GeminiLiveCompanion,
    gemini_api_key,
)

REQUEST = "Open the Notepad app on my Windows computer. Just open it, nothing else."
OPEN_TOOLS = {"launch_app", "start_desktop_task", "desktop_control"}


def _notepad_windows() -> list[str]:
    """Return titles of all top-level windows that look like Notepad."""
    try:
        import win32gui
    except Exception:
        return []
    found: list[str] = []

    def _cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd) or ""
        cls = win32gui.GetClassName(hwnd) or ""
        if "Notepad" in title or cls == "Notepad":
            found.append(title or cls)

    win32gui.EnumWindows(_cb, None)
    return found


def _make_controller():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from app.widget.textbox_overlay import OverlayController

    QApplication.instance() or QApplication([])
    return OverlayController(8000)


async def _one(controller, idx: int) -> bool:
    from google import genai
    from google.genai import types

    comp = GeminiLiveCompanion(GeminiLiveCallbacks())
    config = comp._live_config(types)
    g = genai.Client(api_key=gemini_api_key())

    tool_name = None
    tool_args: dict = {}

    async with g.aio.live.connect(model=comp.model, config=config) as session:
        await session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=REQUEST)]),
            turn_complete=True,
        )
        async for message in session.receive():
            tc = getattr(message, "tool_call", None)
            calls = getattr(tc, "function_calls", None) if tc else None
            if not calls:
                sc = getattr(message, "server_content", None)
                if sc and getattr(sc, "turn_complete", False) and tool_name is None:
                    break  # model went text-only, no action
                continue
            call = calls[0]
            tool_name = str(getattr(call, "name", "") or "")
            tool_args = dict(getattr(call, "args", {}) or {})
            # ack so the model's turn closes cleanly
            await session.send_tool_response(
                function_responses=[
                    types.FunctionResponse(
                        name=tool_name, id=getattr(call, "id", None), response={"ok": True}
                    )
                ]
            )
            break

    if tool_name is None:
        print(f"[{idx}] FAIL: model did not call any tool (text-only)")
        return False
    if tool_name not in OPEN_TOOLS:
        print(f"[{idx}] FAIL: model called unexpected tool {tool_name!r} for a pure open")
        return False

    # Drive the REAL production bridge with the model's actual call.
    result = controller._live_tool(tool_name, tool_args)
    ok_flag = bool(isinstance(result, dict) and result.get("ok"))

    # Honest criterion: a Notepad window EXISTS after the call (covers both
    # launch-new and focus-existing; single-instance apps reuse one window).
    deadline = time.time() + 6
    appeared = False
    while time.time() < deadline:
        if _notepad_windows():
            appeared = True
            break
        time.sleep(0.4)

    status = "PASS" if appeared else "FAIL"
    print(
        f"[{idx}] {status}: tool={tool_name} ok={ok_flag} "
        f"window={'yes' if appeared else 'NONE'} "
        f"msg={str((result or {}).get('message',''))[:70]!r}"
    )
    return appeared


async def main() -> int:
    if not gemini_api_key():
        print("FAIL: no Gemini API key in .env")
        return 1
    try:
        controller = _make_controller()
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: could not build controller: {type(exc).__name__}: {exc}")
        return 1

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    passes = 0
    for i in range(n):
        try:
            ok = await asyncio.wait_for(_one(controller, i + 1), timeout=45)
        except Exception as exc:  # noqa: BLE001
            print(f"[{i+1}] FAIL: {type(exc).__name__}: {exc}")
            ok = False
        passes += 1 if ok else 0

    print(f"\nLIVE CHAIN: {passes}/{n} opened Notepad on the desktop")
    return 0 if passes == n else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

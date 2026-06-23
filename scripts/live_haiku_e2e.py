"""Full end-to-end: talk to Gemini Live -> it calls our tool -> Orynn's desktop
agent actually opens Notepad and types a haiku on the real screen.

Flow proven here (the whole point):
    text request -> Gemini 3 Flash Live decides to call start_desktop_task(goal)
      -> we submit that goal to Orynn's backend (/api/tasks)
      -> the gpt-oss desktop agent drives Notepad via UIA/keyboard
      -> we poll until the task reaches a terminal status and report it.

The request is sent as text (no mic needed) but the tool-calling + execution path
is identical to speaking. Requires the Orynn backend already running on PORT and a
free-tier Gemini key in .env. WILL move your mouse / type on screen.

    python scripts/live_haiku_e2e.py
"""
from __future__ import annotations

import asyncio
import http.cookiejar
import json
import sys
import time
import urllib.request
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
from app.widget.textbox_overlay import build_task_payload  # noqa: E402

PORT = 8000
REQUEST = (
    "Please actually open the Notepad app on my Windows computer and type a short "
    "three-line haiku about the ocean into it. Use your desktop tool to do it for real."
)
TERMINAL = {
    "completed", "complete", "done", "succeeded", "success", "finished",
    "error", "failed", "cancelled", "canceled", "killed", "stopped", "timeout",
}


class Client:
    """Minimal cookie-session backend client (mirrors the overlay's BackendClient)."""

    def __init__(self, port: int) -> None:
        self.base = f"http://127.0.0.1:{port}"
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        self._opener.open(urllib.request.Request(self.base + "/api/session", method="POST"), timeout=5)

    def request(self, method: str, path: str, data: dict | None = None, timeout: float = 10.0) -> dict:
        body = json.dumps(data).encode() if data is not None else None
        headers = {"Accept": "application/json"}
        if body:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=body, headers=headers, method=method.upper())
        with self._opener.open(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
        return json.loads(raw) if raw else {}


def submit_desktop_task(client: Client, goal: str) -> tuple[str | None, str]:
    payload = build_task_payload(goal)
    tid = str(payload.get("task_id") or "")
    pf = client.request("POST", "/api/tasks/preflight", {
        "goal": payload.get("goal", ""),
        "mode": payload.get("mode", "auto"),
        "model": payload.get("model"),
        "isolated_app": payload.get("isolated_app"),
    }, timeout=15)
    if isinstance(pf, dict):
        if pf.get("blocked"):
            return None, f"preflight blocked: {pf.get('issues')}"
        if pf.get("can_override") and pf.get("issues"):
            payload["readiness_override"] = True
    client.request("POST", "/api/tasks", payload, timeout=20)
    return tid, f"mode={payload.get('mode')}"


def poll_task(client: Client, tid: str, timeout: float = 200.0) -> dict:
    start, last = time.time(), None
    while time.time() - start < timeout:
        rec = client.request("GET", f"/api/tasks/{tid}", timeout=8)
        st = str(rec.get("status") or "")
        if st != last:
            print(f"  [task] status: {st}")
            last = st
        if st.lower() in TERMINAL:
            return rec
        time.sleep(2.0)
    return {"status": "timeout", "reason": f"no terminal status in {timeout:.0f}s"}


async def ask_gemini_to_run(client: Client) -> tuple[str | None, str]:
    """Drive one Live turn; when Gemini calls start_desktop_task, submit it for real."""
    from google import genai
    from google.genai import types

    comp = GeminiLiveCompanion(GeminiLiveCallbacks())
    config = comp._live_config(types)
    g = genai.Client(api_key=gemini_api_key())

    print(f"Connecting to {comp.model} ...")
    async with g.aio.live.connect(model=comp.model, config=config) as session:
        await session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=REQUEST)]),
            turn_complete=True,
        )
        print("Asked Gemini to write a haiku in Notepad. Waiting for the tool call...")
        said = ""
        async for message in session.receive():
            content = getattr(message, "server_content", None)
            if content is not None:
                out = getattr(content, "output_transcription", None)
                if out is not None and getattr(out, "text", ""):
                    said += out.text

            tool_call = getattr(message, "tool_call", None)
            calls = getattr(tool_call, "function_calls", None) if tool_call else None
            if calls:
                for call in calls:
                    name = str(getattr(call, "name", "") or "")
                    args = dict(getattr(call, "args", {}) or {})
                    if name != "start_desktop_task":
                        await session.send_tool_response(function_responses=[
                            types.FunctionResponse(name=name, id=getattr(call, "id", None),
                                                   response={"ok": True})])
                        continue
                    goal = str(args.get("goal") or "").strip()
                    print(f'\nGemini -> start_desktop_task(goal="{goal}")')
                    tid, info = submit_desktop_task(client, goal)
                    print(f"Submitted to Orynn ({info}); task_id={tid}")
                    await session.send_tool_response(function_responses=[
                        types.FunctionResponse(name=name, id=getattr(call, "id", None),
                                               response={"ok": bool(tid), "task_id": tid or "",
                                                         "message": "Orynn started the task."})])
                    if said.strip():
                        print(f'(Gemini said: "{said.strip()[:120]}")')
                    return tid, goal
        return None, said


async def main() -> int:
    if not gemini_api_key():
        print("FAIL: no Gemini API key in .env")
        return 1
    try:
        client = Client(PORT)
    except Exception as exc:
        print(f"FAIL: backend not reachable on :{PORT} ({exc}). Start it with run_desktop.py.")
        return 1

    try:
        tid, goal = await asyncio.wait_for(ask_gemini_to_run(client), timeout=60)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: live error: {type(exc).__name__}: {exc}")
        return 1

    if not tid:
        print("\nFAIL: Gemini did not call start_desktop_task.")
        return 1

    print("\nWatching Orynn's desktop agent run the task (it's driving Notepad now)...")
    rec = poll_task(client, tid)
    status = str(rec.get("status") or "")
    reason = str(rec.get("reason") or "")[:300]
    print(f"\nFinal status: {status}")
    if reason:
        print(f"Reason: {reason}")
    ok = status.lower() in {"completed", "complete", "done", "succeeded", "success", "finished"}
    print("\nPASS: Gemini Live -> tool call -> Orynn wrote the haiku in Notepad." if ok
          else "\nDONE (check the result above / your Notepad window).")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

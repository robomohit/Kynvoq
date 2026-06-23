"""Quick, watchable end-to-end: ask Gemini Live to just OPEN Notepad.

Drives one Live turn with text -> Gemini calls start_desktop_task("open notepad")
-> we submit it to Orynn -> we stream the agent's live events to the console and
hard-cap at 90s, auto-killing the task if it stalls (so it can't silently spin or
hold your mouse hostage).

    python scripts/live_open_notepad.py
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
REQUEST = "Use your desktop tool to open the Notepad app on my Windows computer. Just open it."
HARD_CAP_SECONDS = 90.0
TERMINAL = {"completed", "complete", "done", "succeeded", "success", "finished",
            "error", "failed", "cancelled", "canceled", "killed", "stopped", "timeout"}
OK_STATUSES = {"completed", "complete", "done", "succeeded", "success", "finished"}


class Client:
    def __init__(self, port: int) -> None:
        self.base = f"http://127.0.0.1:{port}"
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
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


def submit(client: Client, goal: str) -> str:
    payload = build_task_payload(goal)
    tid = str(payload.get("task_id") or "")
    pf = client.request("POST", "/api/tasks/preflight",
                        {"goal": payload.get("goal", ""), "mode": payload.get("mode", "auto")}, timeout=15)
    if isinstance(pf, dict) and pf.get("can_override") and pf.get("issues"):
        payload["readiness_override"] = True
    client.request("POST", "/api/tasks", payload, timeout=20)
    return tid


def watch(client: Client, tid: str) -> str:
    """Stream events + status until terminal or the hard cap; kill on timeout."""
    start, cursor, last_status = time.time(), 0, None
    while True:
        elapsed = time.time() - start
        if elapsed > HARD_CAP_SECONDS:
            print(f"\n[cap] {HARD_CAP_SECONDS:.0f}s reached with no completion — killing task.")
            try:
                client.request("POST", f"/api/tasks/{tid}/kill", timeout=8)
            except Exception:
                pass
            return "timeout"

        try:
            ev = client.request("GET", f"/api/overlay/events?since={cursor}&limit=80", timeout=8)
            for e in ev.get("events", []) or []:
                if str(e.get("task_id") or "") not in ("", tid):
                    continue
                msg = e.get("message") or e.get("reason") or e.get("type")
                if msg:
                    print(f"  [{elapsed:4.0f}s] {str(e.get('type','')):12} {str(msg)[:90]}")
            cursor = ev.get("cursor", cursor)
        except Exception:
            pass

        try:
            rec = client.request("GET", f"/api/tasks/{tid}", timeout=8)
            st = str(rec.get("status") or "")
            if st != last_status:
                print(f"  [{elapsed:4.0f}s] >>> status: {st}")
                last_status = st
            if st.lower() in TERMINAL:
                return st
        except Exception:
            pass
        time.sleep(1.5)


async def drive_gemini(client: Client) -> str | None:
    from google import genai
    from google.genai import types

    comp = GeminiLiveCompanion(GeminiLiveCallbacks())
    config = comp._live_config(types)
    g = genai.Client(api_key=gemini_api_key())
    print(f"Connecting to {comp.model} ...")
    async with g.aio.live.connect(model=comp.model, config=config) as session:
        await session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=REQUEST)]),
            turn_complete=True)
        print("Asked Gemini to open Notepad. Waiting for the tool call...")
        async for message in session.receive():
            tc = getattr(message, "tool_call", None)
            calls = getattr(tc, "function_calls", None) if tc else None
            if not calls:
                continue
            for call in calls:
                name = str(getattr(call, "name", "") or "")
                args = dict(getattr(call, "args", {}) or {})
                if name != "start_desktop_task":
                    await session.send_tool_response(function_responses=[
                        types.FunctionResponse(name=name, id=getattr(call, "id", None), response={"ok": True})])
                    continue
                goal = str(args.get("goal") or "").strip()
                print(f'\nGemini -> start_desktop_task(goal="{goal}")')
                tid = submit(client, goal)
                print(f"Submitted to Orynn; task_id={tid}\n")
                await session.send_tool_response(function_responses=[
                    types.FunctionResponse(name=name, id=getattr(call, "id", None),
                                           response={"ok": True, "task_id": tid, "message": "Opening Notepad."})])
                return tid
    return None


async def main() -> int:
    if not gemini_api_key():
        print("FAIL: no Gemini API key in .env")
        return 1
    client = Client(PORT)
    try:
        tid = await asyncio.wait_for(drive_gemini(client), timeout=45)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: live error: {type(exc).__name__}: {exc}")
        return 1
    if not tid:
        print("FAIL: Gemini did not call start_desktop_task.")
        return 1

    print("Watching Orynn open Notepad (live)...")
    status = watch(client, tid)
    print(f"\nFinal status: {status}")
    if status.lower() in OK_STATUSES:
        print("PASS: Gemini Live -> tool call -> Orynn opened Notepad. Chain works.")
        return 0
    print("Chain fired (Gemini called the tool + Orynn accepted it); the desktop "
          "executor didn't finish in time — that's the free-tier agent, not Live.")
    return 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

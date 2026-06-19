"""Overnight QA matrix: drive the REAL Gemini Live model with many varied text
prompts (no microphone) and record which tool it routes each to, then execute a
curated SAFE set of tool calls through the real OverlayController to fill the task /
overlay / label logs and exercise the execution code paths.

Two phases:
  A. routing matrix — one fresh Live session per prompt, capture the model's tool
     call (or text-only), post a dummy FunctionResponse. No side effects. This is
     where ROUTING logic errors show up (chat that spawns a task, a disruptive verb
     that skips consent, etc.).
  B. execution probes — call controller._live_tool(...) directly for a safe set
     (run_terminal reads, observe/find, look_at_screen, web_search, a real
     "open Notepad and type" task, an escalating click, consent gate, stop). Fills
     logs and surfaces CODE errors in the tool-execution path.

Run from the project root with the backend already running on :8000:
    python scripts/live_qa_matrix.py            # both phases
    python scripts/live_qa_matrix.py --routing   # phase A only
    python scripts/live_qa_matrix.py --exec      # phase B only

Needs GEMINI_API_KEY/GOOGLE_API_KEY. Prints a matrix + JSON summary; never prints keys.
"""
from __future__ import annotations

import asyncio
import json
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

# (prompt, expectation tag) — tag is what a CORRECT route looks like, for the scan.
ROUTING_PROMPTS = [
    ("What's the capital of France?", "chat:none"),
    ("Tell me a quick joke.", "chat:none"),
    ("What's the weather in Tokyo right now?", "web_search"),
    ("Who won the last Super Bowl?", "web_search"),
    ("What's currently on my screen?", "look_at_screen"),
    ("Read what this error dialog says.", "look_at_screen"),
    ("Run git status for me.", "run_terminal"),
    ("List the files in my current folder.", "run_terminal"),
    ("Open Notepad.", "start_desktop_task"),
    ("Open Notepad and type hello world.", "start_desktop_task"),
    ("Click the New Agent button in Cursor.", "start_desktop_task|desktop_control"),
    ("Open Calculator and compute 12 times 9.", "start_desktop_task"),
    ("Set up my email signature.", "start_desktop_task"),
    ("Press Ctrl+S to save.", "desktop_control|start_desktop_task"),
    ("Scroll down on this page.", "desktop_control|start_desktop_task"),
    ("Delete everything in my Downloads folder.", "consent|start_desktop_task"),
    ("Send a message to John saying I'll be late.", "consent|start_desktop_task"),
    ("Stop what you're doing.", "stop_current_task"),
    ("Did the last task work?", "get_companion_status"),
    ("Open my Documents folder and find the budget spreadsheet, then open it.", "start_desktop_task"),
]

PER_PROMPT_TIMEOUT = 35.0


async def _route_one(comp, genai, types, client, prompt: str) -> dict:
    """One fresh Live session: send `prompt`, return the first tool call (or text)."""
    out = {"tool": None, "args": None, "text_only": False, "error": None}
    config = comp._live_config(types)
    try:
        async with client.aio.live.connect(model=comp.model, config=config) as session:
            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text=prompt)]),
                turn_complete=True,
            )
            got_text = False
            async for message in session.receive():
                tc = getattr(message, "tool_call", None)
                calls = getattr(tc, "function_calls", None) if tc else None
                if calls:
                    call = calls[0]
                    out["tool"] = str(getattr(call, "name", "") or "")
                    out["args"] = dict(getattr(call, "args", {}) or {})
                    resp = [types.FunctionResponse(name=out["tool"], id=getattr(call, "id", None),
                                                   response={"ok": True, "task_id": "qa"})]
                    await session.send_tool_response(function_responses=resp)
                    await asyncio.sleep(0.3)
                    return out
                content = getattr(message, "server_content", None)
                if content is not None:
                    ot = getattr(content, "output_transcription", None)
                    if ot is not None and getattr(ot, "text", ""):
                        got_text = True
                    if getattr(content, "turn_complete", False):
                        out["text_only"] = got_text
                        return out
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


async def run_routing() -> list[dict]:
    from google import genai
    from google.genai import types
    key = gemini_api_key()
    if not key:
        raise RuntimeError("no Gemini API key in environment (.env)")
    comp = GeminiLiveCompanion(GeminiLiveCallbacks())
    client = genai.Client(api_key=key)
    print(f"Routing matrix against {comp.model} ({len(ROUTING_PROMPTS)} prompts)\n")
    rows = []
    for prompt, expect in ROUTING_PROMPTS:
        try:
            r = await asyncio.wait_for(_route_one(comp, genai, types, client, prompt), timeout=PER_PROMPT_TIMEOUT)
        except asyncio.TimeoutError:
            r = {"tool": None, "args": None, "text_only": False, "error": "timeout"}
        chose = r["tool"] or ("(text-only)" if r["text_only"] else (r["error"] or "(nothing)"))
        ok = _route_ok(expect, r)
        flag = "ok " if ok else "FLAG"
        print(f"  [{flag}] {prompt[:54]:54} -> {chose}")
        rows.append({"prompt": prompt, "expect": expect, "got": chose,
                     "tool": r["tool"], "args": r["args"], "text_only": r["text_only"],
                     "error": r["error"], "ok": ok})
    return rows


def _route_ok(expect: str, r: dict) -> bool:
    opts = expect.split(":")[0].split("|") if ":" in expect or "|" in expect else [expect]
    # normalize: "chat:none" -> ["chat"], "consent|start_desktop_task" -> [...]
    opts = expect.replace("chat:none", "none").split("|")
    tool = r["tool"]
    if "none" in opts:
        return tool is None  # chat: must NOT call a tool
    if tool is None:
        return False
    # "consent" is satisfied by start_desktop_task (the glue applies the gate) too.
    norm = set(opts) | ({"start_desktop_task"} if "consent" in opts else set())
    return tool in norm


# ── Phase B: execution probes through the real controller ─────────────────────
def run_exec_probes() -> list[dict]:
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from app.widget.textbox_overlay import OverlayController
    QApplication.instance() or QApplication([])
    c = OverlayController(8000)
    probes = [
        ("run_terminal", {"command": "echo hello"}),
        ("run_terminal", {"command": "git status"}),
        ("run_terminal", {"command": "ls"}),               # exercises Windows translation
        ("run_terminal", {"command": "dir"}),
        ("run_terminal", {"command": "del nonexistent.txt"}),   # consent gate
        ("web_search", {"query": "python release notes"}),
        ("get_companion_status", {}),
        ("desktop_control", {"action": "observe", "app": "Notepad"}),
        ("desktop_control", {"action": "find", "query": "Text editor", "app": "Notepad"}),
        ("desktop_control", {"action": "press_keys", "keys": "ctrl+a", "app": "Notepad"}),
        ("look_at_screen", {"question": "what app is in focus?"}),
        ("start_desktop_task", {"goal": "open Notepad and type QA matrix line"}),
        ("desktop_control", {"action": "click", "query": "Delete", "app": "File Explorer"}),  # consent
    ]
    rows = []
    for name, args in probes:
        t0 = time.monotonic()
        try:
            res = c._live_tool_for_generation(None, name, args)
            dt = round((time.monotonic() - t0) * 1000)
            ok = bool(isinstance(res, dict) and res.get("ok"))
            tag = "consent" if isinstance(res, dict) and res.get("needs_consent") else ("ok" if ok else "fail")
            msg = str((res or {}).get("message") or (res or {}).get("output") or "")[:70]
            print(f"  [{tag:7}] {name}({list(args.values())[0] if args else ''})  {dt}ms  {msg}")
            rows.append({"tool": name, "args": args, "result": tag, "ms": dt, "msg": msg})
        except Exception as exc:  # noqa: BLE001
            print(f"  [ERROR ] {name}: {type(exc).__name__}: {exc}")
            rows.append({"tool": name, "args": args, "result": "EXCEPTION", "error": f"{type(exc).__name__}: {exc}"})
        time.sleep(0.4)
    return rows


def main() -> int:
    do_routing = "--exec" not in sys.argv
    do_exec = "--routing" not in sys.argv
    summary = {}
    if do_routing:
        rows = asyncio.run(run_routing())
        flags = [r for r in rows if not r["ok"]]
        summary["routing"] = {"total": len(rows), "flagged": len(flags),
                              "flags": [{"prompt": r["prompt"], "expect": r["expect"], "got": r["got"]} for r in flags]}
        print(f"\nRouting: {len(rows)-len(flags)}/{len(rows)} matched expectation; {len(flags)} flagged.\n")
    if do_exec:
        print("Execution probes (real controller -> backend on :8000):\n")
        erows = run_exec_probes()
        exc = [r for r in erows if r["result"] in ("EXCEPTION",)]
        summary["exec"] = {"total": len(erows), "exceptions": len(exc), "rows": erows}
        print(f"\nExec: {len(erows)} probes, {len(exc)} raised an exception.\n")
    Path(ROOT / "logs" / "live_qa_matrix_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print("Summary written to logs/live_qa_matrix_summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

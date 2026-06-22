"""Phase 3 sequential live gate runner (one Live session at a time).

Usage (from Orynn root):
    $env:ORYNN_LABEL_LOG="1"
    python docs/implementation-storm/phase3-live/run_phase3_gates.py

Writes docs/implementation-storm/phase3-live/gate_results.json
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:
    pass

os.environ.setdefault("ORYNN_LABEL_LOG", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("ORYNN_LIVE_TASK_WAIT", "0")

LEAK_PATTERNS = [
    "failed: server restarted",
    "server restarted",
    "uia_no_match",
    "invokepattern",
    "traceback",
]

PORT = int(os.getenv("ORYNN_PORT") or "8000")


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sanitize(res):
    try:
        return json.loads(json.dumps(res, default=str))
    except Exception:
        return {"ok": False, "message": str(res)[:300]}


async def _drive_one(comp, client, types, controller, prompt: str, *, max_tools: int = 3) -> dict:
    """One fresh Live session: prompt -> tool(s) -> real execution -> reply."""
    labels_sink: list[str] = []
    orig_set_label = controller._set_label

    def _capture_label(text, **kw):
        labels_sink.append(str(text or ""))
        return orig_set_label(text, **kw)

    controller._set_label = _capture_label  # type: ignore[method-assign]
    out = {
        "prompt": prompt,
        "tools": [],
        "tool_results": [],
        "reply": "",
        "labels": [],
        "audio_bytes": 0,
        "error": None,
        "started_at": _ts(),
    }
    config = comp._live_config(types)
    try:
        async with client.aio.live.connect(model=comp.model, config=config) as session:
            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text=prompt)]),
                turn_complete=True,
            )
            reply_parts: list[str] = []
            tool_rounds = 0
            async for message in session.receive():
                tc = getattr(message, "tool_call", None)
                calls = getattr(tc, "function_calls", None) if tc else None
                if calls:
                    fr = []
                    for call in calls:
                        name = str(getattr(call, "name", "") or "")
                        args = dict(getattr(call, "args", {}) or {})
                        res = controller._live_tool_for_generation(None, name, args)
                        out["tools"].append({"name": name, "args": args})
                        out["tool_results"].append(_sanitize(res))
                        fr.append(
                            types.FunctionResponse(
                                name=name,
                                id=getattr(call, "id", None),
                                response=_sanitize(res),
                            )
                        )
                    await session.send_tool_response(function_responses=fr)
                    tool_rounds += 1
                    if tool_rounds >= max_tools:
                        break
                    continue
                content = getattr(message, "server_content", None)
                if content is not None:
                    ot = getattr(content, "output_transcription", None)
                    if ot is not None and getattr(ot, "text", ""):
                        reply_parts.append(ot.text)
                    turn = getattr(content, "model_turn", None)
                    for part in getattr(turn, "parts", []) or []:
                        data = getattr(getattr(part, "inline_data", None), "data", None)
                        if data:
                            out["audio_bytes"] += len(data)
                    if getattr(content, "turn_complete", False):
                        out["reply"] = "".join(reply_parts).strip()
                        break
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        controller._set_label = orig_set_label  # type: ignore[method-assign]
    out["labels"] = labels_sink
    out["ended_at"] = _ts()
    return out


def _bubble_leak(labels: list[str], reply: str) -> list[str]:
    blob = (reply + " " + " ".join(labels)).lower()
    return [p for p in LEAK_PATTERNS if p in blob]


async def scenario_e03_spotify(comp, client, types, controller) -> dict:
    """E03: open Spotify (or Notepad fallback) via launch_app; no bubble leak."""
    for app_prompt in ("Open Spotify on my computer.", "Open Spotify.", "Just open Notepad."):
        row = await _drive_one(comp, client, types, controller, app_prompt, max_tools=2)
        tools = [t["name"] for t in row.get("tools") or []]
        leaks = _bubble_leak(row.get("labels") or [], row.get("reply") or "")
        launch_ok = any(
            isinstance(r, dict) and r.get("ok")
            for r in row.get("tool_results") or []
            if (row.get("tools") or [{}])[0].get("name") == "launch_app"
        ) if "launch_app" in tools else None
        if "launch_app" in tools or row.get("error"):
            row["scenario"] = "E03_spotify_launch"
            row["pass"] = "launch_app" in tools and not leaks and not row.get("error")
            row["routing"] = tools
            row["leaks"] = leaks
            row["launch_ok"] = launch_ok
            row["notes"] = (
                "Used launch_app specialist"
                if "launch_app" in tools
                else f"Routed to {tools} instead of launch_app"
            )
            return row
    row["scenario"] = "E03_spotify_launch"
    row["pass"] = False
    row["notes"] = "Model never called launch_app"
    return row


async def scenario_e04_calculator(comp, client, types, controller) -> dict:
    """E04: Calculator e2e compute."""
    row = await _drive_one(
        comp,
        client,
        types,
        controller,
        "Open Calculator and compute 17 times 23 for me.",
        max_tools=4,
    )
    tools = [t["name"] for t in row.get("tools") or []]
    leaks = _bubble_leak(row.get("labels") or [], row.get("reply") or "")
    reply_l = (row.get("reply") or "").lower()
    spoken_391 = "391" in reply_l or "three hundred ninety" in reply_l
    any_ok = any(isinstance(r, dict) and r.get("ok") for r in row.get("tool_results") or [])
    row["scenario"] = "E04_calculator_e2e"
    row["pass"] = not leaks and not row.get("error") and (spoken_391 or any_ok)
    row["routing"] = tools
    row["leaks"] = leaks
    row["spoken_391"] = spoken_391
    row["notes"] = f"tools={tools}; reply_len={len(row.get('reply') or '')}"
    return row


async def scenario_e02_silent_turns(comp, client, types, controller) -> dict:
    """E02: background task should produce spoken update (audio or transcript)."""
    row = await _drive_one(
        comp,
        client,
        types,
        controller,
        "Open Notepad and type the word hello. Tell me when it's done.",
        max_tools=4,
    )
    leaks = _bubble_leak(row.get("labels") or [], row.get("reply") or "")
    has_audio = int(row.get("audio_bytes") or 0) > 500
    has_reply = bool((row.get("reply") or "").strip())
    row["scenario"] = "E02_silent_turns"
    row["pass"] = not leaks and not row.get("error") and (has_audio or has_reply)
    row["audio_bytes"] = row.get("audio_bytes")
    row["leaks"] = leaks
    row["notes"] = f"audio={has_audio} reply={has_reply}"
    return row


async def scenario_routing_launch(comp, client, types, controller) -> dict:
    """launch_app vs start_desktop_task routing check."""
    cases = [
        ("Open Notepad.", "launch_app"),
        ("Open Notepad and type hello world.", "start_desktop_task"),
        ("Open Calculator.", "launch_app"),
    ]
    results = []
    for prompt, expect in cases:
        row = await _drive_one(comp, client, types, controller, prompt, max_tools=1)
        got = (row.get("tools") or [{}])[0].get("name") if row.get("tools") else None
        ok = got == expect
        results.append({"prompt": prompt, "expect": expect, "got": got, "ok": ok})
    passed = sum(1 for r in results if r["ok"])
    return {
        "scenario": "routing_launch_vs_task",
        "pass": passed >= 2,
        "cases": results,
        "notes": f"{passed}/{len(results)} routing matches",
        "started_at": _ts(),
        "ended_at": _ts(),
    }


async def scenario_e05_vision(comp, client, types, controller) -> dict:
    """E05: vision peek — look_at_screen with frame_age_ms if available."""
    row = await _drive_one(
        comp,
        client,
        types,
        controller,
        "What's on my screen right now? Use your vision tool.",
        max_tools=2,
    )
    tools = [t["name"] for t in row.get("tools") or []]
    frame_age = None
    for r in row.get("tool_results") or []:
        if isinstance(r, dict) and "frame_age_ms" in r:
            frame_age = r.get("frame_age_ms")
    leaks = _bubble_leak(row.get("labels") or [], row.get("reply") or "")
    row["scenario"] = "E05_vision_peek"
    row["pass"] = "look_at_screen" in tools and not leaks and not row.get("error")
    row["frame_age_ms"] = frame_age
    row["routing"] = tools
    row["leaks"] = leaks
    return row


async def scenario_complex_notepad(comp, client, types, controller) -> dict:
    """Complex: open notepad, type hello."""
    row = await _drive_one(
        comp,
        client,
        types,
        controller,
        "Open Notepad, type hello, and save nothing — just type hello.",
        max_tools=4,
    )
    leaks = _bubble_leak(row.get("labels") or [], row.get("reply") or [])
    row["scenario"] = "complex_notepad"
    row["pass"] = not leaks and not row.get("error") and bool(row.get("tools"))
    row["leaks"] = leaks
    return row


async def scenario_web_search(comp, client, types, controller) -> dict:
    row = await _drive_one(
        comp,
        client,
        types,
        controller,
        "Who won the last Super Bowl? Search the web and tell me.",
        max_tools=2,
    )
    tools = [t["name"] for t in row.get("tools") or []]
    row["scenario"] = "web_search"
    row["pass"] = "web_search" in tools and not row.get("error")
    row["routing"] = tools
    return row


async def main() -> int:
    from google import genai
    from google.genai import types
    from PySide6.QtWidgets import QApplication

    from app.widget.gemini_live import GeminiLiveCallbacks, GeminiLiveCompanion, gemini_api_key
    from app.widget.textbox_overlay import OverlayController

    key = gemini_api_key()
    if not key:
        print("BLOCKER: no Gemini API key")
        (OUT / "gate_results.json").write_text(
            json.dumps({"blocker": "no_api_key", "at": _ts()}, indent=2),
            encoding="utf-8",
        )
        return 2

    QApplication.instance() or QApplication([])
    comp = GeminiLiveCompanion(GeminiLiveCallbacks())
    client = genai.Client(api_key=key)
    controller = OverlayController(PORT)

    print(f"Phase 3 gates — model={comp.model} port={PORT} ORYNN_LABEL_LOG=1\n")

    scenarios = [
        ("E03", scenario_e03_spotify),
        ("E04", scenario_e04_calculator),
        ("E02", scenario_e02_silent_turns),
        ("routing", scenario_routing_launch),
    ]
    results: list[dict] = []
    agent1_pass = True
    for tag, fn in scenarios:
        print(f"--- Running {tag} ---")
        row = await fn(comp, client, types, controller)
        results.append(row)
        ok = bool(row.get("pass"))
        agent1_pass = agent1_pass and ok
        print(f"  -> {'PASS' if ok else 'FAIL'} {row.get('notes', '')}\n")
        if tag == "E03" and not ok and row.get("leaks"):
            print("  BLOCKER: bubble leak on E03 — stopping Agent 1 extended.")
            break

    if agent1_pass:
        print("Agent 1 passed — running Agent 2 extended scenarios\n")
        for tag, fn in [
            ("E05", scenario_e05_vision),
            ("complex", scenario_complex_notepad),
            ("web_search", scenario_web_search),
        ]:
            print(f"--- Running {tag} ---")
            row = await fn(comp, client, types, controller)
            results.append(row)
            print(f"  -> {'PASS' if row.get('pass') else 'FAIL'}\n")
    else:
        results.append(
            {
                "scenario": "agent2_skipped",
                "pass": False,
                "notes": "Agent 1 gate failed — extended scenarios skipped",
            }
        )

    results.append(
        {
            "scenario": "WS5_browser_task",
            "pass": None,
            "skip": True,
            "notes": "browser_task not implemented in Phase 2 (WS5 deferred)",
        }
    )

    summary = {
        "run_at": _ts(),
        "model": comp.model,
        "port": PORT,
        "agent1_pass": agent1_pass,
        "results": results,
    }
    (OUT / "gate_results.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {OUT / 'gate_results.json'}")
    fails = [r["scenario"] for r in results if r.get("pass") is False]
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

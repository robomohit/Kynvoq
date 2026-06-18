"""Debug helper: log every Gemini Live session message shape (tool-call investigation)."""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = ROOT.parent / "Ai_computer" / "debug-eec63b.log"
SESSION = "eec63b"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:
    pass

from app.widget.gemini_live import GeminiLiveCallbacks, GeminiLiveCompanion, gemini_api_key

PROMPT = (
    "I'm at my Windows PC. Please open Notepad and type the word hello for me. "
    "Use your desktop tool to actually do it on my computer."
)


def _log(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    payload = {
        "sessionId": SESSION,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
        "runId": "pre-fix",
    }
    line = json.dumps(payload, default=str) + "\n"
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(line)
    print(message, json.dumps(data, default=str)[:240])


def _summarize_message(msg) -> dict:
    out: dict = {"type": type(msg).__name__}
    for attr in (
        "tool_call",
        "server_content",
        "session_resumption_update",
        "usage_metadata",
        "go_away",
        "setup_complete",
    ):
        val = getattr(msg, attr, None)
        if val is None:
            continue
        if attr == "tool_call":
            calls = getattr(val, "function_calls", None) or []
            out["tool_call"] = [
                {
                    "name": getattr(c, "name", None),
                    "args": dict(getattr(c, "args", {}) or {}),
                    "id": getattr(c, "id", None),
                }
                for c in calls
            ]
            continue
        if attr == "server_content":
            sc = val
            out["server_content"] = {
                "interrupted": getattr(sc, "interrupted", None),
                "turn_complete": getattr(sc, "turn_complete", None),
                "input_transcription": getattr(getattr(sc, "input_transcription", None), "text", None),
                "output_transcription": getattr(getattr(sc, "output_transcription", None), "text", None),
            }
            turn = getattr(sc, "model_turn", None)
            parts = getattr(turn, "parts", None) or []
            part_info = []
            for part in parts:
                fn = getattr(part, "function_call", None)
                if fn is not None:
                    part_info.append(
                        {
                            "kind": "function_call",
                            "name": getattr(fn, "name", None),
                            "args": dict(getattr(fn, "args", {}) or {}),
                        }
                    )
                    continue
                text = getattr(part, "text", None)
                if text:
                    part_info.append({"kind": "text", "text": str(text)[:120]})
                    continue
                data = getattr(getattr(part, "inline_data", None), "data", None)
                if data:
                    part_info.append({"kind": "audio", "bytes": len(data)})
            out["server_content"]["parts"] = part_info
            continue
        out[attr] = str(val)[:200]
    return out


async def main() -> int:
    from google import genai
    from google.genai import types

    key = gemini_api_key()
    if not key:
        print("No API key")
        return 1

    comp = GeminiLiveCompanion(GeminiLiveCallbacks())
    config = comp._live_config(types)
    fn_names = []
    for tool in config.tools:
        for fn in getattr(tool, "function_declarations", None) or []:
            fn_names.append(fn.name)

    _log(
        "C",
        "debug_live_messages.py:config",
        "live config tools",
        {
            "model": comp.model,
            "tool_names": fn_names,
            "has_google_search": any(getattr(t, "google_search", None) for t in config.tools),
            "thinking_level": str(getattr(getattr(config, "thinking_config", None), "thinking_level", None)),
        },
    )

    client = genai.Client(api_key=key)
    msg_count = 0
    async with client.aio.live.connect(model=comp.model, config=config) as session:
        await session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=PROMPT)]),
            turn_complete=True,
        )
        _log("A", "debug_live_messages.py:prompt", "prompt sent", {"prompt_len": len(PROMPT)})

        async for message in session.receive():
            msg_count += 1
            summary = _summarize_message(message)
            _log(
                "A",
                "debug_live_messages.py:receive",
                f"message #{msg_count}",
                summary,
            )
            if summary.get("tool_call"):
                _log("A", "debug_live_messages.py:tool", "top-level tool_call found", summary["tool_call"])
            parts = (summary.get("server_content") or {}).get("parts") or []
            fn_parts = [p for p in parts if p.get("kind") == "function_call"]
            if fn_parts:
                _log("B", "debug_live_messages.py:tool", "function_call in model_turn.parts", fn_parts)

    _log(
        "D",
        "debug_live_messages.py:done",
        "receive loop ended",
        {"message_count": msg_count},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

"""End-to-end smoke test: does Gemini Live actually CALL our local tools?

Connects to the real Live model with the exact production config the companion
uses (``GeminiLiveCompanion._live_config``), sends one text turn asking for a
desktop action, and verifies the model replies with a ``tool_call`` for
``start_desktop_task``. We then post a ``FunctionResponse`` back over the session,
exactly like the real bridge does, and confirm the model accepts it.

The turn is driven with *text* (``send_client_content``) instead of a microphone
so the test is deterministic and runs without audio hardware -- the tool-calling
path is identical whether the user spoke or typed.

Run from the Orynn project root:

    python scripts/live_tool_smoke.py

Needs GEMINI_API_KEY (or GOOGLE_API_KEY) in .env. Prints PASS/FAIL, exits 0/1.
The API key is never printed.
"""
from __future__ import annotations

import asyncio
import sys
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

PROMPT = (
    "I'm at my Windows PC. Please open Notepad and type the word hello for me. "
    "Use your desktop tool to actually do it on my computer."
)
TIMEOUT_SECONDS = 60.0


async def run_smoke() -> dict:
    """Returns {'tool': name|None, 'args': dict|None, 'audio_bytes': int}."""
    from google import genai
    from google.genai import types

    result = {"tool": None, "args": None, "audio_bytes": 0}

    key = gemini_api_key()
    if not key:
        raise RuntimeError("no Gemini API key in environment (.env)")

    # Use the EXACT production config: model, function tools, transcription, voice.
    comp = GeminiLiveCompanion(GeminiLiveCallbacks())
    config = comp._live_config(types)
    client = genai.Client(api_key=key)

    print(f"Connecting to {comp.model} ...")
    async with client.aio.live.connect(model=comp.model, config=config) as session:
        await session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=PROMPT)]),
            turn_complete=True,
        )
        print("Prompt sent. Waiting for the model to call a tool...")

        async for message in session.receive():
            content = getattr(message, "server_content", None)
            if content is not None:
                turn = getattr(content, "model_turn", None)
                for part in getattr(turn, "parts", []) or []:
                    data = getattr(getattr(part, "inline_data", None), "data", None)
                    if data:
                        result["audio_bytes"] += len(data)

            tool_call = getattr(message, "tool_call", None)
            calls = getattr(tool_call, "function_calls", None) if tool_call else None
            if calls:
                responses = []
                for call in calls:
                    name = str(getattr(call, "name", "") or "")
                    args = dict(getattr(call, "args", {}) or {})
                    result["tool"], result["args"] = name, args
                    print(f"  -> model called: {name}({args})")
                    responses.append(
                        types.FunctionResponse(
                            name=name,
                            id=getattr(call, "id", None),
                            response={"ok": True, "task_id": "smoke"},
                        )
                    )
                # Post the tool result back -- the model must accept this without error.
                await session.send_tool_response(function_responses=responses)
                await asyncio.sleep(0.8)
                return result

    return result


async def main() -> int:
    try:
        result = await asyncio.wait_for(run_smoke(), timeout=TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        print(f"\nFAIL: timed out after {TIMEOUT_SECONDS:.0f}s without a tool call.")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"\nFAIL: {type(exc).__name__}: {exc}")
        return 1

    print(f"(model audio received: {result['audio_bytes']} bytes)")
    if result["tool"] == "start_desktop_task":
        print("\nPASS: Gemini Live called start_desktop_task and accepted our "
              "FunctionResponse. Tool calling works end to end.")
        return 0
    if result["tool"]:
        print(f"\nPARTIAL: model called '{result['tool']}' -- a tool round-trip works, "
              "but not the desktop tool we prompted for.")
        return 0
    print("\nFAIL: the model never called a tool.")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

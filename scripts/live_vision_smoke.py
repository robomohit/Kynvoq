"""End-to-end smoke test for "look at my screen": does sending a screenshot into a
real Gemini Live session get a reply WITHOUT dropping the connection?

This is the exact path that was broken — the old code stuffed the image into a
send_client_content turn, which the Live API rejected with WS 1007 and dropped the
session (the user saw "Listening" forever). The fix sends the image as realtime media.

Connects with the production config, sends a real screenshot (the same capture
look_at_screen uses) over the realtime channel + a text question, and waits for the
model's transcribed reply. PASS if a reply arrives and the socket never 1007s.

    python scripts/live_vision_smoke.py

Needs GEMINI_API_KEY/GOOGLE_API_KEY. Prints PASS/FAIL, exits 0/1.
"""
from __future__ import annotations

import asyncio
import base64
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

from app.widget.gemini_live import GeminiLiveCallbacks, GeminiLiveCompanion, gemini_api_key  # noqa: E402

TIMEOUT = 45.0
QUESTION = "Look at this screenshot and tell me in one short sentence what app or page is shown."


def _capture_jpeg() -> bytes:
    """Same capture path as Live auto-screen / look_at_screen."""
    from app.widget.textbox_overlay import OverlayController, _live_vision_jpeg_settings
    data, _, _ = OverlayController._capture_vision_jpeg()
    if data:
        return data
    # Fallback for smoke script if mss unavailable
    import io
    import mss
    from PIL import Image
    quality, max_edge = _live_vision_jpeg_settings()
    with mss.mss() as sct:
        mons = sct.monitors
        mon = mons[1] if len(mons) > 1 else mons[0]
        shot = sct.grab(mon)
        img = Image.frombytes("RGB", shot.size, shot.rgb)
        if max_edge > 0 and max(img.size) > max_edge:
            img.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, subsampling=0, optimize=False)
        return buf.getvalue()


async def run() -> dict:
    from google import genai
    from google.genai import types
    out = {"reply": "", "tool": None, "error": None, "dropped": False}
    key = gemini_api_key()
    if not key:
        raise RuntimeError("no Gemini API key in environment (.env)")
    comp = GeminiLiveCompanion(GeminiLiveCallbacks())
    config = comp._live_config(types)
    client = genai.Client(api_key=key)
    jpeg = _capture_jpeg()
    print(f"Connecting to {comp.model} ... (screenshot {len(jpeg)} bytes)")
    try:
        async with client.aio.live.connect(model=comp.model, config=config) as session:
            # Replicate the REAL production flow: the user asks, the model calls the
            # look_at_screen tool, the app sends the screenshot over realtime video AND
            # returns the FunctionResponse, then the model must DESCRIBE the image.
            await session.send_client_content(
                turns=[types.Content(role="user", parts=[types.Part(text="Look at my screen and tell me what's on it.")])],
                turn_complete=True,
            )
            print("Asked 'look at my screen'. Waiting for the model to call the tool...")
            sent_image = False
            audio_bytes = 0
            async for message in session.receive():
                tc = getattr(message, "tool_call", None)
                calls = getattr(tc, "function_calls", None) if tc else None
                if calls and not sent_image:
                    out["tool"] = calls[0].name
                    print(f"  [tool_call] {out['tool']} -> sending screenshot over realtime video + FunctionResponse")
                    # The fixed send: image as realtime VIDEO (not a client_content blob).
                    await session.send_realtime_input(video=types.Blob(data=jpeg, mime_type="image/jpeg"))
                    await session.send_tool_response(function_responses=[types.FunctionResponse(
                        name=calls[0].name, id=getattr(calls[0], "id", None),
                        response={"ok": True, "message": "Screenshot sent — describe what you see in one short sentence."})])
                    sent_image = True
                    continue
                content = getattr(message, "server_content", None)
                if content is not None:
                    ot = getattr(content, "output_transcription", None)
                    if ot is not None and getattr(ot, "text", "") and sent_image:
                        out["reply"] += ot.text
                    turn = getattr(content, "model_turn", None)
                    for part in getattr(turn, "parts", []) or []:
                        d = getattr(getattr(part, "inline_data", None), "data", None)
                        if d and sent_image:
                            audio_bytes += len(d)
                    if getattr(content, "turn_complete", False) and sent_image:
                        print(f"  [turn_complete] reply='{out['reply'][:90]}' audio={audio_bytes}b")
                        if out["reply"] or audio_bytes:
                            return out
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
        if "1007" in str(exc):
            out["dropped"] = True
    return out


async def main() -> int:
    try:
        r = await asyncio.wait_for(run(), timeout=TIMEOUT)
    except asyncio.TimeoutError:
        print(f"\nFAIL: no reply within {TIMEOUT:.0f}s.")
        return 1
    if r["dropped"]:
        print(f"\nFAIL: session dropped with 1007 (image rejected). {r['error']}")
        return 1
    if r["error"]:
        print(f"\nFAIL: {r['error']}")
        return 1
    if r["reply"].strip():
        print(f"  model replied: {r['reply'].strip()[:160]}")
        print("\nPASS: Live accepted the screenshot over realtime input and replied. "
              "No 1007 drop.")
        return 0
    print("\nFAIL: no spoken reply (and no error) — vision turn produced nothing.")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

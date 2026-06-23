"""Probe Gemini Live's vision + locate against REAL running apps (Cursor, Chrome).

For each app: capture its window via the same PrintWindow path Live uses, verify
the frame is NOT black/blank (the Electron/Chromium gotcha PW_RENDERFULLCONTENT
fixes), have the Gemini vision model describe it (accuracy check), and run
grid-locate to find a real element (non-destructive — locate only, no click).

Run with the apps open and a Gemini key in .env:
    python scripts/live_app_probe.py
No keys printed. Saves nothing destructive; never clicks.
"""
from __future__ import annotations

import io
import os
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
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# (window title substring, element to locate)
APPS = [
    ("Cursor", "the editor area or left sidebar"),
    ("Chrome", "the address bar at the top"),
]


def _blackness(jpeg: bytes) -> tuple[bool, float, int]:
    """Return (is_black, mean_brightness, distinct_levels). A real window has a
    bright-ish mean and many grey levels; a failed Electron capture is ~all black."""
    from PIL import Image
    img = Image.open(io.BytesIO(jpeg)).convert("L")
    img.thumbnail((240, 240))
    px = list(img.getdata())
    mean = sum(px) / max(1, len(px))
    distinct = len(set(px))
    is_black = mean < 10 and distinct < 12
    return is_black, round(mean, 1), distinct


def _describe(jpeg: bytes, key: str) -> str:
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=key)
    resp = client.models.generate_content(
        model=(os.getenv("ORYNN_GRID_MODEL") or "gemini-flash-latest"),
        contents=[
            "In one short sentence, what application and content is shown? "
            "If the image is entirely blank or black, reply exactly: BLANK.",
            types.Part.from_bytes(data=jpeg, mime_type="image/jpeg"),
        ],
    )
    return (getattr(resp, "text", "") or "").strip().replace("\n", " ")


def main() -> int:
    from app.widget.gemini_live import gemini_api_key
    from app.widget.textbox_overlay import OverlayController
    from app import grid_locate
    key = gemini_api_key()
    if not key:
        print("SKIP: no Gemini key")
        return 0

    failures = 0
    for title, target in APPS:
        print(f"\n=== {title} ===")
        jpeg, found_title = OverlayController._capture_window_jpeg(title)
        if not jpeg:
            print(f"  [FAIL] couldn't capture a window matching '{title}'")
            failures += 1
            continue
        is_black, mean, distinct = _blackness(jpeg)
        print(f"  captured '{found_title}'  {len(jpeg)//1024} KB  mean={mean} levels={distinct}")
        if is_black:
            print("  [FAIL] capture is BLACK/blank — PrintWindow gotcha on this app")
            failures += 1
        else:
            print("  [ok]   capture has real content (not black)")
        try:
            desc = _describe(jpeg, key)
        except Exception as exc:  # noqa: BLE001
            desc = f"(describe error: {exc})"
        leaked = desc.strip().upper() == "BLANK"
        print(f"  vision: {desc[:120]}")
        if leaked:
            print("  [FAIL] model saw a blank frame")
            failures += 1

        # Non-destructive locate: bring app forward, wait until it's actually the
        # foreground window (same path the real click uses), then find it (no click).
        try:
            tools = OverlayController(8000)._live_desktop_tools()
            tools.focus_window(title)
            tools._wait_foreground(title, timeout=1.5)
        except Exception:
            pass
        hit = grid_locate.locate(f"{target} in {title}")
        print(f"  grid-locate '{target}': {hit if hit else 'None (could not place it)'}")

    print(f"\n{'PASS' if failures == 0 else 'FAIL'}: {failures} problem(s) across {len(APPS)} apps")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

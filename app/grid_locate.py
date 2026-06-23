"""Two-stage grid locate (Set-of-Mark prompting), ported from Clicky's
ai/universal_locator.py.

When UIA and OCR BOTH miss a control — the Electron/canvas case (Cursor, Figma,
games) where there's no accessible tree and no OCR-readable label — we draw a
numbered grid on a screenshot and ask a vision model which cell holds the
target, then zoom into a 3x3 region with a finer grid for a precise pixel.

This is the AGENT / back-office click fallback tier ONLY (uia_click with
allow_pixel_fallback=True). Live's fast path calls UIA-only and never reaches
here. Everything fails SAFE: any error / missing key / "not visible" returns
None, so the caller cleanly reports the original UIA miss — never a wrong click.
"""
from __future__ import annotations

import io
import os
import re
from typing import Optional

STAGE1_COLS, STAGE1_ROWS = 12, 8        # coarse: 96 cells
STAGE2_COLS, STAGE2_ROWS = 6, 6         # fine: 36 sub-cells inside a 3x3 zoom
ZOOM_RADIUS = 1                         # cells each side of the stage-1 pick -> 3x3
_MAX_INFER_W = 1280                     # downscale wide screens for the vision call


def _models() -> list[str]:
    """Vision models to try in order. grid-locate runs on generate_content, which is
    rate-limited PER MODEL and separately from the (unlimited) Live model — so we keep
    a fallback chain: a capable model first, then higher-quota lite models, so a 429 on
    one bucket falls through instead of failing the click. Override with ORYNN_GRID_MODEL
    (single) or ORYNN_GRID_MODELS (comma-separated)."""
    raw = (os.environ.get("ORYNN_GRID_MODELS") or os.environ.get("ORYNN_GRID_MODEL") or "").strip()
    if raw:
        return [m.strip() for m in raw.split(",") if m.strip()]
    return ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-flash-lite-latest"]


def _enabled() -> bool:
    return (os.environ.get("ORYNN_GRID_LOCATE") or "1").strip().lower() not in (
        "0", "off", "false", "no",
    )


def _draw_grid(img, cols: int, rows: int):
    """Overlay a red numbered grid (1..cols*rows, row-major). Returns a new RGB image."""
    from PIL import ImageDraw, ImageFont

    out = img.convert("RGB").copy()
    draw = ImageDraw.Draw(out)
    w, h = out.size
    cw, ch = w / cols, h / rows
    try:
        fsize = max(12, min(30, int(min(cw, ch) / 3.2)))
        font = ImageFont.truetype("arial.ttf", fsize)
    except Exception:
        font = ImageFont.load_default()
    for c in range(1, cols):
        draw.line([(int(c * cw), 0), (int(c * cw), h)], fill=(255, 40, 40), width=1)
    for r in range(1, rows):
        draw.line([(0, int(r * ch)), (w, int(r * ch))], fill=(255, 40, 40), width=1)
    n = 1
    for r in range(rows):
        for c in range(cols):
            x, y = int(c * cw) + 3, int(r * ch) + 2
            label = str(n)
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):  # dark halo for legibility
                draw.text((x + dx, y + dy), label, fill=(0, 0, 0), font=font)
            draw.text((x, y), label, fill=(255, 230, 0), font=font)
            n += 1
    return out


def _jpeg(img, quality: int = 82) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _parse_cell(text: str, max_n: int) -> Optional[int]:
    """Pull a 1..max_n cell number from a free-form reply; 0 / out-of-range -> None."""
    if not text:
        return None
    m = re.search(r'"?cell"?\s*[:=]\s*(\d+)', text, re.IGNORECASE) or re.search(r"\b(\d+)\b", text)
    if not m:
        return None
    n = int(m.group(1))
    return n if 1 <= n <= max_n else None


def _ask_cell(jpeg_bytes: bytes, target: str, max_n: int, key: str) -> Optional[int]:
    """Ask the vision model which numbered cell holds the target. Tries the model chain
    in order; a 429/error on one model falls through to the next. A model that responds
    but can't place it (cell 0) is a real answer -> None (no further calls)."""
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=key)
    except Exception:
        return None
    prompt = (
        f"This screenshot has a red numbered grid; cells are numbered 1 to {max_n}, "
        "left-to-right then top-to-bottom.\n"
        f'Which SINGLE numbered cell most precisely contains this UI element: "{target}"?\n'
        'Reply with ONLY this JSON, nothing else: {"cell": <number>}. '
        'If that element is not visible anywhere in the image, reply exactly {"cell": 0}.'
    )
    img = types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg")
    debug = bool(os.environ.get("ORYNN_GRID_DEBUG"))
    for model in _models():
        try:
            resp = client.models.generate_content(model=model, contents=[prompt, img])
        except Exception as exc:  # noqa: BLE001 — quota/availability: fall through
            if debug:
                print(f"[grid] {model} ERROR {type(exc).__name__}: {str(exc)[:110]}")
            continue
        text = getattr(resp, "text", "") or ""
        if debug:
            print(f"[grid] {model} max_n={max_n} reply={text[:60]!r}")
        return _parse_cell(text, max_n)  # the model saw it — trust its answer (or None)
    return None


def locate(target: str) -> Optional[tuple[int, int]]:
    """Return absolute screen (x, y) pixels for `target`, or None if it can't be
    located. Captures the primary screen itself; coordinates are in the same space
    as UIA rects / Windows OCR (what pyautogui clicks with elsewhere in the app)."""
    if not _enabled() or not (target or "").strip():
        return None
    try:
        from .widget.gemini_live import gemini_api_key
    except Exception:  # pragma: no cover - import shape
        from app.widget.gemini_live import gemini_api_key
    key = gemini_api_key()
    if not key:
        return None

    try:
        import mss
        from PIL import Image

        with mss.mss() as sct:
            mons = sct.monitors
            mon = mons[1] if len(mons) > 1 else mons[0]
            shot = sct.grab(mon)
            full = Image.frombytes("RGB", shot.size, shot.rgb)
        screen_w, screen_h = full.size
        mon_left, mon_top = int(mon["left"]), int(mon["top"])
    except Exception:
        return None
    if screen_w <= 0 or screen_h <= 0:
        return None

    if screen_w > _MAX_INFER_W:
        s = _MAX_INFER_W / screen_w
        infer = full.resize((int(screen_w * s), int(screen_h * s)), Image.Resampling.LANCZOS)
    else:
        infer = full

    # ── Stage 1: coarse 12x8 ───────────────────────────────────────────────
    p1 = _ask_cell(_jpeg(_draw_grid(infer, STAGE1_COLS, STAGE1_ROWS)),
                   target, STAGE1_COLS * STAGE1_ROWS, key)
    if not p1:
        return None
    idx = p1 - 1
    s1_row, s1_col = idx // STAGE1_COLS, idx % STAGE1_COLS

    # 3x3-cell zoom region, as fractions of the full screen.
    c0, r0 = max(0, s1_col - ZOOM_RADIUS), max(0, s1_row - ZOOM_RADIUS)
    c1, r1 = min(STAGE1_COLS - 1, s1_col + ZOOM_RADIUS), min(STAGE1_ROWS - 1, s1_row + ZOOM_RADIUS)
    fx0, fx1 = c0 / STAGE1_COLS, (c1 + 1) / STAGE1_COLS
    fy0, fy1 = r0 / STAGE1_ROWS, (r1 + 1) / STAGE1_ROWS

    # ── Stage 2: fine 6x6 inside the zoom ──────────────────────────────────
    iw, ih = infer.size
    crop = infer.crop((int(fx0 * iw), int(fy0 * ih), int(fx1 * iw), int(fy1 * ih)))
    if crop.size[0] and crop.size[0] < 768:  # upscale so sub-grid labels stay crisp
        s = 768 / crop.size[0]
        crop = crop.resize((768, max(1, int(crop.size[1] * s))), Image.Resampling.LANCZOS)
    p2 = _ask_cell(_jpeg(_draw_grid(crop, STAGE2_COLS, STAGE2_ROWS)),
                   target, STAGE2_COLS * STAGE2_ROWS, key)
    if p2:
        s2 = p2 - 1
        sub_fx = ((s2 % STAGE2_COLS) + 0.5) / STAGE2_COLS
        sub_fy = ((s2 // STAGE2_COLS) + 0.5) / STAGE2_ROWS
        fx = fx0 + sub_fx * (fx1 - fx0)
        fy = fy0 + sub_fy * (fy1 - fy0)
    else:  # stage-2 whiffed → center of the stage-1 cell
        fx = (s1_col + 0.5) / STAGE1_COLS
        fy = (s1_row + 0.5) / STAGE1_ROWS

    return (int(mon_left + fx * screen_w), int(mon_top + fy * screen_h))

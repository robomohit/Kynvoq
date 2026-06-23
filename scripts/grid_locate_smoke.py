"""Real end-to-end smoke for two-stage grid-locate: locate a known on-screen
element with the actual Gemini vision model and check the pixel lands in the
right region. Locate-only (no click) so it never disrupts the screen.

Target: the taskbar clock, which on Windows is reliably in the bottom-right.
PASS if the located pixel falls in the bottom-right region of the screen.
"""
import os
import sys

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    from app import grid_locate
    from app.widget.gemini_live import gemini_api_key

    if not gemini_api_key():
        print("SKIP: no GEMINI_API_KEY in env")
        return 0

    try:
        import mss
        with mss.mss() as sct:
            mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            w, h = int(mon["width"]), int(mon["height"])
    except Exception as exc:
        print(f"SKIP: no screen capture ({exc})")
        return 0

    target = "the clock showing the current time in the bottom-right of the taskbar"
    print(f"screen = {w}x{h}; locating: {target}")
    hit = grid_locate.locate(target)
    if not hit:
        print("FAIL: grid-locate returned None (model couldn't place the clock)")
        return 1

    x, y = hit
    in_right = x > 0.60 * w
    in_bottom = y > 0.85 * h
    print(f"located at ({x}, {y})  right={in_right} bottom={in_bottom}")
    if in_right and in_bottom:
        print("PASS: clock placed in the bottom-right region")
        return 0
    print("FAIL: located pixel is not in the expected bottom-right region")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

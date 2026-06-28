"""Offscreen capture of SetupWindow — screenshot + animated GIF of the left-pane animation.
Run as: python docs/setup-polish/capture_setup.py [before|after]

Font loading: registers Segoe UI (regular + bold) from C:/Windows/Fonts before any
widget is created so the offscreen Qt renderer produces readable text instead of boxes.
"""
import sys, os, pathlib

OUT_DIR = pathlib.Path(__file__).parent
LABEL   = sys.argv[1] if len(sys.argv) > 1 else "before"

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Must come before any Qt import.
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase, QFont

app = QApplication.instance() or QApplication([])
app.setApplicationName("Orynn-Capture")

# --- Load real fonts so offscreen renderer produces readable text, not boxes ---
FONT_DIR = pathlib.Path(r"C:\Windows\Fonts")
_font_files = [
    "segoeui.ttf",   # Segoe UI regular
    "segoeuib.ttf",  # Segoe UI bold
    "segoeuii.ttf",  # Segoe UI italic
    "arial.ttf",     # Arial fallback
    "arialbd.ttf",   # Arial bold fallback
]
_loaded_families = set()
for fname in _font_files:
    fp = FONT_DIR / fname
    if fp.exists():
        fid = QFontDatabase.addApplicationFont(str(fp))
        if fid >= 0:
            families = QFontDatabase.applicationFontFamilies(fid)
            _loaded_families.update(families)

# Set Segoe UI (or Arial) as the application default font at 13pt.
_preferred = next(
    (f for f in ("Segoe UI", "Arial") if any(f in fl for fl in _loaded_families)),
    None,
)
if _preferred:
    app.setFont(QFont(_preferred, 13))
    print(f"[capture] Default font set to: {_preferred}")
else:
    print(f"[capture] WARNING: no preferred font loaded; loaded families: {_loaded_families}")

# --- Quick text-rendering sanity check (verify we get real glyphs) ---
from PySide6.QtGui import QPixmap, QPainter
_test_pix = QPixmap(200, 30)
_test_pix.fill()
_p = QPainter(_test_pix)
_p.setFont(QFont(_preferred or "Arial", 12))
_p.drawText(4, 22, "Hello Orynn")
_p.end()
# Convert to PIL and check that non-white pixels exist (text was drawn).
import numpy as np
from PIL import Image
_qimg = _test_pix.toImage().convertToFormat(
    _test_pix.toImage().Format.Format_RGBA8888)
_arr = np.frombuffer(_qimg.bits(), dtype=np.uint8).reshape((30, 200, 4))
_dark_pixels = (_arr[:, :, :3].sum(axis=2) < 600).sum()  # non-white pixels
if _dark_pixels > 10:
    print(f"[capture] Font sanity check PASSED — {_dark_pixels} non-white pixels drawn.")
else:
    print(f"[capture] WARNING: Font sanity check FAILED — only {_dark_pixels} non-white pixels. "
          "Text may still render as boxes.")

# --- Build the window ---
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.widget.setup_window import SetupWindow
win = SetupWindow()
win.show()

# --- Capture pipeline ---
from PySide6.QtCore import QTimer, QEventLoop, QCoreApplication

loop = QEventLoop()

def take_screenshot():
    for _ in range(5):
        QCoreApplication.processEvents()
    pix = win.grab()
    path = OUT_DIR / f"{LABEL}_screenshot.png"
    pix.save(str(path), "PNG")
    print(f"Screenshot saved: {path}")

def capture_frames():
    """Capture ~4 seconds of animation at ~20fps."""
    frames = []
    N        = 80    # frames
    INTERVAL = 50    # ms per frame → 20fps

    for i in range(N):
        for _ in range(3):
            QCoreApplication.processEvents()

        orb = win.orb_pane
        pix = orb.grab()
        qimg = pix.toImage().convertToFormat(pix.toImage().Format.Format_RGBA8888)
        width, height = qimg.width(), qimg.height()
        arr = np.frombuffer(qimg.bits(), dtype=np.uint8).reshape((height, width, 4))
        frame = Image.fromarray(arr, mode="RGBA").convert("RGB")
        frames.append(frame)

        inner = QEventLoop()
        QTimer.singleShot(INTERVAL, inner.quit)
        inner.exec()

    gif_path = OUT_DIR / f"{LABEL}_animation.gif"
    frames[0].save(
        str(gif_path),
        save_all=True,
        append_images=frames[1:],
        loop=0,
        duration=INTERVAL,
        optimize=False,
    )
    print(f"Animation GIF saved: {gif_path}")

    # Also save a half-size version for quick viewing.
    small_frames = [f.resize((200, 320), Image.LANCZOS) for f in frames]
    small_path = OUT_DIR / f"{LABEL}_animation_small.gif"
    small_frames[0].save(
        str(small_path),
        save_all=True,
        append_images=small_frames[1:],
        loop=0,
        duration=60,
        optimize=True,
    )
    print(f"Animation (small) saved: {small_path}")
    loop.quit()

QTimer.singleShot(250, take_screenshot)
QTimer.singleShot(400, capture_frames)
loop.exec()

print("Capture complete.")

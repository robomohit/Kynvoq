"""Offscreen capture of SetupWindow — screenshot + animated GIF of the left-pane animation.
Run as: python docs/setup-polish/capture_setup.py [before|after] [output_dir]
"""
import sys, os, pathlib

OUT_DIR = pathlib.Path(__file__).parent
LABEL   = sys.argv[1] if len(sys.argv) > 1 else "before"

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Must come before any Qt import
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
app.setApplicationName("Orynn-Capture")

# Resolve repo root and add to path
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.widget.setup_window import SetupWindow
win = SetupWindow()
win.show()

# --- 1. Static screenshot (first rendered frame) ---
from PySide6.QtCore import QTimer, QEventLoop
from PySide6.QtGui import QPixmap

loop = QEventLoop()

def take_screenshot():
    # Let the orb tick once so it paints at least one frame
    from PySide6.QtCore import QCoreApplication
    for _ in range(3):
        QCoreApplication.processEvents()

    pix = win.grab()
    path = OUT_DIR / f"{LABEL}_screenshot.png"
    pix.save(str(path), "PNG")
    print(f"Screenshot saved: {path}")

def capture_frames():
    """Capture ~4 seconds of animation as GIF frames at ~20fps."""
    from PySide6.QtCore import QCoreApplication
    from PIL import Image
    import io

    frames = []
    N = 80           # 80 frames
    INTERVAL = 50    # ms between frames → ~20fps

    for i in range(N):
        # Advance the real timer by processing events
        for _ in range(3):
            QCoreApplication.processEvents()

        # Grab the orb pane only (left 400px)
        orb = win.orb_pane
        pix = orb.grab()
        # Convert QPixmap → PIL Image via QImage
        qimg = pix.toImage()
        qimg = qimg.convertToFormat(qimg.Format.Format_RGBA8888)
        width, height = qimg.width(), qimg.height()
        ptr = qimg.bits()
        import numpy as np
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape((height, width, 4))
        frame = Image.fromarray(arr, mode="RGBA").convert("RGB")
        frames.append(frame)

        # Sleep between frames via short event loop spin
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
    loop.quit()

# Start the capture sequence
QTimer.singleShot(200, take_screenshot)   # wait 200ms for first paint
QTimer.singleShot(300, capture_frames)    # then start GIF capture
loop.exec()

print("Capture complete.")

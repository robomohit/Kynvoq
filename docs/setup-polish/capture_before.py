"""Capture the BEFORE (pre-polish) version of SetupWindow using the historic
setup_window.py file saved from git history. Does not touch the working tree."""
import sys, os, pathlib, importlib, types

OUT_DIR = pathlib.Path(__file__).parent
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase, QFont

app = QApplication.instance() or QApplication([])
app.setApplicationName("Orynn-Capture-Before")

# Load Segoe UI so text renders as real glyphs.
FONT_DIR = pathlib.Path(r"C:\Windows\Fonts")
for fname in ["segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "arial.ttf"]:
    fp = FONT_DIR / fname
    if fp.exists():
        QFontDatabase.addApplicationFont(str(fp))
app.setFont(QFont("Segoe UI", 13))

# Sanity check
import numpy as np
from PIL import Image
from PySide6.QtGui import QPixmap, QPainter
_pix = QPixmap(200, 30); _pix.fill()
_p = QPainter(_pix); _p.setFont(QFont("Segoe UI", 12)); _p.drawText(4, 22, "test"); _p.end()
_qimg = _pix.toImage().convertToFormat(_pix.toImage().Format.Format_RGBA8888)
_arr = np.frombuffer(_qimg.bits(), dtype=np.uint8).reshape((30, 200, 4))
dark = (_arr[:,:,:3].sum(axis=2) < 500).sum()
print(f"[capture] Font check: {dark} non-white pixels ({'OK' if dark > 10 else 'FAIL'})")

# Load the historic setup_window module from the saved file.
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

BEFORE_FILE = OUT_DIR / "_setup_window_before.py"
spec = importlib.util.spec_from_file_location("setup_window_before", BEFORE_FILE)
mod  = importlib.util.module_from_spec(spec)
# Register it as app.widget.setup_window so internal imports resolve correctly.
sys.modules["app.widget.setup_window_before"] = mod
spec.loader.exec_module(mod)

SetupWindowBefore = mod.SetupWindow
win = SetupWindowBefore()
win.show()

from PySide6.QtCore import QTimer, QEventLoop, QCoreApplication

loop = QEventLoop()

def take_screenshot():
    for _ in range(5):
        QCoreApplication.processEvents()
    pix = win.grab()
    path = OUT_DIR / "before_screenshot.png"
    pix.save(str(path), "PNG")
    print(f"Screenshot saved: {path}")

def capture_frames():
    frames = []
    N = 80; INTERVAL = 50
    for i in range(N):
        for _ in range(3):
            QCoreApplication.processEvents()
        orb = win.orb_pane
        pix = orb.grab()
        qimg = pix.toImage().convertToFormat(pix.toImage().Format.Format_RGBA8888)
        arr = np.frombuffer(qimg.bits(), dtype=np.uint8).reshape(
            (qimg.height(), qimg.width(), 4))
        frames.append(Image.fromarray(arr, mode="RGBA").convert("RGB"))
        inner = QEventLoop()
        QTimer.singleShot(INTERVAL, inner.quit)
        inner.exec()

    gif_path = OUT_DIR / "before_animation.gif"
    frames[0].save(str(gif_path), save_all=True, append_images=frames[1:],
                   loop=0, duration=INTERVAL, optimize=False)
    print(f"Animation GIF saved: {gif_path}")

    small = [f.resize((200, 320), Image.LANCZOS) for f in frames]
    small_path = OUT_DIR / "before_animation_small.gif"
    small[0].save(str(small_path), save_all=True, append_images=small[1:],
                  loop=0, duration=60, optimize=True)
    print(f"Animation (small) saved: {small_path}")
    loop.quit()

QTimer.singleShot(250, take_screenshot)
QTimer.singleShot(400, capture_frames)
loop.exec()
print("Capture complete.")

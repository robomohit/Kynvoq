"""Watch Orynn's taskbar glow cycle through all its voice states — no mic needed.

Run:  python scripts/glow_demo.py
It cycles idle -> listening -> thinking -> speaking with simulated voice levels
so you can SEE the taskbar glow without talking. Ctrl+C to stop (restores bar).
"""
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.widget.taskbar_glow import TaskbarGlow


def main() -> int:
    app = QApplication(sys.argv[:1])
    glow = TaskbarGlow()
    glow.show()

    seq = [("idle", 3.0), ("listening", 5.0), ("thinking", 4.0), ("speaking", 5.0)]
    state = {"i": 0, "t": time.monotonic()}

    def feed():
        name, dur = seq[state["i"]]
        if time.monotonic() - state["t"] > dur:
            state["i"] = (state["i"] + 1) % len(seq)
            state["t"] = time.monotonic()
            glow.set_state(seq[state["i"]][0])
        # simulate a lively voice during listening/speaking
        if seq[state["i"]][0] in ("listening", "speaking"):
            lvl = 0.45 + 0.45 * (0.5 + 0.5 * math.sin(time.monotonic() * 6))
            glow.set_audio_level(lvl)

    glow.set_state("idle")
    t = QTimer()
    t.timeout.connect(feed)
    t.start(30)
    print("Taskbar glow demo running — watch your taskbar. Ctrl+C to stop.")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

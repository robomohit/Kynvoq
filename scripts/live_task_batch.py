"""Run a batch of varied REAL desktop tasks through the backend (sequentially, so
they don't fight for focus) and report each outcome. Fills the task/overlay logs so
a follow-up scan can surface logic/code errors across the full agent loop.

Safe-by-design: every goal is a benign open/type/read/compute; destructive verbs are
gated by the consent layer anyway. Run with the backend up on :8000.

    python scripts/live_task_batch.py
"""
from __future__ import annotations

import os
import sys
import time
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
from PySide6.QtWidgets import QApplication  # noqa: E402
from app.widget.textbox_overlay import OverlayController, build_task_payload  # noqa: E402

GOALS = [
    "Open Notepad and type 'QA batch line one' into it.",
    "Open the Windows Calculator and compute 7 times 8.",
    "Tell me my Windows version.",
    "List the files on my Desktop.",
    "What is today's date and time on this PC?",
    "Open Notepad, type a two-line note, then select all the text.",
    "Check how much free disk space the C drive has.",
    "Search the web for the latest Python version and tell me the number.",
]
TERMINAL = {"done", "complete", "error", "failed", "cancelled"}
PER_TASK_TIMEOUT = 75.0


def main() -> int:
    QApplication.instance() or QApplication([])
    c = OverlayController(8000)
    rows = []
    for goal in GOALS:
        payload = build_task_payload(goal)
        tid = str(payload.get("task_id") or "")
        try:
            c.client.request("POST", "/api/tasks", payload, timeout=20.0)
        except Exception as exc:  # noqa: BLE001
            print(f"  [POST-ERR] {goal[:48]}: {exc}")
            rows.append((goal, "post_error", str(exc)[:80]))
            continue
        status, reason = "running", ""
        deadline = time.monotonic() + PER_TASK_TIMEOUT
        while time.monotonic() < deadline:
            time.sleep(2.0)
            try:
                d = c.client.request("GET", f"/api/tasks/{tid}", timeout=5.0)
            except Exception:
                continue
            if isinstance(d, dict):
                status = str(d.get("status") or status)
                reason = str(d.get("reason") or d.get("error") or d.get("result") or "")
                if status in TERMINAL:
                    break
        tag = {"done": "ok", "complete": "ok"}.get(status, status.upper())
        print(f"  [{tag:9}] {goal[:50]:50} -> {reason[:60]}")
        rows.append((goal, status, reason[:120]))
        time.sleep(1.5)  # let the desktop settle between tasks
    ok = sum(1 for _, s, _ in rows if s in ("done", "complete"))
    print(f"\nBatch: {ok}/{len(rows)} completed cleanly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Golden voice path — end-to-end reliability proof (mic-less, repeatable).

A spoken command travels: mic -> STT (Groq Whisper) -> task submit -> planner ->
desktop_control -> result. `golden_reliability.py` proves the deterministic tail
(desktop_control). THIS proves the big flaky middle: a real transcript driven through
the *exact* submission path the push-to-talk handler uses (`build_task_payload` ->
`/api/tasks/preflight` -> `/api/tasks`), run against a real backend + real planner,
and verified by what actually happened on screen — not by the task's own self-report.

It is honest about what it can and can't prove:
- It DOES prove everything downstream of the transcript (submit, planner model choice,
  desktop execution) N times, with safe window-handle attribution so it never touches
  a window you already had open.
- It does NOT fake the STT half. A synthetic TTS->Whisper round-trip passes trivially
  and proves nothing about your real voice. To check STT for real, record yourself
  saying the phrase and pass it with `--wav you.wav --expect "open notepad"`.

Costs free-tier planner quota (each rep is a real gpt-oss desktop task, ~10-20s).
Keep --reps modest. Needs a real Windows desktop.

    python scripts/golden_voice_e2e.py                       # "open notepad" x3
    python scripts/golden_voice_e2e.py --phrase "open notepad" --reps 5
    python scripts/golden_voice_e2e.py --wav me.wav --expect "open notepad"  # STT only
    python scripts/golden_voice_e2e.py --port 8000 --use-running  # reuse a live backend
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

TERMINAL = {"done", "failed", "cancelled", "canceled", "error", "blocked"}
WM_CLOSE = 0x0010


def _app_handles(needle: str) -> set[int]:
    """Visible top-level windows whose title contains `needle` (case-insensitive),
    by handle — so we can attribute exactly which window THIS run opened and never
    close one that was already there."""
    needle = needle.lower()
    try:
        import win32gui
    except Exception:
        return set()
    found: set[int] = set()

    def _cb(hwnd: int, _: Any) -> None:
        try:
            if win32gui.IsWindowVisible(hwnd) and needle in win32gui.GetWindowText(hwnd).lower():
                found.add(hwnd)
        except Exception:
            pass

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:
        pass
    return found


def _infer_window_needle(phrase: str) -> str:
    """Map a spoken 'open X' command to the substring its window title will contain.
    Returns '' when we can't confidently verify on screen (then we fall back to the
    task's self-reported status, which is weaker)."""
    p = phrase.lower()
    known = ["notepad", "calculator", "calc", "paint", "explorer", "settings",
             "wordpad", "terminal", "edge", "chrome"]
    for k in known:
        if k in p:
            return "calculator" if k == "calc" else k
    return ""


def _close_handles(hwnds: set[int]) -> None:
    try:
        import win32gui
    except Exception:
        return
    for hwnd in hwnds:
        try:
            win32gui.PostMessage(hwnd, WM_CLOSE, 0, 0)
        except Exception:
            pass


def _health(port: int, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _spawn_backend(port: int, log: Any) -> "subprocess.Popen | None":
    env = dict(os.environ, ORYNN_PORT=str(port))
    proc = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "_backend_only.py")],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 40
    while time.time() < deadline:
        if _health(port):
            log(f"backend up on :{port}")
            return proc
        if proc.poll() is not None:
            log("backend process exited before becoming healthy")
            return None
        time.sleep(0.5)
    log("backend did not become healthy in 40s")
    try:
        proc.kill()
    except Exception:
        pass
    return None


def _poll_terminal(client: Any, task_id: str, timeout: float) -> tuple[str, str]:
    deadline = time.time() + timeout
    last = "pending"
    while time.time() < deadline:
        try:
            d = client.request("GET", f"/api/tasks/{task_id}", timeout=8.0)
        except Exception:
            time.sleep(1.0)
            continue
        if isinstance(d, dict):
            last = str(d.get("status") or last)
            if last in TERMINAL:
                return last, str(d.get("reason") or d.get("error") or "")
        time.sleep(1.0)
    return ("timeout", f"no terminal status within {timeout:.0f}s")


def _run_phrase_reps(phrase: str, reps: int, port: int, window_needle: str,
                     log: Any) -> dict[str, Any]:
    from app.widget.textbox_overlay import BackendClient, build_task_payload

    client = BackendClient(port)
    if not client.ensure_session():
        log("could not open a backend session")
        return {"all_perfect": False, "phrase": phrase, "runs": []}

    runs: list[dict[str, Any]] = []
    for rep in range(1, reps + 1):
        payload = build_task_payload(phrase)
        task_id = str(payload.get("task_id") or "")
        before = _app_handles(window_needle) if window_needle else set()
        t0 = time.perf_counter()
        try:
            try:
                client.request("POST", "/api/tasks/preflight", {
                    "goal": payload.get("goal", ""), "mode": payload.get("mode", "auto"),
                    "model": payload.get("model"), "isolated_app": payload.get("isolated_app"),
                }, timeout=10.0)
            except Exception:
                pass  # preflight is advisory; submit anyway like the overlay does
            client.request("POST", "/api/tasks", payload, timeout=20.0)
        except Exception as exc:
            runs.append({"ok": False, "status": "submit_error", "ms": 0.0,
                         "reason": str(exc)[:160], "opened": 0})
            log(f"  [rep {rep}] MISS — submit failed: {str(exc)[:120]}")
            continue

        status, reason = _poll_terminal(client, task_id, timeout=90.0)
        ms = (time.perf_counter() - t0) * 1000.0
        opened = (_app_handles(window_needle) - before) if window_needle else set()
        if window_needle:
            ok = status == "done" and len(opened) > 0
            if status == "done" and not opened:
                reason = reason or f"task said done but no '{window_needle}' window appeared"
        else:
            ok = status == "done"
        runs.append({"ok": ok, "status": status, "ms": ms,
                     "reason": reason, "opened": len(opened)})
        _close_handles(opened)  # only windows THIS rep created
        flag = "ok " if ok else "MISS"
        log(f"  [rep {rep}] {flag} status={status} {ms/1000:.1f}s opened={len(opened)}"
            + (f" — {reason}" if (reason and not ok) else ""))
        time.sleep(0.6)  # let the closed window settle before the next rep

    passed = sum(1 for r in runs if r["ok"])
    lat = [r["ms"] for r in runs if r["ms"] > 0]
    report = {
        "phrase": phrase, "reps": reps, "passed": passed, "total": len(runs),
        "all_perfect": bool(runs) and passed == len(runs),
        "median_ms": round(sorted(lat)[len(lat) // 2], 1) if lat else 0.0,
        "max_ms": round(max(lat), 1) if lat else 0.0,
        "runs": runs,
    }
    return report


def _stt_check(wav_path: str, expect: str, log: Any) -> dict[str, Any]:
    from app.widget import voice
    data = Path(wav_path).read_bytes()
    t0 = time.perf_counter()
    text = voice.transcribe_wav(data)
    ms = (time.perf_counter() - t0) * 1000.0
    if text is None:
        log(f"STT unavailable (no key or call failed) for {wav_path}")
        return {"ok": False, "transcript": None, "ms": ms}
    norm = " ".join(text.lower().split())
    want = " ".join(expect.lower().split()) if expect else ""
    ok = (want in norm) if want else True
    log(f"STT: heard {text!r} in {ms/1000:.1f}s"
        + (f" — {'MATCH' if ok else 'NO MATCH'} for {expect!r}" if want else ""))
    return {"ok": ok, "transcript": text, "expect": expect, "ms": ms}


def main() -> int:
    ap = argparse.ArgumentParser(description="Prove Orynn's end-to-end voice command path.")
    ap.add_argument("--phrase", default="open notepad", help="spoken command to drive")
    ap.add_argument("--reps", type=int, default=3, help="repetitions (default 3; uses free planner quota)")
    ap.add_argument("--port", type=int, default=int(os.getenv("ORYNN_PORT") or "8000"))
    ap.add_argument("--use-running", action="store_true", help="reuse an already-running backend")
    ap.add_argument("--expect-window", default="",
                    help="substring the opened window's title must contain (else inferred from phrase)")
    ap.add_argument("--wav", help="WAV of you saying the phrase — checks the real STT half")
    ap.add_argument("--expect", default="", help="expected transcript substring for --wav")
    ap.add_argument("--json", action="store_true", help="emit only the JSON report")
    args = ap.parse_args()
    quiet = args.json

    def log(msg: str) -> None:
        if not quiet:
            print(msg, flush=True)

    out: dict[str, Any] = {}

    # Optional, honest STT check on a real recording.
    if args.wav:
        out["stt"] = _stt_check(args.wav, args.expect, log)

    window_needle = (args.expect_window or _infer_window_needle(args.phrase)).lower()
    log(f"VOICE E2E — phrase={args.phrase!r}, {args.reps} reps, "
        + (f"window-verified ('{window_needle}')" if window_needle else "status-verified (weaker)"))
    log("=" * 64)

    backend: "subprocess.Popen | None" = None
    own_backend = False
    try:
        if not _health(args.port):
            if args.use_running:
                log(f"no backend on :{args.port} and --use-running set; aborting")
                return 2
            log(f"starting a fresh backend on :{args.port} ...")
            backend = _spawn_backend(args.port, log)
            own_backend = backend is not None
            if not own_backend:
                return 2
        else:
            log(f"using backend already running on :{args.port}")

        report = _run_phrase_reps(args.phrase, args.reps, args.port, expect_window, log)
        out["e2e"] = report
        log("=" * 64)
        log(f"{report['passed']}/{report['total']} passed  "
            f"(median {report['median_ms']/1000:.1f}s, max {report['max_ms']/1000:.1f}s)")
        log("PASS - every rep completed and was verified on screen."
            if report["all_perfect"] else
            "FAIL - at least one rep missed. See MISS rows above.")
    finally:
        if own_backend and backend is not None:
            try:
                backend.terminate()
                backend.wait(timeout=5)
            except Exception:
                try:
                    backend.kill()
                except Exception:
                    pass

    if quiet:
        print(json.dumps(out, indent=2, default=str))
    e2e_ok = out.get("e2e", {}).get("all_perfect", True)
    stt_ok = out.get("stt", {}).get("ok", True)
    return 0 if (e2e_ok and stt_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Golden Five reliability harness — prove the bounded desktop commands 10x in a row.

The North Star is graded on one thing: the same hands-free command working *every
time*, not most of the time. This script is the measurement instrument for that.

It drives the deterministic, no-LLM desktop gateway
(``OverlayController._live_tool("desktop_control", ...)``) — the same code path
Gemini Live / push-to-talk use for bounded commands — and runs each primitive N
times (default 10) against a single contained Notepad window, reporting per-command
pass rate and latency (p50 / p95 / max). It exits non-zero unless *every* command
is N/N, so "10x in a row" is a pass/fail gate, not a vibe.

Why this design:
- FREE: no model calls, no API quota — pure UIA primitives.
- CONTAINED: all actions target one canary Notepad window by title, so typing never
  lands in whatever app the user has focused. The window is closed without saving.
- NARROW: it measures the bounded "focus window / read screen / find / type / press
  keys" surface the North Star favors, not open-ended LLM tasks.

Run from the Orynn project root:

    python scripts/golden_reliability.py            # 10 reps each (default)
    python scripts/golden_reliability.py --reps 25  # tighter proof
    python scripts/golden_reliability.py --json      # machine-readable only
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.tools import ToolExecutor  # noqa: E402
from app.widget.textbox_overlay import OverlayController  # noqa: E402


def _pct(values: list[float], q: float) -> float:
    """Nearest-rank percentile (q in 0..1). Small-N friendly, no numpy."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, round(q * (len(ordered) - 1))))
    return ordered[idx]


def _discard_notepad_tab(tools: ToolExecutor, title_hint: str) -> None:
    try:
        tools.focus_window(title_hint)
        tools.key("ctrl+w")
        time.sleep(0.25)
        dont_save = tools.uia_find("Don't Save", title_hint)
        if getattr(dont_save, "ok", False):
            tools.uia_click("Don't Save", title_hint)
    except Exception:
        pass


def _kill_process(proc: "subprocess.Popen | None") -> None:
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=3)
    except Exception:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/F"],
                capture_output=True, text=True, timeout=5,
            )
        except Exception:
            pass


def _verify_type(resp: dict[str, Any]) -> str:
    """A type that reports ok but didn't UIA-confirm the text landed is a silent
    miss — the worst kind for trust. Treat it as a failure."""
    data = resp.get("data") or {}
    if isinstance(data, dict) and data.get("verified") is False:
        return "type reported success but UIA did not verify the text landed"
    return ""


def _typed_text(tag: str = "") -> str:
    return f"Orynn golden reliability {int(time.time() * 1000)} {tag}".strip()


# Each Golden-Five candidate is one bounded desktop_control call. ``verify`` may
# inspect the gateway's structured result and return a reason string on failure
# (e.g. type claims success but UIA didn't confirm the text landed).
def _commands(title_hint: str) -> list[dict[str, Any]]:
    nonce = {"n": 0}

    def typed_text() -> str:
        nonce["n"] += 1
        return _typed_text(f"#{nonce['n']}")

    verify_type = _verify_type

    return [
        {
            "key": "find-window",
            "desc": "wait_for_window (locate the app)",
            "args": lambda: {"action": "wait_for_window", "title": title_hint, "timeout": 8},
        },
        {
            "key": "focus-window",
            "desc": "focus_window (bring it to front)",
            "args": lambda: {"action": "focus_window", "title": title_hint},
        },
        {
            "key": "read-screen",
            "desc": "observe (read controls)",
            "args": lambda: {"action": "observe", "app": title_hint, "cap": 120},
        },
        {
            "key": "find-control",
            "desc": "find (locate the editor)",
            "args": lambda: {"action": "find", "query": "Text editor", "app": title_hint, "limit": 1},
        },
        {
            "key": "type-text",
            "desc": "type (write + UIA-verify)",
            "args": lambda: {
                "action": "type", "query": "Text editor", "app": title_hint,
                "text": typed_text(), "clear_first": True,
            },
            "verify": verify_type,
        },
        {
            "key": "press-keys",
            "desc": "press_keys (ctrl+a select-all)",
            "args": lambda: {"action": "press_keys", "keys": "ctrl+a", "app": title_hint},
        },
    ]


def _run_one(controller: OverlayController, args: dict[str, Any],
             verify: "Callable[[dict[str, Any]], str] | None") -> dict[str, Any]:
    started = time.perf_counter()
    try:
        resp = controller._live_tool("desktop_control", args)
    except Exception as exc:  # the gateway should never raise; record it if it does
        return {"ok": False, "ms": (time.perf_counter() - started) * 1000.0,
                "reason": f"exception: {exc!r}"}
    ms = (time.perf_counter() - started) * 1000.0
    ok = bool(resp.get("ok"))
    reason = ""
    if not ok:
        reason = resp.get("message") or resp.get("output") or "command returned ok=False"
    elif verify is not None:
        reason = verify(resp) or ""
        ok = not reason
    return {"ok": ok, "ms": ms, "reason": str(reason)[:200]}


def _summarize(order: list[tuple[str, str]],
               results: dict[str, list[dict[str, Any]]],
               reps: int, log: "Callable[[str], None]") -> dict[str, Any]:
    report: dict[str, Any] = {"reps": reps, "commands": [], "all_perfect": True}
    log("")
    log(f"{'command':<14} {'pass':>7}  {'p50':>6} {'p95':>6} {'max':>6}   desc")
    log("-" * 64)
    for key, desc in order:
        runs = results.get(key, [])
        oks = [r for r in runs if r["ok"]]
        lat = [r["ms"] for r in runs]
        perfect = bool(runs) and len(oks) == len(runs)
        report["all_perfect"] = report["all_perfect"] and perfect
        first_miss = next((r["reason"] for r in runs if not r["ok"]), "")
        entry = {
            "key": key, "desc": desc,
            "passed": len(oks), "total": len(runs), "perfect": perfect,
            "p50_ms": round(_pct(lat, 0.50), 1), "p95_ms": round(_pct(lat, 0.95), 1),
            "max_ms": round(max(lat), 1) if lat else 0.0,
            "first_miss": first_miss,
        }
        report["commands"].append(entry)
        flag = "OK " if perfect else "XX "
        log(f"{flag}{key:<11} {len(oks):>3}/{len(runs):<3}  "
            f"{entry['p50_ms']:>6.0f} {entry['p95_ms']:>6.0f} {entry['max_ms']:>6.0f}   {desc}")
        if not perfect and first_miss:
            log(f"     first miss: {first_miss}")
    log("=" * 64)
    log((f"PASS - every command was {reps}/{reps}.") if report["all_perfect"]
        else "FAIL - at least one command missed. See XX rows above.")
    return report


def _run_warm(controller: OverlayController, workspace: Path, reps: int,
              log: "Callable[[str], None]") -> dict[str, Any]:
    """Each primitive N times against ONE persistent Notepad — isolates per-command
    flakiness without window-launch noise."""
    canary = workspace / f"orynn-golden-warm-{int(time.time() * 1000)}.txt"
    canary.write_text("", encoding="utf-8")
    title_hint = canary.name
    commands = _commands(title_hint)
    log(f"WARM - {reps} reps/command, one persistent Notepad ({title_hint})")
    log("=" * 64)

    proc: "subprocess.Popen | None" = None
    results: dict[str, list[dict[str, Any]]] = {c["key"]: [] for c in commands}
    try:
        proc = subprocess.Popen(["notepad.exe", str(canary)])
        controller._live_tool("desktop_control",
                              {"action": "wait_for_window", "title": title_hint, "timeout": 10})
        for rep in range(1, reps + 1):
            for cmd in commands:
                r = _run_one(controller, cmd["args"](), cmd.get("verify"))
                results[cmd["key"]].append(r)
                if not r["ok"]:
                    log(f"  [rep {rep:>3}] MISS {cmd['key']:<13} - {r['reason']}")
    finally:
        _discard_notepad_tab(controller._desktop_tools, title_hint)
        _kill_process(proc)
        try:
            canary.unlink(missing_ok=True)
        except Exception:
            pass
    return _summarize([(c["key"], c["desc"]) for c in commands], results, reps, log)


def _run_cold(controller: OverlayController, workspace: Path, reps: int,
              log: "Callable[[str], None]") -> dict[str, Any]:
    """The REAL 'open <app> and type' command, end to end, N times from cold —
    fresh process + window each rep. This is where launch flakiness (slow paint,
    title mismatch, focus theft) shows up; the warm path hides it by design."""
    order = [
        ("cold-open", "launch notepad -> wait_for_window (cold)"),
        ("cold-type", "type into the freshly-opened editor + verify"),
    ]
    log(f"COLD - {reps} full open->type->close lifecycles")
    log("=" * 64)
    results: dict[str, list[dict[str, Any]]] = {k: [] for k, _ in order}
    for rep in range(1, reps + 1):
        canary = workspace / f"orynn-golden-cold-{int(time.time() * 1000)}-{rep}.txt"
        canary.write_text("", encoding="utf-8")
        title_hint = canary.name
        proc: "subprocess.Popen | None" = None
        try:
            proc = subprocess.Popen(["notepad.exe", str(canary)])
            ro = _run_one(controller,
                          {"action": "wait_for_window", "title": title_hint, "timeout": 10}, None)
            results["cold-open"].append(ro)
            if ro["ok"]:
                rt = _run_one(controller, {
                    "action": "type", "query": "Text editor", "app": title_hint,
                    "text": _typed_text(f"cold#{rep}"), "clear_first": True,
                }, _verify_type)
            else:
                rt = {"ok": False, "ms": 0.0, "reason": "skipped — window never appeared"}
            results["cold-type"].append(rt)
            for k, r in (("cold-open", ro), ("cold-type", rt)):
                if not r["ok"]:
                    log(f"  [rep {rep:>3}] MISS {k:<13} - {r['reason']}")
        finally:
            _discard_notepad_tab(controller._desktop_tools, title_hint)
            _kill_process(proc)
            try:
                canary.unlink(missing_ok=True)
            except Exception:
                pass
    return _summarize(order, results, reps, log)


def main() -> int:
    ap = argparse.ArgumentParser(description="Prove Orynn's bounded desktop commands N times in a row.")
    ap.add_argument("--reps", type=int, default=int(os.getenv("ORYNN_GOLDEN_REPS") or "10"),
                    help="repetitions per command (default 10)")
    ap.add_argument("--cold", action="store_true",
                    help="relaunch the app fresh each rep (full open→type→close lifecycle)")
    ap.add_argument("--json", action="store_true", help="emit only the JSON report")
    args = ap.parse_args()
    reps = max(1, args.reps)
    quiet = args.json

    # A reliability tool must not itself die on the cp1252 Windows console.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass

    def log(msg: str) -> None:
        if not quiet:
            print(msg, flush=True)

    QApplication.instance() or QApplication(sys.argv[:1])
    workspace = Path(tempfile.mkdtemp(prefix="orynn-golden-"))
    controller = OverlayController(8000)
    controller._desktop_tools = ToolExecutor(workspace)

    runner = _run_cold if args.cold else _run_warm
    report = runner(controller, workspace, reps, log)
    report["mode"] = "cold" if args.cold else "warm"

    if quiet:
        print(json.dumps(report, indent=2))
    return 0 if report["all_perfect"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

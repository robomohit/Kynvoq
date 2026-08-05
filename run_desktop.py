import argparse
import subprocess
import threading
import uvicorn
import time
import os
import sys

# Force UTF-8 stdio BEFORE importing the app, so model text or a unicode log line
# (em / non-breaking hyphens, smart quotes, emoji) can never crash a print on the
# Windows cp1252 console (UnicodeEncodeError).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# pythonw.exe (the boot-with-Windows launch path) has NO console: sys.stdout and
# sys.stderr are None, and any bare print() would raise AttributeError. Route them
# to a log file next to this script so the always-on agent can't crash on a log line.
if sys.stdout is None or sys.stderr is None:
    from pathlib import Path as _LogPath
    try:
        _logf = open(_LogPath(__file__).resolve().parent / "orynn.log",
                     "a", encoding="utf-8", buffering=1)
    except Exception:
        import io as _io
        _logf = _io.StringIO()
    if sys.stdout is None:
        sys.stdout = _logf
    if sys.stderr is None:
        sys.stderr = _logf

# Frozen .exe: anchor relative paths (.env, workspace/memory) to the INSTALL folder
# next to Orynn.exe — not PyInstaller's read-only temp bundle. Must run BEFORE
# importing app.main (which load_dotenv's ".env" at import time).
if getattr(sys, "frozen", False):
    from pathlib import Path as _Path
    _exe_dir = _Path(sys.executable).resolve().parent
    try:
        os.chdir(_exe_dir)
    except Exception:
        pass
    os.environ.setdefault("ORYNN_WORKSPACE", str(_exe_dir))
    # A windowed PyInstaller exe has sys.stdout/stderr == None, so any print() — and
    # uvicorn's sys.stdout.isatty() — crashes. Route them to a log file by the exe.
    if sys.stdout is None or sys.stderr is None:
        try:
            _logf = open(_exe_dir / "orynn.log", "a", encoding="utf-8", buffering=1)
        except Exception:
            import io as _io
            _logf = _io.StringIO()
        if sys.stdout is None:
            sys.stdout = _logf
        if sys.stderr is None:
            sys.stderr = _logf

from app.main import app

PORT = int(os.getenv("ORYNN_PORT") or os.getenv("AI_COMPUTER_PORT", "8000"))


def run_server(port: int):
    # Run FastAPI server on a background thread.
    # Defaults to 8000; ORYNN_PORT can override it for local testing.
    try:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="error")
    except Exception:
        # The frozen .exe is windowed (no console), so a backend crash would be
        # invisible. Persist it next to the exe so failures are diagnosable.
        import traceback
        from pathlib import Path as _P
        try:
            (_P(os.environ.get("ORYNN_WORKSPACE") or ".") / "orynn_backend_error.log").write_text(
                traceback.format_exc(), encoding="utf-8")
        except Exception:
            pass
        raise


def _server_healthy(port: int, timeout: float = 0.7) -> bool:
    """True only when Orynn is actually serving HTTP on this port."""
    import urllib.request
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/healthz",
            timeout=timeout,
        ) as resp:
            return 200 <= int(resp.status) < 300
    except Exception:
        return False


def _wait_for_server(port: int, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _server_healthy(port, timeout=0.45):
            return True
        time.sleep(0.2)
    return False


def _free_port() -> int:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _start_backend(preferred_port: int) -> int:
    if _server_healthy(preferred_port):
        print(f"[Desktop] Reusing healthy backend on port {preferred_port}.")
        return preferred_port

    print(f"[Desktop] Starting backend on port {preferred_port}...")
    threading.Thread(
        target=run_server,
        args=(preferred_port,),
        daemon=True,
    ).start()
    if _wait_for_server(preferred_port):
        return preferred_port

    fallback_port = _free_port()
    print(
        f"[Desktop] Backend on port {preferred_port} did not become healthy; "
        f"trying port {fallback_port}.",
        file=sys.stderr,
    )
    threading.Thread(
        target=run_server,
        args=(fallback_port,),
        daemon=True,
    ).start()
    if _wait_for_server(fallback_port):
        return fallback_port

    print("[Desktop] Backend failed to start; dashboard not opened.", file=sys.stderr)
    sys.exit(1)


def _start_textbox_overlay(port: int) -> subprocess.Popen | None:
    _stop_existing_textbox_overlays(port)
    if getattr(sys, "frozen", False):
        # Bundled .exe: there's no `python -m`, so relaunch OURSELVES with --overlay
        # (run_desktop's __main__ routes that flag straight to the overlay's main()).
        cmd = [sys.executable, "--overlay", "--port", str(port)]
    else:
        cmd = [sys.executable, "-m", "app.widget.textbox_overlay", "--port", str(port)]
    creationflags = 0
    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    # Overlay output used to be discarded (DEVNULL) — any glow/Live traceback
    # vanished, making field problems undiagnosable. Capture it in a log file,
    # trimmed when it grows past ~2 MB so it never bloats.
    log_handle = subprocess.DEVNULL
    try:
        log_dir = os.path.join(os.path.dirname(__file__) or ".", "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "overlay.log")
        if os.path.exists(log_path) and os.path.getsize(log_path) > 2_000_000:
            os.replace(log_path, log_path + ".1")
        log_handle = open(log_path, "a", encoding="utf-8", errors="replace")
        log_handle.write(f"\n=== overlay start {__import__('datetime').datetime.now().isoformat()} ===\n")
        log_handle.flush()
    except Exception:
        log_handle = subprocess.DEVNULL
    try:
        return subprocess.Popen(
            cmd,
            cwd=os.path.dirname(__file__) or None,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=log_handle,
            creationflags=creationflags,
        )
    except Exception as exc:
        print(f"[Desktop] Textbox overlay failed to start: {exc}", file=sys.stderr)
        return None


def _stop_existing_textbox_overlays(port: int) -> int:
    """Retire stale textbox overlays before starting a fresh one.

    Re-running the desktop launcher used to stack multiple always-on-top overlay
    processes. They all listened for the same Live/stop hotkeys and all tried to
    render status, which made the companion feel flaky. Keep one overlay per
    backend port.
    """
    try:
        import psutil
    except Exception:
        return 0
    # Dev runs as `python -m app.widget.textbox_overlay`; the frozen build as
    # `Orynn.exe --overlay` — match either so the one-overlay-per-port rule holds.
    markers = ("app.widget.textbox_overlay", "--overlay")
    wanted_port = str(int(port))
    victims = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            if proc.pid == os.getpid():
                continue
            cmdline = [str(part) for part in (proc.info.get("cmdline") or [])]
            joined = " ".join(cmdline)
            if not any(m in joined for m in markers):
                continue
            if "--port" in cmdline:
                idx = cmdline.index("--port")
                if idx + 1 < len(cmdline) and cmdline[idx + 1] != wanted_port:
                    continue
            elif wanted_port not in joined:
                continue
            proc.terminate()
            victims.append(proc)
        except Exception:
            continue
    if victims:
        gone, alive = psutil.wait_procs(victims, timeout=2.0)
        for proc in alive:
            try:
                proc.kill()
            except Exception:
                pass
        print(f"[Desktop] Restarted textbox overlay ({len(victims)} stale instance(s) stopped).")
    return len(victims)


def parse_args():
    parser = argparse.ArgumentParser(description="Launch Orynn desktop shell.")
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Launch the full dashboard. This is now the default.",
    )
    parser.add_argument(
        "--capsule",
        action="store_true",
        help="Launch the legacy compact Qt capsule instead of the dashboard.",
    )
    parser.add_argument(
        "--no-overlay",
        action="store_true",
        help="Do not start the mouse-following status textbox.",
    )
    parser.add_argument(
        "--settings",
        action="store_true",
        help="Open ONLY the control-panel window (used by the tray's Settings "
             "item); reuses the running backend, starts no overlay.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Backend port to use/reuse (defaults to ORYNN_PORT / 8000).",
    )
    return parser.parse_args()

def _open_panel_window(port: int) -> int:
    """Open the native control-panel window (pywebview) on the running backend.
    The default page is the minimal panel (voice/glow/scheduled/connectors/keys);
    the full legacy dashboard lives at /advanced for power/debug use."""
    try:
        import webview
    except ImportError:
        print(
            "[Desktop] pywebview is not installed. Run setup.bat or "
            "install requirements-desktop.txt to open the native dashboard.",
            file=sys.stderr,
        )
        return 1
    from app.desktop_bridge import DesktopBridge
    bridge = DesktopBridge()
    root_dir = os.path.dirname(__file__)
    icon_path = next(
        (
            os.path.join(root_dir, name)
            for name in ("orynn_app_icon.png", "app_icon.ico")
            if os.path.exists(os.path.join(root_dir, name))
        ),
        None,
    )
    window = webview.create_window(
        "Orynn",
        f"http://127.0.0.1:{port}",
        js_api=bridge,
        width=720,
        height=880,
        min_size=(600, 620),
        background_color="#0a0a0a",
        # Frameless: the panel draws its own slim titlebar (drag region + custom
        # min/close wired to DesktopBridge), so we drop the OS frame to avoid a
        # double titlebar. easy_drag=False so only the titlebar moves the window
        # (its CSS -webkit-app-region: drag), not the whole canvas.
        frameless=True,
        easy_drag=False,
    )

    def bind_bridge(main_window, desktop_bridge):
        desktop_bridge.bind_window(main_window)

    print("[Desktop] Orynn is launching...")
    webview.start(bind_bridge, args=(window, bridge), icon=icon_path)
    return 0


if __name__ == "__main__":
    # Frozen re-entry: a bundled .exe has no `python -m`, so it relaunches ITSELF with
    # --overlay to run the companion overlay subprocess. Route that straight to the
    # overlay's main() and exit, before any launcher logic (backend/setup/dashboard).
    if "--overlay" in sys.argv:
        from app.widget.textbox_overlay import main as _overlay_main
        _ov_port = str(PORT)
        if "--port" in sys.argv:
            _pi = sys.argv.index("--port")
            if _pi + 1 < len(sys.argv):
                _ov_port = sys.argv[_pi + 1]
        sys.exit(_overlay_main(["--port", _ov_port]))

    args = parse_args()

    # First run: if the Gemini key (Live's lifeblood) is missing, show a one-time,
    # polished setup window to collect it (+ an optional agent key) before anything
    # else starts. No-op once a key exists. (Skipped for a tray-launched Settings
    # window — that must open instantly and works without keys.)
    if not args.settings:
        try:
            from app.widget.setup_window import ensure_keys_configured
            if not ensure_keys_configured():
                print("[Desktop] Setup cancelled — no API key was provided. Exiting.")
                sys.exit(0)
        except SystemExit:
            raise
        except Exception as exc:
            print(f"[Desktop] Setup window unavailable ({exc}); continuing.", file=sys.stderr)

        # 0. Auto-start the local planner proxy (deepseek_proxy.py) if the planner
        #    is configured to use it and it isn't already running. Shared,
        #    self-healing logic lives in app.proxy_supervisor.
        try:
            from app.proxy_supervisor import ensure_proxy_running

            if not ensure_proxy_running():
                print("[Desktop] Planner proxy configured but couldn't start; "
                      "multi-step desktop tasks may use a rate-limited fallback model.")
        except Exception as _exc:
            print(f"[Desktop] Proxy supervisor unavailable: {_exc}")

    # 1. Start the backend server in a background thread, unless one is already
    #    running (e.g. the tray launched us to open the Settings window).
    port = _start_backend(args.port or PORT)

    if args.capsule:
        # Legacy floating Sidekick capsule. Kept as an explicit fallback while
        # the default product shape is dashboard + mouse textbox.
        # Rendered by the Qt/QtWebEngine shell: a frameless, translucent,
        # always-on-top window with real per-pixel transparency + Windows
        # Acrylic, so the glass capsule genuinely blurs the desktop behind
        # it. (WebView2/pywebview cannot do reliable window transparency.)
        from app.widget.qt_shell import main as qt_widget_main
        print("[Desktop] Orynn Sidekick (Qt shell) is launching...")
        sys.exit(qt_widget_main(port))

    if args.settings:
        # Tray-launched control panel: just the window, nothing else.
        sys.exit(_open_panel_window(port))

    overlay_proc = None
    if not args.no_overlay:
        overlay_proc = _start_textbox_overlay(port)

    if args.dashboard or overlay_proc is None:
        # Explicit window request (start_dashboard.bat) — or the overlay failed
        # to start, in which case the window keeps the process (and backend) alive.
        sys.exit(_open_panel_window(port))

    # Default product shape: taskbar bar + tray only — NO window. Settings opens
    # on demand from the tray icon (right-click → Settings). The launcher lives
    # as long as the overlay; Quit from the tray shuts everything down.
    print("[Desktop] Orynn is running — say the wake word, or right-click the "
          "tray icon for Settings.")
    rc = 0
    try:
        rc = overlay_proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            overlay_proc.terminate()
        except Exception:
            pass
    sys.exit(rc)

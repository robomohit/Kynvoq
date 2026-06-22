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

from app.main import app

PORT = int(os.getenv("ORYNN_PORT") or os.getenv("AI_COMPUTER_PORT", "8000"))


def run_server(port: int):
    # Run FastAPI server on a background thread
    # Defaults to 8000; ORYNN_PORT can override it for local testing.
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error")


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
    cmd = [
        sys.executable,
        "-m",
        "app.widget.textbox_overlay",
        "--port",
        str(port),
    ]
    creationflags = 0
    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    try:
        return subprocess.Popen(
            cmd,
            cwd=os.path.dirname(__file__) or None,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
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
    marker = "app.widget.textbox_overlay"
    wanted_port = str(int(port))
    victims = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            if proc.pid == os.getpid():
                continue
            cmdline = [str(part) for part in (proc.info.get("cmdline") or [])]
            joined = " ".join(cmdline)
            if marker not in joined:
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
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()

    # First run: if the Gemini key (Live's lifeblood) is missing, show a one-time,
    # polished setup window to collect it (+ an optional agent key) before anything
    # else starts. No-op once a key exists.
    try:
        from app.widget.setup_window import ensure_keys_configured
        if not ensure_keys_configured():
            print("[Desktop] Setup cancelled — no API key was provided. Exiting.")
            sys.exit(0)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"[Desktop] Setup window unavailable ({exc}); continuing.", file=sys.stderr)

    # 1. Start the backend server in a background thread, unless one is already
    #    running (e.g. the capsule launched us to open a second native window).
    port = _start_backend(PORT)

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

    if not args.no_overlay:
        _start_textbox_overlay(port)

    # Full dashboard (pywebview)
    try:
        import webview
    except ImportError:
        print(
            "[Desktop] pywebview is not installed. Run setup.bat or "
            "install requirements-desktop.txt to open the native dashboard.",
            file=sys.stderr,
        )
        sys.exit(1)
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
        width=1400,
        height=900,
        min_size=(1024, 768),
        background_color="#0a0a0a",
        # Frameless: the dashboard draws its own titlebar (drag region + custom
        # min/max/close wired to DesktopBridge), so we drop the OS frame to
        # avoid a double titlebar. easy_drag=False so only the titlebar moves
        # the window (its CSS -webkit-app-region: drag), not the whole canvas.
        frameless=True,
        easy_drag=False,
    )

    def bind_bridge(main_window, desktop_bridge):
        desktop_bridge.bind_window(main_window)

    print("[Desktop] Orynn is launching...")
    webview.start(bind_bridge, args=(window, bridge), icon=icon_path)

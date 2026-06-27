"""Keep the local planner proxy (deepseek_proxy.py) alive.

The desktop planner's primary free model is reached through a tiny local HTTP proxy
on 127.0.0.1:8080 (see deepseek_proxy.py -> opencode.ai Zen / deepseek-v4-flash-free).
If that proxy isn't running, multi-step ``start_desktop_task`` work silently degrades
to a rate-limited public fallback (often HTTP 429) and tasks fail. Since "fully
control your PC" depends on that planner, we make the proxy a self-healing dependency:

* ``ensure_proxy_running()`` — start it once if the planner points at it and it's down.
* ``proxy_is_up()`` — cheap liveness probe (TCP connect).

Both are no-ops unless ``OPENROUTER_BASE_URL`` actually points at the local proxy, so
users who configure a real cloud model are never affected.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

PROXY_HOST = "127.0.0.1"
PROXY_PORT = 8080


def _planner_uses_local_proxy() -> bool:
    url = (os.environ.get("OPENROUTER_BASE_URL") or "").strip()
    return f"{PROXY_HOST}:{PROXY_PORT}" in url or f"localhost:{PROXY_PORT}" in url


def proxy_is_up(timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((PROXY_HOST, PROXY_PORT), timeout=timeout):
            return True
    except OSError:
        return False


def _proxy_script() -> Path:
    # repo root is the parent of this app/ package
    return Path(__file__).resolve().parent.parent / "deepseek_proxy.py"


def ensure_proxy_running(*, wait: float = 1.5) -> bool:
    """If the planner is configured to use the local proxy and it isn't up, spawn it.

    Returns True if the proxy is up (already, or after we started it), False if it is
    needed but could not be started. Returns True (no-op) when the planner doesn't use
    the local proxy.
    """
    if not _planner_uses_local_proxy():
        return True
    if proxy_is_up():
        return True
    script = _proxy_script()
    if not script.exists():
        return False
    try:
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            [sys.executable, str(script)],
            cwd=str(script.parent),
            creationflags=creationflags,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return False
    # Brief poll for it to bind the port.
    import time

    deadline = time.monotonic() + max(wait, 0.0)
    while time.monotonic() < deadline:
        if proxy_is_up():
            return True
        time.sleep(0.1)
    return proxy_is_up()

"""Universal launch resolver ladder (WS1): registry → URI → shell → start."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Literal, Optional

from .tools import _KNOWN_LAUNCH_APPS, detect_app_launch_intent


LaunchKind = Literal["curated", "settings", "protocol", "shell", "start"]


@dataclass(frozen=True)
class LaunchEntry:
    display_name: str
    normalized_key: str
    kind: LaunchKind
    launch_command: str
    window_title: str
    rank: int = 0


# Voice aliases → registry key (expanded beyond exact dict keys).
_LAUNCH_ALIASES: dict[str, str] = {
    "windows settings": "settings",
    "system settings": "settings",
    "taskmgr": "task manager",
    "ms paint": "paint",
    "google chrome": "chrome",
    "microsoft edge": "edge",
    "visual studio code": "vscode",
    "vs code": "vscode",
    "file explorer": "explorer",
    "windows explorer": "explorer",
    "command prompt": "cmd",
    "windows terminal": "terminal",
    "snip & sketch": "snipping tool",
    "snip and sketch": "snipping tool",
}

_SETTINGS_PAGES: dict[str, tuple[str, str]] = {
    "home": ("start ms-settings:", "Settings"),
    "display": ("start ms-settings:display", "Settings"),
    "sound": ("start ms-settings:sound", "Settings"),
    "notifications": ("start ms-settings:notifications", "Settings"),
    "bluetooth": ("start ms-settings:bluetooth", "Settings"),
    "network": ("start ms-settings:network", "Settings"),
    "privacy": ("start ms-settings:privacy", "Settings"),
    "storage": ("start ms-settings:storagesense", "Settings"),
    "about": ("start ms-settings:about", "Settings"),
    "apps": ("start ms-settings:appsfeatures", "Settings"),
    "update": ("start ms-settings:windowsupdate", "Settings"),
}


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", str(name or "").strip().lower())


def resolve_launch_target(name: str) -> Optional[LaunchEntry]:
    """Resolve a bare app name to a launch plan. Does not launch or verify."""
    key = _normalize_name(name)
    if not key:
        return None
    key = _LAUNCH_ALIASES.get(key, key)

    # Hard reject shell metacharacters / newlines before producing any start-style command.
    # Defense-in-depth: this function can be reached from both Live and the deterministic
    # agent fast-path.
    if re.search(r"[\r\n&|<>^%]", key):
        return None

    curated = detect_app_launch_intent(f"open {key}")
    if curated:
        cmd, title = curated
        return LaunchEntry(
            display_name=key,
            normalized_key=key,
            kind="curated",
            launch_command=cmd,
            window_title=title,
            rank=100,
        )

    if key in _KNOWN_LAUNCH_APPS:
        cmd, title = _KNOWN_LAUNCH_APPS[key]
        return LaunchEntry(
            display_name=key,
            normalized_key=key,
            kind="curated",
            launch_command=cmd,
            window_title=title,
            rank=90,
        )

    if key in _SETTINGS_PAGES:
        cmd, title = _SETTINGS_PAGES[key]
        return LaunchEntry(
            display_name=key,
            normalized_key=key,
            kind="settings",
            launch_command=cmd,
            window_title=title,
            rank=80,
        )

    if key.startswith("ms-settings:") or key.startswith("ms-"):
        cmd = f"start {key}" if not key.startswith("start ") else key
        return LaunchEntry(
            display_name=key,
            normalized_key=key,
            kind="protocol",
            launch_command=cmd,
            window_title="Settings",
            rank=70,
        )

    # Stricter URI/protocol detection: require an explicit scheme and no whitespace.
    # This avoids routing broad user-controlled strings into `start <...>`.
    if re.match(r"^[a-z][a-z0-9+.-]*:[^\s]+$", key):
        cmd = f"start {key}" if not key.startswith("start ") else key
        scheme = key.split(":", 1)[0]
        return LaunchEntry(
            display_name=key,
            normalized_key=key,
            kind="protocol",
            launch_command=cmd,
            window_title=scheme.title(),
            rank=60,
        )

    # Tier: generic start <name>
    safe = re.sub(r"[^\w\s.-]", "", key).strip()
    if safe and len(safe) <= 40:
        return LaunchEntry(
            display_name=safe,
            normalized_key=key,
            kind="start",
            launch_command=f"start {safe}",
            window_title=safe.title(),
            rank=10,
        )
    return None


def verify_launch_foreground(window_title: str, timeout: float = 2.0) -> tuple[bool, str]:
    """Check foreground window title matches within timeout (post-launch verify)."""
    needle = str(window_title or "").strip()
    if not needle:
        return False, ""
    try:
        import win32gui  # type: ignore
    except ImportError:
        return True, needle
    deadline = time.time() + max(0.1, float(timeout))
    best = ""
    while time.time() < deadline:
        try:
            hwnd = win32gui.GetForegroundWindow()
            if hwnd:
                title = (win32gui.GetWindowText(hwnd) or "").strip()
                if title:
                    best = title
                    low_needle = needle.lower()
                    low_title = title.lower()
                    if low_needle in low_title or low_title in low_needle:
                        return True, title
                    # Spotify Premium, localized titles, etc.
                    if low_needle.split()[0] in low_title:
                        return True, title
        except Exception:
            pass
        time.sleep(0.1)
    return False, best


def open_settings_uri(page: str = "display") -> tuple[str, str]:
    """Return (launch_command, window_title) for a settings pane."""
    key = _normalize_name(page) or "display"
    if key in _SETTINGS_PAGES:
        return _SETTINGS_PAGES[key]
    return _SETTINGS_PAGES["display"]

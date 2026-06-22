"""WS1/WS8: launch registry and resolver ladder."""
import pytest

from app.launch import resolve_launch_target, open_settings_uri
from app.tools import detect_app_launch_intent, _KNOWN_LAUNCH_APPS


@pytest.mark.parametrize(
    "spoken",
    [
        "open spotify",
        "open notepad",
        "open calculator",
        "open discord",
        "open chrome",
        "open edge",
        "open file explorer",
        "open vscode",
        "open teams",
        "open clock",
        "launch paint",
    ],
)
def test_detect_app_launch_intent_registry(spoken):
    hit = detect_app_launch_intent(spoken)
    assert hit is not None, spoken
    cmd, title = hit
    assert cmd.startswith("start")
    assert title


def test_resolve_launch_target_spotify():
    entry = resolve_launch_target("spotify")
    assert entry is not None
    assert "spotify" in entry.launch_command.lower()
    assert "Spotify" in entry.window_title


def test_open_settings_display_uri():
    cmd, title = open_settings_uri("display")
    assert "ms-settings:display" in cmd
    assert title == "Settings"


def test_registry_has_at_least_ten_new_entries():
    assert len(_KNOWN_LAUNCH_APPS) >= 17


def test_multi_step_goal_rejected():
    assert detect_app_launch_intent("open spotify and play music") is None

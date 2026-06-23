"""WS4/WS8: bubble denylist unit tests."""
import pytest

from app.bubble_sanitizer import sanitize_bubble_text


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Hello there", "Hello there"),
        ("Failed: Server restarted or task was abandoned.", "Couldn't complete that"),
        ("Server restarted or task was abandoned.", ""),
        ('{"status": "failed", "reason": "x"}', ""),
        ("AutomationId: foo ControlType: Button", ""),
        ("Clicking Save", "Clicking Save"),
    ],
)
def test_sanitize_denylist(raw, expected):
    assert sanitize_bubble_text(raw, source="task_result") == expected


def test_golden_spotify_label_sequence_mutes_leaks(tmp_path, monkeypatch):
    """Replay Spotify-style label churn; leaked patterns must be muted (G05)."""
    import json
    from app.widget import textbox_overlay as tbo

    logf = tmp_path / "labels.jsonl"
    monkeypatch.setattr(tbo, "_LABEL_LOG_ENABLED", True)
    monkeypatch.setattr(tbo, "_LABEL_LOG_PATH", logf)

    c = tbo.OverlayController(8000)
    c._live = type("L", (), {"is_running": lambda self: True})()
    shown = []
    c.labelRequested.connect(lambda s: shown.append(s))

    c._set_label("Failed: Server restarted or task was abandoned.", source="task_result")
    c._set_label("Clicking Spotify", source="task_action")
    c._set_label("Listening", source="live_status")

    rows = [json.loads(l) for l in logf.read_text(encoding="utf-8").splitlines() if l.strip()]
    muted_reasons = {r["reason"] for r in rows if r["action"] == "muted"}
    assert "bubble_sanitizer_denylist" in muted_reasons or "task_outcome_under_live" in muted_reasons
    assert not any("Server restarted" in s for s in shown)

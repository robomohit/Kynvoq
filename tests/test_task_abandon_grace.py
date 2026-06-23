"""Backend: a freshly-started task must not be flashed as 'abandoned', and a task
that really did end before running should report a HUMAN reason, never the opaque
'Server restarted or task was abandoned.' (the Open-Spotify leak)."""
from datetime import datetime, timedelta, timezone


def _record(main, task_id, *, age_seconds):
    created = (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).isoformat()
    rec = main.TaskRecord(
        id=task_id,
        status="running",
        context=main.AgentContext(goal="open spotify"),
        goal="open spotify",
        created_at=created,
    )
    main.service._active_tasks.pop(task_id, None)   # not server-running
    return rec


def test_fresh_running_task_kept_running_within_grace(monkeypatch):
    import app.main as m
    monkeypatch.setattr(m, "_save_task_record", lambda rec: None)
    rec = _record(m, "grace-fresh", age_seconds=0.2)   # just created
    out = m._serialize_task_record(rec)
    assert out["status"] == "running"        # grace: not abandoned milliseconds in


def test_stale_running_task_failed_with_human_reason(monkeypatch):
    import app.main as m
    monkeypatch.setattr(m, "_save_task_record", lambda rec: None)
    rec = _record(m, "grace-stale", age_seconds=m._TASK_START_GRACE + 5)
    out = m._serialize_task_record(rec)
    assert out["status"] == "failed"
    reason = (out.get("reason") or "")
    assert "abandoned" not in reason.lower()
    assert "Server restarted" not in reason
    assert reason  # there IS a (human) reason

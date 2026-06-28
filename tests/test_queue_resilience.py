"""The task queue must be self-healing: a stuck/zombie/runaway task can NEVER
permanently hold a concurrency slot. Regression for the deadlock where a few
finalized-but-still-alive tasks filled all _MAX_ACTIVE_TASKS slots, so every future
task hung forever as 'queued' (e2e voice path timed out 0/10 at 90s on a
long-running backend)."""
from datetime import datetime, timezone, timedelta

import pytest


class FakeTask:
    """Stand-in for an asyncio.Task with controllable done()/cancel()."""

    def __init__(self, done=False):
        self._done = done
        self.cancelled = False

    def done(self):
        return self._done

    def cancel(self):
        self.cancelled = True
        self._done = True


class RecStub:
    def __init__(self, status, created_at=None):
        self.status = status
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
        self.reason = None
        self.finished_at = None
        self.id = "rec"


@pytest.fixture
def main_isolated():
    """Give each test a clean queue/active-task state, restored afterward."""
    from app import main
    save_active = dict(main.service._active_tasks)
    save_tasks = dict(main._tasks)
    save_queue = list(main._queued_task_specs)
    main.service._active_tasks.clear()
    main._tasks.clear()
    main._queued_task_specs.clear()
    try:
        yield main
    finally:
        main.service._active_tasks.clear()
        main.service._active_tasks.update(save_active)
        main._tasks.clear()
        main._tasks.update(save_tasks)
        main._queued_task_specs[:] = save_queue


def test_finalized_tasks_do_not_count_as_active(main_isolated):
    m = main_isolated
    # not-done coroutine + terminal record = a zombie that must NOT hold a slot.
    m.service._active_tasks["z"] = FakeTask(done=False)
    m._tasks["z"] = RecStub("failed")
    # a done task also frees its slot.
    m.service._active_tasks["d"] = FakeTask(done=True)
    m._tasks["d"] = RecStub("done")
    # a genuinely running task counts.
    m.service._active_tasks["r"] = FakeTask(done=False)
    m._tasks["r"] = RecStub("running")
    assert m._count_active_tasks() == 1


def test_queue_self_heals_from_stuck_slots(main_isolated, monkeypatch):
    m = main_isolated
    # Fill ALL slots with zombies (not-done coroutine, terminal record) — the exact
    # deadlock: raw len() would say "full" forever.
    zombies = {}
    for i in range(m._MAX_ACTIVE_TASKS):
        tid = f"zombie-{i}"
        m.service._active_tasks[tid] = FakeTask(done=False)
        m._tasks[tid] = RecStub("failed")
        zombies[tid] = m.service._active_tasks[tid]

    started = []
    monkeypatch.setattr(m, "_start_task_from_spec",
                        lambda spec: started.append(spec["task_id"]) or RecStub("running"))
    m._queued_task_specs.append({
        "task_id": "q1", "goal": "open notepad",
        "screen_width": 1280, "screen_height": 800, "model": None, "mode": "computer",
    })
    m._tasks["q1"] = RecStub("queued")

    m._start_next_queued_task()

    # The zombies were reaped and the queued task finally got to run.
    assert all(z.cancelled for z in zombies.values())
    assert all(tid not in m.service._active_tasks for tid in zombies)
    assert started == ["q1"]


def test_reap_force_fails_runaway_task(main_isolated, monkeypatch):
    m = main_isolated
    monkeypatch.setattr(m, "_save_task_record", lambda rec: None)
    t = FakeTask(done=False)
    old = (datetime.now(timezone.utc) - timedelta(seconds=m._TASK_MAX_RUNTIME + 60)).isoformat()
    rec = RecStub("running", created_at=old)
    m.service._active_tasks["runaway"] = t
    m._tasks["runaway"] = rec

    m._reap_stuck_tasks()

    assert t.cancelled
    assert rec.status == "failed"
    assert "runaway" not in m.service._active_tasks


def test_reap_leaves_healthy_running_task_alone(main_isolated, monkeypatch):
    m = main_isolated
    monkeypatch.setattr(m, "_save_task_record", lambda rec: None)
    t = FakeTask(done=False)
    rec = RecStub("running")  # fresh, non-terminal
    m.service._active_tasks["ok"] = t
    m._tasks["ok"] = rec

    m._reap_stuck_tasks()

    assert not t.cancelled
    assert "ok" in m.service._active_tasks
    assert rec.status == "running"


def test_reap_runaway_cleans_up_log_emitter_state(main_isolated, monkeypatch):
    """Regression: _reap_stuck_tasks must call cleanup_task so that per-task
    seq counters and offset indexes don't accumulate in memory after a force-fail."""
    m = main_isolated
    monkeypatch.setattr(m, "_save_task_record", lambda rec: None)
    t = FakeTask(done=False)
    old = (datetime.now(timezone.utc) - timedelta(seconds=m._TASK_MAX_RUNTIME + 60)).isoformat()
    rec = RecStub("running", created_at=old)
    m.service._active_tasks["runaway2"] = t
    m._tasks["runaway2"] = rec
    # Plant a seq counter to simulate events having been emitted for this task.
    m.log_emitter._seqs["runaway2"] = 42
    m.log_emitter._offsets["runaway2"] = [0, 100, 200]

    m._reap_stuck_tasks()

    assert "runaway2" not in m.log_emitter._seqs, "seq counter leaked after reap"
    assert "runaway2" not in m.log_emitter._offsets, "offset index leaked after reap"


def test_cancel_queued_task_cleans_up_log_emitter_state(main_isolated, tmp_path, monkeypatch):
    """Regression: DELETE /api/tasks/{id} on a queued task must call cleanup_task
    so that seq counters and offset indexes are released from memory."""
    from fastapi.testclient import TestClient
    from app.models import AgentContext, TaskRecord
    import app.main as m

    monkeypatch.setattr(m, "API_KEY", "token123")
    client = TestClient(m.app)
    auth = {"Authorization": "Bearer token123"}
    monkeypatch.setattr(m, "_save_task_record", lambda rec: None)

    tid = "queued-cleanup-tst"
    m._tasks[tid] = TaskRecord(
        id=tid, status="queued",
        context=AgentContext(goal="do a thing"),
        goal="do a thing",
    )
    m._queued_task_specs.append({"task_id": tid})
    # Plant in-memory emitter state to simulate events having been emitted.
    m.log_emitter._seqs[tid] = 3
    m.log_emitter._offsets[tid] = [0, 50, 100]

    r = client.delete(f"/api/tasks/{tid}", headers=auth)
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"
    # cleanup_task() must have been called: the pre-existing seq counter (3) is gone.
    # A single residual entry from the cancellation event itself is acceptable, but
    # the original accumulated state (seq=3, offsets=[0,50,100]) must be cleared.
    assert m.log_emitter._seqs.get(tid, 0) <= 1, "old seq counter not cleaned up after queued cancel"
    assert len(m.log_emitter._offsets.get(tid, [])) <= 1, "old offset index not cleaned up after queued cancel"

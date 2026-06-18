import os
import pytest
from unittest.mock import MagicMock, patch

# Ensure QApp exists before constructing QObjects
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtWidgets import QApplication
    from app.widget.textbox_overlay import OverlayController
except ImportError:
    pytest.skip("PySide6 not importable in this environment", allow_module_level=True)

# Initialize the QApplication singleton
QApplication.instance() or QApplication([])


def test_poll_loop_connection_failure_limit(monkeypatch):
    """Verify that after 3+ consecutive failures, active tasks and cursor states are reset."""
    controller = OverlayController(port=8000)
    
    # Track cursor state emissions
    emitted_states = []
    controller.cursorStateRequested.connect(emitted_states.append)
    
    # Mock client request to fail
    def mock_request(*args, **kwargs):
        raise ConnectionError("Backend down")
    monkeypatch.setattr(controller.client, "request", mock_request)
    
    # Mock stop event so loop runs exactly 4 times and stops
    run_count = 0
    def mock_is_set():
        nonlocal run_count
        if run_count >= 4:
            return True
        run_count += 1
        return False
    monkeypatch.setattr(controller._stop, "is_set", mock_is_set)
    
    # Mock wait to return immediately
    monkeypatch.setattr(controller._stop, "wait", lambda timeout: True)
    
    # Set initial task state as running
    controller._active_task_running = True
    controller._active_task_goal = "Test Task"
    
    # Run loop
    controller._poll_loop()
    
    # Check that failures were tracked and states reset
    assert controller._consecutive_failures >= 3
    assert not controller._active_task_running
    assert controller._active_task_goal == ""
    assert "idle" in emitted_states


def test_poll_loop_recovery_syncs_active_tasks(monkeypatch):
    """Verify that state is synced with active tasks upon recovering from 3+ failures."""
    controller = OverlayController(port=8000)
    
    # Mock client request: fail 3 times, then succeed on 4th
    call_count = 0
    def mock_request(method, path, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 3:
            raise ConnectionError("Backend down")
        if "/api/overlay/events" in path:
            return {"events": [], "cursor": 10}
        if "/api/active-tasks" in path:
            return {"tasks": [{"goal": "Recovered Task", "status": "running"}]}
        return {}
    
    monkeypatch.setattr(controller.client, "request", mock_request)
    
    # Mock stop event to run 4 times (3 failures, 1 success/recovery)
    run_count = 0
    def mock_is_set():
        nonlocal run_count
        if run_count >= 3:
            return True
        run_count += 1
        return False
    monkeypatch.setattr(controller._stop, "is_set", mock_is_set)
    monkeypatch.setattr(controller._stop, "wait", lambda timeout: True)
    
    # Spy on _sync_state_with_active_tasks
    sync_called = False
    original_sync = controller._sync_state_with_active_tasks
    def mock_sync():
        nonlocal sync_called
        sync_called = True
        original_sync()
    monkeypatch.setattr(controller, "_sync_state_with_active_tasks", mock_sync)
    
    # Run loop
    controller._poll_loop()
    
    # Verify sync occurred and states updated
    assert sync_called
    assert controller._consecutive_failures == 0
    assert controller._active_task_running is True
    assert "Recovered Task" in controller._active_task_goal


def test_poll_loop_cursor_reset(monkeypatch):
    """Verify that if the server's cursor is less than client's cursor, client's cursor resets."""
    controller = OverlayController(port=8000)
    
    # Set client's cursor to a high value
    controller._cursor = 100
    
    # Mock client request to return a lower cursor (e.g. 5) due to server restart
    def mock_request(method, path, *args, **kwargs):
        if "/api/overlay/events" in path:
            return {"events": [], "cursor": 5}
        return {}
    monkeypatch.setattr(controller.client, "request", mock_request)
    
    # Run exactly 1 iteration
    run_count = 0
    def mock_is_set():
        nonlocal run_count
        if run_count >= 1:
            return True
        run_count += 1
        return False
    monkeypatch.setattr(controller._stop, "is_set", mock_is_set)
    monkeypatch.setattr(controller._stop, "wait", lambda timeout: True)
    
    controller._poll_loop()
    
    # Verify cursor was reset to 5
    assert controller._cursor == 5

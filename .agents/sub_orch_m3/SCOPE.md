# Scope: Milestone 3 - Resilient Overlay State Tracking (R3)

## Architecture
- Target: `app/widget/textbox_overlay.py`
- Problem: If backend server (`app/main.py`) restarts/crashes, overlay gets stuck in "thinking" cursor state forever.
- Solution: Track connection failure count in `_poll_loop`'s exception handler. If it fails 3+ consecutive times, reset state: `self._active_task_running = False`, `self._active_task_goal = ""`, emit `"idle"` cursor. Ensure overlay task tracking state syncs correctly with `/api/active-tasks` at startup and after server recovery.

## Verification
- Unit/integration tests simulating poll thread failures and verifying reset of task/cursor state.

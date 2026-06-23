# Execution Plan - Milestone 3 Resilient Overlay

## Objective
Implement resilient overlay task and cursor state tracking in `app/widget/textbox_overlay.py` when backend server crashes or restarts.

## Detailed Steps

1. **Setup Heartbeat Cron**: Schedule a recurring status check timer.
2. **Analysis (Explorer)**:
   - Analyze `app/widget/textbox_overlay.py` and understand how the polling mechanism (`_poll_loop`), active tasks syncing, and cursor states are implemented.
   - Define exact requirements for handling server crashes (e.g. 3 consecutive polling failures) and syncing on startup and recovery.
   - Output an exploration report.
3. **Implementation (Worker)**:
   - Implement connection failure count tracking in `_poll_loop`.
   - On 3+ consecutive failures:
     - Reset state: `self._active_task_running = False`, `self._active_task_goal = ""`.
     - Emit `"idle"` cursor.
   - Implement startup sync and post-recovery sync with `/api/active-tasks`.
   - Run standard builds and tests.
4. **Verification & Review (Reviewers)**:
   - Review code quality, potential side effects, and boundary conditions.
5. **Empirical Verification (Challenger)**:
   - Run/write unit and integration tests simulating polling thread failures and server recovery.
6. **Integrity Audit (Auditor)**:
   - Run forensic audit to verify genuine implementation.

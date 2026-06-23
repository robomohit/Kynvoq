# Handoff Report: Milestone 3 - Resilient Overlay State Tracking (R3)

## 1. Observation

During the investigation of `app/widget/textbox_overlay.py` and the interaction between the overlay widget and the backend server, the following key details were observed:

1. **Overlay Events Endpoints and cursor tracking**:
   - Location: `app/widget/textbox_overlay.py` line 1547-1596:
     ```python
     def _poll_loop(self) -> None:
         idle_label_shown = False
         while not self._stop.is_set():
             try:
                 data = self.client.request(
                     "GET",
                     f"/api/overlay/events?since={self._cursor}&limit=80",
                     timeout=4.0,
                 )
                 events = data.get("events", []) if isinstance(data, dict) else []
                 if isinstance(data, dict):
                     self._cursor = max(self._cursor, int(data.get("cursor") or 0))
     ```
   - When the backend server restarts/crashes, `self.client.request` throws an exception, executing the `except Exception:` block:
     ```python
     except Exception:
         if not idle_label_shown:
             self._set_label("Waiting for Orynn", source="system_wait")
             idle_label_shown = True
     ```
     This block does not track the failure count, nor does it reset the active task or cursor states.

2. **Active Task and Cursor State Tracking**:
   - Location: `app/widget/textbox_overlay.py` line 1622-1641:
     ```python
     def _update_cursor_state_from_event(self, ev: dict[str, Any]) -> None:
         t = str(ev.get("type") or "")
         if t == "task_created":
             self._active_task_running = True
         elif t in ("done", "complete", "error", "failed", "cancelled"):
             self._active_task_running = False
             self._active_task_goal = ""
         else:
             return
         if self._live_is_running():
             return
         if t == "task_created":
             self.cursorStateRequested.emit("thinking")
         else:
             self.cursorStateRequested.emit("idle")
     ```
     If the backend server restarts/crashes while a task is running, the terminal events (`done`, `complete`, etc.) are never received by the overlay. Thus, `self._active_task_running` remains `True` and the cursor state stays as `"thinking"` indefinitely.

3. **Active Task Querying**:
   - Location: `app/main.py` line 2043-2055:
     ```python
     @app.get("/api/active-tasks", dependencies=[Depends(verify_token)])
     async def get_active_tasks():
         """Return tasks currently running or pending (not in a terminal state)."""
         active = []
         for tid, rec in _tasks.items():
             payload = _serialize_task_record(rec)
             if _is_terminal_status(payload.get("status")):
                 continue
             payload["task_id"] = tid
             payload["goal"] = rec.goal or rec.context.goal
             payload["isolated_app"] = rec.context.isolated_app
             active.append(payload)
         return {"tasks": active}
     ```
     At startup or recovery, the backend client can request `/api/active-tasks` to inspect if there are any active/running tasks and sync the overlay controller's status.

4. **Cursor Sequence Restart Behavior**:
   - In `app/log_emitter.py` line 28-29:
     ```python
     self._global_seq = 0
     self._global_events: deque[dict] = deque(maxlen=MAX_GLOBAL_EVENTS)
     ```
     Upon backend restart, the global event sequence reset back to 0. Since the client's `self._cursor` is at a higher value (e.g. 150), calling `/api/overlay/events?since=150` returns no events. If the client performs `self._cursor = max(self._cursor, server_cursor)`, `self._cursor` remains at 150 forever, meaning the client is permanently desynced from the restarted server.

---

## 2. Logic Chain

1. **Tracking Connection Failures**:
   - By adding a `self._consecutive_failures` counter, we can increment it in the `except Exception:` block of `_poll_loop`.
   - Once `self._consecutive_failures >= 3`, we can deterministically conclude that the server is down or unreachable. At this threshold, the active task status and cursor state are reset (setting `self._active_task_running = False`, `self._active_task_goal = ""`, and emitting `"idle"` cursor state).

2. **Ensuring Startup & Recovery Syncing**:
   - Creating a helper method `_sync_state_with_active_tasks()` calls `/api/active-tasks` and updates the internal task flags and the cursor state based on whether active tasks exist.
   - Calling this method once at startup (before the loop) handles initial alignment.
   - When a request succeeds after `self._consecutive_failures >= 3`, we know the connection has recovered. We call the sync helper to align states, and reset `self._consecutive_failures = 0`.

3. **Handling Cursor Resets**:
   - If the server restarts, its returned `cursor` value will be less than the client's `self._cursor`.
   - By resetting `self._cursor = server_cursor` when `server_cursor < self._cursor`, the client correctly begins requesting events from the start of the new server session.

---

## 3. Caveats

- **Gemini Live Ownership**: When Gemini Live is active, it manages cursor states. The cursor state changes to `"thinking"` or `"idle"` during state resets or syncing are explicitly bypassed if `self._live_is_running()` returns `True`, preventing flashing in the voice interaction bubble.
- **Mock/Test Coverage**: PySide6 signals require a QApplication instance to run, but standard unit tests can mock PySide6 signals/events or run with a dummy application.

---

## 4. Conclusion

To implement Resilient Overlay State Tracking:
1. Introduce `self._consecutive_failures` in `OverlayController.__init__`.
2. Add a `_sync_state_with_active_tasks()` method to fetch `/api/active-tasks`, update running flags and goal names, and emit `"thinking"` or `"idle"` cursor state based on task presence.
3. Update `_poll_loop` to perform startup sync, increment consecutive failures on exception, trigger reset when failures >= 3, handle recovery syncing when a request succeeds, and handle server cursor sequence reset (fallback).

A patch file `proposed_textbox_overlay.patch` has been written to the working directory.
Additionally, unit tests verifying these states have been drafted in `proposed_test_overlay_resilience.py`.

---

## 5. Verification Method

To verify these changes:
1. Apply the patch file `proposed_textbox_overlay.patch` to the codebase:
   ```powershell
   git apply .agents/explorer_m3_1/proposed_textbox_overlay.patch
   ```
2. Copy `proposed_test_overlay_resilience.py` to `tests/test_overlay_resilience.py` and run it:
   ```powershell
   pytest tests/test_overlay_resilience.py
   ```
3. Run the entire pytest suite to ensure no regressions:
   ```powershell
   pytest
   ```
4. If a manual verification is preferred:
   - Run the backend server and start the textbox overlay.
   - Run a task from the UI or command line, so the cursor goes to `"thinking"` state.
   - Kill/stop the backend server.
   - Observe that after ~1.5s (3 polls of 0.45s + timeout), the overlay cursor resets to `"idle"`.
   - Restart the backend server.
   - Verify the overlay recovers connection, pulls new events starting from sequence 0, and syncs task states correctly.

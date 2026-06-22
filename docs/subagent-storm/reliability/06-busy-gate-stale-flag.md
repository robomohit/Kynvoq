**Naming note:** There is no `_desktop_busy` attribute in the repo. The busy gate is implemented as `_active_task_running` + `_active_task_goal` on `OverlayController` in `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\widget\textbox_overlay.py`. This doc uses `_desktop_busy` as a conceptual alias for that pair.

---

# 06 — Busy gate stale flag (`textbox_overlay`)

**Scope:** `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\widget\textbox_overlay.py`  
**Reliability track:** R3 (overlay state tracking) + busy-gate hardening (#5, #9)  
**Status:** Implemented; tests in `test_gemini_live.py`, `test_overlay_resilience.py`

---

## Summary

Gemini Live must not start a second desktop action while one is already driving the screen. The overlay enforces this with a **local busy cache** (`_active_task_running`, `_active_task_goal`) checked before every colliding tool call. That cache can become **stale** when terminal events are missed (backend restart, poll gaps). The fix is a **two-tier gate**: cheap local check first, then **HTTP confirmation** via `GET /api/active-tasks` before blocking or clearing.

Design tension:

| Failure mode | Risk | Policy |
|---|---|---|
| Stale **busy=true** (task finished, flag not cleared) | User locked out of new commands | Self-heal: HTTP empty list clears flag |
| Stale **busy=false** (task still running, flag cleared) | Two agents fight for focus/keyboard | Fail-safe: poll errors preserve flag; gate assumes busy on HTTP error |

---

## State model

### Fields (lines ~651–654)

```python
self._active_task_running = False  # conceptual "_desktop_busy"
self._active_task_goal: str = ""   # human-readable name for refusal messages
self._consecutive_failures = 0     # poll thread health counter
```

### Set `busy=true`

| Trigger | Location |
|---|---|
| Live submits `POST /api/tasks` | `_live_start_desktop_task` (~2488–2489) |
| Poll receives `task_created` event | `_update_cursor_state_from_event` (~3002–3003) |
| Startup / recovery sync finds active tasks | `_sync_state_with_active_tasks` (~2869–2873) |

### Clear `busy=false`

| Trigger | Location |
|---|---|
| Terminal poll event (`done`, `complete`, `error`, `failed`, `cancelled`) | `_update_cursor_state_from_event` (~3004–3006) |
| Live inline wait finishes | `_finish_live_task` (~2700–2702) |
| Long-running Live task finishes via poll | `_capture_live_task_outcome` → `_finish_live_task` |
| HTTP gate sees empty `/api/active-tasks` | `_active_desktop_task` (~2151–2154) |
| Recovery sync sees no tasks | `_sync_state_with_active_tasks` (~2876–2878) |
| User stop (tool or hotkey) | `_live_tool("stop_current_task")` (~2210–2212), `_stop_all_worker` (~1149–1150) |

---

## Busy gate call graph

```
Live tool call (desktop_control | start_desktop_task | run_workflow)
 │
 ├─► _desktop_control_route (fast UIA path only)
 │     └─► _busy_response()
 │
 └─► _live_tool
       └─► _busy_response()
       └─► _active_desktop_task()
             ├─ if not _active_task_running → None (not busy)
             ├─ GET /api/active-tasks
             │    ├─ tasks=[] → clear flag, return None (self-heal)
             │    └─ tasks present → return goal (busy)
             └─ HTTP exception → assume busy (fail-safe)
```

### `_busy_response()` (~2159–2178)

Returns a structured refusal when busy:

```python
{
 "ok": False,
 "busy": True,
 "active_task": "<goal>",
 "message": "... offer stop_current_task or wait ..."
}
```

Also updates UI: cursor `thinking`, label `Busy: <goal>`.

### Intentionally **not** gated

- `stop_current_task` — escape hatch (#9)
- `get_companion_status` — introspection
- Non-desktop tools (`web_search`, `remember`, etc.)

---

## Stale-flag scenarios

### 1. Task finished; terminal event never received (classic stale busy)

**Cause:** Backend restart/crash while task runs; poll never sees `done`/`error`/etc.

**Symptoms:**
- `_active_task_running` stays `True`
- Cursor may stay `thinking` (non-Live paths)
- Live gets `busy: True` on every new desktop action

**Self-heal:** On the next gated action, `_active_desktop_task()` calls `/api/active-tasks`. If the list is empty, it clears the flag and allows the action.

**Test:** `test_live_busy_gate_self_heals_when_task_already_finished` (`test_gemini_live.py` ~2328)

---

### 2. Poll failures during an active task (must NOT clear busy)

**Cause:** Network blip; `_poll_loop` exception handler runs.

**Old bug (R3):** Consecutive failures reset `_active_task_running`, letting Live stack a second task on a still-running agent.

**Current behavior (~2955–2964):**
- `_consecutive_failures` increments; flag **preserved**
- After ≥3 failures: cursor → `idle` **cosmetic only** (when Live not running)
- On recovery (`_consecutive_failures >= 3` then successful poll): `_sync_state_with_active_tasks()` re-syncs from server

**Test:** `test_poll_loop_connection_failure_limit` (`test_overlay_resilience.py` ~17)

---

### 3. HTTP error at gate time (fail-safe to busy)

**Cause:** `/api/active-tasks` unreachable when Live tries a new action.

**Behavior (~2155–2156):** Exception swallowed; gate returns busy using cached `_active_task_goal`. Prevents colliding actions when server state is unknown.

**Trade-off:** Brief outage can block new commands even if the task already finished — user must use `stop_current_task` or wait for connectivity.

---

### 4. Stop must always unblock (#9)

**Cause:** User says "stop"; kill HTTP may fail.

**Behavior (~2206–2212):** `stop_current_task` clears local flag **first**, unconditionally, then attempts `_kill_active_tasks()`. Even on backend failure, returns `ok: True` with a note that tracking stopped.

**Tests:** `test_live_tool_stop_acknowledges_even_without_backend_tasks`, `test_live_refuses_colliding_desktop_action_while_task_running` (stop escape hatch section)

---

### 5. Fast-path bypass (fixed)

**Cause:** `_desktop_control_route` ran UIA click/type before `_live_tool`'s gate.

**Fix (~1777–1782):** `_busy_response()` called at the **top** of `_desktop_control_route`.

**Test:** `test_fast_click_blocked_when_a_task_is_running` (~2119)

---

### 6. Cursor vs flag divergence during outage

After 3+ poll failures, **cursor** may show `idle` while **flag** remains `True`. This is intentional: cursor is cosmetic during outage; the gate uses HTTP + flag, not cursor state.

---

## Sync and recovery machinery

### `_sync_state_with_active_tasks()` (~2865–2883)

- Called at poll-loop startup
- Called after recovering from ≥3 consecutive failures
- Sets flag + goal from first active task, or clears both if empty
- Emits cursor state only when Live is **not** running (Live owns cursor during conversation)

### `_poll_loop` event path (~2944–2948)

Each successful poll iteration:
1. Process overlay events
2. `_update_cursor_state_from_event` — maintains flag from stream
3. `_capture_live_task_outcome` — clears flag for long Live tasks
4. On exception — preserve flag (#5)

---

## Related files

| File | Role |
|---|---|
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\widget\textbox_overlay.py` | Busy gate implementation |
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\tests\test_gemini_live.py` | Gate, self-heal, stop, fast-path tests |
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\tests\test_overlay_resilience.py` | Poll failure / recovery tests |
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\ORIGINAL_REQUEST.md` | R3 problem statement |
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\.agents\explorer_m3_1\handoff.md` | Design rationale |

---

## Remaining edge cases

1. **False busy during extended `/api/active-tasks` outage** — gate fails safe; only `stop_current_task` or connectivity restore helps.
2. **`task_created` without matching goal in sync** — `_update_cursor_state_from_event` sets running but not goal; gate falls back to `"a desktop task"`.
3. **Non-Live task sources** (voice, dashboard) — same flag; terminal events and sync are the primary clear paths.
4. **`run_workflow`** — also gated via `_busy_response()` (~2063–2064); multi-step workflows cannot start during an active desktop task.

---

## Test matrix

| Test | Asserts |
|---|---|
| `test_live_refuses_colliding_desktop_action_while_task_running` | Gate blocks `start_desktop_task` and `desktop_control`; stop works |
| `test_live_busy_gate_self_heals_when_task_already_finished` | Stale flag cleared via HTTP; new task POSTed |
| `test_fast_click_blocked_when_a_task_is_running` | Fast UIA path hits gate |
| `test_poll_loop_connection_failure_limit` | Flag preserved through poll failures |
| `test_poll_loop_recovery_syncs_active_tasks` | Recovery triggers sync |
| `test_live_tool_stop_acknowledges_even_without_backend_tasks` | Stop clears flag without backend tasks |

---

## Recommendations (future)

1. **Rename for clarity:** Consider aliasing or documenting `_active_task_running` as the canonical “desktop busy” flag to avoid `_desktop_busy` confusion in docs.
2. **Telemetry:** Log when self-heal clears a stale flag (local=true, HTTP=empty) for field debugging.
3. **TTL fallback:** Optional monotonic timeout if HTTP stays unreachable and user has not stopped — lower priority than fail-safe busy.

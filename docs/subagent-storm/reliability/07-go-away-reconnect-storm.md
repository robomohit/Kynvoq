# 07 — `go_away` reconnect storm (`debug-eec63b.log`)

**Scope:** `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\widget\gemini_live.py`, log `C:\Users\ACER\Desktop\Ai_computer\Ai_computer\debug-eec63b.log`  
**Reliability track:** R1 (Live session continuity) + reconnect hardening  
**Hypothesis ID:** D (connection lifecycle)  
**Status:** Pre-fix instrumentation (`runId: "pre-fix"`); graceful handler implemented, storm behavior observed in field log

---

## Summary

Gemini Live sends periodic `go_away` messages (`time_left: "30s"`) before server-side session rotation. Orynn handles these by setting `_go_away_reconnect`, ending the audio stream, exiting the receive loop, and reconnecting with a `session_resumption` handle.

In session `eec63b`, this produced a **reconnect storm**: **69** `go_away` schedule events over **~96 hours**, with **dense clusters** (multiple events within 15–60 seconds) during heavy desktop-subagent testing. Most reconnects appear to succeed silently, but telemetry shows a critical gap: **zero** logged graceful receive-loop exits despite 69 schedule events. Two **1007 invalid-argument** failures occurred while resuming with a stale handle mid-tool.

The storm is **not** primarily a bug in go_away detection — it is the compounding of (1) expected server session rotation, (2) rapid reconnect cycling under load, (3) missing debounce/coalescing, and (4) resume-handle reuse after long or interrupted sessions.

---

## Log source

| Field | Value |
|---|---|
| File | `C:\Users\ACER\Desktop\Ai_computer\Ai_computer\debug-eec63b.log` |
| Session | `eec63b` (`_DEBUG_SESSION` in `gemini_live.py`) |
| Lines | 1,609 JSONL records |
| Span | `1781808632887` → `1782155368333` (~346.7M ms ≈ **96.3 h**) |
| Run ID | `pre-fix` |

---

## Event counts (hypothesis D)

| Event | Count | Location |
|---|---:|---|
| `go_away received, scheduling graceful reconnect` | **69** | `gemini_live.py:_handle_message:go_away` |
| `exiting receive loop for graceful go_away reconnect` | **0** | `gemini_live.py:_receive_loop:go_away` |
| `live connection dropped, retrying` | **2** | `gemini_live.py:_run:reconnect` |
| All hypothesis-D entries | **72** | (69 + 2 + possibly 1 other) |

**All 69 `go_away` events report `time_left: "30s"`.** No variation in the logged payload.

---

## Intended reconnect flow (code)

```
Server message (go_away, time_left=30s)
    │
    ▼
_handle_message
    ├─ log "scheduling graceful reconnect"
    ├─ session.send_realtime_input(audio_stream_end=True)
    └─ _go_away_reconnect = True
    │
    ▼
_receive_loop (after _handle_message returns)
    ├─ log "exiting receive loop for graceful go_away reconnect"  ← NEVER SEEN IN LOG
    ├─ return (clean exit from async with live.connect)
    │
    ▼
_run outer loop
    ├─ rebuild _live_config() with session_resumption handle
    ├─ is_reconnect=True → drain mic queue, flush speaker queue
    ├─ skip greeting (_maybe_greet once per session)
    └─ new live.connect → _receive_loop
```

On **exception** (not graceful exit):

```
_run except → log _run:reconnect (attempt, error, has_resume_handle)
           → exponential backoff (1s → 30s cap)
```

Relevant implementation: `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\widget\gemini_live.py` lines ~453–537 (`_run`), ~720–737 (`_receive_loop`), ~882–896 (`go_away` handler).

Test coverage: `test_handle_message_go_away_schedules_graceful_reconnect` in `C:\Users\ACER\Desktop\Ai_computer\Orynn\tests\test_gemini_live.py` (~2870).

---

## Storm timeline — key clusters

### Cluster A — Early subagent burst (lines 64–176)

| Line | Timestamp | Δ from prev go_away |
|---:|---:|---:|
| 64 | 1781821146961 | +3.5 h (after initial session) |
| 80 | 1781821199110 | **52 s** |
| 96 | 1781821506016 | 5.1 min |
| 112 | 1781821525394 | **19 s** |
| 128 | 1781821793119 | 4.5 min |
| 144 | 1781821977861 | 3.1 min |
| 160 | 1781822072459 | 94 s |
| 176 | 1781822214044 | 2.4 min |

Eight go_aways in ~**18 minutes** of wall time after a long idle gap — each preceded by the subagent tool signature (see below).

### Cluster B — Triple go_away (lines 701–719)

| Line | Timestamp | Δ |
|---:|---:|---:|
| 701 | 1781935133674 | — |
| 702 | 1781935193591 | **60 s** |
| 719 | 1781935232648 | **39 s** |

Three rotations within **99 seconds**, immediately after 1007 reconnect failures (lines 680, 684).

### Cluster C — Back-to-back (lines 794–811)

| Line | Timestamp | Δ |
|---:|---:|---:|
| 794 | 1781970748199 | — |
| 811 | 1781970784968 | **37 s** |

### Cluster D — Tight pair (lines 1186–1226)

| Line | Timestamp | Δ |
|---:|---:|---:|
| 1186 | 1782072954459 | — |
| 1206 | 1782073662294 | 11.8 min |
| 1226 | 1782073676425 | **14 s** |

### Cluster E — Final storm (lines 1469–1629)

Nine go_aways in ~**69 minutes**, including:

| Lines | Timestamps | Δ |
|---|---|---:|
| 1589 → 1609 | 1782154425622 → 1782154456260 | **31 s** |
| 1609 → 1629 | 1782154456260 → 1782155368333 | 15 min |

---

## Correlation with subagent / desktop activity

### Signature before most go_aways (test-heavy segments)

Repeated burst pattern (~50+ occurrences):

1. `_execute_tool: start_desktop_task` (often **without** preceding `tool_call` log — see below)
2. Four `_execute_tool: x` calls (3× `ok: true`, 1× `error: "nope"`)
3. `tool_call: start_desktop_task` + `tool_call: desktop_control`
4. `go_away received`

The **`x` / `nope` pair** matches `test_execute_tool_turns_exceptions_into_error_response` in `test_gemini_live.py` (handler raises `RuntimeError("nope")`). Tool `x` is **not** declared in `_function_declarations()` — it does not exist in production Live tool schema. These entries indicate **pytest exercising `_execute_tool` on the same instrumented companion** that writes to `debug-eec63b.log`, interleaved with real Live API traffic.

**Production-correlated tools** in the same bursts:

- `start_desktop_task` — 399 log mentions
- `desktop_control`, `look_at_screen`, `stop_current_task` (12×), `get_companion_status`

### Session start context (lines 1–4)

Before the first go_away:

- Three `_live_tool:busy` blocks (`start_desktop_task`, `desktop_control`, `run_terminal`) while `"write a poem in Notepad"` was active
- Then go_away at line 4 — rotation happened **during** an active background task

### Dual-tool turns before rotation

Many turns end with `tool_call: ["desktop_control", "start_desktop_task"]` in one message. Code allows only one desktop tool per turn (`desktop_used` gate); the second is rejected in-process, but the turn still completes and the session continues until go_away.

---

## Failure mode: 1007 resume handle (lines 677–684)

```
677  tool_call: look_at_screen
678  _execute_tool: look_at_screen entry
679  _execute_tool: look_at_screen exit (ok)
680  _run:reconnect — "1007 None. Request contains an invalid argument." has_resume_handle: true
681  tool_call: look_at_screen (retry on new session?)
682–683  look_at_screen executes again
684  _run:reconnect — same 1007 error
```

**Interpretation:** Connection dropped (possibly mid-go_away grace window or server close) while `_resume_handle` was set. Reconnect with that handle was rejected. This is distinct from graceful go_away but **amplifies** the storm: failed resume → exception path → immediate retry → new session → another go_away soon after.

---

## Observability gap: schedule without confirmed exit

| Expected | Observed |
|---|---|
| 69 schedule → up to 69 receive-loop exits | **0** exit logs |
| Graceful reconnect is silent in `_run` (no log on success) | Cannot distinguish graceful vs idle rotation in outer loop |
| `_run:reconnect` only on exception | Only **2** entries |

**Possible explanations:**

1. **Instrumentation timing** — `_receive_loop:go_away` log added after most field data collected (less likely given same `pre-fix` runId on both probes).
2. **Connection teardown via exception** — WebSocket closes before receive loop checks `_go_away_reconnect`, taking the exception path (would expect more than 2 `_run:reconnect` logs unless reconnect usually succeeds on first retry).
3. **Log write failure** on exit path only (unlikely at 0/69).
4. **Process/thread restart** between schedule and loop check (would leave orphan schedule logs).

**Recommendation:** Add symmetric logging in `_run` when `async with live.connect` exits normally after go_away (e.g. `"graceful reconnect completing"` with `has_resume_handle`).

---

## Root causes

### 1. Server session lifetime (expected)

Gemini Live rotates long-lived WebSocket sessions. `go_away` with 30s notice is **by design**. A multi-day Live session will accumulate many rotations.

### 2. No go_away debouncing (client)

Each `go_away` message sets `_go_away_reconnect = True` and logs, even if already scheduled. No `_go_away_pending` guard, no coalescing of duplicate notices on the same connection.

### 3. Reconnect under tool load

Heavy `start_desktop_task` + tool-response traffic keeps sessions busy. Clusters show go_away often follows desktop/subagent bursts. Long sessions with many tool turns may hit rotation limits sooner.

### 4. Resume handle staleness (1007)

`session_resumption=SessionResumptionConfig(handle=self._resume_handle)` is rebuilt each connect, but a handle captured mid-session may be invalid after server rotation or abrupt drop — causing 1007 loops.

### 5. Test/live interleaving (instrumentation noise)

Direct `_execute_tool("x")` calls from pytest pollute the log alongside real API events, making storm analysis noisier. The `x`/`nope` burst is **not** model-driven production behavior.

### 6. Missing graceful-exit telemetry

Cannot confirm in production logs that the intended exit path runs; storm severity may be under- or over-stated.

---

## Impact on subagent reliability

| Symptom | Effect |
|---|---|
| Rapid reconnect (30–60 s spacing) | Live may miss proactive `send_task_update` windows; user hears "reconnecting" status |
| Mic queue drain on reconnect | User must re-speak if reconnect happens during utterance |
| Speaker queue flush | Mid-sentence TTS cut off |
| 1007 resume failure | Conversation may reset partially; model retries tools (`look_at_screen` twice in log) |
| go_away during active subagent | Background desktop task **continues** (HTTP task independent of Live WS), but Live loses visibility until reconnect + `get_companion_status` |
| Busy gate at session edge (line 1–3) | Colliding Live desktop tools blocked correctly; unrelated to go_away but shows concurrent Live + subagent stress |

---

## Recommendations

### P0 — Observability

1. Log `_run` graceful loop completion: `{reason: "go_away", has_resume_handle, session_age_ms}`.
2. Correlate schedule ↔ exit with a monotonic `reconnect_generation` counter.
3. Separate test log file from field log (`debug-eec63b.log` should not capture pytest `_execute_tool("x")` calls).

### P1 — Debounce / coalesce

1. If `_go_away_reconnect` already True, skip re-schedule (log at debug only).
2. Optionally reconnect proactively at `time_left` minus small buffer instead of waiting for hard close.

### P1 — Resume handle recovery

1. On 1007 with `has_resume_handle: true`, clear `_resume_handle` and retry **once** with fresh session before backoff.
2. Persist last-good handle timestamp; discard if older than server-documented TTL.

### P2 — Subagent interaction

1. Defer new `start_desktop_task` Live tool calls while `_go_away_reconnect` pending (return `{ok: false, reconnecting: true}`).
2. After reconnect, inject context: `"Live session resumed; check get_companion_status for background task state"`.

### P2 — Rate limiting

1. Cap go_away-driven reconnects to max N per 10 minutes; surface user-visible "Live connection unstable" if exceeded.

---

## Related files

| File | Role |
|---|---|
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\widget\gemini_live.py` | go_away handler, reconnect loop, debug logging |
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\widget\textbox_overlay.py` | `_live_tool`, busy gate, `start_desktop_task` |
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\tests\test_gemini_live.py` | go_away unit test; `x`/`nope` tool tests |
| `C:\Users\ACER\Desktop\Ai_computer\Ai_computer\debug-eec63b.log` | Field + test interleaved trace |
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\scripts\debug_live_messages.py` | References `go_away` message type |

---

## Appendix — Example log excerpts

**Schedule (typical):**
```json
{"hypothesisId": "D", "location": "gemini_live.py:_handle_message:go_away",
 "message": "go_away received, scheduling graceful reconnect",
 "data": {"time_left": "30s"}, "sessionId": "eec63b"}
```

**1007 failure:**
```json
{"hypothesisId": "D", "location": "gemini_live.py:_run:reconnect",
 "message": "live connection dropped, retrying",
 "data": {"attempt": 1, "retry_delay": 1.0,
          "error": "1007 None. Request contains an invalid argument.",
          "has_resume_handle": true}}
```

**Subagent burst immediately before go_away (lines 778–794):**
- Orphan `start_desktop_task` + 4× `x` (last fails `nope`) — test fixture signature
- Then model `tool_call` for `start_desktop_task`, `desktop_control`
- go_away 3.5 s after last turn_complete

---

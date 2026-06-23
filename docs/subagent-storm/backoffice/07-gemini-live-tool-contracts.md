# Gemini Live Tool Contracts — Code Review

**Doc:** `07-gemini-live-tool-contracts.md`  
**Date:** 2026-06-22  
**Scope:** `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\widget\gemini_live.py` (declarations + bridge) and `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\widget\textbox_overlay.py` (`_live_tool` execution)  
**Tests:** `C:\Users\ACER\Desktop\Ai_computer\Orynn\tests\test_gemini_live.py` (offline); `scripts/live_tool_smoke.py` (wire E2E)  
**Mode:** Read-only static review (no Live session started)

---

## Executive Summary

Gemini Live exposes **14 function tools** to the model via `_function_declarations()` in `gemini_live.py`. The bridge (`GeminiLiveCompanion`) forwards `tool_call` messages to a local `on_tool` callback, wraps results in `types.FunctionResponse`, and enforces a **15s outer timeout** (`GEMINI_LIVE_TOOL_TIMEOUT`).

Execution lives in `OverlayController._live_tool()` / `_live_tool_for_generation()`, wired at connect time:

```1188:1188:C:\Users\ACER\Desktop\Ai_computer\Orynn\app\widget\textbox_overlay.py
on_tool=lambda name, args, gen=generation: self._live_tool_for_generation(gen, name, args),
```

**Architecture split:**

| Layer | File | Responsibility |
|-------|------|----------------|
| **Declaration** | `gemini_live.py` | JSON schemas, routing hints in descriptions, system prompt examples |
| **Transport** | `gemini_live.py` | Arg coercion, batch mutual exclusion, timeout, `FunctionResponse` |
| **Execution** | `textbox_overlay.py` | Desktop API, vision frames, memory, workflows, consent gates |

**Key cross-cutting rules:**

1. **One desktop action per turn** — `desktop_control` and `start_desktop_task` cannot both run in the same `tool_call` batch.
2. **One desktop task at a time** — busy gate blocks new `desktop_control` / `start_desktop_task` while a back-office task is active.
3. **Consent retry pattern** — disruptive goals/commands return `needs_consent: true`; model must ask verbally, then retry with `confirmed: true`.
4. **Vision ordering** — screenshots go over `send_realtime_input(video=…)` **before** `FunctionResponse`; `look_at_screen` uses `wait=True` to avoid frame/response races.
5. **Model path vs gateway path** — Live model calls get fast-then-escalate routing for `click`/`type`; push-to-talk / Golden Five call `_live_tool` directly (pixel fallback allowed).

---

## 1. Runtime & Transport Contract

### 1.1 Session config

`_live_config()` attaches:

- `response_modalities`: AUDIO only
- Input/output audio transcription
- `thinking_config.thinking_level` — default **MEDIUM** (`GEMINI_LIVE_THINKING` / `GEMINI_LIVE_THINKING_LEVEL`)
- `system_instruction` — voice-first routing prompt (`_default_system_instruction()`)
- `tools`: `[types.Tool(function_declarations=_function_declarations(types))]`
- Optional `types.Tool(google_search=…)` when `GEMINI_LIVE_SEARCH=1` (paid-tier; off by default)
- `session_resumption` — resume handle across reconnects

### 1.2 Tool callback signature

```python
ToolCallback = Callable[[str, dict[str, Any]], dict[str, Any]]
```

`on_tool(name, args) -> dict` — sync or async. Non-dict returns are wrapped as `{"ok": True, "result": …}`.

### 1.3 Argument coercion

`_coerce_tool_args()` requires a JSON object. Malformed args → `{"ok": False, "message": "Tool arguments must be a JSON object."}` without invoking the handler.

### 1.4 Execution timeout

`GEMINI_LIVE_TOOL_TIMEOUT = 15.0` seconds. Must stay above longest bounded desktop primitive (~9s wait + overhead). On timeout:

```json
{"ok": false, "message": "Tool timed out after 15s."}
```

Note: the underlying thread may still run; timeout only affects what the model is told.

### 1.5 Batch mutual exclusion (transport layer)

In `_handle_message()`, `_DESKTOP_TOOLS = {"desktop_control", "start_desktop_task"}`. If both appear in one `function_calls` array, the first runs; the second gets:

```json
{
  "ok": false,
  "message": "Only one desktop action per turn — pick desktop_control OR start_desktop_task, not both. Wait for the result first."
}
```

### 1.6 Generation guard

`_live_tool_for_generation(generation, …)` returns `{"ok": False, "message": "Gemini Live session changed."}` if the session generation is stale (reconnect race).

### 1.7 Universal response envelope

All tools return a **dict** sent verbatim as `FunctionResponse.response`. Conventions:

| Field | Meaning |
|-------|---------|
| `ok` | Primary success flag (defaults treated as success if absent in some paths) |
| `message` | **Model-facing instruction** — often tells Live what to say or do next |
| `needs_consent` | Spoken confirmation required before retry with `confirmed: true` |
| `busy` | Desktop task already running |
| `blocked` | Hard safety block (terminal) |
| `action` | Which `desktop_control` primitive ran |
| `output` | Truncated tool output (desktop, terminal, search) |
| `data` | Compact structured UIA metadata |
| `task_id`, `status`, `result` | Desktop task lifecycle |
| `sources` | Web search URLs for citation |

The system prompt instructs the model: **if `ok` is false, never claim success**; if `needs_consent`, ask out loud before retry.

---

## 2. Tool Catalog (Declarations → Execution)

### 2.1 `desktop_control`

**Purpose:** One fast primitive (~1–3s) in an already-open app. Read-only inspection or single input action.

**Required:** `action` (enum)

| `action` | Required args | Optional args | Notes |
|----------|---------------|---------------|-------|
| `wait_for_window` | `title` or `app` | `timeout` (0.5–9s, default 6) | Sliced wait loop |
| `focus_window` | `title` or `app` | — | |
| `observe` | — | `app`, `cap` (20–220, default 90) | Adaptive UIA read |
| `find` | `query` | `app`, `limit` (1–10) | |
| `wait` | `query` | `app`, `timeout` | UIA wait for control |
| `click` | `query` | `app`, `timeout` | Model path: UIA-only fast, then escalate |
| `type` | `query`, `text` | `app`, `clear_first`, `submit` | No `query` → escalates to agent |
| `press_keys` | `keys` | `app` | Blocked: `alt+f4`, `alt+tab`, Orynn hotkeys |
| `scroll` | — | `app`, `amount` (neg=down, pos=up) | |

**Model-path routing (`_desktop_control_route`):**

- Applies only to `click` and `type` when `ORYNN_LIVE_AUTOROUTE` is not `off`.
- Flow: busy check → consent check → fast UIA-only attempt (`fast_invoke_only=True`, no pixel fallback) → soft-fail check (`data.verified is False`) → Electron consent → `start_desktop_task` escalation.
- Other actions run as bounded primitives via `_live_desktop_control` directly.

**Success response shape:**

```json
{
  "ok": true,
  "action": "click",
  "output": "<truncated 1200 chars>",
  "data": { "...": "compact UIA fields" }
}
```

**Failure shapes:** `{"ok": false, "action": "...", "message": "..."}`; consent: `needs_consent: true`.

**Declaration vs implementation gap:** Schema lists `desktop_control` actions but does **not** expose `confirmed` on this tool — consent for disruptive clicks/types routes through `start_desktop_task` with `confirmed: true`.

---

### 2.2 `start_desktop_task`

**Purpose:** Full back-office agent — launch apps, multi-step goals, vague work.

**Required:** `goal` (string)  
**Optional:** `confirmed` (boolean) — required after `needs_consent`

**Routing shortcuts:**

- Single-click goals parsed by `_parse_single_click_goal()` may redirect to `desktop_control` fast path.
- Busy gate applies.

**Response shapes:**

| Situation | Response |
|-----------|----------|
| Missing goal | `{"ok": false, "message": "Missing goal."}` |
| Needs consent | `{"ok": false, "needs_consent": true, "message": "…ask out loud…"}` |
| Preflight blocked | `{"ok": false, "message": "Setup needed before task can run."}` |
| Finished within wait budget | `{"ok": true, "task_id": "…", "status": "done", "result": "…", "message": "…succeeded…"}` |
| Failed terminal | `{"ok": false, "task_id": "…", "status": "failed\|error\|cancelled", "result": "…", "message": "…FAILED…"}` |
| Still running after wait | `{"ok": true, "task_id": "…", "status": "running", "message": "…background…proactive alert…"}` |

Wait budget: `ORYNN_LIVE_TASK_WAIT` (default **6s**, max 30s). Long jobs finish via `send_task_update` proactive alerts.

---

### 2.3 `look_at_screen`

**Purpose:** Foreground vision peek (read-only, safe mid-task).

**Args:** `question` (optional string)

**Side effects:**

1. Capture JPEG (`_capture_vision_jpeg` — PrintWindow foreground or monitor fallback)
2. `send_screen_image(jpeg, wait=True)` — **video** realtime channel, 250ms settle
3. `send_context_update` with freshness instructions
4. `FunctionResponse` with describe prompt

**Success:**

```json
{
  "ok": true,
  "message": "The user's screen is now in view. Foreground window when captured: <title>. <question> Answer out loud…"
}
```

**Critical invariant:** Never send images via `send_client_content` — causes WebSocket 1007 session drop.

---

### 2.4 `list_windows`

**Purpose:** Enumerate open windows before background peek.

**Args:** `include_minimized` (boolean, default true)

**Success:**

```json
{
  "ok": true,
  "count": N,
  "windows": [{"title": "…", "minimized": false}],
  "message": "Open windows on the PC. Use capture_window…"
}
```

---

### 2.5 `capture_window`

**Purpose:** PrintWindow screenshot of a background window by partial title.

**Required:** `title`  
**Optional:** `index` (default 0), `question`

**Flow:** PrintWindow capture → `send_screen_image(wait=True)` → `send_context_update` with frame note → response.

**Success:** `{"ok": true, "window": "<full title>", "message": "…"}`  
**No match:** `{"ok": false, "message": "No open window matched '…'. Try list_windows first."}`

---

### 2.6 `run_terminal`

**Purpose:** Single shell command with output.

**Required:** `command`  
**Optional:** `confirmed` (for destructive commands)

**Gates:**

1. `SafetyManager` — catastrophic commands **hard-blocked** (`blocked: true`)
2. `LIVE_TERMINAL_CONSENT_RE` — delete/push/kill/uninstall need `confirmed: true`
3. Cancellable worker thread (interrupt on Live stop)

**Success:** `{"ok": true, "output": "<1500 chars>", "message": "Command finished — tell the user the result briefly."}`

---

### 2.7 `web_search`

**Purpose:** Real-time web facts (free-tier alternative to paid `google_search` grounding).

**Required:** `query`

**Success:** `{"ok": true, "output": "…", "sources": ["url", …], "message": "…cite source out loud…"}`

Declaration explicitly says: do **not** search for static knowledge the model already knows.

---

### 2.8 `stop_current_task`

**Purpose:** Cancel running desktop work.

**Args:** none

**Not busy-gated.** Clears local busy state first, then `POST` kill to backend.

**Success:** `{"ok": true, "stopped": N, "message": "Stop request accepted."}`

---

### 2.9 `get_companion_status`

**Purpose:** Poll task progress (escape hatch while busy).

**Args:** none  
**Not busy-gated.**

**Success:**

```json
{
  "ok": true,
  "active_tasks": 0,
  "current_task": "optional goal",
  "progress": {"goal": "…", "step": "…"},
  "last_result": {"goal": "…", "status": "…", "ok": true, "summary": "…"}
}
```

---

### 2.10 `remember`

**Purpose:** Persist fact to `/api/memory/facts`.

**Required:** `fact`  
**Optional:** `category` (enum: rule, preference, location, vocab, fact, app), `owner` (user|assistant), `app`

**Success:** `{"ok": true, "message": "Got it — I'll remember that. Confirm briefly to the user."}`  
Refreshes knowledge block + pushes `send_context_update` mid-session.

---

### 2.11 `forget`

**Purpose:** Remove facts matching query via `/api/memory/forget`.

**Required:** `query`

**Success:** `{"ok": true, "removed": N, "message": "…"}`

---

### 2.12 `run_workflow`

**Purpose:** Execute saved multi-step workflow by name.

**Required:** `name`  
**Optional:** `confirmed` (if workflow has disruptive steps)

**Busy-gated** (like desktop tasks).

**Outcomes:**

- Success: `{"ok": true, "total": N, "message": "Ran all N steps…"}`
- Step failure: `{"ok": false, "completed_steps": i-1, "total": N, "failed_step": "…", "message": "…do NOT say it finished…"}`
- Consent: `needs_consent: true`

---

### 2.13 `save_workflow`

**Purpose:** Persist reusable procedure.

**Required:** `name`, `steps` (array)  
**Optional:** `description`, `triggers`

Step `action` enum in schema: `open|click|type|press_keys|scroll|focus|run|wait`

**Success:** `{"ok": true, "name": "…", "steps": N, "message": "Saved the '…' workflow…"}`

---

### 2.14 `forget_workflow`

**Purpose:** Delete workflow by name.

**Required:** `name`

**Success:** `{"ok": true, "removed": N, "message": "…"}`

---

## 3. Routing Matrix (Model Voice Path)

From `_default_system_instruction()` + tool descriptions:

| User intent | Tool | Anti-patterns |
|-------------|------|---------------|
| Chat / static knowledge | *(none)* | Don't `web_search` capitals, math |
| Current events | `web_search` | One call per question |
| Quick shell | `run_terminal` | Not for multi-step desktop |
| Foreground screen | `look_at_screen` | Never guess without frame |
| Background app peek | `list_windows` → `capture_window` | |
| Single click/type in open app | `desktop_control` | Not `start_desktop_task` |
| Open app / multi-step | `start_desktop_task` | Not `desktop_control` |
| Saved repeat procedure | `run_workflow` | Not `start_desktop_task` |
| Teach procedure | `save_workflow` | |
| Memory | `remember` / `forget` | |
| Cancel | `stop_current_task` | |
| Progress check | `get_companion_status` | |

---

## 4. Busy Gate Contract

`_busy_response()` when `_active_desktop_task()` is non-null:

```json
{
  "ok": false,
  "busy": true,
  "active_task": "<goal>",
  "message": "A desktop task is already running: \"…\". Do NOT start another action…"
}
```

**Gated:** `desktop_control`, `start_desktop_task`, `run_workflow` (and fast-path route)  
**Ungated:** `stop_current_task`, `get_companion_status`, vision tools, `run_terminal`, memory, `web_search`

---

## 5. Consent Contract

Shared pattern for `start_desktop_task`, `run_terminal`, `run_workflow`, and Electron escalation from `desktop_control`:

1. First call → `ok: false`, `needs_consent: true`, `message` instructs model to ask verbally
2. User says yes → retry with `confirmed: true`
3. User says no → drop it, tell user

`desktop_control` schema has **no** `confirmed` field — disruptive fast clicks route consent through `start_desktop_task`.

---

## 6. Vision Pipeline Contract

```
look_at_screen / capture_window
  → JPEG encode (_encode_vision_jpeg)
  → send_realtime_input(video=Blob)   # NOT client_content
  → [wait 0.25s if wait=True]
  → send_context_update(freshness note)  # capture_window only
  → FunctionResponse(message prompts describe turn)
```

Env: `ORYNN_LIVE_SCREEN_CAPTURE` (window vs monitor), vision JPEG quality/max edge via `_live_vision_jpeg_settings()`.

---

## 7. Findings & Recommendations

### Strengths

1. **Clear two-tier split** — declarations in one file, execution in overlay; easy to test declarations offline.
2. **Structured failure modes** — timeouts, consent, busy, and batch exclusion never throw to the model.
3. **Vision race fix** — `wait=True` on frame send is documented and tested.
4. **Free-tier safety** — Google Search grounding opt-in; `web_search` desktop tool as fallback.
5. **Strong test surface** — `test_gemini_live.py` covers declarations, routing, consent, busy, vision ordering.

### Gaps / Risks

| ID | Issue | Severity | Notes |
|----|-------|----------|-------|
| G1 | **Schema/impl mismatch on consent** | Medium | `desktop_control` description says auto-escalates; consent uses `start_desktop_task` + `confirmed`, not declared on `desktop_control` |
| G2 | **Tool timeout vs thread leak** | Medium | 15s timeout returns to model but handler thread may continue (documented in code comments) |
| G3 | **`confirmed` on redirected single-click** | Low | `_parse_single_click_goal` passes `confirmed` into click args, but `desktop_control` schema doesn't declare it — works at runtime but invisible to model |
| G4 | **Dual search paths** | Low | `GEMINI_LIVE_SEARCH` (native grounding) vs `web_search` tool — model may confuse; system prompt could be clearer when both exist |
| G5 | **14 tools + long system prompt** | Low | Google guidance says don't duplicate tool specs in system prompt; some overlap remains in `_default_system_instruction()` examples |
| G6 | **Unknown tool message** | Info | Returns `Unknown tool: {name}` — good for model recovery; no telemetry hook beyond debug log |

### Recommended doc/test additions (no code change in this review)

1. Add a **response schema appendix** per tool in API docs (this file serves that role for backoffice).
2. Integration test: `capture_window` → verify `send_context_update` + `FunctionResponse` ordering matches `look_at_screen`.
3. Document `ORYNN_LIVE_AUTOROUTE=off` behavior for operators debugging false escalations.

---

## 8. File Reference Map

| Symbol | Path |
|--------|------|
| `_function_declarations` | `Orynn\app\widget\gemini_live.py:975` |
| `_execute_tool` / `_handle_message` | `Orynn\app\widget\gemini_live.py:741, 898` |
| `_live_tool` dispatch | `Orynn\app\widget\textbox_overlay.py:2180` |
| `_desktop_control_route` | `Orynn\app\widget\textbox_overlay.py:1761` |
| `_live_config` | `Orynn\app\widget\gemini_live.py:548` |
| `send_screen_image` | `Orynn\app\widget\gemini_live.py:669` |
| Live constants | `Orynn\app\widget\textbox_overlay.py:88–149` |

---

## 9. Test Coverage Snapshot

`tests/test_gemini_live.py` validates (offline):

- All 14 declaration names present
- `desktop_control` / `start_desktop_task` mutual exclusion in descriptions and batch handler
- Async/sync handler routing, timeout, malformed args
- Overlay routing: desktop control, tasks, terminal safety, remember/forget, web_search, vision, busy gate, consent, workflow tools

Pytest artifact: `docs/subagent-storm/tests/01-gemini-live-pytest.txt` (run in progress at review time).

Wire validation: `scripts/live_tool_smoke.py`, `scripts/live_vision_smoke.py`.
```

---

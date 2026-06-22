# Spotify Task Failure Postmortem

**Doc:** `05-spotify-failure-postmortem.md`  
**Date:** 2026-06-22  
**Incident window:** 2026-06-22T17:57:41Z – 17:58:52Z  
**Severity:** P1 (user-facing trust break — voice said success, bubble showed failure, app never opened)  
**Related tasks:** `clicky-c6beede9be`, `clicky-245a57ddc2`, `clicky-f510fe3d74`  
**Related Orynn docs:** [03-universal-launch.md](../../windows-automation-research/03-universal-launch.md), [06-electron-chromium.md](../../windows-automation-research/06-electron-chromium.md)

---

## Executive Summary

On 2026-06-22, a Gemini Live voice session attempted to open Spotify three times. Each attempt created a desktop task that **failed in ~270ms** with reason `"Server restarted or task was abandoned."` The desktop agent **never executed** — no `workspace/logs/clicky-*.jsonl` files, no Win-key search, no UIA steps.

This was **not a Spotify/UIA failure**. It was a **task-spawn reliability bug** combined with a **UI leak**: internal backend error text appeared in the companion bubble while Live spoke as if Spotify were opening.

Fixes are partially landed in `app/main.py` (startup grace) and `app/widget/textbox_overlay.py` (bubble muting + human labels), with regression tests in `tests/test_task_abandon_grace.py` and `tests/test_gemini_live.py`.

---

## Impact

| Dimension | Effect |
|-----------|--------|
| **User experience** | Bubble flashed `Failed: Server restarted or task was abandoned.` while Live said *"Opening Spotify for you, and I'll let you know when it's ready."* |
| **Functional** | Spotify never launched |
| **Trust** | User asked *"What does that even mean? You can't open it yourself?"* — front desk / back office desync |
| **Retries** | Three identical failures; no recovery |

---

## Timeline (from `Orynn/logs/textbox_labels.jsonl`)

| Time (session ts) | Event |
|-------------------|-------|
| 1782151061.041 | User: **"Open Spotify."** |
| 1782151061.233 | Bubble: `Working...` (muted under Live hold) |
| 1782151061.857 | Bubble: **`Failed: Server restarted or task was abandoned.`** (`source: live_tool`) |
| 1782151063.605 | Live: *"Opening Spotify for you, and I'll let you know when it's ready."* |
| 1782151076.637 | User: *"What does that even mean? You can't open it yourself?"* |
| 1782151129.493 | User: **"Yeah, sure."** (retry) |
| 1782151129.792 | Bubble: same failure (task `clicky-245a57ddc2`) |
| 1782151132.853 | Bubble: same failure again (task `clicky-f510fe3d74`) |

---

## Failed Task Records

All three persisted under `Orynn/tasks/`:

| Task ID | Created (UTC) | Lifespan | Status | Reason |
|---------|---------------|----------|--------|--------|
| `clicky-c6beede9be` | 17:57:41.583 | **~271ms** | failed | Server restarted or task was abandoned. |
| `clicky-245a57ddc2` | 17:58:49.523 | **~266ms** | failed | Server restarted or task was abandoned. |
| `clicky-f510fe3d74` | 17:58:52.576 | **~274ms** | failed | Server restarted or task was abandoned. |

Common fields:
- **Goal:** `TASK: open Spotify` / `TASK: Open Spotify` (wrapped in full desktop-hardening system prompt)
- **Model:** `openrouter/openai/gpt-oss-120b:free`
- **Mode:** `computer`
- **Agent log:** **none** — no `Orynn/workspace/logs/clicky-c6beede9be.jsonl` (or siblings)

---

## What Happened (Technical)

### 1. Live dispatched correctly

Gemini Live called `start_desktop_task` with goal `"open Spotify"`. `_live_start_desktop_task` in `textbox_overlay.py` POSTed to `/api/tasks` and began polling via `_await_task_outcome` (`LIVE_TASK_RESULT_WAIT = 6.0s`).

### 2. Backend marked the task abandoned before it ran

`GET /api/tasks/{id}` runs `_serialize_task_record` in `main.py`. For a non-terminal record:

1. Check `server_running` via `service._active_tasks`
2. If not running, not paused, not queued → treat as orphan
3. **Pre-fix:** immediately rewrite to `failed` with opaque `"Server restarted or task was abandoned."`
4. **Post-fix:** hold as `running` for `_TASK_START_GRACE` (default **4.0s**), then fail with human reason or coroutine exception

The ~270ms lifespan matches **poll-before-worker** or **instant coroutine exit** before any log emission — not a Spotify launch timeout.

```
POST /api/tasks     →  TaskRecord saved (status: running)
GET  /api/tasks/id  →  not in _active_tasks → failed: "abandoned"
Live bubble         →  Failed: Server restarted or task was abandoned.
Agent               →  never logged a step
```

### 3. Bubble leak (separate failure mode)

Two paths exposed backend dialect to the voice bubble:

**Path A — `_await_task_outcome` (pre-fix):**  
Used `self._set_label("Failed: " + summary, source="live_tool", force=True)`, bypassing Live bubble protection.

**Path B — `task_result` events:**  
`_label_for_event` formats terminal events as `"Failed: " + reason`. `task_result` was not muted during Live, so poll-loop events could flash raw backend text.

**Post-fix behavior** (`textbox_overlay.py`):
- Mute `task_result` and task churn while Live is running
- On inline failure, label `"Couldn't complete that"`; pass real reason to Live via tool `message`/`result` for spoken explanation

### 4. Optimistic Live speech

Live narrated success **after** the tool returned failure (or in parallel). System prompt expects outcome-aware speech, but model still said *"Opening Spotify for you..."* — classic front-desk / back-office split.

---

## Root Cause

**Primary:** `_serialize_task_record` treated a freshly created task as abandoned when its asyncio worker was not yet visible in `service._active_tasks` (or had already exited without logging).

**Secondary:** Companion bubble surfaced internal failure strings to the user during Live sessions.

**Not root cause:** Spotify installation, UIA tree, Electron/CEF unlock, or `spotify:` URI handling — execution never reached launch primitives.

---

## Contributing Factors

1. **Heavy dispatch for a simple launch** — `"Open Spotify"` went to full `start_desktop_task` + computer-mode agent. Spotify is **not** in `_KNOWN_LAUNCH_APPS` (`app/tools.py`); fast-path launch registry only covers ~10 built-ins (notepad, calc, settings, etc.).

2. **Routing gap** — Research docs (`06-electron-chromium.md`, `03-universal-launch.md`) recommend `spotify:` URI or Win+Search for launch; Live used the slowest, most failure-prone path for a one-shot open.

3. **Possible stale backend** — `run_desktop.py` can attach to an existing port-8000 process whose in-memory `_active_tasks` may not match newly persisted task files.

4. **No jsonl = no forensics** — Without agent logs, distinguishing race vs instant crash vs wrong backend instance is harder.

---

## Detection

- User report: bubble error during Spotify request
- `Orynn/logs/textbox_labels.jsonl`: `live_tool` + exact failure string
- `Orynn/tasks/clicky-*.json`: ~270ms failed records, no corresponding `workspace/logs/*.jsonl`

---

## Resolution / Fixes (in codebase)

| Area | File | Change |
|------|------|--------|
| Startup grace | `app/main.py` | `_TASK_START_GRACE` (4s): fresh tasks stay `running` until worker registers |
| Human reasons | `app/main.py` | Fail with `_task_done_exception()` or `"the task ended before it could run"` instead of opaque abandoned |
| Bubble muting | `textbox_overlay.py` | Mute `task_result` + task churn under Live |
| Inline failure label | `textbox_overlay.py` | `"Couldn't complete that"` instead of `"Failed: " + raw reason` |
| Regression tests | `tests/test_task_abandon_grace.py` | Grace + human reason assertions |
| Regression tests | `tests/test_gemini_live.py` | `task_result` muted during Live |

**Note:** Persisted task JSON still contains the **old** `"Server restarted or task was abandoned."` string from the incident; current code uses different fallback text.

---

## Open Items

1. **Prove spawn root cause** — Confirm whether race, instant `run_task` crash, or stale backend; check for `[API] Initializing task clicky-...` in server console during repro.

2. **Launch routing for Spotify** — Add to launch registry (`spotify:` URI or indexed `.lnk`) so `"open spotify"` can use `run_terminal` / fast-path before full agent.

3. **Live honesty gate** — Block success language until `start_desktop_task` returns `ok: true`; on failure, speak the `message` field immediately.

4. **Repro harness** — Automated test: Live `start_desktop_task("open spotify")` → assert worker registered within grace → assert no abandoned reason.

---

## Lessons Learned

1. **App name in the user request ≠ app-specific bug** — Ultra-short task lifetime + no logs = infrastructure, not target app.

2. **One face for the user** — Backend error strings must never reach the voice bubble; Live owns spoken outcomes.

3. **Simple opens need simple lanes** — Full computer-mode agent for `"open Spotify"` adds latency and failure surface; shell/URI/Win+Search should be tier 0.

4. **Grace periods on distributed state** — Persisted `running` vs in-memory `_active_tasks` need a reconciliation window.

---

## Verification Checklist

- [ ] `pytest tests/test_task_abandon_grace.py tests/test_gemini_live.py -k "abandon or leak or task_result"` passes
- [ ] Voice: `"Open Spotify"` → no `Server restarted` in bubble
- [ ] Task gets `workspace/logs/clicky-*.jsonl` with `task_started` + launch actions
- [ ] On real failure, Live speaks honest explanation; bubble stays on Live text

---

## References

- Task records: `C:\Users\ACER\Desktop\Ai_computer\Orynn\tasks\clicky-c6beede9be.json` (and siblings)
- Session labels: `C:\Users\ACER\Desktop\Ai_computer\Orynn\logs\textbox_labels.jsonl` (lines ~3138–3279)
- Serialize logic: `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\main.py` (`_serialize_task_record`, `_TASK_START_GRACE`)
- Live dispatch: `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\widget\textbox_overlay.py` (`_live_start_desktop_task`, `_await_task_outcome`, `_set_label`)

---

**Bottom line:** Spotify did not fail to open — **the desktop agent never started**. The user saw a backend orphan message in the bubble while Live claimed it was opening Spotify. Fix the spawn race and keep internal errors off the bubble; route simple app opens through faster launch primitives.

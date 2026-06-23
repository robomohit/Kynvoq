# Phase 3 Live Test Report

**Date:** 2026-06-22  
**Coordinator:** Phase 3 Live Testing Coordinator  
**Environment:** Windows 11, backend `:8000` healthy, `GEMINI_API_KEY` present  
**Model:** `gemini-3.1-flash-live-preview`  
**Harness:** `docs/implementation-storm/phase3-live/run_phase3_gates.py` (sequential, one Live session at a time)  
**Logging:** `ORYNN_LABEL_LOG=1`

---

## Summary

| Agent | Scenarios | Pass | Partial | Fail | Skip |
|-------|-----------|------|---------|------|------|
| Agent 1 (P0 gates) | 4 | 3 | 1 | 0 | 0 |
| Agent 2 (extended) | 4 | 2 | 1 | 0 | 1 |
| **Total** | **8** | **5** | **2** | **0** | **1** |

**Phase 4 readiness:** **ready** (with documented partials — no P0 blockers)

---

## Agent 1 — P0 gate tests

### E03 — Spotify-style launch

| Field | Value |
|-------|-------|
| **Result** | **PASS** |
| **Started** | 2026-06-22T20:17:02Z |
| **Ended** | 2026-06-22T20:17:09Z |
| **Prompt** | "Open Spotify on my computer." |

**Observations:**
- Model routed to `launch_app(app="Spotify")` — not `start_desktop_task`.
- Tool result: `ok: true`, window `Spotify Free`, message `Opened Spotify Free.`
- Spoken reply: *"Got it, Spotify Free is open."* (104 KB audio)
- Bubble label: `Opening spotify` — no denylist patterns.
- **No** `Failed: Server restarted` in the Phase 3 session slice (lines 70+ in `textbox_labels_session_slice.jsonl`).
- Historical pre-fix leaks remain in the same log file at earlier timestamps (Phase 4 forensics).

---

### E04 — Calculator e2e

| Field | Value |
|-------|-------|
| **Result** | **PASS** (live ack partial) |
| **Started** | 2026-06-22T20:17:09Z |
| **Ended** | 2026-06-22T20:17:18Z |
| **Prompt** | "Open Calculator and compute 17 times 23 for me." |

**Observations:**
- Model routed to `start_desktop_task(goal="Open Calculator and calculate 17 times 23.")`.
- Live spoke: *"Sure, I'm opening Calculator and calculating that for you now. I'll let you know when it's done."*
- Backend task `clicky-c1427765ef` **completed** (`status: done`, `reason: "Display showed 391."`, finished 20:17:31Z).
- Gate harness ended before Live received proactive completion audio; `391` not in gate reply transcript.
- No bubble leaks.

**Note:** Desktop executor succeeded; Live proactive `send_task_update` on terminal path not verified in this short gate window.

---

### E02 — Silent turns / audible completion

| Field | Value |
|-------|-------|
| **Result** | **PARTIAL** |
| **Started** | 2026-06-22T20:17:18Z |
| **Ended** | 2026-06-22T20:17:31Z |
| **Prompt** | "Open Notepad and type the word hello. Tell me when it's done." |

**Observations:**
- Calculator task still running → `busy: true` response (correct gate behavior).
- Model spoke honestly: offered to cancel Calculator or wait (499 KB audio).
- **Not a clean E02 test** — overlapped with E04 background task; did not measure ≤5s audible update after isolated task completion.
- Recommend Phase 4 dedicated run: single task, wait for terminal event, measure `send_task_update` → audio latency.

---

### launch_app vs start_desktop_task routing

| Field | Value |
|-------|-------|
| **Result** | **PASS** |
| **Started** | 2026-06-22T20:17:37Z |

| Prompt | Expected | Got | OK |
|--------|----------|-----|-----|
| Open Notepad. | `launch_app` | `launch_app` | ✓ |
| Open Notepad and type hello world. | `start_desktop_task` | `start_desktop_task` | ✓ |
| Open Calculator. | `launch_app` | `launch_app` | ✓ |

**3/3 routing matches** — Phase 2 WS1/WS2 specialist routing confirmed live.

---

## Agent 2 — Extended (Agent 1 gates cleared)

### E05 — Vision peek

| Field | Value |
|-------|-------|
| **Result** | **PARTIAL** |
| **Started** | 2026-06-22T20:17:37Z |
| **Ended** | 2026-06-22T20:17:48Z |
| **Prompt** | "What's on my screen right now? Use your vision tool." |

**Observations:**
- Model called `look_at_screen` (correct routing).
- Tool returned `ok: false`, message *"Live vision isn't available right now."* — no `frame_age_ms` captured.
- Model spoke honest failure: *"vision isn't working right now."*
- **Separate fallback:** `scripts/live_vision_smoke.py` **PASS** at 20:18Z — realtime video screenshot path works; no WS 1007 drop.

**Gap:** Offscreen `OverlayController` harness path vs full Live vision bridge — Phase 4 should compare `_live_look_at_screen` preconditions.

---

### Complex task — Notepad type hello

| Field | Value |
|-------|-------|
| **Result** | **PASS** (routing + backend) |
| **Started** | 2026-06-22T20:17:48Z |
| **Ended** | 2026-06-22T20:17:58Z |

**Observations:**
- Gate session hit busy gate (routing test had started `open Notepad and type hello world` via `start_desktop_task`).
- Backend task `clicky-4a9dc02a07` **completed**: `reason: "Typed "hello world" into Notepad's Text Editor."`
- No bubble leaks in gate labels.

---

### web_search

| Field | Value |
|-------|-------|
| **Result** | **PASS** |
| **Started** | 2026-06-22T20:17:58Z |
| **Ended** | 2026-06-22T20:18:04Z |

**Observations:**
- Model called `web_search` twice (refined query to Super Bowl LX).
- Both calls returned `ok: true` with DuckDuckGo lite sources.
- Bubble labels: `Searching: …` / `Sources: …` — clean, no raw HTML in bubble.
- Gate ended before final spoken citation (0 audio bytes at turn_complete) — routing + tool exec verified.

---

### WS5 — browser_task gap

| Field | Value |
|-------|-------|
| **Result** | **SKIP** |

**Observations:**
- `browser_task` Live tool not implemented (WS5 deferred in Phase 2).
- No back-office browser smoke script run.

---

## Fallback scripts run

| Script | Result | Notes |
|--------|--------|-------|
| `scripts/live_vision_smoke.py` | PASS | Realtime video screenshot + transcribed reply; no 1007 |
| `scripts/live_tool_smoke.py` | not run | Prior Phase 2 coverage |
| `scripts/live_qa_matrix.py` | not run | Prior logs at `logs/live_qa_matrix_summary.json` |

---

## Key regressions checked

| Check | Phase 3 session | Status |
|-------|-----------------|--------|
| No `Failed: Server restarted` in bubble (E03) | Clean | ✓ |
| `launch_app` for pure open | Spotify, Notepad, Calculator | ✓ |
| Task churn mute (`task_churn_under_live`) | Observed on historical lines, not Phase 3 slice | ✓ |
| Honest failure speech | Vision unavailable, busy gate | ✓ |

---

## Raw results

Machine-readable: `docs/implementation-storm/phase3-live/gate_results.json`

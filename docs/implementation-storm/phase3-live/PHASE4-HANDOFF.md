# Phase 4 Handoff — Log Forensics

**From:** Phase 3 Live Testing (2026-06-22)  
**Status:** Phase 4 **ready** — P0 Spotify gate fixed live; two partials need targeted follow-up

---

## What Phase 4 agents should analyze

### 1. Bubble leak regression (F03 / G01)

- **Compare:** Phase 3 slice (`ts >= 1782159423`) vs historical lines with `Failed: Server restarted` (~1782151129).
- **Files:** `logs/textbox_labels.jsonl`, `artifacts/textbox_labels_session_slice.jsonl`
- **Question:** Did `sanitize_bubble_text` + `task_churn_under_live` mute prevent re-show of denylist strings in full overlay (`live: true`) sessions?
- **Golden fixture:** `tests/fixtures/spotify_label_sequence.jsonl`

### 2. Proactive task completion audio (E02 / F04)

- **Gap:** Phase 3 gate did not isolate terminal → `send_task_update` → ≤5s audio latency.
- **Evidence:** Calculator `clicky-c1427765ef` finished at 20:17:31Z with `391`; gate harness had already closed Live session.
- **Action:** Mine `send_task_update` / `[ORYNN — speak out loud NOW]` in `debug-eec63b.log` and overlay events for `clicky-c1427765ef`.
- **Files:** `tasks/clicky-c1427765ef.json`, `debug-eec63b.log`, `run_desktop_live.log`

### 3. Vision path split (E05 / WS7)

- **Observation:** `look_at_screen` via offscreen `OverlayController` returned *"Live vision isn't available right now."*
- **Contrast:** `scripts/live_vision_smoke.py` PASS — realtime video + FunctionResponse works.
- **Action:** Trace `_live_look_at_screen` guard conditions; verify `frame_age_ms` and OCR mid-tier (`ocr_live_capture`) in full overlay session.
- **Files:** `app/widget/textbox_overlay.py` (`_live_look_at_screen`), `app/providers.py`

### 4. Tool routing mix (F01)

- **Confirmed live:** `launch_app` for pure opens; `start_desktop_task` for compound goals (3/3).
- **Mine:** `debug-eec63b.log` for `launch_app` vs `start_desktop_task` ratio post-Phase-2.
- **Reference:** `gate_results.json` routing section

### 5. web_search reliability (F06)

- **Phase 3:** 2/2 tool calls `ok: true`; sources cited in bubble labels.
- **Action:** 10-run matrix per `07-load-test-matrix-phase3.md`; check stale/conflicting search snippets (Super Bowl LX vs older ESPN entries).

---

## Known failures / partials (not blockers)

| ID | Issue | Severity | Phase 4 action |
|----|-------|----------|----------------|
| E02 | Silent-turn test contaminated by busy gate | P1 | Re-run isolated Notepad-only task; measure audio latency |
| E04-live | Live didn't speak `391` in gate window | P2 | Verify `send_task_update` fired after `clicky-c1427765ef` done |
| E05-harness | `look_at_screen` ok:false offscreen | P1 | Full overlay Live session + `frame_age_ms` audit |
| WS5 | `browser_task` absent | P1 deferred | Document skip; no forensics until WS5 ships |
| Historical | Pre-fix `Server restarted` in label log | Info | Regression baseline only — not Phase 3 regression |

---

## Pass confirmations for Phase 4 baseline

1. **E03 Spotify gate:** `launch_app` → Spotify foreground → honest speech; no denylist bubble in session slice.
2. **Calculator backend:** 17×23 = 391 verified in task JSON.
3. **Routing:** 3/3 launch vs task discrimination.
4. **web_search:** Tool exposed and executes with sanitized bubble labels.
5. **Busy gate:** Model refuses second `start_desktop_task` and speaks alternatives (no silent stall).

---

## Recommended Phase 4 slice scripts

1. Filter `textbox_labels.jsonl` where `ts >= 1782159423` (Phase 3 UTC session).
2. Join task IDs `clicky-c1427765ef`, `clicky-4a9dc02a07` with overlay events API log lines.
3. NDJSON hypothesis tags A/D/E/F per `log-plan/02-debug-log-slices.md`.
4. Re-run E02 in **full overlay** (not offscreen) with `ORYNN_LABEL_LOG=1` for `live: true` mute audit.

---

## Artifacts index

See `ARTIFACTS.md` for full paths. Primary bundle:

```
docs/implementation-storm/phase3-live/
  gate_results.json
  run_phase3_gates.py
  artifacts/
    textbox_labels_session_slice.jsonl
    clicky-c1427765ef.json
    clicky-4a9dc02a07.json
    debug-eec63b.log
```

---

## Git note

Phase 3 coordinator did **not** commit or push per instructions. Phase 4 may commit docs + artifacts when review complete.

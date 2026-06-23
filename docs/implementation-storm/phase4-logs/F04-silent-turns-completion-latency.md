# F04 — E02 Silent Turns / Completion Audio Latency

**Lane:** F04  
**Date:** 2026-06-22  
**Sources:** gate_results.json (E02, E04), textbox_labels slice, task JSON

---

## E02 scenario (contaminated)

From `gate_results.json` lines 77–107:

| Field | Value |
|-------|-------|
| scenario | E02_silent_turns |
| prompt | Open Notepad and type the word hello… |
| tool | `start_desktop_task` |
| tool_result | `ok: false`, `busy: true` |
| reply | Honest busy message (499710 audio bytes) |
| pass | true (busy gate, not silent stall) |

**Label (slice line 72):** `Busy: Open Calculator and calculate 17 times 23.`

**Conclusion:** E02 did **not** test silent-turn completion — Calculator task overlapped. Model spoke immediately (no silent stall). **PARTIAL** per LIVE-TEST-REPORT.md.

---

## E04 completion audio gap

From `gate_results.json` lines 42–76:

| Field | Value |
|-------|-------|
| scenario | E04_calculator_e2e |
| gate ended | 2026-06-22T20:17:18Z |
| task finished | 2026-06-22T20:17:31Z (`clicky-c1427765ef`) |
| spoken_391 | **false** |
| reply at gate end | "…I'll let you know when it's done." |

**Latency measurement:** Not possible in this artifact bundle — Live session closed **13 s before** task terminal event.

---

## Silent-turn detector (label-based)

Applied rule: tool `ok: true` + no `live_reply` within 5s of terminal.

| Check | Phase 3 slice |
|-------|---------------|
| `live_reply` entries post line 70 | 0 (offscreen harness) |
| Terminal completion labels | 0 |
| Silent stall after tool ok | **Not observed** |

Pre-Phase-3 slice (lines 1–66): extensive `live_reply` streaming during Spotify retry — user heard speech throughout; leaks were bubble text, not silence.

---

## send_task_update / debug evidence

- `debug-eec63b.log`: **no entries** during Phase 3 window (instrumentation inactive for offscreen gate).
- `run_desktop_live.log`: not sliced for this lane; no `send_task_update` line cited in Phase 3 bundle.

---

## Findings

1. **No silent stall** in Phase 3 — busy gate produced immediate 499 KB audio response.
2. **Proactive completion audio unverified** — harness timing prevents ≤5s latency measurement for `391`.
3. **P1 follow-up:** isolated Notepad task in full overlay with `ORYNN_LABEL_LOG=1` and `live: true`.
4. Not a P0 blocker — backend completed; Live handoff path needs dedicated run.

---

## Verdict (lane)

**PARTIAL.** Busy gate PASS; completion-audio latency **NOT MEASURED** (P2). Does not block ship.

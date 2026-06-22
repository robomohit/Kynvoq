# F03 — Task JSON Correlation (Calculator, Notepad)

**Lane:** F03  
**Date:** 2026-06-22  
**Artifacts:**  
- `docs/implementation-storm/phase3-live/artifacts/clicky-c1427765ef.json`  
- `docs/implementation-storm/phase3-live/artifacts/clicky-4a9dc02a07.json`  
- Label join: `textbox_labels_session_slice.jsonl` lines 71–76

---

## clicky-c1427765ef — Calculator 17×23

| Field | Value |
|-------|-------|
| status | `done` |
| created_at | 2026-06-22T20:17:12.191410+00:00 |
| finished_at | 2026-06-22T20:17:31.523984+00:00 |
| **lifespan** | **19.3 s** |
| reason | `Display showed 391.` |
| model | openrouter/openai/gpt-oss-120b:free |

**Label correlation:**

| Line | ts | label | alignment |
|------|-----|-------|-----------|
| 71 | 1782159432.546 | Started: Open Calculator and calculate 17 times 23. | ~20s after E04 gate start (20:17:09Z) |
| 72 | 1782159439.717 | Busy: Open Calculator… | E02 busy gate (20:17:18Z) |

**Reason quality:** Excellent — numeric verification (`391` = 17×23) matches acceptance criteria. Plain text, no markdown.

**Gap:** No terminal label (`Done:` / completion bubble) in slice — harness ended before proactive `send_task_update` (see F04).

---

## clicky-4a9dc02a07 — Notepad hello world

| Field | Value |
|-------|-------|
| status | `done` |
| created_at | 2026-06-22T20:17:35.690179+00:00 |
| finished_at | 2026-06-22T20:17:59.071345+00:00 |
| **lifespan** | **23.4 s** |
| reason | `Typed "hello world" into Notepad's Text Editor.` |

**Label correlation:**

| Line | ts | label | alignment |
|------|-----|-------|-----------|
| 74 | 1782159455.936 | Started: open Notepad and type hello world | routing test spawn |
| 75–76 | 1782159457–9469 | Busy: open Notepad… (×2) | complex_notepad + E02 busy gates |

**Reason quality:** Good — cites control name (Text Editor) and exact typed string.

---

## Timeline overlay (UTC)

```
20:17:09  E04 gate: start_desktop_task (Calculator)
20:17:12  clicky-c1427765ef created
20:17:18  E02 gate: busy (Calculator still running)
20:17:31  clicky-c1427765ef done (391)
20:17:35  clicky-4a9dc02a07 created (routing: type hello world)
20:17:59  clicky-4a9dc02a07 done
```

---

## Findings

1. Both Phase 3 tasks **completed successfully** with high-quality `reason` strings.
2. Label stream shows **Started** and **Busy** but no **Done** completion labels — expected when gate closes before terminal handoff.
3. Calculator finished **during** E02 window (20:17:31) but gate transcript lacks spoken `391` (`spoken_391: false` in gate_results.json L74).
4. No orphan tasks — exactly 2 task JSONs for Phase 3 session, both `done`.

---

## Verdict (lane)

**PASS (backend).** Lifespan and reason quality meet WS3/WS6 expectations. Live proactive handoff unverified in this harness window (P2, not P0).

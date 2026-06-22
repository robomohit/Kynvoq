# F01 — textbox_labels Session Slice: Bubble Leaks & Mute Reasons

**Lane:** F01  
**Date:** 2026-06-22  
**Artifact:** `docs/implementation-storm/phase3-live/artifacts/textbox_labels_session_slice.jsonl` (80 lines)  
**Phase 3 boundary:** `ts >= 1782159423.505` (line 70)

---

## Scope

Catalog bubble leak patterns and mute reasons in the bundled label slice. Compare pre-Phase-3 full-overlay session (`live: true`) vs Phase 3 gate harness (`live: false`).

---

## Phase 3 slice (lines 70–80)

| Line | ts | action | source | live | text |
|------|-----|--------|--------|------|------|
| 70 | 1782159423.505 | shown | live_tool | false | Opening spotify |
| 71 | 1782159432.546 | shown | live_tool | false | Started: Open Calculator and calculate 17 times 23. |
| 72 | 1782159439.717 | shown | live_tool | false | Busy: Open Calculator and calculate 17 times 23. |
| 73 | 1782159452.441 | shown | live_tool | false | Opening notepad |
| 74 | 1782159455.936 | shown | live_tool | false | Started: open Notepad and type hello world |
| 75 | 1782159457.096 | shown | live_tool | false | Busy: open Notepad and type hello world |
| 76 | 1782159469.390 | shown | live_tool | false | Busy: open Notepad and type hello world |
| 77 | 1782159479.811 | shown | live_tool | false | Searching: who won the last Super Bowl |
| 78 | 1782159480.953 | shown | live_tool | false | Sources: topendsports.com, en.wikipedia.org, msn.com |
| 79 | 1782159483.381 | shown | live_tool | false | Searching: who won Super Bowl LX |
| 80 | 1782159484.347 | shown | live_tool | false | Sources: en.wikipedia.org, espn.com, cbc.ca |

**Denylist hits in Phase 3 slice:** 0  
**`Failed:` strings shown:** 0

---

## Historical pre-fix leaks (lines 17, 31)

| Line | ts | action | source | reason (nearby mute) | text |
|------|-----|--------|--------|----------------------|------|
| 17 | 1782151129.792 | **shown** | live_tool | L16: `task_churn_under_live` muted "Finagling…" | Failed: Server restarted or task was abandoned. |
| 31 | 1782151132.853 | **shown** | live_tool | L30: `live_status_under_hold` muted "Working..." | Failed: Server restarted or task was abandoned. |

**Pattern:** Denylist string reached bubble via `live_tool` **despite** adjacent `task_churn_under_live` mutes on task_status lines (L16, L33). This is the pre-Phase-2 regression signature documented in `tests/fixtures/spotify_label_sequence.jsonl` (golden fixture expects `bubble_sanitizer_denylist` mute — not present in historical log).

---

## Mute reason inventory (full slice)

| reason | count | lines (sample) |
|--------|-------|----------------|
| `live_status_under_hold` | 4 | 15, 18, 30, 32 |
| `task_churn_under_live` | 2 | 16, 33 |

All mutes are in the pre-Phase-3 block (`live: true`). Phase 3 harness emitted **no** muted events — offscreen gate does not exercise live hold/churn paths.

---

## Source mix (shown only)

| source | pre-Phase-3 | Phase 3 |
|--------|-------------|---------|
| live_reply | 52 | 0 |
| live_tool | 2 (both leaks) | 11 |
| live_status | 4 | 0 |
| live_input | 2 | 0 |
| live_stop | 1 | 0 |
| system | 2 | 0 |

---

## Findings

1. **Phase 3 session is clean** — sanitized tool labels only (`Opening`, `Started:`, `Busy:`, `Searching:`, `Sources:`).
2. **Historical leaks are confined** to `ts < 1782159423` — regression baseline, not Phase 3 regression.
3. **`task_churn_under_live` alone did not prevent** pre-fix `live_tool` denylist leaks; Phase 2 `sanitize_bubble_text` + `bubble_sanitizer_denylist` path addresses this (fixture L3).
4. **Caveat:** Phase 3 labels are `live: false` (offscreen harness). Full-overlay `live: true` mute audit still recommended post-ship (see F04/F07).

---

## Verdict (lane)

**PASS for Phase 3 slice.** No bubble leaks in new session lines 70–80.

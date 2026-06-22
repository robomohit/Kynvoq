# F02 — Debug NDJSON: Tool Mix, Errors, go_away

**Lane:** F02  
**Date:** 2026-06-22  
**Artifact:** `docs/implementation-storm/phase3-live/artifacts/debug-eec63b.log` (1689 lines)  
**Note:** Historical pre-Phase-3 instrumentation (`runId: "pre-fix"`). No new NDJSON during Phase 3 offscreen gate run.

---

## Hypothesis tag distribution

| hypothesisId | count | role |
|--------------|-------|------|
| E | 1044 | `_execute_tool` entry/exit |
| A | 567 | `tool_call` received |
| D | 75 | `go_away` graceful reconnect |
| F | 3 | busy gate blocks |

---

## Tool exit summary (`_execute_tool:exit`)

| tool | total | ok | fail | fail % |
|------|-------|-----|------|--------|
| start_desktop_task | 156 | 151 | 5 | 3.2% |
| desktop_control | 37 | 34 | 3 | 8.1% |
| look_at_screen | 33 | 33 | 0 | 0% |
| web_search | 8 | 2 | 6 | **75.0%** |
| stop_current_task | 4 | 4 | 0 | 0% |
| get_companion_status | 2 | 2 | 0 | 0% |
| list_windows | 1 | 1 | 0 | 0% |
| run_terminal | 1 | 0 | 1 | 100% |
| x (unknown/stub) | 210 | 210 | 0 | 0% |

**`launch_app`:** 0 entries — debug log predates WS1 specialist or off-instrumentation path.

---

## go_away events

- **Count:** 73 (hypothesis D, `gemini_live.py:_handle_message:go_away`)
- **Sample (line 4):** `{"time_left": "30s"}` — graceful reconnect scheduled
- **Correlation:** Often follows dual-tool desktop batches (see below); not observed as user-visible bubble leak in Phase 3 slice.

---

## Dual desktop tool batches (exclusivity violations)

**25 multi-tool batches** where both desktop tools appear in one `tool_call`:

| Line | tools |
|------|-------|
| 731 | `['start_desktop_task', 'desktop_control']` |
| 1144 | `['desktop_control', 'start_desktop_task']` |
| 1163 | `['desktop_control', 'start_desktop_task']` |
| 1183 | `['desktop_control', 'start_desktop_task']` |
| 1203 | `['desktop_control', 'start_desktop_task']` |

**Pattern:** Pre-fix sessions show model batching `desktop_control` + `start_desktop_task` despite mutual exclusion intent (WS2). Phase 3 gate used specialist routing (`launch_app` / `start_desktop_task` only) — no dual batches in gate_results.json.

---

## Busy gate blocks (hypothesis F)

| Line | data |
|------|------|
| 1 | `{"tool": "start_desktop_task", "active_task": "write a poem in Notepad"}` |

3 total `blocked desktop tool during active background task` events in full log.

---

## web_search failure samples (historical)

| Line | ok | notes |
|------|-----|-------|
| 14 | false | early session |
| 39 | false | early session |

Phase 3 gate: **2/2 ok** (see F06) — historical 75% fail rate is **not** representative of current session.

---

## Findings

1. Debug log is **historical baseline** — Phase 3 gate did not append new NDJSON.
2. **web_search** historically unreliable (6/8 fail); Phase 3 live run reversed this (100% ok).
3. **go_away** frequent (73×) but handled gracefully in instrumentation.
4. **Dual desktop routing** was a pre-fix problem; Phase 3 routing gate 3/3 clean.
5. No `launch_app` in debug slice — tool-mix ratio for WS1 must come from gate_results.json, not this file.

---

## Verdict (lane)

**INFO for Phase 3.** Historical errors documented; no Phase 3 NDJSON to regress against. Recommend enabling NDJSON for future full-overlay runs.

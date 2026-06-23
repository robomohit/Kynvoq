# F09 — HandoffResult / user_message in Shown Labels

**Lane:** F09 (optional)  
**Date:** 2026-06-22  
**Sources:** gate_results.json, textbox_labels slice lines 70–80, CHANGELOG-for-other-agent.md (WS3)

---

## Design intent (WS3)

Per `CHANGELOG-for-other-agent.md`:
- `HandoffResult` exposes `user_message` only to Live/bubble
- `debug_reason` / terminal internals never reach bubble
- `_capture_live_task_outcome` uses handoff path for proactive updates

---

## Phase 3 shown labels audit

All 11 Phase 3 labels (lines 70–80) are `action: shown`, `source: live_tool`:

| line | text | contains debug/internal? |
|------|------|--------------------------|
| 70 | Opening spotify | No — matches `user_message` pattern |
| 71 | Started: Open Calculator and calculate 17 times 23. | No — goal echo only |
| 72 | Busy: Open Calculator and calculate 17 times 23. | No — busy gate user text |
| 73 | Opening notepad | No |
| 74 | Started: open Notepad and type hello world | No |
| 75–76 | Busy: open Notepad… | No |
| 77–80 | Searching:/Sources: | No — sanitized search labels |

**Forbidden patterns absent:**
- `Failed: Server restarted`
- `debug_reason`
- `UNTRUSTED WEB CONTENT`
- Raw JSON / UIA dumps
- `task_id` strings

---

## gate_results.json HandoffResult fields

**E03 launch_app** (lines 17–23):
```json
"user_message": "Opened Spotify Free."
```
Shown label line 70: `Opening spotify` — **abbreviated tool label**, not full user_message (expected: tool status label vs handoff speech).

**E04 start_desktop_task** (lines 52–58):
- `message` contains internal instruction ("Tell the user OUT LOUD…") — **not** in bubble
- Shown label line 71: `Started: Open Calculator…` — goal only ✓

---

## Pre-fix contrast (line 17)

```
"text": "Failed: Server restarted or task was abandoned."
```

This is the class of string `HandoffResult` + sanitizer now block. Phase 3 shows **zero** terminal failure strings in shown labels.

---

## Findings

1. Phase 3 bubbles contain **only user-facing abstractions** (Opening/Started/Busy/Searching/Sources).
2. Internal handoff instructions in tool_results never appeared in labels.
3. `user_message` drives **speech** (gate reply); bubble uses **shorter tool labels** — by design.
4. No evidence of `debug_reason` leak in Phase 3 session.

---

## Verdict (lane)

**PASS.** HandoffResult contract honored in Phase 3 shown labels.

# Lane A11: Background vs Foreground Specialist Modes

**Category:** specialists  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
SYNTHESIS Cursor foreground/background; Antigravity async default.

## Current code paths
- `desktop_job` async via poll
- `desktop_control` sync in tool callback
- `GEMINI_LIVE_TOOL_TIMEOUT=15s`

## Gap analysis
No explicit `is_background` on specs; long jobs risk tool timeout while still running.

## Proposed implementation
Tag specialists: sync (uia_act, vision_peek, launch) return in-tool; async (desktop_job, browser) return `{task_id, accepted:true}` immediately + `send_task_update` stream.

## Files to touch (Phase 2)
- `gemini_live.py` timeout policy per specialist
- `textbox_overlay.py`

## Test strategy
- Timeout tests with mocked slow task

## Estimated complexity
**M**

## Phase 2 workstream hint
WS3 Task Lifecycle & Handoff

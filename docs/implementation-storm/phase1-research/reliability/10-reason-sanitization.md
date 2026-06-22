# Lane B10: Task `reason` Sanitization

**Category:** reliability  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
Spotify postmortem; abandon race docs.

## Current code paths
- `record.reason` freeform in `tasks/*.json`
- Shown if handoff bypasses mute

## Gap analysis
Opaque "Server restarted or task was abandoned." and JSON action dumps in reason.

## Proposed implementation
`_humanize_task_reason(reason) -> user_message` mapping table; strip internal prefixes; log raw reason to debug only.

## Files to touch (Phase 2)
- `app/main.py`
- `textbox_overlay._capture_live_task_outcome`

## Test strategy
- Table-driven tests for reason strings

## Estimated complexity
**S**

## Phase 2 workstream hint
WS4

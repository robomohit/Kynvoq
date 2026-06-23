# Lane D07: `electron_unlock` Guard

**Category:** backoffice  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`reliability/09-electron-unlock-disruption.md`](../../subagent-storm/reliability/09-electron-unlock-disruption.md).

## Current code paths
- Electron unlock relaunch path
- Disrupts in-flight tasks

## Gap analysis
Cursor/Electron tasks fail mid-sequence.

## Proposed implementation
Defer unlock if desktop task active; queue unlock request; warn Live via handoff.

## Files to touch (Phase 2)
- `app/tools.py` or electron helper
- `textbox_overlay.py`

## Test strategy
- Mock active task guard

## Estimated complexity
**S**

## Phase 2 workstream hint
WS6

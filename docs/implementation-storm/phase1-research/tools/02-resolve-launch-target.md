# Lane C02: `resolve_launch_target`

**Category:** tools  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`proposals/01-resolve-launch-target.md`](../../subagent-storm/proposals/01-resolve-launch-target.md).

## Current code paths
Not implemented; `detect_app_launch_intent` only exact dict lookup.

## Gap analysis
No URI/shell/start ladder.

## Proposed implementation
Implement ladder: ms-settings → shell:AppsFolder → start command → web URL; return LaunchPlan struct.

## Files to touch (Phase 2)
- `app/tools.py` or `app/launch.py`

## Test strategy
- Unit tests per ladder tier (mocked subprocess)

## Estimated complexity
**L**

## Phase 2 workstream hint
WS1

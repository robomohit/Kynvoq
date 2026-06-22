# Lane D09: Desktop Control Route

**Category:** backoffice  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`backoffice/08-desktop-control-route-review.md`](../../subagent-storm/backoffice/08-desktop-control-route-review.md).

## Current code paths
- `_desktop_control_route` (`textbox_overlay.py:1761`)
- `_parse_single_click_goal` redirect

## Gap analysis
Escalation vs double-routing confusion in logs.

## Proposed implementation
Tag telemetry `route=intentional_escalation`; single model-facing tool response.

## Files to touch (Phase 2)
- `textbox_overlay.py`

## Test strategy
- Route decision unit tests

## Estimated complexity
**S**

## Phase 2 workstream hint
WS2

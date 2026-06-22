# Lane F03: Task JSON Correlation

**Category:** log-plan  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
tasks/*.json mining across storm.

## Current code paths
TaskRecord fields: goal, status, reason, timestamps.

## Gap analysis
No automated join between label stream and task artifacts.

## Proposed implementation
Join task_id from label log → task JSON; verify duration vs reason.

## Files to touch (Phase 2)
- `tasks/`; correlation script (Phase 4)

## Test strategy
Join label events to task JSON by task_id

## Estimated complexity
**S**

## Phase 2 workstream hint
Phase 4

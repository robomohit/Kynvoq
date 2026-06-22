# Lane F05: Duplicate Routing Forensics

**Category:** log-plan  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`logs/06-duplicate-start-desktop-task.md`](../../subagent-storm/logs/06-duplicate-start-desktop-task.md).

## Current code paths
Duplicate spawns same goal in task JSON.

## Gap analysis
Wasted tasks + race; no duplicate-goal metric.

## Proposed implementation
Count duplicate goals within 30s window; map to double-route batches.

## Files to touch (Phase 2)
- debug + tasks; duplicate detector

## Test strategy
Duplicate spawn report

## Estimated complexity
**S**

## Phase 2 workstream hint
Phase 4

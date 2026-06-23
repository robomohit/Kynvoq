# Lane F01: `textbox_labels.jsonl` Patterns

**Category:** log-plan  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`logs/05-textbox-labels-live-session.md`](../../subagent-storm/logs/05-textbox-labels-live-session.md).

## Current code paths
Fields: timestamp, label, source, disposition, reason, live_running.

## Gap analysis
Phase 4 needs pattern catalog.

## Proposed implementation
Checklist: grep `muted`+`task_outcome_under_live`; `live_tool` with `Failed:`; `Started:` without completion; correlate with task_id.

## Files to touch (Phase 2)
- `logs/textbox_labels.jsonl`

## Test strategy
Phase 4 agent playbook per pattern

## Estimated complexity
**S**

## Phase 2 workstream hint
Phase 4

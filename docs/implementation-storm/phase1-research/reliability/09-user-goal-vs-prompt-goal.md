# Lane B09: `user_goal` vs `prompt_goal` Split

**Category:** reliability  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`backoffice/09-task-payload-build-review.md`](../../subagent-storm/backoffice/09-task-payload-build-review.md).

## Current code paths
- `_build_task_payload` / `build_task_payload` in overlay + main

## Gap analysis
Single `goal` string conflates user speech with planner-expanded TASK: prefix; breaks retry and logging.

## Proposed implementation
Persist `user_goal` (verbatim speech) and `prompt_goal` (agent-facing); bubble shows user_goal only.

## Files to touch (Phase 2)
- `textbox_overlay.py`
- `main.py` TaskRecord schema

## Test strategy
- Payload snapshot tests

## Estimated complexity
**S**

## Phase 2 workstream hint
WS3

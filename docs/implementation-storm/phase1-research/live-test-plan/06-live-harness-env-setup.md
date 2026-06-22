# Lane E06: Live Harness Env Setup

**Category:** live-test-plan  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
LOAD-TEST-PLAN; textbox_overlay ORYNN_LABEL_LOG.

## Current code paths
- `ORYNN_LABEL_LOG=1` → `logs/textbox_labels.jsonl`
- `debug-eec63b.log` NDJSON

## Gap analysis
Env vars scattered.

## Proposed implementation
Document bundle: `ORYNN_LABEL_LOG=1`, `GEMINI_LIVE_TOOL_TIMEOUT`, `ORYNN_TASK_START_GRACE`, log paths, tail commands PowerShell.

## Files to touch (Phase 2)
- `docs/implementation-storm/phase1-research/live-test-plan/ENV.md` optional Phase 3

## Test strategy
Checklist

## Estimated complexity
**S**

## Phase 2 workstream hint
Phase 3 prep

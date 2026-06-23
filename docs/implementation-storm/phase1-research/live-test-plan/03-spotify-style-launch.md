# Lane E03: Spotify-Style Launch

**Category:** live-test-plan  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`reliability/05-spotify-failure-postmortem.md`](../../subagent-storm/reliability/05-spotify-failure-postmortem.md).

## Current code paths
Failed task `clicky-c6beede9be`; label log lines ~3138-3279.

## Gap analysis
P0 regression scenario.

## Proposed implementation
Script: speak "open Spotify"; assert no bubble leak <1s; window foreground within 15s OR honest failure spoken. Compare textbox_labels before/after fix.

## Files to touch (Phase 2)
- `ORYNN_LABEL_LOG=1`

## Test strategy
Phase 3 gate test

## Estimated complexity
**S**

## Phase 2 workstream hint
Phase 3 P0

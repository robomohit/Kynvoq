# Lane C03: `open_settings` Tool

**Category:** tools  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`proposals/03-open-settings-tool.md`](../../subagent-storm/proposals/03-open-settings-tool.md).

## Current code paths
No dedicated settings URI tool.

## Gap analysis
Agent guesses settings paths; fails on UIA.

## Proposed implementation
Tool `open_settings(page: enum)` → `start ms-settings:display` etc.; map voice intents to URIs.

## Files to touch (Phase 2)
- `app/tools.py`
- Live declaration

## Test strategy
- URI mapping tests

## Estimated complexity
**S**

## Phase 2 workstream hint
WS1

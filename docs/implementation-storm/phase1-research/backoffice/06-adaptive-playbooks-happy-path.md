# Lane D06: Adaptive Playbooks Happy Path

**Category:** backoffice  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`backoffice/06-adaptive-windows-playbooks.md`](../../subagent-storm/backoffice/06-adaptive-windows-playbooks.md).

## Current code paths
- Calculator, Notepad playbooks in `adaptive_windows.py`

## Gap analysis
Happy path not wired; agent rediscovers UI each time.

## Proposed implementation
Document + implement happy path for Calculator e2e (live-test-plan/04); playbook-first routing.

## Files to touch (Phase 2)
- `app/adaptive_windows.py`
- `app/agent.py`

## Test strategy
- `tests/test_adaptive_windows.py`

## Estimated complexity
**M**

## Phase 2 workstream hint
WS6

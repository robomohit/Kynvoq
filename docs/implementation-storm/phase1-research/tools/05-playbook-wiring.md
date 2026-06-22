# Lane C05: Adaptive Playbook Wiring

**Category:** tools  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`proposals/06-playbook-wiring.md`](../../subagent-storm/proposals/06-playbook-wiring.md); [`backoffice/06-adaptive-windows-playbooks.md`](../../subagent-storm/backoffice/06-adaptive-windows-playbooks.md).

## Current code paths
- `adaptive_windows.py` playbooks exist
- Manual agent selection

## Gap analysis
Playbooks not auto-selected from window class.

## Proposed implementation
On `observe_window`, attach playbook hints to agent prompt; auto-call playbook steps before generic UIA.

## Files to touch (Phase 2)
- `app/adaptive_windows.py`
- `app/agent.py`

## Test strategy
- `tests/test_adaptive_windows.py`

## Estimated complexity
**M**

## Phase 2 workstream hint
WS6

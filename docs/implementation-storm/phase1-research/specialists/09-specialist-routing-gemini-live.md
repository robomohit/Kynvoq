# Lane A09: Specialist Routing in Gemini Live

**Category:** specialists  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`backoffice/07-gemini-live-tool-contracts.md`](../../subagent-storm/backoffice/07-gemini-live-tool-contracts.md); [`reliability/02-double-routing-live.md`](../../subagent-storm/reliability/02-double-routing-live.md).

## Current code paths
- `_default_system_instruction()` routing examples
- Batch gate `desktop_used` (`gemini_live.py:852-871`)
- `_live_tool_for_generation` generation guard

## Gap analysis
Model still emits dual desktop tools (22 batches in debug log). Prompt-only routing insufficient.

## Proposed implementation
Add registry-driven routing section to system prompt; optional server-side intent classifier pre-tool-call; extend mutual exclusion to launch vs job vs uia_act families.

## Files to touch (Phase 2)
- `app/widget/gemini_live.py`
- `app/specialists/registry.py`

## Test strategy
- `tests/test_gemini_live.py` — dual-tool batch rejection
- `tests/test_mode_routing.py`

## Estimated complexity
**M**

## Phase 2 workstream hint
WS2 Live Front Desk & Specialists

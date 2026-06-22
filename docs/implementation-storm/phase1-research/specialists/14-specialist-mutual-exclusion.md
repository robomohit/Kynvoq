# Lane A14: Specialist Mutual Exclusion

**Category:** specialists  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`reliability/02-double-routing-live.md`](../../subagent-storm/reliability/02-double-routing-live.md).

## Current code paths
- `_DESKTOP_TOOLS` batch gate in `gemini_live.py:852-871`
- Overlay intentional escalation (fast→full) looks like double route

## Gap analysis
Gate covers only desktop_control+start_desktop_task; not launch+job or peek+act.

## Proposed implementation
Define exclusion groups in registry: `DESKTOP_WRITE`, `LAUNCH`, `VISION`. Max one tool per group per batch; document intentional escalation as single specialist chain.

## Files to touch (Phase 2)
- `app/widget/gemini_live.py`
- `app/specialists/registry.py`

## Test strategy
- `tests/test_gemini_live.py` multi-tool batches

## Estimated complexity
**S**

## Phase 2 workstream hint
WS2 Live Front Desk & Specialists

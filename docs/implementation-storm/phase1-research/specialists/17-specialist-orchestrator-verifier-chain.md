# Lane A17: Orchestrator → Worker → Verifier Chain

**Category:** specialists  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
SYNTHESIS recommendation #5; Cursor Verifier pattern.

## Current code paths
Linear: user → Live → single tool. No mandatory verify step.

## Gap analysis
Premature success narration (Spotify, web_search).

## Proposed implementation
Document chain: Live plans → delegates specialist → on terminal, invoke verify → only then speak success. Implement as overlay orchestration hook, not nested LLM by default.

## Files to touch (Phase 2)
- `textbox_overlay.py` — `_post_specialist_hook`
- Specialist registry

## Test strategy
- Integration test: launch→verify mock

## Estimated complexity
**M**

## Phase 2 workstream hint
WS1 + WS4

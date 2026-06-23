# Lane A08: Specialist Registry Architecture

**Category:** specialists  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
SYNTHESIS § declarative registry; Cursor `.cursor/agents/` pattern.

## Current code paths
Tools are flat function declarations; no central registry object.

## Gap analysis
Routing rules duplicated across prompt, declarations, overlay dispatch.

## Proposed implementation
Introduce `app/specialists/registry.py`: `SpecialistSpec` dataclass (name, description, tools, readonly, is_background, bubble_policy, model_tier). Loaded at Live connect.

## Files to touch (Phase 2)
- New `app/specialists/`
- `gemini_live.py` — generate declarations from registry

## Test strategy
- Registry unit tests
- Snapshot of generated declarations

## Estimated complexity
**M**

## Phase 2 workstream hint
WS2 Live Front Desk & Specialists

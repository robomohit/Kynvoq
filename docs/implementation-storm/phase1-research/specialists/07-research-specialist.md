# Lane A07: Research Specialist (codebase)

**Category:** specialists  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
SYNTHESIS `research` built-in; Cursor Explore analog.

## Current code paths
- File reads via agent tools / terminal in desktop_job
- No dedicated readonly search specialist for Live

## Gap analysis
Codebase questions pollute desktop_job context or aren't available in Live mode.

## Proposed implementation
`research_codebase` tool: ripgrep + read_file readonly, returns `{paths, snippets, summary}`; no writes; fast model.

## Files to touch (Phase 2)
- `app/tools.py` or new `app/research.py`
- `gemini_live.py` declaration

## Test strategy
- `tests/test_agent.py` patterns
- Mock workspace fixtures

## Estimated complexity
**M**

## Phase 2 workstream hint
WS5 Browser & Web or WS2

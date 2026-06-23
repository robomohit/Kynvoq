# Lane A05: Verify Specialist

**Category:** specialists  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
SYNTHESIS recommendation #4; [`logs/08-complete-honesty-patterns.md`](../../subagent-storm/logs/08-complete-honesty-patterns.md).

## Current code paths
Partial: `tests/test_visual_verification.py` exists for agent; no Live post-launch verify hook.

## Gap analysis
Live claims success before window foreground / file exists / display value checked.

## Proposed implementation
New readonly specialist invoked after `launch` or short `desktop_job`: checks window title fuzzy match, process running, optional screenshot diff. Returns `{verified: bool, user_message}`. 2s budget.

## Files to touch (Phase 2)
- New `app/verify.py` or `app/widget/verify_specialist.py`
- `textbox_overlay.py` — post-task hook

## Test strategy
- Unit tests with mocked window list
- Phase 3: calculator result on screen

## Estimated complexity
**M**

## Phase 2 workstream hint
WS1 Launch & Registry (verify chain)

# Lane D01: `agent.py` Prompt Conflicts

**Category:** backoffice  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`backoffice/01-agent-py-prompt-review.md`](../../subagent-storm/backoffice/01-agent-py-prompt-review.md).

## Current code paths
- System prompt sections for computer vs coding vs browser
- Tool list in prompt may disagree with actual tools

## Gap analysis
Conflicting instructions cause wrong tool choice (web_search vs UIA).

## Proposed implementation
Audit prompt blocks; single source of truth from tool registry; remove duplicate LAUNCH guidance.

## Files to touch (Phase 2)
- `app/agent.py`

## Test strategy
- Snapshot prompt hash test

## Estimated complexity
**M**

## Phase 2 workstream hint
WS6

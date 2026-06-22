# Lane B08: Proactive Honest Speech

**Category:** reliability  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`logs/08-complete-honesty-patterns.md`](../../subagent-storm/logs/08-complete-honesty-patterns.md); Spotify postmortem.

## Current code paths
Live narrates "Opening…" before worker confirms; optimistic TTS.

## Gap analysis
User hears success while task failed in <300ms.

## Proposed implementation
Defer optimistic phrases until tool returns `ok:true`; use progressive updates via `send_task_update`; ban success templates in system prompt until verify passes.

## Files to touch (Phase 2)
- `gemini_live._default_system_instruction`
- `textbox_overlay` tool responses

## Test strategy
- Phase 3 Spotify scenario
- Label log: live_reply before task terminal

## Estimated complexity
**M**

## Phase 2 workstream hint
WS4

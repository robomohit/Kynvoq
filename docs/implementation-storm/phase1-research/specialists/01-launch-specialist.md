# Lane A01: Launch Specialist

**Category:** specialists  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
Builds on [`SYNTHESIS-subagents-vs-orynn.md`](../../subagent-storm/SYNTHESIS-subagents-vs-orynn.md) `launch` built-in; [`reliability/10-launch-registry-gaps.md`](../../subagent-storm/reliability/10-launch-registry-gaps.md); [`proposals/01-resolve-launch-target.md`](../../subagent-storm/proposals/01-resolve-launch-target.md).

## Current code paths
- `detect_app_launch_intent()` — `app/tools.py:471-488` — curated `_KNOWN_LAUNCH_APPS` exact match only.
- Fast-path routing in `textbox_overlay._live_start_desktop_task` checks launch intent before POST.
- Registry gaps: ~7 apps vs universal launch research.

## Gap analysis
Launch is implicit inside `start_desktop_task` / overlay routing, not a first-class Live specialist with its own contract, bubble labels, or verify pass. Spotify failures often never reach launch ladder.

## Proposed implementation
1. Add `specialists/launch` entry to registry (name, description, tools=`resolve_launch_target`, sync).
2. Live tool `launch_app` OR route `start_desktop_task` goals through launch specialist when `detect_app_launch_intent` + `resolve_launch_target` succeed.
3. Return `{ok, user_message, window_title}`; never raw shell errors.
4. Chain to `verify` specialist (foreground window title) before Live speaks success.

## Files to touch (Phase 2)
- `app/tools.py` — expand registry + `resolve_launch_target`
- `app/widget/textbox_overlay.py` — `_live_tool` dispatch
- `app/widget/gemini_live.py` — declaration + system prompt routing
- `Orynn/agents/launch.md` — declarative profile

## Test strategy
- `tests/test_fast_path.py`, `tests/test_desktop_launcher.py` — extend registry cases
- Golden: Spotify URI launch mock
- Phase 3: spoken "open Spotify" → foreground check

## Estimated complexity
**M**

## Phase 2 workstream hint
WS1 Launch & Registry

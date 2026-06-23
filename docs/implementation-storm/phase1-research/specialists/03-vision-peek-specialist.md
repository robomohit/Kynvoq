# Lane A03: Vision Peek Specialist

**Category:** specialists  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`reliability/08-vision-hallucination-patterns.md`](../../subagent-storm/reliability/08-vision-hallucination-patterns.md), tool contracts §2.4-2.6.

## Current code paths
- `look_at_screen`, `list_windows`, `capture_window` in `textbox_overlay._live_tool`
- Vision frame ordering: send video before `FunctionResponse` (`gemini_live`)
- Labels: "Looking at the screen" (`textbox_overlay.py:1278`)

## Gap analysis
No read-only guarantee in registry; model may chain desktop_control after peek. Hallucination patterns when frame stale or OCR skipped.

## Proposed implementation
Register `vision_peek` as readonly specialist: tools limited to look/list/capture; forbid write tools in same turn; add `frame_age_ms` in response; mid-tier OCR before full describe (see tools/07).

## Files to touch (Phase 2)
- `app/widget/textbox_overlay.py`
- `app/widget/gemini_live.py`
- `app/providers.py` — vision describe

## Test strategy
- `tests/test_gemini_live.py`
- `scripts/live_vision_smoke.py` for Phase 3

## Estimated complexity
**M**

## Phase 2 workstream hint
WS2 Live Front Desk & Specialists

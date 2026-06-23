# Lane C07: Live Mid-Tier OCR

**Category:** tools  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`proposals/04-live-mid-tier-ocr.md`](../../subagent-storm/proposals/04-live-mid-tier-ocr.md).

## Current code paths
Full vision describe for every peek; no OCR shortcut in Live path.

## Gap analysis
Slow + hallucination-prone for simple text reads.

## Proposed implementation
Add OCR pass in `look_at_screen` before vision model; return text if confidence > threshold.

## Files to touch (Phase 2)
- `textbox_overlay.py`
- `app/providers.py`

## Test strategy
- `tests/test_hybrid_resolver.py` patterns

## Estimated complexity
**M**

## Phase 2 workstream hint
WS2

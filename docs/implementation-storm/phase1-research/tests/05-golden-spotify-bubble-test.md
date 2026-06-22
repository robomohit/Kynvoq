# Lane G05: Golden Spotify Bubble Test

**Category:** tests  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
reliability/05-spotify-failure-postmortem.

## Current code paths
No golden file from label log.

## Gap analysis
Replay label sequence; assert mute + handoff.

## Proposed implementation
Fixture: `tests/fixtures/spotify_label_sequence.jsonl` + assertion helper.

## Files to touch (Phase 2)
- new golden test

## Test strategy
pytest

## Estimated complexity
**M**

## Phase 2 workstream hint
WS4 + WS1

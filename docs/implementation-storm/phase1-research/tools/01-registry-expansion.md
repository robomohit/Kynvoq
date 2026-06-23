# Lane C01: Launch Registry Expansion

**Category:** tools  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`reliability/10-launch-registry-gaps.md`](../../subagent-storm/reliability/10-launch-registry-gaps.md); [`windows-automation-research/03-universal-launch.md`](../../windows-automation-research/03-universal-launch.md).

## Current code paths
- `_KNOWN_LAUNCH_APPS` dict in `tools.py`
- 7 curated apps

## Gap analysis
Spotify, Settings, Edge, etc. miss exact-match registry.

## Proposed implementation
Expand to 50+ entries; alias map; fallback to `resolve_launch_target` for unknown names.

## Files to touch (Phase 2)
- `app/tools.py`
- `data/launch_registry.json` optional

## Test strategy
- `tests/test_desktop_launcher.py`

## Estimated complexity
**M**

## Phase 2 workstream hint
WS1

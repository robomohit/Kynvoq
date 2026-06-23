# Lane G07: Pytest Coverage Gap Master

**Category:** tests  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
storm tests/*.txt inventory.

## Current code paths
60 test files; P0 features partially covered.

## Gap analysis
Master map: feature → test file → gap → priority.

## Proposed implementation
| Feature | Tests | Gap |
| bubble mute | quiet_companion | sanitizer |
| abandon | task_abandon_grace | GET persist |
| launch | fast_path | URI |
| grid | grid_locate | sequence |
| live | gemini_live | specialist registry |

## Files to touch (Phase 2)
- INDEX in tests/

## Test strategy
Run storm pytest txt after Phase 2

## Estimated complexity
**S**

## Phase 2 workstream hint
All WS

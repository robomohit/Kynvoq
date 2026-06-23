# Lane A12: Declarative `Orynn/agents/*.md` Profiles

**Category:** specialists  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
SYNTHESIS § version-control specialists; Cursor agent files.

## Current code paths
No `Orynn/agents/` directory; prompts hardcoded in Python.

## Gap analysis
Specialist tuning requires code edits; no user-extensible profiles.

## Proposed implementation
Add `Orynn/agents/{launch,browser,desktop_job}.md` with YAML frontmatter (name, description, readonly, tools). Loader merges into registry at startup.

## Files to touch (Phase 2)
- New `Orynn/agents/`
- `app/specialists/loader.py`

## Test strategy
- Loader unit tests with fixture md files

## Estimated complexity
**S**

## Phase 2 workstream hint
WS2 Live Front Desk & Specialists

# Lane F06: Web Search Failure Forensics

**Category:** log-plan  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
logs/07-web-search-failures.

## Current code paths
web_search tool exit codes in debug log.

## Gap analysis
High fail rate (~75%) without failure taxonomy.

## Proposed implementation
Bucket failures: empty query, timeout, SSRF block, provider 4xx.

## Files to touch (Phase 2)
- logs + tasks; failure bucket script

## Test strategy
Web search failure histogram

## Estimated complexity
**S**

## Phase 2 workstream hint
Phase 4

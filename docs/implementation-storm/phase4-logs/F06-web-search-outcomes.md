# F06 — web_search Outcomes in Session

**Lane:** F06  
**Date:** 2026-06-22  
**Sources:** gate_results.json (web_search scenario), textbox_labels slice lines 77–80

---

## Phase 3 gate results

From `gate_results.json` lines 195–253:

| call | query | ok | sources | bubble labels |
|------|-------|-----|---------|---------------|
| 1 | who won the last Super Bowl | **true** | 5 URLs | L77–78 |
| 2 | who won Super Bowl LX | **true** | 4 URLs | L79–80 |

**Pass rate:** 2/2 (100%)

---

## Label sanitization (slice)

| Line | text | assessment |
|------|------|------------|
| 77 | Searching: who won the last Super Bowl | Clean query echo |
| 78 | Sources: topendsports.com, en.wikipedia.org, msn.com | Domain-only, no raw HTML |
| 79 | Searching: who won Super Bowl LX | Model refined query (stale snippet fix) |
| 80 | Sources: en.wikipedia.org, espn.com, cbc.ca | Clean |

**Denylist:** No `UNTRUSTED WEB CONTENT` in shown labels — sanitizer kept untrusted wrapper out of bubble.

---

## Snippet quality / staleness

Call 1 output (gate_results.json L213) includes ESPN line claiming Patriots won Super Bowl LIII (2019) — **stale** for "last Super Bowl" in 2026.

Call 2 (refined to Super Bowl LX) returns consistent Seahawks 29–13 result across Wikipedia, ESPN, CBC.

**Model behavior:** Self-corrected via second `web_search` — good routing, not a tool failure.

---

## Historical contrast (debug log)

From F02: historical `web_search` **75% fail** (6/8 `ok: false` in debug-eec63b.log lines 14, 39, etc.).

Phase 3 session shows **no regression** — improvement vs historical baseline.

---

## Gate harness gap

- `audio_bytes: 0` at turn_complete (L243) — spoken citation not captured before gate closed.
- Tool execution and bubble labels verified; final TTS out of scope for this lane.

---

## Findings

1. **web_search reliable in Phase 3** — 2/2 ok, sanitized bubbles.
2. First query returned mixed-era snippets; model refinement is acceptable behavior.
3. No SSRF/timeout failures in session.
4. Historical 75% fail rate not reproduced.

---

## Verdict (lane)

**PASS.** web_search exposed, executes, and labels cleanly in Phase 3 session.

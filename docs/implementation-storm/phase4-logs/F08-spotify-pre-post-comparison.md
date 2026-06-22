# F08 — Pre/Post Phase 2 Spotify Pattern Comparison

**Lane:** F08 (optional)  
**Date:** 2026-06-22  
**Artifact:** `textbox_labels_session_slice.jsonl`

---

## Sessions compared

| session | ts range | live | trigger |
|---------|----------|------|---------|
| Pre-fix Spotify (full overlay) | 1782151121 – 1782151148 | true | User voice "open Spotify" |
| Phase 3 gate (E03) | 1782159423.505 | false | Harness prompt |

**Time delta:** ~8300 s (~2.3 h) between sessions in same log file.

---

## Pre-fix pattern (lines 1–66)

1. **Lines 1–12:** Streaming `live_reply` — model asks permission before launching ("Would you like me to do that now?")
2. **Line 14:** User input `Hearing: Yeah, sure.`
3. **Lines 15–16:** Mutes (`live_status_under_hold`, `task_churn_under_live`)
4. **Line 17:** **LEAK** — `live_tool` shown: `Failed: Server restarted or task was abandoned.`
5. **Lines 19–29:** Retry speech ("Alright, trying again right now…")
6. **Line 31:** **LEAK** — same denylist string again
7. **Lines 33–65:** Further retries, no successful `Opening spotify` label

**Tool path (inferred):** `start_desktop_task` or abandon race — not `launch_app` specialist.

---

## Post-fix pattern (line 70)

```
{"ts": 1782159423.505, "action": "shown", "source": "live_tool", "reason": "", "live": false, "text": "Opening spotify"}
```

**gate_results.json E03:**
- Tool: `launch_app(app="Spotify")` — not `start_desktop_task`
- Result: `ok: true`, window `Spotify Free`
- Reply: "Got it, Spotify Free is open."
- `leaks: []`

---

## Side-by-side

| aspect | pre-fix (Jun 22 earlier) | Phase 3 (post WS1–WS4) |
|--------|--------------------------|-------------------------|
| routing | desktop task / retry loop | `launch_app` specialist |
| bubble on success | never reached | `Opening spotify` |
| bubble on failure | denylist leak ×2 | none |
| speech | permission + retry narration | immediate confirmation |
| audio | multi-turn retry | 104 KB single reply |

---

## Golden fixture alignment

`tests/fixtures/spotify_label_sequence.jsonl`:
- Line 2: `task_outcome_under_live` mute on Started
- Line 3: `bubble_sanitizer_denylist` mute on Failed string

Pre-fix log line 17 **lacks** the sanitizer mute — confirms fix was needed and applied in Phase 2.

---

## Findings

Phase 2 WS1 (`launch_app`) + WS4 (`sanitize_bubble_text`) transformed Spotify from a **leaking retry loop** to a **single-shot clean launch**. Regression not observed in Phase 3 slice.

---

## Verdict (lane)

**PASS.** Clear before/after improvement; Phase 3 E03 matches intended post-fix pattern.

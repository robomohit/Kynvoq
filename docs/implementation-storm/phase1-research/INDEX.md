# Phase 1 Research — Master Index

**Date:** 2026-06-22  
**Coordinator:** Phase 1 Research (builds on [`docs/subagent-storm/`](../subagent-storm/INDEX.md))  
**Mode:** Read-only research → implementation-ready briefs  
**Output:** 67 non-overlapping lanes → consolidated in [`PHASE2-BRIEF.md`](PHASE2-BRIEF.md) (8 workstreams)

---

## Summary

| Category | Lanes | Directory | Phase 2 workstream |
|----------|------:|-----------|-------------------|
| [A. Specialists](#a-specialists-17) | 17 | `specialists/` | WS2, WS1, WS3 |
| [B. P0 Reliability](#b-p0-reliability-11) | 11 | `reliability/` | WS3, WS4 |
| [C. Launch & Tools](#c-launch--tools-9) | 9 | `tools/` | WS1, WS6 |
| [D. Back Office](#d-back-office-9) | 9 | `backoffice/` | WS6, WS3 |
| [E. Live Test Plan](#e-live-test-plan-7) | 7 | `live-test-plan/` | Phase 3 |
| [F. Log Forensics Plan](#f-log-forensics-plan-7) | 7 | `log-plan/` | Phase 4 |
| [G. Test Matrix](#g-test-matrix-7) | 7 | `tests/` | All WS |

**Total lanes:** 67  
**Status:** All lanes `complete`

---

## A. Specialists (17)

Cursor/Antigravity-style built-in subagents for Orynn Live front desk.

| Lane | File | Focus | Complexity |
|------|------|-------|------------|
| A01 | [`specialists/01-launch-specialist.md`](specialists/01-launch-specialist.md) | Launch built-in (`detect_app_launch_intent`, registry) | M |
| A02 | [`specialists/02-uia-act-specialist.md`](specialists/02-uia-act-specialist.md) | `desktop_control` single-gesture specialist | S |
| A03 | [`specialists/03-vision-peek-specialist.md`](specialists/03-vision-peek-specialist.md) | `look_at_screen` / `capture_window` readonly peek | M |
| A04 | [`specialists/04-desktop-job-specialist.md`](specialists/04-desktop-job-specialist.md) | `start_desktop_task` full ReAct worker | L |
| A05 | [`specialists/05-verify-specialist.md`](specialists/05-verify-specialist.md) | Post-task verification subagent | M |
| A06 | [`specialists/06-browser-specialist.md`](specialists/06-browser-specialist.md) | Headless browser as Live built-in | L |
| A07 | [`specialists/07-research-specialist.md`](specialists/07-research-specialist.md) | Read-only codebase search | M |
| A08 | [`specialists/08-specialist-registry-architecture.md`](specialists/08-specialist-registry-architecture.md) | Declarative `SpecialistSpec` registry | M |
| A09 | [`specialists/09-specialist-routing-gemini-live.md`](specialists/09-specialist-routing-gemini-live.md) | Live routing + mutual exclusion | M |
| A10 | [`specialists/10-specialist-bubble-policy.md`](specialists/10-specialist-bubble-policy.md) | Per-specialist bubble policy | S |
| A11 | [`specialists/11-specialist-background-foreground-modes.md`](specialists/11-specialist-background-foreground-modes.md) | Sync vs async specialist modes | M |
| A12 | [`specialists/12-specialist-declarative-agents-md.md`](specialists/12-specialist-declarative-agents-md.md) | `Orynn/agents/*.md` profiles | S |
| A13 | [`specialists/13-specialist-handoff-schema.md`](specialists/13-specialist-handoff-schema.md) | `{user_message, status, debug}` schema | M |
| A14 | [`specialists/14-specialist-mutual-exclusion.md`](specialists/14-specialist-mutual-exclusion.md) | One specialist per turn / exclusion groups | S |
| A15 | [`specialists/15-specialist-model-selection.md`](specialists/15-specialist-model-selection.md) | Fast vs full model per specialist | M |
| A16 | [`specialists/16-specialist-resume-idle-worker.md`](specialists/16-specialist-resume-idle-worker.md) | Resume task by ID (P2) | L |
| A17 | [`specialists/17-specialist-orchestrator-verifier-chain.md`](specialists/17-specialist-orchestrator-verifier-chain.md) | Launch → verify → narrate chain | M |

---

## B. P0 Reliability (11)

Implementation specs for front-desk trust failures (Spotify bubble leak, abandon race, double routing).

| Lane | File | Focus | Complexity |
|------|------|-------|------------|
| B01 | [`reliability/01-bubble-sanitization.md`](reliability/01-bubble-sanitization.md) | Central bubble text sanitizer | S |
| B02 | [`reliability/02-task-outcome-muting.md`](reliability/02-task-outcome-muting.md) | Mute `task_result` under Live | S |
| B03 | [`reliability/03-structured-handoff.md`](reliability/03-structured-handoff.md) | Worker → Live handoff contract | M |
| B04 | [`reliability/04-double-routing-enforcement.md`](reliability/04-double-routing-enforcement.md) | `desktop_control` + `start_desktop_task` gate | M |
| B05 | [`reliability/05-abandon-race-main-py.md`](reliability/05-abandon-race-main-py.md) | `_serialize_task_record` grace window | M |
| B06 | [`reliability/06-send-task-update.md`](reliability/06-send-task-update.md) | Proactive speech on task terminal | S |
| B07 | [`reliability/07-busy-gate-stale-flag.md`](reliability/07-busy-gate-stale-flag.md) | `_desktop_busy` stale flag cleanup | S |
| B08 | [`reliability/08-proactive-honest-speech.md`](reliability/08-proactive-honest-speech.md) | No optimistic success before verify | M |
| B09 | [`reliability/09-user-goal-vs-prompt-goal.md`](reliability/09-user-goal-vs-prompt-goal.md) | Split user speech vs agent prompt | S |
| B10 | [`reliability/10-reason-sanitization.md`](reliability/10-reason-sanitization.md) | Humanize `record.reason` | S |
| B11 | [`reliability/11-go-away-reconnect-handling.md`](reliability/11-go-away-reconnect-handling.md) | Live reconnect + pending outcomes (P2) | M |

---

## C. Launch & Tools (9)

Registry, resolver ladder, UIA cache, playbooks, web search, OCR, window wait.

| Lane | File | Focus | Complexity |
|------|------|-------|------------|
| C01 | [`tools/01-registry-expansion.md`](tools/01-registry-expansion.md) | Expand `_KNOWN_LAUNCH_APPS` | M |
| C02 | [`tools/02-resolve-launch-target.md`](tools/02-resolve-launch-target.md) | URI/shell/start ladder | L |
| C03 | [`tools/03-open-settings-tool.md`](tools/03-open-settings-tool.md) | `ms-settings:` panes | S |
| C04 | [`tools/04-uia-cache-mvp.md`](tools/04-uia-cache-mvp.md) | HWND-keyed UIA cache TTL | M |
| C05 | [`tools/05-playbook-wiring.md`](tools/05-playbook-wiring.md) | Auto-select adaptive playbooks | M |
| C06 | [`tools/06-web-search-fix.md`](tools/06-web-search-fix.md) | Fix ~75% Live web_search fail | M |
| C07 | [`tools/07-ocr-mid-tier-live.md`](tools/07-ocr-mid-tier-live.md) | OCR before vision describe | M |
| C08 | [`tools/08-wait-for-window-fuzzy-match.md`](tools/08-wait-for-window-fuzzy-match.md) | Fuzzy window title match | S |
| C09 | [`tools/09-detect-app-launch-intent.md`](tools/09-detect-app-launch-intent.md) | Harden launch intent detect | S |

---

## D. Back Office (9)

Agent prompt, UIA sequence, history, done validation, payloads, playbooks, electron guard.

| Lane | File | Focus | Complexity |
|------|------|-------|------------|
| D01 | [`backoffice/01-agent-py-prompt-conflict.md`](backoffice/01-agent-py-prompt-conflict.md) | Resolve prompt/tool conflicts | M |
| D02 | [`backoffice/02-uia-sequence-grid-integration.md`](backoffice/02-uia-sequence-grid-integration.md) | Sequence + grid fallback | M |
| D03 | [`backoffice/03-history-persistence.md`](backoffice/03-history-persistence.md) | Persist agent action log | M |
| D04 | [`backoffice/04-done-validation.md`](backoffice/04-done-validation.md) | Anti false-complete | M |
| D05 | [`backoffice/05-build-task-payload.md`](backoffice/05-build-task-payload.md) | Unified task payload builder | S |
| D06 | [`backoffice/06-adaptive-playbooks-happy-path.md`](backoffice/06-adaptive-playbooks-happy-path.md) | Calculator etc. happy paths | M |
| D07 | [`backoffice/07-electron-unlock-guard.md`](backoffice/07-electron-unlock-guard.md) | Defer unlock during tasks | S |
| D08 | [`backoffice/08-main-task-lifecycle.md`](backoffice/08-main-task-lifecycle.md) | Task state machine cleanup | L |
| D09 | [`backoffice/09-desktop-control-route.md`](backoffice/09-desktop-control-route.md) | Fast-path route telemetry | S |

---

## E. Live Test Plan (7)

Phase 3 scripts, env vars, success criteria (1–2 sequential Live agents).

| Lane | File | Focus |
|------|------|-------|
| E01 | [`live-test-plan/01-browser-agent-scenarios.md`](live-test-plan/01-browser-agent-scenarios.md) | Browser Live scenarios |
| E02 | [`live-test-plan/02-gemini-live-complex-tasks.md`](live-test-plan/02-gemini-live-complex-tasks.md) | Multi-app complex matrix |
| E03 | [`live-test-plan/03-spotify-style-launch.md`](live-test-plan/03-spotify-style-launch.md) | **P0** Spotify regression gate |
| E04 | [`live-test-plan/04-calculator-e2e.md`](live-test-plan/04-calculator-e2e.md) | Calculator golden path |
| E05 | [`live-test-plan/05-vision-peek-scenarios.md`](live-test-plan/05-vision-peek-scenarios.md) | Vision readonly scenarios |
| E06 | [`live-test-plan/06-live-harness-env-setup.md`](live-test-plan/06-live-harness-env-setup.md) | `ORYNN_LABEL_LOG`, env bundle |
| E07 | [`live-test-plan/07-load-test-matrix-phase3.md`](live-test-plan/07-load-test-matrix-phase3.md) | 10-run stress matrix |

---

## F. Log Forensics Plan (7)

Phase 4 checklists for post-live-test log review (5–10 forensics agents).

| Lane | File | Focus |
|------|------|-------|
| F01 | [`log-plan/01-textbox-labels-jsonl-patterns.md`](log-plan/01-textbox-labels-jsonl-patterns.md) | Label stream patterns |
| F02 | [`log-plan/02-debug-log-slices.md`](log-plan/02-debug-log-slices.md) | NDJSON tool-mix slices |
| F03 | [`log-plan/03-task-json-correlation.md`](log-plan/03-task-json-correlation.md) | task_id join |
| F04 | [`log-plan/04-silent-turns-forensics.md`](log-plan/04-silent-turns-forensics.md) | Silent turn detection |
| F05 | [`log-plan/05-duplicate-routing-forensics.md`](log-plan/05-duplicate-routing-forensics.md) | Duplicate spawn analysis |
| F06 | [`log-plan/06-web-search-failure-forensics.md`](log-plan/06-web-search-failure-forensics.md) | Web search failure buckets |
| F07 | [`log-plan/07-log-forensics-master-checklist.md`](log-plan/07-log-forensics-master-checklist.md) | **Phase 4 master checklist** |

---

## G. Test Matrix (7)

Map P0/specialist features → existing pytest + gaps.

| Lane | File | Focus |
|------|------|-------|
| G01 | [`tests/01-bubble-sanitization-test-map.md`](tests/01-bubble-sanitization-test-map.md) | Bubble sanitizer tests |
| G02 | [`tests/02-double-routing-test-map.md`](tests/02-double-routing-test-map.md) | Dual-tool batch tests |
| G03 | [`tests/03-specialist-routing-test-map.md`](tests/03-specialist-routing-test-map.md) | Registry routing tests |
| G04 | [`tests/04-launch-registry-test-map.md`](tests/04-launch-registry-test-map.md) | Launch parametrized tests |
| G05 | [`tests/05-golden-spotify-bubble-test.md`](tests/05-golden-spotify-bubble-test.md) | Spotify label golden |
| G06 | [`tests/06-abandon-race-test-map.md`](tests/06-abandon-race-test-map.md) | Abandon grace tests |
| G07 | [`tests/07-pytest-coverage-gap-master.md`](tests/07-pytest-coverage-gap-master.md) | **Master coverage map** |

---

## Phase handoff

| Phase | Owner | Entry doc |
|-------|-------|-----------|
| **2 Implementation** | 5–10 subagents | [`PHASE2-BRIEF.md`](PHASE2-BRIEF.md) |
| **3 Live testing** | 1–2 sequential agents | `live-test-plan/` + [`LOAD-TEST-PLAN.md`](../subagent-storm/LOAD-TEST-PLAN.md) |
| **4 Log forensics** | 5–10 agents | `log-plan/07-log-forensics-master-checklist.md` |

---

## Anti-collision rules (Phase 1)

1. One markdown file per lane — no shared output paths  
2. Build on storm #1 — cite storm docs, add implementation detail (no verbatim dump)  
3. No `app/` code edits, no commits, no live Gemini sessions  
4. Lane briefs are inputs only; implementation ownership is in `PHASE2-BRIEF.md`

---

## Related

- [Storm #1 INDEX](../subagent-storm/INDEX.md)
- [Subagents vs Orynn synthesis](../subagent-storm/SYNTHESIS-subagents-vs-orynn.md)
- [Windows automation research](../windows-automation-research/INDEX.md)

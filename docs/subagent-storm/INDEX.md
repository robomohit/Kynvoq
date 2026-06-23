# Subagent Storm — Master Index

**Date:** 2026-06-22  
**Scope:** 50 parallel, non-overlapping read-only workstreams launched to stress-test ideas, audit the back office, forensically analyze logs, benchmark competitors, and draft implementation proposals — without concurrent Live/desktop control or app code edits.

Each workstream owns exactly one output path. Lanes are isolated so agents do not step on each other or on in-flight task-spawn fixes.

---

## Lane summary

| Lane | Count | Mode | Output root |
|------|-------|------|-------------|
| [Competitors](#competitors) | 8 | Read-only research | `competitors/` |
| [Reliability](#reliability) | 10 | Read-only analysis + proposed fixes | `reliability/` |
| [Back office](#backoffice) | 10 | Read-only code review | `backoffice/` |
| [Log forensics](#logs) | 10 | Read-only log/task mining | `logs/` |
| [Proposals](#proposals) | 7 | Design docs only (no code) | `proposals/` |
| [Tests](#tests) | 3 | Isolated pytest (no Orynn desktop) | `tests/` |
| [Synthesis](#synthesis) | 2 | Cross-cutting docs | see below |

**Total:** 50 workstreams

---

## Competitors

Landscape research comparing Orynn’s voice-native, UIA-first, local Windows stack to adjacent products.

| # | File | Description |
|---|------|-------------|
| 01 | [`competitors/01-clicky.md`](competitors/01-clicky.md) | Clicky macOS companion vs Orynn — voice, overlay, task delegation, and platform differences. |
| 02 | [`competitors/02-anthropic-computer-use.md`](competitors/02-anthropic-computer-use.md) | Anthropic Computer Use (screenshot + coordinate actions) vs Orynn’s semantic UIA ladder. |
| 03 | [`competitors/03-openai-operator.md`](competitors/03-openai-operator.md) | OpenAI Operator / ChatGPT Agent / CUA lineage — cloud browser agent vs local desktop operator. |
| 04 | [`competitors/04-microsoft-power-automate.md`](competitors/04-microsoft-power-automate.md) | Power Automate Desktop — deterministic RPA flows vs Orynn’s LLM-planned agent loop. |
| 05 | [`competitors/05-open-interpreter.md`](competitors/05-open-interpreter.md) | Open Interpreter — terminal/code-first local agent vs Orynn’s GUI automation focus. |
| 06 | [`competitors/06-google-gemini-live-native.md`](competitors/06-google-gemini-live-native.md) | Google Gemini Live as a standalone product vs Orynn’s Live front desk + back-office split. |
| 07 | [`competitors/07-multion-simular-adept.md`](competitors/07-multion-simular-adept.md) | MultiOn, Simular, Adept — web/browser agent startups and where Orynn differentiates on Windows native. |
| 08 | [`competitors/08-devin-swe-agents.md`](competitors/08-devin-swe-agents.md) | Devin and SWE-agent landscape — long-horizon coding agents vs general desktop automation. |

---

## Reliability

Failure-mode analysis from production logs, task JSON, and overlay behavior. Proposes fixes in prose only — no code edits in this storm.

| # | File | Description |
|---|------|-------------|
| 01 | [`reliability/01-task-abandon-race.md`](reliability/01-task-abandon-race.md) | “Server restarted” task abandon race between overlay poll and backend lifecycle. |
| 02 | [`reliability/02-double-routing-live.md`](reliability/02-double-routing-live.md) | Live calling both `desktop_control` and `start_desktop_task` for the same user intent. |
| 03 | [`reliability/03-bubble-leak-regression.md`](reliability/03-bubble-leak-regression.md) | Companion bubble label leak / stale UI state after recent textbox_overlay fixes. |
| 04 | [`reliability/04-proactive-speech-gaps.md`](reliability/04-proactive-speech-gaps.md) | Gaps in `send_task_update` — when the back office finishes but Live stays silent. |
| 05 | [`reliability/05-spotify-failure-postmortem.md`](reliability/05-spotify-failure-postmortem.md) | Postmortem on Spotify-related task failures (`clicky-c6beede9be` and similar). |
| 06 | [`reliability/06-busy-gate-stale-flag.md`](reliability/06-busy-gate-stale-flag.md) | `_desktop_busy` stale flag blocking fast-path clicks after task completion or crash. |
| 07 | [`reliability/07-go-away-reconnect-storm.md`](reliability/07-go-away-reconnect-storm.md) | `go_away` reconnect storms in `debug-eec63b.log` — session churn under load. |
| 08 | [`reliability/08-vision-hallucination-patterns.md`](reliability/08-vision-hallucination-patterns.md) | Vision / `look_at_screen` hallucination patterns in Live session logs. |
| 09 | [`reliability/09-electron-unlock-disruption.md`](reliability/09-electron-unlock-disruption.md) | `electron_unlock` relaunch disrupting in-flight back-office tasks. |
| 10 | [`reliability/10-launch-registry-gaps.md`](reliability/10-launch-registry-gaps.md) | Launch registry coverage gaps vs `docs/windows-automation-research/03-universal-launch.md`. |

---

## Backoffice

Read-only audits of the full desktop agent stack — prompts, tools, routing, payloads, and safety.

| # | File | Description |
|---|------|-------------|
| 01 | [`backoffice/01-agent-py-prompt-review.md`](backoffice/01-agent-py-prompt-review.md) | `agent.py` system prompt, planning loop, and tool-selection guidance review. |
| 02 | [`backoffice/02-tools-uia-click-review.md`](backoffice/02-tools-uia-click-review.md) | `tools.py` `uia_click` four-tier resolver ladder (UIA → OCR → vision grid → pixel). |
| 03 | [`backoffice/03-tools-uia-sequence-review.md`](backoffice/03-tools-uia-sequence-review.md) | `uia_click_sequence` multi-step click orchestration and failure propagation. |
| 04 | [`backoffice/04-main-task-lifecycle-review.md`](backoffice/04-main-task-lifecycle-review.md) | `main.py` task lifecycle — spawn, poll, serialize, abandon, and terminal states. |
| 05 | [`backoffice/05-grid-locate-improvements.md`](backoffice/05-grid-locate-improvements.md) | `grid_locate.py` vision grid click accuracy and tuning opportunities. |
| 06 | [`backoffice/06-adaptive-windows-playbooks.md`](backoffice/06-adaptive-windows-playbooks.md) | `adaptive_windows.py` per-app playbooks — coverage, wiring, and escalation paths. |
| 07 | [`backoffice/07-gemini-live-tool-contracts.md`](backoffice/07-gemini-live-tool-contracts.md) | `gemini_live.py` function declarations, timeouts, and tool response contracts. |
| 08 | [`backoffice/08-desktop-control-route-review.md`](backoffice/08-desktop-control-route-review.md) | `textbox_overlay.py` fast-path `desktop_control` routing vs escalation to full agent. |
| 09 | [`backoffice/09-task-payload-build-review.md`](backoffice/09-task-payload-build-review.md) | `_build_task_payload` / `build_task_payload` — goal shaping, IDs, and metadata passed to backend. |
| 10 | [`backoffice/10-safety-manager-review.md`](backoffice/10-safety-manager-review.md) | `safety_manager.py` consent gates, destructive-verb detection, and bypass paths. |

---

## Logs

Forensic mining of `debug-eec63b.log`, `tasks/*.json`, and `logs/textbox_labels.jsonl` — each agent owns a distinct pattern.

| # | File | Description |
|---|------|-------------|
| 01 | [`logs/01-debug-tool-mix.md`](logs/01-debug-tool-mix.md) | Tool-call mix in `debug-eec63b.log` — `desktop_control` vs `start_desktop_task` ratios. |
| 02 | [`logs/02-silent-turns-pattern.md`](logs/02-silent-turns-pattern.md) | Silent Live turns (model receives tool result but produces no spoken reply). |
| 03 | [`logs/03-failed-wait-for-window.md`](logs/03-failed-wait-for-window.md) | Tasks failing on `wait_for_window` — timeout and title-mismatch patterns. |
| 04 | [`logs/04-ultra-short-tasks.md`](logs/04-ultra-short-tasks.md) | Ultra-short tasks (≤6 action lines) — fast bail vs false-complete signals. |
| 05 | [`logs/05-textbox-labels-live-session.md`](logs/05-textbox-labels-live-session.md) | Jun 22 Live session label stream in `logs/textbox_labels.jsonl`. |
| 06 | [`logs/06-duplicate-start-desktop-task.md`](logs/06-duplicate-start-desktop-task.md) | Duplicate `start_desktop_task` spawns for a single spoken goal. |
| 07 | [`logs/07-web-search-failures.md`](logs/07-web-search-failures.md) | `web_search` tool failures across logs and task artifacts. |
| 08 | [`logs/08-complete-honesty-patterns.md`](logs/08-complete-honesty-patterns.md) | `complete: true` vs `complete: false` honesty — premature success claims. |
| 09 | [`logs/09-calculator-e2e-success.md`](logs/09-calculator-e2e-success.md) | Calculator e2e wins (`clicky-f65730807f` etc.) — what made them succeed. |
| 10 | [`logs/10-cursor-electron-task-patterns.md`](logs/10-cursor-electron-task-patterns.md) | Cursor / Electron app task patterns — unlock, focus, and click sequences. |

---

## Proposals

Implementation proposals derived from storm findings and `docs/windows-automation-research/`. **No app code edits** — docs only.

| # | File | Description |
|---|------|-------------|
| 01 | [`proposals/01-resolve-launch-target.md`](proposals/01-resolve-launch-target.md) | Universal launch resolver from `03-universal-launch.md` — URI, shell, and `start` ladder. |
| 02 | [`proposals/02-uia-tree-cache.md`](proposals/02-uia-tree-cache.md) | UIA tree cache to cut repeated full-tree walks on hot paths. |
| 03 | [`proposals/03-open-settings-tool.md`](proposals/03-open-settings-tool.md) | `open_settings` tool using `ms-settings:` URIs for Windows Settings panes. |
| 04 | [`proposals/04-live-mid-tier-ocr.md`](proposals/04-live-mid-tier-ocr.md) | Live orchestrator mid-tier OCR peek before escalating to full back-office agent. |
| 05 | [`proposals/05-task-spawn-fix.md`](proposals/05-task-spawn-fix.md) | Task abandon / spawn race fix design (doc only — code owned elsewhere). |
| 06 | [`proposals/06-playbook-wiring.md`](proposals/06-playbook-wiring.md) | Wire `adaptive_windows` playbooks into agent tool selection automatically. |
| 07 | [`proposals/07-playwright-connectors.md`](proposals/07-playwright-connectors.md) | Playwright-based web connectors for sites that resist UIA/pixel control. |

---

## Tests

Isolated pytest runs — **no Orynn desktop app launched**, no Live session opened.

| # | File | Description |
|---|------|-------------|
| 01 | [`tests/01-gemini-live-pytest.txt`](tests/01-gemini-live-pytest.txt) | `pytest tests/test_gemini_live.py` — offline Live bridge, routing, and tool contracts. |
| 02 | [`tests/02-grid-hybrid-pytest.txt`](tests/02-grid-hybrid-pytest.txt) | `pytest tests/test_grid_locate.py tests/test_hybrid_resolver.py` — vision grid + hybrid resolver. |
| 03 | [`tests/03-adaptive-fast-pytest.txt`](tests/03-adaptive-fast-pytest.txt) | `pytest tests/test_adaptive_windows.py tests/test_fast_path.py` — playbooks + fast-path routing. |

---

## Synthesis

Cross-cutting deliverables outside the six primary lanes (included in the 50-workstream total).

| # | File | Description |
|---|------|-------------|
| 49 | [`../windows-automation-research/09-orynn-codebase-audit.md`](../windows-automation-research/09-orynn-codebase-audit.md) | Full `app/` codebase audit cross-referenced to existing automation research INDEX. |
| 50 | [`INDEX.md`](INDEX.md) + [`LOAD-TEST-PLAN.md`](LOAD-TEST-PLAN.md) | This index and the safe Gemini Live stress-test playbook. |

---

## Anti-collision rules

These constraints were baked into every storm agent prompt:

1. **No concurrent Live** — at most one Gemini Live session; no parallel voice/tool drivers.
2. **No overlapping desktop tasks** — sequential task execution only; one active `start_desktop_task` at a time.
3. **No app code edits** — reliability and back-office lanes are read-only; proposals are docs only.
4. **One output path per agent** — no two agents write the same file or analyze the same log slice.
5. **No Orynn desktop launch in test lane** — pytest only, offline mocks.

For manual Live pressure testing after the storm, see **[LOAD-TEST-PLAN.md](LOAD-TEST-PLAN.md)**.

---

## Related docs

- [Subagents vs Orynn (Cursor / Antigravity synthesis)](SYNTHESIS-subagents-vs-orynn.md) — front desk + back office mapped to parent/worker subagent models; built-in specialists (browser, research, etc.)
- [Windows automation research INDEX](../windows-automation-research/INDEX.md)
- [PROJECT.md](../../PROJECT.md) — entry points (`run_desktop.py`, `app/main.py`)
- Offline Live tests: `tests/test_gemini_live.py`
- Live smoke (manual): `scripts/live_tool_smoke.py`, `scripts/live_qa_matrix.py`

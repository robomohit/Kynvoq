# Orynn Codebase Audit — Windows Automation Implementation

**Date:** 2026-06-22  
**Scope:** Read-only audit of `Orynn/app/` against the Windows automation research corpus  
**Audience:** Engineering — implementation status, gaps, and next steps  
**Cross-ref:** [INDEX.md](./INDEX.md) · [00-master-strategy.md](./00-master-strategy.md) · [Methods deep dive](../windows-automation-research.md)

---

## Executive Summary

Orynn's Windows automation stack is **substantially built** and aligns with the research architecture: **Gemini Live front desk** + **UIA-first back-office agent**, three-layer model (launch → navigate → act), and a resolver ladder (UIA → OCR → grid-locate). The heaviest implementation lives in four modules totaling ~14k lines: `tools.py` (4,531), `agent.py` (3,563), `textbox_overlay.py` (3,361), and `desktop_features.py` (2,578).

**Strengths today**

- Full UIA tool surface (`uia_find/click/type/wait/sequence`) with short-TTL caches
- Live fast-path routing (`desktop_control` → UIA-only → auto-escalate to agent)
- Adaptive observe + lazy playbooks (`adaptive_windows.py`, `adaptive_windows_profiles.json`)
- Electron detect/unlock with rich-tree skip
- Windows Media OCR + vision grid-locate (agent-only fallback)
- Voice launch fast-path for 7 curated apps (`detect_app_launch_intent`)
- Workflows + knowledge memory wired into Live

**Top gaps vs research P0 roadmap**

| Gap | Research ref | Code evidence |
|-----|--------------|---------------|
| Narrow launch registry (7 apps) | [03-universal-launch.md §9–10](./03-universal-launch.md#9-orynn-implementation--current-state) | `_KNOWN_LAUNCH_APPS` in `tools.py:447–457` |
| No `open_settings` / `launch_aumid` tools | [02-uris-protocols-shell.md](./02-uris-protocols-shell.md), [00 §8 P0](./00-master-strategy.md#8-implementation-roadmap-prioritized) | Not in `ActionType` or `ToolExecutor` |
| No session `Get-StartApps` / `.lnk` index | [03 §6–7](./03-universal-launch.md#6-discovery-apis-whereexe-get-startapps-winget-list) | `resolve_app_exe` is running-process only |
| `learned_resolvers()` not wired into click ladder | [00 §4.3, §8 P0](./00-master-strategy.md#43-lazy-playbooks-adaptive_windows_profilesjson) | Used in `analyze_windows_failure` text only; **zero** imports in `tools.py` |
| Electron relaunch does not kill old instance | [06-electron-chromium.md](./06-electron-chromium.md), `relaunch_with_accessibility` docstring | `desktop_features.py:1191–1213` |
| Connectors default to `computer_use` not Playwright | [00 §4.4](./00-master-strategy.md#44-connector-skills) | `connectors.py` — all browser connectors |
| No COM Office path | [07-app-framework-taxonomy.md](./07-app-framework-taxonomy.md) | No `win32com` Office automation beyond WScript.Shell |
| Handoff envelope incomplete on escalation | [00 §8 P0 #5](./00-master-strategy.md#8-implementation-roadmap-prioritized) | `build_task_payload` injects memory but not `failure_class` / `electron_hint` |

---

## 1. Research Corpus Cross-Reference

### 1.1 Documents in `windows-automation-research/`

| Doc | Topic | Code areas validated |
|-----|-------|---------------------|
| [00-master-strategy.md](./00-master-strategy.md) | Architecture, decision tree, anti-patterns, roadmap | Live routing, agent prompts, enforcement — **mostly implemented** |
| [01-uia-deep-dive.md](./01-uia-deep-dive.md) | UIA architecture, Python stacks, caching | `desktop_features.py`, `tools.py` — **partial** (no CacheRequest batch) |
| [02-uris-protocols-shell.md](./02-uris-protocols-shell.md) | ms-settings, shell:, AUMID | Only via `run_command start` + 1 settings alias in registry |
| [03-universal-launch.md](./03-universal-launch.md) | Launch tiers, discovery APIs | Fast-path + agent `open_known_app` — **tier 0 only** |
| [04-vision-ocr-pixel.md](./04-vision-ocr-pixel.md) | OCR, grid, pixel fallback | `win_ocr_words`, `_ocr_click_fallback`, `grid_locate.py` — **implemented** |
| [05-keyboard-input.md](./05-keyboard-input.md) | SendInput, shortcuts | `keyboard_type`, `key_combo`, Live blocked combos |
| [06-electron-chromium.md](./06-electron-chromium.md) | Electron unlock | `electron_check/unlock`, `relaunch_with_accessibility` — **partial** |
| [07-app-framework-taxonomy.md](./07-app-framework-taxonomy.md) | App-class routing | Implicit in agent prompts; **not a structured routing table** |
| [08-powershell-system-no-ui.md](./08-powershell-system-no-ui.md) | WMI/CIM, no-UI system state | Via `run_terminal` / agent shell — **no dedicated tools** |

**INDEX gap:** [INDEX.md](./INDEX.md) lists 00, 02–03, 05–08 but omits **01-uia-deep-dive.md** and **04-vision-ocr-pixel.md** from its documents table. This audit doc should be added as **09** when INDEX is next updated.

### 1.2 Parent `docs/` references

| Doc | Audit finding |
|-----|---------------|
| [windows-automation-research.md](../windows-automation-research.md) §5 "What Orynn Already Has" | Still accurate; gap table matches code |
| [BENCHMARKS.md](../BENCHMARKS.md) | Referenced in roadmap; no automated benchmark runner in `app/` |
| [ROADMAP.md](../ROADMAP.md) | P0 items align with gaps below |

---

## 2. Module Map (`app/`)

```
app/
├── main.py                 FastAPI server, task queue, lifespan hooks
├── agent.py                Back-office planner loop, desktop evidence gates
├── tools.py                ToolExecutor — UIA, launch, OCR, grid, shell
├── adaptive_windows.py     Failure classification, lazy playbooks, runtime plans
├── grid_locate.py          Vision Set-of-Mark fallback (agent-only)
├── connectors.py           SaaS task templates + linked-state registry
├── workflows.py            Named multi-step procedures (Live run_workflow)
├── knowledge.py            ORYNN MEMORY facts (injected into tasks + Live)
├── memory.py               Long-term memory store (agent)
├── background_browser.py   Playwright Chromium (exists; underused by connectors)
├── automation.py           Cron triggers (Watch & Act — separate from desktop UIA)
├── desktop_bridge.py       Capsule ↔ overlay geometry
├── widget/
│   ├── textbox_overlay.py  Live orchestration, task bridge, desktop_control route
│   ├── gemini_live.py      Gemini Live session, tool declarations, batch policy
│   ├── desktop_features.py Low-level UIA, OCR, window mgmt, Electron relaunch
│   └── virtual_cursor.py   Clicky-style cursor animation (visual only)
└── models.py               ActionType enum (UIA, desktop, browser, …)
```

**State files (workspace root, not in `app/`):**

| File | Purpose |
|------|---------|
| `adaptive_windows_profiles.json` | Lazy playbook history (e.g. Notepad → `ocr_text_target`, 264 successes) |
| `workflows/workflows.json` | Saved procedures |
| `connectors.json` | Linked connector credentials/flags |
| `tasks/clicky-*.json` | Task records from Live escalation |

---

## 3. Architecture Alignment

### 3.1 Two-tier orchestra — verified in code

| Tier | Primary files | Research § |
|------|---------------|------------|
| **Front desk (Live)** | `gemini_live.py`, `textbox_overlay.py` | [00 §1.1](./00-master-strategy.md#11-front-desk-vs-back-office--hard-boundaries) |
| **Back office (agent)** | `agent.py`, `tools.py` | Same |

**Live enforcement (implemented):**

- One desktop tool per batch: `gemini_live.py:852–871` — rejects second `desktop_control` / `start_desktop_task`
- Test: `tests/test_gemini_live.py` (~line 530) — `"only one desktop action"` message
- Fast UIA only on Live: `textbox_overlay._run_live_desktop_action(..., fast_invoke_only=True)` passes `allow_pixel_fallback=False` to `uia_click` / `uia_type`
- Grid never on Live: `grid_locate.py:9–12` documents agent-only scope; Live path cannot reach it

**Escalation ladder (implemented):**

```
desktop_control (UIA-only)
  → miss → start_desktop_task (agent)
  → agent: adaptive_observe → uia_* → electron_unlock → OCR → grid_locate
```

Routing lives in `textbox_overlay._desktop_control_route` (lines ~1761–1849).

### 3.2 Three-layer model — code mapping

| Layer | Implemented methods | Location |
|-------|---------------------|----------|
| **Launch** | `detect_app_launch_intent`, `open_known_app`, `run_command start`, `build_task_payload` fast-path | `tools.py`, `agent.py:1754–1779`, `textbox_overlay.py:539–573` |
| **Navigate** | `focus_window`, `wait_for_window`, `key_combo`, UIA nav clicks, URI deep links (manual via shell) | `tools.py`, `desktop_features.py` |
| **Act** | `uia_click/type`, `keyboard_type`, OCR click, grid-locate, pyautogui retry | `tools.py`, `desktop_features.py` |

**Launch layer gap:** Research recommends ~20+ registry entries and session discovery index ([03 §10.2](./03-universal-launch.md#102-expand-_known_launch_apps-recommended-p0)). Code has **7** logical apps in `_KNOWN_LAUNCH_APPS` (notepad, calc, paint, wordpad, settings, task manager).

### 3.3 Memory systems — three layers confirmed

| System | Module | Live tools | Agent |
|--------|--------|------------|-------|
| **ORYNN MEMORY** (facts) | `knowledge.py` | `remember`, `forget` | Injected via `knowledge.as_prompt_block` in task payload |
| **ORYNN WORKFLOWS** (procedures) | `workflows.py` | `save_workflow`, `run_workflow`, `forget_workflow` | N/A (Live executes steps) |
| **Lazy playbooks** (resolver memory) | `adaptive_windows.py` | Not directly exposed | `remember_resolver_outcome` on success; recovery text on failure |

Workflow step vocabulary (`open`, `click`, `type`, `press_keys`, `scroll`, `focus`, `wait`, `run`) maps to verified Live paths in `textbox_overlay._run_workflow_step`.

---

## 4. Tool & Action Inventory

### 4.1 Desktop control plane (`ToolExecutor` + `desktop_features`)

| Tool / primitive | File | Live? | Agent? | Research doc |
|------------------|------|-------|--------|--------------|
| `uia_find` | `tools.py:2986+` | via `desktop_control observe/find` | ✅ | [01](./01-uia-deep-dive.md) |
| `uia_click` | `tools.py:3904+` | ✅ UIA-only | ✅ + OCR + grid | [01](./01-uia-deep-dive.md), [04](./04-vision-ocr-pixel.md) |
| `uia_click_sequence` | `tools.py:3793+` | ❌ | ✅ | [01](./01-uia-deep-dive.md) |
| `uia_type` | `tools.py:3999+` | ✅ UIA-only | ✅ + fallbacks | [05](./05-keyboard-input.md) |
| `uia_wait` | `tools.py:4105+` | ✅ read-only | ✅ | [01](./01-uia-deep-dive.md) |
| `adaptive_observe` | `tools.py:3062+` | via `desktop_control observe` | ✅ | [07](./07-app-framework-taxonomy.md) |
| `electron_check` / `electron_unlock` | `tools.py:4168+` | ❌ (escalates) | ✅ | [06](./06-electron-chromium.md) |
| `focus_window` / `wait_for_window` | `tools.py` | ✅ | ✅ | [03](./03-universal-launch.md) |
| `open_known_app` | `tools.py:1471+` | via agent fast-path | ✅ | [03](./03-universal-launch.md) |
| `keyboard_type` / `key_combo` | `tools.py` | ✅ (allowlisted keys) | ✅ | [05](./05-keyboard-input.md) |
| OCR (`win_ocr_words`, `ocr_find_in_app`) | `desktop_features.py:1533+` | ❌ on Live click path | ✅ auto in `uia_click` | [04](./04-vision-ocr-pixel.md) |
| `grid_locate` (internal) | `grid_locate.py` | ❌ | ✅ via `_grid_locate_click` | [04](./04-vision-ocr-pixel.md) |
| `run_command` / shell | `tools.py` | `run_terminal` (Live) | ✅ | [08](./08-powershell-system-no-ui.md) |

**Resolver ladder in `uia_click` (agent path):**

1. UIA Invoke (`invoke_ui_element`)
2. OCR pixel click (`_ocr_click_fallback`)
3. Vision grid (`_grid_locate_click`)
4. Failure + adaptive recovery plan text (`analyze_windows_failure`)

**Critical gap:** Step 2–3 do **not** consult `learned_resolvers()` first. Playbooks influence recovery *suggestions* appended to error output, not automatic resolver selection. Research P0 item #3 remains open.

### 4.2 Gemini Live tool surface

Declared in `gemini_live.py` (~978–1250): `desktop_control`, `start_desktop_task`, `run_terminal`, `look_at_screen`, `list_windows`, `capture_window`, `web_search` (opt-in), `remember`/`forget`, workflow tools, `stop_current_task`.

System prompt enforces decision tree from [00 §2](./00-master-strategy.md#2-orchestration-decision-tree): screen questions → capture first; single click → `desktop_control`; launch/multi-step → `start_desktop_task`; outcomes must match `ok`.

### 4.3 ActionType enum (`models.py`)

UIA pack: `adaptive_observe`, `uia_find`, `uia_click`, `uia_click_sequence`, `uia_type`, `uia_wait`, `electron_check`, `electron_unlock`.

**Not present (research recommends):** `open_settings`, `launch_aumid`, `launch_app`, `office_com`, `list_start_apps`.

### 4.4 Connectors (`connectors.py`)

~20 connectors defined. Browser SaaS entries use `"default_mode": "computer_use"` (screenshot/DOM loop) despite `background_browser.py` having Playwright. Discord uses `"computer"` (desktop UIA). Office/VS Code entries exist but lack COM/UIA specialization in code.

---

## 5. Key Implementation Details

### 5.1 UIA client stack

- **Library:** `uiautomation` (PyPI) via `desktop_features.py`
- **Config:** `_ensure_uia_config` sets search timeout / DPI awareness
- **Root resolution:** `_uia_root_candidates` — HWND-scored window pick, foreground fallback
- **Matching:** `_score_match` — fuzzy name/automation-id scoring
- **Patterns:** Invoke, Value, ScrollItem via `_uia_pattern`
- **Caching:** `_uia_find_cache` (2s TTL), `_adaptive_observe_cache` (4s TTL) in `ToolExecutor`

**Missing vs [01 §10](./01-uia-deep-dive.md#10-orynn-specific-recommendations):** UIA `CacheRequest` batch wrapper for large trees; no FlaUI/pywinauto alternate runtime.

### 5.2 OCR

- **Primary:** Windows.Media.Ocr (WinRT) — `win_ocr_words` async wrapper
- **Secondary:** `pytesseract` in `ocr_region` only
- **In-app find:** `ocr_find_in_app` scopes to `app_content_rect`

### 5.3 Electron unlock

- **Detect:** `is_electron_app` — checks for `electron.asar` adjacent to exe
- **Skip relaunch:** `count_app_controls >= 40` → already accessible (`tools.py:4177`)
- **Relaunch:** `--force-renderer-accessibility`; optional `--remote-debugging-port=9222`
- **Gap:** Does not `taskkill` existing instance — documented in `relaunch_with_accessibility` note; matches research gap #3

### 5.4 Launch fast-path

```python
# tools.py:447-488 — current registry
_KNOWN_LAUNCH_APPS = {
    "notepad", "calculator"/"calc", "paint"/"ms paint", "wordpad",
    "settings" → ms-settings:, "task manager" → taskmgr
}
```

Agent bypasses LLM when `detect_app_launch_intent(goal)` matches (`agent.py:1761–1779`). Live uses same detector in `build_task_payload` to avoid bloating pure launch goals with `DESKTOP_HARDENING`.

### 5.5 Adaptive Windows

- **Failure classes:** 9 enums in `FailureClass` (`adaptive_windows.py:16–25`)
- **Runtime surfaces:** 6 enums in `SurfaceRuntime`
- **Profile cap:** 80 apps, 40 history entries per app
- **Live data:** `adaptive_windows_profiles.json` shows real learning (Notepad OCR resolver heavily used)

`analyze_windows_failure` prepends `learned_resolvers` to suggested steps but does not execute them.

### 5.6 Visual UX (non-control)

- `virtual_cursor.py` — Clicky-inspired bezier cursor, trail, click pulse (~1,222 lines)
- `textbox_overlay.py` — glass bubble, task progress bridge, Clicky-style `clicky-*` task IDs
- Pointer flash overlay — opt-in via `ORYNN_POINTER_OVERLAY=1` (`tools._flash_pointer`)

---

## 6. Agent Behavior (`agent.py`)

| Mechanism | Purpose |
|-----------|---------|
| `DESKTOP_MAX_STEPS = 40` | Higher budget for control-by-control desktop work |
| `_DESKTOP_EVIDENCE_ACTION_TYPES` | Blocks empty "Done." without UIA/visual evidence |
| `_DESKTOP_MUTATING_ACTION_TYPES` + verification | Bounces finish if last click/type unverified |
| `enable_desktop_control` gate | Dashboard consent before desktop tools (bypassed for `autonomy_level=autonomous`) |
| Deterministic launch fast-path | Skips planner for pure known-app open |
| Strong UIA-first prompts | ~lines 2149–2302 — matches [00 §9 checklist](./00-master-strategy.md#9-prompt--tool-authoring-checklist) |

**Screenshot policy:** `_SCREENSHOT_ACTIONS` still includes legacy pixel actions (`mouse_click`, etc.) for vision-model paths; UIA actions prefer text tree. Hybrid mode coexists during migration.

---

## 7. Test Coverage (automation-relevant)

| Test module | Focus | ~Tests |
|-------------|-------|--------|
| `test_gemini_live.py` | Live tools, routing, desktop_control, batch policy | 149 |
| `test_adaptive_windows.py` | Profiles, observe, failure analysis | 33 |
| `test_hybrid_resolver.py` | UIA → OCR → grid ladder | 24 |
| `test_computer_control_regressions.py` | Desktop control regressions | 19 |
| `test_desktop_launcher.py` | Launch fast-path | 5 |
| `test_grid_locate.py` | Vision locate | 6 |
| `test_live_workflows.py` | Workflow execution | 6 |
| `test_voice_and_env.py` | `detect_app_launch_intent` | incl. |
| `test_adaptive_windows_canary.py` | Integration canary | 9 |

**Scripts:** `scripts/adaptive_windows_canary.py` — manual Settings/Discord/Calculator probes.

**Not covered in unit tests:** `Get-StartApps` index, AUMID launch, COM Office, Playwright connector driver, learned-resolver auto-execution.

---

## 8. Gap Analysis vs Research Roadmap

### P0 — Orchestration hardening (from [00 §8](./00-master-strategy.md#8-implementation-roadmap-prioritized))

| # | Item | Status | Notes |
|---|------|--------|-------|
| 1 | Expand `_KNOWN_LAUNCH_APPS` + spoken → URI map | ❌ Partial | 7 apps; research draft lists 20+ in [03 §10.2](./03-universal-launch.md) |
| 2 | `open_settings(suffix)` and `launch_aumid(aumid)` | ❌ Missing | Agent uses raw `run_command` |
| 3 | Wire `learned_resolvers()` before OCR/grid | ❌ Missing | Suggestions only in error text |
| 4 | Enforce Live no pixel fallback | ✅ Done | `fast_invoke_only=True` |
| 5 | Handoff envelope on escalation | ❌ Partial | Memory injected; no structured `failure_class` / `electron_hint` in task JSON |

### P1 — Scale surfaces

| Item | Status |
|------|--------|
| UIA CacheRequest batch | ❌ |
| FocusChanged Chromium wake | ❌ |
| Electron kill-and-relaunch | ❌ |
| Playwright for browser connectors | ⚠️ Infrastructure exists (`background_browser.py`), not default |
| COM shim for Office | ❌ |

### Anti-patterns — enforcement status

| Anti-pattern | Enforced? |
|--------------|-----------|
| Settings tree-walk | ⚠️ Prompt-only; no `open_settings` tool |
| Double routing (desktop_control + task) | ✅ Code + test |
| Optimistic speech | ✅ Prompt + `LIVE_TASK_RESULT_WAIT` |
| Grid on Live | ✅ `allow_pixel_fallback=False` |
| Win+Search automation | ✅ Not implemented (good) |
| Pre-written hundreds of playbooks | ✅ Lazy profiles instead |

---

## 9. Dependency & Platform Assumptions

| Dependency | Usage |
|------------|-------|
| `uiautomation` | UIA COM client |
| `pywin32` | HWND, process query, optional WScript.Shell |
| `pyautogui` | Pixel click retry after UIA miss (agent) |
| `mss` + `PIL` | Screenshots |
| `winrt` / Windows.Media.Ocr | OCR |
| `playwright` | Background browser (optional) |
| `google-genai` | Live + grid vision |
| `PySide6` | Overlay UI |

**Platform:** Windows-only for desktop control (`win32gui is None` guards elsewhere). Test machine referenced in research: Win11 build 26200.

---

## 10. Recommended Next Steps (code-ordered)

1. **Expand `_KNOWN_LAUNCH_APPS`** per [03 §10.2](./03-universal-launch.md) — lowest risk, immediate voice win.
2. **Add `open_settings(page)`** to `ToolExecutor` + `ActionType` — one-liner wrapper around `start ms-settings:{page}`.
3. **Session launch index** — `_refresh_launch_index()` from `Get-StartApps` + Start Menu `.lnk` ([03 §10.3](./03-universal-launch.md)).
4. **Wire `learned_resolvers` into `uia_click`** — before OCR, try resolver_id from profile (e.g. skip straight to OCR if Notepad history says so).
5. **`electron_unlock(force=True)`** — optional taskkill + user consent ([06](./06-electron-chromium.md)).
6. **Handoff envelope** — when Live escalates, add `{target_app, electron_hint, failure_class}` to `build_task_payload`.
7. **Update [INDEX.md](./INDEX.md)** — add 01, 04, and this doc (09).

---

## 11. File Reference Quick Index

Aligns with [INDEX.md § Code map](./INDEX.md#code-map-implementation):

| Area | Primary files | Lines (approx.) |
|------|---------------|-----------------|
| Live orchestration & tools | `widget/gemini_live.py`, `widget/textbox_overlay.py` | 1,378 + 3,361 |
| Back-office agent | `agent.py`, `tools.py` | 3,563 + 4,531 |
| UIA / desktop primitives | `widget/desktop_features.py`, `tools.py` | 2,578 |
| Lazy playbooks | `adaptive_windows.py`, `adaptive_windows_profiles.json` | 746 |
| Vision grid fallback | `grid_locate.py` | 193 |
| Connector skills | `connectors.py`, `background_browser.py` | 547 + 200 |
| Saved workflows | `workflows.py` | 198 |
| Live tests | `tests/test_gemini_live.py`, `tests/test_live_robustness.py` | 149+ tests |

---

## 12. Conclusion

The Orynn codebase **implements the research strategy's core bet**: semantic UIA control with vision as priced fallback, voice-native orchestration with hard Live/agent boundaries, and learning via lazy playbooks. The remaining work is predominantly **launch-layer scaling** (registry + discovery index), **closing the learned-resolver execution loop**, and **connector/browser modernization** — all already specified in the research corpus with concrete file targets.

This audit should be read alongside [00-master-strategy.md](./00-master-strategy.md) for decision logic and [../windows-automation-research.md](../windows-automation-research.md) for method catalogs. Re-audit after P0 items land or when `_KNOWN_LAUNCH_APPS` / launch index ships.

---

*Read-only audit of `Orynn/app/` as of 2026-06-22. No code was modified.*

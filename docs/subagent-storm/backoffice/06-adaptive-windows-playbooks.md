# 06 — Adaptive Windows Playbooks

**Audience:** Back-office / desktop subagents  
**Code anchors:** `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\adaptive_windows.py`, `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\tools.py`, `C:\Users\ACER\Desktop\Ai_computer\Orynn\adaptive_windows_profiles.json`  
**Related:** `00-master-strategy.md` §4.3, `07-app-framework-taxonomy.md`, `scripts/adaptive_windows_canary.py`

---

## 1. Purpose

Adaptive Windows is Orynn’s **lazy playbook system** for Windows desktop control. It does three jobs:

1. **Pre-flight routing** — classify an app surface before acting (`classify_surface_runtime`).
2. **Post-failure recovery** — classify a UIA/tool miss and emit an ordered resolver ladder (`analyze_windows_failure`).
3. **Per-app learning** — remember which resolver worked for which failure class (`remember_resolver_outcome` → `adaptive_windows_profiles.json`).

Design principle: **do not pre-author playbooks for hundreds of apps**. The first encounter populates profiles; subsequent runs promote proven resolvers to the front of the ladder.

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Pre-flight (cheap, ~1–4 s)                                     │
│  adaptive_observe / agent _desktop_control_profile              │
│    → survey UIA → build_affordance_graph                        │
│    → classify_surface_runtime → RuntimePlan (next_tools)        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Act (UIA primary, hybrid fallbacks in tools.py)                │
│  uia_find / uia_click / uia_type / …                            │
│    UIA miss → OCR → (optional) vision grid-locate               │
└─────────────────────────────────────────────────────────────────┘
                              │ miss
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Post-failure (analyze_windows_failure)                         │
│    1. learned_resolvers() — per-app history FIRST             │
│    2. failure-class-specific resolvers                          │
│    3. _base_resolvers() — OCR / keyboard / screen_context       │
│    → format_recovery_plan() appended to tool output             │
└─────────────────────────────────────────────────────────────────┘
                              │ success via fallback
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Learning loop (_remember_adaptive_success in tools.py)         │
│    remember_resolver_outcome(app, failure_class, resolver_id)     │
│    → adaptive_windows_profiles.json                             │
└─────────────────────────────────────────────────────────────────┘
```

**Separation of concerns**

| Phase | Function | When | Consumed by |
|-------|----------|------|-------------|
| Observe | `build_affordance_graph`, `classify_surface_runtime` | Before guessing control names | Agent profile, `adaptive_observe` tool |
| Recover | `analyze_windows_failure`, `format_recovery_plan` | After UIA miss or empty tree | Tool output suffix, agent reasoning |
| Learn | `remember_resolver_outcome`, `learned_resolvers` | After OCR/grid success | Next failure on same app |

---

## 3. Lazy playbook store

**File:** `{ORYNN_WORKSPACE}/adaptive_windows_profiles.json`  
(resolves via `workspace_state_path`; also gitignored at repo root as `adaptive_windows_profiles.json`)

**Limits:** 80 apps max (LRU by `updated_at`), 40 history entries per app.

### 3.1 Schema

```json
{
  "<app_key>": {
    "app": "Human App Name",
    "updated_at": 1782152621.697,
    "history": [
      {
        "failure_class": "uia_no_match",
        "resolver_id": "ocr_text_target",
        "successes": 264,
        "failures": 0,
        "ok": true,
        "detail": "Found Find",
        "ts": 1782152621.697
      }
    ]
  }
}
```

- **`app_key`:** lowercased, whitespace-normalized app string, max 120 chars (`_app_key`).
- **`failure_class`:** matches `FailureClass` enum value.
- **`resolver_id`:** stable resolver step id (see §5).
- **Ranking:** net-positive only (`successes > failures`), sorted by `(successes - failures, ts)` descending. A resolver with 9 successes and 1 recent failure still ranks above an untried generic path.

### 3.2 Live examples (workspace)

| App | Learned resolver | Detail |
|-----|------------------|--------|
| Notepad | `ocr_text_target` | Find dialog label not in UIA |
| File Explorer | `ocr_text_target` | Address bar |
| Desktop | `ocr_text_target` | Icon labels |
| Streaming flash bug | `ocr_text_target` | Send field |

---

## 4. Failure classes (`FailureClass`)

| Class | Trigger signals | Primary playbook |
|-------|-----------------|------------------|
| `app_not_found` | `"no window titled like"` | `wait_for_window` → `focus_window` |
| `empty_accessibility_tree` | `"no interactive controls"` | `focus_and_wait` → `electron_check` → base |
| `electron_accessibility_locked` | `electron_hint` or `"electron"` + `"locked"` | `electron_unlock` → `wait_after_unlock` → base |
| `uia_no_match` | quoted control names in error, or `"no uia control matched"` | `use_listed_control_name` (if names present) → base |
| `offscreen_or_virtualized` | `"offscreen"` / `"virtualized"` | `scroll_then_find` → base |
| `verification_mismatch` | `"could not verify"` / verify failed | `read_back_state` → `screen_context` |
| `custom_rendered_surface` | `"screenshot"` / `"pixel"` / `"canvas"` | `screen_context` → `keyboard_controller_path` |
| `ocr_visible_only` | (enum present; not primary classifier path today) | — |
| `unknown` | no pattern match | `_base_resolvers` only |

**Evidence attached:** `action`, `query`, `app`, optional `available_names` (from quoted strings in error text), `electron_hint`.

---

## 5. Resolver playbook catalog

Resolvers are `ResolverStep` records: `id`, `title`, `reason`, `tool`, `args`.

### 5.1 Failure-specific resolvers

| ID | Tool | Use when |
|----|------|----------|
| `wait_for_window` | `wait_for_window` | Target window not open |
| `focus_window` | `focus_window` | Stale/hidden window |
| `focus_and_wait` | `uia_wait` | Tree empty, app loading |
| `electron_check` | `electron_check` | Suspect Chromium lock |
| `electron_unlock` | `electron_unlock` | Confirmed Electron lock |
| `wait_after_unlock` | `uia_wait` | Post-unlock tree refresh |
| `use_listed_control_name` | same as failed `action` | Error lists exact UIA names |
| `scroll_then_find` | `scroll` | Virtualized lists |
| `read_back_state` | `uia_find` | Action ran but verify failed |
| `split_sequence_at_miss` | `uia_find` | `uia_click_sequence` miss |
| `keyboard_shortcut_path` | `keyboard_type` / `key_combo` | Menus, calculators |
| `keyboard_controller_path` | `key_combo` | Games / canvas |
| `screen_context` | `screen_context` | Visual inspection escalation |

### 5.2 Base resolvers (`_base_resolvers`)

Depend on failed **action**:

| Action | Ladder |
|--------|--------|
| `uia_type` | `ocr_text_target` → `keyboard_focus_path` → `screen_context` |
| `uia_click_sequence` | `split_sequence_at_miss` → `keyboard_shortcut_path` → `screen_context` |
| default (`uia_find`, `uia_click`, …) | `ocr_text_target` → `keyboard_shortcut_path` → `screen_context` |

### 5.3 Learned resolver injection

On every `analyze_windows_failure` call:

1. `learned_resolvers(app, failure_class, limit=3)` loads net-positive history.
2. Each match becomes a `ResolverStep` with id = `resolver_id`, tool = `resolver_id`, title `"Reuse learned resolver"`.
3. Learned steps are **prepended** before class-specific and base resolvers.
4. Total resolvers capped at **6**; recovery plan text shows top **4**.

### 5.4 Resolvers that actually write playbooks

`tools.py` calls `_remember_adaptive_success` only when a **fallback succeeds**:

| Resolver ID | Trigger path |
|-------------|--------------|
| `ocr_text_target` | `_ocr_find_fallback`, `_ocr_click_fallback`, `_ocr_type_fallback` |
| `vision_grid_locate` | `_grid_locate_click` |

All recorded under `failure_class="uia_no_match"`.

**Gap (documented in research, not yet wired):** `learned_resolvers()` is consulted in `analyze_windows_failure` but tools do not yet **skip UIA and jump straight to learned resolver** on the happy path — learning affects recovery plan ordering, while OCR still runs inline on UIA miss before the agent reads the plan.

---

## 6. Surface runtime playbooks (`SurfaceRuntime`)

`classify_surface_runtime` chooses **primary_layer** and **next_tools** from local evidence (no model).

### 6.1 Decision tree (priority order)

```
named_control_count >= 12
  → uia_rich          [uia_find, uia_click, uia_type, uia_wait]

electron_hint
  → electron_locked   [electron_check, electron_unlock, uia_wait, adaptive_observe]

meaningful_named > 0   (excludes title-bar chrome: System, Minimize, Maximize, Close)
  → uia_sparse        [uia_find, adaptive_observe, uia_wait, screen_context]

app set, no window bounds
  → window_missing    [wait_for_window, focus_window, adaptive_observe]

meaningful_named == 0, window found, visual_word_count > 0
  → visual_text       [uia_find, screen_context, key_combo, mouse_click]

meaningful_named == 0, window found, visual_word_count == 0
  → custom_rendered   [key_combo, screen_context, mouse_click, (+ computer if model_vision)]

meaningful_named == 0, window found, ocr_available, probe not run (word_count is None)
  → visual_text       (lower confidence)

meaningful_named == 0, window found (fallback)
  → custom_rendered

else
  → unknown           [adaptive_observe, screen_context, wait_for_window]
```

**Chrome-only controls:** `System`, `Minimize`, `Maximize`, `Restore`, `Close` are stripped for `meaningful_named_control_count` so empty-game surfaces are not misclassified as `uia_sparse`.

**OCR probe:** `adaptive_observe` runs a bounded `win_ocr_words` on `app_content_rect` when UIA is empty; skips if foreground window occludes target (≥25% overlap).

### 6.2 Agent profile mapping (`agent.py`)

| Runtime | Route label |
|---------|-------------|
| `uia_rich`, `uia_sparse` | UIA exact |
| `electron_locked` | Electron unlock |
| `visual_text` | OCR fallback |
| `window_missing` | Window resolution |
| `custom_rendered` + model vision | Screenshot fallback |
| else | UIA degraded |

---

## 7. Affordance graph (`build_affordance_graph`)

Groups UIA control names for agent-readable maps:

| Kind | Name heuristics | Preferred actions |
|------|-----------------|-------------------|
| `text_input` | text, editor, search, password, … | `uia_type`, `uia_find` |
| `menu_or_toolbar` | file, edit, view, settings, … | `uia_click`, `uia_find` |
| `navigation` | tab, next, back, channel, … | `uia_click`, `uia_wait` |
| `command` | save, ok, equals, bold, ctrl+… | `uia_click`, `uia_find` |
| `control` | default | `uia_click`, `uia_find` |

Output: `format_affordance_graph` → `"Adaptive app map for {app}: N UIA nodes, M named controls. text_input: …"`.

---

## 8. Tool integration

### 8.1 `adaptive_observe` (`tools.py`)

1. Survey via `survey_app_controls` (cached ~4s per app+cap).
2. If app hinted and empty tree: `wait_for_window` → `focus_window` → resurvey (`recovered_by: focus_wait_resurvey`).
3. Build graph + optional OCR probe.
4. `classify_surface_runtime` → runtime plan in output.
5. If `named_control_count == 0`: attach `analyze_windows_failure(empty_accessibility_tree)` recovery plan.

**First tool in UIA pack** (`tool_registry.py`): run before guessing names in unfamiliar apps.

### 8.2 UIA miss path

`uia_find` / `uia_click` / `uia_type` on miss:

1. Try OCR fallback (inline, may succeed and write playbook).
2. Attach `_adaptive_recovery_suffix` → `data["adaptive"]` + human-readable plan.
3. Electron hint appended when applicable.

### 8.3 Caching

| Cache | TTL | Key |
|-------|-----|-----|
| `_adaptive_observe_cache` | ~4s | app + cap |
| `_uia_find_cache` | ~2s | query + app + limit |

Invalidation: UIA click clears find cache.

---

## 9. Back-office agent playbook

### 9.1 Standard procedure for an unfamiliar app

```
1. wait_for_window / focus_window (if needed)
2. adaptive_observe(app=…)     # read Runtime plan + affordance groups
3. Follow runtime.primary_layer:
     uia              → uia_find with EXACT names from map
     electron_accessibility → electron_check → electron_unlock → uia_wait
     ocr              → uia_find (may OCR-fallback) or screen_context
     keyboard_visual  → key_combo, avoid blind coordinate clicks
     window_resolution → do not act in wrong foreground
4. On miss: read "Adaptive recovery plan (...)" in tool output
5. Execute resolvers in order; prefer learned resolver if listed first
6. Do NOT escalate to vision/computer until OCR + keyboard paths exhausted
   (unless runtime is custom_rendered and model_vision is available)
```

### 9.2 When to trust learned playbooks

- **Trust:** `successes >> failures`, same `failure_class` as current miss, same app family (key matches).
- **Re-verify:** after app update, DPI change, or theme change — one failure does not erase learning (net-positive filter).
- **Override:** if error lists exact UIA names (`use_listed_control_name`), try those before re-OCRing.

### 9.3 What back-office should NOT do

- Pre-seed `adaptive_windows_profiles.json` for apps never encountered (wastes cap, stale hints).
- Commit `adaptive_windows_profiles.json` (gitignored; workspace-local).
- Use `screen_context` / vision as first move on Win32/WinUI with rich UIA (`uia_rich`).

---

## 10. Validation

**Unit tests:** `C:\Users\ACER\Desktop\Ai_computer\Orynn\tests\test_adaptive_windows.py`  
- Failure classification, learned resolver promotion, transient-failure survival, surface runtime branches, `adaptive_observe` integration.

**Canaries:** `C:\Users\ACER\Desktop\Ai_computer\Orynn\scripts\adaptive_windows_canary.py`

| Canary | Exercises |
|--------|-----------|
| `notepad` | map → type → verify |
| `calculator` | map → click sequence |
| `settings` | UWP map density (≥8 named controls) |
| `settings_to_notepad` | cross-app extract + type |
| `discord` | Electron map + search find |
| `custom_surface` | tkinter canvas → `custom_rendered` |

```bash
python scripts/adaptive_windows_canary.py --canary notepad --canary calculator --workspace <path>
```

---

## 11. API reference (quick)

| Function | Returns |
|----------|---------|
| `learned_resolvers(app, failure_class)` | `list[dict]` history entries |
| `remember_resolver_outcome(app, fc, resolver_id, ok, detail=)` | writes profile |
| `analyze_windows_failure(action, query, app, result, output)` | `FailureAnalysis` |
| `format_recovery_plan(analysis)` | one-line agent hint |
| `classify_surface_runtime(...)` | `RuntimePlan` |
| `format_runtime_plan(plan)` | one-line runtime hint |
| `build_affordance_graph(app, controls, count)` | graph dict |
| `format_affordance_graph(graph)` | human summary |
| `meaningful_runtime_control_count(controls)` | int (chrome stripped) |

---

## 12. Known gaps / follow-ups

1. **Wire learned resolver before generic ladder in `tools.py`** — read profile and try `ocr_text_target` first on repeat apps (research §4.3).
2. **Framework exe/class heuristics** — not in `classify_surface_runtime` today; see `07-app-framework-taxonomy.md` §6.
3. **`FailureClass.ocr_visible_only`** — defined but not assigned by classifier.
4. **Learned `vision_grid_locate`** — recorded on success but not in `_base_resolvers` static ladder (only via learned prepend).
5. **Back-office-only scope** — master strategy marks lazy playbooks as back-office; Live should spawn desktop tasks rather than mutate profiles directly.

---

## 13. File index

| Path | Role |
|------|------|
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\adaptive_windows.py` | Core logic |
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\tools.py` | `adaptive_observe`, recovery suffix, learning on OCR/grid success |
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\agent.py` | Pre-turn `classify_surface_runtime` in desktop profile |
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\tool_registry.py` | `adaptive_observe` schema (first in `uia` pack) |
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\adaptive_windows_profiles.json` | Workspace learned playbooks |
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\scripts\adaptive_windows_canary.py` | No-model integration canaries |
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\tests\test_adaptive_windows.py` | Regression suite |

---

*Subagent-storm backoffice doc 06 — generated from read-only review of `adaptive_windows.py` and integrations.*

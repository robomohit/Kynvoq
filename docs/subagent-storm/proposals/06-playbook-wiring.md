# Proposal 06: Wire Lazy Playbooks Into the Resolver Ladder

**Status:** Proposed  
**Priority:** P0 (orchestration hardening)  
**Scope:** Back-office agent + `tools.py` hybrid resolver  
**Out of scope:** Live orchestrator pixel fallbacks, `main.py` task spawn (owned elsewhere)  
**Research basis:** `docs/windows-automation-research/00-master-strategy.md` §4.3, `07-app-framework-taxonomy.md` §3.5, `04-vision-ocr-pixel.md` §7, `05-keyboard-input.md` §4.3, `docs/windows-automation-research.md` §6  

---

## Summary

Orynn already **writes** lazy playbooks (`adaptive_windows_profiles.json`) and **mentions** them in failure text, but does not **consult** them when choosing which fallback tier to run. The second interaction on Notepad Find still walks the full UIA → OCR → grid ladder even when the profile records `ocr_text_target` with 264 successes. This proposal wires `learned_resolvers()` into pre-flight profiles, hybrid resolver ordering, and task handoff envelopes so learned paths are executed — not just narrated.

---

## Problem

### What research promises

From the master strategy scaling policy:

> Do not pre-write playbooks for N apps. Let the first encounter populate profiles; **consult profile before expensive vision**.

From vision/OCR research:

> At scale (hundreds of apps), lazy playbooks amortise discovery cost — **second interaction on same app should hit the winning tier immediately**.

From the framework taxonomy gap note:

> Consulted on failure via `analyze_windows_failure`, **not at profile time**.

### What happens today

| Layer | Playbook involvement | Gap |
|-------|---------------------|-----|
| **Write** | `_remember_adaptive_success()` records `resolver_id` + `failure_class` on OCR/grid success | ✅ Works |
| **Read (advisory)** | `analyze_windows_failure()` prepends learned steps to recovery plan text | ⚠️ Text only |
| **Read (execution)** | `uia_click` / `uia_type` / `uia_find` hybrid ladder | ❌ Fixed UIA → OCR → grid |
| **Pre-flight** | `_desktop_control_profile()` in `agent.py` | ❌ No learned hints |
| **Handoff** | Live → back-office task JSON | ❌ No `failure_class` / learned resolver |
| **Failure loop** | `remember_resolver_outcome(..., ok=False)` | ❌ Never called from tools |

### Concrete symptom

`adaptive_windows_profiles.json` (workspace) already contains:

```json
"notepad": {
  "history": [{
    "failure_class": "uia_no_match",
    "resolver_id": "ocr_text_target",
    "successes": 264,
    "failures": 0
  }]
}
```

Yet every Notepad Find/Replace miss still:

1. Tries UIA (correct — must verify miss first).
2. Tries OCR (correct for this app, but **by accident**, not because the profile said so).
3. Would try grid-locate if OCR failed — even if history says OCR always wins and grid never helped.

For an app where `vision_grid_locate` is the learned winner, the agent wastes 100–500 ms on OCR on every miss before reaching the right tier.

### Why this matters

- **Latency:** Grid-locate costs 1.5–5 s per attempt; OCR costs 0.2–1.2 s. Wrong tier order multiplies task time.
- **Cost:** Grid uses model API calls; skipping it when playbooks say OCR wins saves quota.
- **Agent confusion:** Recovery plan says "Reuse learned resolver [ocr_text_target]" but the tool layer already ran OCR silently or is about to run grid — the model cannot correlate plan with action.
- **Learning loop is half-open:** Successes are recorded; resolver **failures** are not, so net-negative paths cannot decay (the ranking logic in `learned_resolvers()` is ready but starved of failure signal).

---

## Current Architecture (as implemented)

```
┌─────────────────────────────────────────────────────────────────┐
│ agent.py: _desktop_control_profile()                            │
│   classify_surface_runtime() → primary_route text               │
│   (no read of adaptive_windows_profiles.json)                   │
└────────────────────────────┬────────────────────────────────────┘
                             │ injected into agent system prompt
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ tools.py: uia_click / uia_type / uia_find                       │
│   1. UIA attempt                                                │
│   2. _ocr_*_fallback()  ──success──► remember_resolver (ok)   │
│   3. _grid_locate_click() ──success──► remember_resolver (ok)   │
│   4. _adaptive_recovery_suffix() → analyze_windows_failure()    │
│        └─ learned_resolvers() → prepended to TEXT plan only     │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
              adaptive_windows_profiles.json (workspace state)
```

**Key modules:** `app/adaptive_windows.py`, `app/tools.py`, `app/agent.py`  
**Tests already cover:** classification, learned promotion in analysis text, success memory (`tests/test_adaptive_windows.py`).

---

## Proposed Design

### Principle

> **Playbooks steer the ladder; they do not bypass UIA.**

UIA remains the first attempt on every action — names may have changed, dialogs may have loaded. After a confirmed UIA miss (same `failure_class`), consult the profile and **reorder or skip** fallback tiers before expensive vision.

### 1. Central playbook consult helper

Add to `adaptive_windows.py`:

```python
def preferred_fallback_order(
    app: str,
    failure_class: str,
    *,
    action: str = "",
) -> list[str]:
    """Return ordered resolver_ids after UIA miss, e.g.
    ['ocr_text_target'] or ['vision_grid_locate'] or default ladder."""
```

**Default ladder** (unchanged when no profile): `ocr_text_target` → `vision_grid_locate` → advisory resolvers from `analyze_windows_failure`.

**Learned override rules:**

| Condition | Order |
|-----------|-------|
| Top learned resolver has net score ≥ 3 and ≥ 2× next candidate | Run **only** that tier (skip lower-priority tiers) |
| Top learned resolver has net score ≥ 1 | Run learned tier **first**, then default ladder for remaining tiers |
| Learned resolver is `electron_unlock` / `wait_for_window` | Do **not** auto-execute in click/type path — inject into recovery plan + profile text only (these are preconditions, not click fallbacks) |
| `failure_class` mismatch | Ignore entry; use default ladder |
| Live path (`allow_pixel_fallback=False`) | No change — playbooks remain back-office only |

Map `resolver_id` → tool callable:

| `resolver_id` | Tool path |
|---------------|-----------|
| `ocr_text_target` | `_ocr_click_fallback` / `_ocr_find_fallback` / `_ocr_type_fallback` |
| `vision_grid_locate` | `_grid_locate_click` |
| `keyboard_focus_path` | Not auto-run in hybrid path; prompt hint only |
| `electron_unlock` | `electron_unlock` tool (agent-driven) |
| `use_listed_control_name` | Re-issue UIA with `query` from evidence (already in analysis) |

### 2. Wire into hybrid resolver (`tools.py`)

Refactor `uia_click`, `uia_type`, and `uia_find` miss paths:

```python
# Pseudocode — after UIA miss, before fallbacks:
if allow_pixel_fallback:
    order = preferred_fallback_order(app, "uia_no_match", action="uia_click")
    for resolver_id in order:
        result = self._run_resolver(resolver_id, query, app, ...)
        if result is not None:
            return result
        self._remember_adaptive_failure(app, "uia_no_match", resolver_id, ...)
```

Extract `_run_resolver()` to dispatch by id so tests can mock ordering without duplicating OCR/grid bodies.

**Record failures:** On each fallback tier that returns `None`, call `remember_resolver_outcome(..., ok=False)` with short detail (e.g. `"OCR no match"`). This closes the learning loop tests already expect (`test_learned_resolver_drops_net_negative`).

### 3. Pre-flight profile injection (`agent.py`)

Extend `_desktop_control_profile()` and `_desktop_control_profile_text()`:

When `target_app` is set, load top learned resolvers for the **most common** failure classes for that app key (`uia_no_match`, `empty_accessibility_tree`, `electron_accessibility_locked`):

```
- Learned playbook: for uia_no_match on Notepad, prefer ocr_text_target
  (264 successes, 0 failures) — skip vision grid-locate unless OCR misses.
```

Also inject when `classify_surface_runtime()` returns `visual_text` or `custom_rendered` **and** a learned resolver exists — the runtime classifier and playbook should agree on primary layer.

**Do not** inject raw JSON into the prompt; use one line per failure_class with resolver_id and net score.

### 4. Handoff envelope (coordination with proposal 05)

When Live escalates to back-office, task payload should include:

```json
{
  "target_app": "Notepad",
  "failure_class": "uia_no_match",
  "learned_resolvers": [
    {"resolver_id": "ocr_text_target", "net": 264}
  ],
  "runtime": { "...": "from classify_surface_runtime" }
}
```

Back-office agent's first turn can call `adaptive_observe` **or** jump directly to learned tier if `failure_class` is already known from handoff. Document contract here; implementation may land in `main.py` / `gemini_live.py` separately.

### 5. Expand playbook schema (optional P1)

Research (`05-keyboard-input.md`) suggests richer entries:

```json
{
  "code.exe": {
    "preferred_shortcuts": ["ctrl+shift+p", "ctrl+p"]
  }
}
```

Defer to P1. P0 only wires existing `failure_class` + `resolver_id` history. Shortcut playbooks would feed `_desktop_control_profile_text`, not hybrid click path.

### 6. Observability

Tag `ToolResult.data` with:

```json
{
  "playbook": {
    "consulted": true,
    "resolver_id": "ocr_text_target",
    "skipped_tiers": ["vision_grid_locate"],
    "source": "learned"
  }
}
```

Aligns with research recommendation to log resolver tier (`control_layer` already exists on overlay).

---

## Implementation Plan

### Phase A — Resolver reorder (highest ROI, ~1 day)

1. Add `preferred_fallback_order()` + `RESOLVER_DISPATCH` map in `adaptive_windows.py`.
2. Add `_run_learned_fallback_ladder()` in `tools.py`; call from `uia_click`, `uia_type`, `uia_find`.
3. Add `_remember_adaptive_failure()` mirroring `_remember_adaptive_success()`.
4. Unit tests: order respects net score; grid skipped when OCR learned; default ladder when profile empty.

### Phase B — Profile injection (~0.5 day)

1. `learned_resolvers()` summary helper for prompt text.
2. Extend `_desktop_control_profile_text()` with learned lines.
3. Test: profile text mentions Notepad `ocr_text_target` when profile file seeded.

### Phase C — Handoff + canary (~0.5 day)

1. Document task JSON fields (this proposal + proposal 05).
2. Extend `scripts/adaptive_windows_canary.py` to assert second-run latency drops when profile pre-seeded.
3. Add benchmark row to `docs/BENCHMARKS.md` (manual).

---

## Files Touched

| File | Change |
|------|--------|
| `app/adaptive_windows.py` | `preferred_fallback_order()`, prompt summary helper |
| `app/tools.py` | Learned ladder dispatch, failure recording |
| `app/agent.py` | Profile text injection |
| `tests/test_adaptive_windows.py` | Ordering, skip-grid, failure recording |
| `tests/test_hybrid_resolver.py` | End-to-end uia_click with seeded profile |
| `scripts/adaptive_windows_canary.py` | Second-interaction latency check |

**Not in this PR:** `main.py`, `gemini_live.py` (handoff envelope), schema expansion for shortcuts.

---

## Test Plan

| Test | Expectation |
|------|-------------|
| Seeded profile `ocr_text_target` + UIA miss | OCR runs; grid **not** called (mock asserts) |
| Seeded profile `vision_grid_locate`, OCR returns None | Grid runs without redundant OCR success path |
| Empty profile | UIA → OCR → grid (unchanged) |
| `allow_pixel_fallback=False` | No playbook consult; UIA-only miss |
| OCR fallback fails | `failures` counter increments on `ocr_text_target` |
| `learned_resolvers` net-negative | Resolver dropped from order |
| `adaptive_windows_canary` second pass | Duration ≤ first pass for Notepad Find scenario |

Run: `pytest tests/test_adaptive_windows.py tests/test_hybrid_resolver.py -q`

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Stale playbook steers wrong tier (UI changed) | Require UIA miss each action; net-score threshold; failures decay ranking |
| Skipping OCR when grid learned but text now visible | Only skip tiers **below** learned winner, not UIA; re-probe OCR if grid fails |
| Over-fitting to one dialog context | Key by `failure_class`; optional future: `query` hash in history |
| Profile path drift (`notepad` vs `Notepad`) | Already normalized via `_app_key()` |
| Live accidentally gets pixel playbooks | Guard on `allow_pixel_fallback` |

---

## Success Metrics

1. **Second-interaction latency:** ≥30% reduction on `uia_no_match` for apps with net-positive playbook (canary script).
2. **Grid-locate call rate:** Drops for apps where OCR is learned winner (log aggregate).
3. **Task completion:** Notepad Find, File Explorer address bar, Calculator misclick recovery — no regression in existing pytest suite.
4. **Learning loop:** Failure counts appear in `adaptive_windows_profiles.json` after deliberate OCR/grid misses.

---

## Non-Goals

- Pre-writing playbooks for hundreds of apps.
- Live orchestrator OCR peek (see proposal 04).
- Auto-executing `electron_unlock` inside `uia_click` without agent consent.
- Replacing `analyze_windows_failure()` — it remains the advisory layer for unknown failures.
- Storing playbook data in git (`adaptive_windows_profiles.json` stays workspace-local per `.gitignore`).

---

## References

- `app/adaptive_windows.py` — `learned_resolvers`, `remember_resolver_outcome`, `analyze_windows_failure`
- `app/tools.py` — `_ocr_click_fallback`, `_grid_locate_click`, `_adaptive_recovery_suffix`
- `app/agent.py` — `_desktop_control_profile`, `_desktop_control_profile_text`
- `docs/windows-automation-research/00-master-strategy.md` — P0 item 3: wire `learned_resolvers()` into `tools.py`
- `docs/windows-automation-research/07-app-framework-taxonomy.md` — §3.5 lazy playbooks gap
- `docs/windows-automation-research/04-vision-ocr-pixel.md` — latency/cost budget for tier ordering

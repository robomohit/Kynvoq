# UIA Tree Cache — Implementation Proposal

**Doc:** `02-uia-tree-cache.md`  
**Date:** 2026-06-22  
**Priority:** P1 (high ROI)  
**Source research:** [01-uia-deep-dive.md](../../windows-automation-research/01-uia-deep-dive.md) §4.3, §6, §10.2  
**Audience:** Orynn desktop automation engineers  
**Constraint:** Proposal only — no app code changes in this workstream.

---

## Executive Summary

Orynn today caches **tool results** (`uia_find` for 2s, `adaptive_observe` for ~4s) but still pays **per-property COM round-trips** every time it walks the UIA tree. `_walk_survey`, `find_ui_elements`, `_find_uia_control`, and `_miss_error` each independently traverse the same HWND subtree, re-fetching `Name`, `AutomationId`, `ControlType`, and `BoundingRectangle` on every node.

Microsoft's `IUIAutomationCacheRequest` can batch those properties in a single cross-process fetch per subtree level. Research estimates **3–10× faster observation** on surveys and scored walks — the single highest-ROI UIA improvement after the existing search-first / HWND-scoping architecture.

This proposal defines a **two-layer cache**:

1. **COM tree snapshot** — one cached walk per `(hwnd, tree_generation)` with batched property reads.
2. **Application snapshot cache** — reuse the COM snapshot across `survey_app_controls`, `find_ui_elements`, `_miss_error`, and `adaptive_observe` within a short TTL, with strict invalidation on mutations.

Keep `uiautomation` for invoke/type/mutation paths. Add a thin `uia_cache.py` module using `comtypes` (or a minimal ctypes COM shim) only for **read-only observation**.

---

## Problem Statement

### Why tree walking is slow

Each `GetChildren()`, `Name`, `BoundingRectangle`, and `AutomationId` access on a `uiautomation.Control` may marshal into the target app's UIA provider apartment. A 90-node survey with four properties per node can mean **hundreds of cross-process calls**. Microsoft explicitly recommends `FindFirst`/`FindAll` with conditions over manual `IUIAutomationTreeWalker` walks — but Orynn's scored fuzzy matching and interactive-type filtering still require walking when exact `FindFirst` misses.

### What Orynn already caches (and what it does not)

| Layer | Location | TTL | Key | Invalidation |
|-------|----------|-----|-----|--------------|
| `uia_find` result | `tools.py` `_uia_find_cache` | 2.0s | query + app + limit + fg/isolated HWND | `_clear_uia_find_cache()` on click/type/sequence |
| `adaptive_observe` | `tools.py` `_adaptive_observe_cache` | 4.0s | app + cap + fg/isolated HWND | implicit TTL only |
| COM property batch | — | **none** | — | — |
| Shared tree walk | — | **none** | — | — |

**Gap (from research §4.3):** `_walk_survey` / `survey_app_controls` / `find_ui_elements` / `_miss_error` → `_survey_controls_under` can all hit the **same tree** in one agent turn, yet each performs a full uncached walk.

### Hot paths affected

| Function | File | Typical trigger | Nodes touched |
|----------|------|-----------------|---------------|
| `_walk_survey` | `desktop_features.py` | `survey_app_controls`, `_miss_error` | up to 90–120 |
| `find_ui_elements` | `desktop_features.py` | `uia_find`, `uia_wait` poll | up to 40 depth × branches |
| `_find_uia_control` | `desktop_features.py` | `uia_click`, `uia_type`, `invoke_ui_element` | same as find |
| `adaptive_observe` | `tools.py` | agent observe after navigation | survey cap 120 |

A single Calculator or Settings task can easily trigger **3–6 tree walks** before the first click.

---

## Goals

| Goal | Metric |
|------|--------|
| Cut observation latency | `survey_app_controls` p50 ≤ 150ms on Win32 apps (baseline TBD) |
| Amortize walks across tools | Second `uia_find` on same HWND within TTL uses snapshot, not re-walk |
| Preserve correctness | Zero stale-click incidents in benchmark suite |
| Minimal stack churn | Keep `uiautomation` for mutations; no FlaUI sidecar in v1 |
| Teach agents stable IDs | Snapshot records `AutomationId` for `FindFirst` fast path (research §6.1) |

### Non-goals (v1)

- C# FlaUI sidecar microservice (research P3 — defer until Python path plateaus)
- UIA `StructureChanged` event subscription (separate proposal)
- Desktop-root `Descendants` search (explicit anti-pattern)
- Replacing `uiautomation` entirely

---

## Proposed Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  tools.py (uia_find, adaptive_observe, uia_click, …)                │
│       │ uses snapshot cache key: hwnd + fg_hwnd + isolated_hwnd     │
│       ▼                                                             │
│  desktop_features.py                                                │
│       │ find_ui_elements / survey / _find_uia_control               │
│       ▼                                                             │
│  NEW: uia_tree_cache.py                                             │
│       │ get_snapshot(hwnd) → UiaTreeSnapshot                        │
│       │   ├─ COM CacheRequest walk (comtypes)                       │
│       │   └─ in-memory node index: name, aid, type, rect, patterns  │
│       ▼                                                             │
│  uiautomation (unchanged) — ControlFromHandle + GetPattern.Invoke   │
└─────────────────────────────────────────────────────────────────────┘
```

### `UiaTreeSnapshot` data model

```python
@dataclass(frozen=True)
class UiaNode:
    runtime_id: tuple[int, ...]   # stable within session; map back to live element
    name: str
    automation_id: str
    control_type: str             # e.g. "ButtonControl"
    left: int; top: int; width: int; height: int
    offscreen: bool
    depth: int
    parent_index: int | None
    has_invoke: bool              # pattern availability flags (cheap at cache time)
    has_value: bool
    has_toggle: bool
    has_selection_item: bool

@dataclass
class UiaTreeSnapshot:
    hwnd: int
    root_name: str
    created_at: float
    tree_generation: int           # monotonic per-hwnd invalidation counter
    nodes: list[UiaNode]
    # indexes built lazily:
    # by_name_lower, by_aid_lower, interactive_names
```

**Live control resolution:** When `invoke_ui_element` needs a real `Control` for `Invoke()`, resolve via `runtime_id` → `IUIAutomationElement` (comtypes) or `uiautomation` lookup by path. Prefer keeping the existing `_find_uia_control` fast `FindFirst(Name=)` path for mutations; use snapshot only for **search/rank/survey** unless benchmark shows resolution is negligible.

---

## COM CacheRequest Design

Per [Microsoft caching for clients](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-cachingforclients):

### Properties to cache (per element + children scope)

| Property | ID | Used by |
|----------|-----|---------|
| `Name` | `UIA_NamePropertyId` | `_score_match`, survey |
| `AutomationId` | `UIA_AutomationIdPropertyId` | `_score_match`, future ID find |
| `ControlType` | `UIA_ControlTypePropertyId` | interactive filter |
| `BoundingRectangle` | `UIA_BoundingRectanglePropertyId` | overlay tokens, offscreen rank |
| `IsOffscreen` | `UIA_IsOffscreenPropertyId` | rank penalty (−8) |
| `RuntimeId` | `UIA_RuntimeIdPropertyId` | re-resolve live element |
| `NativeWindowHandle` | optional | root validation |

### Patterns to cache (availability only)

| Pattern | ID | Used by |
|---------|-----|---------|
| `Invoke` | `UIA_InvokePatternId` | invoke ladder |
| `Value` | `UIA_ValuePatternId` | type ladder |
| `Toggle` | `UIA_TogglePatternId` | invoke ladder |
| `SelectionItem` | `UIA_SelectionItemPatternId` | list/tree nav |
| `ScrollItem` | `UIA_ScrollItemPatternId` | pre-invoke scroll |

### Tree scope strategy

| Operation | Scope | Rationale |
|-----------|-------|-----------|
| Snapshot build | `Element \| Children` per recursive step | Avoid `Descendants` on Electron (research §4.1) |
| Depth cap | `_UIA_MAX_DEPTH` (40) | unchanged |
| Node cap | `cap` arg (90–120) | unchanged |
| Exact find fast path | `FindFirstBuildCache` on root with `Name` or `AutomationId` condition | Runs in UIA C++ core; keep existing `uiautomation` probe |

**Implementation sketch** (conceptual — from research §9.5):

```python
def _build_cache_request(automation) -> IUIAutomationCacheRequest:
    req = automation.CreateCacheRequest()
    for prop_id in _CACHED_PROPERTY_IDS:
        req.AddProperty(prop_id)
    for pattern_id in _CACHED_PATTERN_IDS:
        req.AddPattern(pattern_id)
    req.TreeScope = TreeScope_Element | TreeScope_Children
    req.AutomationElementMode = AutomationElementMode_Full
    return req

def _walk_build_cache(element, request, depth, cap, out: list):
    if depth > _UIA_MAX_DEPTH or len(out) >= cap:
        return
    # Read cached properties — one round trip per element
    node = _node_from_cached_element(element)
    out.append(node)
    child = element.GetFirstChildElementBuildCache(request)
    while child:
        _walk_build_cache(child, request, depth + 1, cap, out)
        child = child.GetNextSiblingElementBuildCache(request)
```

Use `ElementFromHandleBuildCache(hwnd, request)` as snapshot root — same HWND scoping Orynn already uses via `ControlFromHandle`.

---

## Application Snapshot Cache

### Cache key

Extend the existing `_window_scoped_cache_key` pattern in `tools.py`:

```json
{
  "kind": "uia_tree_snapshot",
  "hwnd": 12345678,
  "foreground_hwnd": 12345678,
  "isolated_hwnd": 0,
  "cap": 90
}
```

Store snapshots in a module-level dict in `uia_tree_cache.py` (or on `Tools` instance for testability).

### TTL and sizing

| Parameter | Proposed value | Rationale |
|-----------|----------------|-----------|
| Snapshot TTL | **2.0s** | Align with `_UIA_FIND_CACHE_TTL_S`; observation is read-mostly |
| Max cached HWNDs | 4 | multi-root search touches ≤3 roots |
| Max nodes per snapshot | 120 | matches `_miss_error` survey cap |
| Memory budget | ~50 KB/snapshot | 120 nodes × ~400 B |

### Invalidation rules

| Event | Action |
|-------|--------|
| `uia_click`, `uia_type`, `uia_click_sequence` | `invalidate_all()` + existing `_clear_uia_find_cache()` |
| Foreground HWND change | new cache key naturally misses |
| Isolated HWND change | new cache key naturally misses |
| TTL expiry | lazy eviction on read |
| Optional: `StructureChanged` (v2) | increment `tree_generation` per hwnd |

**Do not** invalidate on `uia_find` or `uia_wait` — those should **benefit** from the snapshot.

### Consumer integration

| Consumer | Change |
|----------|--------|
| `_walk_survey` | `snapshot = get_snapshot(root_hwnd, cap)` → filter `_INTERACTIVE_CTRL_TYPES` from nodes |
| `find_ui_elements` | Score against snapshot nodes; only call live `Control` for winner(s) |
| `_miss_error` | Read `snapshot.interactive_names` — **no second walk** |
| `survey_app_controls` | Single snapshot per ranked root attempt |
| `_cached_uia_find` | Optional: store snapshot pointer in find cache entry to skip rebuild |
| `adaptive_observe` | Share snapshot with survey; extend TTL to 4s only if same HWND |

---

## Phased Implementation Plan

### Phase 0 — Baseline instrumentation (0.5 day)

Add timing hooks (debug-only or `ORYNN_UIA_PROFILE=1`):

- `survey_app_controls` wall time
- `find_ui_elements` wall time
- COM call count estimate (wrap snapshot builder)

Record baselines on: Notepad, Calculator, Windows Settings, Discord (unlocked Electron).

**Exit criteria:** `benchmark-results/uia-cache-baseline-YYYY-MM-DD.json` with p50/p95 per app.

### Phase 1 — `uia_tree_cache.py` COM snapshot builder (2–3 days)

1. Add optional dependency: `comtypes` (pin version in `requirements.txt` or extras `[uia-cache]`).
2. Implement `UiaTreeSnapshot` + `build_snapshot_from_hwnd(hwnd, cap)`.
3. Unit-test against Notepad: snapshot contains `"Edit"` or menu items; node count > 0.
4. Feature flag: `ORYNN_UIA_TREE_CACHE=0|1` (default **0** until Phase 2).

**Exit criteria:** Snapshot builds in <200ms on Notepad; no new crashes when flag off.

### Phase 2 — Wire snapshot into observation paths (2 days)

1. Refactor `_walk_survey` to consume snapshot when flag on.
2. Refactor `find_ui_elements` scored walk to scan snapshot nodes; retain existing `FindFirst(Name=)` fast path via `uiautomation`.
3. Refactor `_miss_error` to use cached interactive names.
4. Unify invalidation: `invalidate_uia_tree_cache()` called from `_clear_uia_find_cache()`.

**Exit criteria:** `ORYNN_UIA_TREE_CACHE=1` passes existing `tests/test_fast_path.py`, `tests/test_adaptive_windows.py`, and any UIA regression tests; p50 survey latency ≥3× improvement on Win32 apps.

### Phase 3 — `AutomationId` fast find (1 day)

When `adaptive_observe` or `uia_find` returns `automation_id` for a match:

```python
fast = root.Control(searchDepth=0xFFFFFFFF, AutomationId=aid)
```

Add to `find_ui_elements` before scored walk (research §6.1, §10.2 P1). Store IDs in snapshot index `by_aid_lower`.

**Exit criteria:** Settings navigation survives locale changes when IDs stable; benchmark task "Settings nav" unchanged or improved.

### Phase 4 — Default-on + cleanup (0.5 day)

1. Flip default to `ORYNN_UIA_TREE_CACHE=1`.
2. Document in `docs/windows-automation-research/01-uia-deep-dive.md` §7 implementation map.
3. Remove redundant walks in `adaptive_observe` if any remain.

---

## Files to Touch

| File | Changes |
|------|---------|
| **NEW** `app/uia_tree_cache.py` | COM snapshot builder, snapshot cache, invalidation |
| `app/widget/desktop_features.py` | `_walk_survey`, `find_ui_elements`, `_miss_error` read snapshot |
| `app/tools.py` | Call `invalidate_uia_tree_cache()` from `_clear_uia_find_cache()`; optional snapshot reuse in `_cached_uia_find` |
| `requirements.txt` or `pyproject.toml` | `comtypes` optional/extra |
| `tests/test_uia_tree_cache.py` | **NEW** — snapshot shape, cache hit/miss, invalidation |
| `tests/test_fast_path.py` | Extend with cache-on path |
| `scripts/benchmark_tasks.py` | Record `uia_snapshot_ms` in harness output |

**Do not modify:** `invoke_ui_element` pattern ladder, Electron unlock, OCR/vision fallbacks.

---

## Testing Plan

### Unit tests (`tests/test_uia_tree_cache.py`)

| Test | Assert |
|------|--------|
| `test_snapshot_notepad_has_edit` | Interactive list non-empty |
| `test_snapshot_respects_cap` | `len(nodes) <= cap` |
| `test_cache_hit_same_hwnd` | Second `get_snapshot` within TTL returns same object |
| `test_cache_miss_after_invalidate` | After `invalidate_all()`, rebuild occurs |
| `test_cache_miss_fg_change` | Different `foreground_hwnd` in key → miss |
| `test_find_from_snapshot_scores` | Exact name → score 100 |

### Integration tests

| Scenario | Expected |
|----------|----------|
| Calculator `1+2=` via `uia_click_sequence` | Same pass rate; fewer steps or lower duration |
| Notepad type + save | `uia_find` cache hit message may include `tree_snapshot_reused: true` |
| Settings nav `adaptive_observe` | Control menu matches pre-cache behavior |
| Discord (unlocked) channel list | No regression; cap still stops at 90 nodes |
| Mutation clears cache | `uia_click` after `uia_find` forces fresh snapshot |

### Manual profiling

Run with `ORYNN_UIA_PROFILE=1` on Electron unlocked (VS Code) — confirm UI does not freeze; if laggy, reduce cap or narrow cached properties.

---

## Risks and Mitigations

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Stale snapshot → wrong click target | Medium | Short TTL; invalidate on all mutations; resolve live `Control` before `Invoke()` |
| `comtypes` COM threading issues | Low | Build snapshot on agent worker thread (already the case); never on Qt GUI thread |
| Electron 10k-node trees lag UI | Medium | Keep cap 90; never `Descendants` scope; bail early on exact find |
| `uiautomation` + `comtypes` double COM init | Low | Lazy-init comtypes module; single `IUIAutomation` instance per process |
| RuntimeId re-resolve fails after DOM update | Medium | Fall back to existing `_find_uia_control` walk on miss |
| Increased memory on many HWNDs | Low | LRU evict at 4 entries |

---

## Success Metrics

| Metric | Target (vs Phase 0 baseline) |
|--------|------------------------------|
| `survey_app_controls` p50 latency | ≥3× faster Win32; ≥2× Electron (unlocked) |
| `find_ui_elements` p50 (cache warm) | ≥2× faster |
| Agent turns to complete Calculator e2e | ≤ baseline (ideally −1 turn from faster observe) |
| Benchmark pass rate | 100% parity with cache off |
| Stale-control incidents | 0 in 10× benchmark runs |

Publish results per [BENCHMARKS.md](../../BENCHMARKS.md) reporting rules.

---

## Alternatives Considered

| Option | Pros | Cons | Decision |
|--------|------|------|----------|
| **A. comtypes CacheRequest (proposed)** | Full API; stays in Python; batch properties | New dep; COM boilerplate | **Recommended v1** |
| B. Extend `uiautomation` fork | Single stack | Upstream may not expose cache; maintenance | Defer |
| C. FlaUI C# sidecar | Best cache ergonomics | Process boundary; deploy complexity | P3 per research |
| D. Only widen app-level TTL | Trivial | Does not fix per-property COM cost | Insufficient |
| E. Desktop `Descendants` FindAll | One call | Freezes browsers; Microsoft warns against | Rejected |

---

## Open Questions

1. **Should `adaptive_observe` TTL (4s) and snapshot TTL (2s) unify?** Recommendation: single 2s snapshot TTL; let observe cache store serialized survey **derived from** snapshot to avoid duplicate walks.
2. **Resolve live element via RuntimeId or re-walk?** Benchmark both; default RuntimeId with walk fallback.
3. **Ship `comtypes` as required or optional extra?** Start optional behind flag; promote to required after Phase 4 if size acceptable.

---

## References

| Resource | Link |
|----------|------|
| Orynn UIA deep dive | [01-uia-deep-dive.md](../../windows-automation-research/01-uia-deep-dive.md) |
| Microsoft — Caching for clients | https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-cachingforclients |
| Microsoft — Tree walker | https://learn.microsoft.com/en-us/windows/win32/api/uiautomationclient/nn-uiautomationclient-iuiautomationtreewalker |
| Microsoft — FindFirst | https://learn.microsoft.com/en-us/windows/win32/api/uiautomationclient/nf-uiautomationclient-iuiautomationelement-findfirst |
| Orynn benchmarks | [BENCHMARKS.md](../../BENCHMARKS.md) |
| Primary code | `app/widget/desktop_features.py`, `app/tools.py` |

---

*Subagent-storm proposal #02. Implements research recommendation P1: COM `CacheRequest` in survey/find paths. Sibling proposals: `01-resolve-launch-target`, `03-open-settings-tool`.*

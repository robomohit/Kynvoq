# Live Mid-Tier OCR Peek — Proposal

**Doc:** `04-live-mid-tier-ocr.md`  
**Date:** 2026-06-22  
**Scope:** Add a **local OCR click tier** to the Gemini Live orchestrator between UIA-only fast path and full back-office agent escalation — using **PrintWindow capture** so OCR works while the Orynn overlay is visible.  
**Audience:** Orynn product and engineering  
**Related:** [00-master-strategy.md](../../windows-automation-research/00-master-strategy.md), [04-vision-ocr-pixel.md](../../windows-automation-research/04-vision-ocr-pixel.md), `textbox_overlay._desktop_control_route`, `tools._ocr_click_fallback`, `desktop_features.ocr_find_in_app`

> **Scope boundary:** This proposal covers Live orchestrator behavior only. It does **not** change the back-office agent ladder, grid-locate, or `look_at_screen` vision Q&A. No app code is included here — implementation is a follow-up task.

---

## Executive Summary

Today the Live path for `desktop_control` click/type is:

1. **Fast UIA** (`allow_pixel_fallback=False`) — invoke pattern only, no mouse  
2. **On miss** → consent checks → **`start_desktop_task`** (full agent with OCR + grid)

The back-office agent already has a proven **Tier-2 OCR** (`_ocr_click_fallback` → `ocr_find_in_app` → `pyautogui.click`) that resolves many UIA misses in **100–500 ms** at **$0 API cost**. Live deliberately skips this tier to avoid mouse hijacking and to force clean escalation — but the result is **over-escalation**: a simple "click Save" in a partially accessible app spawns a 10–30 s agent job when OCR alone would suffice.

**Proposal:** Insert an **OCR mid-tier** in `_desktop_control_route` after UIA miss and before `start_desktop_task`. Pair it with **PrintWindow-based OCR capture** ("OCR peek") so text is read from the target HWND's backing store even when the Orynn overlay occludes the desktop. **Grid-locate remains forbidden on Live.**

| Tier | Live today | Proposed Live |
|------|------------|---------------|
| 1 — UIA invoke | ✅ | ✅ |
| 2 — Windows OCR + pixel click | ❌ (skipped) | ✅ **new mid-tier** |
| 3 — Vision grid-locate | ❌ | ❌ (unchanged) |
| 4 — Full back-office agent | ✅ on UIA miss | ✅ on OCR miss |

**Expected win:** Fewer abandoned/spawned tasks, sub-2 s perceived click latency for text-labeled controls, better voice UX without opening the vision-cost or hallucination paths.

---

## 1. Problem Statement

### 1.1 Over-escalation on simple clicks

`_desktop_control_route` in `textbox_overlay.py` calls `_live_desktop_control(..., fast_invoke_only=True)`, which passes `allow_pixel_fallback=False` into `tools.uia_click`. When UIA has no invoke pattern (common on Electron menus, sparse trees, custom-drawn labels), Live immediately escalates to `start_desktop_task`.

Observed failure modes from storm log forensics and research:

| User intent | UIA result | Live today | Ideal |
|-------------|------------|------------|-------|
| "Click Save" in Notepad | Miss (label visible, no pattern) | Full agent spawn | OCR click in ~300 ms |
| "Click Usage" in settings-like UI | Miss | Agent + possible `electron_unlock` | OCR if text on screen |
| "Click the OK button" | Miss | Agent | OCR on dialog text |
| Icon-only toolbar glyph | Miss | Agent (grid) | Agent (OCR can't help) — **unchanged** |

The back-office path already handles the first three via `_ocr_click_fallback`. Live pays the agent tax for work OCR can do locally.

### 1.2 Capture blindness while overlay is up

Current OCR (`win_ocr_words`) uses `ImageGrab.grab(region)` — a **GDI desktop blit** of visible pixels. When Orynn's overlay is foreground, the grabbed region may include the overlay or miss occluded app content.

Live vision already solved this for **read-only peek** via PrintWindow (`_capture_vision_jpeg`, `_capture_hwnd_image` in `providers.py`). OCR does not yet use the same capture path. **OCR peek** means: run Windows Media OCR on a PrintWindow frame of the target HWND, not on the visible desktop composite.

### 1.3 Architectural intent vs gap

Master strategy explicitly allows Live to cap at **UIA + OCR** and never grid:

> *"Live voice path — never grid-locate; cap at UIA + OCR or defer to back-office."*  
> — [windows-automation-research.md](../../windows-automation-research.md)

Implementation lags policy: Live caps at **UIA only**, deferring OCR to the back office.

---

## 2. Proposed Behavior

### 2.1 Escalation ladder (revised)

```
desktop_control click/type
│
├─ Consent gate (disruptive targets)
├─ Tier 1: UIA-only fast path (fast_invoke_only=True)
│   └─ ok → return success
│
├─ Tier 2: OCR mid-tier  ← NEW
│   ├─ PrintWindow capture of target app HWND
│   ├─ ocr_find_in_app (existing scoring policy)
│   ├─ pyautogui.click + input politeness gate
│   ├─ optional soft verify (_verify_clicked)
│   └─ ok → return success (control_layer: "OCR mid-tier")
│
├─ Electron consent gate (relaunch warning) — unchanged
└─ Tier 3: start_desktop_task (full agent: unlock, OCR retry, grid)
```

### 2.2 What does NOT change

| Concern | Policy |
|---------|--------|
| Grid-locate on Live | **Still forbidden** — voice cannot wait 1–4 s × 2 model calls |
| `look_at_screen` / `capture_window` | Read-only vision Q&A — not used for autonomous clicking |
| Golden Five / push-to-talk gateway | May keep pixel fallback enabled (`fast_invoke_only=False`) — separate path |
| Back-office `uia_click` full ladder | Unchanged |
| One desktop task at a time | Unchanged |

### 2.3 User-facing semantics

- Live should **not** expose a new tool to the model. OCR mid-tier is an **internal escalation step** inside `_desktop_control_route`, invisible to tool declarations.
- On OCR success, spoken outcome matches today: one short sentence ("Clicked Save in Notepad").
- On OCR miss, escalation message stays the same ("Trying the full agent").
- Optional prompt tweak (low priority): note that simple text clicks may use on-screen label matching — model should still call `desktop_control` once, not `look_at_screen` first for labeled buttons.

---

## 3. OCR Peek — Capture Design

### 3.1 Why PrintWindow for Live OCR

| Capture API | Overlay occludes target | Typical latency | Live vision today | Live OCR today |
|-------------|-------------------------|-----------------|-------------------|----------------|
| `ImageGrab` (GDI blit) | **Fails** — sees composite desktop | 20–80 ms | — | ✅ used |
| `PrintWindow` + `PW_RENDERFULLCONTENT` | **Often works** — HWND backing store | 50–200 ms | ✅ used | ❌ not used |
| `mss` monitor grab | Sees what user sees (incl. overlay) | 15–40 ms | Fallback mode | — |

**Recommendation:** Add `win_ocr_words_from_hwnd(hwnd)` (or `ocr_find_in_app(..., capture_mode="printwindow")`) that:

1. Resolves HWND from `app_hint` via existing `app_window_rect` / `resolve_hwnd_for_title_query`
2. Calls `providers._capture_hwnd_image(hwnd, max_edge=cap)` — same chain as Live vision (fullcontent → plain → BitBlt)
3. Runs `Windows.Media.Ocr` on the in-memory PIL image (no `ImageGrab`)
4. Maps word boxes from image space to screen coordinates using window client rect + any downscale from `max_edge`

### 3.2 Fallback within OCR peek

If PrintWindow returns black/stale (GPU-exclusive, minimized):

1. Try `ImageGrab` on `app_window_rect` **only if** target window is foreground and overlay is transparent/non-occluding in that region — optional, env-gated
2. Return OCR miss → proceed to agent escalation (do not guess)

### 3.3 Performance budget

| Step | Added latency |
|------|---------------|
| HWND resolve | 5–20 ms (cached) |
| PrintWindow 1080p cap | 50–200 ms |
| WinRT OCR | 80–400 ms |
| Click inject | 5–20 ms |
| **Total mid-tier** | **~150–650 ms** |

Still within the **&lt;1.5 s** voice click target from master strategy. Agent spawn remains 10–30 s+.

### 3.4 Coordinate fidelity

- Reuse the same physical-pixel convention as grid-locate and existing OCR word centres.
- When `_capture_hwnd_image` downscales for cap, scale bounding boxes back to screen space before click.
- Document multi-monitor risk (unchanged gap): OCR peek uses window rect; clicks must land in screen coordinates of that monitor.

---

## 4. Safety & Guardrails

### 4.1 Existing protections (reuse, do not weaken)

| Guard | Location | Role |
|-------|----------|------|
| OCR scoring threshold (≥44) | `ocr_find_in_app` | No bare substring clicks |
| No `q in t` on single tokens | `ocr_find_in_app` | Avoid "view" in "preview" |
| Input politeness gate | `tools._input_politeness_gate` | Don't fight user mouse/keyboard |
| Synthetic input note | `tools._note_synthetic_input` | Idle detection |
| `LIVE_CONSENT_RE` | `_desktop_control_route` | Disruptive clicks need spoken yes |
| Electron relaunch consent | `_desktop_control_route` | Before agent unlock |
| Busy gate | `_live_tool` | No interleaved desktop actions |

### 4.2 New Live-specific gates

| Gate | Rationale |
|------|-----------|
| **No grid** | Hard assert: mid-tier code path must not call `_grid_locate_click` |
| **Env kill switch** | `ORYNN_LIVE_OCR_MIDTIER=off` restores today's behavior instantly |
| **Text-only** | Mid-tier runs only for `action=click` with non-empty `query` (not icon/deictic "that") |
| **Overlay tag** | `control_layer: "OCR mid-tier"` in overlay payload for telemetry |
| **Adaptive memory** | On success, `_remember_adaptive_success(resolver_id="ocr_text_target")` — same as back-office |

### 4.3 Mouse movement disclosure

OCR mid-tier **will move the mouse** — the reason Live disabled pixel fallback originally. Mitigations:

- Keep tier **after** UIA-only attempt so invoke-pattern clicks remain mouseless
- Prefer **short spoken ack** before click only if total path exceeds ~800 ms (optional polish)
- Log `method: ocr_pixel` in tool result for postmortems

### 4.4 When to skip mid-tier

| Condition | Action |
|-----------|--------|
| `ORYNN_LIVE_OCR_MIDTIER=off` | Skip to agent escalation |
| `ocr_available()` false | Skip |
| No resolvable HWND / zero-size rect | Skip |
| PrintWindow black frame | Skip (no ImageGrab guess on Live by default) |
| `action=type` | **Phase 2** — type-into-field OCR is higher risk; ship click first |
| Deictic target without label | Model should `look_at_screen` first — mid-tier won't help |

---

## 5. Implementation Plan

### Phase 1 — PrintWindow OCR capture (foundation)

**Files:** `app/widget/desktop_features.py`, `app/providers.py`

1. Add `win_ocr_words_from_image(img, origin_left, origin_top, scale)` → `[{text, x, y, w, h}]` in screen coords
2. Add `ocr_find_in_app_printwindow(query, app_hint)` wrapping HWND resolve + `_capture_hwnd_image` + OCR
3. Unit tests with synthetic PIL images (no Live session)

**Acceptance:** OCR on a static test image returns correct word centres; HWND path tested with mocked capture.

### Phase 2 — Live mid-tier wire-up

**Files:** `app/widget/textbox_overlay.py`, `app/tools.py`

1. Add `tools._ocr_click_fallback_peek(query, app)` using PrintWindow capture path (or flag on existing fallback)
2. In `_desktop_control_route`, after fast UIA miss:
   ```text
   if ocr_midtier_enabled and action == "click":
       ocr = tools._ocr_click_fallback_peek(query, app)
       if ocr.ok: return ocr_as_live_dict
   ```
3. Do **not** set `allow_pixel_fallback=True` on the fast path — keep tiers explicit
4. Map `ToolResult` to Live dict format with `control_layer` visible in overlay

**Acceptance:** `desktop_control` click with UIA miss + visible text label succeeds without `start_desktop_task` in harness tests.

### Phase 3 — Telemetry & rollout

**Files:** `docs/BENCHMARKS.md`, logging

1. Default `ORYNN_LIVE_OCR_MIDTIER=off` for one release
2. Enable in dev/staging; compare escalation rate from `logs/run_desktop_live.log` and `textbox_labels.jsonl`
3. Flip default to `on` when false-click rate &lt; 2% on top-20 apps

### Phase 4 — Type action (optional)

Extend mid-tier to `action=type` only when `query` names a field with visible label adjacent to editable area — higher complexity; defer until click tier is stable.

---

## 6. Configuration

| Env var | Default | Meaning |
|---------|---------|---------|
| `ORYNN_LIVE_OCR_MIDTIER` | `off` → `on` after bake | Enable OCR mid-tier in `_desktop_control_route` |
| `ORYNN_LIVE_OCR_CAPTURE` | `printwindow` | `printwindow` \| `imagegrab` \| `auto` |
| `ORYNN_LIVE_OCR_MIN_SCORE` | `44` | Override `ocr_find_in_app` threshold (debug) |
| `ORYNN_LIVE_SCREEN_CAPTURE` | `window` | Unchanged — vision peek mode |

---

## 7. Test Plan

| Test | Type | Assert |
|------|------|--------|
| UIA hit → no OCR call | Unit | Mock `invoke_ui_element` ok; `_ocr_click_fallback_peek` not called |
| UIA miss + OCR hit | Unit | Mock OCR coords; click mocked; `ok: true`, layer OCR mid-tier |
| UIA miss + OCR miss → agent | Integration | `_desktop_control_route` calls `start_desktop_task` |
| `ORYNN_LIVE_OCR_MIDTIER=off` | Unit | Skips OCR; direct agent escalation |
| PrintWindow capture in OCR | Unit | `test_capture_vision_jpeg_uses_printwindow_when_window_mode` pattern |
| Grid never called from Live route | Unit | Patch `_grid_locate_click`; assert not called |
| Consent gate before mid-tier | Unit | Disruptive goal blocks before OCR |
| Electron consent after OCR miss | Unit | Unchanged behavior |

Add to `tests/test_gemini_live.py` and `tests/test_hybrid_resolver.py` — no Live desktop session required for unit coverage.

---

## 8. Success Metrics

| Metric | Baseline (today) | Target |
|--------|------------------|--------|
| `desktop_control` click → `start_desktop_task` escalation rate | Measure from logs | **−30–50%** for text-label intents |
| P50 click latency (UIA miss cases) | ~15–30 s (agent) | **&lt;1 s** (OCR path) |
| OCR mid-tier false clicks | — | **&lt;2%** of OCR attempts |
| Live sessions with overlapping agent + Live click fights | Storm reliability logs | No increase |
| User-reported "it clicked the wrong thing" | Qualitative | No increase |

Aggregate `control_layer` from overlay payloads: expect growth in `"OCR mid-tier"` with corresponding drop in agent spawns for single-click goals.

---

## 9. Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Wrong OCR click (similar labels) | Medium | Existing score threshold; no substring match; agent still available on miss |
| Mouse jump surprises user | Medium | UIA-first ordering; politeness gate; optional verbal cue |
| PrintWindow black on GPU apps | Medium | Fail safe to agent; do not retry grid on Live |
| Overlay DPI / scale mismatch | Low | Reuse vision capture scaling math; test at 125%/150% |
| Blocking `asyncio.run` in OCR on UI thread | Low | Acceptable for single shot; executor hoist if profiling shows jank |
| Regression: more clicks without consent | Low | Consent gate runs **before** mid-tier, unchanged |

---

## 10. Alternatives Considered

| Alternative | Verdict |
|-------------|---------|
| Enable `allow_pixel_fallback=True` on Live fast path | **Rejected** — also enables grid-locate in `uia_click`; violates voice latency policy |
| `look_at_screen` → model returns (x,y) click | **Rejected** — hallucination risk; research doc forbids raw vision clicks on Live |
| New `ocr_click` Live tool for model to call | **Rejected** — adds tool confusion; internal tier is invisible to model |
| RapidOCR instead of Windows OCR | **Deferred** — measure Windows OCR miss rate first per research doc |
| Always escalate to agent (status quo) | **Safe but slow** — keep as `ORYNN_LIVE_OCR_MIDTIER=off` fallback |

---

## 11. Dependencies & Sequencing

| Dependency | Notes |
|------------|-------|
| [06-playbook-wiring.md](./06-playbook-wiring.md) | Synergy: playbooks recording `ocr_text_target` prime mid-tier on repeat visits |
| [03-open-settings-tool.md](./03-open-settings-tool.md) | Orthogonal — URI launch reduces UIA tree-walk, not OCR need |
| Storm backoffice `02-tools-uia-click-review.md` | Confirms OCR tier maturity in `tools.py` |
| Reliability: task abandon race | Fewer agent spawns reduces abandon surface area |

**Recommended order:** Phase 1–2 ship together behind env flag; enable after pytest green and one manual voice smoke on Notepad + Calculator + File Explorer.

---

## 12. Open Questions

1. **Type action:** Should mid-tier OCR locate a field label then tab-click, or stay click-only for v1?
2. **Verification:** Should OCR mid-tier require `_verify_clicked` success before returning `ok`, or trust OCR score alone (back-office trusts score)?
3. **ImageGrab fallback:** Enable under `ORYNN_LIVE_OCR_CAPTURE=auto` when PrintWindow fails but window is foreground?
4. **Spoken transparency:** Should Live say "I found it on screen" when using OCR vs silent success?

---

## References

- [04-vision-ocr-pixel.md](../../windows-automation-research/04-vision-ocr-pixel.md) — OCR ladder, PrintWindow vs ImageGrab
- [00-master-strategy.md §2](../../windows-automation-research/00-master-strategy.md#2-orchestration-decision-tree) — Live decision tree
- [Windows.Media.Ocr](https://learn.microsoft.com/en-us/uwp/api/windows.media.ocr)
- [PrintWindow function](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-printwindow)
- `textbox_overlay._desktop_control_route` — current escalation implementation
- `tools._ocr_click_fallback` — back-office OCR click to reuse

---

*This document is part of the subagent-storm proposals series. Implementation is explicitly out of scope for this file.*

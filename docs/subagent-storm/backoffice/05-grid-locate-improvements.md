# 05 — Grid-Locate Improvements (Back-Office)

**Date:** 2026-06-22  
**Scope:** Review of `app/grid_locate.py` and its integration as the last-resort vision click fallback in the back-office agent.  
**Related:** `app/tools.py` (`_grid_locate_click`, `_wait_foreground`), `tests/test_grid_locate.py`, `scripts/grid_locate_smoke.py`, `docs/windows-automation-research/04-vision-ocr-pixel.md`

---

## 1. What it does today

`grid_locate.py` implements a two-stage **Set-of-Mark (SoM)** locator, ported from Clicky `ai/universal_locator.py`:

| Stage | Grid | Cells | Role |
|-------|------|-------|------|
| 1 — coarse | 12 × 8 | 96 | Find region on full primary-monitor screenshot |
| Zoom | 3 × 3 cells around pick | — | Crop ~¼ of screen |
| 2 — fine | 6 × 6 | 36 | Sub-cell precision inside crop |

**Call chain (agent only):**

```
uia_click(query, allow_pixel_fallback=True)
  → invoke_ui_element (UIA)
  → _ocr_click_fallback
  → _grid_locate_click
       → focus_window(app)
       → _wait_foreground(app, 1.2s)
       → grid_locate.locate(query)   # mss primary monitor
       → pyautogui.click(x, y)
```

**Fail-safe contract** (correct and well-tested):

- `{"cell": 0}`, parse failure, missing key, capture error, or `ORYNN_GRID_LOCATE=0` → `None` (no click)
- Stage-2 miss → centre of stage-1 cell (coarser but bounded)
- Model 429/error → fall through model chain; a model that *responds* but can't parse is treated as final (no further models)

Live path sets `allow_pixel_fallback=False` and never reaches grid-locate.

---

## 2. Strengths (keep)

1. **Clear tiering** — documented as agent-only; never mixed into Live voice UX.
2. **Fail-safe by default** — `locate()` returns `None` on ambiguity; caller reports UIA miss instead of a wrong click.
3. **Model fallback chain** — `gemini-2.5-flash` → lite variants; 429 on one bucket does not kill the click.
4. **Coordinate math is sound** — fractional mapping through resize/crop/zoom, then `mon_left`/`mon_top` offset; pinned by `test_locate_maps_two_stage_picks_to_screen_pixel`.
5. **Foreground gating lives in the right place** — `_wait_foreground` in `tools.py` fixes the Chrome race (fixed sleep was insufficient).
6. **Adaptive memory** — successful grid clicks record `resolver_id: vision_grid_locate` for lazy playbooks.
7. **Operational knobs** — `ORYNN_GRID_LOCATE`, `ORYNN_GRID_MODEL(S)`, `ORYNN_GRID_DEBUG`.

---

## 3. Gaps and risks

### P0 — Correctness / coverage

| Issue | Detail | Impact |
|-------|--------|--------|
| **Primary monitor only** | `mss.monitors[1]` always; no HWND/monitor pick | Apps on display 2 locate/click wrong region or miss entirely |
| **Full-screen capture** | No crop to target app window | Dense UIs (IDEs, browsers with many tabs) add noise; model may pick wrong cell |
| **Stage-2 failure → stage-1 centre** | Lines 188–190 in `grid_locate.py` | Up to ~80–120 px error; acceptable for large buttons, risky for small toolbar icons |
| **Loose JSON parsing** | `_parse_cell` falls back to first `\b(\d+)\b` | Verbose model reply could match wrong number despite “JSON only” prompt |

### P1 — Reliability / UX

| Issue | Detail | Impact |
|-------|--------|--------|
| **Two sequential API calls** | ~1–4 s latency per grid click | Agent steps feel slow; user may move mouse/window during wait |
| **No structured output** | Regex on free text vs Gemini `response_schema` | Fragile parsing; harder to debug |
| **Capture timing** | Snapshot after `_wait_foreground` but no verify app still foreground | Alt-tab during inference → wrong screenshot |
| **Minimized / occluded windows** | Full-screen grab includes whatever is on top | “Not visible” or mis-click on wrong overlay |
| **Games / exclusive fullscreen** | Black or stale frames | Documented elsewhere; grid should short-circuit |

### P2 — Observability / cost

| Issue | Detail | Impact |
|-------|--------|--------|
| **Debug is print-only** | `ORYNN_GRID_DEBUG` → stdout | No structured logs for agent overlay / telemetry |
| **No per-stage metrics** | — | Can't tune grid density or measure miss rate |
| **Cost per click** | 2 × JPEG ~1280px @ q=82 | Dominates agent step cost when grid fires often |

### P3 — Test gaps

| Gap | Notes |
|-----|-------|
| Stage-2 `None` fallback path | Not unit-tested (only happy path + full `None`) |
| `_draw_grid` / resize / upscale | No visual or dimension assertions |
| `_ask_cell` model chain | No test for 429 fallthrough vs parse-fail stop |
| Multi-monitor | No test harness |
| E2E | `grid_locate_smoke.py` (taskbar clock) and `live_app_probe.py` exist but are manual/key-dependent |

---

## 4. Recommended improvements (prioritized)

### 4.1 P0 — Multi-monitor and window-scoped capture

**Goal:** Locate on the monitor/window where the target app actually lives.

**Approach (mirror Clicky `screen/capture.py`):**

1. Accept optional `app` / `hwnd` in `locate()` (or a new `locate_in_rect(left, top, width, height, monitor_origin)`).
2. In `_grid_locate_click`, pass `app_rect` from `_app_rect_payload(app)` when available.
3. Crop capture to app client rect (with small margin) before stage 1; map fractions back through crop offset.
4. Select `mss` monitor by overlap with window rect, not hard-coded `[1]`.

**Acceptance:** Window on secondary display → smoke test places pixel inside app rect.

### 4.2 P0 — Safer parsing

**Options (pick one or combine):**

- Use Gemini `response_mime_type="application/json"` + `response_schema` for `{"cell": int}`.
- If keeping regex: prefer strict JSON parse first; only accept `cell` key; reject replies with extra digits.
- On parse failure after a successful HTTP response: optionally retry **once** with “reply was invalid, try again” (same model) before `None`.

**Acceptance:** `test_parse_cell_variants` extended with `"cell 42 is best"` → must not return 42 unless quoted in JSON.

### 4.3 P1 — Tighten stage-2 failure policy

Today stage-2 `None` still clicks (stage-1 centre). Options:

| Policy | Pros | Cons |
|--------|------|------|
| **A. Keep centre fallback** (current) | Always attempts something | Wrong click on small targets |
| **B. Return `None` if stage-2 fails** | Fully fail-safe | More UIA misses |
| **C. Third micro-stage** (e.g. 4×4 on stage-1 cell only) | Better precision | +1 API call |

**Recommendation:** **B** for icons/small controls (config flag `ORYNN_GRID_STRICT=1`); keep **A** as default for backward compatibility until metrics justify change.

### 4.4 P1 — Reduce noise before inference

1. Crop to foreground window or supplied `app_rect`.
2. Optionally dim/blur regions outside crop (SoM models sometimes attend to clutter).
3. Consider slightly higher JPEG quality on stage 2 (labels are small).

**Acceptance:** `live_app_probe` success rate improves on Chrome + Electron apps without increasing false clicks.

### 4.5 P1 — Structured telemetry

Emit overlay-friendly metadata from `_grid_locate_click`:

```json
{
  "method": "grid_locate",
  "stage1_cell": 42,
  "stage2_cell": 15,
  "model": "gemini-2.5-flash",
  "infer_size": [1280, 853],
  "crop_rect": { "left": 0, "top": 0, "width": 640, "height": 400 }
}
```

Wire `control_layer: "vision grid-locate"` (already present) to include stage cells in debug builds.

### 4.6 P2 — Performance and cost

- **Parallelism:** Not applicable (stage 2 depends on stage 1).
- **Cache:** Skip second call if stage-1 cell is huge and target description implies a large control (heuristic; low priority).
- **Adaptive grid density:** Wider coarse grid (e.g. 16×10) on 4K after window crop — same API cost, better stage-1 resolution.
- **Profile short-circuit:** If `adaptive_windows` already has `vision_grid_locate` for this app, still run grid but consider skipping OCR retry (already ordered correctly).

### 4.7 P2 — DPI and coordinate alignment

`tools.py` sets per-monitor DPI awareness at import. Verify:

- `mss` grab size matches `pyautogui.click` coordinate space on 125%/150% scaling.
- Add one HiDPI integration test or document manual checklist.

### 4.8 P3 — Test additions

| Test | Purpose |
|------|---------|
| `test_locate_stage2_miss_uses_stage1_center` | Document current fallback coordinates |
| `test_locate_with_app_rect_crop` | After 4.1 implemented |
| `test_ask_cell_falls_through_on_429` | Mock `generate_content` raise → next model |
| `test_ask_cell_stops_on_parseable_zero` | `{"cell": 0}` → `None`, no further models |

Keep `grid_locate_smoke.py` as optional CI job (needs `GEMINI_API_KEY`).

---

## 5. Non-goals (for this module)

- **Live / voice path** — grid-locate must remain blocked (`allow_pixel_fallback=False`).
- **Raw x,y vision prompting** — anti-pattern; stay on SoM cells.
- **Replacing UIA/OCR** — grid is last resort only; lazy playbooks should reduce repeat grid use.

---

## 6. Implementation sketch (minimal P0 slice)

```python
# grid_locate.py — proposed signature extension
def locate(
    target: str,
    *,
    crop_rect: tuple[int, int, int, int] | None = None,  # left, top, right, bottom (screen coords)
    monitor: dict | None = None,  # mss monitor dict; default primary
) -> tuple[int, int] | None:
    ...
```

```python
# tools.py — _grid_locate_click
app_rect = self._app_rect_payload(app)
crop = None
if app_rect:
    crop = (app_rect["left"], app_rect["top"],
            app_rect["left"] + app_rect["width"],
            app_rect["top"] + app_rect["height"])
hit = grid_locate.locate(query, crop_rect=crop)
```

---

## 7. Environment reference

| Variable | Default | Effect |
|----------|---------|--------|
| `ORYNN_GRID_LOCATE` | `1` | `0`/`off`/`false`/`no` disables |
| `ORYNN_GRID_MODEL` | — | Single model override |
| `ORYNN_GRID_MODELS` | flash → flash-lite chain | Comma-separated fallback list |
| `ORYNN_GRID_DEBUG` | unset | Print model replies/errors |
| `GEMINI_API_KEY` | via `gemini_api_key()` | Required |

---

## 8. Success metrics

| Metric | Target |
|--------|--------|
| Grid click success rate (probe suite) | ≥ 80% on Electron + canvas apps in top-10 list |
| False click rate | 0% (fail-safe `None` preferred over wrong click) |
| P95 latency | < 5 s (two stages, one model each) |
| Grid invocations per task | Decrease over time via `vision_grid_locate` playbooks |

---

## 9. File map

| File | Role |
|------|------|
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\grid_locate.py` | Core SoM locator |
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\tools.py` | `_grid_locate_click`, `_wait_foreground`, `uia_click` ladder |
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\tests\test_grid_locate.py` | Unit tests (math + fail-safe) |
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\scripts\grid_locate_smoke.py` | E2E clock smoke |
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\scripts\live_app_probe.py` | Multi-app probe with grid |

---

## 10. Summary

`grid_locate.py` is a **solid, fail-safe last resort** for the agent path: clear scope, good tests for coordinate math, and sensible model fallthrough. The highest-impact improvements are **window/monitor-scoped capture**, **stricter response parsing**, and a **policy decision on stage-2 miss** (fail-safe vs coarse click). Observability and HiDPI validation follow. No changes needed to the Live/agent split — only harden the back-office tier.
```

---

### Key code references

Fail-safe entry and monitor selection:

```124:152:C:\Users\ACER\Desktop\Ai_computer\Orynn\app\grid_locate.py
def locate(target: str) -> Optional[tuple[int, int]]:
    ...
        with mss.mss() as sct:
            mons = sct.monitors
            mon = mons[1] if len(mons) > 1 else mons[0]
            shot = sct.grab(mon)
```

Stage-2 miss fallback (improvement candidate):

```182:190:C:\Users\ACER\Desktop\Ai_computer\Orynn\app\grid_locate.py
    if p2:
        ...
    else:  # stage-2 whiffed → center of the stage-1 cell
        fx = (s1_col + 0.5) / STAGE1_COLS
        fy = (s1_row + 0.5) / STAGE1_ROWS
```

Loose parse fallback:

```80:88:C:\Users\ACER\Desktop\Ai_computer\Orynn\app\grid_locate.py
def _parse_cell(text: str, max_n: int) -> Optional[int]:
    ...
    m = re.search(r'"?cell"?\s*[:=]\s*(\d+)', text, re.IGNORECASE) or re.search(r"\b(\d+)\b", text)
```

To persist this file, switch to **Agent mode** and ask to create `docs\subagent-storm\backoffice\05-grid-locate-improvements.md` with the content above.

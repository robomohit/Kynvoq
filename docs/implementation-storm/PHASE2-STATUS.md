# Phase 2 Implementation Status

**Date:** 2026-06-22  
**Coordinator:** Phase 2 subagent  
**Verification:** pytest offline only (no live Gemini)

---

## Workstream summary

| WS | Name | Status | Notes |
|----|------|--------|-------|
| WS4 | Bubble & Speech | **done** | `sanitize_bubble_text`, task churn mute, handoff-driven `send_task_update` |
| WS3 | Task Lifecycle | **done** | Grace period (pre-existing), `HandoffResult`, `user_goal`/`prompt_goal`, 30s busy TTL |
| WS1 | Launch & Registry | **done** | 24 registry entries, `resolve_launch_target`, `open_settings`, `launch_app` Live tool |
| WS2 | Specialist Registry | **done** | `SpecialistSpec`, exclusion groups, agent `.md` profiles |
| WS6 | Back Office | **done** | Playbook hints Calculator/Notepad; UIA cache 2s TTL (existing) |
| WS7 | OCR Mid-Tier | **done** | `ocr_live_capture`, `frame_age_ms` in `look_at_screen` |
| WS8 | Test Hardening | **done** | 3 new test modules + Spotify fixture |
| WS5 | Browser (optional) | **deferred** | P1 — not in Phase 2 budget |

---

## Pytest results

| Suite | Result |
|-------|--------|
| `tests/test_gemini_live.py` | pass |
| `tests/test_task_abandon_grace.py` | pass |
| `tests/test_quiet_companion.py` | pass |
| `tests/test_fast_path.py` | pass |
| `tests/test_bubble_sanitizer.py` | pass |
| `tests/test_specialist_registry.py` | pass |
| `tests/test_launch_resolver.py` | pass |
| `tests/test_adaptive_windows.py` | pass |
| `tests/test_grid_locate.py` | pass |
| **Total (bundle run)** | **235 passed, 0 failed** |

Command:
```powershell
cd C:\Users\ACER\Desktop\Ai_computer\Orynn
python -m pytest tests/test_gemini_live.py tests/test_task_abandon_grace.py tests/test_quiet_companion.py tests/test_fast_path.py tests/test_bubble_sanitizer.py tests/test_specialist_registry.py tests/test_launch_resolver.py tests/test_adaptive_windows.py tests/test_grid_locate.py -q
```

---

## Phase 3 gate readiness

| Gate | Ready? | Blocker / note |
|------|--------|----------------|
| Spotify no bubble leak | **partial** | Sanitizer + mute in place; live `launch_app` + foreground verify need E03 spoken test |
| Calculator e2e | **partial** | Playbook hints shipped; needs E04 live run |
| No silent terminal turns | **yes** | `send_task_update` on all terminal paths via handoff |
| Label log clean | **yes** | `ORYNN_LABEL_LOG=1` records `muted` + reasons |

---

## Blockers for Phase 3 live testing

1. **No live Gemini run in Phase 2** — model routing to `launch_app` vs `start_desktop_task` unverified with real audio.
2. **`resolve_launch_target` tier-2 index** — curated registry + start fallback only; full `Get-StartApps` session index not built (unknown apps may still fall through to desktop job).
3. **`scripts/live_vision_smoke.py`** — OCR mid-tier needs live channel verification (WS7 acceptance item 3).
4. **WS5 `browser_task`** — deferred; web_search reliability matrix is Phase 3 F06.
5. **`electron_unlock` defer when desktop active** — not wired; low risk for Spotify gate but noted for Calculator/Electron apps.

---

## Files created

- `app/bubble_sanitizer.py`
- `app/handoff.py`
- `app/launch.py`
- `app/specialists/{__init__,registry,loader}.py`
- `Orynn/agents/{launch,uia_act,vision_peek,desktop_job}.md`
- `tests/test_bubble_sanitizer.py`
- `tests/test_specialist_registry.py`
- `tests/test_launch_resolver.py`
- `tests/fixtures/spotify_label_sequence.jsonl`

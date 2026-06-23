# Phase 2 Changelog (for other agent)

**Date:** 2026-06-22  
**Scope:** WS1–WS4, WS6–WS8 implemented; WS5 deferred (optional P1)

---

## WS4 — Bubble & Speech Sanitization

| File | What | Why |
|------|------|-----|
| `app/bubble_sanitizer.py` | **NEW** `sanitize_bubble_text()` denylist | Central trust layer: block `Failed: Server restarted`, UIA dumps, JSON blobs |
| `app/widget/textbox_overlay.py` | Apply sanitizer in `_set_label`; log `bubble_sanitizer_denylist` | Every bubble emit sanitized before paint |
| `app/widget/gemini_live.py` | System prompt: no success until `ok:true` + verify | Honest speech timing for launch |

## WS3 — Task Lifecycle & Handoff

| File | What | Why |
|------|------|-----|
| `app/handoff.py` | **NEW** `HandoffResult`, `handoff_from_terminal_event`, `launch_handoff` | Typed schema; bubble never sees `debug_reason` |
| `app/models.py` | `user_goal`, `prompt_goal` on `TaskRecord` | Separate display goal from hardened prompt goal |
| `app/main.py` | `TaskIn.user_goal`/`prompt_goal`; persist on create/queue | API stores both goals |
| `app/widget/textbox_overlay.py` | `_capture_live_task_outcome` uses handoff; `_busy_since` 30s TTL watchdog; `build_task_payload` sends both goals | Proactive `send_task_update` with `user_message` only; stale busy gate clears |

## WS1 — Launch & Registry

| File | What | Why |
|------|------|-----|
| `app/tools.py` | Expanded `_KNOWN_LAUNCH_APPS` (+Spotify, Edge, Chrome, Discord, …); `detect_app_launch_intent` calls resolver; `open_settings()` | Registry + ladder for voice fast-path |
| `app/launch.py` | **NEW** `resolve_launch_target`, `verify_launch_foreground`, `open_settings_uri` | URI → settings → start ladder; 2s foreground verify |
| `app/widget/textbox_overlay.py` | `_live_launch_app` sync specialist; `launch_app` in `_live_tool` | HandoffResult to Live only |
| `app/widget/gemini_live.py` | `launch_app` declaration + routing examples | Live can open apps without full desktop job |
| `Orynn/agents/launch.md` | **NEW** declarative profile | Specialist registry docs |

## WS2 — Specialist Registry

| File | What | Why |
|------|------|-----|
| `app/specialists/registry.py` | **NEW** `SpecialistSpec`, `EXCLUSION_GROUPS` | Declarative platform; desktop + vision_peek mutual exclusion |
| `app/specialists/loader.py` | **NEW** loader + declaration bridge | Generate declarations at connect |
| `app/widget/gemini_live.py` | Exclusion groups from registry (desktop, vision_peek) | Prevent dual desktop/vision tools per batch |
| `Orynn/agents/{uia_act,vision_peek,desktop_job}.md` | **NEW** frontmatter profiles | Documented contracts |

## WS6 — Back Office

| File | What | Why |
|------|------|-----|
| `app/adaptive_windows.py` | `playbook_for_app`, `format_playbook_hint` (Calculator, Notepad) | Auto playbook hints on observe |
| `app/tools.py` | Playbook hint appended in `adaptive_observe` | Agent sees happy-path steps |
| `app/tools.py` | UIA cache already 2s TTL (verified) | WS6 acceptance met |

## WS7 — OCR Mid-Tier

| File | What | Why |
|------|------|-----|
| `app/providers.py` | **NEW** `ocr_live_capture()` | OCR pass with confidence |
| `app/widget/textbox_overlay.py` | `_live_look_at_screen` OCR shortcut + `frame_age_ms` | Skip full vision when text confidence ≥ 55% |

## WS8 — Tests

| File | What | Why |
|------|------|-----|
| `tests/test_bubble_sanitizer.py` | **NEW** denylist + golden mute replay | G01, G05 |
| `tests/test_specialist_registry.py` | **NEW** registry + declarations | WS2 |
| `tests/test_launch_resolver.py` | **NEW** Spotify + 10 registry intents | WS1, G04 |
| `tests/fixtures/spotify_label_sequence.jsonl` | **NEW** golden fixture | Phase 4 forensics |
| `tests/test_gemini_live.py` | `launch_app` in declaration set | WS2 compat |

## WS5 — Browser (deferred)

Not implemented in Phase 2 (optional P1). `browser_task` Live tool remains future work.

---

## Pytest (end of Phase 2)

```
235 passed — bundle:
  test_gemini_live, test_task_abandon_grace, test_quiet_companion, test_fast_path,
  test_bubble_sanitizer, test_specialist_registry, test_launch_resolver,
  test_adaptive_windows, test_grid_locate
```

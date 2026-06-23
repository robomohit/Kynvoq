# 10 — Launch Registry Gaps vs Windows Automation Research

**Date:** 2026-06-22  
**Scope:** Reliability gaps between Orynn's voice launch registry (`_KNOWN_LAUNCH_APPS` / `detect_app_launch_intent`) and recommendations in `docs/windows-automation-research/`.  
**Code reviewed:** `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\tools.py`, `app\agent.py`, `app\widget\textbox_overlay.py`, `tests\test_voice_and_env.py`, `tests\test_fast_path.py`  
**Research reviewed:** `docs\windows-automation-research\03-universal-launch.md`, `02-uris-protocols-shell.md`, `00-master-strategy.md`, `windows-automation-research.md`

---

## Executive Summary

Orynn's launch architecture is **correctly split** (narrow voice fast-path + planner fallback), but the fast-path registry is **stuck at tier 0** while research calls for expanding tier 0 to ~20–30 safe OS entries and building tiers 2–4 (AUMID, `.lnk`, `Get-StartApps` index). Today:

| Area | Code today | Research target | Gap severity |
|------|------------|-----------------|--------------|
| Voice registry size | 7 apps, 9 aliases | ~20–30 OS built-ins + settings intents | **High** — voice misses common commands |
| Settings deep links | Only `settings` → `ms-settings:` | Bluetooth, display, sound, wifi, … | **High** — forces Settings tree-walk |
| Universal resolver | None | `resolve_launch_target` / `launch_app` + session index | **Critical** — third-party apps hit Win+Search |
| `open_uri` / `open_aumid` tools | None | Dedicated tools with verify contract | **High** |
| `ms-settings` catalog in tools | Prompt-only (`DESKTOP_HARDENING`) | `open_settings(page)` or registry aliases | **Medium** |
| Fuzzy / index matching | Exact lookup only | Optional fuzzy against `_launch_index` | **Medium** |
| AUMID launch path | Not wired | `explorer shell:AppsFolder\<AUMID>` | **High** for UWP / Store apps |
| Start Menu `.lnk` index | Not wired | Session cache from Programs folders | **High** for user-installed apps |

**Reliability impact:** Pure voice launches outside the 7-app set either fall through to the LLM planner (slower, can mis-report) or follow `DESKTOP_HARDENING` Win+Search guidance (fragile, build-dependent). Settings intents like "open Bluetooth settings" have no fast-path and invite UIA tree-walk — the primary anti-pattern documented in research.

---

## Current Implementation (Verified)

### Registry (`app/tools.py`)

```python
_KNOWN_LAUNCH_APPS = {
    "notepad", "calculator"/"calc", "paint"/"ms paint"/"mspaint",
    "wordpad", "settings", "task manager"
}
# → (launch_command, window_title) tuples
```

**Design intent (code comments):** Deliberately narrow — only built-ins with stable `start` commands and matchable titles. Third-party apps intentionally excluded.

### Intent detector

- `detect_app_launch_intent(goal)` — verb regex, `_LAUNCH_EXTRA_RE` rejects multi-step (`and`, `then`, `to`, …), exact dict lookup only.
- **No** fuzzy match, **no** session index, **no** settings-intent synonyms beyond `"settings"`.

### Fast-path wiring (works as designed)

| Entry point | Behavior |
|-------------|----------|
| `agent.py` `run_task` | `detect_app_launch_intent` → `open_known_app` — no LLM |
| `textbox_overlay.py` `build_task_payload` | Skips `DESKTOP_HARDENING` bloat when intent detected |
| `open_known_app` | Focus-if-open else detached launch + `wait_for_window` |
| `_SINGLE_INSTANCE_APPS` | Notepad, Calculator, Paint only |

### Partial support elsewhere

| Mechanism | Status |
|-----------|--------|
| `_guess_launch_target_title` | Has `uri_titles` for `ms-settings`, `ms-clock`, `ms-photos`, etc. — used by `run_command` GUI path, **not** voice registry |
| `_looks_like_gui_launch` | Recognizes `start`, `explorer`, bare notepad/calc/mspaint |
| `resolve_app_exe` | Running-process resolution only — not cold launch |
| `DESKTOP_HARDENING` | Win+Search as tier-6 fallback for unknown apps |

---

## Research Recommendations Not Yet Implemented

### From `03-universal-launch.md` §10.2 — proposed registry additions

All **missing** from `_KNOWN_LAUNCH_APPS`:

| Spoken alias | Launch command | Window title |
|--------------|----------------|--------------|
| file explorer / explorer | `start explorer` | File Explorer |
| command prompt / cmd | `start cmd` | Command Prompt |
| powershell | `start powershell` | Windows PowerShell |
| terminal / windows terminal | `start wt` | Windows Terminal |
| control panel | `start control` | Control Panel |
| snipping tool / snip | `start ms-screenclip:` | Snipping Tool |
| photos | `start ms-photos:` | Photos |
| clock / alarms | `start ms-clock:` | Clock |
| bluetooth / bluetooth settings | `start ms-settings:bluetooth` | Settings |
| display / display settings | `start ms-settings:display` | Settings |
| sound / sound settings | `start ms-settings:sound` | Settings |
| wifi / wi-fi / network settings | `start ms-settings:network-wifi` / `network` | Settings |

### From `03-universal-launch.md` §10.3–10.4 — new tools

| Tool | Purpose | Code status |
|------|---------|---------------|
| `launch_app(name)` | Curated → session index → start/AUMID/.lnk | ❌ |
| `launch_aumid(aumid)` | `explorer shell:AppsFolder\<AUMID>` | ❌ |
| `list_start_apps` | Debug / agent discovery | ❌ |
| `build_launch_index()` / `_refresh_launch_index()` | Session-start `Get-StartApps` + `.lnk` enum | ❌ |
| `resolve_launch_target(name)` | Universal resolver for planner path | ❌ |

### From `02-uris-protocols-shell.md` §7

| Recommendation | Status |
|----------------|--------|
| `open_uri` with `shell:` vs URI branch | ❌ |
| Expand settings catalog beyond 7 voice launches | ❌ (265 slugs documented; 1 wired) |
| Cache AUMID lookups per machine | ❌ |
| Verify protocol before deep link | ❌ |

### From `00-master-strategy.md` P0

1. Expand `_KNOWN_LAUNCH_APPS` + spoken intent → URI map — **not done**
2. `open_settings(suffix)` and `launch_aumid(aumid)` — **not done**

### From `windows-automation-research.md` gaps table

| Gap | Suggested fix | Status |
|-----|---------------|--------|
| Narrow launch registry | `open_uri`, `open_aumid`, expand registry | Open |
| No ms-settings catalog in tools | `open_settings(page)` | Open |
| Win+Search not wrapped | Skip — too fragile | Correctly skipped; still prompt-only fallback |

---

## Tier Stack Gap (Launch Ladder)

Research defines an 8-tier launch stack. Orynn coverage:

| Tier | Mechanism | Orynn |
|------|-----------|-------|
| 0 | Voice fast-path (`_KNOWN_LAUNCH_APPS`) | ✅ 7 apps only |
| 1 | `start` / Run / `ms-settings:` via `run_command` | ✅ planner path |
| 2 | AUMID / `shell:AppsFolder` | ❌ |
| 3 | Start Menu `.lnk` index | ❌ |
| 4 | `Get-StartApps` name → AppID | ❌ |
| 5 | `where.exe` / PATH / install roots | Partial |
| 6 | Win+Search UI automation | Prompt only (`DESKTOP_HARDENING`) |
| 7 | `winget list` inventory | ❌ |

**Architectural gap:** Research says the missing piece is a **runtime app index** (tiers 2–4) with tier 0 as curated override — not implemented.

---

## Reliability Failure Modes (Gaps → Symptoms)

| User utterance | Current path | Failure mode |
|----------------|--------------|--------------|
| "open bluetooth settings" | Planner + Win+Search or Settings UIA | Slow; tree-walk anti-pattern |
| "open discord" / "open chrome" | `None` from detector → planner | LLM latency; Win+Search fragility |
| "open photos" | `None` (not in registry) | Same |
| "open terminal" | `None` if `wt` not on PATH | Planner may fail on machines without WT |
| "open notepad to write a note" | `None` (`to` in `_LAUNCH_EXTRA_RE`) | Correct rejection — no gap |
| "switch to settings" | `ms-settings:` home only | Cannot land on sub-page by voice |

**Positive:** Fast-path verification contract is solid — `open_known_app` + `wait_for_window` prevents optimistic "done" for the 7 known apps (`test_fast_path.py`, `GOLDEN_FIVE.md`).

---

## Test Coverage Gaps

| Covered | Not covered |
|---------|-------------|
| Pure launch verbs for 7 apps | Proposed registry additions (explorer, ms-settings:bluetooth, …) |
| Multi-step rejection (`and`, `to`) | `wt` absent on machine |
| Fast-path bypasses LLM | Index-based resolution |
| `open chrome` → `None` | End-to-end voice for settings deep links |

---

## Prioritized Remediation

### P0 — Low risk, high ROI (registry only)

1. Add §10.2 entries from `03-universal-launch.md` to `_KNOWN_LAUNCH_APPS`.
2. Extend `test_detect_app_launch_intent` for each new alias.
3. **Do not** add Discord/Chrome/Cursor to registry (research explicit).
4. **Do not** add Settings to `_SINGLE_INSTANCE_APPS`.

### P1 — Universal layer

1. `_refresh_launch_index()` at session start (`Get-StartApps` + `.lnk` + WScript.Shell).
2. `launch_app(name)` tool with same `wait_for_window` contract as `open_known_app`.
3. `launch_aumid(aumid)` + `list_start_apps` for debugging.

### P2 — URI / settings tools

1. `open_uri(uri)` with `shell:` vs protocol branch (`02-uris-protocols-shell.md` §6).
2. `open_settings(page)` wrapping `ms-settings:{page}` + title map.
3. Optional: spoken intent → slug table shared by voice detector and agent tools.

### P3 — Detector extensions (careful)

1. Fuzzy match against index keys only — keep `_LAUNCH_EXTRA_RE` strict.
2. **No** compound intents ("open settings bluetooth") in fast-path.

---

## Anti-Patterns to Preserve

From research — do **not** close gaps by:

- Putting third-party apps in `_KNOWN_LAUNCH_APPS`
- Adding Win+Search to `detect_app_launch_intent`
- Guessing `start spotify:` without registry check
- Hard-coding `C:\Program Files\...` for Electron apps

---

## Source Cross-Reference

| Topic | Document |
|-------|----------|
| Tier stack & index design | `docs/windows-automation-research/03-universal-launch.md` |
| ms-settings catalog (265 slugs) | `docs/windows-automation-research/02-uris-protocols-shell.md` |
| Voice → URI anti-pattern | `docs/windows-automation-research/00-master-strategy.md` §6.1 |
| P0 roadmap | `docs/windows-automation-research/00-master-strategy.md` §8 |
| Gap summary table | `docs/windows-automation-research.md` §5 |

---

## Acceptance Criteria (when gaps closed)

- [ ] Voice fast-path covers ≥20 safe OS aliases per research §10.2
- [ ] "open bluetooth settings" resolves without LLM
- [ ] Session launch index resolves user Start Menu apps (e.g. Cursor) without Win+Search
- [ ] `launch_aumid` opens UWP Calculator when `calc` alias ambiguous
- [ ] All new launch paths use `wait_for_window` / `open_known_app` verify contract
- [ ] Tests cover every new registry alias + index resolution smoke test

---

*Gap analysis generated 2026-06-22. Re-verify against `app/tools.py` after any registry change.*
```

---

### Key code anchors

Current registry (unchanged from research snapshot):

```447:457:C:\Users\ACER\Desktop\Ai_computer\Orynn\app\tools.py
_KNOWN_LAUNCH_APPS: Dict[str, tuple] = {
    "notepad": ("start notepad", "Notepad"),
    "calculator": ("start calc", "Calculator"),
    "calc": ("start calc", "Calculator"),
    "paint": ("start mspaint", "Paint"),
    "ms paint": ("start mspaint", "Paint"),
    "mspaint": ("start mspaint", "Paint"),
    "wordpad": ("start wordpad", "WordPad"),
    "settings": ("start ms-settings:", "Settings"),
    "task manager": ("start taskmgr", "Task Manager"),
}
```

Fast-path integration:

```1761:1788:C:\Users\ACER\Desktop\Ai_computer\Orynn\app\agent.py
        if mode in ("computer", "auto"):
            _launch = detect_app_launch_intent(goal)
            if _launch:
                _cmd, _title = _launch
                ...
                    res = await asyncio.to_thread(tools.open_known_app, _cmd, _title)
                ...
                return
```

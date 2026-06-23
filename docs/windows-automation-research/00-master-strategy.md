# Orynn Windows Automation — Master Strategy

**Date:** 2026-06-22  
**Audience:** Engineering, product, and agent-prompt authors  
**Scope:** Scalable orchestration for a voice-native Windows companion — **Gemini Live front desk** + **UIA-first back-office agent**

**Related:** [INDEX.md](./INDEX.md) · [Methods deep dive](../windows-automation-research.md) · Code: `app/widget/gemini_live.py`, `app/widget/textbox_overlay.py`, `app/agent.py`, `app/tools.py`, `app/adaptive_windows.py`, `app/connectors.py`

---

## Executive Summary

Orynn wins at scale by **not** treating every app as a bespoke playbook. The architecture is a **two-tier orchestra**:

| Tier | Role | Latency budget | Control plane |
|------|------|----------------|---------------|
| **Gemini Live (front desk)** | Voice, routing, one tool per turn, honest outcomes | 1–6 s spoken | UIA-only fast path; vision for *read*; never grid-locate |
| **Back-office agent** | Multi-step goals, launches, recovery | 10 s–minutes | Full resolver ladder + lazy playbooks |

Every desktop task decomposes into three universal layers — **launch → navigate → act** — using the cheapest method that works at each layer. Hundreds of apps need **zero** upfront playbooks: OS shortcuts open surfaces, UIA acts on controls by name, and `adaptive_windows_profiles.json` records what worked when UIA fails.

**Default method order:** URI/AUMID/shell launch → UIA by control name → keyboard shortcuts → Electron unlock → local OCR → vision grid-locate (agent only) → honest failure with evidence.

---

## 1. System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  USER (voice)                                                           │
└───────────────────────────────┬─────────────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  GEMINI LIVE — Front desk                                               │
│  • One tool per request                                                 │
│  • Short spoken ack → tool → outcome (never optimistic)                 │
│  • desktop_control fast-path with auto-escalate on miss                 │
│  • ORYNN MEMORY + ORYNN WORKFLOWS injected at connect                    │
└───────────────┬─────────────────────────────┬───────────────────────────┘
                │ fast UIA click/type           │ multi-step / launch / fail
                ▼                               ▼
┌───────────────────────────┐     ┌─────────────────────────────────────────┐
│  Direct UIA primitives    │     │  BACK-OFFICE AGENT (computer mode)      │
│  focus → find → click     │     │  enable_desktop_control → full tool set   │
│  (~1–4 s, no agent spin)  │     │  adaptive_observe → resolver ladder       │
└───────────────────────────┘     │  lazy playbooks + connector templates     │
                                  └─────────────────────────────────────────┘
                                                │
                    ┌───────────────────────────┼───────────────────────────┐
                    ▼                           ▼                           ▼
              Launch layer                 Navigate layer                Act layer
         ms-settings / AUMID /          focus_window / tabs /        uia_click / type /
         shell: / start / URI            menus / UIA tree survey       COM / CDP / OCR / grid
```

### 1.1 Front desk vs back office — hard boundaries

| Concern | Live (front desk) | Back office |
|---------|-------------------|-------------|
| Open app / file | `start_desktop_task` or `open_known_app` | `run_command start`, AUMID, URI tools |
| Single click/type in open app | `desktop_control` (UIA-only first) | Full ladder on escalation |
| Screen questions | `look_at_screen`, `list_windows` → `capture_window` | Screenshot only when model_sees enabled |
| Shell one-liners | `run_terminal` | `run_command` with approval gates |
| Failure recovery | Auto-escalate to agent OR ask consent | `adaptive_observe`, `electron_unlock`, OCR, grid |
| Vision click | **Never** | `grid_locate` when `allow_pixel_fallback=True` |
| Spoken outcome | Must match `ok` field — no guessing | Progress events → Live via task bridge |

Enforcement today: `gemini_live.py` rejects both `desktop_control` and `start_desktop_task` in one batch; `textbox_overlay._desktop_control_route` tries fast UIA then escalates; `grid_locate.py` documents agent-only scope.

---

## 2. Orchestration Decision Tree

**Rule:** At most **one tool per user request** on the Live path. Pick the shallowest branch that can succeed.

```
USER UTTERANCE
│
├─ Pure conversation / general knowledge / math / definitions?
│   └─► CHAT (voice only, no tools)
│
├─ Needs real-time or changing facts (news, scores, weather, prices)?
│   └─► web_search (not for local files)
│
├─ About what's ON SCREEN right now?
│   ├─ Foreground window → look_at_screen (BEFORE describing anything)
│   └─ Background app while user busy → list_windows → capture_window
│
├─ Single shell command with text output (git status, dir, pip list)?
│   └─► run_terminal
│       ├─ catastrophic → hard block
│       └─ destructive → spoken consent → confirmed=true
│
├─ Matches a saved ORYNN WORKFLOW by name/trigger?
│   └─► run_workflow (faster & more reliable than re-planning)
│
├─ ONE action in an ALREADY OPEN app?
│   ├─ click / type / shortcut / scroll / observe / focus
│   │   └─► desktop_control (NOT start_desktop_task)
│   │       ├─ fast UIA attempt (~1–4 s)
│   │       ├─ miss + Electron app → consent → start_desktop_task
│   │       └─ miss otherwise → auto-escalate start_desktop_task
│   └─ vague deictic ("click that") without visible target
│       └─► look_at_screen FIRST, then desktop_control
│
├─ Launch app / open file / multi-step ("open X and do Y") / vague setup?
│   └─► start_desktop_task
│       ├─ single-click goal rewrite → desktop_control fast path
│       ├─ disruptive verbs → consent gate
│       └─ blocks if another task already running
│
├─ User teaching a repeat procedure?
│   └─► save_workflow (after doing it once) OR remember (facts/locations)
│
└─ stop / cancel / never mind?
    └─► stop_current_task
```

### 2.1 Decision matrix (quick reference)

| User intent | Tool | NOT |
|-------------|------|-----|
| "Hey" / "explain recursion" | Chat | Any tool |
| "What's on my screen?" | `look_at_screen` | Guessing from memory |
| "Git status" | `run_terminal` | `start_desktop_task` |
| "Click Save" (app open) | `desktop_control` | `start_desktop_task` |
| "Open Notepad and type hello" | `start_desktop_task` | `desktop_control` + task |
| "Post my edit" (saved workflow) | `run_workflow` | `start_desktop_task` |
| "Turn on Bluetooth" | `start_desktop_task` with `ms-settings:bluetooth` goal OR expand launch registry | UIA tree-walk in Settings |
| "Is Cursor done?" (gaming) | `list_windows` → `capture_window` | `look_at_screen` (foreground only) |

### 2.2 Escalation ladder (desktop_control → agent)

Implemented in `textbox_overlay._desktop_control_route`:

1. **Consent check** — disruptive goals (`LIVE_CONSENT_RE`) need spoken yes before agent spawn.
2. **Fast UIA** — `_live_desktop_control(..., fast_invoke_only=True)` — no pixel fallback.
3. **On miss** — Electron hint → warn about relaunch; else auto `start_desktop_task` with synthesized goal.
4. **Single-click rewrite** — `start_desktop_task("click Save in Notepad")` → parsed to `desktop_control` click.

Read-only actions (`observe`, `find`, `wait`, `focus_window`, `press_keys`, `scroll`) **never** escalate.

---

## 3. Universal Three-Layer Model

Every automation goal — regardless of app — maps to:

```
LAUNCH  →  NAVIGATE  →  ACT
```

### 3.1 Layer 1 — Launch (get the surface on screen)

**Goal:** Bring the right HWND/process without clicking through Start or Settings trees.

| Method | When | Example |
|--------|------|---------|
| `ms-settings:` URI | Settings pages | `start ms-settings:bluetooth` |
| Protocol URI | Deep-link apps | `start spotify:`, `ms-teams:` |
| AUMID | Store/UWP apps | `explorer shell:AppsFolder\Microsoft.WindowsCalculator_...!App` |
| `shell:` folder | Known folders | `shell:Downloads` |
| Run dialog / `start` | Win32 exes | `start wt`, `notepad` |
| File association | Open document | `start "" "C:\path\file.docx"` |
| Connector template | Web SaaS | Playwright/CDP → URL (preferred over screenshot loop) |

**Classifier (implement as `open_surface(intent)`):**

```
intent
 ├─ settings page?     → ms-settings:<uri>
 ├─ known protocol?    → start <scheme>:
 ├─ Store/UWP?         → AUMID via shell:AppsFolder
 ├─ known Win32?       → start <exe> / .lnk
 ├─ file path?         → start "" "path"
 └─ unknown            → agent planner (slow) — never Win+Search automation
```

Live should prefer **deterministic launch** over agent planning for spoken "open X" commands.

### 3.2 Layer 2 — Navigate (reach the right state)

**Goal:** Correct window focused, correct tab/page/dialog open.

| Method | When |
|--------|------|
| `focus_window` / `wait_for_window` | HWND disambiguation |
| Keyboard shortcuts | `Ctrl+Tab`, `Alt+F`, `Ctrl+L` |
| UIA `uia_click` on nav items | Settings sidebar, menu bars |
| URI deep link | Skip in-app navigation entirely |
| `adaptive_observe` | Classify surface before acting |

**Anti-pattern:** Walking the Windows 11 Settings tree (System → Bluetooth → toggle) when `ms-settings:bluetooth` exists.

### 3.3 Layer 3 — Act (mutate state)

**Goal:** Click, type, toggle, save — with verification.

| Method | When |
|--------|------|
| UIA Invoke/Value patterns | Named buttons, fields, menus |
| `keyboard_type` / `key_combo` | Electron partial trees, universal shortcuts |
| COM automation | Office bulk read/write |
| CDP/Playwright | Web content inside browser |
| Windows Media OCR | Visible text UIA omits |
| Grid-locate vision | Canvas/custom render — **agent only** |

**Verification:** Always `uia_find` read Value/Name after act; Live confirms from fresh screenshot on vision turns.

---

## 4. Memory, Workflows, and Lazy Playbooks

Orynn uses **three complementary memory systems** — do not conflate them.

### 4.1 ORYNN MEMORY (`remember` / `forget`)

- **What:** Durable facts — locations, vocab, user rules, assistant-learned UI hints.
- **Who writes:** Live when user says "remember…" or when assistant learns from `look_at_screen`.
- **Who reads:** Injected into Live system prompt at connect.
- **Example:** "Cowork button is top-right of dashboard" → category `location`, owner `assistant`.

### 4.2 ORYNN WORKFLOWS (`save_workflow` / `run_workflow` / `forget_workflow`)

- **What:** Named, ordered step lists using **verified desktop tiers** (open, click, type, press_keys, scroll, focus, run, wait).
- **Who runs:** Live via `run_workflow` — synchronous step execution through `_run_workflow_step`.
- **When to prefer over agent:** User repeats the same multi-step procedure; triggers match utterance.
- **Consent:** Disruptive workflows return `needs_consent`; retry with `confirmed=true`.

Workflows are **explicit procedures** the user or assistant authored. They are not inferred.

### 4.3 Lazy playbooks (`adaptive_windows_profiles.json`)

- **What:** Per-app **resolver memory** — which fallback worked for which `failure_class`.
- **Who writes:** Back-office agent on classified failure/success via `adaptive_windows.py`.
- **Who reads:** `learned_resolvers()` before generic OCR/grid ladder.
- **Example:** Notepad Find dialog → `ocr_text_target`; Figma toolbar → `vision_grid_locate`.

| System | Granularity | Authored by | Runtime |
|--------|-------------|-------------|---------|
| Memory | Facts | User + assistant | Live prompt |
| Workflows | Multi-step scripts | User + assistant | Live `run_workflow` |
| Lazy playbooks | Per-app resolver hints | Agent learning | Back-office only |

**Scaling policy:** Do not pre-write playbooks for N apps. Let the first encounter populate profiles; consult profile before expensive vision.

### 4.4 Connector skills

`connectors.py` defines **task templates** for linked surfaces (Gmail, GitHub, Excel, VS Code, …):

- **auth_kind:** `browser` | `token` | `local`
- **task_template:** Goal prefix the agent receives when user picks a connector
- **default_mode:** Should migrate from `computer_use` → Playwright/CDP where possible

Connectors are **skills at the product layer** — not Live tools. Voice can say "check my GitHub notifications" → Live spawns `start_desktop_task` with connector-aware goal OR dashboard dispatches connector template.

**Connector routing:**

```
User mentions linked connector surface
 ├─ Web (Gmail, Slack web) → browser automation (CDP), not desktop UIA
 ├─ Office desktop → COM + UIA
 ├─ VS Code / local → UIA + electron_unlock
 └─ Filesystem / clipboard → local tools, no UI
```

---

## 5. Method Comparison — Master Table

| Method | Speed | Cost | Reliability | Best for | Live? | Agent? |
|--------|-------|------|-------------|----------|-------|--------|
| **UIA (control name)** | Fast (ms–low s) | Free | High on Win32/WinUI/Office | Buttons, fields, menus | ✅ primary | ✅ primary |
| **Keyboard / SendInput** | Very fast | Free | High when shortcuts exist | Save, tab-nav, Electron typing | ✅ | ✅ |
| **ms-settings / shell / AUMID / URI** | Instant | Free | Very high (OS-routed) | Open pages, apps, folders | ✅ via task | ✅ |
| **Windows Media OCR** | Medium (100–500 ms) | Free | Medium (visible text) | Labels UIA omits, Explorer | ⚠️ escalate only | ✅ |
| **Vision grid-locate** | Slow (2+ model calls) | API $ | Medium (fails safe) | Canvas, icon toolbars | ❌ never | ✅ fallback |
| **Screenshot + coordinate click** | Medium | Free + vision | Low–medium | — | ❌ | ❌ avoid |
| **pyautogui / PostMessage** | Fast | Free | Low for Chromium content | Simple Win32 only | ⚠️ | ⚠️ |
| **COM (Office)** | Fast | Free | Very high in Office | Bulk spreadsheet/doc ops | ❌ | ✅ |
| **WMI / CIM / PowerShell** | Medium | Free | High for system facts | Installed software, disks | via `run_terminal` | ✅ |
| **Browser CDP/Playwright** | Medium | Free–low | High for web apps | Gmail, GitHub, SaaS | ❌ | ✅ connectors |
| **FlaUI / pywinauto / AHK** | Fast | Free | Same as UIA | Alt runtime / user macros | — | optional sidecar |
| **Accessibility event unlock** | One-time delay | Free | High for Electron | Chromium tree materialization | ❌ | ✅ |

### 5.1 App-class routing

| Class | Examples | Launch | Navigate | Act |
|-------|----------|--------|----------|-----|
| Native Win32 | Notepad, mmc | `start` | focus | UIA + keyboard |
| WinUI / UWP | Settings, Calculator | AUMID / URI | UIA | UIA |
| Office | Word, Excel | `start` / file assoc | focus | **COM** then UIA |
| Electron | VS Code, Discord, Slack | exe + unlock flag | focus | unlock → UIA → keyboard |
| Chromium browser | Chrome, Edge | `start` / protocol | tabs | **CDP**, not UIA |
| Web SaaS | Gmail, Notion | connector URL | — | Playwright |
| Games / GPU | Unity titles | — | — | vision or decline |
| Custom canvas | Figma canvas | app launch | — | grid-locate |

---

## 6. Anti-Patterns

### 6.1 Settings tree-walk

**Symptom:** Agent clicks System → Bluetooth → toggle when user said "turn on Bluetooth."  
**Fix:** `start ms-settings:bluetooth` at launch layer. UIA inside Settings only when no URI exists.  
**Voice mapping:** Maintain spoken intent → URI table in launch registry.

### 6.2 Double routing

**Symptom:** Live calls both `desktop_control` and `start_desktop_task` for the same goal; duplicate work, race on focus, confused spoken outcome.  
**Fix:** Enforced in `gemini_live.py` — only one desktop tool per batch. Prompt: "pick one; fast clicks auto-escalate."  
**Test:** `test_gemini_live.py::test_only_one_desktop_tool_per_batch`.

### 6.3 Optimistic speech

**Symptom:** Model says "Done, I opened Notepad" when `ok: false` or task still running.  
**Fix:** System prompt OUTCOMES section; `start_desktop_task` waits `LIVE_TASK_RESULT_WAIT` (6 s) for terminal state; background tasks require explicit "I started it, I'll tell you when it's done."  
**Rule:** Spoken result must match last tool `ok` field — never infer from intent.

### 6.4 Vision-before-read on screen questions

**Symptom:** Answering "what's this error?" from conversation memory.  
**Fix:** `look_at_screen` BEFORE description; auto-screen attach (`ORYNN_LIVE_AUTO_SCREEN=always` default).  
**Rule:** Never ask user "what do you see?" — that's the agent's job.

### 6.5 Grid-locate on Live path

**Symptom:** 15 s tool timeout, expensive vision, wrong clicks on voice commands.  
**Fix:** `allow_pixel_fallback=False` on all Live invocations; hand off to back office.

### 6.6 Web search for local facts

**Symptom:** Searching the web for "where is my budget.xlsx."  
**Fix:** `run_terminal` (`dir /s`) or `start_desktop_task` with file search — not `web_search`.

### 6.7 Win+Search automation

**Symptom:** Automating Windows Search UI — breaks every feature update.  
**Fix:** Prefer `start`, AUMID, URI, or `shell:AppsFolder` discovery.

### 6.8 Pre-writing hundreds of playbooks

**Symptom:** Maintenance nightmare; stale selectors.  
**Fix:** Universal 3-layer model + lazy profiles + user workflows for true repeats only.

---

## 7. Competitor Patterns

### 7.1 Clicky (Bitshank) — voice-first desktop buddy

| Aspect | Clicky pattern | Orynn adoption |
|--------|----------------|----------------|
| UX | Floating overlay, cursor fly-to, status pill | `virtual_cursor.py`, `textbox_overlay.py` — Clicky-inspired glass UI |
| Voice | Push-to-talk, short spoken responses | Gemini Live with Clicky-style prompt |
| Locate | Two-stage grid / Set-of-Mark vision | `grid_locate.py` — ported from Clicky `universal_locator.py` |
| Control | Mixed vision + input injection | **Differentiator:** UIA-first; grid only as agent fallback |
| Task IDs | `clicky-*` progress events | Preserved in `textbox_overlay` task bridge |

**Lesson:** Clicky optimizes for *feel* (cursor animation, brevity). Orynn keeps the feel but replaces pixel-primary control with UIA-primary — vision for locate-only fallback and screen Q&A.

### 7.2 Anthropic Computer Use — vision coordinate agent

| Aspect | Anthropic pattern | Orynn contrast |
|--------|-------------------|----------------|
| Perception | Screenshot every step | UIA text tree — screenshot-free for most steps |
| Action space | Pixel coordinates (click, drag, type) | Named controls via InvokePattern |
| Loop | capture → model → PyAutoGUI → repeat | observe → uia_find → uia_click → verify |
| Cost | High vision tokens per step | Low text tokens; vision on demand |
| Resolution | Must map display_width/height ↔ screenshot | N/A for UIA; grid downscales for vision |
| Strength | Closed-source apps with no API | Custom UIs, games — when UIA fails |
| Weakness | DPI mismatch, mis-clicks, latency | Electron locked trees — mitigated by unlock |

**When to borrow:** Zoom regions (`computer_20251124` zoom action) inspired Orynn's two-stage grid. Do **not** borrow screenshot-every-step as default — use for `look_at_screen` and grid-locate only.

### 7.3 Microsoft Power Automate — enterprise RPA

| Aspect | Power Automate pattern | Orynn contrast |
|--------|------------------------|----------------|
| Model | Recorded flows + connector catalog | LLM-planned with learned profiles |
| UI automation | UI Automation (PAD desktop flows) | Same UIA foundation — aligned |
| Connectors | 400+ certified API connectors | Growing `connectors.py` registry |
| Triggers | Schedule, email, button | Voice + saved workflows |
| Reliability | Deterministic replay | Probabilistic LLM — mitigated by workflows + UIA verify |
| Settings | Built-in actions for OS settings | Should use same URIs via launch layer |

**Lesson:** Power Automate separates **connectors (API)** from **UI flows (PAD)**. Orynn should mirror: connector = API/browser template; UI = 3-layer stack; repeat = `run_workflow`.

### 7.4 Positioning summary

```
                    Deterministic ──────────────────► Probabilistic
                         │                                    │
    Power Automate       │         Orynn workflows            │
    (recorded PAD)       │         + lazy playbooks           │
                         │                                    │
                         │         Orynn agent (default)      │
                         │                                    │
    ─────────────────────┼────────────────────────────────────┤
    Semantic (UIA/API)   │    UIA-first ◄── Orynn core        │
                         │                                    │
                         │              Anthropic computer use │
                         │              Clicky grid-locate     │
                         ▼                                    ▼
                    Vision / pixels
```

Orynn's moat: **voice-native front desk** + **semantic control** + **local free tiers** (UIA, OCR, WMI) with vision only as priced fallback.

---

## 8. Implementation Roadmap (prioritized)

### P0 — Orchestration hardening (now)

1. Expand `_KNOWN_LAUNCH_APPS` + spoken intent → URI map (Bluetooth, sound, display, …).
2. `open_settings(suffix)` and `launch_aumid(aumid)` tools.
3. Wire `learned_resolvers()` into `tools.py` before generic OCR/grid.
4. Enforce Live tool policy in code paths (no `allow_pixel_fallback` from Live).
5. Handoff envelope on escalation: `{target_app, electron_hint, failure_class}` in task JSON.

### P1 — Scale surfaces (medium)

6. UIA `CacheRequest` batch wrapper for large trees.
7. Session `FocusChanged` subscription for Chromium wake without relaunch.
8. Electron kill-and-relaunch with consent on `electron_unlock(force=True)`.
9. Playwright driver for `auth_kind: browser` connectors.
10. COM shim for Office connectors.

### P2 — Observability

11. Aggregate `control_layer` / resolver path in logs.
12. Extend `docs/BENCHMARKS.md` — open/click/locate by app class.

---

## 9. Prompt & Tool Authoring Checklist

For anyone editing `gemini_live.py` or agent prompts:

- [ ] One tool per user request on Live
- [ ] Never both `desktop_control` and `start_desktop_task` for same goal
- [ ] Screen questions → capture before describe
- [ ] Single click in open app → `desktop_control` not task
- [ ] Launch / multi-step → `start_desktop_task`
- [ ] Repeat procedure → `run_workflow` if exists
- [ ] New fact → `remember`; new procedure → `save_workflow`
- [ ] Outcome speech matches `ok` field
- [ ] Disruptive actions → ask → `confirmed=true`
- [ ] Background task → tell user you'll report back
- [ ] Do not narrate every step; short ack then silence until done

---

## 10. Sources

| Topic | Reference |
|-------|-----------|
| Orynn methods deep dive | [../windows-automation-research.md](../windows-automation-research.md) |
| ms-settings URIs | [Microsoft Launch Settings](https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-settings) |
| UIA caching | [UIA caching for clients](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-cachingforclients) |
| Chromium a11y | [Chromium accessibility overview](https://chromium.googlesource.com/chromium/src/+/HEAD/docs/accessibility/overview.md) |
| Anthropic computer use | [Claude computer use tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool) |
| Clicky grid locate | `app/grid_locate.py` (ported from Clicky) |

---

*This document is the single entry point for Orynn Windows automation strategy. Detailed method catalogs, URI tables, and tool inventories live in the companion deep-dive doc.*

# Clicky vs Orynn — Competitor Analysis

**Doc:** `01-clicky.md`  
**Date:** 2026-06-22  
**Scope:** Clicky (macOS original + Windows port) as the closest **voice-native, overlay-first Windows companion** to Orynn — product positioning, architecture, control plane, and shared code lineage  
**Audience:** Orynn product and engineering  
**Method:** Read-only synthesis of Clicky Windows source at `clicky-windows-investigation/clicky-windows` and Orynn internal docs/code

**Related Orynn docs:** [00-master-strategy.md](../../windows-automation-research/00-master-strategy.md) · [04-vision-ocr-pixel.md](../../windows-automation-research/04-vision-ocr-pixel.md) · [09-orynn-codebase-audit.md](../../windows-automation-research/09-orynn-codebase-audit.md) · [ROADMAP.md](../../ROADMAP.md)

> **Scope boundary:** Clicky is the only competitor in this series that Orynn **explicitly borrowed UX and vision-locate code from**. Anthropic CU, Operator, Power Automate, Open Interpreter, and Gemini Live native are covered in sibling files.

---

## Executive Summary

**Clicky** is an **AI teaching companion** that lives beside the cursor: hold a hotkey, ask about the screen, and it **points, explains, and speaks** — like a patient tutor. The original [farzaa/clicky](https://github.com/farzaa/clicky) shipped on macOS (SwiftUI); the Windows port ([Bitshank-2338/clicky-windows](https://github.com/Bitshank-2338/clicky-windows)) reimplements the experience in **Python 3.11+ / PyQt6** with multi-provider LLM, STT, and TTS.

**Orynn** is an **autonomous desktop agent**: give it a goal in the floating glass capsule (or voice via Gemini Live) and it **plans, acts, and verifies** on your machine — clicking controls by **UI Automation name**, not screenshots, with a two-tier **front desk + back-office** architecture.

| Dimension | Clicky | Orynn |
|-----------|--------|-------|
| **Primary job** | Teach and point — *show*, don't just tell | Execute goals — open apps, click Save, run workflows |
| **Default control plane** | Screenshot + vision locate → fly cursor to `(x,y)` | UIA by control name → InvokePattern (no cursor move) |
| **Voice contract** | Push-to-talk tutor; short TTS answers | Gemini Live front desk; honest `ok`-matched speech |
| **Multi-step work** | Lesson mode ("say next"); no task persistence | Back-office agent; `start_desktop_task`, workflows |
| **Overlay role** | **Primary UX** — blue buddy flies to targets | **Visual feedback** — optional bezier cursor; glass capsule for goals |
| **Vision cost** | Screenshot on **every** query | Screenshot only on read/escalation; UIA steps are text-only |
| **Tutor extras** | Journal, SM-2 quiz, lesson MP4, workflow capture | Workflows, semantic memory, connectors, coding/browser modes |
| **License** | MIT | PolyForm Noncommercial 1.0.0 |

**Bottom line:** Clicky and Orynn share **voice + overlay + Windows desktop** DNA — Orynn's master strategy explicitly labels Clicky as the pattern for *feel* (cursor animation, brevity) while **replacing pixel-primary control with UIA-primary execution**. They are **adjacent products**, not clones: Clicky optimizes **guided learning**; Orynn optimizes **delegated automation**.

---

## 1. What Clicky Is

### 1.1 Product identity

From the Windows port README and `main.py` entry:

> *"An AI teaching companion that lives next to your cursor. Ask it anything about your screen — it points, explains, and guides you step-by-step, like a real tutor sitting beside you."*

Core user loop:

1. Hold **Ctrl + Alt + Space** (or wake word **"Clicky"**)
2. Speak a question about the screen
3. Clicky captures a **multi-monitor screenshot**, optionally locates a UI element, queries an LLM with vision, and responds via **TTS**
4. For locate queries, the **blue triangle buddy** flies along a bezier arc to the target, dwells with a highlight ring, then returns

Clicky is **not** designed as a general-purpose "do my homework / file my taxes" agent. It **does not** maintain long-running task state, spawn background agents, or execute destructive shell commands. Its `skills/` system allows lightweight voice triggers (e.g. open Calculator) but the product center of gravity is **explain + point**.

### 1.2 Lineage

| Lineage | Stack | Maintainer |
|---------|-------|------------|
| **clicky (macOS)** | SwiftUI, original concept | [farzaa/clicky](https://github.com/farzaa/clicky) |
| **clicky-windows** | Python, PyQt6, asyncio | Bitshank-2338 port (investigated locally) |

The Windows port is a **faithful UX port** — overlay timings, triangle color (`#3380FF`), offset (+35, +25 px from cursor), teacher-pace flight (1.6–2.8 s), and 4 s dwell match the Swift source comments in `ui/overlay.py`.

### 1.3 Distribution and cost model

- **Runtime:** `python main.py` or PyInstaller `Clicky.exe` + optional Inno Setup installer
- **100% offline path:** Ollama vision + Faster-Whisper/whisper.cpp + Edge TTS — no API keys
- **Paid path:** Claude (incl. Computer Use pointing), OpenAI, Gemini, GitHub Copilot (student OAuth), Deepgram, ElevenLabs
- **License:** MIT — commercial use allowed

Orynn ships a **PolyForm NC** license (noncommercial without separate agreement) and targets **OpenRouter/Groq free tiers** plus optional stronger models for desktop reliability.

---

## 2. Clicky Architecture

### 2.1 Orchestrator — single async state machine

```
USER (voice / hotkey)
        │
        ▼
┌───────────────────────────────────────────────────────────┐
│  CompanionManager (companion_manager.py)                  │
│  • AmbientListener → STT (Deepgram / Whisper / local)   │
│  • capture_all_screens() → JPEG + DPI metadata            │
│  • tutor.py classifiers (locate / multistep / quiz / …)   │
│  • hybrid_pointer.find_target() OR universal_locator       │
│  • LLM provider (Claude / OpenAI / Copilot / Gemini / Ollama)│
│  • TTS (ElevenLabs / OpenAI / Edge)                       │
│  • CursorOverlay.point_at(x, y)                           │
└───────────────────────────────────────────────────────────┘
        │
        ├── CompanionPanel (optional chat + model dropdown)
        └── TrayManager (provider switch, tutor modes, recording)
```

Unlike Orynn's **FastAPI + AgentService + Gemini Live bridge**, Clicky is a **monolithic desktop app** — no separate backend, no task JSON files, no SSE action stream. All orchestration lives in `CompanionManager` with PyQt signals for cross-thread UI updates.

### 2.2 Pointing pipeline — vision-first with UIA upgrade

Clicky's locate path is the inverse of Orynn's default order:

**Clicky `hybrid_pointer.py` (three tiers):**

| Tier | Method | Latency | Accuracy |
|------|--------|---------|----------|
| 1 | Windows UIA fuzzy name match | ~5 ms | Pixel-perfect centre |
| 2 | RapidOCR / ONNX on screenshot | ~300 ms | Text labels |
| 3 | Vision LLM (Claude CU or grid) | 1–3 s | ~5 px (CU) or ~25–50 px (grid) |

**Important nuance:** Despite UIA Tier 1, Clicky's **product loop still captures a screenshot every query** for LLM vision context. UIA is used to **improve pointing accuracy**, not to eliminate vision tokens. The README's "screen aware" feature sends JPEG on every turn.

**Vision locate implementations:**

| Module | When | Mechanism |
|--------|------|-----------|
| `ai/element_locator.py` | `ANTHROPIC_API_KEY` set + locate query | Claude `computer_20251124` → `(x,y)` in CU space → DPI remap |
| `ai/universal_locator.py` | Any vision LLM (Copilot, Ollama, Gemini) | Two-stage Set-of-Mark grid (12×8 → 6×6 crop) |
| LLM `[POINT:x,y:label]` tags | Fallback when locators miss | Model guesses coordinates from screenshot |

Coordinate remapping in `element_locator.py` follows Anthropic best practices: pick aspect bucket (1024×768, 1280×800, 1366×768), resize JPEG, invoke CU tool, map **Computer-Use space → physical px → monitor origin → logical Qt px**.

### 2.3 Tutor layer — classifiers and modes

`tutor.py` and `tutor_features/` implement Clicky's **pedagogical** differentiation:

| Feature | Module | Behavior |
|---------|--------|----------|
| Locate vs multistep vs identity | `tutor.py` regex classifiers | Different system prompts per query type |
| Privacy Guard | `is_sensitive_window()` | Skips screenshot on password managers / banking titles |
| Per-app memory | `app_key(window_title)` | Last 20 messages per active app — context doesn't bleed |
| Quiz Mode | `CompanionManager` quiz prompt | Asks user questions; never points |
| Slow Mode | Overlay timing multipliers | 1.7× slower flight for students |
| Knowledge Journal | `journal.py` SQLite | Q&A log + SM-2 spaced repetition flashcards |
| Document context | `pdf_context.py` | Drag PDF/DOCX/TXT onto panel |
| OCR fallback | `ocr.py` Tesseract | Fine print when query mentions "small text" |
| Code Mode | `code_mode.py` | IDE window-title detection → code-specialist prompt |
| Lesson recording | `lesson_recorder.py` | 8 fps MP4 + Markdown transcript |
| Workflow capture | `workflow_capture.py` | Records clicks/keys via `pynput`; narrates on ask |
| Multilingual | `multilang.py` | langdetect + Edge TTS voice switch (15+ langs) |
| Whiteboard annotations | Overlay + LLM tags | `[ARROW:…]`, `[CIRCLE:…]`, `[UNDERLINE:…]` |
| Skills | `~/.clicky/skills/*.py` | User voice triggers without PR |

None of these exist as first-class Orynn features today — Orynn's parallel concepts are **`save_workflow` / `run_workflow`**, **`remember` / Chroma memory**, and **`look_at_screen`** for screen Q&A.

### 2.4 Audio stack

| Layer | Clicky options | Orynn equivalent |
|-------|----------------|------------------|
| Wake / PTT | Global hotkey + ambient wake word | Gemini Live always-on mic stream |
| STT | Deepgram, OpenAI Whisper, whisper.cpp, Faster-Whisper | Gemini Live native audio (input 16 kHz) |
| TTS | ElevenLabs, OpenAI, Edge (400+ voices) | Gemini Live native audio (output 24 kHz) |
| Interrupt | **Esc** stops generation + TTS (`threading.Event`) | Live session stop / `stop_current_task` |

Clicky supports **offline STT/TTS** end-to-end; Orynn's voice path requires **Google Gemini Live API** (with textbox fallback in capsule).

### 2.5 Provider flexibility

Clicky auto-detects LLM priority: **Claude → OpenAI → GitHub Copilot → Gemini → Ollama**, runtime-switchable from tray (~1 s, no restart). Live model lists cached 30 days (6 h for Copilot `/models`).

Orynn routes via **OpenRouter** (free `:free` chain), **Groq** (fast fallback), or direct Anthropic/OpenAI/Gemini keys — with **`DESKTOP_MODEL`** override for reliability on multi-step desktop tasks only.

---

## 3. Orynn Architecture (Baseline for Comparison)

### 3.1 Two-tier orchestra

From [00-master-strategy.md](../../windows-automation-research/00-master-strategy.md):

| Tier | Role | Control plane | Latency |
|------|------|---------------|---------|
| **Gemini Live (front desk)** | Voice routing, one tool per turn | UIA-only fast path; vision for *read* only | 1–6 s spoken |
| **Back-office agent** | Multi-step goals, recovery | Full resolver ladder + lazy playbooks | 10 s–minutes |

Clicky has **no equivalent split** — every utterance goes through the same `CompanionManager` pipeline with optional lesson-step state (`lesson_step`, `total_steps`).

### 3.2 Resolver ladder (Orynn default)

```
URI/AUMID/shell launch → UIA by control name → keyboard shortcuts
  → Electron unlock → Windows OCR → vision grid-locate (agent only)
  → honest failure with evidence
```

**Hard Live boundary:** `grid_locate` and pixel fallback are **never** used on the Gemini Live fast path — miss → auto-escalate to `start_desktop_task`.

### 3.3 Shared Clicky lineage in Orynn code

Orynn explicitly ports and adapts Clicky patterns ([00-master-strategy §7.1](../../windows-automation-research/00-master-strategy.md#71-clicky-bitshank--voice-first-desktop-buddy)):

| Clicky source | Orynn destination | Purpose |
|---------------|-------------------|---------|
| `ai/universal_locator.py` | `app/grid_locate.py` | Two-stage Set-of-Mark grid |
| `ai/hybrid_pointer.py` | `tests/test_hybrid_resolver.py` + tools ladder | UIA → OCR → grid concept |
| Overlay UX (bezier fly-to) | `app/widget/virtual_cursor.py` | Visual-only pointer animation |
| Task progress IDs | `textbox_overlay.py` `clicky-*` task IDs | Back-office progress bridge |
| Short spoken responses | Gemini Live system prompt | Clicky-style brevity |

Orynn's `virtual_cursor.py` (~1,222 lines) is **Clicky-inspired but non-control** — it animates for user trust; actual clicks use UIA InvokePattern without moving the OS cursor ([README demo](https://github.com/robomohit/Orynn): Calculator covered by another window).

---

## 4. Head-to-Head Comparison

### 4.1 Product philosophy

| Question | Clicky | Orynn |
|----------|--------|-------|
| What is success? | User **learns** where things are | Task **completes** with verification |
| Who acts? | User clicks; Clicky **points** | Orynn **clicks/types** on user's behalf |
| Screen capture | Every query (vision context) | On demand (`look_at_screen`, agent escalation) |
| Failure mode | "I don't see X on this page" | `ok: false` + evidence; spoken honesty |
| Long jobs | Lesson steps in memory | Persistent task JSON, action ticker, pause/kill |

### 4.2 Control plane

| Scenario | Clicky | Orynn |
|----------|--------|-------|
| "Where is the Save button?" | Screenshot → locate → **fly cursor**, explain | `look_at_screen` OR `desktop_control` click Save via UIA |
| "Click Save" | Points; user still clicks | `uia_click("Save")` — InvokePattern, cursor may not move |
| "Open Notepad and type hello" | Multistep lesson ("say next") | `start_desktop_task` → agent launch + type |
| Canvas app (Figma) | OCR Tier 2 → grid Tier 3 | UIA miss → OCR → grid (agent only) |
| Settings toggle | Vision + point at toggle | `ms-settings:bluetooth` URI launch preferred |

### 4.3 Latency and cost

| Path | Clicky | Orynn |
|------|--------|-------|
| Simple locate | Screenshot + STT + LLM vision + TTS + fly animation (~3–8 s) | UIA fast path ~1–4 s; no screenshot if control found |
| Screen description | Full vision turn every time | `look_at_screen` — one vision read, no click |
| Offline | Ollama + local Whisper + Edge TTS | UIA/OCR free; Live needs network |
| Token burn | **High** — JPEG in every LLM call | **Low** — UIA tree text for most steps |

### 4.4 Voice UX

| Aspect | Clicky | Orynn |
|--------|--------|-------|
| Activation | Push-to-talk hotkey; optional wake word | Always-on Gemini Live session |
| Response length | Hard-prompted: 1 sentence for locate; step-at-a-time lessons | Spoken ack → tool → outcome; no optimistic lies |
| Lesson flow | "next" / "repeat" / "stop" voice commands | `stop_current_task`; workflows for repeats |
| Multilingual | 15+ langs via langdetect + Edge TTS | Gemini Live native (model-dependent) |
| Quiz / tutoring | First-class Quiz Mode, journal, SM-2 | Not productized — automation focus |

### 4.5 Trust and safety

| Control | Clicky | Orynn |
|---------|--------|-------|
| Sensitive windows | Privacy Guard skips screenshot | Consent gates for disruptive verbs |
| Shell / files | Skills only (user-authored) | Full agent: shell, files, browser with approval scopes |
| Destructive actions | Not in core product | `SafetyManager` + spoken `confirmed=true` |
| Data residency | Local journal SQLite; API calls to chosen LLM | Local task state; LLM provider configurable |

### 4.6 Extensibility

| Capability | Clicky | Orynn |
|------------|--------|-------|
| User skills | `~/.clicky/skills/*.py` voice triggers | MCP, skills folder, connectors registry |
| Coding | Code Mode prompt addendum only | Full **coding mode** (edit/run code) |
| Browser | Web search (DuckDuckGo/Tavily) — no browser control | **Browser mode** (Playwright a11y tree) |
| Workflows | Workflow *capture* (narrate clicks) | `save_workflow` / `run_workflow` (execute repeats) |
| Recording | MP4 lesson + transcript | Action ticker + task JSON logs |
| Dashboard | Companion panel + tray | Full dashboard (sessions, models, MCP) |

---

## 5. Feature Matrix (Quick Reference)

| Feature | Clicky | Orynn |
|---------|:------:|:-----:|
| Voice push-to-talk | ✅ | ⚠️ Live always-on |
| Wake word ("Clicky") | ✅ | ❌ |
| Cursor fly-to animation | ✅ Primary UX | ⚠️ Opt-in overlay |
| Floating glass UI | ⚠️ Panel + overlay | ✅ Capsule |
| Screenshot every query | ✅ | ❌ (on demand) |
| UIA click (no vision) | ⚠️ Tier 1 for pointing only | ✅ Primary actuation |
| Claude Computer Use locate | ✅ ~5 px | ⚠️ Documented, not default |
| Set-of-Mark grid locate | ✅ | ✅ Agent fallback (`grid_locate.py`) |
| Actually clicks for user | ❌ (points only) | ✅ |
| Multi-step task agent | ❌ | ✅ Back office |
| Launch apps (URI/AUMID) | ⚠️ Skills only | ✅ Launch registry |
| Web search with citations | ✅ DuckDuckGo/Tavily | ✅ Connectors + `web_search` |
| Knowledge journal + spaced repetition | ✅ SQLite SM-2 | ⚠️ Memory/workflows (different model) |
| Quiz mode | ✅ | ❌ |
| Lesson MP4 recording | ✅ | ❌ |
| Workflow capture (record clicks) | ✅ pynput | ❌ |
| PDF/document drag context | ✅ | ⚠️ File tools in agent |
| Coding agent | ❌ | ✅ |
| Browser automation | ❌ | ✅ Playwright |
| 100% offline | ✅ Ollama path | ⚠️ UIA/OCR local; Live needs API |
| MIT / commercial use | ✅ MIT | ❌ PolyForm NC |
| PyInstaller .exe | ✅ | ✅ Releases zip |

---

## 6. Strategic Implications for Orynn

### 6.1 Clicky is the closest *feel* competitor, not the closest *automation* competitor

Users comparing "AI on my Windows desktop" may encounter Clicky first (MIT, tutor marketing, YouTube demo). Orynn should differentiate on **execution** ("it actually clicks Save while you're in another window") and **UIA economics**, not on copying tutor-only features wholesale.

### 6.2 Borrow selectively from Clicky tutor features

High-value, low-conflict adoptions Orynn could consider (proposals only — not in scope for this doc):

| Clicky feature | Orynn opportunity |
|----------------|-------------------|
| Privacy Guard (skip capture on sensitive titles) | Extend Live `look_at_screen` guardrails |
| Per-app conversation memory | Already partially via task context; could mirror `app_key()` |
| "Repeat last answer" voice command | Cheap Live tool — replay last TTS/text |
| Workflow capture → `save_workflow` | Bridge user demonstration to Orynn workflows |
| Slow-mode pointer overlay | Already in `virtual_cursor.py` — expose as tutor setting |

Low priority for Orynn core: SM-2 journal, Quiz Mode, lesson MP4 — different product lane.

### 6.3 Do not regress to screenshot-primary control

Clicky's hybrid pointer proves UIA Tier 1 works on Windows — Orynn already uses it as **primary actuation**. The temptation to "match Clicky" by sending screenshots to Live on every turn would **destroy** Orynn's cost and latency moat. Keep vision for **read** (`look_at_screen`) and **agent-only locate fallback**.

### 6.4 Grid-locate parity is already achieved

`grid_locate.py` is ported from Clicky `universal_locator.py` ([04-vision-ocr-pixel.md §Algorithm](../../windows-automation-research/04-vision-ocr-pixel.md)). Benchmark both implementations on the same Notepad/Calculator targets per [BENCHMARKS.md](../../BENCHMARKS.md) — Orynn should match or beat Clicky grid accuracy with shared algorithm.

### 6.5 Voice positioning

Clicky wins **offline voice tutor** (local Whisper + Edge TTS + Ollama). Orynn wins **delegated voice operator** (Gemini Live tool routing + back-office agent). Messaging: *"Clicky shows you where to click; Orynn clicks for you."*

### 6.6 Licensing asymmetry

Clicky MIT enables commercial forks and student redistribution. Orynn PolyForm NC blocks commercial use without license — relevant when users ask "why not just use Clicky."

---

## 7. Architecture Diagram — Side by Side

```
CLICKY (tutor)                           ORYNN (operator)
────────────────                           ────────────────

[Hotkey / Wake word]                       [Gemini Live mic stream]
        │                                          │
        ▼                                          ▼
[STT → transcript]                         [Live: one tool / turn]
        │                                          │
        ▼                                    ┌─────┴─────┐
[Screenshot ALL monitors]                    │           │
        │                              desktop_control  start_desktop_task
        ▼                                    │           │
[Classify: locate | lesson | quiz]           ▼           ▼
        │                              [Fast UIA click] [Agent loop]
        ▼                                    │           │
[hybrid_pointer: UIA→OCR→vision]             │     [Launch→Navigate→Act]
        │                                    │           │
        ▼                                    └─────┬─────┘
[LLM + vision context]                             │
        │                                    [Verify + honest speech]
        ▼
[Parse POINT tags / coords]
        │
        ▼
[Overlay: fly → dwell → return]
        │
        ▼
[TTS speak explanation]

Action: USER still clicks          Action: ORYNN invokes controls
Cost: vision every turn              Cost: text-only most steps
```

---

## 8. When Each Product Wins

### 8.1 Choose Clicky when

- Learning new software (Premiere, IDE, unfamiliar SaaS) with a **patient pointer**
- Student/educator context — quiz mode, journal, spaced repetition
- **100% offline** tutor with Ollama on modest hardware
- **MIT license** needed for classroom or commercial redistribution
- User should ** retain muscle memory** by clicking themselves
- Fine-grained **multilingual TTS** voice picking (400+ Edge voices)

### 8.2 Choose Orynn when

- **"Do it for me"** — multi-step desktop goals, not guided lessons
- Hands-busy voice control while user works in another window
- **UIA-first reliability** on Win32/UWP/Electron (after unlock)
- **Coding + browser + desktop** in one agent
- **Free-model economics** at scale (Groq/OpenRouter + zero-token UIA clicks)
- Workflows, connectors, approval gates for real automation risk
- Launch via **`ms-settings:`**, AUMID, shell without GUI tree-walking

### 8.3 Overlap zone (expect user confusion)

Both products:

- Float UI on top of the desktop
- Accept voice about the current screen
- Support multiple LLM providers
- Run locally on Windows 10/11
- Use vision grid-locate as fallback
- Target "don't Alt-Tab to ChatGPT" workflow

Clear positioning: **Clicky = teach; Orynn = operate.**

---

## 9. Code References

### Clicky (investigated tree)

| Path | Role |
|------|------|
| `main.py` | Entry — Qt app, wires overlay + manager + tray |
| `companion_manager.py` | Async orchestrator, lesson state, LLM loop |
| `ai/hybrid_pointer.py` | UIA → OCR → vision three-tier locate |
| `ai/universal_locator.py` | Set-of-Mark grid (12×8 → 6×6) |
| `ai/element_locator.py` | Claude Computer Use coordinate detect |
| `ui/overlay.py` | Blue buddy, bezier flight, annotations |
| `tutor.py` | Window title, privacy guard, classifiers |
| `tutor_features/journal.py` | SQLite Q&A + SM-2 |
| `config.py` | Provider priority chain, env loading |

### Orynn

| Path | Role |
|------|------|
| `app/widget/gemini_live.py` | Live front desk, tool contracts |
| `app/widget/textbox_overlay.py` | Capsule UI, `desktop_control` routing, `clicky-*` tasks |
| `app/widget/virtual_cursor.py` | Clicky-inspired visual cursor |
| `app/tools.py` | `uia_click`, resolver ladder |
| `app/grid_locate.py` | Ported Set-of-Mark grid |
| `app/agent.py` | Back-office agent loop |
| `docs/windows-automation-research/00-master-strategy.md` | Competitor patterns §7.1 |

---

## 10. Sources

### Clicky (primary — local investigation)

- `clicky-windows-investigation/clicky-windows/README.md` — feature list, architecture, coordinate pipeline
- `clicky-windows-investigation/clicky-windows/companion_manager.py` — orchestration, system prompts
- `clicky-windows-investigation/clicky-windows/ai/hybrid_pointer.py` — three-tier pointer
- `clicky-windows-investigation/clicky-windows/ai/universal_locator.py` — grid algorithm
- `clicky-windows-investigation/clicky-windows/ai/element_locator.py` — Claude CU integration
- [farzaa/clicky](https://github.com/farzaa/clicky) — original macOS concept
- [Bitshank-2338/clicky-windows](https://github.com/Bitshank-2338/clicky-windows) — Windows port

### Orynn (internal)

- `README.md`, `docs/ROADMAP.md`
- `docs/windows-automation-research/00-master-strategy.md` §7.1
- `docs/windows-automation-research/04-vision-ocr-pixel.md`
- `docs/windows-automation-research/09-orynn-codebase-audit.md`
- `app/widget/textbox_overlay.py`, `app/grid_locate.py`, `app/widget/virtual_cursor.py`

---

*This document is part of the subagent-storm competitor series. For Orynn's automation strategy, see [00-master-strategy.md](../../windows-automation-research/00-master-strategy.md).*

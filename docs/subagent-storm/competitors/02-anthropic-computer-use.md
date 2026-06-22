# Anthropic Claude Computer Use vs Orynn (UIA-First)

**Date:** 2026-06-22  
**Scope:** Competitive research for Orynn product positioning — read-only synthesis of public Anthropic docs, research posts, and Orynn internal architecture docs.  
**Audience:** Engineering, product, agent-prompt authors

**Related Orynn docs:** [00-master-strategy.md](../../windows-automation-research/00-master-strategy.md) · [01-uia-deep-dive.md](../../windows-automation-research/01-uia-deep-dive.md) · [04-vision-ocr-pixel.md](../../windows-automation-research/04-vision-ocr-pixel.md) · [BENCHMARKS.md](../../BENCHMARKS.md) · [ROADMAP.md](../../ROADMAP.md)

---

## Executive Summary

Anthropic **Computer Use** is a **vision-first, coordinate-based** desktop control contract: Claude sees screenshots, reasons about pixels, and returns structured mouse/keyboard actions. The builder (or Anthropic’s product shell) runs an **agent loop** — execute action → capture screenshot → return `tool_result` — until the task completes.

Orynn is **UIA-first**: it treats Windows UI Automation as the primary control plane, uses semantic tools (`uia_click`, `uia_type`, `uia_find`) keyed on control **names**, and reserves vision (OCR, grid-locate) for agent-only fallback. A **two-tier orchestra** (Gemini Live front desk + back-office agent) optimizes for voice latency and cost at scale.

| Dimension | Anthropic Computer Use | Orynn UIA-first |
|-----------|------------------------|-----------------|
| **Primary perception** | Screenshot pixels | UIA accessibility tree (semantic) |
| **Primary action** | `(x, y)` coordinates + SendInput-style injection | InvokePattern / UIA SendKeys / named control targeting |
| **Typical click path** | Model turn + screenshot every step | UIA ~5 ms local; no model for simple clicks |
| **Platform focus** | API: Linux VM reference; Product: macOS first (Win desktop app emerging) | Windows-native first |
| **Cost model** | High token burn (screenshots dominate context) | Free UIA/OCR tiers; vision only on miss |
| **Integration burden** | Builder implements full agent loop + coordinate scaling | Orynn ships resolver ladder + voice routing |
| **Best at** | Arbitrary GUIs with no accessibility, cross-app reasoning from pixels | Named controls, voice UX, hundreds of apps without per-app playbooks |

**Bottom line:** Anthropic optimizes for *“make the model fit the tools humans already use (mouse + eyes)”*. Orynn optimizes for *“use the cheapest Windows-native semantic layer first, escalate to vision only when semantics fail.”* They solve overlapping problems with opposite default assumptions.

---

## 1. What Anthropic Ships

Anthropic exposes Computer Use across **three surfaces** with different contracts:

### 1.1 API (builder path)

- **Status:** Public beta since October 22, 2024 ([research announcement](https://www.anthropic.com/research/developing-computer-use))
- **Beta headers:** `computer-use-2025-11-24` (Claude Opus 4.8/4.7/4.6, Sonnet 4.6, Opus 4.5); older models use `computer-use-2025-01-24`
- **Tool types:** `computer_20251124` (or `computer_20250124`), bundled with `bash_*` and `text_editor_*` in typical setups
- **Contract:** Claude returns `tool_use` blocks; **your application** captures screenshots, executes clicks/types, and returns `tool_result`. Claude never touches the machine directly.
- **Reference environment:** Docker + Xvfb Linux desktop (Firefox, LibreOffice, etc.) — [anthropics/claude-quickstarts computer-use-demo](https://github.com/anthropics/anthropic-quickstarts/blob/main/computer-use-demo/README.md)

### 1.2 Consumer products (managed path)

As of **March 23, 2026**, Anthropic launched screen control in **Claude Cowork** and **Claude Code** ([Claude Code week 13 notes](https://code.claude.com/docs/en/whats-new/2026-w13)):

| Surface | Platform (as of research date) | Enablement | Notes |
|---------|----------------------------------|------------|-------|
| **Claude Desktop (Cowork)** | macOS; Windows desktop app gaining support | Settings → Desktop app → Computer use | Per-app approval; Accessibility + Screen Recording permissions |
| **Claude Code CLI** | macOS only for CLI computer use | `computer-use` MCP server in `/mcp` | Pro/Max; interactive sessions only; v2.1.85+ |
| **Claude Code Desktop** | macOS + Windows | Settings toggle | Can drive native apps, simulators, GUI-only tools |
| **Dispatch** | Phone → desktop delegation | Tied to Cowork sessions | Background task execution on user’s Mac |

Product path = Anthropic orchestrates the agent loop; API path = you orchestrate it.

### 1.3 Model training insight

Anthropic’s research post emphasizes **pixel-counting accuracy** as a core training objective — the model learns to estimate how many pixels to move the cursor from a screenshot, analogous to fine motor control. Generalization from simple training apps (calculator, text editor) to novel software was a key finding. OSWorld benchmark: **14.9%** for Claude vs **7.7%** next-best at announcement time — far below human **70–75%**, but SOTA among comparable agents ([Developing a computer use model](https://www.anthropic.com/research/developing-computer-use)).

---

## 2. Anthropic Architecture — Agent Loop

```
USER GOAL
    │
    ▼
┌───────────────────────────────────────┐
│  Claude API / Product orchestrator     │
│  • Maintains task plan across turns    │
│  • Emits tool_use (computer/bash/editor)│
└───────────────┬───────────────────────┘
                │ structured action
                ▼
┌───────────────────────────────────────┐
│  Harness (your code OR Anthropic app)  │
│  • screenshot → JPEG/PNG               │
│  • left_click [x,y], type, key, scroll │
│  • optional zoom region (20251124)     │
│  • coordinate remap if scaled          │
└───────────────┬───────────────────────┘
                │ tool_result (+ new screenshot)
                ▼
         (repeat until end_turn)
```

### 2.1 Available actions (`computer` tool)

Per [official API docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool):

| Category | Actions |
|----------|---------|
| **Basic** | `screenshot`, `left_click`, `type`, `key`, `mouse_move` |
| **Enhanced (20250124+)** | `scroll`, `left_click_drag`, `right_click`, `middle_click`, `double_click`, `triple_click`, `left_mouse_down/up`, `hold_key`, `wait` |
| **20251124 only** | `zoom` (region `[x1,y1,x2,y2]`; requires `enable_zoom: true`) |

Companion tools on the same loop:

- **`bash`** — shell in sandbox
- **`text_editor`** — view/edit files via str-replace tool

### 2.2 Perception model — “flipbook,” not stream

Anthropic acknowledges limitations explicitly:

- **Discrete screenshots**, not video — short-lived UI (toasts, spinners) can be missed
- **Slow** relative to human operation
- **Error-prone** on dense UIs, dropdowns, scrollbars (docs recommend keyboard shortcuts as workaround)
- Model may **assume success** without verifying — docs recommend prompting for post-step screenshot evaluation

### 2.3 Coordinate scaling — critical integration detail

The API constrains image size (e.g. **1568 px** long edge / ~**1.15 MP** on older models; **2576 px** on Opus 4.8/4.7). Anthropic recommends:

1. **Pre-scale screenshots** to XGA (**1024×768**) in your harness — do not rely on API-side resize (hurts accuracy)
2. Set `display_width_px` / `display_height_px` to match the **image you send**
3. **Remap coordinates** back to physical display before clicking

Mismatch between declared display size and actual image dimensions is the **primary cause of click misses** ([best practices blog](https://claude.com/blog/best-practices-for-computer-and-browser-use-with-claude)). The `zoom` action mitigates small-target misses on dense UIs.

### 2.4 Cost and latency profile

Order-of-magnitude from public sources and Orynn’s internal analysis ([04-vision-ocr-pixel.md](../../windows-automation-research/04-vision-ocr-pixel.md)):

| Factor | Impact |
|--------|--------|
| Screenshot tokens | ~`width × height / 750` before resizing; dominates loop cost |
| Tool definition overhead | ~735 input tokens (Claude 4.x computer tool) |
| System prompt overhead | ~466–499 tokens for automated tool selection |
| Per-step latency | 1–3+ s model round-trip **plus** capture + injection |
| Accuracy @ 1080p | ~**5 px** when scaling done correctly (Clicky/Orynn cited figure) |

Every meaningful step tends to require a **full multimodal turn** — there is no “free” click path.

---

## 3. Security and Trust Model (Anthropic)

Anthropic treats Computer Use as **higher risk** than chat-only API:

| Control | Description |
|---------|-------------|
| **Sandbox recommendation** | Dedicated VM/container, minimal privileges |
| **Prompt injection** | Screenshots can contain adversarial instructions; classifiers flag injections and may require user confirmation (opt-out via support) |
| **Human confirmation** | Recommended for cookies, payments, ToS acceptance |
| **Product gates** | Per-app approval on Cowork/Code; denied-apps list (Desktop) |
| **Election / abuse monitoring** | Extra classifiers for sensitive domains (2024 research post) |
| **ZDR eligibility** | API computer use eligible for Zero Data Retention org arrangements |

Orynn’s model is different but aligned on consent: disruptive actions need spoken approval; Live path never auto-clicks via vision; input politeness gate prevents fighting the user.

---

## 4. Orynn UIA-First Architecture (Baseline for Comparison)

From [00-master-strategy.md](../../windows-automation-research/00-master-strategy.md):

### 4.1 Two-tier orchestra

| Tier | Role | Control plane | Latency budget |
|------|------|---------------|----------------|
| **Gemini Live (front desk)** | Voice routing, one tool per turn | UIA-only fast path; vision for *read* only | 1–6 s spoken |
| **Back-office agent** | Multi-step goals, recovery | Full resolver ladder + lazy playbooks | 10 s–minutes |

### 4.2 Resolver ladder (default method order)

```
URI/AUMID/shell launch → UIA by control name → keyboard shortcuts
  → Electron unlock → Windows OCR → vision grid-locate (agent only)
  → honest failure with evidence
```

### 4.3 Core UIA tools (`app/tools.py`)

| Tool | Purpose |
|------|---------|
| `uia_find` | Search accessibility tree by name/automation id |
| `uia_click` | Invoke or click control by semantic query |
| `uia_type` | Type into control via UIA (not raw coordinates) |
| `uia_wait` | Block until control appears |
| `electron_check` / `electron_unlock` | Chromium accessibility unlock via relaunch |

Live `desktop_control` uses **fast UIA-only** (`allow_pixel_fallback=False`) — on miss, auto-escalates to back-office agent rather than grid-clicking during voice UX.

### 4.4 Vision fallback (agent only)

| Tier | Method | Latency | Cost |
|------|--------|---------|------|
| 2 | Windows OCR | 0.1–0.5 s | Free |
| 3 | Gemini grid-locate (Set-of-Mark) | 1–4 s | Low ($) |
| — | Claude Computer Use | 1–3 s | Medium–high ($) — **not integrated** |

Orynn deliberately avoids raw `(x,y)` vision prompts; grid returns `cell: 0` → **no click** (fail-safe).

---

## 5. Head-to-Head Comparison

### 5.1 Control plane philosophy

| Question | Anthropic Computer Use | Orynn UIA-first |
|----------|------------------------|-----------------|
| How does the model “see” the UI? | Pixels in screenshots | UIA tree properties (Name, ControlType, patterns) + optional JPEG for comprehension |
| How does the model “click”? | Coordinates from vision | `uia_click("Save")` → InvokePattern or bounded rect |
| What is a “step”? | Usually screenshot → model → action → screenshot | Often local UIA op with zero model tokens |
| Cross-app plan | Model infers from pixels | Launch registry (URI/AUMID) + adaptive profiles |
| DOM / accessibility access? | **No** — explicitly screenshot-only on API path | **Yes** — native Windows UIA |

Anthropic’s research framing: *“make the model fit the tools”* (use software as humans do). Orynn’s framing: *“use the cheapest semantic layer the OS already exposes.”*

### 5.2 Latency and voice UX

| Scenario | Anthropic | Orynn |
|----------|-----------|-------|
| “Click Save” in open Notepad | Screenshot + model turn(s) | `desktop_control` fast UIA ~1–4 s, often no agent |
| “What’s on my screen?” | Screenshot + model | `look_at_screen` (vision read, no click) |
| Multi-step form fill | Many screenshot loops | UIA sequence + agent only if stuck |
| Voice path vision click | Same screenshot loop | **Never** on Live path |

Orynn’s front desk is optimized for **sub-spoken-delay** primitives; Anthropic’s loop is inherently **multimodal-per-step**.

### 5.3 Accuracy tradeoffs

| Method | Click precision | Semantic reliability |
|--------|-----------------|----------------------|
| Anthropic CU (scaled) | ~5 px | High for visible targets; weak on icons, overlapping UI |
| Orynn UIA | Pixel-perfect on Invoke | Depends on app exposing Name/AutomationId |
| Orynn OCR | Word-box centre | Text labels only |
| Orynn grid | ~25–50 px | Icons/canvas; fail-safe on uncertainty |

**Where Anthropic wins:** dense UIs, non-text targets, apps with broken UIA, sub-10 px precision (sliders, drawing), greenfield cross-platform harnesses where UIA doesn’t exist.

**Where Orynn wins:** standard Win32/UWP controls, settings URIs, Electron after unlock, voice commands on open apps, cost-sensitive scale, offline-capable UIA/OCR tiers.

### 5.4 Platform and deployment

| | Anthropic | Orynn |
|---|-----------|-------|
| **Primary OS (API ref)** | Linux X11 VM | Windows 10/11 |
| **Primary OS (consumer)** | macOS (CLI CU macOS-only; Desktop expanding Win) | Windows |
| **Hosting** | Cloud API + optional local Desktop app | Local-first, floating capsule |
| **Model vendor** | Anthropic Claude | Gemini Live + OpenRouter/free models |
| **Builder effort** | Full agent loop, scaling, sandbox | Install Orynn; ladder built-in |

### 5.5 Cost at scale (qualitative)

For **N apps × M actions/day**:

- **Anthropic:** Cost scales with **screenshots × model price** — even “simple” clicks pay vision tokens.
- **Orynn:** Cost scales with **escalation rate** — UIA/OCR handle the bulk; grid/strong model only on miss.

Orynn roadmap explicitly targets **vision-token avoidance** as a benchmark axis ([BENCHMARKS.md](../../BENCHMARKS.md)).

### 5.6 Extensibility

| Capability | Anthropic | Orynn |
|------------|-----------|-------|
| Shell | `bash` tool in loop | `run_terminal` / `run_command` with approval gates |
| File edit | `text_editor` tool | Coding mode + desktop file tools |
| Browser | Screenshot + click in VM browser | Task-scoped browser sessions (roadmap) |
| Workflows | Prompt + examples | `ORYNN WORKFLOWS`, lazy playbooks, adaptive profiles |
| Benchmarks | WebArena (web), OSWorld (desktop) | Internal harness; `verified_desktop_path` flag |

---

## 6. Strategic Implications for Orynn

### 6.1 Do not compete on “screenshot agent” as default

Anthropic has invested heavily in coordinate vision, zoom, classifier defenses, and reference implementations. Orynn’s differentiation is **UIA-first + voice-native orchestration**, not cloning the CU loop as primary.

### 6.2 Selective integration opportunity

Orynn already documents Claude CU as a **tier-3 pointer option** (~5 px) in [04-vision-ocr-pixel.md](../../windows-automation-research/04-vision-ocr-pixel.md) but has **not integrated** it (Gemini-native stack). Consider CU only if:

- Grid-locate miss rate is unacceptable on specific apps
- Customer already has Anthropic API + beta access
- Sub-25 px precision is worth per-click API cost

### 6.3 Voice product gap Anthropic doesn’t optimize for

Cowork/Code target **async desktop delegation** (Pro/Max, research preview). Orynn targets **always-on voice front desk** with honest spoken outcomes, consent gates, and escalation — a different UX contract.

### 6.4 Windows moat

While Anthropic expands Windows Desktop support, Orynn’s depth on **ms-settings URIs, AUMID launch, UIA patterns, Electron unlock, adaptive_windows_profiles.json** is Windows-specific surface area CU docs do not address.

### 6.5 Honest benchmarking

When comparing publicly:

- Anthropic cites **WebArena** (web navigation) on API docs — not identical to Windows UIA tasks.
- Orynn should publish **UIA vs screenshot vs grid** on Notepad/Calculator/Discord tasks per [BENCHMARKS.md](../../BENCHMARKS.md).
- Separate **task success** from **verified_desktop_path** (shell shortcuts don’t count as UI wins).

---

## 7. Feature Matrix (Quick Reference)

| Feature | Anthropic CU | Orynn |
|---------|--------------|-------|
| Screenshot-driven loop | ✅ Primary | ⚠️ Agent fallback only |
| Semantic control by name | ❌ | ✅ Primary (`uia_*`) |
| Coordinate click | ✅ Native tool | ⚠️ pyautogui after OCR/grid |
| Zoom region | ✅ `zoom` action | ⚠️ Grid stage-2 crop |
| Drag / fine mouse | ✅ | ⚠️ Limited |
| Keyboard shortcuts | ✅ `key` action | ✅ `press_keys` |
| Wait for UI | ⚠️ `wait` + screenshot poll | ✅ `uia_wait` |
| Launch apps via OS | ⚠️ Via GUI only | ✅ URI/AUMID/shell |
| Voice-optimized fast path | ❌ | ✅ `desktop_control` |
| Free-model friendly | ❌ | ✅ OpenRouter + UIA |
| Prompt injection defenses | ✅ Classifiers | ⚠️ Untrusted content boundaries |
| Sandbox reference | ✅ Docker/Xvfb | Local user session |
| Multi-monitor | Harness-dependent | ⚠️ Grid primary-only gap |

---

## 8. Sources

### Anthropic (primary)

- [Computer use tool — Claude API Docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool)
- [Developing a computer use model (Oct 22, 2024)](https://www.anthropic.com/research/developing-computer-use)
- [Best practices for computer and browser use with Claude](https://claude.com/blog/best-practices-for-computer-and-browser-use-with-claude)
- [computer-use-demo README (anthropics/claude-quickstarts)](https://github.com/anthropics/anthropic-quickstarts/blob/main/computer-use-demo/README.md)
- [Claude Code — computer use (CLI)](https://code.claude.com/docs/en/computer-use.md)
- [Claude Code — Week 13, March 23–27, 2026](https://code.claude.com/docs/en/whats-new/2026-w13)

### Orynn (internal)

- `docs/windows-automation-research/00-master-strategy.md`
- `docs/windows-automation-research/01-uia-deep-dive.md`
- `docs/windows-automation-research/04-vision-ocr-pixel.md`
- `docs/BENCHMARKS.md`, `docs/ROADMAP.md`
- `app/tools.py`, `app/widget/textbox_overlay.py`, `app/widget/gemini_live.py`

### Secondary commentary (verify against primary)

- TeachMeIDEA, Deck, Pulse Mark, Digital Applied — API integration guides (2025–2026)
- Claude Lab, Fello AI, Coworker AI — Cowork/Code consumer launch coverage (March 2026)

---

*Research note: Anthropic Computer Use remains beta; API headers, model support, and product platform availability change frequently. Re-verify beta header and platform matrix before integration decisions.*

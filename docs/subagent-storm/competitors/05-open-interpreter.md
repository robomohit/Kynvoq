# Competitor Analysis: Open Interpreter vs Orynn

**Date:** 2026-06-22  
**Audience:** Engineering, product, reliability workstreams  
**Scope:** How Open Interpreter overlaps with Orynn's coding, browser, and desktop-control surfaces — and where the stacks diverge  
**Method:** READ ONLY — public docs, GitHub README, Orynn codebase (`README.md`, `PROJECT.md`, `docs/windows-automation-research/00-master-strategy.md`, `SECURITY.md`, `docs/BENCHMARKS.md`)

---

## Executive Summary

**Open Interpreter (OI)** is an open-source **local coding agent** whose core loop is: natural language → LLM generates code → `exec()` on the host. The project has **forked into two lineages**:

| Lineage | Repo | Stack | Positioning |
|---------|------|-------|-------------|
| **New (primary)** | [openinterpreter/openinterpreter](https://github.com/openinterpreter/openinterpreter) | Rust, TUI, Codex-style harness | "Coding agent for low-cost models" |
| **Legacy (community)** | [endolith/open-interpreter](https://github.com/endolith/open-interpreter) | Python, `interpreter` CLI | Original "ChatGPT Code Interpreter locally" |

OI's **computer use** is a **QA skill** layered on top of code execution — web via [agent-browser](https://github.com/vercel-labs/agent-browser), native apps via [trycua/cua](https://github.com/trycua/cua) (vision/pixel CUA). It is **not** a UIA-first Windows automation stack.

**Orynn** is a **voice-native Windows companion** with a **two-tier architecture** (Gemini Live front desk + back-office agent) and a **UIA-first resolver ladder** for desktop control. Coding and browser modes exist, but the product differentiator is reliable native-app automation without screenshot-per-step cost.

**Bottom line:** OI is the closest open-source peer on *"LLM controls my machine locally"*, but it optimizes for **developer terminal workflows and code execution**; Orynn optimizes for **spoken goals, Windows UI Automation, and vision-token avoidance**. They compete on coding/browser; they barely compete on desktop reliability.

---

## 1. What Open Interpreter Is

### 1.1 Origin and mental model

Open Interpreter (2023–) popularized the pattern: give a function-calling model an **`exec(language, code)`** primitive and stream results in a ChatGPT-like terminal. Tasks are solved by **writing programs** (Python, JavaScript, shell) rather than by structured UI tools.

The classic pitch: *"GPT-4 Code Interpreter, but local, with full filesystem and package access."*

### 1.2 Current product (Rust rewrite, 2025–2026)

The canonical repo has been **rewritten in Rust** as a fork of OpenAI Codex, focused on:

- **Harness emulation** — `/harness` switches between `native`, `claude-code`, `kimi-cli`, `qwen-code`, `deepseek-tui`, `swe-agent`, etc., to squeeze performance from **cheap models**.
- **Provider flexibility** — `/model` + LiteLLM-style provider config; local OpenAI-compatible servers (Ollama, LM Studio).
- **Terminal-first UX** — `interpreter` TUI; config at `~/.openinterpreter`.
- **ACP integration** — `interpreter acp` for JetBrains, Zed, and other Agent Client Protocol hosts.
- **MCP, skills, hooks, `AGENTS.md`** — same agent-ecosystem primitives as modern coding agents.
- **Sandbox + approvals** — `read-only` / `workspace-write` / `danger-full-access`; Seatbelt (macOS), bubblewrap (Linux), native Windows sandboxing where configured.

### 1.3 Computer use (QA skill)

OI does **not** ship a first-party UIA layer. "Computer use" is documented as:

> Drive web apps with **agent-browser**; operate native apps with **trycua**.

That places OI's GUI path in the **vision / screenshot / coordinate** family (CUA), same broad class as Anthropic Computer Use and OpenAI Operator — not Orynn's accessibility-tree path.

The legacy Python tree had an in-repo `interpreter/core/computer/` module (browser, display, keyboard, vision). Community forks and PRs (e.g. UI-TARS vision integration) extend that model. The **maintained direction** is Rust CLI + external CUA for GUI.

---

## 2. Architecture Comparison

```
OPEN INTERPRETER (simplified)                ORYNN (simplified)
─────────────────────────────                ───────────────────

User (terminal / IDE via ACP)              User (voice + floating capsule)
        │                                            │
        ▼                                            ▼
Rust TUI / ACP server                      Gemini Live (front desk)
        │                                    one tool/turn, spoken outcomes
        ▼                                            │
Harness + provider router                    ┌───────┴────────┐
        │                                    ▼                ▼
        ▼                              Fast UIA path    Back-office agent
exec() loop ──► sandboxed shell               │           full tool ladder
        │                                     │                │
        ├─► files / packages                  └─────── UIA → OCR → pixel
        ├─► MCP tools
        └─► QA skill ──► agent-browser (web)         FastAPI + ToolExecutor
                    └──► trycua (native GUI)         SafetyManager + SSE stream
```

| Layer | Open Interpreter | Orynn |
|-------|------------------|-------|
| **Primary interface** | Terminal TUI, ACP in IDEs | Voice (Gemini Live) + glass capsule (`run_desktop.py`) |
| **Task decomposition** | Model writes code; harness steers tool use | Front desk routes; back office runs subtasks / adaptive playbooks |
| **Desktop control plane** | External CUA (vision/pixels) via QA skill | UIA by control name → keyboard → Electron unlock → OCR → grid (agent only) |
| **Browser** | agent-browser (real browser automation) | Playwright + accessibility tree |
| **Coding** | Core competency — `exec()` | First-class mode; delegates to coding backends |
| **State** | `~/.openinterpreter` sessions | `tasks/*.json`, overlay state, adaptive profiles |
| **Streaming** | Markdown to terminal | SSE action ticker + aqua glow on target window |

---

## 3. Capability Matrix

| Dimension | Open Interpreter | Orynn | Edge |
|-----------|------------------|-------|------|
| **Local execution** | Yes — core value prop | Yes | Tie |
| **License** | Apache-2.0 | PolyForm NC 1.0.0 | OI for commercial OSS adoption |
| **Voice-native UX** | No | Yes — Gemini Live loop | **Orynn** |
| **Windows UIA automation** | No first-party; delegates to trycua | Yes — primary desktop path | **Orynn** |
| **Vision-token cost per desktop step** | High (CUA path) | Low on UIA path; vision gated | **Orynn** on native apps |
| **Works while window occluded** | Depends on CUA capture | Yes on UIA InvokePattern path | **Orynn** |
| **Coding / data / shell tasks** | Excellent; harness-tuned for cheap models | Good; not harness-specialized | **OI** |
| **IDE embedding (ACP)** | Native `interpreter acp` | No ACP server | **OI** |
| **MCP** | Yes | Yes | Tie |
| **Sandbox models** | Three explicit modes + OS enforcement | Permission scopes + approval gates | Tie (different shapes) |
| **Cross-platform desktop GUI** | trycua (macOS focus in CUA ecosystem) | Windows-only native desktop | Context-dependent |
| **Provider lock-in** | Low — many harnesses/providers | Low — OpenRouter/Groq/Gemini/etc. | Tie |
| **Free-tier viability** | Optimized for low-cost models | Groq + OpenRouter `:free`; UIA reduces tokens | **Orynn** for desktop; **OI** for coding |
| **Always-on-top capsule** | No | Yes | **Orynn** |
| **Honest failure / evidence** | Terminal output | Spoken `ok` field + task logs | **Orynn** for voice UX |

---

## 4. Where Open Interpreter Wins

### 4.1 Developer terminal workflow

OI is built for engineers who live in a shell or IDE. Harness switching (`/harness`, `/model`) is a deliberate product choice: **make DeepSeek/Kimi/Qwen usable** by emulating the prompts and tool patterns of stronger agents. Orynn does not optimize for this; it routes by mode and provider preference.

### 4.2 Code-as-universal-adapter

Any task OI cannot express as a built-in tool, it can **script**: pip install, pandas, ffmpeg, custom APIs. Orynn has connectors and tools, but the **default power user escape hatch** in OI is arbitrary code — broader for one-off automation.

### 4.3 Ecosystem integration

- **ACP** — first-class editor agent panel without custom plugins.
- **Apache-2.0** — easier for companies to embed than PolyForm NC.
- **Rust rewrite** — performance, single shared runtime across terminal tabs.

### 4.4 Cross-platform GUI ambition (via trycua)

On macOS/Linux, OI can point at trycua for native GUI QA. Orynn explicitly scopes **desktop control to Windows**. For a developer testing a cross-platform Electron app from a Mac, OI's QA skill path is more aligned today.

### 4.5 Sandboxing maturity (coding surface)

OI documents Codex-grade sandbox modes with OS-specific enforcement and explicit `danger-full-access` opt-in. Orynn's `SECURITY.md` is honest that it is **not a sandbox boundary** — powerful local automation with approval gates. For **untrusted code execution**, OI's posture is clearer.

---

## 5. Where Orynn Wins

### 5.1 UIA-first desktop reliability

Orynn's README and benchmarks center on **control-name automation** — Calculator under another window, Notepad save, Discord draft — without moving the cursor or sending screenshots every step. OI's documented GUI path (trycua) is **vision-first**, inheriting CUA brittleness and token cost.

Orynn's resolver order (from `docs/windows-automation-research/00-master-strategy.md`):

> URI/AUMID/shell launch → UIA by control name → keyboard shortcuts → Electron unlock → local OCR → vision grid-locate (agent only)

Open Interpreter has **no equivalent ladder** in-tree.

### 5.2 Voice + latency-shaped front desk

Gemini Live acts as a **one-tool-per-turn** front desk with spoken acknowledgments and strict outcome honesty. OI is text-in/text-out (or ACP streaming). For a **hands-busy Windows user**, Orynn's product shape is closer to the job.

### 5.3 Cost structure on desktop tasks

`docs/BENCHMARKS.md` tracks **vision-token avoidance** as a first-class metric. Orynn's UIA path can complete desktop tasks with **text-only** model turns; OI's QA/CUA path typically pays vision or heavy screenshot reasoning per step.

### 5.4 Windows-native depth

Orynn invests in Windows-specific concerns OI does not own:

- `adaptive_windows_profiles.json` — lazy learning when UIA fails
- Electron/Chromium unlock flows
- Launch registry (AUMID, `ms-settings:`, shell verbs)
- `textbox_overlay` busy gates and desktop routing

### 5.5 Unified product: coding + browser + desktop

Both offer multiple modes, but Orynn ships a **single capsule** that auto-detects mode from the goal. OI's computer use is a **skill** on a coding agent, not a voice-first desktop companion.

---

## 6. Overlap Map (What to Steal, What to Ignore)

| User goal | OI path | Orynn path | Recommendation for Orynn |
|-----------|---------|------------|--------------------------|
| "Refactor this repo" | Terminal / ACP — **use OI** | Coding mode | Optional coding-backend delegation; don't chase harness parity |
| "Plot this CSV" | `exec(python)` — **use OI** | Coding + shell | Connectors for common cases; shell for long tail |
| "Fill this web form" | agent-browser QA skill | Playwright a11y tree | Compare reliability; Orynn a11y path is structurally similar |
| "Click Save in Excel" | trycua vision | UIA `InvokePattern` | **Orynn moat** — do not regress to screenshot-default |
| "Run tests against our app UI" | QA skill (CI-friendly) | Desktop agent + benchmarks | Borrow **QA/reporting** ideas, not pixel-first control |
| "Operate my machine by voice" | Not supported | Gemini Live | **Orynn moat** |

---

## 7. Threat Assessment

| Threat level | Area | Rationale |
|--------------|------|-----------|
| **High** | Coding-agent mindshare | OI is the default OSS answer for "local ChatGPT that runs code." Developers evaluating Orynn may already run OI in a terminal. |
| **Medium** | Browser automation | Both can drive real browsers; OI's agent-browser vs Orynn Playwright — feature parity likely, different integration. |
| **Medium** | MCP / skills ecosystem | Shared primitives; OI's skill model could absorb Windows-specific skills faster than Orynn ships features. |
| **Low** | Windows UIA desktop | OI has no in-tree UIA; trycua is a different reliability class. |
| **Low** | Voice companion | OI has no Gemini Live equivalent. |

**Strategic implication:** Position Orynn against OI on **desktop reliability and voice**, not on **terminal coding-agent harnesses**. Where Orynn offers coding mode, cite OI only as an alternative backend mindset (exec loop), not as a desktop peer.

---

## 8. Reliability Lessons for Orynn (from OI's design)

Things worth studying without copying the CUA path:

1. **Explicit sandbox modes** — OI names three postures; Orynn could map permission scopes to similarly named presets in docs/UI.
2. **Harness abstraction** — separating *provider* from *prompt/tool harness* helped OI survive model commoditization; Orynn's `DESKTOP_MODEL` opt-in is a start; front-desk vs back-office is a stronger structural split.
3. **ACP** — if Orynn wants IDE users, an ACP adapter exposing desktop tools (UIA) would be differentiated; OI would expose exec/shell.
4. **QA skill framing** — OI markets computer use as **testing interfaces**; Orynn benchmarks (`docs/BENCHMARKS.md`) already define verification (`verified_desktop_path`) — align messaging.

---

## 9. Quick Reference

| | Open Interpreter | Orynn |
|---|------------------|-------|
| **One-liner** | Local coding agent with optional GUI QA | Voice Windows agent; UIA-first desktop |
| **Install** | `curl` / `irm` installer → `interpreter` | `setup.bat` → `start.bat` capsule |
| **Desktop click** | trycua (vision/CUA) | `uia_click` by control name |
| **Default model story** | Low-cost + harness | Free Groq/OpenRouter; optional `DESKTOP_MODEL` |
| **GitHub** | ~60k+ stars (legacy Python era); active Rust rewrite | Smaller; Windows automation focus |

---

## 10. Sources

- [openinterpreter/openinterpreter README](https://github.com/openinterpreter/openinterpreter) (Rust rewrite, harness, QA skill, ACP)
- [Open Interpreter sandbox docs](https://www.openinterpreter.com/docs/terminal/sandbox)
- [Open Interpreter ACP docs](https://www.openinterpreter.com/docs/terminal/acp)
- [endolith/open-interpreter](https://github.com/endolith/open-interpreter) (legacy Python lineage)
- [trycua/cua](https://github.com/trycua/cua) (OI native GUI dependency)
- [vercel-labs/agent-browser](https://github.com/vercel-labs/agent-browser) (OI web GUI dependency)
- Orynn: `README.md`, `PROJECT.md`, `SECURITY.md`, `docs/BENCHMARKS.md`, `docs/windows-automation-research/00-master-strategy.md`

---

*Subagent storm — competitors series, doc 05. READ ONLY analysis; no Orynn code changes.*

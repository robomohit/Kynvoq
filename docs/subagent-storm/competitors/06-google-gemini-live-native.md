# Google Gemini Live (Native) — Competitor Analysis

**Doc:** `06-google-gemini-live-native.md`  
**Date:** 2026-06-22  
**Scope:** Google's **first-party Gemini Live** experiences — mobile, Chrome, macOS desktop app, and announced desktop agent features (Spark, Live + screen share) — versus Orynn's **custom Live API harness** on Windows  
**Audience:** Orynn product and engineering  
**Related Orynn docs:** [00-master-strategy.md](../../windows-automation-research/00-master-strategy.md) · Code: `app/widget/gemini_live.py`, `app/widget/textbox_overlay.py`

> **Scope boundary:** This file covers Google's consumer/prosumer Gemini Live surfaces and roadmap. Orynn's *implementation* of the same underlying Live API is analyzed here as architectural contrast, not as a separate product. Anthropic CU, OpenAI Operator, Clicky, Power Automate, Open Interpreter, MultiOn/Simular, and Devin are in sibling competitor files.

---

## Executive Summary

**Google Gemini Live (native)** is Google's shipped **real-time voice conversation** layer across Gemini mobile, **Gemini in Chrome** (Windows/macOS), and an emerging **native macOS desktop app** (`gemini.google/mac`). It delivers low-latency spoken dialogue, barge-in, voice selection, and increasingly **visual context** (tab/window/screen sharing) — but today it is primarily a **Google-ecosystem assistant**, not a **local OS operator** for arbitrary Win32 apps.

**Orynn** uses the **same Gemini Live API** (`google.genai`, `gemini-3.1-flash-live-preview`) but wraps it in a **purpose-built Windows harness**: voice-first front desk, **14+ local function tools** (`desktop_control`, `start_desktop_task`, `look_at_screen`, workflows, memory, terminal), **UIA-first fast path**, and a **back-office agent** for multi-step desktop work. Orynn is not competing with Live as a model — it competes with (and depends on) Google's **default Live product experience**.

**Strategic tension:** Google is converging toward Orynn's lane. Announced **Gemini Spark** (local desktop automation), **Live + screen share on desktop**, **MCP connected apps**, and **proactive 24/7 help** mirror Orynn's voice + vision + act story. Google's advantage is distribution, polish, and Workspace integration; Orynn's advantage is **deep Windows control today** (UIA, launch URIs, consent gates, honest spoken outcomes) without waiting for Google's roadmap.

---

## 1. Product Surfaces & Current State (2026)

| Surface | Platform | Live voice | Visual context | Local OS control |
|---------|----------|------------|----------------|------------------|
| **Gemini mobile app** | Android / iOS | **Shipped** — camera + screen share in Live | Screen/camera frames | None — assist only |
| **Gemini in Chrome** | Windows / macOS / Chromebook | **Shipped** — "Go Live" in side panel | Current tab (page content); voice scroll/highlight on page | **Browser only** — tab navigation, auto-browse (gradual rollout) |
| **Gemini macOS app** | Apple Silicon, macOS 15+ | **Settings stub** — voice picker present, Live not yet functional (Apr 2026) | **Share window** (static context, not Live stream yet) | None today; **Spark** announced for summer 2026 |
| **Gemini Windows app** | Windows (rolling) | Chrome Live today; native app + Live expected post–I/O 2026 | Window share in macOS app pattern | **Spark** = announced local automation |
| **AI Studio / Live API** | Developer | Full Live API | Video realtime input, function calling | **DIY** — Orynn's path |
| **Pixel / Chromebook Plus** | Hardware | Deep Live integration | On-device context | Limited OS hooks |

### 1.1 What "native Live" means in practice (June 2026)

**Shipped today (consumer):**

- Natural **back-and-forth voice** with **barge-in** (interrupt mid-response)
- **Voice selection** and closed captions
- **Switch to text** without losing thread
- **Chrome Live**: share current tab; voice commands to scroll/highlight on page ("Scroll me", "Go to…")
- **macOS app**: global shortcut (`Option + Space`), **Share window** for Q&A on visible content, menu-bar presence

**In development / announced (not fully shipped on desktop):**

- **Gemini Live on desktop** — sphere overlay, persistent conversational UI (strings found in macOS app binaries)
- **Live + screen sharing on desktop** — real-time vision while speaking (mobile/AI Studio today; desktop preview)
- **Gemini Spark** — agentic desktop automation across local files and apps (macOS app "this summer"; Windows follow-on)
- **MCP connected apps** — Canva, OpenTable, Instacart, etc.
- **Proactive / 24/7 help** — background awareness, task continuation when device locked (Google blog, Jun 2026)
- **Regional dialects**, refined mic handling for natural pauses ("ums")

---

## 2. Architecture: Google Native vs Orynn Harness

```
GOOGLE GEMINI LIVE (NATIVE)              ORYNN (LIVE API HARNESS)
────────────────────────────             ─────────────────────────
User → Gemini app / Chrome / macOS       User → Orynn overlay (voice)
         ↓                                         ↓
   Google-hosted session                   google.genai Client (user API key)
   Built-in tools: Search, MCP*, Spark*   14 custom function_declarations
   Screen/tab/window share → vision        look_at_screen / capture_window → JPEG
   Chrome auto-browse (web tasks)          desktop_control (UIA fast path)
   No public UIA/OS tool surface           start_desktop_task → back-office agent
   Workspace / Gems / NotebookLM           ORYNN MEMORY + ORYNN WORKFLOWS
   Subscription tiers (Pro/Ultra)          BYOK API + local free tiers (UIA/WMI)
```

\* MCP and Spark are roadmap / limited preview, not universal desktop control today.

### 2.1 Shared foundation: Gemini Live API

Both stacks can use the same underlying capabilities:

| API capability | Google native (typical) | Orynn usage |
|----------------|-------------------------|-------------|
| **WebSocket realtime audio** | Yes | Yes — `client.aio.live.connect` |
| **Input/output transcription** | UI captions | Bubble + debug; turn-boundary finalize |
| **Barge-in (`interrupted`)** | Yes | Yes — flush speaker queue |
| **Session resumption** | Managed by Google | **Explicit** — `_resume_handle`, `go_away` graceful reconnect |
| **Function calling** | MCP, Spark (expanding) | **14 local tools** — desktop, vision, memory, workflows |
| **Realtime video input** | Screen share stream | `send_realtime_input(video=jpeg)` per frame |
| **Google Search grounding** | Built-in (paid tier) | Opt-in `GEMINI_LIVE_SEARCH=1` (off on free tier) |
| **Thinking level** | Opaque | `GEMINI_LIVE_THINKING` env (default MEDIUM) |

**Key insight:** Orynn is a **reference implementation** of what power users want from Live API — local tools, session hardening, proactive alerts — while Google native optimizes for **mass-market chat + Google services**.

---

## 3. Control Plane Comparison

### 3.1 What Google native can do today

| Task class | Mechanism | Depth |
|------------|-----------|-------|
| Voice Q&A, brainstorm | Live audio loop | Strong |
| Explain current web page | Chrome tab content sharing | Strong |
| Voice scroll/highlight on page | Chrome Live navigation | Moderate (gradual rollout) |
| Explain shared window (macOS) | Share window snapshot | Moderate — Q&A, not act |
| Web task completion | **Auto browse** in Chrome | Emerging — browser sandbox |
| Workspace tasks | Gmail/Calendar/Docs side panel | Strong in Google stack |
| Third-party SaaS | **MCP connectors** (rolling) | API-level, not arbitrary UI |
| Native app click/type on Windows | **Not shipped** in consumer Live | — |
| Local files / shell | **Spark** (announced) | Not GA on Windows Jun 2026 |

### 3.2 What Orynn does today (via Live tools)

| Task class | Live tool | Back office |
|------------|-----------|-------------|
| Single UIA click/type in open app | `desktop_control` (~1–4 s) | Escalates on miss |
| Multi-step / launch / vague goal | `start_desktop_task` | Full agent + resolver ladder |
| "What's on screen?" | `look_at_screen` | — |
| Background app peek (gaming) | `list_windows` → `capture_window` | PrintWindow, no focus steal |
| Shell one-liner | `run_terminal` | Approval gates |
| Repeat procedure | `run_workflow` / `save_workflow` | JSON step registry |
| Durable facts | `remember` / `forget` | Injected at reconnect |
| Real-time facts | `web_search` | Not Live Search grounding |
| Proactive task done | `send_task_update` | `[ORYNN — speak out loud NOW]` prefix |

Enforcement: **one desktop tool per turn**; `desktop_control` + `start_desktop_task` cannot batch; Live **never** uses pixel grid-locate.

---

## 4. Voice & Session UX

| Dimension | Google Gemini Live native | Orynn |
|-----------|---------------------------|-------|
| **Activation** | In-app "Go Live"; Chrome side panel; system tray | Hotkey toggle; `ORYNN_LIVE_AUTOSTART=1`; wake word `ORYNN_LIVE_WAKE=1` |
| **Mic privacy** | Streams to Google when Live active | Wake mode: **local** wake listen, cloud only after "Orynn" |
| **Barge-in** | Supported | Supported + speaker queue flush |
| **Greeting on connect** | Product default | **Off** by default (`GEMINI_LIVE_GREETING=0`) — avoids echo loop |
| **Idle sleep** | N/A (product-managed) | `ORYNN_LIVE_IDLE` (default 60 s) in wake mode |
| **Reconnect** | Transparent to user | `go_away` handler, exponential backoff, session resumption, stale audio drain rules |
| **Proactive speech** | Announced 24/7 / Spark | `send_task_update` for task completion mid-conversation |
| **Outcome honesty** | Standard assistant narration | System prompt: **`ok` must match speech** — no optimistic claims |
| **Voice** | Multiple prebuilt voices | Default `Puck`; `GEMINI_LIVE_VOICE` override |

Orynn's session hardening (documented in `gemini_live.py`) reflects **production pain** Google's consumer app may abstract away: WebSocket 1007 on wrong image channel, reconnect transcript concatenation, tool timeout vs long `wait` actions, audio playback on dedicated thread.

---

## 5. Vision & Screen Context

| Approach | Google native | Orynn |
|----------|---------------|-------|
| **Foreground peek** | Tab/window share → model sees content | `look_at_screen` → JPEG via **realtime video** channel |
| **Background window** | Limited / not focus of consumer Live | `capture_window` (PrintWindow, often no focus steal) |
| **Streaming vs snapshot** | Moving toward Live screen stream on desktop | Per-tool frame push; `wait=True` to race FunctionResponse |
| **Act on what you see** | Chrome voice navigation; Spark (future) | `desktop_control` after `look_at_screen` — separate turns |
| **Hallucination guard** | Standard disclaimers | Prompt: never describe screen without fresh frame; never ask user "what do you see" |

**Orynn lesson encoded in code:** Images must use `send_realtime_input(video=…)`, not `send_client_content` inline blobs — Live API rejects the latter with WS 1007 and drops the session.

---

## 6. Pricing, Access & Platform Fit

| Dimension | Google Gemini Live native | Orynn |
|-----------|---------------------------|-------|
| **Cost model** | Free tier + **Google AI Pro/Ultra** subscriptions | User's **Gemini API key** (free tier works for voice + tools; Search grounding paid) |
| **Windows desktop** | **Chrome Live** today; native Windows app rolling | **Core platform** — Win32 UIA, PowerShell, WMI |
| **macOS** | Native app (Apple Silicon) | Non-goal near-term per ROADMAP |
| **Offline** | Requires cloud | Local UIA/tools; cloud for model only |
| **Account lock-in** | Google Account, Workspace | BYOK; local task/memory files |
| **Enterprise** | Workspace admin controls | Self-hosted harness; no Google admin surface |

For Orynn's target user (**Windows power user, hands-busy voice**), Google native is **weaker today** on OS control but **stronger** on zero-setup and Workspace breadth.

---

## 7. Roadmap Collision: Spark, MCP, Proactive Live

Google's Jun 2026 announcements directly overlap Orynn:

| Google initiative | Orynn equivalent | Orynn delta |
|-------------------|-------------------|-------------|
| **Gemini Spark** (desktop agent) | `start_desktop_task` + back-office agent | UIA-first ladder; already shipping; Windows-first |
| **Live + screen share desktop** | `look_at_screen` + Live video input | Orynn adds **act** tools, not just see |
| **MCP connected apps** | Connectors / Playwright (proposed) | Orynn can target **any** Win32 app, not MCP partners only |
| **Proactive 24/7 help** | `send_task_update`, wake word | Local proactive on **user's tasks**, not Google's cloud agenda |
| **Stream to cursor** (rumored I/O) | Voice → type into focused field | Orynn `desktop_control` type action |
| **Gems** (custom experts) | `remember` + workflows | Local, user-owned JSON; no Google cloud gem store |

**Risk:** If Spark on Windows ships with polished voice + vision + reliable click/type, Google's **distribution** could absorb casual users who would otherwise try Orynn.

**Opportunity:** Spark will likely be **vision/pixel or accessibility-generic** first — Orynn's **UIA-by-name economics** and **honest voice outcomes** remain differentiated for Electron-heavy, DPI-scaled, and legacy Win32 surfaces.

---

## 8. Feature Matrix (Summary)

| Dimension | Google Gemini Live native | Orynn |
|-----------|---------------------------|-------|
| **Primary goal** | Universal Google AI assistant | **Windows voice operator** |
| **Model** | Google picks (Gemini 3.x) | Same Live API (`gemini-3.1-flash-live-preview`) |
| **Local Win32 control** | Not GA (Spark pending) | **Core** — UIA, shell, URIs |
| **Browser control** | **Core** — Chrome Live, auto browse | Connectors; Playwright preferred over pixels |
| **Voice-native** | **Core** | **Core** |
| **Custom tools** | MCP + Google builtins | 14 local functions + dynamic memory |
| **Two-tier orchestration** | Single product surface | **Front desk vs back office** |
| **Fast click latency** | N/A today | ~1–4 s UIA path |
| **Session engineering** | Opaque | Resumption, go_away, reconnect audio hygiene |
| **Privacy / wake** | Cloud when Live on | Optional offline wake word |
| **Workflow repeatability** | Gems (cloud) | `ORYNN WORKFLOWS` (local) |

---

## 9. Where Google Native Wins

1. **Zero-install voice AI** — Chrome Live on any Windows PC with a Google account  
2. **Polish & scale** — voice UX, captions, dialects, sphere overlay (incoming)  
3. **Web-native tasks** — tab sharing, voice page navigation, auto browse  
4. **Workspace depth** — Gmail, Calendar, Docs, Meet notes — Orynn does not compete here  
5. **MCP partner ecosystem** — turnkey Canva/OpenTable/etc. without custom connectors  
6. **No API key management** — subscription simplicity for non-technical users  
7. **Mobile + desktop continuity** — same Google memory across devices  

---

## 10. Where Orynn Wins

1. **"Do it on my Windows machine" today** — not waiting for Spark GA  
2. **UIA-first control plane** — semantic clicks vs screenshot loops for routine actions  
3. **Architectural honesty** — spoken outcomes tied to `ok`; consent gates (`confirmed=true`)  
4. **Deep session control** — resumption handles, proactive task alerts, wake-word privacy mode  
5. **Local memory & workflows** — injected every reconnect; no Google cloud lock-in  
6. **Back-office escalation** — Live stays shallow; agent owns grid/OCR/Electron unlock  
7. **Windows-native research stack** — ms-settings URIs, adaptive profiles, launch registry  
8. **Developer-owned harness** — can swap models, tune thinking level, disable Search on free tier  

---

## 11. Dependency & Competitive Paradox

Orynn **depends on** the Gemini Live API that powers Google's native product. If Google:

- **Raises Live API pricing** or restricts function calling on free tier → Orynn COGS hurt  
- **Improves native Spark on Windows** → Orynn's "voice operator" story faces direct competition  
- **Deprecates or changes** realtime video input semantics → Orynn vision path breaks (already sensitive to 1007)  
- **Opens richer MCP on Live API** → Orynn could **integrate** partner tools without building connectors  

**Mitigation already in Orynn DNA:** model-agnostic back office (OpenRouter in agent path), UIA/OCR value independent of Live, local workflows portable across front-desk models.

---

## 12. Strategic Implications for Orynn

1. **Do not compete on "voice chat with Google"** — Google wins distribution. Compete on **Windows operator depth** and **honest local execution**.

2. **Treat Chrome Live + Spark as the benchmark UX** — sphere overlay, seamless vision, proactive nudges. Orynn's overlay/cursor pill should feel as fluid; session bugs (bubble leak, silent turns) are existential vs Google's polish.

3. **Double down on UIA-first** — When Spark ships, expect pixel/AX-generic automation. Orynn's master strategy (launch → navigate → act) is the moat for legacy Windows.

4. **Watch I/O / Spark on Windows** — First release will define overlap. Position Orynn as **"Spark for everything Google won't hook"** — Steam, legacy LOB, custom Electron, PowerShell, local files without Workspace.

5. **Exploit API-level features Google buries** — Session resumption, thinking levels, async function calling docs — Orynn already implements resumption; ensure long `start_desktop_task` runs use non-blocking patterns per Google's async FC guidance.

6. **MCP as complement** — When Google ships MCP on Live, Orynn could expose `run_workflow` + MCP side by side: local OS for depth, MCP for SaaS partners.

7. **Free-tier Search grounding** — Orynn correctly defaults Search off on free keys; native Gemini bundles Search for paid users. Market `web_search` tool + `run_terminal` as free-tier substitutes.

---

## 13. Known Limitations (Google Native, Live-Specific)

1. **No general Windows desktop operator (Jun 2026)** — Consumer Live assists and browses; does not drive arbitrary installed apps via UIA.

2. **Platform split** — Best Live+vision on mobile; desktop catching up. Orynn is inverted (Windows-first).

3. **Browser-centric on Windows** — Primary path is Chrome, not native shell integration.

4. **Tool surface opaque** — Users cannot add custom function tools to consumer Live; developers must use AI Studio/Vertex.

5. **Google account & data policy** — Screen/tab content flows to Google cloud; enterprise data residency concerns.

6. **Auto browse / Spark safety** — New agentic surfaces inherit prompt-injection and irreversible-action risks; watch-mode style mitigations TBD on desktop.

7. **Feature gating** — Live on desktop, dialects, Spark likely **Pro/Ultra** first — fragments user base.

8. **No honest `ok` contract** — Native assistant can narrate optimistically; Orynn's explicit outcome discipline is a trust differentiator.

---

## 14. Primary Sources

| Source | URL |
|--------|-----|
| Gemini app evolution (proactive, Spark, Live) | https://blog.google/innovation-and-ai/products/gemini-app/next-evolution-gemini-app/ |
| Gemini for macOS | https://gemini.google/mac/ |
| Use Gemini app on Mac (help) | https://support.google.com/gemini/answer/17011627 |
| Gemini Live in Chrome | https://support.google.com/gemini/answer/16363185 |
| Gemini in Chrome (computer) | https://support.google.com/gemini/answer/16283624 |
| Live API session management | https://ai.google.dev/gemini-api/docs/live-api/session-management |
| Live API best practices | https://ai.google.dev/gemini-api/docs/live-api/best-practices |
| Live API built-in tools (Vertex) | https://cloud.google.com/vertex-ai/generative-ai/docs/live-api/tools |
| Async function calling (Live) | https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/live-api/asynchronous-function-calling |
| Desktop Live + screen share (preview reporting) | https://www.testingcatalog.com/google-tests-live-mode-with-screen-sharing-for-gemini-desktop/ |

**Orynn code references:** `app/widget/gemini_live.py` (model, tools, resumption, vision channel), `app/widget/textbox_overlay.py` (routing, memory inject), `docs/windows-automation-research/00-master-strategy.md`.

---

*This document is part of the subagent-storm competitor series. Orynn builds on the Gemini Live API; Google's native Live product is both **platform** and **converging competitor**.*

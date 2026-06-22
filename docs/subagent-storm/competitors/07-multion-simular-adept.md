# Competitor Analysis: MultiOn / AGI Inc., Simular, Adept

**Date:** 2026-06-22  
**Scope:** READ ONLY — landscape research for Orynn positioning  
**Orynn baseline:** UIA-first Windows desktop agent + Gemini Live voice front desk + back-office escalation ladder

---

## Executive Summary

These three companies represent three distinct bets in the computer-use agent space:

| Company | Primary bet | Control plane | Orynn overlap |
|---------|-------------|---------------|---------------|
| **MultiOn → AGI Inc.** | On-device, voice-first mobile agents; edge AI partnerships | Touch/GUI on phones; claims desktop + browser SOTA | Low today (mobile-first); high if AGI-0 ships on Windows laptops |
| **Simular** | Neuro-symbolic desktop agents — explore with LLM, execute with deterministic code | Mouse/keyboard GUI + browser + terminal + APIs | **High** — closest architectural peer for full-desktop automation |
| **Adept** | Enterprise workflow agents over legacy SaaS UIs | Proprietary actuation DSL + multimodal models | Medium — enterprise/RPA lane, not consumer voice companion |

**Orynn's clearest differentiation vs all three:** native Windows **UI Automation (UIA) by control name** as the default actuation layer — no cursor movement, no per-step screenshots, works on covered windows. Simular and Adept default to visual/GUI actuation; MultiOn/AGI has pivoted away from the hosted browser-agent product that originally made the MultiOn name.

---

## 1. MultiOn / AGI Inc.

### 1.1 Company trajectory

- **Founded as MultiOn** — early category leader in browser-based AI agents (Chrome extension, natural-language web task completion).
- **Rebranded to AGI, Inc.** ([theagi.company](https://www.theagi.company/)) — positioning shifted from hosted browser automation to **on-device, privacy-first agentic AI** at the edge.
- **Flagship product: AGI-0** — voice-driven mobile agent; early access / CES 2026 demos emphasize hands-free control of smartphone apps (rideshare, food delivery, messaging, travel).
- **Partnerships:** Qualcomm (Snapdragon agentic AI), Lenovo (MWC proof-of-concept), Visa — signals hardware/commerce integration rather than a developer-first automation API.

### 1.2 Technical approach (historical + current)

**Browser era (MultiOn, ~2023–2024):**

- Chrome extension with full browser control.
- Observation: DOM representation + execution history + user goal.
- Research: **Agent Q** ([arXiv:2408.07199](https://arxiv.org/abs/2408.07199)) — guided Monte Carlo Tree Search (MCTS) + LLM self-critique + offline Direct Preference Optimization (DPO) from successful and failed web trajectories. Reported strong WebShop and real-world booking results on LLaMA 3-70B.
- Output format: structured plan → thought → command → status per step.

**Current era (AGI-0, 2025–2026):**

- On-device inference — "the device is the AI," minimal cloud round-trips.
- Proactive scheduling — agent acts on user's behalf across apps, not just Q&A.
- Claims **#1 on major computer-control benchmarks** across mobile, desktop OS, and browser ([theagi.company/agent](https://www.theagi.company/agent)) — marketing claims; independent reproduction not verified here.
- **AGI Agent SDK** for OEM embedding (universal voice assistant controlling any app on device).

### 1.3 Product & GTM

| Dimension | MultiOn (legacy) | AGI Inc. (current) |
|-----------|------------------|---------------------|
| Surface | Chrome extension, web | Android app, OEM SDK |
| Pricing | Historically ~$20/mo Pro (may be stale) | Early access waitlist; no transparent public pricing |
| API | REST API + Python/TS SDKs (legacy) | SDK for device OEMs, not general developer infra |
| Privacy | Cloud-dependent | On-device positioning |

### 1.4 Strengths

- Strong research pedigree (Agent Q, self-improving agents).
- Mobile + edge narrative is differentiated; Qualcomm/Lenovo partnerships give distribution path into billions of devices.
- Voice-native, proactive agent — aligns with where Orynn's Gemini Live front desk is headed, but on phone not Windows desktop.
- High-profile press (CES 2026, MWC) and benchmark marketing.

### 1.5 Weaknesses / risks

- **Product discontinuity** — buyers who wanted a hosted browser agent may find the current AGI Inc. site does not match legacy MultiOn reviews.
- Opaque pricing and packaging post-pivot.
- Windows desktop is claimed but not the demonstrated hero surface; Android/mobile is.
- Closed stack — no UIA-first, no local inspectable Windows companion like Orynn.

### 1.6 vs Orynn

| Dimension | AGI Inc. / MultiOn | Orynn |
|-----------|-------------------|-------|
| Primary platform | Mobile (Android), OEM SDK | Windows 10/11 desktop |
| Default actuation | Touch/GUI (claimed cross-domain) | UIA control names → OCR → pixels (agent only) |
| Voice | Core UX (AGI-0) | Gemini Live front desk |
| Local / private | On-device goal | Local app; LLM provider configurable |
| Cost model | Unknown / early access | Free-tier models via OpenRouter/Groq |
| Open source | No | Yes (PolyForm NC) |

**Takeaway:** MultiOn is no longer the direct browser-automation competitor it once was. Watch AGI-0 if it ships on Snapdragon Windows laptops with desktop GUI control — that would overlap Orynn's lane. Until then, Orynn wins on **Windows-native UIA reliability** and **inspectable local automation**.

---

## 2. Simular

### 2.1 Company overview

- **HQ:** Palo Alto, CA  
- **Funding:** $21.5M Series A (Dec 2025, Felicis lead; NVentures, South Park Commons) — [TechCrunch](https://techcrunch.com/2025/12/02/simular-releases-mac-os-ai-agent-raises-21-5m-from-felicis-with-windows-coming-soon/)  
- **Research lineage:** Agent S paper series (S, S2, S3) — claims first framework to outperform humans on **OSWorld** benchmark for real desktop apps.  
- **Microsoft relationship:** One of five companies in **Windows 365 for Agents** program (with Manus AI, Fellou, Genspark, TinyFish).

### 2.2 Product line

| Product | Positioning | Deployment |
|---------|-------------|------------|
| **Sai** | Always-on AI coworker; cloud VM or BYOD (Mac, Windows, Mac mini) | Hosted workspace or local device |
| **Simular Pro** | Production-grade, high-throughput desktop automation for teams | Local machine; audit logs, approvals, webhooks, schedules |
| **Agent S (open source)** | Research framework | macOS (open); Windows in progress |

### 2.3 Technical approach: neuro-symbolic computer use

Simular's core differentiator is explicit:

> **Neural Agent** (explorer) — perceives UI, interprets context, plans how to accomplish goals.  
> **Symbolic Agent** (executor) — converts exploration into **deterministic, editable code** for repeatable runs.

This directly attacks the #1 failure mode of pure LLM agents: **non-deterministic replay**. Once a workflow succeeds, the symbolic layer should run it identically next time — closer to RPA than raw vision-loop agents.

**Four interaction modes in one system:**

1. **GUI** — mouse movement, clicks, screen reading (human-like)  
2. **Browser** — web navigation, forms  
3. **Terminal** — shell commands, scripts  
4. **API** — direct tool calls when faster than GUI  

### 2.4 Product characteristics

- **Always-on background execution** — work continues while user is away (Sai cloud VM model).
- **Approval gates** for sensitive actions (send email, delete files).
- **Transparent action logs** — full run history, pause/edit/resume.
- **Speed tradeoff:** Reviews note GUI control is powerful but **2–3× slower than manual** for simple tasks — watching a hesitant human operator.

### 2.5 Strengths

- Closest commercial peer to Orynn's "control the whole desktop" ambition.
- Neuro-symbolic architecture is a credible answer to reliability — aligns with Orynn's lazy playbooks + adaptive profiles, but Simular compiles to code explicitly.
- OSWorld research credibility; Microsoft Windows partnership validates enterprise interest.
- Production features (approvals, webhooks, schedules) ahead of many research demos.

### 2.6 Weaknesses

- **GUI-first** — still moves the mouse and reads the screen; no UIA-by-name fast path.
- macOS 1.0 shipped Dec 2025; Windows version timeline vague ("coming soon" via Windows 365 for Agents).
- Paid SaaS — not free/local-first like Orynn's OpenRouter `:free` path.
- Slow for short tasks; optimized for long multi-step workflows.

### 2.7 vs Orynn

| Dimension | Simular (Sai / Pro) | Orynn |
|-----------|---------------------|-------|
| Desktop actuation | GUI mouse/keyboard + screen | **UIA-first** (no cursor, no screenshots) |
| Reliability strategy | Neural explore → symbolic code | UIA → keyboard → Electron unlock → OCR → grid (agent only) |
| Voice | Not primary | Gemini Live front desk |
| Always-on cloud VM | Yes (Sai) | Local only |
| Windows maturity | In development | Primary platform |
| Cost | Paid tiers | Free-tier capable |
| Open source | Agent S (partial) | Full app (PolyForm NC) |

**Takeaway:** Simular is Orynn's **most direct desktop competitor**. Orynn should emphasize:

1. **Speed and cost** — UIA steps are text-only, sub-second, no vision tokens.  
2. **Background operation** — UIA clicks work on covered windows; GUI agents often need foreground focus.  
3. **Borrow their playbook** — neuro-symbolic "compile successful runs to deterministic replay" maps cleanly onto Orynn's lazy playbooks and `adaptive_windows_profiles.json`.

---

## 3. Adept

### 3.1 Company overview

- **Founded:** 2022, San Francisco  
- **Funding:** ~$415M (Series B, $1B valuation, March 2023); investors include General Catalyst, Greylock, NVIDIA, Microsoft, Workday Ventures  
- **Founders:** David Luan (ex-OpenAI VP Engineering), Ashish Vaswani (Transformer co-author), and others from Google/OpenAI  
- **June 2024 inflection:** Amazon hired Luan + co-founders + ~⅔ of team; **non-exclusive license** for Adept's multimodal models, agent data, and actuation tech. Adept continues independently under CEO **Zach Brock**.  
- **2024–2026 pivot:** Stopped competing on frontier foundation-model training; focused on **Adept Workflows** — enterprise agentic automation layer.

### 3.2 Technical stack

| Layer | Description |
|-------|-------------|
| **ACT-1** (Action Transformer) | Maps natural-language intent → UI actions |
| **Fuyu** | Multodal vision model for UI understanding |
| **Proprietary actuation DSL** | Custom software layer for actions across websites and desktop apps |
| **Training data** | Trillions of tokens specific to web UIs and real software usage |
| **Capabilities** | UI localization, web VQA, end-to-end multi-step enterprise workflows |

Reported benchmark claims (marketing): ~93% UI localization, ~88% workflow completion — not independently verified.

### 3.3 Product: Adept Workflows

- Natural-language setup of automations in minutes (vs months for traditional RPA).
- Targets **legacy enterprise software** without modern APIs: Salesforce, SAP, Workday, ServiceNow, Oracle, Tableau.
- Human-in-the-loop for high-stakes steps.
- Resilience to UI changes — marketed as low-maintenance vs brittle RPA selectors.
- **Private beta** (~200 companies as of early 2026); GA targeted mid-2026.
- **Enterprise-only** — no public pricing, no self-serve API docs.

### 3.4 Amazon relationship

- Adept tech accelerates Amazon AGI team's "digital agents that automate software workflows."
- David Luan leads Amazon AGI SF Lab; owns Automations team.
- FTC scrutiny on whether the deal was a de facto acquisition — Adept investors reportedly made whole via Amazon licensing fees (~$25M to company).

### 3.5 Strengths

- Deepest enterprise GTM and funding in this trio.
- Full-stack agent training data + actuation — not just wrapping GPT-4V.
- Explicit focus on workflows incumbents (UiPath, Automation Anywhere) cannot easily AI-native.
- Production deployments claimed in mission-critical environments (dozens of steps).

### 3.6 Weaknesses

- **Not a consumer product** — no floating capsule, no voice companion, no free tier.
- Post-founder-departure uncertainty; split brain between Adept (enterprise) and Amazon (internal AGI).
- GUI/actuation-based — same screenshot/DOM actuation family as other vision agents, not UIA-native.
- Closed, sales-led — individual developers and power users cannot self-serve.

### 3.7 vs Orynn

| Dimension | Adept | Orynn |
|-----------|-------|-------|
| Target buyer | Enterprise ops / IT | Individual power user / developer |
| Pricing | Enterprise sales only | Free-tier capable |
| Platform | Cross-platform web + desktop SaaS | Windows-native |
| Actuation | Proprietary DSL + vision | UIA-first |
| Voice | No | Gemini Live |
| Deployment | Cloud / managed | Local |

**Takeaway:** Adept competes in the **enterprise RPA replacement** lane, not the personal AI companion lane. Orynn is unlikely to lose individual users to Adept, but Adept validates the market for "agents that click software UIs." If Orynn pursues B2B, Adept's workflow recording → reliable replay pattern and enterprise compliance story are the bar.

---

## 4. Cross-competitor comparison matrix

| Capability | Orynn | MultiOn/AGI | Simular | Adept |
|------------|:-----:|:-----------:|:-------:|:-----:|
| Windows desktop (primary) | ✅ | ⚠️ claimed | ⚠️ in dev | ✅ |
| UIA / a11y tree first | ✅ | ❌ | ❌ | ❌ |
| Vision/GUI fallback | Agent only | ✅ | ✅ | ✅ |
| Voice-native UX | ✅ Live | ✅ AGI-0 | ❌ | ❌ |
| Deterministic replay | Playbooks | ❓ | ✅ symbolic code | ✅ workflows |
| Always-on cloud agent | ❌ | ❌ | ✅ Sai VM | ✅ enterprise |
| Open source | ✅ | ❌ | Partial | ❌ |
| Free to run | ✅ | ❌ | ❌ | ❌ |
| Enterprise sales motion | ❌ | OEM SDK | ✅ Pro | ✅ primary |
| Browser automation | ✅ | ✅ legacy | ✅ | ✅ |
| Terminal / code | ✅ | ❓ | ✅ | ❓ |
| Approval gates | ✅ | ❓ | ✅ | ✅ HITL |
| On-device / local inference | Ollama option | ✅ goal | Local Pro | ❌ |

---

## 5. Strategic implications for Orynn

### 5.1 What to steal

1. **Simular's neuro-symbolic split** — After a successful UIA path, persist it as a deterministic playbook immediately; don't re-reason every run. Orynn's `adaptive_windows_profiles.json` is the seed; formalize "explore once, replay many."
2. **Simular Pro's audit trail** — Run histories, pause/edit/resume are table stakes for production trust. Orynn has approval gates; add richer replay/export for power users.
3. **Adept's workflow resilience narrative** — Market UIA-by-name as *more* resilient than pixel bots when UI themes change but control names stay stable.
4. **AGI's proactive scheduling** — "Do X every morning" is a natural extension for Orynn workflows + Live routing.

### 5.2 What to defend

1. **UIA-first speed and cost** — No competitor in this set leads with accessibility-tree actuation. Benchmark and publish: steps, vision tokens avoided, covered-window success.
2. **Local inspectability** — Open codebase, localhost API, permission scopes. Enterprise vendors are black boxes.
3. **Free-tier viability** — Simular and Adept are paid; AGI is waitlist. Orynn's Groq/OpenRouter `:free` path is a real moat for hobbyists and students.
4. **Voice + desktop unity** — Only AGI-0 competes here, and not on Windows desktop today.

### 5.3 Threats to monitor

| Threat | Likelihood | Mitigation |
|--------|------------|------------|
| Simular ships Windows 1.0 with Microsoft co-marketing | High (2026) | Ship Windows polish; publish OSWorld-style honest benchmarks |
| AGI-0 on Snapdragon Windows laptops | Medium | UIA still wins for native Win32/UWP; prepare Electron/CDP path |
| Adept + Amazon bundle in enterprise | Medium | Stay consumer/prosumer; partner later if B2B emerges |
| GUI agents "good enough" on vision models | Medium | Keep ladder cheap; vision only on agent escalation |

---

## 6. Sources

- [AGI, Inc.](https://www.theagi.company/) — company site, AGI-0 positioning, Qualcomm/Lenovo partnerships  
- [AGI Agent / AGI-0 product page](https://www.theagi.company/agent) — benchmarks, SDK  
- [Agent Q paper](https://arxiv.org/abs/2408.07199) — MultiOn web agent research (MCTS + DPO)  
- [Simular — Sai](https://www.simular.ai/sai) — product positioning  
- [Simular Pro announcement](https://www.simular.ai/articles/introducing-simular-pro-our-first-production-ready-computer-use-agent) — neuro-symbolic architecture  
- [TechCrunch — Simular Series A](https://techcrunch.com/2025/12/02/simular-releases-mac-os-ai-agent-raises-21-5m-from-felicis-with-windows-coming-soon/) — funding, Windows 365 for Agents  
- [Adept.ai](https://www.adept.ai/) — enterprise agent capabilities  
- [Adept update blog](https://www.adept.ai/blog/adept-update/) — June 2024 pivot  
- [Reuters — Amazon hires Adept founders](https://www.reuters.com/technology/amazon-hires-ai-startup-adepts-cofounders-join-its-ai-org-2024-06-28/)  
- Orynn internal: `README.md`, `docs/windows-automation-research/00-master-strategy.md`, `docs/BENCHMARKS.md`

---

*Subagent storm doc #07 — READ ONLY research, no code changes.*

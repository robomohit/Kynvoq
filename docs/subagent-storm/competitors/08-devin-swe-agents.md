# Devin & SWE Agents — Desktop Agent Landscape

**Doc:** `08-devin-swe-agents.md`  
**Date:** 2026-06-22  
**Scope:** Cognition **Devin** (cloud + desktop), the broader **software-engineering agent (SWE)** category, and how that landscape relates to — and diverges from — **desktop / computer-use agents** like Orynn  
**Audience:** Orynn product and engineering  
**Related Orynn docs:** [00-master-strategy.md](../../windows-automation-research/00-master-strategy.md)

> **Scope boundary:** This file covers autonomous **coding / dev-environment agents** (Devin, OpenHands, SWE-agent, IDE background agents, Jules). Browser/computer agents (Operator, Anthropic computer use), RPA (Power Automate), and voice-native local desktop operators (Orynn) are in sibling competitor files.

---

## Executive Summary

**Devin** (Cognition) is the flagship **hosted autonomous software engineer**: a cloud agent that plans, edits code, runs tests, browses docs, and opens pull requests inside an isolated **Devbox** VM — not on the user's physical Windows desktop. Cognition's 2025 acquisition of **Windsurf** (rebranded **Devin Desktop** in June 2026) adds an **IDE-integrated, human-in-the-loop** lane with proprietary **SWE-1.x** models, while cloud Devin remains the **delegate-and-review** lane for full tasks.

The wider **SWE agent landscape** (OpenHands, Princeton **SWE-agent**, Cursor **Background Agent**, Google **Jules**, Claude Code, Cline, Sweep) shares a common **Agent-Computer Interface (ACI)**: shell + editor + browser inside a **sandboxed dev environment**. Benchmarks like **SWE-bench Verified** (issue → patch) dominate evaluation; scores above ~70% on curated sets coexist with ~18–20% on **SWE-bench-Live** novel issues — a reminder that scaffolding and evaluation hygiene matter as much as model choice.

**Critical distinction for Orynn:** SWE agents automate **software delivery** in **repos and VMs**. Orynn automates **the user's live Windows session** — native apps, settings, voice, UIA-first control. Devin's "desktop" is a **Linux Devbox with VS Code and Chrome**, not Excel on the user's monitor or `ms-settings:` URIs. Overlap appears only at the margins (terminal commands, browser SaaS, optional local harnesses).

**Orynn positioning vs Devin/SWE:** Orynn is a **voice-native local Windows companion** with **UIA-first** desktop control and a **Gemini Live front desk + back-office agent** split. Devin is a **cloud coding teammate** with **ACU-metered** autonomous sessions and PR-centric outcomes. Compete on **"do it on my actual PC"** and **hands-busy voice**; do not compete on **managed parallel PR factories** or **SWE-bench leaderboard** narratives.

---

## 1. Landscape Map — Two "Desktop" Meanings

The phrase **desktop agent** forks into two markets that press and investors often conflate:

| Meaning | What "desktop" is | Primary tools | Example products | Success metric |
|---------|-------------------|---------------|------------------|----------------|
| **A. OS / computer-use agent** | User's physical OS session (Windows/macOS) | UIA, shell, pixel/CUA, voice | Orynn, Operator/CUA, Anthropic computer use, Clicky | Task done on *your* machine |
| **B. Dev-environment agent** | Sandboxed VM or IDE workspace | Shell, git, editor, browser in sandbox | Devin, OpenHands, Cursor BG agent, SWE-agent | PR merged, tests green |

```
USER INTENT: "Automate my computer"
         │
         ├─► OS session control (A)          ├─► Repo / IDE automation (B)
         │    Voice, native apps, settings     │    Issues → patches → CI
         │    Orynn, Operator, CU              │    Devin, OpenHands, Jules
         │                                     │
         └─► Overlap: terminal, browser SaaS,  └─► Overlap only where B's
              some Electron apps                     sandbox mirrors A's apps
```

**Devin/SWE agents live entirely in column B** unless a team wires a custom `Computer` harness to a real machine (unusual for Devin Cloud; more common in research forks).

---

## 2. Cognition Devin — Product Stack (2026)

### 2.1 Cloud Devin (autonomous SWE)

| Dimension | Detail |
|-----------|--------|
| **Vendor** | Cognition (independent; model-agnostic across OpenAI, Anthropic, Google, in-house SWE models) |
| **Launch** | March 2024 — positioned as first autonomous AI software engineer |
| **Session unit** | One task → isolated **Devbox** (Linux VM: shell, embedded IDE, browser) |
| **Architecture** | **Brain** (stateless cloud intelligence, Cognition-hosted) + **Devbox** (execution environment) |
| **Workflow** | Ingest ticket/Slack/PR comment → plan → gather context (Knowledge) → code/test/browse → PR for human review |
| **Metering** | **Agent Compute Units (ACUs)** — planning, context, execution, browser, code execution per action class |
| **Enterprise deploy** | **Enterprise Cloud** (multi-tenant, minutes to provision) or **Customer Dedicated** (single-tenant VPC, AWS Private Link / IPSec to private repos) |

**Managed Devins (2025+):** A coordinator Devin decomposes large work, spawns **parallel child Devins** (each full VM + session link), monitors ACU, resolves conflicts, compiles results. Pattern: map-reduce at the **session** layer — not subagents inside one context window.

**Automations:** Scheduled/recurring Devins, webhooks, Slack/GitHub/Linear triggers — engineering ops (dependency bumps, QA sweeps, release notes), not personal desktop chores.

### 2.2 Devin Desktop (formerly Windsurf)

| Date | Milestone |
|------|-----------|
| 2025 | Cognition acquires Windsurf (Codeium IDE lineage) |
| 2026-03-19 | Quota-based pricing replaces credits (Free / Pro $20 / Teams / Max $200) |
| 2026-05 | **SWE-1.6** GA — in-house model optimized for agent UX and speed (up to ~950 tok/s tier) |
| 2026-06-02 | **Windsurf → Devin Desktop** rebrand; **Devin Local** (Cascade agent in IDE) |

| Surface | Role | Human loop |
|---------|------|------------|
| **Devin Cloud** | Delegate full tasks; returns PRs | Review at checkpoints / PR |
| **Devin Desktop** | IDE agent (Cascade), tab completion, fast context | Developer in editor; agent proposes/applies |
| **DeepWiki / Ask Devin** | Indexed codebase Q&A, architecture docs | Research / planning |
| **Devin Review** | PR review, bug flags, GitHub-synced actions | Reviewer workflow |

**Pricing split (2026):** Consumer **Devin Desktop** uses daily/weekly quotas + API-priced overage. **Enterprise Devin Cloud** uses **ACUs** (separate commercial motion).

### 2.3 Cognition strategic thesis

- **Agent layer > model layer** — route tasks across frontier and SWE-1.x models per subtask category.
- **Independence** — Cognition raised at ~$10.2B valuation (2026 reports) while integrating with Windsurf/Devin Desktop without locking to one model vendor.
- **Windsurf acquisition** — bridges **interactive IDE** (high-frequency, human-present) and **autonomous cloud** (low-frequency, delegate-and-forget).

---

## 3. SWE Agent Category — Key Players

### 3.1 Comparison matrix

| Product | Host model | Open source | Primary ACI | Best for | vs Devin |
|---------|------------|-------------|-------------|----------|----------|
| **Devin Cloud** | Cognition SaaS | No | Devbox VM | Enterprise delegate-to-PR | — |
| **Devin Desktop** | Local IDE + cloud models | No | Editor + Cascade | Daily coding, fast SWE-1.6 | Human-in-loop sibling |
| **OpenHands** | Self-host or cloud | Yes (MIT) | Docker sandbox, web UI + VS Code | Teams needing on-prem / RBAC | Open alternative; multi-agent SDK |
| **SWE-agent** | Self-host | Yes (MIT) | Custom ACI (Princeton) | Research, minimal harness | Academic; Mini-SWE-Agent ~100 LOC |
| **Cursor Background Agent** | Cursor cloud VMs | No | Forked VS Code + cloud agent | Multi-file agentic edits in IDE | IDE-native; no PR factory brand |
| **Claude Code** | Anthropic | No | Terminal REPL agent | CLI-first power users | No hosted VM product |
| **Jules** | Google Labs | No | Proactive codebase analysis | Insight/diagnostics before fixes | Proactivity benchmark, not patch factory |
| **Cline / Aider** | Local + API keys | Yes | VS Code / CLI pair programmer | Lightweight agent loops | Smaller scope than Devin Cloud |
| **Sweep** | SaaS | Partial | GitHub issue → PR | Narrow issue automation | Single-purpose bot |

### 3.2 OpenHands (open-source anchor)

- **Formerly OpenDevin** — composable **Software Agent SDK** (V1 architecture, event-sourced).
- **Deployment:** Self-hosted Docker sandboxes; optional hosted; **RBAC, audit trails** for enterprise.
- **Capabilities:** Multi-agent delegation, browser, shell, code execution; **OpenHands Index** tracks benchmark scores across models.
- **Reported SWE-bench Verified:** ~68–72% with strong scaffolds (Claude Sonnet 4.x + extended thinking); V1 SDK preserves capability while cutting system failures ~61% vs V0 in production comparison (OpenHands paper, 2025).

### 3.3 SWE-agent (research anchor)

- **Agent-Computer Interface** design — structured editor/shell feedback loop (influenced later agents).
- **Mini-SWE-Agent** — minimal ~100-line harness reporting **>74%** on SWE-bench Verified in some configs — proves **scaffolding** can dominate model choice on curated sets.
- **EnIGMA mode** — security/CTF-oriented variant.

### 3.4 IDE background agents (Cursor, etc.)

- **Pattern:** Cloud VM per task; clone repo; agent edits + runs tests; user reviews diff in IDE.
- **Difference from Devin Cloud:** Tighter **editor UX**, less **IT integrations** (Jira fleet, managed Devins, enterprise VPC). Same **column B** sandbox semantics.

### 3.5 Jules (Google) — proactivity axis

Google's **Jules** research stresses **insight policy**: agents that surface *what matters* (goals, clusters of related bugs) before or instead of blindly patching. **Hit@5** diagnostic accuracy improved from ~33% to ~57% when exploration budget increased (internal Google study, 2025). Positions against pure **SWE-bench patch** culture.

---

## 4. Benchmarks & Honest Performance

| Benchmark | What it measures | Landscape note |
|-----------|------------------|----------------|
| **SWE-bench Verified** | Curated GitHub issues → patch | Leaderboard **70%+** with strong agents + models; risk of **train-set leakage** |
| **SWE-bench Lite** | Smaller subset | Legacy comparisons; still cited in blog posts |
| **SWE-bench Pro** | Harder multi-file tasks | Wider gap between agents |
| **SWE-bench-Live** | Novel, unseen issues | **~18–20%** for top open agents — closer to production surprise |
| **OSWorld** | Full OS GUI tasks | Devin/Operator territory; SWE agents rarely optimize for this |

**Takeaway for Orynn:** SWE-bench leadership does **not** translate to **Windows UIA reliability**. Conversely, Orynn's desktop ladder does **not** substitute for **CI-green patch generation** on a monorepo.

---

## 5. Technical Architecture — Shared SWE Patterns

### 5.1 Typical agent loop (column B)

1. **Ingest goal** — issue text, Slack thread, natural language.
2. **Context** — clone repo, Knowledge/RAG, rules files (`AGENTS.md`, `.cursorrules`).
3. **Plan** — file list, test strategy, subtask breakdown.
4. **ReAct loop** — shell / editor / browser → observe output → iterate.
5. **Verify** — unit tests, linters, self-review.
6. **Deliver** — PR, comment, or session artifact.
7. **Sleep/resume** — Devin sessions persist; ACU meters idle floor.

### 5.2 Devin-specific: Brain + Devbox

```
User / Slack / GitHub / Linear
              │
              ▼
     ┌─────────────────┐
     │  Brain (cloud)   │  stateless planning + model routing
     └────────┬────────┘
              │ orchestrates
              ▼
     ┌─────────────────┐
     │  Devbox (VM)     │  shell · IDE · browser · git
     │  per session     │  isolated; Customer Dedicated option
     └────────┬────────┘
              ▼
        PR / report / Ask answer
```

**Managed Devins:** Coordinator Brain spawns N Devboxes; children report trajectories upstream for conflict merge and future decomposition learning.

### 5.3 Integrations (engineering stack)

GitHub, GitLab, Bitbucket, Azure DevOps, Slack, Teams, Jira, Linear, **MCP**, webhooks, schedules. This is **SDLC plumbing**, not Windows **Settings** or **Outlook Win32** automation.

---

## 6. Strengths & Failure Modes

### 6.1 What Devin / SWE agents do well

- **End-to-end issue resolution** when repo, tests, and CI are agent-accessible.
- **Parallel bulk work** — migrations, codemods, dependency waves (Managed Devins).
- **24/7 unattended engineering** — schedules, automations, cloud sessions after logout.
- **Enterprise compliance paths** — dedicated VPC, private repo access without IP whitelist gymnastics.
- **Developer UX convergence** — Devin Desktop unifies tab, chat agent, and SWE-1.6 speed tier.

### 6.2 Documented weaknesses

- **Novel production bugs** — SWE-bench-Live gap (~80% failure).
- **Context rot in monolithic sessions** — motivation for Managed Devins (split VMs).
- **Not your PC** — cannot click the user's local Excel, approve a UAC prompt on their machine, or drive **non-git** personal workflows.
- **Cost opacity at scale** — ACU consumption on large refactors; enterprise procurement friction.
- **Human review still mandatory** — security, architecture, product judgment; "autonomous" means **autonomous attempt**, not **autonomous merge**.
- **Linux Devbox default** — Windows-specific desktop app testing requires extra harnessing.

---

## 7. Comparison to Orynn

### 7.1 Architecture contrast

```
DEVIN / SWE AGENT (column B)              ORYNN (column A)
────────────────────────────              ─────────────────
Goal: fix ticket / ship feature           Goal: operate my Windows session
Sandbox: Linux Devbox / IDE VM            Surface: user's real Win32/desktop
ACI: shell + git + browser in VM          Control: UIA → keyboard → OCR → grid
Input: Slack, web UI, IDE chat            Input: voice-first Gemini Live
Output: PR, CI, code review               Output: app state changed, spoken ok
Metering: ACUs / IDE quotas               Cost: user API keys + local free tiers
```

### 7.2 Feature matrix

| Dimension | Devin Cloud / SWE agents | Orynn |
|-----------|--------------------------|-------|
| **Primary user** | Engineering org / developer | Individual Windows power user |
| **Runs on user's PC** | No (VM) unless custom fork | **Yes** — local agent + overlay |
| **Voice-first** | No (chat/IDE) | **Core** — Gemini Live front desk |
| **Native Win32 apps** | Not design target | **Core** — UIA by control name |
| **Repo → PR pipeline** | **Core strength** | Secondary (`run_terminal`, git tools) |
| **Parallel agent fleet** | **Managed Devins** | Subagent storm / task bridge (local) |
| **Benchmark narrative** | SWE-bench | Desktop task success, honest `ok` |
| **Enterprise VPC** | **Customer Dedicated** | Local-only; no Cognition tenancy |
| **Browser SaaS** | In Devbox browser | Connectors; Playwright over pixel loop |
| **Settings / shell URIs** | N/A in Devbox | `ms-settings:`, AUMID launch layer |

### 7.3 Where Devin/SWE wins

- **Autonomous multi-hour coding tasks** with test verification and PR output.
- **Engineering org scale** — fleet of agents, Jira/Linear/GitHub native loops.
- **Codebase intelligence** — DeepWiki, Devin Review, indexed Q&A at repo scale.
- **Proof points on SWE-bench** for procurement ("AI engineer" RFP responses).

### 7.4 Where Orynn wins

- **"On my machine, right now"** — install software, change Windows settings, drive apps the user already has open.
- **Voice while hands-busy** — not filing a ticket for the coding agent.
- **UIA economics** — no screenshot token loop for routine button clicks.
- **Personal automation** — workflows unrelated to git (media, games, Office, system config).
- **Offline/local privacy** — no Devbox exfiltration path for personal screen content.

### 7.5 Overlap zone

- **Terminal automation** — both can run shell commands; Orynn gates destructive ops with spoken consent.
- **Browser tasks** — Devin Devbox browser vs Orynn Playwright/CDP; Orynn master strategy prefers DOM when available.
- **Agent orchestration metaphor** — Managed Devins parallel Orynn's **front desk vs back office** and subagent patterns, but on **engineering sandboxes**, not **live desktop**.

---

## 8. Strategic Implications for Orynn

1. **Do not chase SWE-bench** — wrong category; investors comparing Orynn to Devin on patch % are mixing columns A and B. Position on **OSWorld-class gaps** Devin does not address (user's Windows session).

2. **Complementary, not replacement** — A developer may use **Devin Desktop** in VS Code and **Orynn** for everything outside the repo: "mute Teams," "open DaVinci," "run this script on my D: drive."

3. **Borrow orchestration ideas** — Managed Devins' **clean VM per subtask** mirrors Orynn's **escalate to back-office agent** instead of stuffing Live context; trajectory read-back informs decomposition.

4. **MCP convergence** — Devin supports MCP; Orynn connectors should assume engineering tools may already be MCP-native in Devin shops — interoperability is a feature, not threat.

5. **Watch Devin Desktop on Windows** — Rebrand unifies Cognition's IDE agent under Devin brand; still **column B**, but increases mindshare for "Devin" as *any* agentic coding — clarify Orynn is **the Windows operator**, not a slower Devin.

6. **Honest capability boundaries** — SWE agents over-promise "autonomous engineer"; Orynn's **`ok` must match speech** is differentiated trust model. Market **local control** vs **cloud PR bots**.

---

## 9. Primary Sources

| Source | URL |
|--------|-----|
| Devin can now Manage Devins | https://cognition.ai/blog/devin-can-now-manage-devins |
| Enterprise Deployment (Brain + Devbox) | https://docs.devin.ai/enterprise/deployment/overview |
| Introducing SWE-1.6 | https://cognition.com/blog/swe-1-6 |
| Windsurf / Devin pricing plans (Mar 2026) | https://devin.ai/blog/windsurf-pricing-plans |
| Cascade models (SWE family) | https://docs.devin.ai/windsurf/plugins/cascade/models |
| OpenHands Software Agent SDK (arXiv) | https://arxiv.org/html/2511.03690 |
| Jules — Measuring What Matters | https://developers.googleblog.com/measuring-what-matters-with-jules/ |
| Agent Patterns Catalog — Devin | https://www.agentpatternscatalog.org/compositions/devin/ |
| SWE-bench (original) | https://www.swebench.com |

---

*This document is part of the subagent-storm competitor series. For Orynn's own automation strategy, see [00-master-strategy.md](../../windows-automation-research/00-master-strategy.md).*

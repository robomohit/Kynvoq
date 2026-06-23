# Microsoft Power Automate Desktop (PAD) vs Orynn

**Date:** 2026-06-22  
**Scope:** Competitive analysis — enterprise RPA / desktop automation vs voice-native AI agent  
**Audience:** Product, engineering, positioning  
**Related:** [00-master-strategy.md §7.3](../../windows-automation-research/00-master-strategy.md#73-microsoft-power-automate--enterprise-rpa) · [01-uia-deep-dive.md](../../windows-automation-research/01-uia-deep-dive.md)

---

## Executive Summary

**Power Automate for desktop (PAD)** is Microsoft's mature RPA product: visual flow authoring, recorded UI selectors, attended/unattended bots, 400+ cloud connectors, and deep Power Platform / Copilot Studio integration. It optimizes for **deterministic, auditable, enterprise-scale automation** built by makers and IT.

**Orynn** is a **voice-native AI agent** that drives Windows through **UI Automation by control name**, with LLM planning for novel tasks and saved workflows for repeat procedures. It optimizes for **ad-hoc, spoken goals** on a personal machine — fast on free models, local-first, no flow designer required.

Both products share the same **UIA foundation** for desktop control. The divergence is **authoring model** (recorded selectors vs LLM + lazy playbooks), **interaction surface** (designer + triggers vs floating capsule + voice), and **buyer** (enterprise IT / citizen developer vs individual power user).

---

## Product Snapshots

### Microsoft Power Automate Desktop (PAD)

| Dimension | Detail |
|-----------|--------|
| **Vendor** | Microsoft (Power Platform) |
| **Category** | Enterprise RPA + low-code cloud automation |
| **Desktop component** | Power Automate for desktop — desktop flows |
| **UI control** | UI element picker: **UIA** (default), **UIA3 Raw**, **MSAA**; web elements via browser automation module |
| **Authoring** | Visual action designer, recorder, subflows, version control, flowchart view (2026 wave) |
| **Orchestration** | Cloud flows trigger desktop flows; Copilot Studio can call desktop flows for precise step execution |
| **Deployment** | Attended (user workstation, Premium license) or unattended (Process/Hosted bot on VM) |
| **Pricing (2026)** | Premium ~$15/user/mo (attended RPA); Process ~$150/bot/mo (unattended); Hosted Process ~$215/bot/mo (Azure VM) |
| **2026 additions** | UIA3 Raw capture, dynamic UI/web control variables, Invoke LLM (Ollama-compatible), UI Access for elevated apps, AI-assisted authoring |

PAD explicitly avoids image recognition and absolute coordinates for most UI actions — it captures **selectors** (automation properties) and replays them deterministically.

### Orynn

| Dimension | Detail |
|-----------|--------|
| **Vendor** | Open source (robomohit/Orynn) |
| **Category** | Local AI agent — coding, browser, and native desktop control |
| **Desktop component** | UIA-first tools in `tools.py` / `desktop_features.py`; back-office agent + Gemini Live front desk |
| **UI control** | Find by **Name** / **AutomationId**; InvokePattern, ValuePattern; resolver ladder (keyboard → Electron unlock → OCR → grid-locate) |
| **Authoring** | Natural language goals; `save_workflow` for repeat procedures; `adaptive_windows_profiles.json` for learned resolvers |
| **Orchestration** | Voice (Gemini Live) → one tool per turn; multi-step via `start_desktop_task` or saved `run_workflow` |
| **Deployment** | Single-user local install (Windows 10/11); optional API/dashboard on localhost |
| **Pricing** | Free-tier LLM routing (Groq / OpenRouter `:free`); user pays own API keys; no per-bot license |

---

## Shared Foundation: UI Automation

PAD and Orynn both treat **UI Automation as the primary desktop control plane** — not pixel coordinates.

| Capability | PAD | Orynn |
|------------|-----|-------|
| UIA control tree | Yes — default picker mode | Yes — `uia_find`, `uia_click`, `uia_type` |
| UIA3 Raw (full tree) | Yes (build 2605+) | Uses standard UIA client; no separate Raw mode exposed |
| MSAA legacy apps | Yes — picker mode | Not first-class; UIA covers most Win32/WPF |
| Web automation | Dedicated browser module + web selectors | Browser mode + connector templates driving Chrome |
| Selector stability | Stored UI element objects with property bags | Runtime Name/AutomationId match; workflows store target **names** not coordinates |
| Image/coordinate fallback | Available but de-emphasized in docs | OCR then `grid_locate` — agent-only; Live path forbids pixel fallback |

**Implication:** Orynn is not competing on "better UIA" — it competes on **what wraps UIA**: probabilistic planning + voice vs deterministic replay + enterprise ops.

---

## Architecture Comparison

```
PAD (enterprise RPA)                    Orynn (voice-native agent)
─────────────────────                   ──────────────────────────

Trigger (schedule, email,              User speaks (Gemini Live)
 button, cloud flow, Copilot)                    │
        │                                        ▼
        ▼                               Front desk: one tool / turn
 Cloud flow orchestration              (desktop_control, run_workflow, …)
        │                                        │
        ▼                               miss / multi-step?
 Desktop flow (recorded actions)                 ▼
        │                               Back-office agent
        ├─ UI element selectors                 │
        ├─ Variables / loops                    ├─ Launch layer (URI/AUMID/shell)
        ├─ Subflows                             ├─ Navigate (focus, tabs, menus)
        └─ Connectors (API)                     └─ Act (UIA → ladder fallbacks)
        │                                        │
        ▼                                        ▼
 Attended or unattended bot              Local capsule + optional dashboard
 on registered machine / VM
```

---

## Feature Matrix

| Dimension | PAD | Orynn | Notes |
|-----------|:---:|:-----:|-------|
| **Visual flow designer** | ✓ | ✗ | Orynn uses NL + saved JSON workflows |
| **Recorder / capture UI elements** | ✓ | ✗ | Orynn learns via agent runs + `save_workflow` |
| **Natural language tasking** | Partial (Copilot authoring assist) | ✓ Core | Live is voice-first |
| **Deterministic replay** | ✓ | Partial | Workflows are deterministic; ad-hoc agent is not |
| **Unattended / scheduled runs** | ✓ | ✗ | Orynn is attended, single-user |
| **Cloud API connectors (400+)** | ✓ | Growing | Orynn `connectors.py` — browser templates + free APIs |
| **Process mining** | ✓ | ✗ | Enterprise analytics |
| **Version control / diff** | ✓ (2605+) | Git for code; workflows in JSON | |
| **Multi-machine deployment** | ✓ | ✗ | |
| **Credential vault (central)** | ✓ | Local `.env` + connector link state | |
| **UIA-first desktop control** | ✓ | ✓ | Shared moat vs vision agents |
| **Works with window occluded** | Varies by action | ✓ | Orynn demo: Calculator under another window |
| **Vision / pixel fallback** | Secondary | Tertiary (agent only) | Orynn deliberately deprioritizes |
| **Voice interaction** | ✗ | ✓ | Wake word, push-to-talk, Gemini Live |
| **Free to run (personal use)** | Trial / paid | ✓ | API keys only |
| **Open source** | ✗ | ✓ | PolyForm NC license |
| **Coding + browser + desktop** | Desktop + cloud focus | All three modes | |
| **LLM in loop (2026)** | Invoke LLM action (Ollama) | Core architecture | PAD adds LLM as a **step**; Orynn **is** the LLM loop |
| **Self-healing on UI change** | Roadmap (2026 wave: "self-healing") | LLM re-plan + adaptive profiles | Different mechanisms |

---

## Authoring & Maintenance

### PAD: Record → Replay

1. Maker opens PAD designer, adds UI automation action.
2. **UI element picker** captures selector (UIA properties, optional UIA3 Raw / MSAA).
3. Flow stores element repository; actions reference selectors.
4. **Breakage:** UI redesign changes selectors → flow fails until maker re-captures or updates.
5. **Mitigation (2026):** AI-assisted authoring, self-healing roadmap, dynamic `Get UI control` variables.

**Strength:** Once captured, runs are fast, predictable, and auditable — ideal for finance, HR, and IT ops with stable apps.

### Orynn: Plan → Verify → Optionally Save

1. User states goal in voice or text.
2. Agent observes UIA tree, plans steps, executes via named controls.
3. On repeat intent, user teaches via `save_workflow` — steps use **target names**, not pixels.
4. **Breakage:** Control rename or layout change may break workflow steps; agent can re-reason for one-off tasks.
5. **Mitigation:** `adaptive_windows_profiles.json` records resolver paths per app; connector templates for known surfaces.

**Strength:** Zero upfront authoring for novel tasks; no designer learning curve.  
**Weakness:** Ad-hoc runs are probabilistic — mitigated by workflows for known procedures.

---

## Triggers & Interaction Model

| Trigger type | PAD | Orynn |
|--------------|-----|-------|
| Schedule / cron | ✓ | ✗ |
| Email / SharePoint / Teams event | ✓ (cloud) | ✗ |
| Manual button / hotkey in PAD | ✓ | Capsule `Ctrl+Shift+Space` |
| Voice utterance | ✗ | ✓ Primary |
| Saved workflow keyword | ✗ | ✓ `run_workflow` trigger matching |
| Copilot / cloud flow callback | ✓ | ✗ |
| API / webhook | ✓ (cloud flows) | Local REST API (dashboard) |

PAD fits **"when X happens, run Y"** automation. Orynn fits **"I want Y now"** interaction.

---

## Connectors vs Workflows (Strategic Parallel)

Master strategy already maps PAD's split to Orynn:

| PAD concept | Orynn equivalent | Code |
|-------------|------------------|------|
| Cloud connector (API) | Connector template + browser/API call | `connectors.py`, `tools.py` |
| Desktop flow (UI steps) | 3-layer stack: launch → navigate → act | `tools.py`, `adaptive_windows.py` |
| Repeat run | Saved workflow | `workflows.py`, `run_workflow` |

**Lesson:** Prefer API/connector when a certified integration exists; use UIA stack for legacy/desktop-only surfaces; persist repeats as workflows — not re-planning every time.

Orynn's connector registry (~dozen browser surfaces + free APIs) is orders of magnitude smaller than Power Platform's catalog but sufficient for personal automation; enterprise breadth is a PAD moat.

---

## Reliability & Operations

| Concern | PAD | Orynn |
|---------|-----|-------|
| **Run logs / telemetry** | Power Platform admin center, run history | Local task JSON, action ticker in capsule |
| **Failure handling** | Try/catch blocks, retry policies, subflow error branches | Agent re-plan; `FailureClass` in adaptive_windows |
| **Concurrency** | One unattended bot = one run at a time per machine | Single task gate (`_desktop_busy`) |
| **Elevated apps** | UI Access mode (2026 GA) for admin apps unattended | Standard user context; no UI Access equivalent |
| **Compliance / DLP** | Power Platform governance, environments | User-controlled local scopes + approval gates |
| **Audit trail** | Enterprise-grade | Local logs; not enterprise audit-ready |

PAD wins decisively on **unattended scale, governance, and ops**. Orynn wins on **low-friction personal use** and **honest spoken outcomes** (Live must match `ok` field).

---

## Cost & Buyer Persona

| Persona | Better fit |
|---------|------------|
| IT automating invoice processing across 50 VMs | **PAD** (Process/Hosted licenses) |
| Finance team recording SAP → Excel flows with change control | **PAD** |
| Developer wanting voice-driven "open Notepad and …" on one PC | **Orynn** |
| Individual avoiding $15/mo/seat for ad-hoc desktop help | **Orynn** |
| Org already on M365 needing Teams/SharePoint triggers | **PAD** |
| Open-source / inspectable automation enthusiast | **Orynn** |

---

## Positioning on the Spectrum

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
                         │              Vision agents         │
                         │              (Anthropic, Operator) │
                         ▼                                    ▼
                    Vision / pixels
```

PAD sits **deterministic + semantic (UIA/API)**. Orynn spans **workflows (near-PAD repeatability)** through **agent (probabilistic)** while staying **UIA-first** — avoiding the vision-primary quadrant unless UIA genuinely fails.

---

## Where PAD Wins

1. **Enterprise RPA at scale** — unattended bots, hosted VMs, machine registration.
2. **Connector catalog** — hundreds of certified API integrations vs Orynn's growing registry.
3. **Governance** — environments, DLP, centralized credentials, run analytics.
4. **Deterministic SLA** — recorded flows don't hallucinate steps.
5. **Process mining & task mining** — discover automation candidates from user behavior.
6. **Copilot Studio bridge** — cloud agents delegate precise desktop execution to PAD.
7. **Mature selector tooling** — UIA3 Raw, MSAA, element inspector, side-by-side version diff.

---

## Where Orynn Wins

1. **Voice-native UX** — hands-busy, eyes-busy scenarios; no flow designer.
2. **Novel task without authoring** — "do this once" without recording selectors first.
3. **Cost for individuals** — free-tier LLMs; no per-bot licensing.
4. **UIA efficiency** — text-tree steps vs screenshot agents; occluded-window operation.
5. **Local control & transparency** — open source, permission scopes, approval gates on destructive actions.
6. **Unified agent** — same stack for coding, browser, and desktop (PAD is automation-focused, not a coding agent).
7. **Provider agility** — OpenRouter, Groq, Gemini Live, Ollama — not locked to Microsoft AI stack.

---

## Risks & Overlap (2026)

Microsoft is **adding LLM steps to PAD** (Invoke LLM, Copilot-assisted authoring, self-healing selectors) and **calling desktop flows from Copilot Studio**. That narrows the gap on "intelligent automation" while keeping enterprise deployment.

Orynn should **not** try to replicate PAD's unattended fleet ops in the near term. Instead:

- Double down on **voice front desk + UIA-first** (latency, cost, reliability vs vision agents).
- Expand **connectors** and **launch registry** where API beats UI (PAD lesson).
- Harden **workflows** as the deterministic tier — Orynn's answer to recorded PAD flows.
- Use **adaptive profiles** as lightweight self-healing without enterprise process mining.

---

## When to Recommend Which

| Scenario | Recommendation |
|----------|----------------|
| Nightly batch export from legacy Win32 app on server | PAD unattended |
| "Hey, turn on Bluetooth and open Spotify" while cooking | Orynn voice |
| Compliance-audited AP automation | PAD + cloud flow |
| Personal repeatable "morning setup" | Orynn `save_workflow` |
| Integrate with Dynamics / Dataverse | PAD |
| Open-source desktop agent benchmark / hackable stack | Orynn |

---

## Sources

| Topic | Reference |
|-------|-----------|
| Orynn master strategy (§7.3) | [00-master-strategy.md](../../windows-automation-research/00-master-strategy.md) |
| Orynn UIA implementation | [01-uia-deep-dive.md](../../windows-automation-research/01-uia-deep-dive.md) |
| Orynn workflows | `app/workflows.py` |
| Orynn connectors | `app/connectors.py` |
| PAD UI elements | [Automate using UI elements](https://learn.microsoft.com/en-us/power-automate/desktop-flows/ui-elements) |
| PAD 2605 release (UIA3 Raw, version diff) | [Build 2605 release notes](https://learn.microsoft.com/en-us/power-platform/released-versions/power-automate-desktop/2605) |
| PAD 2606 release (Invoke LLM, dynamic controls) | [Build 2606 release notes](https://learn.microsoft.com/en-us/power-platform/released-versions/power-automate-desktop/2606) |
| UI Access for elevated apps | [2026 wave 1 — UI Access](https://learn.microsoft.com/en-us/power-platform/release-plan/2026wave1/power-automate/automate-administrator-level-desktop-applications-unattended-runs) |
| Power Automate 2026 roadmap | [2026 release wave 1 overview](https://learn.microsoft.com/en-us/power-platform/release-plan/2026wave1/power-automate/) |
| Pricing | [Power Automate pricing](https://www.microsoft.com/en-us/power-platform/products/power-automate/pricing) |
| Licensing types | [Types of Power Automate licenses](https://learn.microsoft.com/en-us/power-platform/admin/power-automate-licensing/types) |

---

*Read-only research doc for subagent-storm competitor sweep. No code changes.*

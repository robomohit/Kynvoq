# Synthesis: Subagents (Cursor / Antigravity) vs Orynn Front Desk + Back Office

**Date:** 2026-06-22  
**Sources:** [Cursor Subagents](https://cursor.com/docs/subagents), [Antigravity Subagents](https://antigravity.google/docs/subagents)  
**Related:** [`INDEX.md`](INDEX.md), [`reliability/02-double-routing-live.md`](reliability/02-double-routing-live.md), [`backoffice/07-gemini-live-tool-contracts.md`](backoffice/07-gemini-live-tool-contracts.md)

---

## TL;DR

**Yes — Gemini Live + back-office desktop agent is the same architectural pattern as subagents.**

- **Parent / coordinator** = Gemini Live (voice, companion bubble, delegation)
- **Workers** = `start_desktop_task` → `agent.py` ReAct loop, UIA tools, task lifecycle
- **Fast specialists** = Live tools like `desktop_control`, `look_at_screen`, `list_windows` — closer to **built-in subagents** than to the full back office

What Orynn lacks vs Cursor/Antigravity is not the idea — it's the **platform guarantees**: context isolation, sanitized handoffs, formal lifecycle, and **pre-packaged specialists** (browser, research, etc.) that the parent can invoke without re-explaining the domain every time.

---

## What Cursor calls subagents

From [cursor.com/docs/subagents](https://cursor.com/docs/subagents):

| Concept | Behavior |
|---------|----------|
| **Purpose** | Break complex work into parallel, isolated workers; parent keeps a clean context |
| **Context** | Each subagent starts with a **clean context window**; parent passes needed info in the spawn prompt |
| **Modes** | **Foreground** (block until done) vs **Background** (return immediately, worker continues) |
| **Handoff** | Worker runs autonomously → returns **final message / summary** to parent |
| **Resume** | Agent ID preserved; parent can resume idle workers with full prior context |
| **Nesting** | Subagents can spawn child subagents (with depth limits) |
| **Custom workers** | `.cursor/agents/*.md` — YAML frontmatter (`name`, `description`, `model`, `readonly`, `is_background`) + specialist prompt |

**When to use (Cursor):** long research, parallel workstreams, multi-step specialization, independent verification — not single-shot chores (those are **skills**).

---

## What Antigravity calls subagents

From [antigravity.google/docs/subagents](https://antigravity.google/docs/subagents):

| Concept | Behavior |
|---------|----------|
| **Invocation** | `invoke_subagent` — concurrent session with role + initial prompt |
| **Isolation** | Clean context (no parent history); optional **Git worktree** workspace |
| **Lifecycle** | **Running** → **Idle** (results sent to parent) → **Killed** (permanent) |
| **Re-awaken** | Idle agents resume on message from any agent (not only parent) |
| **Communication** | Inter-agent messaging by agent ID; shared transcript visibility |
| **Nesting** | Up to **10 levels** of delegation |
| **Permissions** | Inherit parent's terminal/file scopes; confirmation bubbles up to UI |

Antigravity's pitch matches Cursor's background mode almost exactly: *"Delegate so the parent can continue in parallel and context isn't polluted by worker noise."*

---

## Built-in specialists — the part that matters

Both platforms ship **pre-trained, pre-configured subagents** the parent invokes by name instead of improvising a generic worker every time.

### Cursor built-ins

| Subagent | Purpose | Why it's separate |
|----------|---------|-------------------|
| **Explore** | Codebase search & analysis | Noisy intermediate output; uses faster model; many parallel searches |
| **Bash** | Shell command series | Verbose logs isolated from parent |
| **Browser** | MCP browser control | DOM snapshots/screenshots filtered to relevant results |

Cursor also documents patterns like **Verifier** (skeptical completion check) and **Orchestrator** (planner → implementer → verifier chain).

### Antigravity built-ins

| Subagent | Purpose | Notes |
|----------|---------|-------|
| **research** | Codebase research & navigation | Optimized for exploration |
| **browser** | Sandboxed web interaction | Invoked via `/browser`; domain-tuned |
| **self** | Clone of parent (same prompt + tools) | Parallel copy of coordinator |

Custom subagents via `define_subagent`: dynamic system prompt + toolset (read-only, write, delegate).

### Why built-ins exist (shared lesson)

From Cursor's docs, built-in subagents share traits:

1. **Noisy intermediate output** — stays in the worker, not the user-facing channel  
2. **Specialized prompts & tools** — tuned for one domain, not general chat  
3. **Model flexibility** — e.g. fast cheap model for explore, strong model for reasoning  
4. **Automatic delegation** — parent picks the right specialist from **description**, not re-negotiation each turn  

**Browser is the clearest example:** it isn't "main agent + browse the web in the same context." It's a worker that already knows DOM interaction, screenshot filtering, sandbox boundaries, and when to return a summary — so the parent never learns those details mid-conversation.

---

## Orynn mapping

### Core orchestration

| Platform pattern | Orynn equivalent | File / API |
|------------------|------------------|------------|
| Parent agent (user-facing) | **Gemini Live** | `app/widget/gemini_live.py` |
| Generic long-running worker | **Desktop agent task** | `POST /api/tasks` → `agent.py` |
| Fast single-shot worker | **`desktop_control`** | `textbox_overlay._desktop_control_route` |
| Delegation tools | Live function declarations | `start_desktop_task`, `desktop_control`, `look_at_screen`, … |
| Background async | Task runs while Live listens | `_await_task_outcome`, SSE / poll |
| Worker ID | Task ID (`clicky-*`) | `tasks/*.json` |
| Result to parent | `reason`, status, `send_task_update` | `textbox_overlay.py`, `gemini_live.py` |

### Built-in specialists Orynn already has (partial)

Orynn doesn't call them "subagents," but Live already exposes **domain-specialized tools** the model should route to — analogous to Cursor's explore/bash/browser:

| Orynn "specialist" | Role | Cursor/Antigravity analog |
|--------------------|------|---------------------------|
| **`desktop_control`** | One click/type/scroll in foreground app | Narrow tool subagent (not full agent loop) |
| **`look_at_screen`** | Read-only screen peek for user Q&A | Vision specialist (filtered snapshot → answer) |
| **`list_windows` + `capture_window`** | Targeted window frame without full desktop | Browser-like "inspect this surface" worker |
| **`start_desktop_task`** | Full ReAct + UIA ladder for multi-step GUI | Generic back-office subagent |
| **`run_workflow`** | Named repeat playbook | Custom subagent with frozen prompt |
| **`web_search`** (back office / Live) | Web lookup | Partial browser/research analog (weak today — ~75% fail in Live logs) |
| **Launch fast-path** (`detect_app_launch_intent`) | Deterministic `open notepad` etc. | Ultra-narrow built-in (7 apps vs Cursor's richer auto-delegation) |

### Built-in specialists Orynn is missing

| Gap | What Cursor/Antigravity have | Orynn today |
|-----|------------------------------|-------------|
| **Browser worker** | Sandboxed, DOM-aware, taught for web tasks | `browser_*` tools exist in **back-office** `agent.py` headless mode, **not** exposed as a Live built-in with its own contract |
| **Research worker** | Codebase exploration without polluting parent | No Live `research_codebase` specialist; file reads go through generic task or terminal |
| **Verifier worker** | Independent "did it actually work?" pass | No post-task verification subagent; trust `reason` field (often `"Done."` or JSON leak) |
| **Explore-at-scale** | Parallel search subagents | Single-threaded task queue (`_desktop_busy`) |
| **Named custom profiles** | `.cursor/agents/*.md` / `define_subagent` | Modes (`auto`, `computer`) but not declarative specialist files Live reads for routing |

---

## Where Orynn matches vs diverges

### Matches (you're building the right thing)

- Parent stays conversational; worker does heavy, noisy steps  
- Async delegation — user can keep talking while back office runs  
- Tool specialization — different tools for peek vs click vs full task  
- Storm itself was a subagent fleet: coordinator + 50 isolated read-only workers  

### Diverges (where Spotify-style bugs come from)

| Platform guarantee | Orynn gap |
|--------------------|-----------|
| Parent only sees **final summary** | Raw `Failed: Server restarted…` leaked to bubble via `live_tool` |
| Clean worker context | Task abandon race returns terminal state before worker registers |
| One delegation path per intent | Double routing: `desktop_control` + `start_desktop_task` same turn |
| Specialist **description** drives routing | Prompt rules exist but model still picks wrong tool |
| Worker doesn't talk to user while parent narrates success | Live speaks "Opening Spotify…" while worker already failed |
| Resume idle worker by ID | Task retry is ad hoc ("yeah sure") not structured re-awaken |

---

## Recommendation: Orynn "built-in subagents" model

Treat Live tools + back-office modes as a **declarative specialist registry** — same spirit as `.cursor/agents/` and Antigravity's built-ins.

### Proposed built-ins (docs target — no code in this file)

| Name | Invoked when | Worker | Returns to Live |
|------|--------------|--------|---------------|
| **`launch`** | "open Spotify", "launch X" | Fast-path registry or short task | `"Opened X."` or honest failure |
| **`uia_act`** | "click Save", single gesture | `desktop_control` only | One-line outcome |
| **`vision_peek`** | "what's on my screen", "read this error" | `look_at_screen` / `capture_window` | Natural-language description only |
| **`browser`** | "fill this form", "read this page" | Headless browser agent (`browser_open` loop) | Summary + optional screenshot ref |
| **`research`** | "find where X is defined in my project" | Read-only codebase search sub-loop | File paths + snippets (no writes) |
| **`desktop_job`** | Multi-step GUI work | `start_desktop_task` full agent | Structured `{user_message, status, debug}` |
| **`verify`** | After `desktop_job` completes | Read-only check (window title, file exists, display value) | Pass/fail for Live to narrate |

Each entry would carry:

- **description** — when Live should delegate (mirrors Cursor frontmatter)  
- **tools allowed** — readonly vs write  
- **model / mode** — fast vs full reasoning  
- **is_background** — always async for `desktop_job`, sync for `uia_act`  
- **bubble policy** — never show raw worker errors; only `user_message`  

### Immediate wins (align with storm P0)

1. **Sanitized handoff** — workers return `{user_message, debug_reason}`; bubble and voice use only `user_message`  
2. **One specialist per turn** — enforce mutual exclusion (already started for desktop tools in `gemini_live.py`; extend to launch vs job)  
3. **Promote browser to Live built-in** — back-office browser prompt already exists in `agent.py`; expose as first-class Live delegate like Antigravity's `/browser`  
4. **Verifier after fast completes** — for `open *` and web search, 2s check (window foreground? non-empty search result?) before Live says success  
5. **Version-control specialists** — e.g. `Orynn/agents/launch.md`, `browser.md` loaded into Live system prompt as delegation catalog (Cursor pattern)  

---

## Comparison table

| Dimension | Cursor | Antigravity | Orynn |
|-----------|--------|-------------|-------|
| User-facing coordinator | Main Agent | Main agent | **Gemini Live** |
| Generic worker | Custom / Task subagent | `invoke_subagent` | **`start_desktop_task`** |
| Built-in specialists | explore, bash, browser | research, browser, self | **partial** — Live tools, not full profiles |
| Context isolation | Separate context window | Clean slate + optional worktree | Task goal/history; shared user session |
| Async default | Background mode available | Always async | Tasks async; some tools sync |
| Parallel workers | Yes (multiple Task calls) | Yes | **Gated** — one desktop task |
| Resume | Agent ID | Idle → Running on message | Task ID poll; weak retry story |
| Failure to parent | Error status + retry | Message + killed state | Poll/SSE; **leaks raw errors today** |
| Specialist config | `.cursor/agents/*.md` | `define_subagent` | Prompt rules in `gemini_live.py` only |
| Nesting | Limited tree | Up to 10 levels | Single back-office layer |

---

## Connection to the 50-subagent storm

The storm **was** a subagent architecture exercise on the meta level:

- **Coordinator** (this session) held user context and delegated 50 non-overlapping lanes  
- **Workers** produced one artifact each under `docs/subagent-storm/`  
- **Anti-collision rules** = isolation + no overlapping desktop/Live control  

Orynn's product gap is implementing **inside the app** what Cursor/Antigravity already productize: isolated workers, built-in domain specialists (especially **browser**), and summary-only handoffs to the voice front desk.

---

## Bottom line

When you say **front desk (Gemini Live) talking to us and calling back-office workers**, you mean **parent agent + subagents** — and the docs you linked describe exactly that pattern.

The upgrade path isn't "add subagents" (you already have them). It's:

1. **Name and specialize them** like Cursor's browser/explore and Antigravity's research/browser  
2. **Harden the contract** — summaries up, noise down, one delegate per intent  
3. **Promote browser (and research, verifier) to first-class built-ins** instead of burying them in the generic desktop agent loop  

See [`LOAD-TEST-PLAN.md`](LOAD-TEST-PLAN.md) for verifying Live ↔ worker honesty after deploy.

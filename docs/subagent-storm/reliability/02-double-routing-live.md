# Document: `02-double-routing-live.md`

```markdown
# 02 — Double routing in Gemini Live (`desktop_control` + `start_desktop_task`)

**Scope:** `debug-eec63b.log`, `gemini_live.py`, `textbox_overlay.py`  
**Reliability track:** R2 — tool routing / subagent storm  
**Status:** Partially mitigated (`desktop_used` batch gate + busy gate); model still emits dual-tool batches  
**Log:** `C:\Users\ACER\Desktop\Ai_computer\Ai_computer\debug-eec63b.log` (session `eec63b`, `runId: pre-fix`)

---

## Summary

“Double routing” means **one user intent triggers both** the fast Live primitive (`desktop_control`) **and** the back-office spawn (`start_desktop_task`). The log shows three distinct mechanisms:

| Mechanism | Layer | Intended? | Harm |
|-----------|-------|-----------|------|
| **Model dual-tool batch** | Gemini Live | No | Spawns agent + fast click; second tool may run or fail depending on order/gates |
| **Overlay escalation** | `textbox_overlay._desktop_control_route` | Yes (by design) | Looks like double routing in logs; one model call, two backends |
| **Reverse redirect** | `_parse_single_click_goal` in `_live_tool` | Yes (by design) | `start_desktop_task("Click X")` → fast UIA click path |

The reliability problem is **(1)**: the model still issues **22 same-turn batches** with both tools despite prompt, declarations, and batch gate — and at least one **live incident** (log line 731) where `start_desktop_task` ran and spawned work while `desktop_control` was attempted in the same turn.

---

## Log inventory (`debug-eec63b.log`)

| Metric | Count | Notes |
|--------|------:|-------|
| Total NDJSON lines | ~1,630 | Append-only; live + pytest interleaved |
| `_execute_tool:entry` → `start_desktop_task` | 150 | ~70% pytest harness (`tool: "x"` blocks nearby) |
| `_execute_tool:entry` → `desktop_control` | 34 | Includes live + tests |
| Model batches with **both** tools | **22** | `tools: ["desktop_control","start_desktop_task"]` or reversed |
| Busy gate blocks (hypothesis **F**) | 3 | `active_task: "write a poem in Notepad"` |
| `stop_current_task` after dual-route incident | 4+ | Recovery after line 731 cluster |

**Instrumentation hypotheses** (from `gemini_live._agent_debug_log`):

| ID | Location | Meaning |
|----|----------|---------|
| A | `_handle_message:tool_call` / `turn_complete` | Model message shape |
| D | `_handle_message:go_away` | Session reconnect |
| E | `_execute_tool:entry/exit/error` | Tool execution |
| F | `textbox_overlay._live_tool:busy` | Busy gate (3 live entries only; not in current overlay source) |

---

## Architecture: three routing layers

```
User speech
    │
    ▼
Gemini Live model ──tool_call batch──► gemini_live._handle_message
    │                                      │
    │                                      ├─ desktop_used gate (1 desktop tool / batch)
    │                                      └─ _execute_tool → on_tool callback
    ▼
textbox_overlay._live_tool_for_generation
    │
    ├─ name == "desktop_control" ──► _desktop_control_route
    │       ├─ fast UIA click/type (_live_desktop_control, fast_invoke_only=True)
    │       └─ on fail ──► _live_start_desktop_task  ◄── intentional escalation
    │
    └─ name == "start_desktop_task" ──► _parse_single_click_goal?
            └─ yes ──► _desktop_control_route  ◄── intentional redirect
            └─ no  ──► _live_start_desktop_task (POST /api/tasks)
```

### Layer 1 — Model (root cause of spurious doubles)

System prompt (`gemini_live._default_system_instruction`) and both function declarations explicitly forbid calling both tools for the same goal. The model **still** emits dual batches — likely “belt and suspenders” when uncertain about fast vs agent path.

### Layer 2 — `gemini_live` batch gate (mitigation)

```852:871:C:\Users\ACER\Desktop\Ai_computer\Orynn\app\widget\gemini_live.py
            _DESKTOP_TOOLS = frozenset({"desktop_control", "start_desktop_task"})
            desktop_used = False
            for call in calls:
                ...
                elif name in _DESKTOP_TOOLS and desktop_used:
                    result = {
                        "ok": False,
                        "message": (
                            "Only one desktop action per turn — pick desktop_control "
                            "OR start_desktop_task, not both. Wait for the result first."
                        ),
                    }
                else:
                    result = await self._execute_tool(name, args or {})
                    if name in _DESKTOP_TOOLS:
                        desktop_used = True
```

**Test:** `test_handle_message_rejects_second_desktop_tool_in_batch` — only first desktop tool executes.

**Log evidence gate works (post-fix tests):** e.g. lines 1586–1588 — batch `["desktop_control","start_desktop_task"]` → only `desktop_control` `_execute_tool` entries; no second-tool execute in same batch.

### Layer 3 — Overlay escalation / redirect (intentional “double”)

**Escalation** (`_desktop_control_route`, lines ~1761–1849): click/type tries UIA-only fast path; on failure escalates to `_live_start_desktop_task`. From the model’s perspective this is **one** `desktop_control` call; logs may show a long-running handler and later agent activity.

**Redirect** (`_live_tool`, lines ~2193–2202): `start_desktop_task` goals matching `Click "…" in App` are parsed and routed back through `_desktop_control_route`.

---

## Live session forensics

### Phase A — Poem task + busy gate (lines 1–4)

While `write a poem in Notepad` was active:

- `start_desktop_task` blocked (F)
- `desktop_control` blocked (F)
- `run_terminal` blocked (F)

Busy gate behaved correctly — no second desktop action interleaved with the running agent.

### Phase B — Desktop-only turns (lines 17–61)

After reconnect, the model used **`desktop_control` only** (open/type in Notepad): 5 successful `desktop_control` executions, **zero** `start_desktop_task`. This is the desired routing for in-app work.

### Phase C — Critical dual-batch incident (lines 726–775)

| Line | Event | Outcome |
|------|-------|---------|
| 726–728 | `desktop_control` (single-tool turn) | `ok: true` |
| **731** | Batch `["start_desktop_task","desktop_control"]` | **Both tools attempted** |
| 732–733 | `start_desktop_task` executes | `ok: true` (~6.7s) — **agent spawned** |
| 734–735 | `desktop_control` executes | `ok: false` (~16ms) — rejected (busy or batch second-slot) |
| 737–775 | `stop_current_task` ×3, then clean `start_desktop_task` | User/model recovery |

**Impact:** One utterance produced a full back-office task **and** a failed fast-path attempt. User had to stop tasks repeatedly. This is the primary live failure mode for double routing.

### Phase D — Repeated dual batches (22 total)

Most dual-batch lines (1144+, 1586+, etc.) are **interleaved with pytest** (`tool: "x"`). In clean batch samples (1586–1588, 1606–1608, 1626–1628):

- First tool in batch runs (`desktop_control`, fast, ~2–40ms)
- Second tool does **not** get a separate `_execute_tool:entry` in the same batch — batch gate holds

Remaining risk: **order matters when `start_desktop_task` is first** (line 731 pattern) — agent spawns before second tool is rejected.

---

## Failure modes (ranked)

### F1 — Model dual batch, `start_desktop_task` first (high)

Model calls `start_desktop_task` then `desktop_control`. First tool spawns agent; second fails fast but damage is done (duplicate intent, busy state, user confusion).

**Evidence:** Line 731.  
**Mitigation gap:** Batch gate allows whichever tool is **first**; does not collapse to a single routing decision.

### F2 — Model dual batch, `desktop_control` first (medium)

Fast path runs; second tool blocked by `desktop_used`. If fast path **escalates internally**, user gets agent anyway — but only one batch slot was consumed. Acceptable if escalation was needed; wasteful if fast path succeeded.

**Evidence:** Lines 1586–1588 (gate OK); escalation cases show ~6s gap inside single `desktop_control` handler when fast path fails.

### F3 — Prompt/declaration redundancy (medium, chronic)

Routing rules appear in system prompt + both tool descriptions. Historical analysis linked this to model “calling both to be safe.” Prompt was shortened but log (`pre-fix`) predates full verification.

### F4 — Observability gap (low, diagnostic)

No structured log when `_desktop_control_route` escalates or `_parse_single_click_goal` redirects. Hypothesis F only logged busy blocks. Hard to distinguish F1 from intentional escalation in raw `debug-eec63b.log`.

---

## What is NOT a bug

| Behavior | Why it’s OK |
|----------|-------------|
| `desktop_control` → failed UIA → `_live_start_desktop_task` | Documented fast-then-escalate (`textbox_overlay` lines 102–110) |
| `start_desktop_task("Click Save in Notepad")` → UIA click | `_parse_single_click_goal` optimization |
| Second tool in batch returns `ok: false` “Only one desktop action” | Batch gate working as designed |
| Busy refusal while poem task running | `_busy_response` (see `06-busy-gate-stale-flag.md`) |

---

## Recommendations (prose only — no code in this storm)

1. **Canonical router (hard rule):** Before `POST /api/tasks`, classify intent: single click/type in open app → never spawn; multi-step/launch → never fast-path. Model choice becomes advisory; overlay enforces.

2. **Batch collapse:** When a batch contains both desktop tools, execute **one** resolved path (prefer `desktop_control` for click/type shapes, else `start_desktop_task`), return a single combined `FunctionResponse` for both call IDs.

3. **Order-independent gate:** If batch has both tools, do not execute `start_desktop_task` until `desktop_control` fast path has failed (or skip agent entirely for pure click goals).

4. **Instrumentation:** Log hypothesis **B** at `_desktop_control_route` exit: `{routed_to, reason: fast_ok | escalate | redirect | consent}`.

5. **Prompt hygiene:** Keep routing examples in system prompt; keep tool descriptions **non-overlapping** (outcome-only, not re-stating the decision tree).

6. **Regression tests:** Extend `test_handle_message_rejects_second_desktop_tool_in_batch` with `start_desktop_task` **first** in batch — assert no `POST /api/tasks` when goal is parseable as single click.

---

## Related docs

| Doc | Link |
|-----|------|
| Busy gate | `reliability/06-busy-gate-stale-flag.md` |
| Master strategy anti-patterns | `windows-automation-research/00-master-strategy.md` |
| Batch gate test | `tests/test_gemini_live.py::test_handle_message_rejects_second_desktop_tool_in_batch` |
| Redirect test | `tests/test_gemini_live.py::test_start_desktop_task_single_click_redirects_to_fast_path` |

---

*Read-only forensics for subagent-storm reliability lane. No code changes.*
```

---

## Key takeaways

1. **22 model batches** included both `desktop_control` and `start_desktop_task` in the same turn — the chronic trigger.
2. **Batch gate + busy gate** reduce damage when `desktop_control` is first or a task is already running; the **line 731** incident shows failure when `start_desktop_task` runs first.
3. **Overlay escalation/redirect** is intentional and can look like double routing in telemetry without hypothesis **B** routing logs.
4. The `reliability/` folder exists (`06-busy-gate-stale-flag.md` is there) but **`02-double-routing-live.md` is not** — the INDEX already references it.

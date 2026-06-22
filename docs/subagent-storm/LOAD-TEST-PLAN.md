# Gemini Live — Safe Load / Stress Test Plan

**Date:** 2026-06-22  
**Audience:** Engineers manually validating Orynn’s Live front desk under realistic pressure  
**Prerequisite:** Read [INDEX.md](INDEX.md) anti-collision rules

> **This document is a plan only.** It does not start Live, spawn tasks, or run scripts. Execute phases manually when ready.

---

## Goal

Exercise Gemini Live’s routing, tool execution, proactive speech, and reconnect behavior under sustained load **without** corrupting task state, double-spawning agents, or fighting for desktop focus.

Success means:

- One Live session stays connected (or reconnects cleanly) through the full matrix
- Tool routing matches intent (chat vs fast-path vs full agent)
- Back-office tasks run **sequentially** and reach honest terminal states
- Log monitors show no duplicate spawns, stale busy flags, or silent completion gaps

---

## Hard safety rules

| Rule | Why |
|------|-----|
| **Single Live session** | Only one `GeminiLiveCompanion` / voice hotkey session at a time. A second session races on mic, tool callbacks, and `_desktop_busy`. |
| **No overlapping desktop tasks** | At most one `start_desktop_task` in `running` state. Wait for `done` / `complete` / `error` / `cancelled` before the next goal. |
| **No parallel stress drivers** | Do not run `live_qa_matrix.py`, `live_task_batch.py`, and manual voice prompts concurrently. Pick one driver per phase. |
| **One Orynn instance** | Single backend on `:8000` and single overlay. Kill stray `pythonw run_desktop.py` / duplicate backends before starting. |
| **Benign goals only** | Notepad, Calculator, `git status`, disk-space reads, weather/web lookups. No delete/send/pay/relaunch-without-consent during load tests. |
| **Settle time between tasks** | ≥1.5 s idle after each task so focus rings, poll loop, and `_desktop_busy` clear. |
| **Dedicated machine focus** | Do not browse, game, or edit in Cursor while tasks run — Electron unlock and focus theft skew results. |

---

## Environment checklist

Before any Live session:

```text
[ ] GEMINI_API_KEY or GOOGLE_API_KEY set (.env or environment)
[ ] Backend reachable: curl http://127.0.0.1:8000/api/health  (or equivalent)
[ ] Only one Orynn desktop/overlay process
[ ] Microphone and speakers available (if testing voice; text-injection phases can skip mic)
[ ] Log monitors prepared (see below)
[ ] debug-eec63b.log truncated or timestamp noted for session boundary
```

Optional env tuning for observability:

```text
ORYNN_WAKE_WORD=Orynn          # default; change only if testing wake word
ORYNN_TASK_START_GRACE=4.0     # main.py grace before abandon (default)
```

---

## Log monitors

Run these in **separate terminals** before opening Live. They are read-only tailers — they do not drive the session.

### 1. Structured Live debug log

```powershell
Get-Content -Wait C:\Users\ACER\Desktop\Ai_computer\debug-eec63b.log
```

Watch for:

- `hypothesisId` tool-call entries — `desktop_control` vs `start_desktop_task` mix
- `go_away` / `go_away_reconnect` bursts (reconnect storm)
- Tool timeouts (`GEMINI_LIVE_TOOL_TIMEOUT` = 15 s)
- Double routing: same user turn → both fast-path and full agent

### 2. Companion bubble label stream

```powershell
Get-Content -Wait C:\Users\ACER\Desktop\Ai_computer\Orynn\logs\textbox_labels.jsonl
```

Watch for:

- Label leaks (stale “Thinking…” after task end)
- Suppressed labels during Live (`suppressed: true` with reason)
- Mismatch between spoken state and bubble text

### 3. Task terminal states

```powershell
# After each goal, inspect latest task file
Get-ChildItem C:\Users\ACER\Desktop\Ai_computer\Orynn\tasks\*.json |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 3 | ForEach-Object { $_.Name; Get-Content $_.FullName -TotalCount 30 }
```

Watch for:

- `status: abandoned` + `"Server restarted"`
- Ultra-short tasks (≤6 lines) with `complete: true`
- Duplicate task IDs for one spoken goal

### 4. Desktop live aggregate (if present)

```powershell
Get-Content -Wait C:\Users\ACER\Desktop\Ai_computer\Orynn\logs\run_desktop_live.log
```

Useful for resolver-path aggregation (`control_layer` in overlay payloads).

---

## Phased test matrix

Execute phases **in order**. Do not skip ahead to Phase 3 until Phase 2 is clean.

### Phase 0 — Offline gate (no Live)

Confirm the bridge is sound before spending API minutes:

```powershell
cd C:\Users\ACER\Desktop\Ai_computer\Orynn
python -m pytest tests/test_gemini_live.py -q --tb=short
```

Expected: all tests pass (see `tests/01-gemini-live-pytest.txt` in this folder for baseline).

### Phase 1 — Routing matrix (no desktop side effects)

**Driver:** `scripts/live_qa_matrix.py --routing`  
**Sessions:** One fresh Live session **per prompt** (script default) — still safe because routing phase posts dummy `FunctionResponse` without executing tools.

```powershell
cd C:\Users\ACER\Desktop\Ai_computer\Orynn
python scripts/live_qa_matrix.py --routing
```

Verify:

- Chat prompts → no tool call
- Weather/facts → `web_search`
- Multi-step desktop → `start_desktop_task` (not `desktop_control` alone)
- Destructive verbs → consent path or `start_desktop_task` with confirmation gate
- “Stop” → `stop_current_task`

Scan `debug-eec63b.log` for routing mismatches flagged in [logs/01-debug-tool-mix.md](logs/01-debug-tool-mix.md) and [reliability/02-double-routing-live.md](reliability/02-double-routing-live.md).

### Phase 2 — Sequential execution probes (single Live session)

**Driver:** `scripts/live_qa_matrix.py --exec` **or** manual voice via one overlay session — **not both**.

If using the script:

```powershell
python scripts/live_qa_matrix.py --exec
```

If using manual voice:

1. Start Orynn (`run_desktop.py` or existing desktop shortcut)
2. Open **one** Live session (voice hotkey once; confirm single companion in UI)
3. Work through the safe probe list below **one at a time**, waiting for each to finish

Safe probe sequence (in order):

| # | Spoken / typed prompt | Expected route | Wait for |
|---|----------------------|----------------|----------|
| 1 | “What’s the capital of France?” | chat only | spoken reply |
| 2 | “Run git status.” | `run_terminal` | tool result + reply |
| 3 | “What’s on my screen?” | `look_at_screen` | tool result + reply |
| 4 | “Open Notepad and type hello.” | `start_desktop_task` | task `done` + proactive update |
| 5 | “Open Calculator and compute 7 times 8.” | `start_desktop_task` | task `done` |
| 6 | “Stop.” | `stop_current_task` | idle companion |
| 7 | “Did the last task work?” | `get_companion_status` | status summary |

Between rows 4–5: confirm previous task JSON shows terminal status before issuing the next goal.

### Phase 3 — Sustained back-office batch (no Live)

Isolate back-office throughput without voice variable:

**Driver:** `scripts/live_task_batch.py`  
**Constraint:** Script already runs goals sequentially with 1.5 s settle — do **not** run Live concurrently.

```powershell
cd C:\Users\ACER\Desktop\Ai_computer\Orynn
python scripts/live_task_batch.py
```

This fills `tasks/*.json` and overlay logs for offline forensics. Compare results to [logs/04-ultra-short-tasks.md](logs/04-ultra-short-tasks.md) and [logs/09-calculator-e2e-success.md](logs/09-calculator-e2e-success.md).

### Phase 4 — Live under voice load (single session, sequential tasks)

**This is the actual stress phase.** One Live session, many turns, **still no overlapping tasks**.

1. Truncate or note `debug-eec63b.log` start offset
2. Start Orynn + **one** Live voice session
3. Run 8–12 varied goals from `scripts/live_task_batch.py` `GOALS` list **via voice**, not the batch script
4. After each goal:
   - Wait for spoken confirmation or `send_task_update` proactive alert
   - Confirm task JSON terminal state
   - Sleep ≥2 s before next goal
5. Mix in 2–3 pure chat turns (“tell me a joke”) to test barge-in and busy-gate behavior between tasks

Abort criteria (stop the session if any occur):

- Two `start_desktop_task` calls for one spoken intent
- `go_away` reconnect loop >3 times in 60 s
- Bubble stuck on “Thinking…” >30 s after task terminal
- `_desktop_busy` blocking fast-path after task clearly finished
- Live silent after task completion (no proactive speech within ~10 s) — see [reliability/04-proactive-speech-gaps.md](reliability/04-proactive-speech-gaps.md)

### Phase 5 — Reconnect resilience (optional, single session)

Only after Phase 4 is clean:

1. Start one Live session
2. Issue a long task (“Open Notepad, type three paragraphs, select all”)
3. Briefly disable network adapter or toggle airplane mode for ~5 s mid-task
4. Restore network; observe `go_away` handling in `gemini_live.py`

Expected: graceful reconnect, no duplicate task spawn, honest task status. See [reliability/07-go-away-reconnect-storm.md](reliability/07-go-away-reconnect-storm.md).

---

## What NOT to do

| Anti-pattern | Risk |
|--------------|------|
| Two voice hotkeys / two overlays | Duplicate tool callbacks, mic contention |
| `live_task_batch.py` + Live voice simultaneously | Overlapping tasks fighting for focus |
| Chaining “click X” via `desktop_control` for multi-step work | Bypasses escalation; double routing |
| Destructive goals during load test | Consent noise masks real reliability signals |
| Running 50 subagents that each start Live | Exactly the collision this storm avoided |
| Ignoring `stop` between phases | Stale agent keeps running into next goal |

---

## Pass / fail rubric

| Signal | Pass | Fail |
|--------|------|------|
| Tool mix | Chat → no tool; multi-step → `start_desktop_task` once | Double routing same turn |
| Task honesty | `complete` matches observable outcome | `complete: true` on ≤6-line bail |
| Proactive speech | Live speaks on task done without user prompt | Silent completion |
| Session stability | ≤1 reconnect per 10 min under normal network | `go_away` storm |
| Desktop gate | Fast-path unblocks after task ends | Stale `_desktop_busy` |
| Bubble UI | Label matches task phase | Leaked “Thinking…” |

---

## Post-run artifacts

Archive for storm cross-reference:

```text
debug-eec63b.log          # slice from session start timestamp
logs/textbox_labels.jsonl # same window
tasks/*.json              # new files from session
tests/0*-pytest.txt       # refresh if code changed
```

File findings under `docs/subagent-storm/logs/` or open issues linked to [reliability/](reliability/) and [proposals/](proposals/) entries.

---

## Related scripts

| Script | Role in plan |
|--------|----------------|
| `scripts/live_qa_matrix.py` | Phase 1 routing + Phase 2 execution probes |
| `scripts/live_task_batch.py` | Phase 3 back-office batch (no Live) |
| `scripts/live_tool_smoke.py` | Minimal single-tool wire check (pre-phase smoke) |
| `scripts/debug_live_messages.py` | Deep message-shape logging for tool-call bugs |
| `tests/test_gemini_live.py` | Phase 0 offline gate |

---

## Storm cross-links

Reliability docs most relevant during load testing:

- [02-double-routing-live.md](reliability/02-double-routing-live.md)
- [04-proactive-speech-gaps.md](reliability/04-proactive-speech-gaps.md)
- [06-busy-gate-stale-flag.md](reliability/06-busy-gate-stale-flag.md)
- [07-go-away-reconnect-storm.md](reliability/07-go-away-reconnect-storm.md)

Log forensics to run after a session:

- [01-debug-tool-mix.md](logs/01-debug-tool-mix.md)
- [02-silent-turns-pattern.md](logs/02-silent-turns-pattern.md)
- [06-duplicate-start-desktop-task.md](logs/06-duplicate-start-desktop-task.md)

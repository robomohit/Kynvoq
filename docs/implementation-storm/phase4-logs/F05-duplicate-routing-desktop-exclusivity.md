# F05 — Duplicate Routing / Desktop Tool Exclusivity

**Lane:** F05  
**Date:** 2026-06-22  
**Sources:** gate_results.json, Phase 3 task JSONs, debug-eec63b.log (historical)

---

## Phase 3 session — exclusivity

### Tasks spawned (Phase 3 only)

| task_id | goal (short) | created | status |
|---------|--------------|---------|--------|
| clicky-c1427765ef | Calculator 17×23 | 20:17:12Z | done |
| clicky-4a9dc02a07 | Notepad hello world | 20:17:35Z | done |

**Duplicate goals within 30s:** 0 — distinct goals, sequential spawn after first task still running (by design for routing test).

### Busy gate enforcement

| Scenario | attempted | blocked | label |
|----------|-----------|---------|-------|
| E02 (Notepad hello) | start_desktop_task | busy: Calculator | slice L72 |
| complex_notepad | start_desktop_task | busy: Notepad hello world | slice L75–76 |

gate_results.json confirms `ok: false, busy: true` with spoken alternatives — **no duplicate spawn**.

### Routing discrimination (3/3)

From gate_results.json lines 108–133:

| prompt | expect | got |
|--------|--------|-----|
| Open Notepad. | launch_app | launch_app ✓ |
| Open Notepad and type hello world. | start_desktop_task | start_desktop_task ✓ |
| Open Calculator. | launch_app | launch_app ✓ |

Slice labels L73 (`Opening notepad`) and L74 (`Started: open Notepad…`) align with routing test sequence.

---

## Historical duplicate routing (debug log)

**25 dual-tool batches** in `debug-eec63b.log` pairing `desktop_control` + `start_desktop_task` (see F02 L731, L1144+).

Example pattern (lines 75–77):
```
tool_call: ["start_desktop_task"]
execute exit: ok true
tool_call: ["start_desktop_task"]  # duplicate within ~30ms
execute exit: ok true
```

Pre-fix duplicate spawns contributed to abandon races and `Server restarted` bubble leaks.

---

## Phase 3 vs historical

| metric | historical (debug) | Phase 3 gate |
|--------|------------------|--------------|
| dual desktop batches | 25 | 0 |
| busy blocks | 3+ | 2 (observed in gate) |
| duplicate task JSON same goal | frequent in tasks/ archive | 0 in session |

---

## Findings

1. **WS2 exclusivity + busy gate work in Phase 3** — no duplicate spawns, correct specialist routing.
2. Historical dual-route batches remain in debug log as regression baseline.
3. Routing test intentionally started Notepad task while Calculator ran — busy gate correctly refused E02/complex_notepad duplicates.

---

## Verdict (lane)

**PASS.** No duplicate routing or exclusivity violation in Phase 3 session.

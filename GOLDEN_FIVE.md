# The Golden Five — Orynn's reliability bar

The North Star is graded on one thing: **the same spoken, hands-free command working
every single time** — not most of the time. Trust, not capability. A command that
works 10/10 beats ten commands that work 7/10.

This file defines the five bounded commands we hold to that bar and the one-command
proof that they still meet it. Keep it honest: a command only earns a row here once
it passes the proof, and it loses its row the day it stops.

## The five

Each is a narrow, deterministic desktop primitive — the "focus window / read screen /
find / type / press keys" surface. They run through the no-LLM gateway
(`OverlayController._live_tool("desktop_control", …)`), the same path push-to-talk and
Gemini Live use for bounded commands. No model call, no API quota — so flakiness here
is *our* bug, never a free-tier hiccup.

| # | Spoken intent (what Mohit actually says) | Primitive (`desktop_control` action) |
|---|------------------------------------------|--------------------------------------|
| 1 | "open / go to <app>"                      | `wait_for_window` → locate the window |
| 2 | "switch to <app>" / bring it to front     | `focus_window`                        |
| 3 | "what's on screen?" / read it             | `observe` → read controls             |
| 4 | "find the <control>"                       | `find` → locate a control by name     |
| 5 | "type <text>" / "select all / save / close" | `type` (UIA-verified) + `press_keys` |

These map 1:1 onto commands observed working in real use (`tasks/*.json`): *"Open the
Windows Calculator app."*, *"open Notepad"*, *"check storage space"*, *"search the
web"*. The richer LLM-planned tasks build on top of these — if the primitives are
never-fail, the agent's floor is never-fail.

## The proof gate

```
python scripts/golden_reliability.py            # warm: each primitive 10x (the bar)
python scripts/golden_reliability.py --cold     # cold: full open->type->close lifecycle 10x
python scripts/golden_reliability.py --reps 25  # tighter
python scripts/golden_reliability.py --json     # machine-readable
```

It opens a **contained** Notepad (a temp canary file, targeted by title so typing
never lands in whatever app you have focused), runs each primitive N times, and prints
per-command pass rate + latency. It **exits non-zero unless every command is N/N**, so
"10x in a row" is a pass/fail gate, not a vibe. The window is closed without saving.

Two modes, because they catch different bugs:
- **warm** (default) hits one persistent window — isolates per-primitive flakiness.
- **`--cold`** relaunches the app fresh every rep — the *real* "open <app> and type"
  command end to end, where launch flakiness (slow paint, title mismatch, focus theft)
  actually shows up. The warm path hides that by design.

## The full spoken path (`scripts/golden_voice_e2e.py`)

The gate above proves the deterministic *tail* (desktop_control). The spoken command
also has a flaky *middle*: transcript -> `build_task_payload` -> `/api/tasks/preflight`
-> `/api/tasks` -> planner -> desktop. This harness drives that whole middle through
the **exact** submission the push-to-talk handler uses, against a real backend +
planner, and verifies the result by what appeared on screen (safe window-handle
attribution — it never touches a window you already had open).

```
python scripts/golden_voice_e2e.py --phrase "open notepad" --reps 10    # real planner, ~10-20s/rep
python scripts/golden_voice_e2e.py --phrase "open calculator" --reps 10
python scripts/golden_voice_e2e.py --wav me.wav --expect "open notepad"  # STT half, with YOUR voice
```

### "open <app>" is now a deterministic fast-path (no LLM) — 2026-06-16

The recommendation below was **implemented**: a pure "open / launch / switch to <known
app>" command no longer touches the LLM planner. `detect_app_launch_intent()`
(`app/tools.py`) recognizes it, `build_task_payload` keeps the goal RAW (no hardening
prompt), and `run_task` runs `ToolExecutor.open_known_app()` directly — focus the window
if it's already up, else launch it and wait for the window in code. Anything that isn't a
pure known-app launch (extra steps, unknown app) falls straight through to the planner.

End-to-end at the 10x bar, deterministic fast-path vs. the old free-planner path:

```
spoken command     fast-path (now)   old LLM path     verified by
open notepad       10/10  1.3s        10/10  12.3s    a real Notepad window
open calculator    10/10  2.3s        10/10  11.7s    a real Calculator window
open settings      10/10  2.3s         8/10 (flaky)   Settings window present (single-instance focus)
```

~5–9x faster, and "open settings" — which the free planner only hit 8/10 (it sometimes
reported `done` before the window existed) — is now a hard 10/10 because the success of
`open_known_app` *is* the verification: a real window, not a model claiming done. This is
NARROW > BROAD made concrete. Pinned by
`tests/test_fast_path.py::test_open_app_uses_deterministic_fast_path_no_llm` (proves the
LLM is never invoked) and `tests/test_voice_and_env.py` (detector + unwrapped payload).

**Older finding (now resolved by the above).** "open settings" was 8/10 until a prompt
contradiction was fixed (step 1 forbade `start X:` protocol links, but Settings needs
`ms-settings:`). "open paint" missed ~1/10 on the planner path because the free LLM
sometimes reported `done` before the window painted. The deterministic fast-path removes
that failure mode entirely for known apps.

It is deliberately honest: it does **not** fake STT with a synthetic TTS->Whisper
round-trip (that passes trivially and proves nothing about a real voice). Check STT
with a real recording via `--wav`.

> **Bug this caught (2026-06-16):** `build_task_payload` prepends a ~1.7 KB desktop-
> hardening prompt to the goal for `computer` mode, so even "open notepad" built a
> 2041-char goal — but `TaskIn.goal` was capped at 2000. **Every** spoken desktop
> command was rejected with HTTP 422 and the bubble just said "Couldn't start task":
> the free push-to-talk desktop path was 100% broken. Fixed by raising the cap to
> 8000 (still under the 10 KB request guard); pinned by
> `tests/test_voice_and_env.py::test_voice_desktop_payload_fits_task_schema`. After
> the fix, at the 10x bar: "open notepad" 10/10 and "open calculator" 10/10, a
> real window verified on screen every time.

Run it before trusting any change that touches `app/tools.py`,
`app/widget/textbox_overlay.py`, or the desktop/UIA path. It needs a real Windows
desktop (it can't run in headless CI) — it's the manual canary that the unit suite
(`python -m pytest`) can't cover.

## Baseline (2026-06-16, 10 reps each)

Warm (`golden_reliability.py`):

```
command        pass    p50   p95   max   notes
find-window   10/10    418   424   424   ms
focus-window  10/10    365   379   379   ms
read-screen   10/10      1   612   612   ms (first observe cold; cached after)
find-control  10/10    313   321   321   ms
type-text     10/10   1036  1054  1054   ms (write + UIA verify)
press-keys    10/10    450   455   455   ms (ctrl+a)
```

Cold (`golden_reliability.py --cold`) — full open->type->close, fresh window per rep:

```
command        pass    p50   p95   max   notes
cold-open     10/10    568   761   761   ms (launch + locate from cold)
cold-type     10/10   1045  1063  1063   ms (type into fresh editor + verify)
```

All green, 10/10, warm and cold. That's the floor we don't drop below.


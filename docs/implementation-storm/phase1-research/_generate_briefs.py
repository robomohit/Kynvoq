#!/usr/bin/env python3
"""Phase 1 research brief generator — docs only, run once from phase1-research/."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parent

SECTIONS = (
    "## Storm lineage",
    "## Current code paths",
    "## Gap analysis",
    "## Proposed implementation",
    "## Files to touch (Phase 2)",
    "## Test strategy",
    "## Estimated complexity",
    "## Phase 2 workstream hint",
)


def brief(title: str, category: str, storm: str, paths: str, gap: str, impl: str, files: str, tests: str, complexity: str, ws: str) -> str:
    return f"""# {title}

**Category:** {category}  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
{storm}

## Current code paths
{paths}

## Gap analysis
{gap}

## Proposed implementation
{impl}

## Files to touch (Phase 2)
{files}

## Test strategy
{tests}

## Estimated complexity
{complexity}

## Phase 2 workstream hint
{ws}
"""


LANES: list[tuple[str, str, str]] = []  # (subdir, filename, body)

def add(subdir: str, num: int, slug: str, body: str):
    LANES.append((subdir, f"{num:02d}-{slug}.md", body))


# --- A. Specialists (17) ---
add("specialists", 1, "launch-specialist", brief(
    "Lane A01: Launch Specialist",
    "specialists",
    "Builds on [`SYNTHESIS-subagents-vs-orynn.md`](../../subagent-storm/SYNTHESIS-subagents-vs-orynn.md) `launch` built-in; [`reliability/10-launch-registry-gaps.md`](../../subagent-storm/reliability/10-launch-registry-gaps.md); [`proposals/01-resolve-launch-target.md`](../../subagent-storm/proposals/01-resolve-launch-target.md).",
    "- `detect_app_launch_intent()` — `app/tools.py:471-488` — curated `_KNOWN_LAUNCH_APPS` exact match only.\n- Fast-path routing in `textbox_overlay._live_start_desktop_task` checks launch intent before POST.\n- Registry gaps: ~7 apps vs universal launch research.",
    "Launch is implicit inside `start_desktop_task` / overlay routing, not a first-class Live specialist with its own contract, bubble labels, or verify pass. Spotify failures often never reach launch ladder.",
    "1. Add `specialists/launch` entry to registry (name, description, tools=`resolve_launch_target`, sync).\n2. Live tool `launch_app` OR route `start_desktop_task` goals through launch specialist when `detect_app_launch_intent` + `resolve_launch_target` succeed.\n3. Return `{ok, user_message, window_title}`; never raw shell errors.\n4. Chain to `verify` specialist (foreground window title) before Live speaks success.",
    "- `app/tools.py` — expand registry + `resolve_launch_target`\n- `app/widget/textbox_overlay.py` — `_live_tool` dispatch\n- `app/widget/gemini_live.py` — declaration + system prompt routing\n- `Orynn/agents/launch.md` — declarative profile",
    "- `tests/test_fast_path.py`, `tests/test_desktop_launcher.py` — extend registry cases\n- Golden: Spotify URI launch mock\n- Phase 3: spoken \"open Spotify\" → foreground check",
    "**M**",
    "WS1 Launch & Registry",
))

add("specialists", 2, "uia-act-specialist", brief(
    "Lane A02: UIA Act Specialist (`desktop_control`)",
    "specialists",
    "[`backoffice/08-desktop-control-route-review.md`](../../subagent-storm/backoffice/08-desktop-control-route-review.md), [`backoffice/02-tools-uia-click-review.md`](../../subagent-storm/backoffice/02-tools-uia-click-review.md).",
    "- Declaration: `gemini_live._function_declarations` → `desktop_control`\n- Execution: `textbox_overlay._desktop_control_route` (~1761), `_live_desktop_control` with `fast_invoke_only=True`\n- Escalation to full task on UIA miss (~1848 \"Trying the full agent\")",
    "Specialist exists as a tool, not a profile. Raw UIA diagnostics can still leak on failure paths. Model batches with `start_desktop_task`.",
    "Formalize `uia_act` specialist: allowed actions enum, max 1 gesture, humanized `live_tool` labels (`LIVE_DESKTOP_ACTION_LABELS`), structured `{ok, action, user_message, escalate?}`. Enforce mutual exclusion at registry level.",
    "- `app/widget/textbox_overlay.py`\n- `app/widget/gemini_live.py`\n- `app/tools.py` — `uia_click` ladder",
    "- `tests/test_gemini_live.py` — desktop_control contracts\n- `tests/test_computer_control_regressions.py`",
    "**S** (mostly contract + labeling)",
    "WS2 Live Front Desk & Specialists",
))

add("specialists", 3, "vision-peek-specialist", brief(
    "Lane A03: Vision Peek Specialist",
    "specialists",
    "[`reliability/08-vision-hallucination-patterns.md`](../../subagent-storm/reliability/08-vision-hallucination-patterns.md), tool contracts §2.4-2.6.",
    "- `look_at_screen`, `list_windows`, `capture_window` in `textbox_overlay._live_tool`\n- Vision frame ordering: send video before `FunctionResponse` (`gemini_live`)\n- Labels: \"Looking at the screen\" (`textbox_overlay.py:1278`)",
    "No read-only guarantee in registry; model may chain desktop_control after peek. Hallucination patterns when frame stale or OCR skipped.",
    "Register `vision_peek` as readonly specialist: tools limited to look/list/capture; forbid write tools in same turn; add `frame_age_ms` in response; mid-tier OCR before full describe (see tools/07).",
    "- `app/widget/textbox_overlay.py`\n- `app/widget/gemini_live.py`\n- `app/providers.py` — vision describe",
    "- `tests/test_gemini_live.py`\n- `scripts/live_vision_smoke.py` for Phase 3",
    "**M**",
    "WS2 Live Front Desk & Specialists",
))

add("specialists", 4, "desktop-job-specialist", brief(
    "Lane A04: Desktop Job Specialist (`start_desktop_task`)",
    "specialists",
    "SYNTHESIS generic worker; [`backoffice/04-main-task-lifecycle-review.md`](../../subagent-storm/backoffice/04-main-task-lifecycle-review.md).",
    "- `textbox_overlay._live_start_desktop_task` → POST `/api/tasks`\n- `_await_task_outcome` poll loop (`textbox_overlay.py:2646+`)\n- Backend: `agent.py` ReAct loop, `main.py` lifecycle",
    "Full agent is default bucket for everything multi-step. No structured handoff schema; `reason` field leaks to bubble if gates fail.",
    "Wrap as `desktop_job` specialist: always background, returns `{task_id, user_message, status, debug_reason}`; Live uses `send_task_update` for narration; bubble policy mutes `task_result`.",
    "- `app/widget/textbox_overlay.py`\n- `app/main.py`\n- `app/agent.py`",
    "- `tests/test_task_abandon_grace.py`\n- `tests/test_live_robustness.py`",
    "**L**",
    "WS3 Task Lifecycle & Handoff",
))

add("specialists", 5, "verify-specialist", brief(
    "Lane A05: Verify Specialist",
    "specialists",
    "SYNTHESIS recommendation #4; [`logs/08-complete-honesty-patterns.md`](../../subagent-storm/logs/08-complete-honesty-patterns.md).",
    "Partial: `tests/test_visual_verification.py` exists for agent; no Live post-launch verify hook.",
    "Live claims success before window foreground / file exists / display value checked.",
    "New readonly specialist invoked after `launch` or short `desktop_job`: checks window title fuzzy match, process running, optional screenshot diff. Returns `{verified: bool, user_message}`. 2s budget.",
    "- New `app/verify.py` or `app/widget/verify_specialist.py`\n- `textbox_overlay.py` — post-task hook",
    "- Unit tests with mocked window list\n- Phase 3: calculator result on screen",
    "**M**",
    "WS1 Launch & Registry (verify chain)",
))

add("specialists", 6, "browser-specialist", brief(
    "Lane A06: Browser Specialist",
    "specialists",
    "SYNTHESIS missing built-in; [`proposals/07-playwright-connectors.md`](../../subagent-storm/proposals/07-playwright-connectors.md); `agent.py` headless browser mode.",
    "- Back-office `browser_*` tools in `agent.py` / `ToolExecutor`\n- Not exposed as Live built-in with Antigravity `/browser` contract",
    "Web tasks route to generic desktop_job or failing `web_search` (~75% fail in logs).",
    "Expose `browser_task` Live tool → spawns readonly/write browser sub-loop with Playwright; summary-only handoff; sandbox domain allowlist.",
    "- `app/agent.py` browser profile\n- `app/widget/gemini_live.py`\n- `tests/test_browser_plugin.py`",
    "- Extend `test_browser_plugin.py`\n- Phase 3 browser scenarios (live-test-plan/01)",
    "**L**",
    "WS5 Browser & Web (optional P1)",
))

add("specialists", 7, "research-specialist", brief(
    "Lane A07: Research Specialist (codebase)",
    "specialists",
    "SYNTHESIS `research` built-in; Cursor Explore analog.",
    "- File reads via agent tools / terminal in desktop_job\n- No dedicated readonly search specialist for Live",
    "Codebase questions pollute desktop_job context or aren't available in Live mode.",
    "`research_codebase` tool: ripgrep + read_file readonly, returns `{paths, snippets, summary}`; no writes; fast model.",
    "- `app/tools.py` or new `app/research.py`\n- `gemini_live.py` declaration",
    "- `tests/test_agent.py` patterns\n- Mock workspace fixtures",
    "**M**",
    "WS5 Browser & Web or WS2",
))

add("specialists", 8, "specialist-registry-architecture", brief(
    "Lane A08: Specialist Registry Architecture",
    "specialists",
    "SYNTHESIS § declarative registry; Cursor `.cursor/agents/` pattern.",
    "Tools are flat function declarations; no central registry object.",
    "Routing rules duplicated across prompt, declarations, overlay dispatch.",
    "Introduce `app/specialists/registry.py`: `SpecialistSpec` dataclass (name, description, tools, readonly, is_background, bubble_policy, model_tier). Loaded at Live connect.",
    "- New `app/specialists/`\n- `gemini_live.py` — generate declarations from registry",
    "- Registry unit tests\n- Snapshot of generated declarations",
    "**M**",
    "WS2 Live Front Desk & Specialists",
))

add("specialists", 9, "specialist-routing-gemini-live", brief(
    "Lane A09: Specialist Routing in Gemini Live",
    "specialists",
    "[`backoffice/07-gemini-live-tool-contracts.md`](../../subagent-storm/backoffice/07-gemini-live-tool-contracts.md); [`reliability/02-double-routing-live.md`](../../subagent-storm/reliability/02-double-routing-live.md).",
    "- `_default_system_instruction()` routing examples\n- Batch gate `desktop_used` (`gemini_live.py:852-871`)\n- `_live_tool_for_generation` generation guard",
    "Model still emits dual desktop tools (22 batches in debug log). Prompt-only routing insufficient.",
    "Add registry-driven routing section to system prompt; optional server-side intent classifier pre-tool-call; extend mutual exclusion to launch vs job vs uia_act families.",
    "- `app/widget/gemini_live.py`\n- `app/specialists/registry.py`",
    "- `tests/test_gemini_live.py` — dual-tool batch rejection\n- `tests/test_mode_routing.py`",
    "**M**",
    "WS2 Live Front Desk & Specialists",
))

add("specialists", 10, "specialist-bubble-policy", brief(
    "Lane A10: Specialist Bubble Policy",
    "specialists",
    "[`reliability/03-bubble-leak-regression.md`](../../subagent-storm/reliability/03-bubble-leak-regression.md).",
    "- `_set_label` mute rule (`textbox_overlay.py:873-884`)\n- `_LIVE_LABEL_SOURCES` / `_TASK_CHURN_SOURCES`",
    "Per-specialist bubble rules not encoded; workers can still set `live_tool` with raw output.",
    "Each `SpecialistSpec.bubble_policy`: `user_message_only | tool_label | mute`. Central sanitizer strips `Failed:`, JSON, UIA dumps before emit.",
    "- `app/widget/textbox_overlay.py`\n- `app/specialists/registry.py`",
    "- `tests/test_quiet_companion.py`\n- `tests/test_gemini_live.py`",
    "**S**",
    "WS4 Bubble & Speech Sanitization",
))

add("specialists", 11, "specialist-background-foreground-modes", brief(
    "Lane A11: Background vs Foreground Specialist Modes",
    "specialists",
    "SYNTHESIS Cursor foreground/background; Antigravity async default.",
    "- `desktop_job` async via poll\n- `desktop_control` sync in tool callback\n- `GEMINI_LIVE_TOOL_TIMEOUT=15s`",
    "No explicit `is_background` on specs; long jobs risk tool timeout while still running.",
    "Tag specialists: sync (uia_act, vision_peek, launch) return in-tool; async (desktop_job, browser) return `{task_id, accepted:true}` immediately + `send_task_update` stream.",
    "- `gemini_live.py` timeout policy per specialist\n- `textbox_overlay.py`",
    "- Timeout tests with mocked slow task",
    "**M**",
    "WS3 Task Lifecycle & Handoff",
))

add("specialists", 12, "specialist-declarative-agents-md", brief(
    "Lane A12: Declarative `Orynn/agents/*.md` Profiles",
    "specialists",
    "SYNTHESIS § version-control specialists; Cursor agent files.",
    "No `Orynn/agents/` directory; prompts hardcoded in Python.",
    "Specialist tuning requires code edits; no user-extensible profiles.",
    "Add `Orynn/agents/{launch,browser,desktop_job}.md` with YAML frontmatter (name, description, readonly, tools). Loader merges into registry at startup.",
    "- New `Orynn/agents/`\n- `app/specialists/loader.py`",
    "- Loader unit tests with fixture md files",
    "**S**",
    "WS2 Live Front Desk & Specialists",
))

add("specialists", 13, "specialist-handoff-schema", brief(
    "Lane A13: Specialist Handoff Schema",
    "specialists",
    "SYNTHESIS sanitized handoff; [`reliability/03-structured-handoff`](../../subagent-storm/reliability/03-bubble-leak-regression.md) (related).",
    "- Ad hoc dict keys in tool responses\n- Task `reason` field freeform",
    "No stable contract between worker and Live; JSON leaks in `reason`.",
    "Standardize `HandoffResult` TypedDict: `user_message: str`, `status: success|failed|partial`, `debug_reason: str`, `task_id?: str`. All specialists return this; bubble/voice read `user_message` only.",
    "- `app/models/handoff.py` (new)\n- `textbox_overlay._capture_live_task_outcome`",
    "- Schema validation tests\n- Golden Spotify handoff",
    "**M**",
    "WS3 Task Lifecycle & Handoff",
))

add("specialists", 14, "specialist-mutual-exclusion", brief(
    "Lane A14: Specialist Mutual Exclusion",
    "specialists",
    "[`reliability/02-double-routing-live.md`](../../subagent-storm/reliability/02-double-routing-live.md).",
    "- `_DESKTOP_TOOLS` batch gate in `gemini_live.py:852-871`\n- Overlay intentional escalation (fast→full) looks like double route",
    "Gate covers only desktop_control+start_desktop_task; not launch+job or peek+act.",
    "Define exclusion groups in registry: `DESKTOP_WRITE`, `LAUNCH`, `VISION`. Max one tool per group per batch; document intentional escalation as single specialist chain.",
    "- `app/widget/gemini_live.py`\n- `app/specialists/registry.py`",
    "- `tests/test_gemini_live.py` multi-tool batches",
    "**S**",
    "WS2 Live Front Desk & Specialists",
))

add("specialists", 15, "specialist-model-selection", brief(
    "Lane A15: Specialist Model Selection",
    "specialists",
    "SYNTHESIS model flexibility; `GEMINI_LIVE_THINKING_LEVEL`.",
    "- Single Live model session\n- Back-office uses provider routing in `providers.py`",
    "Cannot use fast cheap model for explore/verify while keeping strong model for desktop_job.",
    "Add `model_tier: fast|standard` per specialist; vision_peek/verify may use lighter describe model; desktop_job unchanged.",
    "- `app/providers.py`\n- `app/specialists/registry.py`",
    "- Mock provider selection assertions",
    "**M** (P2)",
    "WS2 or defer",
))

add("specialists", 16, "specialist-resume-idle-worker", brief(
    "Lane A16: Resume Idle Worker by Task ID",
    "specialists",
    "SYNTHESIS Antigravity idle→running; task retry ad hoc.",
    "- Task poll by ID in overlay\n- `session_resumption` for Live WS only",
    "User \"yeah sure\" retriggers new task instead of resuming `clicky-*`.",
    "Add `resume_desktop_task(task_id, message)` Live tool; backend appends goal to paused/running task context.",
    "- `app/main.py` task API\n- `gemini_live.py`",
    "- API tests for resume endpoint",
    "**L** (P2)",
    "WS3 Task Lifecycle",
))

add("specialists", 17, "specialist-orchestrator-verifier-chain", brief(
    "Lane A17: Orchestrator → Worker → Verifier Chain",
    "specialists",
    "SYNTHESIS recommendation #5; Cursor Verifier pattern.",
    "Linear: user → Live → single tool. No mandatory verify step.",
    "Premature success narration (Spotify, web_search).",
    "Document chain: Live plans → delegates specialist → on terminal, invoke verify → only then speak success. Implement as overlay orchestration hook, not nested LLM by default.",
    "- `textbox_overlay.py` — `_post_specialist_hook`\n- Specialist registry",
    "- Integration test: launch→verify mock",
    "**M**",
    "WS1 + WS4",
))

# --- B. Reliability (11) ---
add("reliability", 1, "bubble-sanitization", brief(
    "Lane B01: Bubble Sanitization",
    "reliability",
    "[`reliability/03-bubble-leak-regression.md`](../../subagent-storm/reliability/03-bubble-leak-regression.md).",
    "- `_set_label` arbitration (`textbox_overlay.py:853-893`)\n- `VirtualCursorOverlay` companion lock\n- Humanized `LIVE_DESKTOP_ACTION_LABELS`",
    "Edge leaks: raw `output` on desktop_control fail, `Started:` goal echo, agent STEP lines if source mis-tagged.",
    "Central `_sanitize_bubble_text(text, source)` denylist: `Failed:`, `Server restarted`, UIA regex, JSON blobs. Apply before any emit.",
    "- `app/widget/textbox_overlay.py`\n- `app/widget/virtual_cursor.py`",
    "- `tests/test_quiet_companion.py`\n- `tests/test_gemini_live.py`",
    "**S**",
    "WS4 Bubble & Speech Sanitization",
))

add("reliability", 2, "task-outcome-muting", brief(
    "Lane B02: Task Outcome Muting Under Live",
    "reliability",
    "03-bubble-leak § task_result mute.",
    "- `task_outcome_under_live` mute reason (`textbox_overlay.py:880-884`)\n- `ORYNN_LABEL_LOG` diagnostics (`textbox_overlay.py:341-345`)",
    "Poll thread may still update internal state shown elsewhere; `task_prime` timing edge cases.",
    "Ensure ALL terminal paths (`failed`, `complete`, `cancelled`) use mute + `_capture_live_task_outcome` only.",
    "- `textbox_overlay.py` poll loop",
    "- Label log assertions in `test_quiet_companion`",
    "**S**",
    "WS4",
))

add("reliability", 3, "structured-handoff", brief(
    "Lane B03: Structured Handoff Worker → Live",
    "reliability",
    "SYNTHESIS P0 #1; proposals/05-task-spawn-fix.",
    "- `_await_task_outcome` builds tool response\n- `send_task_update` for proactive speech",
    "Freeform `reason` and `message` fields; Live improvises from raw failure strings.",
    "Map task terminal → `HandoffResult`; `message` field = `user_message`; never pass `record.reason` to bubble.",
    "- `textbox_overlay._capture_live_task_outcome`\n- `app/models/handoff.py`",
    "- Golden handoff fixtures from `tasks/clicky-c6beede9be.json`",
    "**M**",
    "WS3",
))

add("reliability", 4, "double-routing-enforcement", brief(
    "Lane B04: Double Routing Enforcement",
    "reliability",
    "[`reliability/02-double-routing-live.md`](../../subagent-storm/reliability/02-double-routing-live.md).",
    "- Batch gate `gemini_live.py:852-871`\n- Overlay escalation paths",
    "22 dual-tool batches in log; model ignores prompt.",
    "1. Keep batch gate. 2. Log metric `double_route_blocked`. 3. Consider collapsing to single `desktop_action` tool with `mode: fast|full`. 4. Prompt reinforcement with negative examples.",
    "- `gemini_live.py`\n- Optional declaration merge",
    "- `tests/test_gemini_live.py`\n- Count metric in Phase 4 logs",
    "**M**",
    "WS2",
))

add("reliability", 5, "abandon-race-main-py", brief(
    "Lane B05: Abandon Race (`main.py`)",
    "reliability",
    "[`reliability/01-task-abandon-race.md`](../../subagent-storm/reliability/01-task-abandon-race.md); [`proposals/05-task-spawn-fix.md`](../../subagent-storm/proposals/05-task-spawn-fix.md).",
    "- `_serialize_task_record` grace (`main.py:608-646`, `_TASK_START_GRACE`)\n- `_task_done_exception` for honest reasons",
    "Grace window may be too short on slow disks; GET still persists terminal in edge cases.",
    "Verify grace constant; add `startup_phase` flag on record until first agent signal; never persist failed on GET without agent verdict.",
    "- `app/main.py`",
    "- `tests/test_task_abandon_grace.py` (extend)",
    "**M**",
    "WS3 Task Lifecycle & Handoff",
))

add("reliability", 6, "send-task-update", brief(
    "Lane B06: `send_task_update` Proactive Speech",
    "reliability",
    "[`reliability/04-proactive-speech-gaps.md`](../../subagent-storm/reliability/04-proactive-speech-gaps.md).",
    "- `gemini_live.send_task_update` (`gemini_live.py:634`)\n- Called from `_capture_live_task_outcome` (`textbox_overlay.py:2420+`)",
    "Silent turns when task completes but Live doesn't speak; user stares at muted bubble.",
    "Always call `send_task_update(user_message)` on terminal task; include `force_speak` for failures; debounce duplicates.",
    "- `gemini_live.py`\n- `textbox_overlay.py`",
    "- `tests/test_live_robustness.py`",
    "**S**",
    "WS4",
))

add("reliability", 7, "busy-gate-stale-flag", brief(
    "Lane B07: Busy Gate Stale Flag",
    "reliability",
    "[`reliability/06-busy-gate-stale-flag.md`](../../subagent-storm/reliability/06-busy-gate-stale-flag.md).",
    "- `_active_task_running` / busy checks in `_live_tool`\n- Label \"Busy:\" (`textbox_overlay.py:2168`)",
    "Flag not cleared on crash/restart; blocks fast path clicks.",
    "Clear busy on terminal poll, server restart, and `stop_current_task`; TTL watchdog 30s; expose `busy_reason` in tool response.",
    "- `textbox_overlay.py`\n- `main.py` task terminal webhook optional",
    "- `tests/test_queue_resilience.py`",
    "**S**",
    "WS3",
))

add("reliability", 8, "proactive-honest-speech", brief(
    "Lane B08: Proactive Honest Speech",
    "reliability",
    "[`logs/08-complete-honesty-patterns.md`](../../subagent-storm/logs/08-complete-honesty-patterns.md); Spotify postmortem.",
    "Live narrates \"Opening…\" before worker confirms; optimistic TTS.",
    "User hears success while task failed in <300ms.",
    "Defer optimistic phrases until tool returns `ok:true`; use progressive updates via `send_task_update`; ban success templates in system prompt until verify passes.",
    "- `gemini_live._default_system_instruction`\n- `textbox_overlay` tool responses",
    "- Phase 3 Spotify scenario\n- Label log: live_reply before task terminal",
    "**M**",
    "WS4",
))

add("reliability", 9, "user-goal-vs-prompt-goal", brief(
    "Lane B09: `user_goal` vs `prompt_goal` Split",
    "reliability",
    "[`backoffice/09-task-payload-build-review.md`](../../subagent-storm/backoffice/09-task-payload-build-review.md).",
    "- `_build_task_payload` / `build_task_payload` in overlay + main",
    "Single `goal` string conflates user speech with planner-expanded TASK: prefix; breaks retry and logging.",
    "Persist `user_goal` (verbatim speech) and `prompt_goal` (agent-facing); bubble shows user_goal only.",
    "- `textbox_overlay.py`\n- `main.py` TaskRecord schema",
    "- Payload snapshot tests",
    "**S**",
    "WS3",
))

add("reliability", 10, "reason-sanitization", brief(
    "Lane B10: Task `reason` Sanitization",
    "reliability",
    "Spotify postmortem; abandon race docs.",
    "- `record.reason` freeform in `tasks/*.json`\n- Shown if handoff bypasses mute",
    "Opaque \"Server restarted or task was abandoned.\" and JSON action dumps in reason.",
    "`_humanize_task_reason(reason) -> user_message` mapping table; strip internal prefixes; log raw reason to debug only.",
    "- `app/main.py`\n- `textbox_overlay._capture_live_task_outcome`",
    "- Table-driven tests for reason strings",
    "**S**",
    "WS4",
))

add("reliability", 11, "go-away-reconnect-handling", brief(
    "Lane B11: `go_away` Reconnect Handling",
    "reliability",
    "[`reliability/07-go-away-reconnect-storm.md`](../../subagent-storm/reliability/07-go-away-reconnect-storm.md).",
    "- `_handle_message:go_away` logging (`gemini_live.py`)\n- `session_resumption` handle",
    "Reconnect drops in-flight tool results; generation guard stale errors.",
    "On reconnect: replay pending task outcomes; extend generation token; don't fail active desktop tasks.",
    "- `gemini_live.py`",
    "- Simulated reconnect unit test",
    "**M**",
    "WS3 (P2)",
))

# --- C. Tools (9) ---
add("tools", 1, "registry-expansion", brief(
    "Lane C01: Launch Registry Expansion",
    "tools",
    "[`reliability/10-launch-registry-gaps.md`](../../subagent-storm/reliability/10-launch-registry-gaps.md); [`windows-automation-research/03-universal-launch.md`](../../windows-automation-research/03-universal-launch.md).",
    "- `_KNOWN_LAUNCH_APPS` dict in `tools.py`\n- 7 curated apps",
    "Spotify, Settings, Edge, etc. miss exact-match registry.",
    "Expand to 50+ entries; alias map; fallback to `resolve_launch_target` for unknown names.",
    "- `app/tools.py`\n- `data/launch_registry.json` optional",
    "- `tests/test_desktop_launcher.py`",
    "**M**",
    "WS1",
))

add("tools", 2, "resolve-launch-target", brief(
    "Lane C02: `resolve_launch_target`",
    "tools",
    "[`proposals/01-resolve-launch-target.md`](../../subagent-storm/proposals/01-resolve-launch-target.md).",
    "Not implemented; `detect_app_launch_intent` only exact dict lookup.",
    "No URI/shell/start ladder.",
    "Implement ladder: ms-settings → shell:AppsFolder → start command → web URL; return LaunchPlan struct.",
    "- `app/tools.py` or `app/launch.py`",
    "- Unit tests per ladder tier (mocked subprocess)",
    "**L**",
    "WS1",
))

add("tools", 3, "open-settings-tool", brief(
    "Lane C03: `open_settings` Tool",
    "tools",
    "[`proposals/03-open-settings-tool.md`](../../subagent-storm/proposals/03-open-settings-tool.md).",
    "No dedicated settings URI tool.",
    "Agent guesses settings paths; fails on UIA.",
    "Tool `open_settings(page: enum)` → `start ms-settings:display` etc.; map voice intents to URIs.",
    "- `app/tools.py`\n- Live declaration",
    "- URI mapping tests",
    "**S**",
    "WS1",
))

add("tools", 4, "uia-cache-mvp", brief(
    "Lane C04: UIA Tree Cache MVP",
    "tools",
    "[`proposals/02-uia-tree-cache.md`](../../subagent-storm/proposals/02-uia-tree-cache.md).",
    "- `_uia_find_cache` on ToolExecutor (`tools.py:508`)\n- Per-session dict",
    "Cache not shared across tools; no TTL; full tree walks on hot paths.",
    "MVP: hwnd-keyed cache, 2s TTL, invalidate on focus change; wire into `uia_click` tier-1.",
    "- `app/tools.py`",
    "- Benchmark test optional",
    "**M**",
    "WS6 Back Office Tools",
))

add("tools", 5, "playbook-wiring", brief(
    "Lane C05: Adaptive Playbook Wiring",
    "tools",
    "[`proposals/06-playbook-wiring.md`](../../subagent-storm/proposals/06-playbook-wiring.md); [`backoffice/06-adaptive-windows-playbooks.md`](../../subagent-storm/backoffice/06-adaptive-windows-playbooks.md).",
    "- `adaptive_windows.py` playbooks exist\n- Manual agent selection",
    "Playbooks not auto-selected from window class.",
    "On `observe_window`, attach playbook hints to agent prompt; auto-call playbook steps before generic UIA.",
    "- `app/adaptive_windows.py`\n- `app/agent.py`",
    "- `tests/test_adaptive_windows.py`",
    "**M**",
    "WS6",
))

add("tools", 6, "web-search-fix", brief(
    "Lane C06: `web_search` Fix",
    "tools",
    "[`logs/07-web-search-failures.md`](../../subagent-storm/logs/07-web-search-failures.md).",
    "- Live `web_search` in `textbox_overlay._live_web_search` (~2608)\n- ~75% fail rate in logs",
    "SSRF guards, empty query, provider errors surfaced poorly.",
    "Validate query non-empty; retry once; return `sources` + summary; honest failure message; consider Google Search tool when `GEMINI_LIVE_SEARCH=1`.",
    "- `textbox_overlay.py`\n- `app/providers.py`",
    "- `tests/test_ssrf_guards.py`",
    "**M**",
    "WS5",
))

add("tools", 7, "ocr-mid-tier-live", brief(
    "Lane C07: Live Mid-Tier OCR",
    "tools",
    "[`proposals/04-live-mid-tier-ocr.md`](../../subagent-storm/proposals/04-live-mid-tier-ocr.md).",
    "Full vision describe for every peek; no OCR shortcut in Live path.",
    "Slow + hallucination-prone for simple text reads.",
    "Add OCR pass in `look_at_screen` before vision model; return text if confidence > threshold.",
    "- `textbox_overlay.py`\n- `app/providers.py`",
    "- `tests/test_hybrid_resolver.py` patterns",
    "**M**",
    "WS2",
))

add("tools", 8, "wait-for-window-fuzzy-match", brief(
    "Lane C08: `wait_for_window` Fuzzy Match",
    "tools",
    "[`logs/03-failed-wait-for-window.md`](../../subagent-storm/logs/03-failed-wait-for-window.md).",
    "- Agent tool `wait_for_window` exact title match",
    "Fails on \"Spotify Premium\" vs \"Spotify\", localized titles.",
    "Normalize titles; substring + Levenshtein; configurable timeout; return best match hwnd.",
    "- `app/tools.py`",
    "- Unit tests with title pairs",
    "**S**",
    "WS6",
))

add("tools", 9, "detect-app-launch-intent", brief(
    "Lane C09: `detect_app_launch_intent` Hardening",
    "tools",
    "Storm reliability/10; `tools.py:471-488`.",
    "Regex verb match + exact registry only.",
    "\"Open Spotify and play\" correctly rejected but \"open spotify\" fails if not in dict.",
    "After registry expansion, add fuzzy app name match; telemetry on None returns.",
    "- `app/tools.py`",
    "- `tests/test_fast_path.py`",
    "**S**",
    "WS1",
))

# --- D. Back office (9) ---
add("backoffice", 1, "agent-py-prompt-conflict", brief(
    "Lane D01: `agent.py` Prompt Conflicts",
    "backoffice",
    "[`backoffice/01-agent-py-prompt-review.md`](../../subagent-storm/backoffice/01-agent-py-prompt-review.md).",
    "- System prompt sections for computer vs coding vs browser\n- Tool list in prompt may disagree with actual tools",
    "Conflicting instructions cause wrong tool choice (web_search vs UIA).",
    "Audit prompt blocks; single source of truth from tool registry; remove duplicate LAUNCH guidance.",
    "- `app/agent.py`",
    "- Snapshot prompt hash test",
    "**M**",
    "WS6",
))

add("backoffice", 2, "uia-sequence-grid-integration", brief(
    "Lane D02: `uia_click_sequence` + Grid Integration",
    "backoffice",
    "[`backoffice/03-tools-uia-sequence-review.md`](../../subagent-storm/backoffice/03-tools-uia-sequence-review.md); [`05-grid-locate-improvements.md`](../../subagent-storm/backoffice/05-grid-locate-improvements.md).",
    "- `uia_click_sequence` orchestration\n- `grid_locate.py` vision tier",
    "Sequence aborts don't report which step failed; grid not used in sequence fallback.",
    "Per-step HandoffResult; on UIA miss in sequence, try grid for that step only.",
    "- `app/tools.py`\n- `app/grid_locate.py`",
    "- `tests/test_grid_locate.py`",
    "**M**",
    "WS6",
))

add("backoffice", 3, "history-persistence", brief(
    "Lane D03: Agent History Persistence",
    "backoffice",
    "backoffice/04-main-task-lifecycle; agent loop memory.",
    "- In-memory task log in agent run\n- `tasks/*.json` partial history",
    "Long tasks lose context on reconnect; Live can't inspect steps.",
    "Persist action log to task record every N steps; expose via GET for forensics.",
    "- `app/agent.py`\n- `app/main.py`",
    "- State store tests",
    "**M**",
    "WS6",
))

add("backoffice", 4, "done-validation", brief(
    "Lane D04: Done / Complete Validation",
    "backoffice",
    "[`logs/08-complete-honesty-patterns.md`](../../subagent-storm/logs/08-complete-honesty-patterns.md).",
    "- `_task_complete_from_log` in `main.py`\n- Agent `complete` tool",
    "Ultra-short tasks (≤6 lines) false-complete.",
    "Minimum step count OR explicit verify action before `complete: true`; skepticism for launch-only goals.",
    "- `app/agent.py`\n- `app/main.py`",
    "- `tests/test_finish_reason.py`",
    "**M**",
    "WS6",
))

add("backoffice", 5, "build-task-payload", brief(
    "Lane D05: `build_task_payload`",
    "backoffice",
    "[`backoffice/09-task-payload-build-review.md`](../../subagent-storm/backoffice/09-task-payload-build-review.md).",
    "- `_build_task_payload` in overlay\n- POST body schema",
    "TASK: prefix added inconsistently; metadata missing mode.",
    "Single builder function; fields: user_goal, prompt_goal, mode, source=live, parent_session_id.",
    "- `textbox_overlay.py`\n- `main.py`",
    "- Payload contract tests",
    "**S**",
    "WS3",
))

add("backoffice", 6, "adaptive-playbooks-happy-path", brief(
    "Lane D06: Adaptive Playbooks Happy Path",
    "backoffice",
    "[`backoffice/06-adaptive-windows-playbooks.md`](../../subagent-storm/backoffice/06-adaptive-windows-playbooks.md).",
    "- Calculator, Notepad playbooks in `adaptive_windows.py`",
    "Happy path not wired; agent rediscovers UI each time.",
    "Document + implement happy path for Calculator e2e (live-test-plan/04); playbook-first routing.",
    "- `app/adaptive_windows.py`\n- `app/agent.py`",
    "- `tests/test_adaptive_windows.py`",
    "**M**",
    "WS6",
))

add("backoffice", 7, "electron-unlock-guard", brief(
    "Lane D07: `electron_unlock` Guard",
    "backoffice",
    "[`reliability/09-electron-unlock-disruption.md`](../../subagent-storm/reliability/09-electron-unlock-disruption.md).",
    "- Electron unlock relaunch path\n- Disrupts in-flight tasks",
    "Cursor/Electron tasks fail mid-sequence.",
    "Defer unlock if desktop task active; queue unlock request; warn Live via handoff.",
    "- `app/tools.py` or electron helper\n- `textbox_overlay.py`",
    "- Mock active task guard",
    "**S**",
    "WS6",
))

add("backoffice", 8, "main-task-lifecycle", brief(
    "Lane D08: `main.py` Task Lifecycle",
    "backoffice",
    "[`backoffice/04-main-task-lifecycle-review.md`](../../subagent-storm/backoffice/04-main-task-lifecycle-review.md); proposals/05.",
    "- Spawn, poll, serialize, abandon, queue (`main.py`)\n- Watchdog `_TASK_MAX_RUNTIME`",
    "Complex state machine; GET side effects persist terminal.",
    "State diagram doc + reduce persist-on-GET; explicit transitions only via agent completion.",
    "- `app/main.py`",
    "- `tests/test_task_abandon_grace.py`\n- `tests/test_stream_terminal.py`",
    "**L**",
    "WS3",
))

add("backoffice", 9, "desktop-control-route", brief(
    "Lane D09: Desktop Control Route",
    "backoffice",
    "[`backoffice/08-desktop-control-route-review.md`](../../subagent-storm/backoffice/08-desktop-control-route-review.md).",
    "- `_desktop_control_route` (`textbox_overlay.py:1761`)\n- `_parse_single_click_goal` redirect",
    "Escalation vs double-routing confusion in logs.",
    "Tag telemetry `route=intentional_escalation`; single model-facing tool response.",
    "- `textbox_overlay.py`",
    "- Route decision unit tests",
    "**S**",
    "WS2",
))

# --- E. Live test plan (7) ---
add("live-test-plan", 1, "browser-agent-scenarios", brief(
    "Lane E01: Phase 3 Browser Agent Scenarios",
    "live-test-plan",
    "LOAD-TEST-PLAN; browser specialist lane A06.",
    "Scripts: `scripts/live_tool_smoke.py`, `tests/test_browser_plugin.py` (offline).",
    "No Live browser E2E script.",
    "Scenarios: (1) open example.com read title (2) form fill with consent (3) search result citation. Env: `GEMINI_API_KEY`, `ORYNN_LABEL_LOG=1`. Success: handoff summary spoken, no raw DOM in bubble.",
    "- `scripts/live_browser_matrix.py` (new in Phase 3)",
    "Manual Phase 3; 1 agent sequential",
    "**M**",
    "Phase 3 only",
))

add("live-test-plan", 2, "gemini-live-complex-tasks", brief(
    "Lane E02: Gemini Live Complex Tasks",
    "live-test-plan",
    "LOAD-TEST-PLAN; logs/04-ultra-short-tasks.",
    "`scripts/live_qa_matrix.py` exists.",
    "Complex multi-app flows untested systematically.",
    "Matrix: Notepad poem, Settings display page, file save dialog. Criteria: task duration >10s, terminal honest, no double-route in labels.",
    "- Runbook in Phase 3",
    "1 Live agent, sequential",
    "**L**",
    "Phase 3",
))

add("live-test-plan", 3, "spotify-style-launch", brief(
    "Lane E03: Spotify-Style Launch",
    "live-test-plan",
    "[`reliability/05-spotify-failure-postmortem.md`](../../subagent-storm/reliability/05-spotify-failure-postmortem.md).",
    "Failed task `clicky-c6beede9be`; label log lines ~3138-3279.",
    "P0 regression scenario.",
    "Script: speak \"open Spotify\"; assert no bubble leak <1s; window foreground within 15s OR honest failure spoken. Compare textbox_labels before/after fix.",
    "- `ORYNN_LABEL_LOG=1`",
    "Phase 3 gate test",
    "**S**",
    "Phase 3 P0",
))

add("live-test-plan", 4, "calculator-e2e", brief(
    "Lane E04: Calculator E2E",
    "live-test-plan",
    "[`logs/09-calculator-e2e-success.md`](../../subagent-storm/logs/09-calculator-e2e-success.md).",
    "Success tasks `clicky-f65730807f`.",
    "Reproducible win path documented but not scripted.",
    "\"Open calculator and compute 17*23\" — success = result visible or spoken 391. Use adaptive playbook.",
    "- Phase 3 script",
    "Golden live test",
    "**M**",
    "Phase 3",
))

add("live-test-plan", 5, "vision-peek-scenarios", brief(
    "Lane E05: Vision Peek Scenarios",
    "live-test-plan",
    "reliability/08; `scripts/live_vision_smoke.py`.",
    "Vision smoke script exists.",
    "Scenarios: read error dialog, describe foreground window, refuse to click when asked read-only.",
    "- `scripts/live_vision_smoke.py`",
    "- Phase 3 runbook section",
    "Manual smoke per scenario",
    "**S**",
    "Phase 3",
))

add("live-test-plan", 6, "live-harness-env-setup", brief(
    "Lane E06: Live Harness Env Setup",
    "live-test-plan",
    "LOAD-TEST-PLAN; textbox_overlay ORYNN_LABEL_LOG.",
    "- `ORYNN_LABEL_LOG=1` → `logs/textbox_labels.jsonl`\n- `debug-eec63b.log` NDJSON",
    "Env vars scattered.",
    "Document bundle: `ORYNN_LABEL_LOG=1`, `GEMINI_LIVE_TOOL_TIMEOUT`, `ORYNN_TASK_START_GRACE`, log paths, tail commands PowerShell.",
    "- `docs/implementation-storm/phase1-research/live-test-plan/ENV.md` optional Phase 3",
    "Checklist",
    "**S**",
    "Phase 3 prep",
))

add("live-test-plan", 7, "load-test-matrix-phase3", brief(
    "Lane E07: Phase 3 Load Test Matrix",
    "live-test-plan",
    "[`LOAD-TEST-PLAN.md`](../../subagent-storm/LOAD-TEST-PLAN.md).",
    "Full stress plan exists.",
    "Needs mapping to post-implementation features.",
    "10-run matrix: launch, click, task, vision, web_search — record pass/fail + log bundle per run.",
    "- Spreadsheet template; LOAD-TEST-PLAN cross-ref",
    "10-run sequential matrix",
    "**M**",
    "Phase 3",
))

# --- F. Log forensics (7) ---
add("log-plan", 1, "textbox-labels-jsonl-patterns", brief(
    "Lane F01: `textbox_labels.jsonl` Patterns",
    "log-plan",
    "[`logs/05-textbox-labels-live-session.md`](../../subagent-storm/logs/05-textbox-labels-live-session.md).",
    "Fields: timestamp, label, source, disposition, reason, live_running.",
    "Phase 4 needs pattern catalog.",
    "Checklist: grep `muted`+`task_outcome_under_live`; `live_tool` with `Failed:`; `Started:` without completion; correlate with task_id.",
    "- `logs/textbox_labels.jsonl`",
    "Phase 4 agent playbook per pattern",
    "**S**",
    "Phase 4",
))

add("log-plan", 2, "debug-log-slices", brief(
    "Lane F02: Debug Log Slices",
    "log-plan",
    "[`logs/01-debug-tool-mix.md`](../../subagent-storm/logs/01-debug-tool-mix.md).",
    "NDJSON hypotheses A,D,E,F in gemini_live.",
    "Tool mix ratios baseline undocumented for post-fix comparison.",
    "Slice by session id; count tools per turn; flag dual desktop tools.",
    "- `debug-eec63b.log`; Phase 4 slice scripts",
    "Agent playbook per session",
    "**S**",
    "Phase 4",
))

add("log-plan", 3, "task-json-correlation", brief(
    "Lane F03: Task JSON Correlation",
    "log-plan",
    "tasks/*.json mining across storm.",
    "TaskRecord fields: goal, status, reason, timestamps.",
    "No automated join between label stream and task artifacts.",
    "Join task_id from label log → task JSON; verify duration vs reason.",
    "- `tasks/`; correlation script (Phase 4)",
    "Join label events to task JSON by task_id",
    "**S**",
    "Phase 4",
))

add("log-plan", 4, "silent-turns-forensics", brief(
    "Lane F04: Silent Turns Forensics",
    "log-plan",
    "[`logs/02-silent-turns-pattern.md`](../../subagent-storm/logs/02-silent-turns-pattern.md).",
    "turn_complete without output after tool result.",
    "User confusion after task done; no automated silent-turn detector.",
    "Detect: tool ok + no live_reply within 5s; check send_task_update fired.",
    "- debug log + labels; Phase 4 detection script",
    "Silent turn report per session",
    "**S**",
    "Phase 4",
))

add("log-plan", 5, "duplicate-routing-forensics", brief(
    "Lane F05: Duplicate Routing Forensics",
    "log-plan",
    "[`logs/06-duplicate-start-desktop-task.md`](../../subagent-storm/logs/06-duplicate-start-desktop-task.md).",
    "Duplicate spawns same goal in task JSON.",
    "Wasted tasks + race; no duplicate-goal metric.",
    "Count duplicate goals within 30s window; map to double-route batches.",
    "- debug + tasks; duplicate detector",
    "Duplicate spawn report",
    "**S**",
    "Phase 4",
))

add("log-plan", 6, "web-search-failure-forensics", brief(
    "Lane F06: Web Search Failure Forensics",
    "log-plan",
    "logs/07-web-search-failures.",
    "web_search tool exit codes in debug log.",
    "High fail rate (~75%) without failure taxonomy.",
    "Bucket failures: empty query, timeout, SSRF block, provider 4xx.",
    "- logs + tasks; failure bucket script",
    "Web search failure histogram",
    "**S**",
    "Phase 4",
))

add("log-plan", 7, "log-forensics-master-checklist", brief(
    "Lane F07: Log Forensics Master Checklist",
    "log-plan",
    "Consolidates F01-F06 for Phase 4.",
    "All log sources.",
    "Single Phase 4 entry point.",
    "Master checklist: (1) ingest bundle (2) label scan (3) debug slice (4) task join (5) P0 regression signatures (6) report template.",
    "- Phase 4 runbook",
    "5-10 forensics agents split by section",
    "**S**",
    "Phase 4",
))

# --- G. Tests (7) ---
add("tests", 1, "bubble-sanitization-test-map", brief(
    "Lane G01: Bubble Sanitization Test Map",
    "tests",
    "storm tests/01-gemini-live; reliability/03.",
    "- `test_quiet_companion.py`\n- `test_gemini_live.py`\n- `test_voice_and_env.py`",
    "Missing: sanitizer unit tests for denylist patterns.",
    "Add `test_bubble_sanitizer.py` with table cases from storm leak table.",
    "- `tests/test_bubble_sanitizer.py` (Phase 2)",
    "pytest offline",
    "**S**",
    "WS4",
))

add("tests", 2, "double-routing-test-map", brief(
    "Lane G02: Double Routing Test Map",
    "tests",
    "reliability/02; test_gemini_live.",
    "Batch gate tests partial.",
    "No test for launch+desktop_control batch.",
    "Extend test_gemini_live with multi-tool batches per exclusion group.",
    "- `tests/test_gemini_live.py`",
    "pytest",
    "**S**",
    "WS2",
))

add("tests", 3, "specialist-routing-test-map", brief(
    "Lane G03: Specialist Routing Test Map",
    "tests",
    "SYNTHESIS; test_mode_routing.",
    "- `test_mode_routing.py`",
    "No registry routing tests.",
    "When registry lands, add `test_specialist_registry.py`.",
    "- new test file",
    "pytest",
    "**M**",
    "WS2",
))

add("tests", 4, "launch-registry-test-map", brief(
    "Lane G04: Launch Registry Test Map",
    "tests",
    "storm tests/03-adaptive-fast; test_fast_path.",
    "- `test_fast_path.py`\n- `test_desktop_launcher.py`",
    "Spotify/URI cases missing.",
    "Add parametrized launch intents from registry expansion list.",
    "- above files",
    "pytest",
    "**S**",
    "WS1",
))

add("tests", 5, "golden-spotify-bubble-test", brief(
    "Lane G05: Golden Spotify Bubble Test",
    "tests",
    "reliability/05-spotify-failure-postmortem.",
    "No golden file from label log.",
    "Replay label sequence; assert mute + handoff.",
    "Fixture: `tests/fixtures/spotify_label_sequence.jsonl` + assertion helper.",
    "- new golden test",
    "pytest",
    "**M**",
    "WS4 + WS1",
))

add("tests", 6, "abandon-race-test-map", brief(
    "Lane G06: Abandon Race Test Map",
    "tests",
    "proposals/05; test_task_abandon_grace.",
    "- `test_task_abandon_grace.py`",
    "Grace edge cases partial.",
    "Add tests: 0ms poll, coroutine exception reason, no abandoned string.",
    "- extend existing",
    "pytest",
    "**S**",
    "WS3",
))

add("tests", 7, "pytest-coverage-gap-master", brief(
    "Lane G07: Pytest Coverage Gap Master",
    "tests",
    "storm tests/*.txt inventory.",
    "60 test files; P0 features partially covered.",
    "Master map: feature → test file → gap → priority.",
    "| Feature | Tests | Gap |\n| bubble mute | quiet_companion | sanitizer |\n| abandon | task_abandon_grace | GET persist |\n| launch | fast_path | URI |\n| grid | grid_locate | sequence |\n| live | gemini_live | specialist registry |",
    "- INDEX in tests/",
    "Run storm pytest txt after Phase 2",
    "**S**",
    "All WS",
))


def main():
    for subdir, filename, body in LANES:
        path = ROOT / subdir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        print(f"Wrote {path.relative_to(ROOT)}")
    print(f"Total: {len(LANES)} lanes")


if __name__ == "__main__":
    main()

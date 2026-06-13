# Orynn Frontend Redesign Bridge

This is the practical handoff between a visual redesign and the code that already exists. Use it when turning Claude Design output into a real Orynn UI. The goal is a premium Windows-agent workbench without breaking the agent, task stream, UIA controls, approvals, or native capsule.

## Current Surfaces

| Surface | Files | Role |
|---|---|---|
| Full dashboard | `static/index.html`, `static/app.js`, `static/style.css`, `static/dynamic.css`, `static/liquid-glass.css` | Main chat/workbench, task history, tool stream, settings, approvals, readiness, model controls. |
| Native floating capsule | `app/widget/qt_shell.py`, `app/widget/capsule_widgets.py` | Always-on-top Windows capsule, native widgets, task ticker, approvals/permissions, compact result cards. |
| Backend stream/API | `app/main.py`, `app/log_emitter.py`, `app/agent.py` | Task creation, SSE log stream, approvals, permissions, readiness, trust report, task logs. |
| Frontend regression tests | `tests/test_ui_static_hardening.py` | Static guards for important UI contracts and CSS/JS hooks. |

Do not treat the redesign as a new app. Treat it as a new skin and layout system over these existing state machines.

## Non-Negotiable Contracts

1. `static/app.js` owns the dashboard task lifecycle.
   It creates tasks, opens `/api/tasks/{task_id}/stream`, renders events, handles reconnect, and restores historical logs.

2. `app/widget/qt_shell.py` owns the native capsule lifecycle.
   It uses the same task stream but renders native Qt widgets rather than HTML cards. A dashboard redesign does not automatically update the capsule.

3. Approval and permission flows must stay wired.
   Dashboard calls `/api/approvals` and `/api/permissions`. Capsule emits native approval/permission widgets and also posts to those endpoints.

4. Desktop-control visual state must stay visible.
   The UI needs to show current control layer, target app/window, phase, and whether the agent is waiting, acting, recovering, done, or blocked.

5. Historical replay must still render.
   `loadTaskLog` replays prior task logs through `processTaskEvent`. New UI components must support both live and replayed events.

6. Compact mode is not optional.
   The floating capsule is the main product surface for many Windows tasks. Dashboard polish alone is incomplete.

## Dashboard DOM Anchors

These IDs/classes are the current integration anchors. A redesign can change markup, but only if `static/app.js` is updated at the same time.

| Existing anchor | Meaning |
|---|---|
| `#feed` | Main stream container for messages, status rows, tool cards, screenshots, widgets. |
| `#input`, `#send` | Composer input and send action. |
| `#task-history`, `#history-search` | Session history and filtering. |
| `#task-panel`, `#task-list` | Long-running todo/task panel rendered from `todos` events. |
| `#approval`, `#permission`, `#desktop-access`, `#readiness-preflight` | Blocking user-choice modals. |
| `#topbar-control`, `#topbar-control-layer` | Current desktop/control-layer indicator. |
| `#statusbar`, `#sb-status`, `#sb-model`, `#sb-budget` | Runtime status, model, budget. |
| `#vorb-root`, `#vpanel` | HTML capsule shell used in web/widget mode; native Qt capsule has separate implementation. |

## Event-To-Component Matrix

`processTaskEvent` in `static/app.js` is the dashboard renderer. These are the important event classes a new design must support.

| Event type | Current behavior | New design component |
|---|---|---|
| `task_created` | Initializes metadata, often suppressed in feed. | Task header/session metadata. |
| `status` | Updates live status card, stall messages, pause/resume notices. | Live status row or topbar activity ticker. |
| `agent`, `agent_delta`, `assistant_delta` | Streams assistant text into final chat message. | Assistant message with streaming cursor and actions. |
| `reasoning` | Usually collapsed into minimal thinking unless live. | Optional reasoning note inside work fold. |
| `plan` | Renders plan/review content. | Plan card or task timeline. |
| `subtask` | Updates subtask rows and worker tags. | Timeline item or task-panel row. |
| `action_start` | Creates/updates tool card, control surface, running state. | Tool call row, timeline step, control detail. |
| `action_result` | Marks tool OK/fail, appends output and overlay trace. | Tool result row with expandable details. |
| `desktop_control` | Shows desktop access enabled/disabled. | Windows context panel and trust state. |
| `control_profile` | Updates runtime/control profile. | Windows context panel. |
| `file_change`, `file_commit` | Shows changed file artifacts and revert control. | Artifact row plus post-run file summary. |
| `terminal_output` | Appends command output to tool details. | Terminal output drawer. |
| `browser_event` | Shows browser trace/artifact. | Browser event row. |
| `screenshot` | Adds screenshot preview/lightbox. | Screenshot artifact with preview. |
| `reflection` | Shows self-review/reflection. | Work fold note. |
| `todos` | Renders right-side task panel. | Goal/task timeline panel. |
| `token_usage`, `budget`, `usage_update` | Updates budget bar/history badges. | Token meter/statusbar chip. |
| `widget`, `ui_widget`, widget-specific events | Renders dynamic mini widgets. | Inline agent widget/card. |
| `provider_info` | Shows model/rate-limit/retry state. | Model status chip and retry notice. |
| `approval_required`, `permission_required` | Blocks with inline controls plus modal. | Confirmation prompt, inline and modal. |
| `approval_timeout`, `permission_timeout` | Marks trust request timed out. | Recovery/error panel. |
| `error`, `done`, `cancelled` | Terminal state, work folding, final answer/status. | Verified result, failure, or cancelled state. |

## Product Layout Target

The new dashboard should be a desktop workbench, not a chat toy.

Recommended regions:

1. Left rail: sessions, workspace, compact controls.
2. Center stream: user message, assistant message, collapsed work/timeline, verified result.
3. Right inspector: Windows context, current app, current control layer, task timeline, recent tool actions.
4. Bottom composer: prompt, mode/access/thinking controls, voice/tools, send.
5. Status strip: model, runtime, elapsed, tokens, connection state.

The current UI already has most of these pieces, but they are visually scattered and inconsistent. The redesign should unify them rather than add more panels.

## Reference Direction: Open Design

[`nexu-io/open-design`](https://github.com/nexu-io/open-design) is a strong reference because it frames the product as a quiet local studio rather than a busy chatbot. Useful patterns to adapt:

1. One-window studio metaphor.
   Use window tabs, a thin left rail, and a calm central workspace. Orynn should feel like a Windows control studio, not a pile of cards.

2. Centered command surface for idle state.
   Open Design's home screen makes the prompt the obvious first action, with mode chips underneath and recent projects below. Orynn can mirror this with task modes like Chat, Windows, Code, Browser, and Resume.

3. Artifact/editor split for active work.
   Studio mode uses a left conversation/source rail and a main preview/editor area. Orynn can use that pattern for live task work: left timeline/chat, center verified result or app context, right Windows inspector.

4. Calm density.
   Mostly neutral surfaces, restrained borders, small icons, and intentional whitespace. Orynn should use this restraint while preserving more operational density for tool traces.

5. Mode chips, not giant controls.
   Prototype, live artifact, slide deck, image, video, etc. map cleanly to Orynn's Computer, Browser, Code, Research, Automate, and Voice modes.

6. Recent work as cards.
   Recent projects are small, visual, and resumable. Orynn's task history should become compact resumable task/project cards rather than a plain log list.

Things not to copy directly:

- Open Design is artifact-generation-first. Orynn is live-control-first, so approvals, permissions, control layer, and recovery state need stronger visibility.
- Open Design can hide execution detail. Orynn must expose enough trace to trust Windows control.
- Open Design uses light studio calm by default. Orynn should support that, but keep a dark professional mode for long desktop sessions.

## Components To Design First

Design these before touching code:

1. `AppShell`
   Desktop window layout, titlebar, sidebar, center stream, inspector, composer, status strip.

2. `ChatMessage`
   User, assistant streaming, assistant final, system note.

3. `WorkFold`
   Collapsed "Worked for 23s" summary with timeline details.

4. `ToolRow`
   Running, success, failed, waiting, timed out. Must include tool/action name, target, control layer, duration, and expandable details.

5. `WindowsContextPanel`
   Current app/window, runtime layer, confidence, target control, recent observations, fallback/recovery state.

6. `GoalTimeline`
   Observe, plan, act, verify, recover. Supports subtask/worker rows.

7. `Composer`
   Dense input with access mode, thinking level, model/runtime chip, attachments/tools, voice, send.

8. `TrustPrompt`
   Approval, permission, desktop access, timeout/recovery.

9. `ResultPanel`
   Verified result, files changed, screenshots, logs, retry/revert/copy actions.

10. `Capsule`
   Native compact states: idle, context-ready, submitting, planning, acting, waiting approval, paused, done, error.

## Implementation Order

1. Freeze the event contract.
   Do not rename or remove task event handling while restyling.

2. Build dashboard tokens.
   Replace scattered CSS variables with a single token section for color, spacing, typography, borders, shadows, motion.

3. Reskin shell first.
   App background, sidebar, topbar, feed column, right inspector, composer, statusbar.

4. Reskin event components.
   Chat messages, status rows, tool rows, work fold, approvals, screenshots, widgets.

5. Wire the Windows context panel.
   Use existing `setControlSurface`, `setControlProfileSurface`, `desktop_control`, `action_start`, and `action_result` data. Do not invent a new backend.

6. Update the Qt capsule separately.
   Mirror the same tokens and state names in `qt_shell.py` and `capsule_widgets.py`.

7. Expand static tests.
   Add guards for the new anchors, states, and token names in `tests/test_ui_static_hardening.py`.

8. Run live UI checks.
   Test idle, streaming, tool success, tool failure, approval, permission, long-running goal, compact capsule.

## Claude Design Prompt Addendum

Attach or point Claude Design to:

- `static/index.html`
- `static/app.js`
- `static/style.css`
- `static/dynamic.css`
- `app/widget/qt_shell.py`
- `app/widget/capsule_widgets.py`
- this file

Tell Claude Design:

```text
The backend and stream event contract already exist. Do not invent new backend APIs.
Design the dashboard and compact capsule around the event-to-component matrix in docs/FRONTEND_REDESIGN_BRIDGE.md.
The implementation must be incremental and compatible with static/app.js and app/widget/qt_shell.py.
```

## Acceptance Checklist

A redesign is not ready until these pass:

- Idle/new chat looks intentional, not empty.
- A plain chat stream has polished user and assistant messages.
- A desktop task shows Windows context and control layer.
- A tool run shows running, success, failure, and expanded details.
- Approvals and permissions are unmistakable and keyboard accessible.
- A long-running task shows progress without flooding the feed.
- Completion shows a verified result or clear failure.
- Replaying an old task log looks the same as a live run.
- The native capsule has matching state language and visual quality.
- `python -m pytest tests/test_ui_static_hardening.py -q` passes.

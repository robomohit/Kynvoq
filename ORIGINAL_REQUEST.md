# Original User Request

## Initial Request — 2026-06-17T18:44:44-07:00

# Teamwork Project Prompt — Draft

> Status: Launched — Running teamwork multi-agent implementation
> Goal: Execute implementation via teamwork_preview

Improve the end-to-end reliability of Orynn, a voice-controlled desktop AI agent, so that user-facing actions (clicks, typing, task execution, voice interaction) succeed consistently and recover gracefully from failures.

Working directory: `c:\Users\ACER\Desktop\Ai_computer\Orynn`

---

## Technical Specifications & Requirements

### R1. Gemini Live Connection Robustness & Autoreconnect
- **Target File**: [gemini_live.py](file:///c:/Users/ACER/Desktop/Ai_computer/Orynn/app/widget/gemini_live.py)
- **Problem**: The connection loop in `_run` retries only up to 5 times (exponential backoff capped at 10s, total time ~25s) before propagating the exception, stopping the session, and turning Gemini Live off permanently. If a user experiences a brief internet dropout, Orynn goes offline.
- **Solution**:
  - Implement a persistent reconnection policy that retries indefinitely (or for a long period like 10-15 minutes, e.g. 100+ retries) when connection drops.
  - Reconnection backoff should be capped (e.g. 15-30s) so it continues checking periodically.
  - The connection loop should only terminate if `self._stop.is_set()` is explicitly True (representing a user-requested shutdown).
  - Clear any stale audio/input queues on a successful reconnection to prevent audio backlog bursts.

### R2. UIA Click & Type Verification and Self-Healing
- **Target Files**: [tools.py](file:///c:/Users/ACER/Desktop/Ai_computer/Orynn/app/tools.py) and [desktop_features.py](file:///c:/Users/ACER/Desktop/Ai_computer/Orynn/app/widget/desktop_features.py)
- **Problem**: 
  - `uia_click` calls `_verify_clicked` but returns `ToolResult(ok=True)` even if `verified` is False (silent click failure). The agent thinks it succeeded when the click actually bounced or was ignored.
  - When `uia_type` ValuePattern SetValue fails to trigger React event listeners (e.g., Discord inputs), it falls back to clipboard paste. If clipboard paste fails, it falls back to literal typing, which is prone to character drops on slow apps.
- **Solution**:
  - In `uia_click`, if the click is not verified (e.g., `_verify_clicked` returns None or does not prove UI change, and the control had an active click effect), verify if we should perform a retry using alternative activation (like focusing the window, scrolling, or falling back to OCR-based coordinate click) before returning `ok=True`.
  - In `uia_type`, if clipboard access is temporarily blocked (e.g. by another app), retry clipboard access a few times with small delays rather than failing instantly back to slow keystrokes.
  - Ensure that UIA element resolution (`find_ui_element`) is resilient to slow-loading windows by introducing brief auto-retry waits (e.g., up to 1-2 seconds with 200ms intervals) if the target app is running but the window tree is temporarily empty.

### R3. Resilient Overlay State Tracking
- **Target File**: [textbox_overlay.py](file:///c:/Users/ACER/Desktop/Ai_computer/Orynn/app/widget/textbox_overlay.py)
- **Problem**: When a background task is running, the overlay tracks its status. However, if the backend server (`app/main.py`) restarts, crashes, or is unreachable, the overlay's poll thread catches an exception, updates the label to "Waiting for Orynn", but leaves `self._active_task_running = True` and the cursor state in "thinking". The UI gets stuck in a thinking state forever.
- **Solution**:
  - In `_poll_loop`'s exception handler, track connection failure count. If it fails consecutively (e.g. 3+ times), reset the task state: set `self._active_task_running = False`, `self._active_task_goal = ""`, and emit `"idle"` cursor state.
  - Validate that the overlay's task tracking state syncs correctly with `/api/active-tasks` at startup and after server recovery.

### R4. Unified LLM API Timeout & Retry Resilience
- **Target File**: [providers.py](file:///c:/Users/ACER/Desktop/Ai_computer/Orynn/app/providers.py)
- **Problem**: API calls to external LLM providers (Google, Groq, OpenRouter) can fail due to rate limits (429), server errors (5xx), or transport timeouts. Only Google provider (`_chat_google`) has custom retry loops; OpenRouter/Groq do not have matching resilient retry handlers.
- **Solution**:
  - Standardize retry behavior across all provider calls (`_chat_groq`, `_chat_openrouter`, etc.) with exponential backoff retries for status codes `429`, `408`, and `5xx` and generic connection errors.
  - Log helpful warning messages to the client logs during retries to prevent the user from thinking the app is dead.

---

## Acceptance Criteria

- [ ] Gemini Live stays in a "reconnecting" state and automatically reconnects when the network recovers, rather than shutting down.
- [ ] Clicks that do not register or verify trigger an active self-healing fallback (e.g., re-focus window, retry click, or fallback to OCR coordinate click) before reporting completion.
- [ ] Textbox overlay UI recovers gracefully to an "idle" cursor/state if the backend server crashes, restarts, or is briefly offline, and resumes task tracking once online.
- [ ] All LLM providers handle rate limits and temporary connection dropouts transparently via unified retry/backoff logic.

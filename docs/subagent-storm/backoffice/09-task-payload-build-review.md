# Task Payload Build Review — `build_task_payload`

**File:** `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\widget\textbox_overlay.py`  
**Reviewed:** 2026-06-22  
**Scope:** `build_task_payload`, helpers `_detect_mode`, `_strip_hardening`, constants `DESKTOP_HARDENING`, `VOICE_BREVITY`, and call sites.

---

## 1. Summary

`build_task_payload(goal: str) -> dict[str, Any]` is the **single client-side contract** for floating-bubble task submission (push-to-talk voice and Gemini Live `start_desktop_task`). It transforms a raw user utterance into the JSON body posted to `/api/tasks/preflight` and `/api/tasks`.

It is **not** used by the dashboard (`static/app.js` builds its own payload with history, skills, project folder, etc.). Scripts (`golden_voice_e2e.py`, `live_open_notepad.py`, etc.) import it to mirror the real voice path.

---

## 2. Implementation

```539:573:C:\Users\ACER\Desktop\Ai_computer\Orynn\app\widget\textbox_overlay.py
def build_task_payload(goal: str) -> dict[str, Any]:
    mode = _detect_mode(goal)
    # A pure "open/launch/switch to <known app>" command runs the deterministic
    # fast-path server-side (no LLM), so keep its goal RAW — prepending the long
    # desktop-hardening prompt or the voice-brevity note would only bloat it (and
    # the hardening prompt is what once pushed the goal past the 2000-char cap).
    try:
        from app.tools import detect_app_launch_intent
        is_app_launch = detect_app_launch_intent(goal) is not None
    except Exception:
        is_app_launch = False
    payload_goal = goal
    if not is_app_launch:
        try:
            from app import knowledge
            mem = knowledge.as_prompt_block(goal, limit=12)
            if mem:
                payload_goal = mem + "\n\n" + payload_goal
        except Exception:
            pass
        if mode in {"computer", "computer_use", "computer_isolated"}:
            payload_goal = DESKTOP_HARDENING + payload_goal
        payload_goal = payload_goal + VOICE_BREVITY
    width, height = _screen_size()
    return {
        "task_id": "clicky-" + secrets.token_hex(5),
        "goal": payload_goal,
        "mode": mode,
        "screen_width": width,
        "screen_height": height,
        "autonomy_level": "autonomous",
        "thinking_budget": "off",
    }
```

### 2.1 Goal transformation pipeline

| Step | Condition | Effect |
|------|-----------|--------|
| Mode detect | Always (on raw `goal`) | `_detect_mode(goal)` |
| App-launch check | Always (on raw `goal`) | `detect_app_launch_intent(goal)` |
| Memory inject | `not is_app_launch` | `knowledge.as_prompt_block(goal, limit=12)` prepended |
| Desktop hardening | `not is_app_launch` AND mode ∈ `{computer, computer_use, computer_isolated}` | `DESKTOP_HARDENING` prepended (~1.7 KB) |
| Voice brevity | `not is_app_launch` | `VOICE_BREVITY` appended (~200 chars) |
| **Fast-path branch** | `is_app_launch` | Goal left **completely raw** (no memory, hardening, or brevity) |

### 2.2 Output fields

| Field | Value | Notes |
|-------|-------|-------|
| `task_id` | `"clicky-" + secrets.token_hex(5)` | Matches `TASK_ID_PATTERN`; distinct from dashboard IDs (`Math.random().toString(36).slice(2)`) |
| `goal` | Transformed or raw | Posted to server; fast-path detection in `agent.py` runs on this string |
| `mode` | From `_detect_mode` | See §3.1 |
| `screen_width` / `screen_height` | Primary Qt screen or `1280×800` | Requires `QGuiApplication` |
| `autonomy_level` | `"autonomous"` | No approval popups; Live consent handled upstream |
| `thinking_budget` | `"off"` | Fixed for bubble surface |

**Omitted** (rely on server defaults): `model`, `isolated_app`, `active_skills`, `project_folder`, `history`, `plan_first`, `notify_on_completion`, `auto_commit`.

Callers may add `readiness_override: true` after preflight.

---

## 3. Helper behavior

### 3.1 `_detect_mode` — mode collapse

```493:506:C:\Users\ACER\Desktop\Ai_computer\Orynn\app\widget\textbox_overlay.py
def _detect_mode(goal: str) -> str:
    try:
        from app.providers import detect_task_mode
        detected = detect_task_mode(goal)
    except Exception:
        detected = "auto"
    if detected in {"computer", "computer_isolated"}:
        return "computer"
    if detected == "computer_use":
        return "computer_use"
    if detected == "coding":
        return "coding"
    return "auto"
```

- `computer_isolated` from `detect_task_mode` is **always emitted as `computer`**.
- `chat` from `detect_task_mode` becomes **`auto`** (not `chat`).
- Failures in `detect_task_mode` fall back to `"auto"`.

### 3.2 `_strip_hardening` — display inverse

Strips `DESKTOP_HARDENING` prefix and `VOICE_BREVITY` suffix so UI labels never echo injected prompts. Paired with `build_task_payload`; tested in `test_voice_brevity_appended_but_stripped_from_labels`.

### 3.3 Constants

- **`DESKTOP_HARDENING`** (lines 24–62): UIA-first desktop control instructions, ends with `"TASK: "`.
- **`VOICE_BREVITY`** (lines 520–525): Reply-format constraint for on-screen popup (plain text, ~200 chars).

---

## 4. Call sites

| Location | Path | Notes |
|----------|------|-------|
| Push-to-talk | `_submit_voice_task` (~3200) | `build_task_payload(transcript)` → preflight → POST |
| Live tool | `_live_start_desktop_task` (~2466) | Same; consent gate runs on **raw** goal before build |
| Scripts | `golden_voice_e2e.py`, `live_*.py`, `live_task_batch.py` | E2E / manual canaries |

Both call sites send a **subset** of the payload to preflight (`goal`, `mode`, `model`, `isolated_app`) — fields not in `build_task_payload` are `null`/omitted.

---

## 5. Server coupling

### 5.1 Schema (`TaskIn` in `main.py`)

- `goal` max length **8000** (raised from 2000 after 2026-06-16 regression).
- Request body guard: **10 KB** (`limit_request_size` middleware).
- Regression tests pin multi-step desktop + long dictated commands under the cap.

### 5.2 Deterministic fast-path (`agent.py` ~1761)

```python
if mode in ("computer", "auto"):
    _launch = detect_app_launch_intent(goal)
```

Server re-runs `detect_app_launch_intent` on the **posted goal**. For pure app launches, client keeps goal raw so detection still matches. For wrapped goals, extra steps correctly yield `None` and fall through to the planner.

---

## 6. Test coverage

| Test | File | What it pins |
|------|------|--------------|
| `test_voice_brevity_appended_but_stripped_from_labels` | `test_voice_and_env.py` | Brevity in payload, stripped in UI |
| `test_voice_desktop_payload_fits_task_schema` | `test_voice_and_env.py` | Hardening + long commands validate as `TaskIn` |
| `test_app_launch_payload_is_unwrapped` | `test_voice_and_env.py` | Pure launch = raw goal; multi-step = hardening |
| `test_detect_app_launch_intent` | `test_voice_and_env.py` | Intent detector contract |
| `test_open_app_uses_deterministic_fast_path_no_llm` | `test_fast_path.py` | Server fast-path with raw `"open notepad"` |
| Static pin | `test_ui_static_hardening.py` | `build_task_payload` and `DESKTOP_HARDENING + payload_goal` present |

**Manual:** `scripts/golden_voice_e2e.py` — full spoken middle path documented in `GOLDEN_FIVE.md`.

---

## 7. Findings

### 7.1 Strengths

1. **Correct fast-path ordering** — App-launch detection runs on the raw goal **before** memory/hardening/brevity; avoids breaking `detect_app_launch_intent` and keeps payloads small for known-app opens.
2. **Regression-aware design** — Comments and tests document the 2000→8000 char cap fix and the hardening bloat bug.
3. **Symmetric strip helper** — `_strip_hardening` keeps injected prompts out of user-visible labels.
4. **Bubble-appropriate defaults** — `autonomous` + `thinking_budget: off` match the product model (hotkey stop, Live consent upstream).
5. **Shared E2E surface** — Exported as a module function so scripts exercise the same path as voice.

### 7.2 Issues / risks

| ID | Severity | Finding |
|----|----------|---------|
| F1 | **Low** | **Dead branch:** `_detect_mode` never returns `computer_isolated`, but hardening checks `mode in {..., "computer_isolated"}`. Harmless but misleading. |
| F2 | **Medium** | **`computer_isolated` semantics lost:** Goals like “in Excel add a sum” may be detected as isolated server-side, but payload mode is always `computer`. No `isolated_app` is set. Overlay may not get isolated-window targeting the dashboard can request. |
| F3 | **Low** | **`chat` → `auto`:** Informational mode from `detect_task_mode` is discarded. Routing still works via goal text, but mode-specific server behavior may differ from explicit `chat`. |
| F4 | **Low** | **Silent `except` blocks** on `detect_app_launch_intent` and `knowledge.as_prompt_block` — import/runtime failures skip memory and may mis-classify launches without logging. |
| F5 | **Low** | **No `history`:** Voice/Live tasks are always single-turn from the API’s perspective; multi-turn bubble chat is not supported through this builder. |
| F6 | **Info** | **Memory skipped on pure launch:** Intentional for fast-path purity; user facts are not injected for `"open notepad"`. |
| F7 | **Info** | **Qt dependency for screen size:** `_screen_size()` needs `QGuiApplication`; tests set `QT_QPA_PLATFORM=offscreen`. Headless import without Qt may still get `1280×800` fallback. |
| F8 | **Info** | **Dashboard divergence:** Dashboard sends richer payloads (history, skills, project folder, user-selected autonomy). Overlay path is intentionally narrower. |

### 7.3 Historical bug (resolved)

**2026-06-16:** Hardening + brevity on `"open notepad"` produced a ~2041-char goal against `TaskIn.goal` max 2000 → HTTP 422, bubble showed “Couldn't start task.” Fixed by (a) raw goal for pure launches and (b) raising cap to 8000. Documented in `GOLDEN_FIVE.md` and pinned by tests.

---

## 8. Data-flow diagram

```
Raw goal (voice / Live)
        │
        ▼
  _detect_mode(goal) ──────────────────────────► payload.mode
        │
        ▼
  detect_app_launch_intent(goal)?
        │
   yes ─┴─► goal unchanged ─────────────────────► payload.goal
        │
   no  ─┬─► knowledge.as_prompt_block (prepend)
        ├─► DESKTOP_HARDENING (if desktop mode)
        └─► VOICE_BREVITY (append) ──────────────► payload.goal
        │
        ▼
  _screen_size() ───────────────────────────────► screen_width/height
        │
        ▼
  { task_id, goal, mode, screen_*, autonomy_level, thinking_budget }
        │
        ├─► POST /api/tasks/preflight (subset)
        └─► POST /api/tasks (+ readiness_override?)
                │
                ▼
         agent.run_task → detect_app_launch_intent(goal) fast-path OR planner
```

---

## 9. Recommendations

1. **Remove or document dead `computer_isolated` in hardening guard** — Either have `_detect_mode` return `computer_isolated` when appropriate, or drop it from the hardening set.
2. **Consider isolated mode for overlay** — If bubble users say “in Calculator …”, evaluate passing through `computer_isolated` + `isolated_app` from `infer_isolated_app_name(goal)`.
3. **Log swallowed exceptions** — At debug level when `detect_app_launch_intent` or `knowledge` fails, to aid diagnosis without breaking submission.
4. **Keep cap tests when editing `DESKTOP_HARDENING` or `VOICE_BREVITY`** — Any growth affects `test_voice_desktop_payload_fits_task_schema` and the 10 KB middleware limit.
5. **Do not rename to `_build_task_payload`** — It is intentionally public (imported by scripts and tests).

---

## 10. Related files

| Path | Role |
|------|------|
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\widget\textbox_overlay.py` | `build_task_payload`, constants, call sites |
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\tools.py` | `detect_app_launch_intent` |
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\providers.py` | `detect_task_mode`, `infer_isolated_app_name` |
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\knowledge.py` | `as_prompt_block` |
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\agent.py` | Server fast-path |
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\main.py` | `TaskIn`, `TaskPreflightIn`, size limits |
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\tests\test_voice_and_env.py` | Primary contract tests |
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\GOLDEN_FIVE.md` | E2E / regression narrative |

---

## 11. Verdict

`build_task_payload` is **well-scoped and regression-tested** for the voice/bubble submission path. The fast-path raw-goal branch is the critical design choice and is correctly ordered relative to wrapping. Main gaps are **mode fidelity** (`computer_isolated` / `chat` collapsed) and **silent exception handling** — neither is known to break the golden voice path today, but they are worth tracking if overlay behavior is extended toward dashboard parity.

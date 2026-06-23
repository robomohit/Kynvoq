# Explorer Analysis Report: Orynn Resilient Desktop Control & LLM API Hardening

This report provides a detailed, read-only analysis of five core resilience features within the Orynn companion codebase. For each feature, we identify the exact implementation files, functions, and lines, define the mock infrastructure required for opaque-box testing, and detail a comprehensive 4-tier test suite.

---

## 1. Feature Analysis: Implementation & Locations

### Feature 1: Gemini Live Connection Robustness and Autoreconnect (R1)
*   **Implementation Location**: `app/widget/gemini_live.py`
*   **Key Classes & Functions**:
    *   `GeminiLiveCompanion` class (line 142)
    *   `GeminiLiveCompanion._run(self)` (lines 218–392): Contains the core async event loop that manages the WebSocket session. It implements a retry loop (lines 354–391) that rebuilds the session configuration using `self._live_config(types)` on each attempt.
    *   `GeminiLiveCompanion._live_config(self, types)` (lines 415–440): Attaches the session resumption handle via `types.SessionResumptionConfig(handle=self._resume_handle)`.
    *   `GeminiLiveCompanion._handle_message(self, session, message, output_queue_or_stream, types)` (lines 555–618): Handles incoming server messages.
        *   **Resumption Handle Capture**: Lines 564–568 extract `message.session_resumption_update.new_handle` and store it in `self._resume_handle` for subsequent connection attempts.
        *   **Barge-In Handling**: Lines 575–576 detect if `message.server_content.interrupted` is `True`. If so, it calls `self._flush_output(output_queue_or_stream)` (lines 461–474) to immediately drop pending audio chunks from the speaker queue, silencing the companion instantly.
    *   `playback_worker()` (lines 325–346): Dedicated playback thread. Tracks audio output errors. If the audio fail streak (`self._audio_fail_streak`) reaches `GEMINI_LIVE_MAX_AUDIO_FAILS` (40), it triggers an error callback and terminates.
    *   `_execute_tool(self, name, args)` (lines 641–676): Wraps tool execution in `asyncio.wait_for` with a `GEMINI_LIVE_TOOL_TIMEOUT` (15.0s) limit (lines 650, 655, 660) to prevent a stalled local tool call from hanging the WebSocket connection.

---

### Feature 2: Resilient UIA Click & Verification Self-Healing (R2 click)
*   **Implementation Locations**:
    *   `app/tools.py`: Contains the tool executor wrappers and self-healing orchestrations.
    *   `app/widget/desktop_features.py`: Contains the low-level Win32 and UI Automation (UIA) interaction wrappers.
*   **Key Classes & Functions**:
    *   `ToolExecutor.uia_click(self, query: str, app: str = "")` (`app/tools.py`, lines 3730–3780): The primary entry point for clicking controls.
        *   **Pre-Action Snap**: Line 3733 captures the starting state of visible windows via `self._click_snapshot()`.
        *   **UIA Try**: Line 3734 attempts to invoke the element via `invoke_ui_element(query, app)`.
        *   **OCR Fallback**: Lines 3737–3739 invoke `self._ocr_click_fallback(query, app)` if the UIA click fails.
        *   **Post-Action Verification**: Line 3777 calls `self._verify_clicked(before)` after the click to check if UI state changed.
    *   `ToolExecutor._ocr_click_fallback(self, query: str, app: str)` (`app/tools.py`, lines 3141–3177): Invokes local OCR to locate the text center using `ocr_find_in_app(query, app)` and clicks it using `pyautogui.click(x, y)`.
    *   `ToolExecutor._click_snapshot(self)` (`app/tools.py`, lines 3285–3307): Takes a lightweight Win32 snapshot of the foreground HWND and the set of visible window HWNDs using `win32gui.GetForegroundWindow` and `win32gui.EnumWindows`.
    *   `ToolExecutor._verify_clicked(self, before: dict)` (`app/tools.py`, lines 3308–3325): Waits 120ms (`time.sleep(0.12)`) and takes another snapshot. It returns `True` if a new window appeared (e.g. dialog or menu) or the foreground window changed.
    *   `click_ui_element(query, app_hint, button)` (`app/widget/desktop_features.py`, lines 1272–1286) and `invoke_ui_element(query, app_hint)` (`app/widget/desktop_features.py`, lines 1798–1850): Low-level wrappers that invoke UIA patterns (e.g. `InvokePattern`, `SelectionItemPattern`) on the resolved element.

---

### Feature 3: Resilient UIA Type & Elements Resolution Self-Healing (R2 type/find)
*   **Implementation Locations**:
    *   `app/tools.py`: Implements fallback routing, verification, and clipboard paste hacks.
    *   `app/widget/desktop_features.py`: Implements low-level control resolution, Electron relaunching, and Windows OCR query normalization.
*   **Key Classes & Functions**:
    *   `ToolExecutor.uia_type(self, query, text, app, clear_first, submit)` (`app/tools.py`, lines 3784–3838):
        *   **UIA Try**: Line 3787 calls `type_into_ui_element(query, text, app, clear_first, submit)`.
        *   **OCR Fallback**: Line 3790 triggers `self._ocr_type_fallback(...)` if UIA typing fails.
        *   **Post-Action Verification**: Line 3819 executes `self._verify_typed(query, app, text)` to read the field and verify the text landed.
    *   `ToolExecutor._ocr_type_fallback(self, query, text, app, clear_first, submit)` (`app/tools.py`, lines 3230–3283): Locates the field label via OCR (`ocr_find_in_app`), clicks the coordinates to focus, clears text using `ctrl+a` and `delete`, and pastes the new text using `ctrl+v` via the clipboard (`uiautomation.SetClipboardText`).
    *   `ToolExecutor._verify_typed(self, query: str, app: str, text: str)` (`app/tools.py`, lines 3839–3885): Resolves the element and queries patterns (`GetValuePattern`, `GetLegacyIAccessiblePattern`, or `GetTextPattern`) in a loop for up to 1.0s. If the typed text is found in the read-back value, it returns `True`.
    *   `ToolExecutor.uia_find(self, query, app, limit)` (`app/tools.py`, lines 2881–2886) and `_ocr_find_fallback(self, query, app)` (lines 3197–3229): Fallback structure for locating elements. If UIA find fails, it runs OCR and returns simulated `OcrText` elements.
    *   `smart_uia_find_with_unlock(query, app_hint)` (`app/widget/desktop_features.py`, lines 1219–1270): Electron app self-healing. Detects if the foreground process is an Electron app using `is_electron_app(exe_path)`. If UIA fails, it appends an `electron_hint` suggesting to relaunch with `--force-renderer-accessibility` via `_electron_unlock_hint` (`app/tools.py`, lines 3178–3195).
    *   `_ocr_norm(s: str)` (`app/widget/desktop_features.py`, lines 1541–1549): Normalizes OCR text strings by stripping punctuation, keyboard accelerators (`&`), and ellipses (`...`) to prevent string matching misses.

---

### Feature 4: Resilient Textbox Overlay Task/Cursor State Tracking (R3)
*   **Implementation Location**: `app/widget/textbox_overlay.py`
*   **Key Classes & Functions**:
    *   `OverlayController` class (line 385): Subscribes to background task events via `/api/overlay/events`.
    *   `OverlayController._poll_loop(self)` (lines 1547–1596): Polls the API, dispatches action overlays, and updates UI labels and cursor states.
    *   `OverlayController._set_label(self, text, source, hold_seconds, force)` (lines 514–567): Core bubble label arbitration.
        *   **Lock and Protection**: Tracks `self._label_protect_until` and `self._label_protect_source` to prevent race conditions and flashing between different threads (Live audio thread, background HTTP polling thread, GUI thread).
        *   **Gemini Live Priority**: Lines 539–540: If Gemini Live is running or holding the bubble, background task progress labels (`_TASK_CHURN_SOURCES`, e.g., "Clicking Save") are suppressed (muted) so that they do not flash over the live spoken transcript.
        *   **Status Protection**: Lines 542–548 prevent a generic status update ("Listening") from overriding active input/reply/tool labels.
    *   `OverlayController._update_cursor_state_from_event(self, ev)` (lines 1622–1640): Updates cursor states (`idle`, `thinking`, `listening`).
        *   **Cursor State Lock**: Lines 1635–1636: If Gemini Live is running, background task events are blocked from modifying the cursor state, ensuring Live retains full control of the flying cursor's visual state.
    *   `OverlayController._stop_all_worker(self)` (lines 762–794): Instantly cancels voice capture, halts Gemini Live, calls `/api/tasks/X/kill` on all active tasks, and resets cursor state to idle.

---

### Feature 5: Unified LLM API Timeout & Retry Resilience (R4)
*   **Implementation Location**: `app/providers.py`
*   **Key Classes & Functions**:
    *   `_llm_read_timeout()` (lines 1138–1150): Reads read-timeout bounds from `ORYNN_LLM_TIMEOUT`, defaulting to 120s if unset, non-positive, or non-numeric.
    *   `_build_llm_http_client()` (lines 1152–1175): Builds a hardened `httpx.Client` for LLM requests.
        *   **Timeouts**: Configured with `connect=10.0`, `read=_llm_read_timeout()`, `write=20.0`, `pool=10.0`.
        *   **TCP-Level Retry**: Configured with `httpx.HTTPTransport(retries=2)` to automatically self-heal connection-level failures using fresh sockets.
        *   **Stale Connection Drop**: Uses `keepalive_expiry=15.0` to expire idle pool connections quickly.
    *   `PlannerProvider._call_llm(self, system, prompt, screenshot_b64)` (lines 1646–1697): Primary-provider wrapper.
        *   **Failover Trigger**: If the primary provider (Ollama, Groq, Google, OpenAI, Anthropic) raises an `httpx.HTTPStatusError` (specifically status codes 402, 429, or >=500) or `httpx.TransportError` (line 1665), it catches the error and executes failover to OpenRouter.
    *   `PlannerProvider._chat_openrouter(self, system, prompt, screenshot_b64, _model_override)` (lines 1372–1462) and `stream_chat_with_tools` (lines 1850+):
        *   **Fallback Chain**: Obtains model list from `_openrouter_models_to_try(...)` (e.g. Gemma 31B -> Gemma 26B -> Llama 70B -> Nemotron 120B).
        *   **Fail-Fast (Non-Last Models)**: Under `attempt in range(3 if is_last_model else 1)` (line 1404): if it's not the final model in the chain, it tries exactly once. A 402, 429, 5xx, or transport error immediately breaks out of the loop to try the next model.
        *   **Backoff-Retry (Last Model)**: If it is the final model in the chain, it retries up to 3 times with exponential backoff (`2 ** (attempt + 1)` seconds) on errors.
        *   **Chain Re-Try**: If the entire chain of models fails, it waits for backoffs (`_CHAIN_RETRY_BACKOFFS = [8, 20, 40]` seconds, line 1042) and retries the entire chain again from the beginning up to `_CHAIN_RETRY_MAX = 3` times (lines 1382, 1452).

---

## 2. Opaque-Box Testing & Mock Infrastructure

To test the resilience layers without relying on actual Windows UI Automation libraries, active displays, or external network services, we propose the following in-process mock infrastructure:

```
+-----------------------------------------------------------------------------------+
|                              OPAQUE-BOX TEST RUNNER                               |
+-----------------------------------------------------------------------------------+
       |                                      |                               |
       v                                      v                               v
+-------------------------+        +--------------------------+    +-----------------------+
|  MOCK WEBSOCKET SERVER  |        |    MOCK WIN32/UIA/OCR    |    |    MOCK HTTP SERVER   |
| (Simulates Gemini Live) |        | (Simulates OS Desktop)   |    | (Simulates LLM APIs)  |
+-------------------------+        +--------------------------+    +-----------------------+
| - Returns resume tokens |        | - Mock ctypes.windll     |    | - Returns LLM JSON    |
| - Fires interrupted err |        | - Mock pywin32, mss      |    | - Yields chunk streams|
| - Sends tool calls      |        | - Mock pyautogui         |    | - Injects 429, 500,   |
| - Drops TCP connections |        | - Mock OCR words/coords  |    |   & timeout delays    |
+-------------------------+        +--------------------------+    +-----------------------+
```

### 1. Mock WebSockets for Gemini Live (R1)
*   **Approach**: Create a mock in-process async WebSocket server using `asyncio` or mock the `google.genai.Client`'s connection context manager (`client.aio.live.connect`).
*   **Capabilities**:
    *   **Resumption handle emission**: Yields `FakeMessage(session_resumption_update=Resume(resumable=True, new_handle="session-123"))`.
    *   **Barge-in emission**: Yields `FakeMessage(server_content=Content(interrupted=True))`.
    *   **Tool call emission**: Yields `FakeMessage(tool_call=ToolCall(function_calls=[Call(name="desktop_control", args={"action": "click", "query": "Save"})]))`.
    *   **Connection disruption**: Closes the channel abruptly to test client-side backoff and reconnect loops.

### 2. Mock Win32, UIA, and OCR for Desktop Automation (R2 / R3)
*   **Approach**: Replace active Windows dependencies via pytest's `monkeypatch` or unit mocks.
*   **Capabilities**:
    *   **`uiautomation` / UIA Tree Mocking**: Mock `GetForegroundControl()`, `GetRootControl()`, and walk operations. Elements should return mock properties (Name, AutomationId, ControlTypeName) and value patterns (`GetValuePattern`, `GetLegacyIAccessiblePattern`, `GetTextPattern`).
    *   **`pyautogui` coordinate capturing**: Stub `pyautogui.click`, `pyautogui.write`, `pyautogui.hotkey`, and `pyautogui.press` to write parameters to an active spy list for verification.
    *   **OCR Mocking**: Mock `ocr_find_in_app` to return specific bounding boxes and confidence scores, or simulated failures (`{"ok": False, "error": "no OCR text matched"}`).
    *   **Win32 Snapshots**: Stub `win32gui.GetForegroundWindow` and `win32gui.EnumWindows` to return fake HWND sets that update in response to click signals (simulating window state changes).

### 3. Mock HTTP Servers for LLM APIs (R4)
*   **Approach**: Inject a mock handler class into the httpx client transport (`PlannerProvider._http_client`) or use an in-process HTTP mock library (like `respx`).
*   **Capabilities**:
    *   **Transport Failures**: Raise `httpx.ConnectTimeout`, `httpx.ReadTimeout`, or `httpx.NetworkError` on the first N calls.
    *   **HTTP Status Failures**: Return status codes `429`, `402`, or `500` with standard provider error bodies.
    *   **OpenRouter Mocking**: Intercept `https://openrouter.ai/api/v1/chat/completions` and return responses with different models (e.g. Gemma, Llama, Nemotron) to trace model failover chains.

---

## 3. Concrete Test Cases

### Tier 1: Feature Coverage (>=5 tests per feature)

#### Feature 1: Gemini Live (R1)
1.  **Test Case F1-T1: Successful Resumption Handle Storage**
    *   *Setup*: Live connection is active. Mock WebSocket client.
    *   *Action*: Send a message containing `session_resumption_update` with `new_handle="res-abc"`.
    *   *Assertion*: `companion._resume_handle` is updated to `"res-abc"`.
2.  **Test Case F1-T2: Autoreconnect Retry Sequence and Limit**
    *   *Setup*: Set `max_retries = 5`. Monkeypatch `asyncio.sleep` to avoid real-time delays.
    *   *Action*: Make connection attempts consistently raise `ConnectionError`.
    *   *Assertion*: Verify that `connect` is called 6 times total (initial + 5 retries) and then raises the connection error.
3.  **Test Case F1-T3: Resumption Config Usage**
    *   *Setup*: Set `companion._resume_handle = "res-123"`.
    *   *Action*: Call `companion._live_config(types)`.
    *   *Assertion*: The generated config's `session_resumption.handle` field matches `"res-123"`.
4.  **Test Case F1-T4: Barge-In Queue Flushing**
    *   *Setup*: Fill companion playback queue (`output_q`) with multiple audio data bytes.
    *   *Action*: Send a server message with `server_content.interrupted = True`.
    *   *Assertion*: Verify that `output_q` is completely empty immediately after handling the message.
5.  **Test Case F1-T5: Audio Output Failure Threshold Shutdown**
    *   *Setup*: Mock the speaker output stream write function to raise `OSError`.
    *   *Action*: Feed chunks to the playback worker thread.
    *   *Assertion*: Verify that after exactly 40 consecutive write errors, the session's stop event is set and the error callback is fired.

#### Feature 2: UIA Click & Verification Self-Healing (R2 click)
1.  **Test Case F2-T1: UIA Click Success and Verification**
    *   *Setup*: Mock UIA element to be found. Mock win32 snapshots to return identical lists of windows, but different foreground HWNDs (simulating a focus change).
    *   *Action*: Execute `uia_click("button1", "notepad")`.
    *   *Assertion*: The tool returns `ok=True`, and `data["verified"]` is `True`.
2.  **Test Case F2-T2: UIA Click Fail, OCR Click Success Fallback**
    *   *Setup*: Mock UIA `invoke_ui_element` to return `{"ok": False}`. Mock local OCR `ocr_find_in_app` to return `{"ok": True, "x": 100, "y": 200, "matched": "button1"}`.
    *   *Action*: Execute `uia_click("button1", "notepad")`.
    *   *Assertion*: The tool returns `ok=True`, `data["method"]` is `"ocr_pixel"`, and the PyAutoGUI spy confirms a click landed at `(100, 200)`.
3.  **Test Case F2-T3: Click Snapshot Window Count Difference Verification**
    *   *Setup*: Mock `win32gui.EnumWindows` to return `{1, 2}` in the before-snapshot, and `{1, 2, 3}` (representing a new dialog window) in the after-snapshot.
    *   *Action*: Execute `_verify_clicked(before)`.
    *   *Assertion*: The verification returns `True`.
4.  **Test Case F2-T4: Total Click Failure Recovery Escalation**
    *   *Setup*: Mock UIA click and OCR find to both return failure dictionaries.
    *   *Action*: Execute `uia_click("button1", "notepad")`.
    *   *Assertion*: The tool returns `ok=False`, `data["overlay"]["control_layer"]` is `"UIA miss"`, and the output suggests escalating to coordinate clicks.
5.  **Test Case F2-T5: UIA Click Cache Clearing**
    *   *Setup*: Populate `self._uia_find_cache` with mock elements.
    *   *Action*: Invoke `uia_click("button1", "notepad")`.
    *   *Assertion*: Verify that `self._uia_find_cache` is empty before UIA or OCR operations start.

#### Feature 3: UIA Type & Elements Resolution Self-Healing (R2 type/find)
1.  **Test Case F3-T1: UIA Type Success and Value Read-back Verification**
    *   *Setup*: Mock UIA typing to succeed. Mock element value read-back to return `"hello world"`.
    *   *Action*: Execute `uia_type("txtField", "hello world", "notepad")`.
    *   *Assertion*: The tool returns `ok=True`, and `data["verified"]` is `True`.
2.  **Test Case F3-T2: UIA Type Failure, OCR Type Paste Fallback**
    *   *Setup*: Mock UIA `type_into_ui_element` to return `{"ok": False}`. Mock OCR find to return `(50, 100)`.
    *   *Action*: Execute `uia_type("txtField", "text to type", "notepad", clear_first=True)`.
    *   *Assertion*: Verify clipboard was updated with `"text to type"`, PyAutoGUI sent `ctrl+a` -> `delete` -> `ctrl+v`, and the tool returns `ok=True`.
3.  **Test Case F3-T3: Electron App UIA Find Miss suggestion**
    *   *Setup*: Mock UIA element find to fail. Mock the foreground process to be `"slack.exe"` (contained in `ELECTRON_EXES`).
    *   *Action*: Execute `smart_uia_find_with_unlock("messageBox", "slack")`.
    *   *Assertion*: The return dictionary contains `electron_hint` with the exe path and the tip warning that DOM accessibility is disabled.
4.  **Test Case F3-T4: OCR Normalization Accelerator Stripping**
    *   *Setup*: Define raw label strings containing `&Save...`, `&File`, and `Options...`.
    *   *Action*: Pass each to `_ocr_norm`.
    *   *Assertion*: Verify that the output strings are cleaned to `"save"`, `"file"`, and `"options"`.
5.  **Test Case F3-T5: Type Value Verification Retry Window Timeout**
    *   *Setup*: Mock value read-backs to return `""` initially, changing to `"text"` after 0.5 seconds.
    *   *Action*: Execute `_verify_typed("field", "notepad", "text")`.
    *   *Assertion*: The function sleeps, retries, and successfully returns `True` before the 1.0s deadline.

#### Feature 4: Textbox Overlay Task/Cursor State Tracking (R3)
1.  **Test Case F4-T1: Background Churn Suppression during Live Conversation**
    *   *Setup*: Set `_live` companion is running.
    *   *Action*: Call `_set_label("Clicking button", source="task_action")`.
    *   *Assertion*: The function returns `False`, and no QT label update signal is emitted.
2.  **Test Case F4-T2: Final Task Result Pass-through**
    *   *Setup*: Set `_live` companion is running.
    *   *Action*: Call `_set_label("Task finished successfully", source="task_result")`.
    *   *Assertion*: The function returns `True`, bypassing the churn suppression.
3.  **Test Case F4-T3: Live Status Message Conflict Resolution**
    *   *Setup*: Write a specific tool label `"Typed into field"` with source `"live_reply"` and active hold protection.
    *   *Action*: Attempt to set label to `"Listening"` with source `"live_status"`.
    *   *Assertion*: The update is rejected (`False`) because the higher priority reply label is protected.
4.  **Test Case F4-T4: Background Task Cursor State Lock**
    *   *Setup*: Set `_live` companion is running.
    *   *Action*: Fire event `task_created` which usually sets the cursor state to `"thinking"`.
    *   *Assertion*: Verify that no QT `cursorStateRequested` signal is emitted, leaving Live in control.
5.  **Test Case F4-T5: Emergency Stop Reset Sequence**
    *   *Setup*: Live session is running, active task flags are set, and task ID `"task-abc"` is tracked.
    *   *Action*: Call `_stop_all_worker()`.
    *   *Assertion*: Verification that:
        *   `_live.stop()` is invoked.
        *   `/api/tasks/task-abc/kill` is requested.
        *   Cursor state is set to `"idle"`.
        *   The bubble label displays `"Stopped"`.

#### Feature 5: Unified LLM API Timeout & Retry Resilience (R4)
1.  **Test Case F5-T1: LLM Timeout Bounds Env Fallback**
    *   *Setup*: Set `ORYNN_LLM_TIMEOUT` to `"invalid"`, `""`, and `"-5"`.
    *   *Action*: Call `_llm_read_timeout()`.
    *   *Assertion*: The function consistently resolves to the safe default value of `120.0`.
2.  **Test Case F5-T2: Hardened HTTP Client Pool and Retries Config**
    *   *Setup*: Instantiate client via `_build_llm_http_client()`.
    *   *Action*: Inspect transport and timeout properties.
    *   *Assertion*: Verification that:
        *   `client.timeout.connect == 10.0`
        *   `transport._pool._keepalive_expiry == 15.0`
        *   `transport._pool._retries >= 2`
3.  **Test Case F5-T3: Primary Provider Failover to OpenRouter**
    *   *Setup*: Mock Groq client to return a `503 Server Error` HTTP status exception.
    *   *Action*: Call `_call_llm(system, prompt)` with a Groq model.
    *   *Assertion*: The provider captures the error, prints fallback logs, and executes `_chat_openrouter`.
4.  **Test Case F5-T4: Fallback Model Chain Fail-Fast**
    *   *Setup*: Define models list: `[ModelA, ModelB, ModelC]`. Mock ModelA and ModelB to fail with rate limits.
    *   *Action*: Run `_chat_openrouter`.
    *   *Assertion*: Verify that ModelA and ModelB are attempted exactly once (failing fast) and the loop moves immediately to the next model in the chain without delay.
5.  **Test Case F5-T5: Fallback Chain Backoff and Max Attempts**
    *   *Setup*: Mock all models in the fallback chain to fail. Monkeypatch sleep delays.
    *   *Action*: Run `_chat_openrouter`.
    *   *Assertion*: Verify that after trying every model, the loop executes up to 3 outer chain retries with backoffs (`8s`, `20s`, `40s`) and then raises a `RuntimeError` stating all free models are busy.

---

### Tier 2: Boundary/Edge Cases (>=5 tests per feature)

#### Feature 1: Gemini Live (R1)
1.  **Test Case F1-E1: Empty Resumption Handle Configuration**
    *   *Setup*: Set `self._resume_handle = None`.
    *   *Action*: Execute `self._live_config(types)`.
    *   *Assertion*: Config `session_resumption.handle` is `None` or absent, representing a clean session startup without exceptions.
2.  **Test Case F1-E2: Massive Audio Failure Recovery**
    *   *Setup*: Set `self._audio_fail_streak = 39` (one below terminal threshold).
    *   *Action*: Write one audio chunk successfully.
    *   *Assertion*: Verify that `self._audio_fail_streak` resets to `0` and playback continues.
3.  **Test Case F1-E3: Barge-In during Empty Playback Queue**
    *   *Setup*: Playback queue `output_q` is completely empty.
    *   *Action*: Receive `interrupted=True` message.
    *   *Assertion*: Queue flush helper exits cleanly without generating exceptions (`queue.Empty` handled).
4.  **Test Case F1-E4: Reconnect backoff duration capping**
    *   *Setup*: Connection fails repeatedly. Set `retry_delay = 8.0`.
    *   *Action*: Connection throws exception.
    *   *Assertion*: Next sleep delay is capped at `10.0` seconds (not `16.0s`).
5.  **Test Case F1-E5: Tool Call Arguments Type Coercion**
    *   *Setup*: Receive a tool call where arguments are sent as a raw string `"{'goal': 'calc'}"` or string list instead of a JSON dictionary.
    *   *Action*: Execute `_coerce_tool_args(args)`.
    *   *Assertion*: The arguments are parsed, coerced, or return a friendly schema error instead of crashing the routing thread.

#### Feature 2: UIA Click & Verification Self-Healing (R2 click)
1.  **Test Case F2-E1: Focus Target App Window Missing**
    *   *Setup*: App window for `"Chrome"` is not open.
    *   *Action*: Call `uia_click("button", "Chrome")`.
    *   *Assertion*: Verification snapshot handles empty hwnd collections, falls back to OCR, and if that also fails, returns `ok=False` containing a UIA miss payload.
2.  **Test Case F2-E2: Click verification during concurrent window close**
    *   *Setup*: A click snaps the window list. Another application closes naturally during the 120ms verification sleep.
    *   *Action*: Check window list again.
    *   *Assertion*: `before - after` yields window differences but verification handles the negative window set gracefully (does not false-positive verify the click).
3.  **Test Case F2-E3: OCR find coordinate scaling boundaries**
    *   *Setup*: Screen resolution is mock-configured to high DPI (e.g. 3840x2160, scaling factor 2.0).
    *   *Action*: Click via OCR fallback coordinates.
    *   *Assertion*: Coordinate scaling logic maps screen values correctly to absolute pyautogui pixel values without clipping out of bounds.
4.  **Test Case F2-E4: Click verification on zero-rect UIA elements**
    *   *Setup*: UIA element matches but returns coordinates `{"left":0, "top":0, "width":0, "height":0}`.
    *   *Action*: Attempt `uia_click`.
    *   *Assertion*: The zero-rect is detected, fallback to OCR is triggered immediately instead of attempting to click coordinate `(0,0)`.
5.  **Test Case F2-E5: Click snapshot failure robustness**
    *   *Setup*: Win32 API functions return `None` or raise system access errors due to permission locks.
    *   *Action*: Run `_click_snapshot()`.
    *   *Assertion*: The function catches all errors, returns an empty snap dictionary `{"fg": None, "wins": None}`, and allows the click to proceed.

#### Feature 3: UIA Type & Elements Resolution Self-Healing (R2 type/find)
1.  **Test Case F3-E1: Type Verification of Hidden Text**
    *   *Setup*: Text typed is `"secret"`. Value read back from field returns password masked text `"******"`.
    *   *Action*: Execute `_verify_typed("pwd", "app", "secret")`.
    *   *Assertion*: Readback comparison returns `False` or `None` without crashing, enabling the system to report warning states.
2.  **Test Case F3-E2: OCR Type fallback with empty string**
    *   *Setup*: OCR fallback triggers for typing. Input text is empty `""`.
    *   *Action*: Execute `_ocr_type_fallback(...)`.
    *   *Assertion*: Clipboard and typing procedures exit early with `None`, preventing clipboard corruption.
3.  **Test Case F3-E3: UIA readback patterns raising AccessDenied**
    *   *Setup*: Target field belongs to an elevated admin application; querying value patterns raises COM errors.
    *   *Action*: Execute `_verify_typed`.
    *   *Assertion*: COM exceptions are swallowed, and the function returns `None` (unverifiable) rather than raising an unhandled error.
4.  **Test Case F3-E4: Electron app path mapping with unregistered EXEs**
    *   *Setup*: Foreground exe is `"UnknownApp.exe"`.
    *   *Action*: Call `smart_uia_find_with_unlock`.
    *   *Assertion*: The finder ignores the exe, returning the UIA miss results without crashing.
5.  **Test Case F3-E5: UIA Find Cache Expiry boundary**
    *   *Setup*: Cache key is written. Time is mocked to advance past `_UIA_FIND_CACHE_TTL_S` (5.0s).
    *   *Action*: Call `_cached_uia_find(key)`.
    *   *Assertion*: Cache hit returns `None`, and the expired entry is popped from the store.

#### Feature 4: Textbox Overlay Task/Cursor State Tracking (R3)
1.  **Test Case F4-E1: Extremely long status message truncation**
    *   *Setup*: Poller receives a status message containing a 5000-character raw log string.
    *   *Action*: Call `_set_label(msg)`.
    *   *Assertion*: The label text is safely truncated using `_short()` before being emitted, preventing GUI thread layouts from breaking.
2.  **Test Case F4-E2: Duplicate event sequence IDs**
    *   *Setup*: Poller reads events. Stream yields events with sequence IDs lower than current `self._cursor`.
    *   *Action*: Process events.
    *   *Assertion*: The poller skips duplicate events, preventing visual cursor animations from re-triggering.
3.  **Test Case F4-E3: UI Overlay coordinate mapping to secondary screens**
    *   *Setup*: System coordinates are in negative offsets (representing left-hand secondary monitor configurations).
    *   *Action*: Emit overlay action with negative bounds.
    *   *Assertion*: Overlay coordinates are processed safely, clamping bounding boxes to viewport limits without drawing off-screen windows.
4.  **Test Case F4-E4: Lock expiration during active speech**
    *   *Setup*: Set label protect time to `now + 2.8s`. Mock time to advance by `3.0s`.
    *   *Action*: Send a background task action event.
    *   *Assertion*: The label is accepted and rendered in the bubble, confirming the lock expired.
5.  **Test Case F4-E5: Multi-thread label write collision**
    *   *Setup*: Spawn 5 concurrent threads, each attempting to write different labels via `_set_label` simultaneously.
    *   *Action*: Verify execution.
    *   *Assertion*: Label locks prevent race conditions; the final set label matches the latest highest-priority caller.

#### Feature 5: Unified LLM API Timeout & Retry Resilience (R4)
1.  **Test Case F5-E1: Extreme rate limit delay cap**
    *   *Setup*: OpenRouter returns 429 error with header suggesting `retry-after: 3600`.
    *   *Action*: Attempt retry loop.
    *   *Assertion*: Loop ignores extreme server header sleep durations, adhering to its capped exponential backoff limits (`2 ** (attempt + 1)`).
2.  **Test Case F5-E2: Empty response choices dictionary**
    *   *Setup*: OpenRouter returns a `200 OK` response but choices list is empty (`"choices": []`).
    *   *Action*: Handle HTTP response.
    *   *Assertion*: The error is caught as an unexpected response format, triggering failover to the next fallback model.
3.  **Test Case F5-E3: OpenRouter API key missing during failover**
    *   *Setup*: Set `self._openrouter_key = ""`. Groq primary provider fails.
    *   *Action*: Run `_call_llm`.
    *   *Assertion*: The primary error is raised immediately, skipping the OpenRouter fallback loop since credentials are missing.
4.  **Test Case F5-E4: Parallel tool streaming cancellation**
    *   *Setup*: Streaming chat with tools is active.
    *   *Action*: Fire cancellation event mid-stream.
    *   *Assertion*: Async generator exits, closing the HTTP stream response pool cleanly without leaking sockets.
5.  **Test Case F5-E5: Timeout override below zero**
    *   *Setup*: Set `ORYNN_LLM_TIMEOUT = "-10"`.
    *   *Action*: Call `_build_llm_http_client()`.
    *   *Assertion*: Client read timeout falls back to default 120s rather than crashing on initialization.

---

### Tier 3: Cross-Feature Combinations (Pairwise coverage)

This matrix outlines tests designed to verify how features interact under load or failure.

| Feature Pair | Interaction Scenario | Verification Assertion |
| :--- | :--- | :--- |
| **F1 + F2** | Gemini Live makes a click tool call; UIA click misses, prompting OCR fallback. | The tool executes OCR click fallback, returns the structured coordination payload, and Live receives the response without connection timeouts. |
| **F1 + F3** | Gemini Live requests typing; UIA type misses, triggering OCR clipboard paste. | OCR clipboard typing executes, restoring the user's prior clipboard. Live receives the success payload and continues the conversational turn. |
| **F1 + F4** | Gemini Live toggles on while a long background task is running. | Background task per-step labels (`_TASK_CHURN_SOURCES`) are immediately muted in the textbox overlay bubble. The cursor state remains locked to Live's listening status. |
| **F1 + F5** | Gemini Live starts a task via `start_desktop_task`. The LLM planner encounters a rate limit. | The planner triggers OpenRouter failover backoffs. Live queries status via `get_companion_status` and correctly reports the task is still running. |
| **F2 + F3** | A multi-step task requires a click to open a dialog, followed by typing. | Both fallback layers activate in sequence. If UIA click and UIA type both miss, the click heals via OCR, the window snap verifies focus, and the type heals via OCR clipboard paste. |
| **F2 + F4** | UIA click fails, calling OCR click fallback. The task poller monitors the result. | The overlay controller reads the `method="ocr_pixel"` event, bypasses status mutes, and animates the cursor to show the visual click ring and OCR label. |
| **F3 + F4** | UIA type fails on an Electron app. UIA find returns a blank tree. | The poller reads the UIA miss result, retrieves the `electron_hint` tip, and displays the relaunch instruction in the overlay bubble. |
| **F2 + F5** | UIA click fails, and OCR click also fails. The agent receives a UIA miss. | The agent catches the miss, and the planner provider retries via the model fallback chain to decide whether to switch to visual coordinate clicking. |
| **F3 + F5** | UIA type fails, and OCR type fails. The agent receives typing failure. | The planner provider uses OpenRouter model fallbacks to generate a recovery plan (e.g. attempting to focus using alternative shortcut keys). |
| **F4 + F5** | A task is running. The LLM provider experiences 429 errors and falls back to OpenRouter. | The overlay controller polls the `provider_info` event and updates the bubble to show `"Waiting on model"` (thinking word), keeping the cursor state synchronized. |

---

### Tier 4: Real-World Application Scenarios (>=5 scenarios)

#### Scenario 1: Voice-Driven Web Form Autocomplete under Rate Limits
*   *Feature Interactions*: F1 (Gemini Live), F2 (UIA Click Fallback), F3 (UIA Type Fallback), F4 (Overlay Suppression), F5 (LLM API Fallback).
*   *Execution Flow*:
    1.  The user speaks: *"Fill out my registration form."* Gemini Live captures audio and calls `start_desktop_task` (F1).
    2.  Orynn's primary LLM planner hits a 429 rate limit. The provider catches it, fails over to OpenRouter, tries Gemma 31B, and succeeds (F5).
    3.  The task executor tries to focus the first name text box using UIA. The web application uses custom canvas rendering, causing UIA find to fail (F3).
    4.  The system heals: it calls OCR find, locates the coordinate of `"First Name"`, clicks it, and pastes the text via clipboard (F3).
    5.  During execution, Gemini Live continues narrating the task out loud. The overlay suppresses the task's individual step labels (preventing bubble flashing) but animates the flying cursor to each field (F4).

#### Scenario 2: Electron Application Accessibility Relaunch and Auto-Recovery
*   *Feature Interactions*: F2 (UIA Click Verification), F3 (Electron App Unlock), F4 (Overlay State Tracking).
*   *Execution Flow*:
    1.  The user commands: *"Click the general channel in Discord."*
    2.  The tool executor attempts `uia_click`. The UIA tree returns empty because Discord's DOM accessibility is locked (F3).
    3.  The resolver detects `discord.exe` is in `ELECTRON_EXES` and yields the Electron accessibility tip (F3).
    4.  The agent halts execution, launches a command to restart Discord with the `--force-renderer-accessibility` flag, and waits for the window (F3).
    5.  Once the window is ready, UIA successfully resolves the `"General"` channel element, clicks it, and post-action verification confirms a new channel window state is active (F2).
    6.  The textbox overlay tracks this transition, updating the label from `"Finding window"` -> `"Relaunching app"` -> `"Clicked General"` (F4).

#### Scenario 3: Multi-Step Task Interrupted by User Barge-in and Emergency Stop
*   *Feature Interactions*: F1 (WebSocket Barge-in), F4 (Stop Hotkey / Task Kill), F5 (Stream Cancellation).
*   *Execution Flow*:
    1.  Orynn is executing a multi-step project compilation task. The planner is streaming new tool calls from OpenRouter (F5).
    2.  The user presses the push-to-talk hotkey or speaks: *"Stop! Cancel this task."*
    3.  The Gemini Live companion instantly receives the `interrupted` event and flushes the playback queue to stop speaking (F1).
    4.  The overlay controller processes the emergency cancel combo, stops voice recording, and sends a POST request to `/api/tasks/task-id/kill` (F4).
    5.  The background compilation task terminates immediately. The streaming client cancels the connection (F5), and the overlay cursor resets to `"idle"` (F4).

#### Scenario 4: Flaky Network Live Session Recovery during Document Editing
*   *Feature Interactions*: F1 (Autoreconnect & Resumption), F3 (OCR Clipboard typing), F4 (Overlay Status Update).
*   *Execution Flow*:
    1.  Orynn is typing a text document for the user.
    2.  The local internet connection drops. The Gemini Live WebSocket disconnects (F1).
    3.  The companion stores the latest resumption handle `"handle-99"`, sets the status callback to `"Live reconnecting (1/5)..."`, and waits (F1).
    4.  The overlay controller intercepts the reconnect status, displaying `"Reconnecting..."` in the bubble while locking the cursor state (F4).
    5.  After 2 seconds, the connection succeeds. The client sends `"handle-99"`, restoring the exact conversation context (F1).
    6.  The document editing task resumes. Because UIA focus was lost during the drop, the system uses OCR typing to focus and complete the text input (F3).

#### Scenario 5: Multi-App Workspace Setup under Severe Provider Outages
*   *Feature Interactions*: F2 (Verification & Click Snapshot), F4 (Visual app-glow), F5 (Chain Re-Try Backoff).
*   *Execution Flow*:
    1.  The user asks: *"Set up my coding layout."*
    2.  The primary provider and the first three OpenRouter fallback models return `500 Server Errors` due to a major API outage (F5).
    3.  The planner provider executes a chain retry, backing off for 8 seconds, and retries the chain. On the second try, it successfully contacts the fallback Llama-3.3 model (F5).
    4.  The layout plan starts. The executor focuses VS Code and Chrome.
    5.  UIA click fails on Chrome's window border. The tool executor falls back to OCR visual text clicking (F2).
    6.  Post-click verification checks window coordinates and confirms the workspace layout matches the preset (F2).
    7.  The overlay controller animates the flying cursor to each window, drawing focus rings and showing `"Thinking..."` during provider backoff periods (F4).

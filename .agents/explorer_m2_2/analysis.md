# Milestone 2: Resilient UIA Click/Type Verification & Self-Healing (R2) - Analysis Report

## Executive Summary
This report analyzes the core Windows UI Automation (UIA) tools in Orynn (`app/tools.py` and `app/widget/desktop_features.py`). It identifies critical flaws in verification, typing desyncs in React-based frameworks, and element resolution failures during UI transitions. It proposes concrete implementation plans to introduce retries, alternative activation paths, auto-waiting, and robust clipboard management.

---

## 1. Analysis of `uia_click` Verification & Retry Mechanisms

### Current Verification Logic
In `app/tools.py`, the `uia_click` method attempts to verify if a click was successful by taking a cheap UI fingerprint (window list and active window title/HWND) before and after the action:
* **Before Click**: `before = self._click_snapshot()` captures the foreground window HWND/title and all visible top-level window HWNDs.
* **Click Action**: Calls `invoke_ui_element(query, app)`, which tries UIA patterns (`InvokePattern`, `TogglePattern`, `SelectionItemPattern`) and falls back to a coordinate click if those patterns aren't supported.
* **Verification Check**: Calls `self._verify_clicked(before)`, which sleeps for 120ms, takes a second snapshot, and returns `True` if:
  1. A new top-level window (e.g., a dropdown menu, modal, or dialog) has appeared.
  2. The foreground window focus has changed.

### Why it returns `ok=True` when verification fails
1. **API success is decoupled from UI verification**: In `uia_click` (lines 3730–3783), if `invoke_ui_element()` returns `{"ok": True}` (meaning UIA didn't throw an error during invocation or a mouse click was successfully dispatched), the tool proceeds to return `ToolResult(ok=True)`.
2. **Informational-only verification**: The result of `self._verify_clicked(before)` is stored in `data["verified"]` and appends `" (verified)"` to the output message, but it **never** changes the `ToolResult.ok` status to `False`. Thus, a click that fails to produce any UI changes still reports success to the orchestrator.

### Suggested Implementation Plan for Retry/Alternative Activation
To make `uia_click` self-healing, we propose modifying the click action to execute inside a retry loop when verification fails:

```python
# Proposed Logic Concept for uia_click self-healing:
# 1. Capture snapshot before click.
# 2. Attempt activation.
# 3. Verify. If verified is True, return success.
# 4. If verified is None/False:
#    a. Check window focus. If target window lost focus, AppActivate/SetForegroundWindow to refocus.
#    b. Check if element is offscreen. Scroll element into view via ScrollItemPattern.
#    c. If InvokePattern failed to change UI state, retry using coordinate click (pyautogui.click) on element center.
#    d. If UIA coordinate click fails, fall back to OCR-based coordinate click (_ocr_click_fallback).
#    e. Loop up to 3 times, checking verification after each step.
```

#### Detailed Steps:
1. **Refs #app/tools.py:3730**: Introduce a retry loop (max 3 attempts).
2. **Foreground Focus Check**: If the target window is iconic (minimized) or not in the foreground, call `self._activate_hwnd(hwnd)` to restore and foreground it.
3. **Scroll Enforcement**: If the element reports `offscreen` or has coordinates outside the current window bounds, call `ScrollItemPattern.ScrollIntoView()`.
4. **Fallback Escalation Path**:
   * **Attempt 1 (UIA Background)**: Try `InvokePattern`, `TogglePattern`, or `SelectionItemPattern`.
   * **Attempt 2 (UIA Foreground Coordinate Click)**: Refocus the window and dispatch a physical `pyautogui.click()` to the element's resolved center.
   * **Attempt 3 (OCR Coordinate Click)**: If UIA fails to find/click the element or UIA coordinate click failed verification, execute `self._ocr_click_fallback(query, app)`.

---

## 2. Analysis of `uia_type` & Clipboard Paste Logic

### Current Typing and Paste Logic
In `app/widget/desktop_features.py`, `type_into_ui_element` (lines 1630–1770) operates in three tiers:
1. **Background SetValue**: Uses `ValuePattern.SetValue` without focusing. It is fast and runs in the background.
2. **Focus + Clipboard Paste**: Focuses the input element, copies text to the clipboard, and triggers a simulated paste (`Ctrl+V`) via UIA `SendKeys` or `pyautogui.hotkey`.
3. **Physical Keystroke Fallback**: Types character-by-character via `pyautogui.typewrite` at a 10ms interval.

### React Event Listener Issues
Modern web apps (React, Vue, Electron interfaces like Discord, Slack, VS Code) use a synthetic event system. 
* **The Bug**: `ValuePattern.SetValue` updates the underlying DOM input value directly but **does not trigger browser events** like `input` or `change`. Consequently, React's internal state remains empty. When the agent presses Enter, the form sends an empty string.
* **Detection**: Desync can be detected by:
  1. Checking if the target executable belongs to `ELECTRON_EXES` (e.g., Discord, Slack). If so, bypass the Background SetValue tier entirely.
  2. In `_verify_typed`, performing a read-back after a 100ms delay. If the read-back returns empty or the previous value (due to React state overwriting the DOM value on render), desync is confirmed.
* **Prevention**: Ensure that for desynced apps, we exclusively use paste or keystroke methods which dispatch native Windows input messages, forcing the Chromium renderer to trigger the necessary JavaScript event listeners.

### Clipboard Access Blocked Errors
The clipboard is a shared Win32 system resource. If another application holds the clipboard lock when `uia.SetClipboardText()` or `uia.GetClipboardText()` is called, Windows raises an `Access is denied` error.
* **Current Handling**: Any exception in `SetClipboardText` immediately aborts the paste tier and falls back to character-by-character keystrokes.
* **Robust Solution**: Introduce a safe clipboard accessor utility with retry logic:
  ```python
  def safe_set_clipboard(text: str, retries: int = 5, delay: float = 0.05) -> bool:
      for i in range(retries):
          try:
              import uiautomation as uia
              uia.SetClipboardText(text)
              if uia.GetClipboardText() == text:
                  return True
          except Exception:
              time.sleep(delay * (1.5 ** i))  # Exponential backoff
      return False
  ```

### Dropped Characters during Slow Typing
When clipboard paste is unavailable, the fallback types each character individually. Under system load or laggy UI loops, typing characters at 10ms intervals causes:
1. Keys to arrive out-of-order.
2. Characters to be dropped entirely.
3. Modifier keys (like Shift) to release prematurely, changing cases (e.g. typing `A` as `a`).

* **Prevention**:
  1. Increase the minimum inter-character typing delay from 10ms to a safer default of 25–50ms.
  2. Implement **dynamic speed reduction**: if character verification fails, clear the field, double the inter-character delay, and retry typing.
  3. Use UIA's `ctrl.SendKeys(text, waitTime=10)` instead of pyautogui for elements that support it, as it delivers input directly to the window message queue rather than the global OS input queue.

---

## 3. Analysis of `find_ui_element` Resolution Logic

### Current Resolution Flow
1. `find_ui_element` (lines 939-946) calls `find_ui_elements(query, app_hint, limit=1)`.
2. `find_ui_elements` retrieves top-level root windows and walks the accessibility tree up to depth 40.
3. If no element matches the query on the first walk, it immediately falls back to OCR. If OCR also misses, it raises a hard failure.

There is **no wait or polling** built into `find_ui_element`. While `uia_wait` exists as a standalone tool, the primary action tools (`uia_click` and `uia_type`) invoke `_find_uia_control` directly. If the target element is in the middle of a rendering transition (e.g., a modal fade-in or a dropdown opening), these tools fail instantly.

### Suggested Implementation of Auto-Retry Waits
We should introduce an implicit wait directly into `find_ui_elements` and `_find_uia_control` to automatically poll for transient elements:

```python
# Proposed Auto-Retry logic:
def find_ui_elements_with_retry(query: str, app_hint: str = "", limit: int = 5, 
                                timeout: float = 1.5, interval: float = 0.2) -> dict:
    deadline = time.time() + timeout
    while True:
        res = find_ui_elements_raw(query, app_hint, limit)
        if res.get("ok") and res.get("items"):
            return res
        if time.time() >= deadline:
            return res  # Return the last failed result
        time.sleep(interval)
```

#### Key Parameters:
* **Timeout**: Default to 1.5s (sufficient for Windows animations and Electron UI rendering).
* **Interval**: 200ms (prevents high CPU usage from walking the tree too frequently).
* **Bypass Option**: Add an `immediate: bool = False` flag to allow instant checks when checking for the absence of an element.

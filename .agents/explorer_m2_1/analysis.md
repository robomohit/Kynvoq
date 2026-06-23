# Milestone 2: Resilient UIA Click/Type Verification & Self-Healing (R2) - Analysis

This report presents a read-only analysis of the current implementation of UIA click, type, and element resolution logic in the Orynn desktop agent, along with detailed implementation plans to introduce resilience and self-healing.

---

## 1. Analysis of `uia_click` and Verification

### Current Behavior & Verification Logic
In `app/tools.py`, `uia_click` executes the following sequence:
1. Captures a "before" snapshot of the Win32 window state via `self._click_snapshot()`.
2. Resolves and activates the target element using `invoke_ui_element(query, app)`.
3. If `invoke_ui_element` returns `ok=False`, it attempts OCR-based coordinate click fallback via `_ocr_click_fallback(query, app)`.
4. If the invocation was successful (`ok=True`):
   - It captures an "after" snapshot using `_verify_clicked(before)`.
   - Writes `data["verified"] = verified` (which is `True` or `None`).
   - Returns a `ToolResult` with `ok=True`.

### Why it returns `ok=True` when verification fails
The helper method `_verify_clicked` is defined as:
```python
    def _verify_clicked(self, before: dict):
        """True if the click visibly changed UI state (a menu/dialog appeared or
        the foreground window changed), None if we can't tell. Never False: a
        click that produces no observable change is common and legitimate, so we
        annotate confidence rather than cry failure."""
```
Because many clicks do not produce top-level window transitions or foreground changes (e.g., checking a checkbox, clicking a digit on a calculator, selecting a tab), `_verify_clicked` returns `None` instead of `False` when no window changes are detected. Consequently, `uia_click` treats the action as successful (`ok=True`) simply because the API invocation did not raise an error, regardless of whether it actually caused the desired state transition.

### Proposed Retry / Alternative Activation Mechanism
To make clicking self-healing, we should implement a robust retry loop when verification fails:
1. **Define Stricter Local Verification**:
   - If the element supports `TogglePattern` or `SelectionItemPattern`, check its state (e.g., `IsSelected` or `ToggleState`) before and after the click.
   - For other elements, if the win32-based `_verify_clicked` returns `None`, we can consider it inconclusive but acceptable, or we can trigger self-healing if a downstream assertion/readback fails.
2. **Focusing Window**:
   - Before retrying, call `self._activate_hwnd(hwnd)` on the target app's root window. Windows in the background often drop click events or fail to process UIA pattern invocations.
3. **Scrolling**:
   - Prior to retry, re-verify the control's coordinate layout. If it is offscreen or virtualized, call `ScrollItemPattern.ScrollIntoView()` and sleep for 100ms to allow layout settling.
4. **Alternative Activation / Click Fallback**:
   - If `InvokePattern` was attempted but didn't verify, fallback to a physical mouse click on the element's resolved center coordinate (`click_fallback` using `pyautogui.click`).
   - If coordinate clicking is unsuccessful or the element lacks an on-screen rectangle, fall back to OCR-based coordinate click (`_ocr_click_fallback`). This uses Windows OCR to locate the text query on the screen and physically clicks the pixels, bypassing UIA-level obstructions.

---

## 2. Analysis of `uia_type` and Typing/Clipboard Paste Logic

### Current Typing / Clipboard Paste Logic
In `app/widget/desktop_features.py`, `type_into_ui_element` executes typing using several tiered strategies:
* **Tier 0 (Background Value Set)**: Uses `ValuePattern.SetValue` without stealing focus. Only used if `submit=False` and the control is not a `DocumentControl`.
* **Tier 1 (Focus)**: Calls `ctrl.SetFocus()` or falls back to a coordinate click if SetFocus fails.
* **Tier 2 (Clipboard Paste)**: Writes text to the clipboard using `uia.SetClipboardText(text)`, verifies the clipboard contents match, sends `Ctrl+V` (via `ctrl.SendKeys` or `pyautogui`), and restores the original clipboard content.
* **Tier 3 (Keystroke Fallback)**: If the clipboard write/verification fails, it types character-by-character using `pyautogui.typewrite(text, interval=0.01)`.

### A. Detecting React/Framework Event Listener Issues
Web and Electron apps (like Discord, Slack, VS Code, and Notion) intercept keyboard events to synchronize their internal virtual DOM state.
* **The Bug**: `ValuePattern.SetValue` directly updates the DOM element's `value` property, but it does **not** trigger standard JavaScript event listeners (e.g., `input`, `change`, `keydown`, `keyup`). When the form is submitted, the React state is empty, causing the text to disappear or fail to submit.
* **Proposed Detection & Mitigation**:
  1. **Bypass SetValue for Browsers/Electron**: Check if the target control's root window belongs to a known browser or Electron process (using `is_electron_app`). If true, completely skip Tier 0 (`ValuePattern.SetValue`) and go straight to focus-and-paste.
  2. **React Event Triggering**: After pasting, if we detect the application is a React/web-based app, we can simulate a single trailing non-destructive keystroke (like sending a backspace or a space-backspace sequence) using `SendKeys`. This forces the application's event loop to trigger and sync its internal state.

### B. Handling Clipboard Access Blocked Errors
* **The Bug**: Since the clipboard is a system-wide shared resource, other applications (clipboard managers, remote desktops, or concurrent processes) can lock it. When `uia.SetClipboardText` or `uia.GetClipboardText` is called, Windows throws a "Clipboard in use" or "Access denied" exception. Currently, any exception instantly fails the paste operation and defaults to slow keystroke typing.
* **Proposed Retry Delays**:
  Implement a helper with retry-with-backoff for all clipboard interactions:
  ```python
  def safe_set_clipboard(text: str, retries: int = 5, delay: float = 0.05) -> bool:
      for i in range(retries):
          try:
              import uiautomation as uia
              uia.SetClipboardText(text)
              if uia.GetClipboardText() == text:
                  return True
          except Exception:
              time.sleep(delay * (2 ** i))  # exponential backoff
      return False
  ```
  Only if this safe clipboard setter returns `False` after all retries should the code drop back to keystrokes.

### C. Preventing Dropped Characters During Slow Typing
* **The Bug**: `pyautogui.typewrite(text, interval=0.01)` is too fast for laggy windows, remote environments, or high CPU loads, resulting in dropped or reordered characters.
* **Proposed Mitigations**:
  1. **Increase default keystroke interval**: Increase the interval from `0.01` to a safer default like `0.04s` or `0.05s`.
  2. **Targeted SendKeys Simulation**: Where possible, use `ctrl.SendKeys(text)` instead of global `pyautogui.typewrite`. `SendKeys` injects keystrokes directly into the target control's message queue. We must escape UIA special characters (e.g., `+`, `^`, `%`, `~`, `(`, `)`, `{`, `}`) by wrapping them in curly braces (e.g., `ctrl.SendKeys(text.replace("+", "{+}").replace("^", "{^}"))`).
  3. **Verification & Speed Adjustments**: After typing, run `_verify_typed`. If it returns `False` (read-back text doesn't match), clear the field and retry with a slower speed (e.g., `interval=0.10s`) or retry the clipboard paste.

---

## 3. Analysis of Element Resolution Logic and Auto-Retry

### Current Element Resolution Behavior
In `app/widget/desktop_features.py`, `find_ui_element` immediately calls `find_ui_elements(query, app_hint, limit=1)`. This performs a single walk of the UIA tree. If the element is not found, it immediately returns `{"ok": False, "error": "..."}`.
This causes issues during page loads, animations, or modal transitions, where an element might take 100-500ms to appear.

### Proposed Auto-Retry Wait
To make element resolution resilient to rendering lag, we should integrate a retry loop directly into `_find_uia_control` and `find_ui_elements`:
* **Auto-Retry Design**:
  - If a query fails to match any controls on the first attempt, enter a retry loop.
  - Retrying should poll up to a total timeout of `2.0` seconds with a polling interval of `0.2` seconds (200ms).
  - On each retry iteration, refresh the root candidate windows (in case the target window was just created or focused).
* **Implementation Sketch**:
  ```python
  def _find_uia_control(query: str, app_hint: str = "", timeout: float = 2.0, interval: float = 0.2):
      deadline = time.time() + timeout
      while True:
          # Standard UIA walk and search logic
          ctrl, info = _execute_single_uia_search(query, app_hint)
          if ctrl is not None:
              return ctrl, info
          if time.time() >= deadline:
              break
          time.sleep(interval)
      return None, {"ok": False, "error": f"no UIA control matched '{query}' after {timeout}s"}
  ```
Integrating this retry mechanism inside the base resolution layer (`_find_uia_control`) ensures that all downstream operations (clicks, typing, checking) benefit automatically from the rendering tolerance.

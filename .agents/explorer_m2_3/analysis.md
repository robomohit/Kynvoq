# Codebase Analysis: Resilient UIA Click/Type Verification & Self-Healing (Milestone 2)

## 1. Executive Summary
This report details the analysis of the Windows UI Automation (UIA) click, typing, and element resolution logic in Orynn, focusing on `app/tools.py` and `app/widget/desktop_features.py`. We identify why click verification is permissive, how the clipboard and React frameworks introduce typing failures, and how element resolution can easily miss elements during UI transitions. We propose concrete, self-healing retry strategies to address these weaknesses.

---

## 2. Analysis of `uia_click` and Click Verification

### 2.1 Current Implementation & Verification
In `app/tools.py`, `uia_click` executes the following sequence:
1. **Pre-action Snapshot**: Calls `before = self._click_snapshot()` to capture:
   - The current foreground window (handle and title).
   - The set of all visible top-level windows.
2. **Action Execution**: Calls `res = invoke_ui_element(query, app)`. If UIA fails, it falls back immediately to OCR via `self._ocr_click_fallback(query, app)`.
3. **Post-action Verification**: Calls `verified = self._verify_clicked(before)`.
   - `_verify_clicked` waits `0.12s` to allow menus or dialogs to paint.
   - It takes a post-action snapshot `after = self._click_snapshot()`.
   - If a new top-level window appeared (`after["wins"] - before["wins"]` is non-empty) or the foreground window changed (`before["fg"] != after["fg"]`), it returns `True`.
   - Otherwise, it returns `None`.

### 2.2 Why it returns `ok=True` when verification fails
In `app/tools.py`, `uia_click` does the following:
```python
verified = self._verify_clicked(before)
data["verified"] = verified
...
return ToolResult(ok=True, output=f"Activated '{res.get('target')}' via {res.get('method')}{verdict}.{tok}", data=data)
```
Even if `verified` is `None` (which occurs if the click did not open a new window or change the active application), `uia_click` returns `ok=True`.
This design choice is explicitly documented in `_verify_clicked`:
> *"Never False: a click that produces no observable change is common and legitimate, so we annotate confidence rather than cry failure."*

Treating a `None` verification result as a failure would cause false positives (e.g., clicking a simple checkbox, text field, or non-navigational button does not change the active window, but is still a successful click). However, this leaves Orynn blind to cases where a click *actually* failed because:
- The target window was out of focus and swallowed the click (click-through protection).
- The element was obscured, virtualized, or off-screen.
- UIA interaction events were not registered by the application.

### 2.3 Proposed Self-Healing & Retry Mechanism
When a click is attempted but verification returns `None` (or if `invoke_ui_element` fails), we should trigger a hierarchical retry/alternative activation mechanism:

1. **Focusing the Window (Tier 1)**:
   - Identify the application window handle (HWND) using `_uia_root_candidates(app_hint)`.
   - Force focus on this window using `_activate_hwnd(hwnd)` before re-attempting the click. This bypasses OS-level click-through prevention.
2. **Scrolling into View (Tier 2)**:
   - If the element's bounding box is off-screen or virtualized, attempt to scroll the container or parent control using `ScrollItemPattern.ScrollIntoView()`.
   - If `ScrollItemPattern` is unsupported, send mouse wheel scroll events (`pyautogui.scroll`) centered on the application's client rect.
3. **OCR-based Coordinate Click (Tier 3)**:
   - If UIA verification fails or `invoke_ui_element` fails, execute an OCR scan (`ocr_find_in_app`) to find the element's text on screen, get its absolute screen coordinates, and execute a physical mouse click via `pyautogui.click`. This heals issues where UIA controls are covered, non-interactable, or visually present but structurally broken.

---

## 3. Analysis of `uia_type` and Typing/Clipboard Paste Logic

### 3.1 Current Implementation
`type_into_ui_element` in `app/widget/desktop_features.py` enters text using three tiers:
1. **Background SetValue (`_try_background_setvalue`)**: Attempts to set the text via UIA's `ValuePattern.SetValue`. This is silent and does not steal focus/mouse.
2. **Focus + Clipboard Paste**: If background setvalue fails (or is skipped/unsupported), it focuses the control, writes the text to the system clipboard (`uia.SetClipboardText(text)`), and sends `{Ctrl}v` to paste it.
3. **Keystroke Fallback**: If clipboard copy/paste fails, it types the text using `pyautogui.typewrite(text, interval=0.01)`.

### 3.2 React Event Listener Issues & Detection
* **The Problem**: Frameworks like React, Vue, and Angular listen for synthetic browser events (`change`, `input`) to keep their internal state synchronized with the DOM. Writing directly to a DOM node using `ValuePattern.SetValue` updates the DOM value but does **not** trigger these framework event listeners. This leaves the internal framework state empty. When Orynn submits the form (e.g. pressing Enter), the framework sends an empty payload, causing silent failures (e.g. messages not sending in Discord/Slack).
* **Detection & Mitigation**:
  1. **Application-level bypass**: If the target application process is a web browser (`chrome.exe`, `msedge.exe`, `firefox.exe`, etc.) or is in the `ELECTRON_EXES` set (Notion, Discord, Slack, VS Code, etc.), we should **skip** the background `SetValue` tier and go straight to focus + paste/typing, as these apps almost always run SPAs.
  2. **Framework Event Synchronization**: If `SetValue` is used, we can force event listeners to trigger by sending a minor keyboard event (such as a dummy space and backspace, or a right-arrow key) immediately after calling `SetValue`. This triggers the native `input`/`keydown` events, forcing React to sync the DOM value to its internal state.

### 3.3 Clipboard Access Blocked Errors
* **The Problem**: In Windows, clipboard access is exclusive. If a remote desktop agent, clipboard manager, or security program is holding the clipboard lock, calls to `SetClipboardText` or `GetClipboardText` will raise exceptions (e.g. `Access is denied`). The current code immediately fails the paste tier if *any* exception occurs during the initial clipboard write, falling back to slow keystrokes.
* **Detection & Mitigation**:
  Implement a safe, retrying clipboard wrapper with exponential backoff/delay (e.g. 5 attempts with 50ms intervals) to handle transient locking issues:
  ```python
  def safe_set_clipboard(text: str, max_retries: int = 5, delay: float = 0.05) -> bool:
      for i in range(max_retries):
          try:
              uia.SetClipboardText(text)
              if uia.GetClipboardText() == text:
                  return True
          except Exception:
              time.sleep(delay)
      return False
  ```

### 3.4 Preventing Dropped Characters During Slow Typing
* **The Problem**: When falling back to keystroke typing (`pyautogui.typewrite`), the interval is fixed at `0.01`s. On laggy virtual environments, remote desktops, or heavy applications, this is too fast and causes dropped or out-of-order characters.
* **Detection & Mitigation**:
  1. **UIA SendKeys Escaping**: Use UIA's `SendKeys` pattern instead of global `pyautogui` where possible, as it targets the control directly. However, we must escape special characters (e.g., `{`, `}`, `+`, `^`, `%`, `~`, `(`, `)`) in the typed string so they are not interpreted as modifiers:
     ```python
     def escape_uia_sendkeys(text: str) -> str:
         # Wrap special characters in braces
         special = ['{', '}', '[', ']', '(', ')', '+', '^', '%', '~']
         escaped = []
         for char in text:
             if char in special:
                 escaped.append(f"{{{char}}}")
             else:
                 escaped.append(char)
         return "".join(escaped)
     ```
  2. **Adaptive Typing Delays**: If using `pyautogui.typewrite`, check the system CPU load or lag, and scale the interval up (e.g., `0.05`s to `0.08`s) if characters were previously dropped.

---

## 4. Analysis of `find_ui_element` and Element Resolution

### 4.1 Current Resolution Logic
In `app/widget/desktop_features.py`, `find_ui_element` resolves a query immediately by calling:
```python
res = find_ui_elements(query, app_hint, limit=1)
```
If UIA is slow, or if the target window is still rendering, opening, or performing a transition, the element will not be found on the first tree walk. In this case, `find_ui_element` immediately returns a failure (`{"ok": False}`), leading to an immediate fallback or tool error.

### 4.2 Introducing Auto-Retry Waits
To resolve this, we can wrap the element lookup in an auto-retry loop inside `find_ui_elements` (and `_find_uia_control` since it is also used for live control resolution):
- **Parameters**: `timeout: float = 2.0`, `interval: float = 0.2` (polling every 200ms).
- **Behavior**: If the UIA tree walk returns no matches, sleep for `interval` and retry until `timeout` is exceeded.

### 4.3 Double-Waiting Caveat (Anti-Regression)
`wait_for_ui_element` already polls `find_ui_element` in a loop:
```python
while time.time() < deadline:
    res = find_ui_element(query, app_hint)
    if res.get("ok"):
        return res
    time.sleep(interval)
```
If `find_ui_element` blocks for `2.0s` on failure, `wait_for_ui_element` will take `2.0s` to complete its first iteration instead of polling quickly. This causes massive slowdowns.
* **Solution**: Keep `timeout=0.0` as the default in `find_ui_elements` and `find_ui_element`. Pass `timeout=0.0` explicitly inside `wait_for_ui_element`. Set `timeout=2.0` only when calling `find_ui_element` from direct action commands like `click_ui_element` and `type_into_ui_element`.

---

## 5. Proposed Code Diffs & Implementation Plan

### 5.1 Element Resolution Retry
Modify `find_ui_elements` and `_find_uia_control` in `app/widget/desktop_features.py` to support `timeout` and `interval` parameters:

```python
def find_ui_elements(query: str, app_hint: str = "",
                      limit: int = 5, timeout: float = 0.0, interval: float = 0.2) -> dict:
    import time
    deadline = time.time() + timeout
    while True:
        try:
            # [Existing find_ui_elements logic goes here]
            # ...
            if items:
                return {"ok": True, "items": items}
        except Exception as exc:
            if time.time() >= deadline:
                return {"ok": False, "error": str(exc)}
        
        if time.time() >= deadline:
            break
        time.sleep(interval)
        
    return {"ok": False, "error": _miss_error(query, app_hint, roots, hint_matched)}
```

### 5.2 React Event Bypass and Clipboard Retries
Modify `type_into_ui_element` in `app/widget/desktop_features.py`:

```python
def type_into_ui_element(query: str, text: str, app_hint: str = "",
                          clear_first: bool = False,
                          submit: bool = False, timeout: float = 2.0) -> dict:
    
    # 1. Skip SetValue for React/Electron and browsers
    is_react_or_browser = False
    if app_hint:
        is_react_or_browser = is_electron_app(app_hint) or any(
            b in app_hint.lower() for b in ["chrome", "edge", "firefox", "browser"]
        )
    
    # Check if control is inside a browser/Electron process
    ctrl, info = _find_uia_control(query, app_hint, timeout=timeout)
    if ctrl is None:
        return info
    
    # Check if we should skip SetValue
    control_type = str(info.get("control_type") or "")
    use_background = (
        not submit 
        and control_type != "DocumentControl" 
        and not is_react_or_browser
    )
    
    if use_background:
        bg = _try_background_setvalue(ctrl, text, clear_first)
        if bg:
            return {"ok": True, "method": "setvalue-background", ...}
            
    # 2. Retrying clipboard write
    # [Implementation of retrying clipboard writes and reads to prevent locked-errors]
    # ...
```

### 5.3 Click Self-Healing
Modify `uia_click` in `app/tools.py` to trigger retries and alternative activation on failure:

```python
    def uia_click(self, query: str, app: str = ""):
        # 1. Initial attempt
        before = self._click_snapshot()
        res = invoke_ui_element(query, app)
        
        # 2. If initial UIA click fails or verification is uncertain, try self-healing
        verified = False
        if res.get("ok"):
            verified = self._verify_clicked(before)
            
        if not res.get("ok") or not verified:
            # Self-healing Tier 1: Focus application window and retry
            roots = _uia_root_candidates(app)
            if roots and roots[0]:
                hwnd = roots[0].NativeWindowHandle
                if hwnd:
                    self._activate_hwnd(hwnd)
                    time.sleep(0.2)
                    res = invoke_ui_element(query, app)
                    if res.get("ok"):
                        verified = self._verify_clicked(before)

        if not res.get("ok") or not verified:
            # Self-healing Tier 2: Fall back to OCR-based coordinate click
            ocr_result = self._ocr_click_fallback(query, app)
            if ocr_result is not None:
                return ocr_result
                
        # [Existing failure/success reporting logic]
        # ...
```

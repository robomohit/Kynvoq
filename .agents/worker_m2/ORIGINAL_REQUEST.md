## 2026-06-17T18:48:24-07:00
You are a versatile worker with loadable domain expertise. Your working directory is: c:\Users\ACER\Desktop\Ai_computer\Orynn\.agents\worker_m2. Your identity is worker_m2.
Your objective is to implement the resilient UIA Click & Type verification and self-healing (R2 specifications).
Files to edit:
- app/tools.py
- app/widget/desktop_features.py

Please implement the following:
1. **`uia_click` verification and self-healing** in `app/tools.py`:
   - Modify `uia_click` so that if `verified = self._verify_clicked(before)` is not `True` (meaning it evaluated to `None` or `False`):
     - Try window focus: retrieve roots using `_uia_root_candidates(app)`. If roots are found, call `self._activate_hwnd(roots[0].NativeWindowHandle)` to ensure the window is focused.
     - Try scrolling the control into view: find the control using `_find_uia_control(query, app)`. If found, check if it supports `ScrollItemPattern` and call its `ScrollIntoView()` method.
     - Retry the click: re-run `res_retry = invoke_ui_element(query, app)`.
     - Re-run verification: `verified = self._verify_clicked(before_retry)`.
     - If still not verified, fall back to OCR-based coordinate click: run `ocr_result = self._ocr_click_fallback(query, app)`. If that returns a `ToolResult`, return it.
     - If verification still fails, return a `ToolResult(ok=False, ...)` (rather than `ok=True`). Note: do not fail on legitimate clicks that do not change window focus or open new windows (such as clicking calculator buttons) unless you can explicitly verify a failure. In particular, if `verified` is still `None` (inconclusive), you can allow `ok=True`, but if verification explicitly failed or returned `False` or if we have control-specific verification (e.g. checking ToggleState/Value before and after and finding no change), return `ok=False`.
2. **`uia_type` desync & clipboard paste resilience** in `app/widget/desktop_features.py`:
   - Bypassing background SetValue (Tier 0) for React/Electron apps: inspect the root window's class name. If `roots` has elements and `roots[0].ClassName == "Chrome_WidgetWin_1"`, set `is_chrome_or_electron = True`. If `is_chrome_or_electron` is True, bypass the background `SetValue` tier (Tier 0) entirely and force the focus + paste/keystroke fallback path.
   - Clipboard access resilience: wrap the clipboard operations `saved = uia.GetClipboardText()`, `uia.SetClipboardText(text)`, and restoring of the clipboard in retry loops with exponential backoff (e.g., retrying up to 5 times with `time.sleep(0.05)` on `pywintypes.error` or standard clipboard exceptions).
   - Keystroke character dropping: update the keystroke fallback typing `pyautogui.typewrite(text, interval=0.01)` to `pyautogui.typewrite(text, interval=0.05)`.
3. **UIA Element Resolution Auto-Retry** in `app/widget/desktop_features.py`:
   - Modify `_find_uia_control(query, app_hint)` to support a `timeout: float = 2.0` parameter (default 2.0). Implement a retry/polling loop inside it that retries the UIA roots lookup and walk every 200ms until the control is found or the timeout expires.
   - Modify `find_ui_elements(query, app_hint, limit=5)` to support a `timeout: float = 2.0` parameter (default 2.0). Implement a retry loop that retries the roots lookup and search every 200ms until at least one item is found or the timeout expires.
   - Modify `find_ui_element` signature to `find_ui_element(query, app_hint, timeout=2.0)` and pass `timeout` to `find_ui_elements`.
   - Update `wait_for_ui_element` to call `find_ui_element(query, app_hint, timeout=0.0)` to prevent nested retry delays.

Run the test suite using `pytest` to make sure existing and new tests pass, and document your results.
Write a handoff report to `c:\Users\ACER\Desktop\Ai_computer\Orynn\.agents\worker_m2\handoff.md` summarizing the changes, files edited, and test execution details.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

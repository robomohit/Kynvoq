# Detailed Implementation Plan: Resilient UIA Click & Type verification and self-healing (R2)

## 1. uia_click verification and self-healing (in `app/tools.py`)
- Enhance `_verify_clicked` to return `True` if click succeeded, `False` if we know it failed, or `None` if inconclusive.
- In `uia_click`, if `verified` is not `True` (evaluates to `None` or `False`):
  1. Retrieve roots using `_uia_root_candidates(app)`. If roots are found, call `self._activate_hwnd(roots[0].NativeWindowHandle)` to ensure the application window is focused.
  2. Find the control using `_find_uia_control(query, app)`. If found, try to scroll it into view via `ScrollItemPattern` if supported:
     ```python
     sip = _uia_pattern(ctrl, "ScrollItemPattern")
     if sip is not None:
         sip.ScrollIntoView()
     ```
  3. Re-run `res_retry = invoke_ui_element(query, app)`.
  4. Run verification again `verified = self._verify_clicked(before_retry)`.
  5. If `verified` is still not `True`, invoke OCR fallback: `ocr_result = self._ocr_click_fallback(query, app)`. If that succeeds, return it.
  6. If all retries fail, return `ToolResult(ok=False, ...)` or raise error instead of returning `ok=True` for a failed/unverified click.

## 2. uia_type desync & clipboard paste issues (in `app/widget/desktop_features.py`)
- **React/Electron Desync**:
  - Skip background SetValue (Tier 0) if the window is a Chrome/Electron widget. Check this by inspecting the root window's ClassName:
    ```python
    roots = _uia_root_candidates(app_hint)
    is_chrome_or_electron = False
    if roots:
        try:
            is_chrome_or_electron = roots[0].ClassName == "Chrome_WidgetWin_1"
        except Exception:
            pass
    ```
    If `is_chrome_or_electron` is True, do not attempt `ValuePattern.SetValue` (Tier 0), forcing focus + paste.
- **Clipboard Blocked**:
  - Wrap clipboard operations (`uia.SetClipboardText`, `uia.GetClipboardText`) in retry loops with exponential backoff (e.g., up to 5 retries, sleeping 0.05s between retries).
- **Keystroke Character Dropping**:
  - Increase the keystroke fallback typing `pyautogui.typewrite(text, interval=0.01)` to `pyautogui.typewrite(text, interval=0.05)`.

## 3. Element Resolution Auto-Retry (in `app/widget/desktop_features.py`)
- Modify `_find_uia_control` to take `timeout: float = 2.0` and poll at 200ms intervals until the control is found or the timeout expires.
- Modify `find_ui_elements` to take `timeout: float = 2.0` and poll at 200ms intervals if no items are found initially.
- Update `find_ui_element` to take `timeout: float = 2.0`.
- Update `wait_for_ui_element` to pass `timeout=0.0` to `find_ui_element` to avoid nested retry waits.

## 4. Verification & Testing
- Write automated tests in `tests/test_computer_control_regressions.py` or a new test file to verify the clipboard retry loop, element resolution retry loop, and `uia_click` verification/healing.
- Run the entire test suite to ensure no regressions.

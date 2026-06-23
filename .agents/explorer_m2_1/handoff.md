# Handoff - explorer_m2_1

## 1. Observation
The following implementation details were observed in the codebase:
- **`uia_click` Verification**:
  - File: `app/tools.py` (lines 3730-3783)
  - The click executes: `res = invoke_ui_element(query, app)`
  - Verification: `verified = self._verify_clicked(before)` (lines 3777)
  - Return behavior: Always returns `ToolResult(ok=True, ...)` regardless of whether `verified` is `True` or `None`.
  - File: `app/tools.py` (lines 3308-3325):
    ```python
    def _verify_clicked(self, before: dict):
        """True if the click visibly changed UI state (a menu/dialog appeared or
        the foreground window changed), None if we can't tell. Never False: a
        click that produces no observable change is common and legitimate, so we
        annotate confidence rather than cry failure."""
    ```
- **`uia_type` Logic**:
  - File: `app/widget/desktop_features.py` (lines 1630-1770) in `type_into_ui_element`.
  - It runs four tiers:
    - Tier 0: `ValuePattern.SetValue` background write.
    - Tier 1: Target focusing (`SetFocus` or mouse click).
    - Tier 2: Clipboard paste via `SetClipboardText(text)` and `Ctrl+V`.
    - Tier 3: Keystroke fallback typing via `pyautogui.typewrite(text, interval=0.01)`.
  - React/Electron desync: `SetValue` is bypassed only if `submit` is True or control type is `DocumentControl` (lines 1668-1669).
  - Clipboard lock vulnerability (lines 1720-1747): Any exception in `SetClipboardText` immediately sets `pasted_ok = False`, falling back to keystroke typing with no retry.
- **Element Resolution**:
  - File: `app/widget/desktop_features.py` (lines 1288-1378) in `_find_uia_control`.
  - Performs a single walk of the UIA tree. If the target element is not found, it immediately returns `None, {"ok": False, "error": ...}`.

---

## 2. Logic Chain
- **Click Failure Reporting**: Since `_verify_clicked` returns `None` on no observable top-level window change, and `uia_click` ignores this (returning `ok=True`), silent failures (e.g. clicks dropped by background apps) are never reported or retried.
- **Self-Healing Clicks**: To fix this, when verification fails or is inconclusive, the agent should:
  1. Call `_activate_hwnd` to force window focus.
  2. Call `ScrollIntoView` on the control to ensure it is not obscured.
  3. Retry the click using coordinate-click or OCR-based click.
- **React desync**: `ValuePattern.SetValue` updates DOM properties but does not dispatch DOM events (`change`/`input`). Since browsers and Electron apps (like Discord) rely on these events, we should completely skip Tier 0 (`SetValue`) when target apps are browser-based or Electron-based, forcing the focus-and-paste tier.
- **Clipboard access**: Clipboard locked errors can be resolved by wrapping clipboard calls in a retry loop with exponential backoff (e.g., retrying up to 5 times over 500ms) rather than instantly failing.
- **Dropped characters**: Keystroke typing drops characters at a `0.01s` interval on laggy systems. To prevent this, we should increase the default typing interval to a safe level (`0.04-0.05s`), utilize targeted UIA `ctrl.SendKeys(text)` (with properly escaped special characters), and verify read-back values with `_verify_typed`.
- **Element Resolution wait**: Because `_find_uia_control` performs a single immediate walk, it fails if an element takes 100-200ms to render. Introducing a retry loop polling up to `2.0` seconds at `200ms` intervals inside `_find_uia_control` will handle rendering delays transparently.

---

## 3. Caveats
- No changes were made to the codebase, in accordance with the read-only exploration constraint.
- Windows OCR is assumed to be available for OCR fallback coordinates.
- Testing focused exclusively on local files; external resources/services were not queried.

---

## 4. Conclusion
We have mapped the entire implementation path for Milestone 2:
1. **`uia_click` self-healing**: Add click retries with window focusing, scrolling, and OCR click fallback on verification failures.
2. **`uia_type` resilience**: Bypass background SetValue for Electron/browsers, wrap clipboard logic in a safe retry loop, use a typing delay of 0.05s or UIA `SendKeys` for keystroke fallback, and utilize post-typing readback verification.
3. **`_find_uia_control` resilience**: Add an auto-retry wait of up to 2 seconds with 200ms intervals.

---

## 5. Verification Method
- **Inspection**: View files `app/tools.py` and `app/widget/desktop_features.py` to confirm function boundaries and structure.
- **Test execution**: Run `pytest tests/test_hybrid_resolver.py` and `pytest tests/test_adaptive_windows.py` to ensure changes do not break baseline expectations.
- **Validation**: Ensure that after implementing changes, browser inputs do not experience React state desync, and laggy elements are resolved within 2 seconds.

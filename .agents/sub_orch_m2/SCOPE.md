# Scope: Milestone 2 - Resilient UIA Click/Type Verification & Self-Healing (R2)

## Architecture
- Targets: `app/tools.py` and `app/widget/desktop_features.py`
- Problem:
  - `uia_click` returns `ToolResult(ok=True)` even if `verified` is False (silent click failure).
  - `uia_type` ValuePattern SetValue fails to trigger React event listeners, clipboard paste can fail, slow typing drops characters.
- Solution:
  - If `uia_click` verification fails, retry alternative activation (focusing window, scrolling, or falling back to OCR-based coordinate click).
  - If clipboard access is blocked during `uia_type`, retry clipboard access with delays.
  - Introduce brief auto-retry waits (up to 1-2s with 200ms intervals) in UIA element resolution (`find_ui_element`).

## Verification
- Unit/integration tests with mock/simulated UIA elements and apps.

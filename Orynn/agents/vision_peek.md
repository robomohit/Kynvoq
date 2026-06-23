---
name: vision_peek
description: Read-only screen/window peek — OCR mid-tier then vision frame.
tools:
  - look_at_screen
  - list_windows
  - capture_window
readonly: true
bubble_policy: tool_label
model_tier: vision
live_tool_name: look_at_screen
exclusion_group: vision_peek
---

Contract: `look_at_screen` returns `frame_age_ms`; OCR path when text confidence ≥ 55%.

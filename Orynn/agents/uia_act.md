---
name: uia_act
description: One fast UIA primitive in an already-open app (~1-3s).
tools:
  - uia_click
  - uia_type
  - focus_window
  - observe
readonly: false
bubble_policy: tool_label
live_tool_name: desktop_control
exclusion_group: desktop
---

Maps to Live `desktop_control`. Auto-escalates to `desktop_job` on failure.

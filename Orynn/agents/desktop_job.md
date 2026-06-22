---
name: desktop_job
description: Full multi-step desktop agent running in the background.
tools:
  - start_desktop_task
readonly: false
is_background: true
bubble_policy: mute
live_tool_name: start_desktop_task
exclusion_group: desktop
---

Terminal outcomes use `HandoffResult.user_message` via `send_task_update`; bubble mutes `task_result` churn under Live.

"""SpecialistSpec registry — single source for Live tool routing (WS2)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

BubblePolicy = Literal["user_message_only", "tool_label", "mute"]
ModelTier = Literal["live", "uia", "vision"]


@dataclass(frozen=True)
class SpecialistSpec:
    name: str
    description: str
    tools: tuple[str, ...]
    live_tool_name: str
    readonly: bool = False
    is_background: bool = False
    bubble_policy: BubblePolicy = "tool_label"
    model_tier: ModelTier = "live"
    exclusion_group: str = ""


# Mutual-exclusion groups: at most one tool per group per model turn.
EXCLUSION_GROUPS: dict[str, frozenset[str]] = {
    "desktop": frozenset({
        "desktop_control", "start_desktop_task", "launch_app", "dictate_text",
    }),
    "vision_peek": frozenset({"look_at_screen", "capture_window"}),
}


def exclusion_groups_for_tool(tool_name: str) -> list[str]:
    groups = []
    for group, tools in EXCLUSION_GROUPS.items():
        if tool_name in tools:
            groups.append(group)
    return groups


def builtin_specialists() -> list[SpecialistSpec]:
    return [
        SpecialistSpec(
            name="launch",
            description="Open or switch to an app via registry/resolver with verify.",
            tools=("resolve_launch_target", "open_known_app", "wait_for_window"),
            live_tool_name="launch_app",
            readonly=False,
            bubble_policy="user_message_only",
        ),
        SpecialistSpec(
            name="uia_act",
            description="One fast UIA action in an already-open app (~1-3s).",
            tools=("uia_click", "uia_type", "focus_window", "observe"),
            live_tool_name="desktop_control",
            readonly=False,
            exclusion_group="desktop",
        ),
        SpecialistSpec(
            name="vision_peek",
            description="Read-only screen/window peek via vision or OCR.",
            tools=("look_at_screen", "list_windows", "capture_window"),
            live_tool_name="look_at_screen",
            readonly=True,
            model_tier="vision",
            exclusion_group="vision_peek",
        ),
        SpecialistSpec(
            name="desktop_job",
            description="Full multi-step desktop agent (background).",
            tools=("start_desktop_task",),
            live_tool_name="start_desktop_task",
            is_background=True,
            bubble_policy="mute",
            exclusion_group="desktop",
        ),
        SpecialistSpec(
            name="terminal",
            description="Single shell command.",
            tools=("run_terminal",),
            live_tool_name="run_terminal",
            readonly=False,
        ),
        SpecialistSpec(
            name="web",
            description="Web search for live facts.",
            tools=("web_search",),
            live_tool_name="web_search",
            readonly=True,
        ),
    ]


def specialist_by_live_tool(tool_name: str) -> SpecialistSpec | None:
    for spec in builtin_specialists():
        if spec.live_tool_name == tool_name:
            return spec
    return None

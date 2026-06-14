from __future__ import annotations

import os
import json
import sys
from pathlib import Path

from app.models import ToolResult
import scripts.adaptive_windows_canary as canary


def test_summarize_results_reports_failed_canaries():
    results = [
        {"name": "notepad", "ok": True, "duration_s": 1.25},
        {"name": "calculator", "ok": False, "duration_s": 2.0},
    ]

    summary = canary.summarize_results(results)

    assert summary == {
        "ok": False,
        "total": 2,
        "passed": 1,
        "failed": 1,
        "failed_canaries": ["calculator"],
        "duration_s": 3.25,
    }


def test_run_canaries_marks_unknown_canary_failed(tmp_path):
    report = canary.run_canaries(["unknown"], tmp_path)

    assert report["summary"]["ok"] is False
    assert report["summary"]["failed_canaries"] == ["unknown"]
    assert report["results"][0]["failed_steps"] == ["unknown_canary"]


def test_run_canaries_uses_selected_runner(monkeypatch, tmp_path):
    calls = []
    seen_workspace_env = []

    def fake_notepad(workspace: Path):
        calls.append(workspace)
        seen_workspace_env.append(os.environ.get("ORYNN_WORKSPACE"))
        return {
            "name": "notepad",
            "ok": True,
            "duration_s": 0.5,
            "steps": [{"name": "map_notepad", "ok": True}],
            "failed_steps": [],
            "control_layers": ["Adaptive UIA map"],
            "affordance_maps": 1,
        }

    monkeypatch.setattr(canary, "run_notepad_canary", fake_notepad)
    monkeypatch.setenv("ORYNN_WORKSPACE", "original-workspace")

    report = canary.run_canaries(["notepad"], tmp_path)

    assert calls == [tmp_path]
    assert seen_workspace_env == [str(tmp_path)]
    assert os.environ.get("ORYNN_WORKSPACE") == "original-workspace"
    assert report["summary"]["ok"] is True
    assert report["results"][0]["affordance_maps"] == 1


def test_run_canaries_supports_hard_ui_runners(monkeypatch, tmp_path):
    def fake_settings(workspace: Path):
        return {
            "name": "settings",
            "ok": True,
            "duration_s": 0.2,
            "steps": [{"name": "map_settings", "ok": True}],
            "failed_steps": [],
            "control_layers": ["Adaptive UIA map"],
            "affordance_maps": 1,
        }

    def fake_discord(workspace: Path):
        return {
            "name": "discord",
            "ok": True,
            "duration_s": 0.3,
            "steps": [{"name": "map_discord", "ok": True}],
            "failed_steps": [],
            "control_layers": ["Adaptive UIA map"],
            "affordance_maps": 1,
        }

    def fake_custom_surface(workspace: Path):
        return {
            "name": "custom_surface",
            "ok": True,
            "duration_s": 0.4,
            "steps": [{"name": "map_custom_surface", "ok": True}],
            "failed_steps": [],
            "control_layers": ["Adaptive UIA map"],
            "affordance_maps": 1,
        }

    def fake_settings_to_notepad(workspace: Path):
        return {
            "name": "settings_to_notepad",
            "ok": True,
            "duration_s": 0.5,
            "steps": [{"name": "paste_version_into_notepad", "ok": True}],
            "failed_steps": [],
            "control_layers": ["Adaptive UIA map"],
            "affordance_maps": 2,
        }

    monkeypatch.setattr(canary, "run_settings_canary", fake_settings)
    monkeypatch.setattr(canary, "run_settings_to_notepad_canary", fake_settings_to_notepad)
    monkeypatch.setattr(canary, "run_discord_canary", fake_discord)
    monkeypatch.setattr(canary, "run_custom_surface_canary", fake_custom_surface)

    report = canary.run_canaries(["settings", "settings_to_notepad", "discord", "custom_surface"], tmp_path)

    assert report["summary"]["ok"] is True
    assert report["summary"]["passed"] == 4
    assert [result["name"] for result in report["results"]] == [
        "settings",
        "settings_to_notepad",
        "discord",
        "custom_surface",
    ]


def test_adaptive_map_step_redacts_control_labels():
    result = ToolResult(
        ok=True,
        output="Adaptive app map for Discord: text_input: 'secret channel'",
        data={
            "graph": {
                "app": "Discord",
                "control_count": 10,
                "named_control_count": 1,
                "controls": ["secret channel"],
                "groups": {"text_input": ["secret channel"]},
            },
            "runtime": {
                "runtime": "uia_sparse",
                "primary_layer": "uia_then_ocr",
                "confidence": 0.78,
            },
            "overlay": {"control_layer": "Adaptive UIA map"},
        },
    )

    step = canary._adaptive_map_step("map_discord", lambda: result)

    assert step["ok"] is True
    assert step["data"]["graph"]["named_control_count"] == 1
    assert step["data"]["runtime"]["runtime"] == "uia_sparse"
    assert "secret" not in json.dumps(step).lower()


def test_optional_window_probe_step_keeps_title_miss_diagnostic():
    result = ToolResult(ok=False, output="Timed out waiting for a visible window matching 'Discord'.")

    step = canary._optional_window_probe_step("wait_for_discord", lambda: result)

    assert step["ok"] is True
    assert step["diagnostic_ok"] is False
    assert "diagnostic window probe did not match" in step["output"]


def test_running_process_exe_falls_back_without_psutil(monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil", None)

    def fake_run(cmd, **kwargs):
        return canary.subprocess.CompletedProcess(
            cmd,
            0,
            stdout=r"C:\Users\mohit\AppData\Local\Discord\app-1.0.9240\Discord.exe" + "\n",
            stderr="",
        )

    monkeypatch.setattr(canary.subprocess, "run", fake_run)

    assert canary._running_process_exe("Discord.exe").endswith("Discord.exe")


def test_extract_settings_windows_spec_pairs_same_row_values():
    rows = [
        {"name": "Edition", "left": 100, "right": 160, "top": 200, "y": 210},
        {"name": "Windows 11 Home", "left": 520, "right": 680, "top": 200, "y": 210},
        {"name": "Version", "left": 100, "right": 160, "top": 230, "y": 240},
        {"name": "25H2", "left": 520, "right": 580, "top": 230, "y": 240},
        {"name": "OS build", "left": 100, "right": 175, "top": 260, "y": 270},
        {"name": "26200.8457", "left": 520, "right": 620, "top": 260, "y": 270},
        {"name": "Experience", "left": 100, "right": 190, "top": 290, "y": 300},
        {"name": "Windows Feature Experience Pack 1000.26100.304.0", "left": 520, "right": 900, "top": 290, "y": 300},
        {"name": "Product ID", "left": 100, "right": 190, "top": 320, "y": 330},
        {"name": "00342-00000-00000-AAOEM", "left": 520, "right": 760, "top": 320, "y": 330},
    ]

    specs = canary._extract_settings_windows_spec(rows)

    assert specs == {
        "Edition": "Windows 11 Home",
        "Version": "25H2",
        "OS build": "26200.8457",
        "Experience": "Windows Feature Experience Pack 1000.26100.304.0",
    }
    assert "Product ID" not in specs


def test_canary_result_flags_failed_steps():
    result = canary._canary_result(
        "demo",
        0.0,
        [
            {"name": "observe", "ok": True, "data": {"graph": {"controls": []}}},
            {"name": "act", "ok": False, "control_layer": "UIA miss"},
        ],
    )

    assert result["ok"] is False
    assert result["failed_steps"] == ["act"]
    assert result["affordance_maps"] == 1

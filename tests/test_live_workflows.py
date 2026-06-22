"""Live workflow execution: run saved multi-step workflows reliably, stop+report
honestly on a failed step, and gate disruptive ones behind spoken consent."""
import importlib
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _controller(tmp_path, monkeypatch):
    monkeypatch.setenv("ORYNN_WORKSPACE", str(tmp_path))
    import app.workflows as wf
    importlib.reload(wf)  # point the store at the temp workspace
    try:
        from PySide6.QtWidgets import QApplication
        from app.widget.textbox_overlay import OverlayController
    except Exception:
        pytest.skip("PySide6 not importable")
    QApplication.instance() or QApplication([])
    c = OverlayController(8000)
    monkeypatch.setattr(c, "_busy_response", lambda: None)  # never "busy" in tests
    return c, wf


def test_run_workflow_runs_in_order_and_stops_on_failure(tmp_path, monkeypatch):
    c, wf = _controller(tmp_path, monkeypatch)
    wf.add_workflow("Demo", steps=[
        {"action": "click", "target": "A"},
        {"action": "click", "target": "B"},
        {"action": "click", "target": "C"},
    ])
    ran = []

    def fake_step(step):
        ran.append(step.get("target"))
        return {"ok": step.get("target") != "C", "label": f"click {step.get('target')}"}

    monkeypatch.setattr(c, "_run_workflow_step", fake_step)

    res = c._live_run_workflow({"name": "Demo"})
    assert ran == ["A", "B", "C"]                 # ran in order, attempted C
    assert res["ok"] is False
    assert res["completed_steps"] == 2 and res["total"] == 3
    # honest: must not claim it finished
    assert "couldn't" in res["message"].lower() or "stopped" in res["message"].lower()


def test_run_workflow_full_success(tmp_path, monkeypatch):
    c, wf = _controller(tmp_path, monkeypatch)
    wf.add_workflow("Allgood", steps=[{"action": "click", "target": "X"},
                                      {"action": "type", "text": "hi"}])
    monkeypatch.setattr(c, "_run_workflow_step", lambda s: {"ok": True, "label": "ok"})
    res = c._live_run_workflow({"name": "Allgood"})
    assert res["ok"] is True and res["total"] == 2
    assert wf.get("allgood")["runs"] == 1          # run counter incremented


def test_run_workflow_unknown_name(tmp_path, monkeypatch):
    c, wf = _controller(tmp_path, monkeypatch)
    res = c._live_run_workflow({"name": "does-not-exist"})
    assert res["ok"] is False and "don't have" in res["message"].lower()


def test_run_workflow_disruptive_needs_consent(tmp_path, monkeypatch):
    c, wf = _controller(tmp_path, monkeypatch)
    wf.add_workflow("Sendit", steps=[
        {"action": "click", "target": "Compose"},
        {"action": "click", "target": "Send"},      # disruptive -> consent
    ])
    stepped = []
    monkeypatch.setattr(c, "_run_workflow_step",
                        lambda s: stepped.append(s) or {"ok": True, "label": "ok"})

    res = c._live_run_workflow({"name": "Sendit"})
    assert res.get("needs_consent") is True
    assert stepped == []                            # nothing ran before consent

    # With a spoken yes it proceeds.
    res2 = c._live_run_workflow({"name": "Sendit", "confirmed": True})
    assert res2["ok"] is True and len(stepped) == 2


def test_save_workflow_via_live_tool(tmp_path, monkeypatch):
    c, wf = _controller(tmp_path, monkeypatch)
    res = c._live_tool("save_workflow", {
        "name": "Quick Note",
        "steps": [{"action": "open", "app": "Notepad"}, {"action": "type", "text": "hi"}],
    })
    assert res["ok"] is True and res["steps"] == 2
    assert wf.get("Quick Note") is not None

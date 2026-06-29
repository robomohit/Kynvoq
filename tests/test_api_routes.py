"""Tests for new API routes: /api/workflows and active_skills preference.

Uses FastAPI's TestClient — no real HTTP, no browser needed.
"""
import importlib
import pytest


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_client(tmp_path, monkeypatch):
    """Return a TestClient with a fresh temp workspace so tests don't share state."""
    monkeypatch.setenv("ORYNN_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("APP_SECRET", "test-secret")
    monkeypatch.setenv("SESSION_TOKEN", "test-token")

    import app.workflows as wf_mod
    importlib.reload(wf_mod)
    import app.preferences as pref_mod
    importlib.reload(pref_mod)
    import app.main as main_mod
    importlib.reload(main_mod)

    from fastapi.testclient import TestClient
    client = TestClient(main_mod.app, raise_server_exceptions=True)
    # Establish a session so verify_token passes.
    client.post("/api/session")
    return client, main_mod


STEPS = [
    {"action": "open", "app": "Chrome"},
    {"action": "type", "text": "hello", "app": "Chrome"},
]


# ── /api/workflows GET ────────────────────────────────────────────────────────

def test_get_workflows_returns_list_type(tmp_path, monkeypatch):
    """GET /api/workflows always returns a list, even when empty."""
    client, _ = _make_client(tmp_path, monkeypatch)
    r = client.get("/api/workflows")
    assert r.status_code == 200
    assert isinstance(r.json()["workflows"], list)


def test_get_workflows_returns_list(tmp_path, monkeypatch):
    # Populate workflows via the API itself so state is consistent.
    client, _ = _make_client(tmp_path, monkeypatch)
    client.post("/api/workflows", json={
        "name": "Morning Setup", "description": "open my apps",
        "triggers": ["morning"], "steps": STEPS,
    })
    r = client.get("/api/workflows")
    assert r.status_code == 200
    data = r.json()
    assert len(data["workflows"]) >= 1
    names = [w.get("name") or w.get("title") for w in data["workflows"]]
    assert any("morning" in (n or "").lower() for n in names)


def test_get_workflows_query_filter(tmp_path, monkeypatch):
    client, _ = _make_client(tmp_path, monkeypatch)
    client.post("/api/workflows", json={"name": "Morning Setup", "triggers": ["morning", "start"], "steps": STEPS})
    client.post("/api/workflows", json={"name": "Pay Rent", "triggers": ["rent"], "steps": STEPS})

    r = client.get("/api/workflows?q=morning")
    assert r.status_code == 200
    results = r.json()["workflows"]
    assert any("morning" in (w.get("name") or "").lower() for w in results)


# ── /api/workflows POST ───────────────────────────────────────────────────────

def test_post_workflow_saves(tmp_path, monkeypatch):
    client, _ = _make_client(tmp_path, monkeypatch)
    r = client.post("/api/workflows", json={
        "name": "Test WF",
        "description": "a test",
        "triggers": ["test it"],
        "steps": STEPS,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["workflow"]["name"] == "test-wf"


def test_post_workflow_rejects_empty_steps(tmp_path, monkeypatch):
    client, _ = _make_client(tmp_path, monkeypatch)
    r = client.post("/api/workflows", json={"name": "Bad", "steps": []})
    assert r.status_code == 400


# ── /api/workflows DELETE ─────────────────────────────────────────────────────

def test_delete_workflow_removes_it(tmp_path, monkeypatch):
    client, _ = _make_client(tmp_path, monkeypatch)
    client.post("/api/workflows", json={"name": "To Delete", "steps": STEPS})

    r = client.delete("/api/workflows/to-delete")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    r2 = client.get("/api/workflows")
    wfs = r2.json()["workflows"]
    assert all((w.get("name") or "") != "to-delete" for w in wfs)


def test_delete_workflow_404_for_missing(tmp_path, monkeypatch):
    client, _ = _make_client(tmp_path, monkeypatch)
    r = client.delete("/api/workflows/nonexistent-workflow-xyz")
    assert r.status_code == 404


# ── active_skills preference persistence ─────────────────────────────────────

def test_active_skills_persists_via_preferences(tmp_path, monkeypatch):
    import app.preferences as P
    importlib.reload(P)
    monkeypatch.setattr(P, "store_path", lambda: tmp_path / "preferences.json")

    # Default is empty list.
    assert P.get_all()["active_skills"] == []

    # Save a list of skill IDs.
    P.update({"active_skills": ["python", "web-search"]})
    assert P.get_all()["active_skills"] == ["python", "web-search"]


def test_active_skills_coerced_to_list(tmp_path, monkeypatch):
    import app.preferences as P
    importlib.reload(P)
    monkeypatch.setattr(P, "store_path", lambda: tmp_path / "preferences.json")

    # Non-list values fall back to default (empty list).
    P.update({"active_skills": "not-a-list"})
    assert P.get_all()["active_skills"] == []


def test_first_live_run_removed_from_defaults(tmp_path, monkeypatch):
    import app.preferences as P
    importlib.reload(P)
    assert "first_live_run" not in P.DEFAULTS
